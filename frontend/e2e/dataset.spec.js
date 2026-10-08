import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { confirmDatasetReview, analyzeDatasetRequest, generateDataset, openDatasetPage } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const settings = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: settings.revision, draft: {} },
  })).ok()).toBe(true);
});

async function openDataset(page, amount = "2") {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A craftsperson working with clay.");
  await page.getByLabel("Trigger text or terms").fill("saved_person");
  await page.getByLabel("Number of prompts").selectOption(amount);
}

async function settings(request) {
  return (await request.get("/api/workspace/settings/dataset")).json();
}

async function finish(request, id) {
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe("succeeded");
  return (await request.get(`/api/jobs/${id}`)).json();
}

async function submit(page, button, endpoint = "/api/workspace/dataset", reviewRequired = false) {
  await openDatasetPage(page, button.startsWith("Retry failed") ? "Dataset"
    : endpoint === "/api/workspace/dataset/scenes" ? "Configure" : "Scenes");
  if (endpoint === "/api/workspace/dataset/scenes") await page.getByLabel("Plan scenes first", { exact: true }).check();
  const accepted = page.waitForResponse((response) => response.url().endsWith(endpoint) && response.status() === 202);
  await page.getByRole("button", { name: button, exact: true }).first().click();
  if (reviewRequired || endpoint === "/api/workspace/dataset/scenes") await confirmDatasetReview(page);
  return accepted;
}

async function seedEditedDatasetBatch(request, planScenesFirst = true) {
  const initial = await settings(request);
  const input = { ...initial.draft, subject: "A craftsperson working with clay.", trigger: "saved_person", amount: 2,
    plan_scenes_first: planScenesFirst };
  const understood = await analyzeDatasetRequest(request, input);
  const accepted = await request.post("/api/workspace/dataset/scenes", {
    data: { input, confirmation_token: understood.confirmation_token },
  });
  expect(accepted.status()).toBe(202);
  await finish(request, (await accepted.json()).id);
  const saved = await settings(request);
  const draft = { ...saved.draft, result_job_id: "manually-edited-batch",
    results: saved.draft.scene_plan.map(({ index, input, idea, scene }) => ({ index, input, idea, scene,
      prompt: `saved_person: edited prompt ${index}; preserve (these words).\n  Deliberate spacing.`,
    })) };
  const stored = await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision, draft } });
  expect(stored.ok()).toBe(true);
  return (await stored.json()).draft;
}

test("backend completes and persists Dataset after the generating browser closes", async ({ page, context, browser, request }) => {
  await openDataset(page, "5");
  const job = await (await generateDataset(page, "5")).json();
  const appUrl = page.url();
  await context.close();
  await finish(request, job.id);
  const saved = await settings(request);
  expect(saved.draft.results).toHaveLength(5);
  expect(saved.checkpoint.job_id).toBe(job.id);
  const recovered = await browser.newContext();
  try {
    const newPage = await recovered.newPage();
    await newPage.goto(appUrl);
    await newPage.getByRole("button", { name: "Dataset", exact: true }).click();
    await openDatasetPage(newPage, "Dataset");
    await expect(newPage.getByLabel("Dataset prompt 5")).toHaveValue(/saved_person/);
  } finally { await recovered.close(); }
});

test("creativity persists and Builder receives the exact checked scene", async ({ page, request }) => {
  await openDataset(page, "1");
  await submit(page, "Generate 1 scene", "/api/workspace/dataset/scenes");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene 1/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await settings(request)).draft;
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Dataset descriptive creativity").selectOption("Dice");
  await expect.poll(async () => (await settings(request)).draft.creativity).toBe("Dice");
  const changed = (await settings(request)).draft;
  expect(changed.scene_plan).toEqual(before.scene_plan);
  expect(changed.scene_plan_signature).toBe(before.scene_plan_signature);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset descriptive creativity")).toHaveValue("Dice");
  await openDatasetPage(page, "Scenes");
  const refused = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 400);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await refused;
  const response = await submit(page, "Regenerate prompt", "/api/workspace/dataset/scene", true);
  expect(response.request().postDataJSON().input.creativity).toBe("Dice");
  const finished = await finish(request, (await response.json()).id);
  expect(finished.llm_trace.request_number).toBe(1);
  expect(finished.llm_trace.messages[1].content).toBe(before.scene_plan[0].scene);
  expect(finished.result.scene_plan[0].self_check).toBe("PASS");
});

