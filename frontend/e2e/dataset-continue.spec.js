import { test, expect } from "@playwright/test";
import { analyzeDatasetRequest, confirmDatasetReview, openDatasetPage } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

async function openDataset(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
}

async function finish(request, id) {
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe("succeeded");
  return (await request.get(`/api/jobs/${id}`)).json();
}

async function seedCurrentPlan(request) {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  const input = { ...record.draft, subject: "A duck exploring a garden.", trigger: "duck_token", amount: 2, plan_scenes_first: true };
  const review = await analyzeDatasetRequest(request, input);
  const response = await request.post("/api/workspace/dataset/scenes", {
    data: { input, confirmation_token: review.confirmation_token },
  });
  expect(response.status()).toBe(202);
  await finish(request, (await response.json()).id);
  return (await request.get("/api/workspace/settings/dataset")).json();
}

for (const theme of ["dark", "light"]) for (const width of [1440, 390]) {
  test(`Configure Learn more keeps its colors when opened in ${theme} mode at ${width}px`, async ({ page }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width, height: 1000 });
    await openDataset(page);
    await page.getByText("Advanced options", { exact: true }).click();
    const help = page.locator("#dataset-configure .dataset-help");
    const colors = () => help.evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, border: style.borderTopColor };
    });
    const before = await colors();
    await help.getByText("Learn more", { exact: true }).click();
    await expect(help).toHaveAttribute("open", "");
    await help.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished.catch(() => {}))));
    expect(await colors()).toEqual(before);
    await page.screenshot({ path: testInfo.outputPath(`configure-help-${theme}-${width}.png`), animations: "disabled", fullPage: true });
    await help.getByText("Learn more", { exact: true }).click();
    expect(await colors()).toEqual(before);
  });
}

test("Plan scenes first confirms fresh scenes and stops without creating prompts", async ({ page, request }) => {
  await openDataset(page);
  await page.getByLabel("Plan scenes first", { exact: true }).check();
  const prompts = [];
  page.on("request", (event) => {
    if (event.method() === "POST" && new URL(event.url()).pathname === "/api/workspace/dataset") prompts.push(event);
  });
  await page.getByRole("button", { name: /^Generate 2 (prompts|scenes)$/ }).click();
  await confirmDatasetReview(page);
  await expect(page.getByRole("tab", { name: "Scenes", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  expect(prompts).toEqual([]);
  expect((await (await request.get("/api/workspace/settings/dataset")).json()).draft.results).toEqual([]);
});

test("Generate reviews an isolated fresh request without changing a saved edited plan", async ({ page, request }) => {
  const record = await seedCurrentPlan(request);
  record.draft.scene_plan[0].idea = "An old idea to replace.";
  record.draft.scene_plan[1].self_check = "";
  record.draft.scene_plan[1].scene_status = "not_generated";
  record.draft.results = [{ index: 1, input: "", idea: record.draft.scene_plan[0].idea,
    scene: record.draft.scene_plan[0].scene, prompt: "duck_token: manually edited previous prompt." }];
  const stored = await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: record.draft },
  });
  expect(stored.ok()).toBe(true);
  const savedDraft = (await stored.json()).draft;
  expect(savedDraft.scene_plan[0].self_check).toBe("");
  expect(savedDraft.results).toEqual([]);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const analysis = page.waitForRequest("**/api/workspace/dataset/understand");
  await page.getByRole("button", { name: /^Generate 2 (prompts|scenes)$/ }).click();
  const reviewed = (await analysis).postDataJSON().input;
  expect(reviewed.scene_plan).toEqual([]);
  expect(reviewed.scene_plan_signature).toBe("");
  expect((await (await request.get("/api/workspace/settings/dataset")).json()).draft).toEqual(savedDraft);
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Planned idea 1")).not.toHaveValue("An old idea to replace.");
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(after.results).toEqual([]);
});

test("Continue keeps the plan and completed prompt, generates only missing prompts, then opens Dataset", async ({ page, request }) => {
  const record = await seedCurrentPlan(request);
  const first = record.draft.scene_plan[0];
  first.prompt_status = "valid";
  record.draft.results = [{ index: 1, input: first.input, idea: first.idea, scene: first.scene,
    prompt: "duck_token: my edited prompt; keep this wording.\n  And spacing." }];
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: record.draft },
  })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const writes = [];
  page.on("request", (event) => { if (event.method() === "POST") writes.push(event.url()); });
  const admission = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const accepted = await admission;
  expect(accepted.request().postDataJSON().resume).toBe(true);
  const completed = await finish(request, (await accepted.json()).id);
  expect(completed.llm_trace.request_number).toBe(1);
  expect(completed.result.prompts[0]).toEqual(record.draft.results[0]);
  expect(completed.result.scene_plan.map((item) => item.scene)).toEqual(record.draft.scene_plan.map((item) => item.scene));
  expect(writes.filter((url) => url.endsWith("/api/workspace/dataset/understand"))).toEqual([]);
  await expect(page.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(record.draft.results[0].prompt);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await openDatasetPage(page, "Scenes");
  writes.length = 0;
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(writes).toEqual([]);
});

test("Continue is absent without scenes, including when Plan scenes first is enabled", async ({ page }) => {
  await openDataset(page);
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
  await page.getByLabel("Plan scenes first", { exact: true }).check();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
  await openDatasetPage(page, "Scenes");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
});

test("Configure Continue writes existing scenes even when Plan scenes first is off", async ({ page, request }) => {
  const record = await seedCurrentPlan(request);
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: { ...record.draft, plan_scenes_first: false } },
  })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Plan scenes first", { exact: true })).not.toBeChecked();
  const admission = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const accepted = await admission;
  expect(accepted.request().postDataJSON().resume).toBe(true);
  const completed = await finish(request, (await accepted.json()).id);
  expect(completed.llm_trace.request_number).toBe(2);
  expect(completed.result.scene_plan.map((row) => row.scene)).toEqual(record.draft.scene_plan.map((row) => row.scene));
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
});
