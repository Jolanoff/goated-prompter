import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("Quality composes in small chunks and geometry stays behind a readable disclosure", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler visiting different exhibits.");
  await page.getByLabel("Trigger text or terms").fill("ohwx_traveler");
  await page.getByLabel("Dataset planning mode").selectOption("Quality");
  await page.getByLabel("Number of prompts").selectOption("5");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate 5 prompts", exact: true }).click();
  const job = await (await accepted).json();
  await expect(page.getByLabel("Dataset prompt 5")).toHaveValue(/ohwx_traveler/);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.status).toBe("succeeded");
  expect(finished.llm_trace.request_number).toBe(8); // Full-batch ideas + 2 chunks + 5 writers.
  const plan = page.getByRole("region", { name: "Scene Planner ideas", exact: true });
  const disclosure = plan.locator("details").filter({ has: page.getByText("Geometry 1", { exact: true }) });
  await expect(disclosure).not.toHaveAttribute("open");
  await expect(disclosure.getByText("gaze direction", { exact: true })).not.toBeVisible();
  await disclosure.locator("summary").click();
  await expect(disclosure.getByText("gaze direction", { exact: true })).toBeVisible();
  await expect(disclosure.getByText("toward action", { exact: true })).toHaveCount(2); // Head and eyes are separate facts.
  await expect(disclosure.getByText("standing neutral", { exact: true })).toBeVisible();
  expect(finished.result.scene_plan.every((row) => row.geometry.gaze_direction === "toward_action" && !("gaze" in row.geometry))).toBe(true);
});

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
  await expect(page.getByRole("heading", { name: "Build a prompt dataset", exact: true })).toBeVisible();
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
  await expect(page.getByLabel("Planned scene 2")).toHaveValue("A woman doing funny stuff; mock scene 2.");
  const scene = "She attempts a pancake flip and the pancake lands on her head, spatula still raised.";
  const idea = "Flipping a pancake onto her head";
  await expect(page.getByLabel("Planned idea 1")).toHaveValue("Mock activity1");
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

test("Quality planning and per-scene controls preserve the rest of the batch", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A woman doing funny stuff");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByLabel("Dataset planning mode").selectOption("Quality");
  await page.getByText("Training trigger & controls", { exact: true }).click();
  await page.getByLabel("Trigger text or terms").fill("ohwx_woman");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  const job = await (await accepted).json();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_woman/);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.llm_trace.request_number).toBe(4); // two planning calls, two writers
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  for (const [label, calls] of [["Regenerate prompt", 1], ["Repair scene", 2], ["Regenerate idea", 3]]) {
    const started = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.status() === 202);
    await page.getByRole("button", { name: label, exact: true }).first().click();
    const sceneJob = await (await started).json();
    await expect(page.getByRole("button", { name: label, exact: true }).first()).toBeEnabled();
    await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
    const done = await (await request.get(`/api/jobs/${sceneJob.id}`)).json();
    expect(done.status).toBe("succeeded");
    expect(done.llm_trace.request_number).toBe(calls);
    // The button can re-enable before the final job update's autosave is flushed.
    await expect.poll(async () => (await (await request.get("/api/workspace/settings/dataset")).json()).draft.scene_plan)
      .toEqual(done.result.scene_plan);
    const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
    expect(after.scene_plan[1]).toEqual(before.scene_plan[1]);
    expect(after.results[1]).toEqual(before.results[1]);
    if (label !== "Regenerate idea") expect(after.scene_plan[0].idea).toBe(before.scene_plan[0].idea);
    else expect(after.scene_plan[0].idea).not.toBe(before.scene_plan[0].idea);
  }
  await page.getByLabel("Planned idea 1").fill("Edited activity");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue("");
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const state = await (await request.get("/api/workspace/settings/dataset")).json();
  expect(state.idea_plan_current).toBe(true);
  expect(state.scene_plan_current).toBe(false);
  await expect(page.getByRole("button", { name: "Repair scene", exact: true }).first()).toBeEnabled();
  await page.getByRole("button", { name: "Repair scene", exact: true }).first().click();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/Edited activity/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(before.results[1].prompt);
});
