import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.put("/api/settings", { data: { builder: {} } });
  const workspace = await (await request.get("/api/workspace")).json();
  expect((await request.post("/api/workspace", { data: { revision: workspace.revision, action: "clear_history" } })).ok()).toBe(true);
  for (const operation of ["refine", "explore"]) {
    const path = `/api/workspace/settings/${operation}`;
    const current = await (await request.get(path)).json();
    const saved = await (await request.put(path, { data: { revision: current.revision, draft: {} } })).json();
    expect((await request.post(`${path}/instructions`, { data: { revision: saved.revision, action: "reset" } })).ok()).toBe(true);
  }
});

test.afterEach(async ({ request }) => {
  const records = (await (await request.get("/api/prompts")).json()).prompts;
  for (const record of records.filter((item) => ["Workflow saved refine", "Workflow saved explore"].includes(item.title))) {
    await request.delete(`/api/prompts/${record.id}`);
  }
});

async function seedVersion(request, prompt = "A traveler in a blue coat.") {
  const workspace = await (await request.get("/api/workspace")).json();
  const response = await request.post("/api/workspace", { data: { revision: workspace.revision, action: "add", prompt,
    target: "Qwen Image", resolution: { aspect_ratio: "Custom", width: 320, height: 480 } } });
  expect(response.ok()).toBe(true);
}