test("prompt failure retries enhancement, not scene construction", async ({ page, request }) => {
  const draft = await seedEditedDatasetBatch(request);
  const saved = await settings(request);
  draft.results = draft.results.filter((row) => row.index !== 1);
  draft.scene_plan[0] = { ...draft.scene_plan[0], prompt_status: "failed", failure_stage: "prompt",
    failure_reason: "Enhancement disconnected; the scene is checked." };
  expect((await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision, draft } })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const response = await submit(page, "Retry failed prompt", "/api/workspace/dataset/scene");
  expect(response.request().postDataJSON().action).toBe("regenerate_prompt");
  const finished = await finish(request, (await response.json()).id);
  expect(finished.llm_trace.request_number).toBe(1);
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/saved_person/);
  expect(finished.result.prompts[1].prompt).toBe(draft.results[0].prompt);
});

test("writer-setting acknowledgements retain eligibility despite reordered JSON keys", async ({ page, request }) => {
  await openDataset(page, "1");
  await submit(page, "Generate 1 scene", "/api/workspace/dataset/scenes");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene 1/);
  await page.route("**/api/workspace/settings/dataset", async (route) => {
    const response = await route.fetch();
    if (route.request().method() !== "PUT") return route.fulfill({ response });
    const record = await response.json();
    record.draft.scene_plan = record.draft.scene_plan.map((row) => Object.fromEntries(Object.entries(row).reverse()));
    await route.fulfill({ response, json: record });
  });
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/workspace/settings/dataset") && response.request().method() === "PUT");
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Dataset prompt length").selectOption("Detailed");
  expect((await saved).ok()).toBe(true);
  await openDatasetPage(page, "Scenes");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  const checked = (await settings(request)).draft.scene_plan;
  const response = await submit(page, "Regenerate prompt", "/api/workspace/dataset/scene", true);
  expect(response.request().postDataJSON().input.scene_plan).toEqual(checked);
  await finish(request, (await response.json()).id);
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/saved_person/);
});

for (const [button, step, endpoint, confirmation] of [
  ["Generate 2 prompts", "Configure", "/api/workspace/dataset", "Confirm and generate prompts"],
  ["Continue", "Scenes", "/api/workspace/dataset", ""],
]) {
  for (const status of [400, 409, 503]) {
    test(`rejected regeneration preserves the edited batch via ${button} (${status})`, async ({ page, request }) => {
      const before = await seedEditedDatasetBatch(request, step === "Scenes");
      await page.goto("/");
      await page.getByRole("button", { name: "Dataset", exact: true }).click();
      await page.route(`**${endpoint}`, (route) => route.fulfill({ status, json: { error: "Generation admission unavailable." } }));
      await openDatasetPage(page, step);
      await page.getByRole("button", { name: button, exact: true }).click();
      if (confirmation) await confirmDatasetReview(page);
      await expect(page.getByText(/Generation admission unavailable/).first()).toBeVisible();
      expect((await settings(request)).draft).toEqual(before);
      await page.reload();
      await page.getByRole("button", { name: "Dataset", exact: true }).click();
      await openDatasetPage(page, "Dataset");
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(before.results[0].prompt);
      await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(before.results[1].prompt);
    });
  }

  test(`batch replacement waits for admission via ${button}`, async ({ page, request }) => {
    const before = await seedEditedDatasetBatch(request, step === "Scenes");
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    let releaseAdmission;
    const admissionGate = new Promise((resolve) => { releaseAdmission = resolve; });
    await page.route(`**${endpoint}`, async (route) => { await admissionGate; await route.continue(); });
    const submission = page.waitForRequest(`**${endpoint}`);
    const accepted = page.waitForResponse((response) => response.url().endsWith(endpoint) && response.status() === 202);
    try {
      await openDatasetPage(page, step);
      await page.getByRole("button", { name: button, exact: true }).click();
      if (confirmation) await confirmDatasetReview(page);
      expect((await submission).postDataJSON().input.results).toEqual(before.results);
      expect((await settings(request)).draft).toEqual(before);
      await expect(confirmation ? page.getByRole("dialog", { name: "Review your Dataset request" })
        .getByRole("button", { name: confirmation }) : page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
      releaseAdmission();
      const job = await (await accepted).json();
      await finish(request, job.id);
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/saved_person:.*mock scene 1/);
      const finished = (await settings(request)).draft;
      expect(finished.results.map((row) => row.index)).toEqual([1, 2]);
      expect(finished.result_job_id).toBe(job.id);
    } finally { releaseAdmission(); }
  });
}

