import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";

async function delayDatasetSettings(page) {
  // Exercise the job-completion/revision-refresh boundary on slower CI runners.
  await page.route("**/api/workspace/settings/dataset", async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({ response });
  });
}

test("backend completes and persists Dataset after the generating browser closes", async ({ page, context, browser, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A craftsperson working with clay.");
  await page.getByLabel("Trigger text or terms").fill("durable_person");
  await page.getByLabel("Number of prompts").selectOption("5");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate 5 prompts", exact: true }).click();
  const job = await (await accepted).json();
  const appUrl = page.url();
  await context.close();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  expect(saved.draft.results).toHaveLength(5);
  expect(saved.checkpoint.job_id).toBe(job.id);
  const recovered = await browser.newContext();
  try {
    const newPage = await recovered.newPage();
    await newPage.goto(appUrl);
    await newPage.getByRole("button", { name: "Dataset", exact: true }).click();
    await expect(newPage.getByLabel("Dataset prompt 5")).toHaveValue(/durable_person/);
  } finally { await recovered.close(); }
});

test("descriptive creativity persists independently and reuses the exact planned scene", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset descriptive creativity")).toHaveValue("Balanced");
  await page.getByLabel("Dataset idea", { exact: true }).fill("One performer balancing inside an aerial hoop.");
  await page.getByLabel("Number of prompts").selectOption("1");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const before = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  await page.getByLabel("Dataset descriptive creativity").selectOption("Dice");
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const changed = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(changed.creativity).toBe("Dice");
  expect(changed.scene_plan_signature).toBe(before.scene_plan_signature);
  expect(changed.scene_plan.map(({ idea, scene, geometry }) => ({ idea, scene, geometry })))
    .toEqual(before.scene_plan.map(({ idea, scene, geometry }) => ({ idea, scene, geometry })));
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset descriptive creativity")).toHaveValue("Dice");
  await page.getByLabel("Trigger text or terms").fill("ohwx_performer");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate prompts from these scenes", exact: true }).click();
  const response = await accepted;
  expect(response.request().postDataJSON().input.creativity).toBe("Dice");
  const job = await response.json();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/ohwx_performer/);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.llm_trace.request_number).toBe(1);
  expect(finished.llm_trace.messages[0].content).toContain("Dataset Creativity — Dice");
  expect(finished.result.scene_plan[0].geometry).toEqual(before.scene_plan[0].geometry);
});

test("a writer failure retries the prompt using backend scene eligibility, not scene repair", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A craftsperson working with clay.");
  await page.getByLabel("Trigger text or terms").fill("retry_person");
  await page.getByLabel("Number of prompts").selectOption("1");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene/);
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  saved.draft.scene_plan[0] = { ...saved.draft.scene_plan[0], prompt_status: "failed",
    failure_stage: "prompt", failure_reason: "Writer disconnected; the scene is valid." };
  expect((await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision, draft: saved.draft } })).ok()).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.status() === 202);
  await page.getByRole("button", { name: "Retry failed prompt", exact: true }).click();
  const response = await accepted;
  expect(response.request().postDataJSON().action).toBe("regenerate_prompt");
  const job = await response.json();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/retry_person/);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.llm_trace.request_number).toBe(1);
});

test("writer-setting acknowledgements retain scene eligibility despite reordered JSON keys", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A craftsperson working with clay.");
  await page.getByLabel("Trigger text or terms").fill("clay_person");
  await page.getByLabel("Number of prompts").selectOption("1");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene/);
  await expect(page.getByLabel("Planned scene 1")).toBeEnabled();
  await page.route("**/api/workspace/settings/dataset", async (route) => {
    const response = await route.fetch();
    if (route.request().method() !== "PUT") return route.fulfill({ response });
    const record = await response.json();
    record.draft.scene_plan = record.draft.scene_plan.map((row) => Object.fromEntries(
      Object.entries({ ...row, geometry: Object.fromEntries(Object.entries(row.geometry).reverse()) }).reverse(),
    ));
    await route.fulfill({ response, json: record });
  });
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/workspace/settings/dataset") && response.request().method() === "PUT");
  await page.getByLabel("Dataset prompt length").selectOption("Detailed");
  expect((await saved).ok()).toBe(true);
  await expect(page.getByRole("button", { name: "Generate prompts from these scenes", exact: true })).toBeEnabled();
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate prompts from these scenes", exact: true }).click();
  expect((await accepted).request().postDataJSON().valid_only).toBe(true);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/clay_person/);
});

