import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test.beforeEach(async ({ request }) => {
  const settings = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: settings.revision, draft: {} },
  })).ok()).toBe(true);
});

test("Dataset builds, persists and exports a trigger-ready batch", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Build a prompt dataset." })).toBeVisible();
  await page.getByText("Training trigger & controls", { exact: true }).click();
  await page.getByLabel("Trigger text or terms").fill("ohwx_person");
  await page.getByLabel("Dataset idea", { exact: true }).fill(
    "A woman with short black hair, green eyes, and a fitted red jacket.",
  );
  await page.getByLabel("Number of prompts").selectOption("3");
  await page.getByLabel("Visual style").selectOption("Anime / manga");
  await page.getByLabel(/Provide my own scene ideas/).check();
  await page.getByLabel("Guided dataset inputs").fill(
    "standing portrait in a city at night\nrunning through a sunlit field",
  );
  await page.getByText("Advanced coverage planning (optional)").click();
  await page.getByLabel("Use coverage plan").check();
  await page.getByRole("button", { name: "Create plan" }).click();
  const planner = page.getByRole("region", { name: "Coverage planner" });
  await expect(planner.getByRole("row")).toHaveCount(4);
  await expect(planner.getByText("standing portrait in a city at night", { exact: true })).toHaveCount(2);
  await expect(planner.getByText("standing portrait in a city at night", { exact: true }).first()).toBeVisible();
  await expect(planner.getByText("running through a sunlit field", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Generate 3 prompts" }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/ohwx_person/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/standing portrait/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/running through/);
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/standing portrait/);
  await expect(page.getByRole("button", { name: "TXT", exact: true })).toBeEnabled();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSONL", exact: true }).click();
  const exported = (await readFile(await (await downloaded).path(), "utf8")).split("\n").map(JSON.parse);
  expect(exported[0].scene).toContain("standing portrait");
  expect(exported[0].idea).toContain("standing portrait");
  expect(exported[0].index).toBe(1);
  const quality = page.getByRole("region", { name: "Dataset quality report" });
  await expect(quality.getByText("Overall", { exact: true })).toBeVisible();
  await expect(quality.getByText(/Prompt checks · \d\/3 passed/)).toBeVisible();
  await expect(quality.getByRole("button", { name: "Deep consistency review" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByText("Dataset settings: Saved")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/ohwx_person/);
  await page.getByText("Advanced coverage planning (optional)", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Coverage planner" }).getByRole("row")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "Dataset quality report" }).getByText("Overall", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Dataset shows background prompt-engine failures in its own view", async ({ page }) => {
  const now = Date.now() / 1000;
  await page.route("**/api/workspace/dataset", (route) => route.fulfill({
    status: 202,
    json: {
      id: "failed-dataset-job", status: "running", revision: 0, kind: "dataset",
      created_at: now, finished_at: null, result: null, error: null,
      progress: "Starting the prompt engine for the dataset…", progress_at: now,
    },
  }));
  await page.route("**/api/jobs/failed-dataset-job", (route) => route.fulfill({
    status: 200,
    json: {
      id: "failed-dataset-job", status: "failed", revision: 1, kind: "dataset",
      created_at: now, finished_at: now + 1, result: null,
      error: "Model process exited unexpectedly.", progress: "Waiting for prompt engine · dataset prompt 1/12",
      progress_at: now, status_reason: "Model process exited unexpectedly.",
      llm_trace: {
        request_number: 1, status: "error", model: "test-model",
        messages: [{ role: "system", content: "Exact system instruction." },
          { role: "user", content: "Exact dataset request." }],
        parameters: { temperature: 0.3, stream: true }, output: "Partial model text",
        reasoning: "", issue: "Model process exited unexpectedly.", started_at: now,
        first_token_at: now + 0.2, updated_at: now + 1, finished_at: now + 1,
        finish_reason: null,
      },
      events: [
        { id: 1, timestamp: now, type: "status", message: "Job accepted." },
        { id: 2, timestamp: now + 0.5, type: "stage", message: "Waiting for prompt engine · dataset prompt 1/12" },
        { id: 3, timestamp: now + 1, type: "error", message: "Model process exited unexpectedly." },
      ],
    },
  }));

  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByText("Training trigger & controls", { exact: true }).click();
  await page.getByLabel("Trigger text or terms").fill("ohwx_person");
  await page.getByLabel("Dataset idea", { exact: true }).fill("A woman wearing a red jacket.");
  await page.getByRole("button", { name: "Generate 12 prompts" }).click();

  await expect(page.getByText(
    "Dataset generation failed. Model process exited unexpectedly.",
    { exact: true },
  )).toBeVisible();
  await page.getByRole("button", { name: "View LLM activity log" }).click();
  const log = page.getByRole("dialog", { name: "LLM activity log" });
  await expect(log).toBeVisible();
  const events = log.getByRole("list", { name: "LLM activity events" });
  await expect(log.getByText("Partial model text", { exact: true })).toBeVisible();
  await log.getByText("What the model is reading", { exact: true }).click();
  await expect(log.getByText("Exact system instruction.", { exact: true })).toBeVisible();
  await expect(events.getByText("Model process exited unexpectedly.", { exact: true })).toBeVisible();
  await expect(events.getByRole("listitem")).toHaveCount(3);
});

test("plan first, edit and persist ideas, reuse across targets, and invalidate semantic changes", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A woman doing funny stuff");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 2")).toHaveValue("A woman doing funny stuff");
  const scene = "She attempts a pancake flip and the pancake lands on her head, spatula still raised.";
  const idea = "Flipping a pancake onto her head";
  await expect(page.getByLabel("Planned idea 1")).toHaveValue("A woman doing funny stuff");
  await page.getByLabel("Planned idea 1").fill(idea);
  await page.getByLabel("Planned scene 1").fill(scene);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(before.scene_plan[0].scene).toBe(scene);
  expect(before.scene_plan[0].idea).toBe(idea);
  expect(before.results).toHaveLength(0);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(scene);
  await expect(page.getByLabel("Planned idea 1")).toHaveValue(idea);
  await page.getByText("Training trigger & controls", { exact: true }).click();
  await page.getByLabel("Trigger text or terms").fill("ohwx_woman");
  await page.getByLabel("Dataset target model").selectOption("Qwen Image");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate prompts from these scenes", exact: true }).click();
  const job = await (await accepted).json();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_woman/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const first = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(first.results[0].scene).toBe(scene);
  expect(first.results[0].idea).toBe(idea);
  await expect(page.getByRole("region", { name: "Dataset results" }).getByText(idea, { exact: true })).toBeVisible();
  expect(first.scene_plan_signature).toBe(before.scene_plan_signature);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.llm_trace.request_number).toBe(2); // two writers, no planner calls
  await page.getByLabel("Dataset target model").selectOption("Anima");
  await page.getByRole("button", { name: "Generate prompts from these scenes", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_woman/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const second = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(second.scene_plan).toEqual(first.scene_plan);
  expect(second.target).toBe("Anima");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("Dataset idea", { exact: true }).fill("A dog on small adventures");
  await expect(page.getByLabel("Planned scene 1")).toHaveCount(0);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const changed = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(changed.scene_plan).toEqual([]);
  expect(changed.scene_plan_signature).toBe("");
  expect(errors).toEqual([]);
});