test("accepted replacement survives a lost admission response", async ({ page, request }) => {
  const before = await seedEditedDatasetBatch(request, false);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  let admitted;
  const accepted = new Promise((resolve) => { admitted = resolve; });
  await page.route("**/api/workspace/dataset", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    admitted(await response.json());
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  const job = await accepted;
  await finish(request, job.id);
  const recovered = (await settings(request)).draft;
  expect(recovered.results).not.toEqual(before.results);
  expect(recovered.results).toHaveLength(2);
  expect(recovered.result_job_id).toBe(job.id);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(recovered.scene_plan[0].scene);
});

test("one idea call precedes ten independent scene/self-check calls", async ({ page, request }) => {
  await openDataset(page, "10");
  const response = await submit(page, "Generate 10 scenes", "/api/workspace/dataset/scenes");
  const finished = await finish(request, (await response.json()).id);
  expect(finished.llm_trace.request_number).toBe(11);
  expect(finished.result.scene_plan.map((row) => row.index)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  expect(finished.result.scene_plan.every((row) => row.self_check === "PASS" && !("geometry" in row))).toBe(true);
  await expect(page.getByLabel("Dataset planning mode")).toHaveCount(0);
});

test("REPAIR blocks only its scene and explicit repair preserves the fixed idea", async ({ page, request }) => {
  await openDataset(page);
  await submit(page, "Generate 2 scenes", "/api/workspace/dataset/scenes");
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const saved = await settings(request);
  const fixedIdea = saved.draft.scene_plan[0].idea;
  saved.draft.scene_plan[0].self_check = "REPAIR:\nThe required glove is hidden.\nMove the glove outward without changing the action.";
  expect((await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision, draft: saved.draft } })).ok()).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  await expect(page.getByRole("button", { name: "Regenerate prompt", exact: true }).first()).toBeDisabled();
  const generated = await finish(request, (await (await submit(page, "Continue")).json()).id);
  expect(generated.llm_trace.request_number).toBe(1);
  expect(generated.result.prompts.map((row) => row.index)).toEqual([2]);
  const repaired = await finish(request, (await (await submit(page, "Repair scene", "/api/workspace/dataset/scene")).json()).id);
  expect(repaired.llm_trace.request_number).toBe(2);
  expect(repaired.result.scene_plan[0].idea).toBe(fixedIdea);
  expect(repaired.result.scene_plan[0].self_check).toBe("PASS");
  expect(repaired.result.prompts[1]).toEqual(generated.result.prompts[0]);
});