test("Quality composes in small chunks and geometry opens in an accessible modal", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
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
  const geometryButton = plan.getByRole("button", { name: "View geometry 1", exact: true });
  const modal = page.getByRole("dialog", { name: "Geometry 1", exact: true });
  await expect(modal).not.toBeVisible();
  await expect(geometryButton).toHaveAttribute("aria-haspopup", "dialog");
  await expect(geometryButton).toHaveAttribute("title", "View geometry 1");
  const neighboringScene = plan.getByLabel("Planned scene 2").locator("../..");
  const sceneBefore = await neighboringScene.boundingBox();
  await geometryButton.focus();
  await page.keyboard.press("Enter");
  await expect(modal).toBeVisible();
  await expect(modal.getByRole("button", { name: "Close geometry", exact: true })).toBeFocused();
  await expect(modal.getByText("gaze direction", { exact: true })).toBeVisible();
  await expect(modal.getByText("toward action", { exact: true })).toHaveCount(2); // Head and eyes are separate facts.
  await expect(modal.getByText("standing neutral", { exact: true })).toBeVisible();
  await page.keyboard.press("Tab");
  expect(await modal.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(modal.getByRole("button", { name: "Close geometry", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(modal.locator("dl")).toBeFocused();
  const sceneAfter = await neighboringScene.boundingBox();
  expect(sceneAfter.height).toBeCloseTo(sceneBefore.height, 2);
  expect(sceneAfter.width).toBeCloseTo(sceneBefore.width, 2);
  expect(sceneAfter.x).toBeCloseTo(sceneBefore.x, 2);
  const fields = modal.locator("dl");
  expect(await fields.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(modal).not.toBeVisible();
  await expect(geometryButton).toBeFocused();
  const results = page.getByRole("region", { name: "Dataset results", exact: true });
  const neighboringPrompt = results.getByLabel("Dataset prompt 2").locator("..");
  const promptBefore = await neighboringPrompt.boundingBox();
  const resultGeometryButton = results.getByRole("button", { name: "View geometry 1", exact: true });
  await resultGeometryButton.click();
  await expect(modal).toBeVisible();
  const promptAfter = await neighboringPrompt.boundingBox();
  expect(promptAfter.height).toBe(promptBefore.height);
  expect(promptAfter.width).toBe(promptBefore.width);
  expect(promptAfter.x).toBe(promptBefore.x);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const modalBox = await modal.boundingBox();
  expect(modalBox.x).toBeGreaterThanOrEqual(0);
  expect(modalBox.x + modalBox.width).toBeLessThanOrEqual(390);
  expect(modalBox.y).toBeGreaterThanOrEqual(0);
  expect(modalBox.y + modalBox.height).toBeLessThanOrEqual(844);
  expect(await fields.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await modal.getByRole("button", { name: "Close geometry", exact: true }).click();
  await expect(modal).not.toBeVisible();
  await expect(resultGeometryButton).toBeFocused();
  expect(finished.result.scene_plan.every((row) => row.geometry.gaze_direction === "toward_action" && !("gaze" in row.geometry))).toBe(true);
});

test.beforeEach(async ({ request }) => {
  const settings = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: settings.revision, draft: {} },
  })).ok()).toBe(true);
});

async function seedEditedDatasetBatch(request) {
  const initial = await (await request.get("/api/workspace/settings/dataset")).json();
  const input = { ...initial.draft, subject: "A craftsperson working with clay.", trigger: "saved_person", amount: 2 };
  const accepted = await request.post("/api/workspace/dataset/scenes", { data: { input } });
  expect(accepted.status()).toBe(202);
  const job = await accepted.json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  const draft = { ...saved.draft, result_job_id: "manually-edited-batch",
    results: saved.draft.scene_plan.map(({ index, input, idea, scene, geometry }) => ({ index, input, idea, scene, geometry,
      prompt: `saved_person: edited prompt ${index}; preserve (these words).\n  Deliberate spacing.`,
    })) };
  const quality = await request.post("/api/workspace/dataset/quality", { data: { input: draft } });
  expect(quality.ok(), await quality.text()).toBe(true);
  draft.quality_report = (await quality.json()).report;
  const stored = await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision, draft } });
  expect(stored.ok()).toBe(true);
  return (await stored.json()).draft;
}

