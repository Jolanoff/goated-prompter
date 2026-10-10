import { test, expect } from "@playwright/test";
import { analyzeDatasetRequest, confirmDatasetReview, openDatasetPage } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

async function finish(request, id) {
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).status).toBe("succeeded");
  return (await (await request.get(`/api/jobs/${id}`)).json()).result;
}

function datasetPosts(page) {
  const posts = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path.startsWith("/api/workspace/dataset")) posts.push(path);
  });
  return posts;
}

test("reloading an automatic batch advances to Dataset without a Continue click or second submission", async ({ page, request }) => {
  let finishJob = false;
  const automatic = { id: "restored-auto-dataset", kind: "dataset", revision: 1,
    status: "running", progress: "Planning scenes", result: { scene_plan: [], completed: 0 }, events: [] };
  await page.route("**/api/bootstrap", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), active_job: automatic } });
  });
  await page.route("**/api/jobs/restored-auto-dataset", (route) => route.fulfill({ json: finishJob
    ? { ...automatic, revision: 2, status: "succeeded", result: { scene_plan: [{ index: 1, scene_status: "valid" }], completed: 1 } }
    : automatic }));
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  const posts = datasetPosts(page);
  await expect(page.locator(".dataset-view").getByRole("status").filter({ hasText: "Planning scenes" })).toBeVisible();
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", { data: { revision: saved.revision,
    draft: { ...saved.draft, results: [{ index: 1, input: "", idea: "A duck rests", scene: "A duck rests on a bench", prompt: "duck_token: a duck rests on a bench" }] } } })).ok()).toBe(true);
  finishJob = true;
  await expect(page.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue("duck_token: a duck rests on a bench");
  expect(posts).toEqual([]);
});

test("Configure Generate completes scenes and prompts after one Understanding review", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  const posts = datasetPosts(page);
  const admission = page.waitForResponse((response) => response.status() === 202 &&
    /\/api\/workspace\/dataset(?:\/scenes)?$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: /^Generate 2 (prompts|scenes)$/ }).click();
  await confirmDatasetReview(page);
  const accepted = await admission;
  await finish(request, (await accepted.json()).id);
  await expect(page.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/duck_token/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  expect(posts).toEqual(["/api/workspace/dataset/understand", "/api/workspace/dataset"]);
  await openDatasetPage(page, "Scenes");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
});

test("a saved scene-review setting never makes normal Generate stop before prompts", async ({ page, request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  await request.put("/api/workspace/settings/dataset", { data: { revision: record.revision,
    draft: { ...record.draft, subject: "One red duck and two men travel together as best friends.",
      trigger: "duck_token", amount: 2, plan_scenes_first: true } } });
  await page.goto("/");
  const posts = datasetPosts(page);
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Configure");
  await expect(page.getByRole("button", { name: "Generate 2 prompts", exact: true })).toBeEnabled();
  const admitted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  const job = await (await admitted).json();
  const result = await finish(request, job.id);
  expect(result.completed).toBe(2);
  await expect(page.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(posts).toEqual(["/api/workspace/dataset/understand", "/api/workspace/dataset"]);
});

test("Scene Continue resumes a saved approved plan without rerunning Understanding", async ({ page, request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  const input = { ...record.draft, subject: "A duck exploring a garden.", trigger: "duck_token", amount: 2,
    plan_scenes_first: true };
  const review = await analyzeDatasetRequest(request, input);
  const planned = await request.post("/api/workspace/dataset/scenes", {
    data: { input, confirmation_token: review.confirmation_token },
  });
  expect(planned.status()).toBe(202);
  await finish(request, (await planned.json()).id);
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  const first = saved.draft.scene_plan[0];
  first.prompt_status = "valid";
  saved.draft.results = [{ index: 1, input: first.input, idea: first.idea, scene: first.scene,
    prompt: "duck_token: preserve my edited prompt.\n  And spacing." }];
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: saved.revision, draft: saved.draft },
  })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  const posts = datasetPosts(page);
  const submission = page.waitForRequest((event) => event.method() === "POST" &&
    new URL(event.url()).pathname.startsWith("/api/workspace/dataset"));
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  expect(new URL((await submission).url()).pathname).toBe("/api/workspace/dataset");
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(saved.draft.results[0].prompt);
  expect(posts).toEqual(["/api/workspace/dataset"]);
  const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(after.scene_plan.map((row) => row.scene)).toEqual(saved.draft.scene_plan.map((row) => row.scene));
});

