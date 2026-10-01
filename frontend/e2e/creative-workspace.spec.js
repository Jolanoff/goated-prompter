import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  for (const operation of ["refine"]) {
    const path = `/api/workspace/settings/${operation}`;
    const settings = await (await request.get(path)).json();
    const saved = await (await request.put(path, { data: { revision: settings.revision, draft: {} } })).json();
    expect((await request.post(`${path}/instructions`, { data: { revision: saved.revision, action: "reset" } })).ok()).toBe(true);
  }
  let snapshot = await (await request.get("/api/workspace")).json();
  const cleared = await request.post("/api/workspace", { data: { action: "clear_history", revision: snapshot.revision } });
  expect(cleared.ok()).toBe(true);
  expect((await request.put("/api/settings", { data: { builder: {} } })).ok()).toBe(true);
});

async function openRefine(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Refine your prompt", exact: true })).toBeVisible();
}

test("refinement, manual edit, diff, undo/redo and branch history persist", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openRefine(page);
  await page.getByLabel("Starting prompt", { exact: true }).fill("A traveler in a red coat under soft light.");
  await page.getByLabel("Starting prompt target").selectOption("Qwen Image");
  await page.getByRole("button", { name: "Start refining", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("A traveler in a red coat under soft light.");
  await page.getByRole("button", { name: "Wider shot", exact: true }).click();
  await page.getByLabel("Refine lock Outfit", { exact: true }).check();
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toContainText("[Mock Goated Prompter]");
  const refined = await page.getByLabel("Current refinement prompt").textContent();
  await page.getByText("What changed", { exact: true }).click();
  await expect(page.getByLabel("Prompt changes")).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("A traveler in a red coat under soft light.");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText(refined);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("A traveler in a red coat under soft light.");
  await page.getByRole("button", { name: "Edit text", exact: true }).click();
  await page.getByLabel("Manual prompt edit").fill("A traveler in a blue coat under soft light.");
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("A traveler in a blue coat under soft light.");
  await expect(page.getByRole("button", { name: "Redo", exact: true })).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("A traveler in a blue coat under soft light.");
  await expect(page.getByRole("button", { name: /v2 · Refinement/ })).toBeVisible();
  const stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(3);
  expect(stored.versions[1].locks).toEqual(["identity", "outfit"]);
  expect(stored.versions[1].target).toBe("Qwen Image");
  expect(stored.versions[2].parent_id).toBe(stored.versions[0].id);
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/refine-workspace.png", fullPage: true });
});

test("stale tab gets a conflict without losing its input or overwriting history", async ({ page, request }) => {
  await openRefine(page);
  await page.getByLabel("Starting prompt", { exact: true }).fill("My unsaved starting prompt");
  const initial = await (await request.get("/api/workspace")).json();
  expect((await request.post("/api/workspace", { data: { revision: initial.revision, action: "add", prompt: "Other tab's prompt", target: "Generic" } })).ok()).toBe(true);
  await page.getByRole("button", { name: "Start refining", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Workspace changed in another tab");
  if (!(await page.getByLabel("Starting prompt", { exact: true }).isVisible())) {
    await page.getByText("Start from another prompt", { exact: true }).click();
  }
  await expect(page.getByLabel("Starting prompt", { exact: true })).toHaveValue("My unsaved starting prompt");
  await expect(page.getByLabel("Current refinement prompt")).toHaveText("Other tab's prompt");
  const stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(1);
});

test("new tabs stay usable on mobile without horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openRefine(page);
  await page.getByLabel("Starting prompt", { exact: true }).fill("A portrait with a long descriptive scene.");
  await page.getByRole("button", { name: "Start refining", exact: true }).click();
  await expect(page.getByLabel("Current refinement prompt")).toBeVisible();
  for (const name of ["Refine", "Settings", "Prompt Builder"]) {
    await page.getByRole("button", { name, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