for (const button of ["Generate 2 prompts", "Generate prompts from these scenes"]) {
  for (const status of [400, 409, 503]) {
    test(`rejected Dataset regeneration preserves the saved edited batch via ${button} (${status})`, async ({ page, request }) => {
      const before = await seedEditedDatasetBatch(request);
      await page.goto("/");
      await page.getByRole("button", { name: "Dataset", exact: true }).click();
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(before.results[0].prompt);
      await page.route("**/api/workspace/dataset", (route) => route.fulfill({
        status, json: { error: "Generation admission unavailable." },
      }));
      await page.getByRole("button", { name: button, exact: true }).click();
      await expect(page.getByText(/Generation admission unavailable/).first()).toBeVisible();
      const after = await (await request.get("/api/workspace/settings/dataset")).json();
      expect(after.draft).toEqual(before);
      await page.reload();
      await page.getByRole("button", { name: "Dataset", exact: true }).click();
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(before.results[0].prompt);
      await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(before.results[1].prompt);
    });
  }

  test(`Dataset replaces the prior batch only after admission via ${button}`, async ({ page, request }) => {
    const before = await seedEditedDatasetBatch(request);
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    let releaseAdmission;
    const admissionGate = new Promise((resolve) => { releaseAdmission = resolve; });
    await page.route("**/api/workspace/dataset", async (route) => {
      await admissionGate;
      await route.continue();
    });
    const submission = page.waitForRequest("**/api/workspace/dataset");
    const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
    try {
      await page.getByRole("button", { name: button, exact: true }).click();
      const input = (await submission).postDataJSON().input;
      expect(input.results).toEqual(before.results);
      expect(input.quality_report).toEqual(before.quality_report);
      expect(input.result_job_id).toBe(before.result_job_id);
      const waiting = await (await request.get("/api/workspace/settings/dataset")).json();
      expect(waiting.draft).toEqual(before);
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(before.results[0].prompt);
      releaseAdmission();
      const job = await (await accepted).json();
      await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
      await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/saved_person:.*mock scene 1/);
      await expect(page.getByLabel("Planned scene 1")).toBeEnabled();
      const finished = await (await request.get("/api/workspace/settings/dataset")).json();
      expect(finished.draft.results.map((row) => row.index)).toEqual([1, 2]);
      expect(finished.draft.results).not.toEqual(before.results);
      expect(finished.draft.result_job_id).toBe(job.id);
    } finally { releaseAdmission(); }
  });
}

test("Dataset recovers an accepted replacement after losing its admission response without restoring stale output", async ({ page, request }) => {
  const before = await seedEditedDatasetBatch(request);
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
  const job = await accepted;
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
  const recovered = await (await request.get("/api/workspace/settings/dataset")).json();
  expect(recovered.draft.results.map((row) => row.index)).toEqual([1, 2]);
  expect(recovered.draft.results).not.toEqual(before.results);
  expect(recovered.draft.result_job_id).toBe(job.id);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(recovered.draft.results[0].prompt);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(recovered.draft.results[1].prompt);
});