test("Scene Continue with a lost session ticket resumes writing rather than Understanding", async ({ page, request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  const input = { ...record.draft, subject: "A duck exploring a garden.", trigger: "duck_token", amount: 2,
    plan_scenes_first: true };
  const review = await analyzeDatasetRequest(request, input);
  const planned = await request.post("/api/workspace/dataset/scenes", {
    data: { input, confirmation_token: review.confirmation_token },
  });
  expect(planned.status()).toBe(202);
  await finish(request, (await planned.json()).id);
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  await page.route("**/api/workspace/settings/dataset", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, continuation_token: "" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  const posts = datasetPosts(page);
  const submission = page.waitForRequest((event) => event.method() === "POST" &&
    new URL(event.url()).pathname.startsWith("/api/workspace/dataset"));
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  expect(new URL((await submission).url()).pathname).toBe("/api/workspace/dataset");
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await expect(page.getByRole("dialog", { name: "Review your Dataset request", exact: true })).toHaveCount(0);
  expect(posts).toEqual(["/api/workspace/dataset"]);
  const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(after.scene_plan.map((row) => row.scene)).toEqual(saved.draft.scene_plan.map((row) => row.scene));
});

test("explicit scenes-only generation pauses and Continue reuses the initial Understanding approval", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  await expect(page.getByRole("button", { name: "Generate 2 prompts", exact: true })).toBeEnabled();
  const posts = datasetPosts(page);
  await page.getByRole("button", { name: "Generate 2 scenes only", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  await expect(page.getByRole("tab", { name: "Scenes", exact: true })).toHaveAttribute("aria-selected", "true");
  const next = page.getByRole("button", { name: "Continue", exact: true });
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  expect(posts).toEqual(["/api/workspace/dataset/understand", "/api/workspace/dataset/scenes", "/api/workspace/dataset"]);
});

test("an edited scene is written as edited under the initial Understanding approval", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  const posts = datasetPosts(page);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await openDatasetPage(page, "Scenes");
  await page.getByLabel("Planned scene 1").fill("  A duck\nreads a map on a bench.  ");
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Repair scene", exact: true })).toHaveCount(0);
  const submission = page.waitForRequest((event) => event.method() === "POST" &&
    new URL(event.url()).pathname.startsWith("/api/workspace/dataset"));
  await page.getByRole("button", { name: "Regenerate prompt", exact: true }).first().click();
  expect(new URL((await submission).url()).pathname).toBe("/api/workspace/dataset/scene");
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/duck_token:.*reads a map/);
  expect(posts).toEqual(["/api/workspace/dataset/understand", "/api/workspace/dataset", "/api/workspace/dataset/scene"]);
});

test("revised source rules preserve automatic generation instead of introducing a scene-only pause", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Dataset prompt length").selectOption("Detailed");
  await openDatasetPage(page, "Scenes");
  await page.getByRole("button", { name: "Regenerate prompt", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request", exact: true });
  await expect(dialog.getByRole("button", { name: "Update summary", exact: true })).toBeEnabled();
  await dialog.getByLabel("Extra instructions or answers").fill("Keep the duck's feet visible.");
  await dialog.getByRole("button", { name: "Update summary", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Confirm and generate prompts", exact: true })).toBeEnabled();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await openDatasetPage(page, "Scenes");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
});

test("1000-character triggers persist and generate while oversized triggers are rejected", async ({ page, request }) => {
  const trigger = "duck_token_".padEnd(1000, "x");
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Number of prompts").selectOption("1");
  const field = page.getByLabel("Trigger text or terms", { exact: true });
  await expect(field).toHaveAttribute("maxlength", "1000");
  await field.fill(trigger);
  await field.press("End");
  await field.pressSequentially("z");
  await expect(field).toHaveValue(trigger);
  await expect.poll(async () => (await (await request.get("/api/workspace/settings/dataset")).json()).draft.trigger).toBe(trigger);

  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  const rejected = await request.put("/api/workspace/settings/dataset", {
    data: { revision: saved.revision, draft: { ...saved.draft, trigger: trigger + "z" } },
  });
  expect(rejected.status()).toBe(400);
  expect((await rejected.json()).error).toContain("at most 1000 characters");
  const unchanged = await (await request.get("/api/workspace/settings/dataset")).json();
  expect(unchanged.revision).toBe(saved.revision);
  expect(unchanged.draft.trigger).toBe(trigger);

  const admission = page.waitForResponse((response) => response.status() === 202 &&
    new URL(response.url()).pathname === "/api/workspace/dataset");
  await page.getByRole("button", { name: "Generate 1 prompt", exact: true }).click();
  await confirmDatasetReview(page);
  await finish(request, (await (await admission).json()).id);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(new RegExp(`^${trigger}: mock scene 1:`));
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(field).toHaveValue(trigger);
});

test("Anima inserts locked multiple-character tags unchanged before a scene-only model response", async ({ page, request }) => {
  const trigger = "2 girls, remilia scarlet, touhou, 1girl, red eyes, short hair, blue hair, mob cap, bat wings, bat wings, flandre scarlet, touhou, 1girl, red eyes, blonde hair, short hair, side ponytail, mob cap, wings, wings, one side up, crystal";
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  const input = { ...record.draft, subject: "Remilia Scarlet passes a red cup to Flandre Scarlet in a dimly lit bedroom.",
    trigger, trigger_type: "Multiple characters", amount: 1, target: "Anima", visual_style: "Anime / manga",
    trigger_at_start: true, trigger_connected: true, expand_trigger: false };
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: input },
  })).ok()).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Trigger text or terms")).toHaveValue(trigger);
  const admission = page.waitForResponse((response) => response.status() === 202 &&
    new URL(response.url()).pathname === "/api/workspace/dataset");
  await page.getByRole("button", { name: "Generate 1 prompt", exact: true }).click();
  const review = page.getByRole("dialog", { name: "Review your Dataset request", exact: true });
  await expect(review).toContainText("Supplied character trigger (verbatim):");
  await expect(review).toContainText(trigger);
  await expect(review).toContainText("not a visibility requirement");
  await confirmDatasetReview(page);
  const id = (await (await admission).json()).id;
  const result = await finish(request, id);
  const expected = `${trigger}, ${result.scene_plan[0].scene}`;
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(expected);
  const finished = await (await request.get(`/api/jobs/${id}`)).json();
  expect(finished.llm_trace.messages[0].content).toContain("The application inserts the locked trigger");
  expect(finished.llm_trace.messages[0].content).not.toContain("Render the scene as anime/manga rather than realistic photography.");
  expect(finished.llm_trace.request_number).toBe(3); // Brainstorm, IDEAS and one body-only writer call.
  const saved = await (await request.get("/api/workspace/settings/dataset")).json();
  expect(saved.draft.trigger).toBe(trigger);
  expect(saved.draft.results[0].prompt).toBe(expected);
});
