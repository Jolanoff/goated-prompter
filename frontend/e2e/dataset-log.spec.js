import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { confirmDatasetReview } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", { data: { revision: record.revision, draft: {} } })).ok()).toBe(true);
});

async function configure(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck confronting a dinosaur.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
}

async function exportLog(page, scope = page) {
  const download = page.waitForEvent("download");
  await scope.getByRole("button", { name: "Export generation log", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("dataset-generation-log.json");
  const text = await readFile(await file.path(), "utf8");
  expect(text).toMatch(/\n {2}"settings": \{/);
  expect(text).not.toContain('"confirmation_token"');
  return JSON.parse(text);
}

test("export downloads only on click, retains confirmed understanding, and does not save or release the generation", async ({ page, request }) => {
  const downloads = [];
  page.on("download", (download) => downloads.push(download));
  await configure(page);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await expect(page.getByRole("button", { name: "Generate 2 prompts", exact: true })).toBeEnabled();
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  expect(downloads).toHaveLength(0);
  const before = await (await request.get("/api/workspace/settings/dataset")).json();
  const writes = [];
  page.on("request", (event) => { if (event.method() !== "GET") writes.push(event.url()); });
  const log = await exportLog(page);
  expect(log.settings.amount).toBe(2);
  expect(log.dataset_idea).toBe("A duck confronting a dinosaur.");
  expect(log.scene_plan).toEqual(before.draft.scene_plan);
  expect(log.generated_prompts).toEqual(before.draft.results);
  expect(log.understanding.status).toBe("confirmed");
  expect(log.understanding.brief.requested_generation).toBe(log.dataset_idea);
  expect(log.job.id).toBe(before.draft.result_job_id);
  expect(log.job.status).toBe("succeeded");
  expect(log.job.llm_trace.request_number).toBeGreaterThan(0);
  expect((await request.get(`/api/jobs/${log.job.id}`)).ok()).toBe(true);
  expect(await (await request.get("/api/workspace/settings/dataset")).json()).toEqual(before);
  expect(writes).toEqual([]);
  expect(downloads).toHaveLength(1);
});

test("review export omits approval credentials and does not confirm the request", async ({ page }) => {
  await configure(page);
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request" });
  await expect(dialog.getByRole("button", { name: "Confirm and plan scenes" })).toBeEnabled();
  const writes = [];
  page.on("request", (event) => { if (event.method() !== "GET") writes.push(event.url()); });
  const log = await exportLog(page, dialog);
  expect(log.understanding.status).toBe("ready");
  expect(log.job.kind).toBe("dataset_understanding");
  expect(log.job.result.brief.requested_generation).toBe(log.dataset_idea);
  expect(log.scene_plan).toEqual([]);
  expect(writes).toEqual([]);
  await expect(dialog.getByRole("button", { name: "Confirm and plan scenes" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  const cancelled = await exportLog(page);
  expect(cancelled.understanding.status).toBe("cancelled");
  expect(cancelled.understanding.brief.requested_generation).toBe(log.dataset_idea);
});

test("active and failed generation exports include partial output, retries and redacted errors", async ({ page }) => {
  await configure(page);
  let failed = false;
  const job = { id: "debug-dataset-job", kind: "dataset", revision: 1, created_at: 1791374400,
    status: "running", progress: "Writing the second prompt", result: { completed: 1, attempts: 2 },
    llm_trace: { request_number: 3, status: "receiving", output: "Partial model text", parameters: { temperature: 0.4 },
      messages: [{ role: "user", content: "Accepted scene" }] }, events: [] };
  await page.route("**/api/workspace/dataset", (route) => route.fulfill({ status: 202, json: job }));
  await page.route("**/api/jobs/debug-dataset-job", (route) => route.fulfill({ json: failed ? { ...job, revision: 2,
    status: "failed", error: "Request timed out: api_key=inline-secret", finished_at: 1791374401,
    partial_responses: [{ partial_text: "Partial model text", completion_state: "timeout" }] } : job }));
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByRole("button", { name: "Generating 2 prompts…", exact: true })).toBeDisabled();
  await expect(page.getByRole("dialog", { name: "Review your Dataset request" })).not.toBeVisible();
  const activeLog = await exportLog(page);
  expect(activeLog.job.status).toBe("running");
  expect(activeLog.job.result.attempts).toBe(2);
  expect(activeLog.job.llm_trace.output).toBe("Partial model text");
  failed = true;
  await expect(page.getByRole("alert").filter({ hasText: "Dataset generation failed" })).toBeVisible();
  const failureLog = await exportLog(page);
  expect(failureLog.job.status).toBe("failed");
  expect(failureLog.job.error).toContain("[REDACTED]");
  expect(JSON.stringify(failureLog)).not.toContain("inline-secret");
  expect(failureLog.job.partial_responses[0].completion_state).toBe("timeout");
});