test("guided Dataset persists and exports on mobile without retired controls", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await openDataset(page, "3");
  await page.getByLabel("Visual style").selectOption("Anime / manga");
  await page.getByLabel(/Provide my own scene ideas/).check();
  await page.getByLabel("Guided dataset inputs").fill("standing portrait in a city at night\nrunning through a sunlit field");
  await generateDataset(page, "3");
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/saved_person/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/standing portrait/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/running through/);
  await expect(page.getByRole("region", { name: "Dataset quality report" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "View geometry 1", exact: true })).toHaveCount(0);
  const downloaded = page.waitForEvent("download");
  const cleanup = page.waitForResponse((response) => response.url().endsWith("/api/jobs?kind=dataset") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "JSONL", exact: true }).click();
  const exported = (await readFile(await (await downloaded).path(), "utf8")).split("\n").map(JSON.parse);
  expect(exported[0].scene).toContain("standing portrait");
  expect(exported[0].idea).toContain("standing portrait");
  expect(exported[0].index).toBe(1);
  for (const id of (await (await cleanup).json()).released) expect((await request.get(`/api/jobs/${id}`)).status()).toBe(404);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  await page.evaluate(() => Promise.all(document.getAnimations().filter((animation) => animation.effect.target.checkVisibility() && Number.isFinite(animation.effect.getTiming().iterations))
    .map((animation) => animation.finished.catch(() => {}))));
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/standing portrait/);
  expect(errors).toEqual([]);
});

test("manual scene edits require rechecking and Clear releases jobs, not scenes", async ({ page, request }) => {
  await openDataset(page);
  await generateDataset(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/saved_person/);
  const manual = "She reads a book on a park bench.";
  await openDatasetPage(page, "Scenes");
  await page.getByLabel("Planned scene 1").fill(manual);
  await expect(page.getByRole("button", { name: "Regenerate prompt", exact: true }).first()).toBeDisabled();
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
  const checked = await finish(request, (await (await submit(page, "Repair scene", "/api/workspace/dataset/scene")).json()).id);
  expect(checked.llm_trace.request_number).toBe(2);
  expect(checked.result.scene_plan[0].scene).toBe(manual);
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/park bench/);
  const cleanup = page.waitForResponse((response) => response.url().endsWith("/api/jobs?kind=dataset") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  for (const id of (await (await cleanup).json()).released) expect((await request.get(`/api/jobs/${id}`)).status()).toBe(404);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(manual);
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
});

test("per-scene actions preserve siblings; idea edits invalidate stale details", async ({ page, request }) => {
  await openDataset(page);
  await generateDataset(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/saved_person/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await settings(request)).draft;
  for (const [label, calls] of [["Regenerate prompt", 1], ["Repair scene", 2], ["Regenerate idea", 3]]) {
    const done = await finish(request, (await (await submit(page, label, "/api/workspace/dataset/scene")).json()).id);
    expect(done.llm_trace.request_number).toBe(calls);
    await expect.poll(async () => (await settings(request)).draft.scene_plan).toEqual(done.result.scene_plan);
    expect(done.result.scene_plan[1]).toEqual(before.scene_plan[1]);
    expect(done.result.prompts[1]).toEqual(before.results[1]);
    if (label === "Regenerate idea") expect(done.result.scene_plan[0].idea).not.toBe(before.scene_plan[0].idea);
    else expect(done.result.scene_plan[0].idea).toBe(before.scene_plan[0].idea);
  }
  await openDatasetPage(page, "Scenes");
  await page.getByLabel("Planned idea 1").fill("Edited activity");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue("");
  await expect.poll(async () => (await settings(request)).draft.scene_plan[0].idea).toBe("Edited activity");
  const edited = (await settings(request)).draft.scene_plan[0];
  expect(edited.self_check).toBe("");
  expect(edited).not.toHaveProperty("placement");
  const repaired = await finish(request, (await (await submit(page, "Repair scene", "/api/workspace/dataset/scene")).json()).id);
  expect(repaired.result.prompts[0].prompt).toContain("Edited activity");
  expect(repaired.result.prompts[1]).toEqual(before.results[1]);
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Dataset idea", { exact: true }).fill("A dog on small adventures.");
  await openDatasetPage(page, "Scenes");
  await expect(page.getByLabel("Planned scene 1")).toHaveCount(0);
});