test("Fast plans ten scenes in three combined chunks", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler visiting different exhibits.");
  await page.getByLabel("Dataset planning mode").selectOption("Fast");
  await page.getByLabel("Number of prompts").selectOption("10");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scenes") && response.status() === 202);
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  const job = await (await accepted).json();
  await expect(page.getByLabel("Planned scene 10")).toHaveValue(/mock scene 10/);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.status).toBe("succeeded");
  expect(finished.llm_trace.request_number).toBe(3);
  expect(finished.result.scene_plan.map((row) => row.index)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test("failed scenes show persistent reasons and do not block writing valid scenes", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler visiting exhibits.");
  await page.getByLabel("Number of prompts").selectOption("3");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 3")).toHaveValue(/mock scene 3/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const settings = await (await request.get("/api/workspace/settings/dataset")).json();
  const reason = "Direct rear camera cannot show a full face. Scene repair failed after bounded recovery.";
  const fixedIdea = settings.draft.scene_plan[0].idea;
  settings.draft.scene_plan[0] = { ...settings.draft.scene_plan[0], scene: "", geometry: {},
    idea_status: "valid", scene_status: "failed", prompt_status: "failed", failure_reason: reason,
    failure_stage: "scene" };
  settings.draft.scene_plan[2] = { ...settings.draft.scene_plan[2], idea: "", scene: "", geometry: {},
    idea_status: "not_generated", scene_status: "not_generated", prompt_status: "not_generated" };
  settings.draft.trigger = "ohwx_traveler";
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: settings.revision, draft: settings.draft },
  })).ok()).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const plan = page.getByRole("region", { name: "Scene Planner ideas", exact: true });
  await expect(plan.getByLabel("Prompt 1 failure reason")).toContainText(reason);
  const results = page.getByRole("region", { name: "Dataset results", exact: true });
  await expect(results.getByLabel("Prompt 1 failure reason")).toContainText(reason);
  await expect(results.getByRole("button", { name: "Retry failed scene", exact: true })).toBeVisible();
  await expect(results.getByRole("button", { name: "Retry failed idea", exact: true })).toHaveCount(0);
  // Measure final-state contrast, not a transient entrance-fade frame.
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((animation) => Number.isFinite(animation.effect.getTiming().iterations))
    .map((animation) => animation.finished.catch(() => {}))));
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate prompts from 1 valid scene", exact: true }).click();
  const response = await accepted;
  expect(response.request().postDataJSON().valid_only).toBe(true);
  const job = await response.json();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_traveler/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
  await expect(results.getByLabel("Prompt 1 failure reason")).toContainText(reason);
  const finished = await (await request.get(`/api/jobs/${job.id}`)).json();
  expect(finished.status).toBe("succeeded");
  expect(finished.llm_trace.request_number).toBe(1);
  expect(finished.result.prompts.map((row) => row.index)).toEqual([2]);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByRole("region", { name: "Dataset results", exact: true }).getByLabel("Prompt 1 failure reason")).toContainText(reason);
  const retry = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.status() === 202);
  await page.getByRole("button", { name: "Retry failed scene", exact: true }).click();
  const repaired = await retry;
  expect(repaired.request().postDataJSON().action).toBe("repair_scene");
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/mock scene 1/);
  await expect(page.getByLabel("Planned idea 1")).toHaveValue(fixedIdea);
});