test("Builder ratios and custom resolution survive reload and transfer into Explore", async ({ page, request }) => {
  await page.goto("/");
  const ratio = page.getByLabel("Builder aspect ratio", { exact: true });
  await expect(ratio.locator("option")).toHaveCount(10);
  await ratio.selectOption("9:16");
  await expect(page.getByLabel("Builder width", { exact: true })).toHaveValue("720");
  await expect(page.getByLabel("Builder height", { exact: true })).toHaveValue("1280");
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  await page.reload();
  await expect(ratio).toHaveValue("9:16");
  await ratio.selectOption("Custom");
  await page.getByLabel("Builder width", { exact: true }).fill("320");
  await page.getByLabel("Builder height", { exact: true }).fill("480");
  await page.getByLabel("Describe your idea", { exact: true }).fill("A traveler in a blue coat.");
  await page.getByRole("button", { name: /^Generate prompt/ }).click();
  await expect(page.getByLabel("Generated prompt", { exact: true })).toHaveValue(/Mock Goated Prompter/);
  const workspace = await (await request.get("/api/workspace")).json();
  expect(workspace.versions.at(-1).resolution).toEqual({ aspect_ratio: "Custom", width: 320, height: 480 });
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  await page.getByRole("button", { name: "Use Builder prompt", exact: true }).click();
  await expect(page.getByLabel("Explore width", { exact: true })).toHaveValue("320");
  await page.getByLabel("Explore target model").selectOption("Anima");
  await page.getByLabel("Direction length").selectOption("Detailed");
  await page.getByLabel("Explore lock Lighting", { exact: true }).check();
  await expect(page.getByLabel("Explore settings save status")).toHaveText("Explore settings: Saved");
  await page.reload();
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  await expect(page.getByLabel("Explore width", { exact: true })).toHaveValue("320");
  await expect(page.getByLabel("Explore height", { exact: true })).toHaveValue("480");
  await expect(page.getByLabel("Explore target model")).toHaveValue("Anima");
  await expect(page.getByLabel("Direction length")).toHaveValue("Detailed");
  await expect(page.getByLabel("Explore lock Lighting", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Idea or prompt to explore")).toHaveValue(/traveler/);
  await page.getByLabel("Explore width", { exact: true }).fill("");
  await expect(page.getByRole("button", { name: "Explore three directions" })).toBeDisabled();
  await expect(page.getByLabel("Explore settings save status")).toHaveText("Explore settings: Saved");
});

test("Refine saves requested changes, explicit locks and a manual edit draft", async ({ page, request }) => {
  await seedVersion(request);
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByLabel("Refinement instructions").fill("Keep the coat and soften the lighting.");
  await page.getByLabel("Refine lock Identity / subject", { exact: true }).uncheck();
  await page.getByLabel("Refine lock Outfit", { exact: true }).check();
  await page.getByRole("button", { name: "Edit text", exact: true }).click();
  await page.getByLabel("Manual prompt edit").fill("An unfinished manual edit I want to keep.");
  await expect(page.getByLabel("Refine settings save status")).toHaveText("Refine settings: Saved");
  await page.reload();
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await expect(page.getByLabel("Refinement instructions")).toHaveValue("Keep the coat and soften the lighting.");
  await expect(page.getByLabel("Refine lock Identity / subject", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("Refine lock Outfit", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Manual prompt edit")).toHaveValue("An unfinished manual edit I want to keep.");
  await page.getByRole("button", { name: "Cancel edit", exact: true }).click();
});

test("advanced instructions save independently and can return to built-in behavior", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByText("Refine advanced settings", { exact: true }).click();
  await page.getByLabel("Refine system prompt", { exact: true }).fill("Keep edits concise and grounded in the source.");
  await page.getByRole("button", { name: "Save Refine instructions", exact: true }).click();
  await expect(page.getByRole("paragraph").filter({ hasText: /^Using saved custom instructions$/ })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByText("Refine advanced settings", { exact: true }).click();
  await expect(page.getByLabel("Refine system prompt", { exact: true })).toHaveValue("Keep edits concise and grounded in the source.");
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  await page.getByText("Explore advanced settings", { exact: true }).click();
  await page.getByLabel("Explore instruction section").selectOption("creative");
  await page.getByLabel("Explore system prompt", { exact: true }).fill("Explore silhouettes and strong graphic framing.");
  await page.getByRole("button", { name: "Save Explore instructions", exact: true }).click();
  await expect(page.getByRole("paragraph").filter({ hasText: /^Using saved custom instructions$/ })).toBeVisible();
  const settings = await (await request.get("/api/workspace/settings/explore")).json();
  expect(settings.instructions.creative).toBe("Explore silhouettes and strong graphic framing.");
  expect(settings.instructions.system).toBe(settings.defaults.system);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Use built-in Explore instructions", exact: true }).click();
  await expect(page.getByLabel("Explore system prompt", { exact: true })).toHaveValue(settings.defaults.creative);
  expect((await (await request.get("/api/workspace/settings/refine")).json()).instructions.system).toBe("Keep edits concise and grounded in the source.");
});

test("Save prompt uses the selected Refine or Explore output and its target and resolution", async ({ page, request }) => {
  await seedVersion(request, "The exact Refine result to save.");
  await page.goto("/");
  await page.getByLabel("Generated prompt", { exact: true }).fill("Unrelated Builder output.");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByRole("button", { name: "Save prompt", exact: true }).click();
  await page.getByLabel("Prompt name", { exact: true }).fill("Workflow saved refine");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  await page.getByLabel("Idea or prompt to explore").fill("A lighthouse above the ocean.");
  await page.getByLabel("Explore target model").selectOption("Anima");
  await page.getByLabel("Explore aspect ratio", { exact: true }).selectOption("21:9");
  await page.getByRole("button", { name: "Explore three directions" }).click();
  await expect(page.getByRole("button", { name: "Explore three directions" })).toBeEnabled();
  const card = page.getByRole("article", { name: "Creative direction", exact: true });
  await expect(card.getByLabel("Creative prompt", { exact: true })).toContainText("lighthouse");
  const selected = await card.getByLabel("Creative prompt", { exact: true }).textContent();
  await card.getByRole("button", { name: "Save prompt", exact: true }).click();
  await page.getByLabel("Prompt name", { exact: true }).fill("Workflow saved explore");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  const records = (await (await request.get("/api/prompts")).json()).prompts;
  expect(records.find((item) => item.title === "Workflow saved refine")).toMatchObject({ prompt: "The exact Refine result to save.", target: "Qwen Image", resolution: { width: 320, height: 480 } });
  expect(records.find((item) => item.title === "Workflow saved explore")).toMatchObject({ prompt: selected, target: "Anima", resolution: { width: 1680, height: 720 } });
  await page.getByRole("button", { name: /Saved Prompts/ }).click();
  await expect(page.getByRole("heading", { name: "Workflow saved refine", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Workflow saved explore", exact: true })).toBeVisible();
});

test("failed workflow autosave retains inputs, retries and blocks stale-tab overwrite", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore", exact: true }).click();
  await page.route("**/api/workspace/settings/explore", (route) => route.request().method() === "PUT"
    ? route.fulfill({ status: 503, json: { error: "Disk offline" } }) : route.continue());
  await page.getByLabel("Idea or prompt to explore").fill("Keep my draft after a failed write.");
  await expect(page.getByRole("alert")).toContainText("Disk offline");
  await expect(page.getByLabel("Idea or prompt to explore")).toHaveValue("Keep my draft after a failed write.");
  await page.unroute("**/api/workspace/settings/explore");
  await page.getByRole("button", { name: "Retry Explore save", exact: true }).click();
  await expect(page.getByLabel("Explore settings save status")).toHaveText("Explore settings: Saved");
  const saved = await (await request.get("/api/workspace/settings/explore")).json();
  await request.put("/api/workspace/settings/explore", { data: { revision: saved.revision, draft: { ...saved.draft, base: "Changed in another tab." } } });
  await page.getByLabel("Idea or prompt to explore").fill("My local conflicting edit.");
  await expect(page.getByRole("alert")).toContainText("changed in another tab");
  await expect(page.getByLabel("Idea or prompt to explore")).toHaveValue("My local conflicting edit.");
  expect((await (await request.get("/api/workspace/settings/explore")).json()).draft.base).toBe("Changed in another tab.");
});
