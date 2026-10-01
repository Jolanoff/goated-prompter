import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.put("/api/settings", { data: { builder: {} } });
  const workspace = await (await request.get("/api/workspace")).json();
  expect((await request.post("/api/workspace", { data: { revision: workspace.revision, action: "clear_history" } })).ok()).toBe(true);
  const path = "/api/workspace/settings/refine";
  const current = await (await request.get(path)).json();
  const saved = await (await request.put(path, { data: { revision: current.revision, draft: {} } })).json();
  expect((await request.post(`${path}/instructions`, { data: { revision: saved.revision, action: "reset" } })).ok()).toBe(true);
});

test.afterEach(async ({ request }) => {
  const records = (await (await request.get("/api/prompts")).json()).prompts;
  for (const record of records.filter((item) => item.title === "Workflow saved refine")) {
    await request.delete(`/api/prompts/${record.id}`);
  }
});

async function seedVersion(request, prompt = "A traveler in a blue coat.") {
  const workspace = await (await request.get("/api/workspace")).json();
  const response = await request.post("/api/workspace", { data: {
    revision: workspace.revision, action: "add", prompt, target: "Qwen Image",
  } });
  expect(response.ok()).toBe(true);
}

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
});

test("advanced Refine instructions save and reset independently", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByText("Refine advanced settings", { exact: true }).click();
  await page.getByLabel("Refine system prompt", { exact: true }).fill("Keep edits concise and grounded in the source.");
  await page.getByRole("button", { name: "Save Refine instructions", exact: true }).click();
  expect((await (await request.get("/api/workspace/settings/refine")).json()).instructions.system)
    .toBe("Keep edits concise and grounded in the source.");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Use built-in Refine instructions", exact: true }).click();
  await expect(page.getByRole("paragraph").filter({ hasText: /^Using built-in instructions$/ })).toBeVisible();
});

test("Save prompt uses the selected Refine output and target", async ({ page, request }) => {
  await seedVersion(request, "The exact Refine result to save.");
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByRole("button", { name: "Save prompt", exact: true }).click();
  await page.getByLabel("Prompt name", { exact: true }).fill("Workflow saved refine");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const records = (await (await request.get("/api/prompts")).json()).prompts;
  expect(records.find((item) => item.title === "Workflow saved refine"))
    .toMatchObject({ prompt: "The exact Refine result to save.", target: "Qwen Image" });
});

test("failed Refine autosave retains input and retries", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.route("**/api/workspace/settings/refine", (route) => route.request().method() === "PUT"
    ? route.fulfill({ status: 503, json: { error: "Disk offline" } }) : route.continue());
  await page.getByLabel("Starting prompt", { exact: true }).fill("Keep my draft after a failed write.");
  await expect(page.getByRole("alert")).toContainText("Disk offline");
  await expect(page.getByLabel("Starting prompt", { exact: true })).toHaveValue("Keep my draft after a failed write.");
  await page.unroute("**/api/workspace/settings/refine");
  await page.getByRole("button", { name: "Retry Refine save", exact: true }).click();
  await expect(page.getByLabel("Refine settings save status")).toHaveText("Refine settings: Saved");
});