test("Dataset builds, persists and exports a trigger-ready batch", async ({ page, request }) => {
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
  await expect(page.getByLabel("Use coverage plan")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Coverage planner" })).toHaveCount(0);
  await page.getByRole("button", { name: "Generate 3 prompts" }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/ohwx_person/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/standing portrait/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/running through/);
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/standing portrait/);
  await expect(page.getByRole("button", { name: "TXT", exact: true })).toBeEnabled();
  await expect(page.getByLabel("Planned scene 1")).toBeEnabled();
  const downloaded = page.waitForEvent("download");
  const cleanup = page.waitForResponse((response) => response.url().endsWith("/api/jobs?kind=dataset") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "JSONL", exact: true }).click();
  const exported = (await readFile(await (await downloaded).path(), "utf8")).split("\n").map(JSON.parse);
  expect(exported[0].scene).toContain("standing portrait");
  expect(exported[0].idea).toContain("standing portrait");
  expect(exported[0].index).toBe(1);
  const released = await (await cleanup).json();
  expect(released.released.length).toBeGreaterThan(0);
  for (const id of released.released) expect((await request.get(`/api/jobs/${id}`)).status()).toBe(404);
  const quality = page.getByRole("region", { name: "Dataset quality report" });
  await expect(quality.getByText("Overall", { exact: true })).toBeVisible();
  await expect(quality.getByText(/Prompt checks · \d\/3 passed/)).toBeVisible();
  await expect(quality.getByRole("button", { name: "Deep consistency review" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByText("Dataset settings: Saved")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/ohwx_person/);
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(/standing portrait/);
  await expect(page.getByLabel("Planned scene 3")).toHaveValue(/standing portrait/);
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
  await page.getByLabel("Dataset target model").selectOption("Qwen Image (original)");
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

test("expanded fruit wording passes subject checks while protected wording stays exact", async ({ page, request }) => {
  const path = "/api/workspace/settings/dataset";
  const record = await (await request.get(path)).json();
  const prompt = "A muscular anthropomorphic banana in a suit punches the apple character in a dress on a padded dojo mat.";
  const input = { ...record.draft, amount: 1, trigger: "a banana, an apple", trigger_connected: false,
    trigger_at_start: false, expand_trigger: true, subject: "Fruit characters in combat.", target: "Generic",
    source_mode: "random", scene_plan: [], scene_plan_signature: "", quality_report: {},
    results: [{ index: 1, input: "", prompt }], result_job_id: "" };
  const expanded = await (await request.post("/api/workspace/dataset/quality", { data: { input } })).json();
  expect(expanded.report.prompts[0].issues.filter((issue) => issue.code.startsWith("trigger"))).toEqual([]);
  const protectedReport = await (await request.post("/api/workspace/dataset/quality", {
    data: { input: { ...input, expand_trigger: false } },
  })).json();
  expect(protectedReport.report.prompts[0].issues.some((issue) => issue.code === "trigger_missing")).toBe(true);
  expect(protectedReport.report.signature).not.toBe(expanded.report.signature);
  expect((await request.put(path, { data: { revision: record.revision, draft: input } })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Allow trigger expansion")).toBeChecked();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(prompt);
  const quality = page.getByRole("region", { name: "Dataset quality report", exact: true });
  await quality.getByText("Prompt checks · 1/1 passed", { exact: true }).click();
  await expect(quality.getByText("All automatic checks passed.")).toBeVisible();
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  const latest = await (await request.get(path)).json();
  expect((await request.put(path, { data: { revision: latest.revision, draft: record.draft } })).ok()).toBe(true);
});

test("reset recent ideas does not invalidate the current plan or prompts", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A performer in a rehearsal room.");
  await page.getByLabel("Trigger text or terms").fill("performer_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/performer_token/);
  await expect(page.getByRole("button", { name: "Reset recent ideas", exact: true })).toBeEnabled();
  const idea = await page.getByLabel("Planned idea 1").inputValue();
  const prompt = await page.getByLabel("Dataset prompt 1").inputValue();
  const reset = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/novelty/reset"));
  await page.getByRole("button", { name: "Reset recent ideas", exact: true }).click();
  expect((await reset).ok()).toBe(true);
  await expect(page.getByText("Recent ideas reset for this concept. Current scenes and prompts are unchanged.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Planned idea 1")).toHaveValue(idea);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(prompt);
});

test("manual scenes regenerate locally and clearing results releases only job checkpoints", async ({ page, request }) => {
  await delayDatasetSettings(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler visiting exhibits.");
  await page.getByLabel("Trigger text or terms").fill("ohwx_traveler");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_traveler/);
  await expect(page.getByLabel("Planned scene 1")).toBeEnabled();
  const manual = "She reads a book on a park bench.";
  await page.getByLabel("Planned scene 1").fill(manual);
  const plan = page.getByRole("region", { name: "Scene Planner ideas", exact: true });
  const started = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.request().method() === "POST");
  await plan.getByRole("button", { name: "Regenerate prompt", exact: true }).first().click();
  const response = await started;
  expect(response.ok(), await response.text()).toBe(true);
  const sceneJob = await response.json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${sceneJob.id}`)).json()).status).toBe("succeeded");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/park bench/);
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(manual);
  await expect(plan.getByRole("button", { name: "View geometry 1", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Clear", exact: true })).toBeEnabled();
  const cleanup = page.waitForResponse((response) => response.url().endsWith("/api/jobs?kind=dataset") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  for (const id of (await (await cleanup).json()).released) expect((await request.get(`/api/jobs/${id}`)).status()).toBe(404);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
  await expect(page.getByText("Dataset settings: Saved")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Planned scene 1")).toHaveValue(manual);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
});

test("Quality planning and per-scene controls preserve the rest of the batch", async ({ page, request }) => {
  await delayDatasetSettings(page);
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
  const repaired = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scene") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Repair scene", exact: true }).first().click();
  const repairResponse = await repaired;
  expect(repairResponse.ok(), await repairResponse.text()).toBe(true);
  const repairJob = await repairResponse.json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${repairJob.id}`)).json()).status).toBe("succeeded");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/Edited activity/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(before.results[1].prompt);
});