test("reset recent ideas leaves current scenes and prompts unchanged", async ({ page }) => {
  await openDataset(page);
  await generateDataset(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/saved_person/);
  await openDatasetPage(page, "Scenes");
  const idea = await page.getByLabel("Planned idea 1").inputValue();
  await openDatasetPage(page, "Dataset");
  const prompt = await page.getByLabel("Dataset prompt 1").inputValue();
  const reset = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/novelty/reset"));
  await openDatasetPage(page, "Configure");
  await page.getByText("Advanced options", { exact: true }).click();
  await page.getByRole("button", { name: "Reset recent ideas", exact: true }).click();
  expect((await reset).ok()).toBe(true);
  await expect(page.getByText("Recent ideas reset for this concept. Current scenes and prompts are unchanged.", { exact: true })).toBeVisible();
  await openDatasetPage(page, "Scenes");
  await expect(page.getByLabel("Planned idea 1")).toHaveValue(idea);
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(prompt);
});

test("target changes require fresh approval while reusing checked scenes for Builder enhancement", async ({ page, request }) => {
  await openDataset(page);
  await generateDataset(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/saved_person/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await settings(request)).draft;
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Dataset target model").selectOption("Anima");
  await page.getByLabel("Plan scenes first", { exact: true }).check();
  await expect.poll(async () => (await settings(request)).draft.target).toBe("Anima");
  const first = await finish(request, (await (await submit(page, "Regenerate prompt", "/api/workspace/dataset/scene", true)).json()).id);
  expect(first.llm_trace.request_number).toBe(1);
  await openDatasetPage(page, "Scenes");
  const next = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.status() === 202);
  await page.getByRole("button", { name: "Regenerate prompt", exact: true }).nth(1).click();
  const done = await finish(request, (await (await next).json()).id);
  expect(done.llm_trace.request_number).toBe(1);
  expect(done.result.scene_plan).toEqual(before.scene_plan);
  expect(done.result.prompts.map((row) => row.scene)).toEqual(before.results.map((row) => row.scene));
  expect(done.result.target).toBe("Anima");
});

test("background engine failures surface in Dataset and its activity log", async ({ page }) => {
  const now = Date.now() / 1000;
  await openDataset(page);
  await page.route("**/api/workspace/dataset", (route) => route.fulfill({ status: 202, json: {
    id: "failed-dataset-job", status: "running", revision: 0, kind: "dataset", created_at: now,
    result: null, error: null, progress: "Starting Dataset enhancement…", progress_at: now,
  } }));
  await page.route("**/api/jobs/failed-dataset-job", (route) => route.fulfill({ status: 200, json: {
    id: "failed-dataset-job", status: "failed", revision: 1, kind: "dataset", created_at: now, finished_at: now + 1,
    result: null, error: "Model process exited unexpectedly.", progress: "Waiting for Dataset enhancement",
    progress_at: now, llm_trace: { request_number: 1, status: "error", model: "test-model",
      messages: [{ role: "system", content: "Exact system instruction." }, { role: "user", content: "Accepted scene." }],
      parameters: {}, output: "Partial model text", reasoning: "", issue: "Model process exited unexpectedly.",
      started_at: now, updated_at: now + 1, finished_at: now + 1 },
    events: [{ id: 1, timestamp: now + 1, type: "error", message: "Model process exited unexpectedly." }],
  } }));
  await generateDataset(page);
  await expect(page.getByText("Dataset generation failed. Model process exited unexpectedly.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "View LLM activity log" }).click();
  const log = page.getByRole("dialog", { name: "LLM activity log" });
  await expect(log.getByText("Partial model text", { exact: true })).toBeVisible();
  await log.getByText("What the model is reading", { exact: true }).click();
  await expect(log.getByText("Accepted scene.", { exact: true })).toBeVisible();
});
