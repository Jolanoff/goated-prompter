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

test("pasted prompts refine directly in one editable box without a starting-prompt step", async ({ page, request }) => {
  await openRefine(page);
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  await expect(prompt).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Start refining", exact: true })).toHaveCount(0);
  await prompt.fill("A traveler in a red coat under soft light.");
  await page.getByLabel("Prompt target").selectOption("Qwen Image (original)");
  await page.getByRole("button", { name: "Wider shot", exact: true }).click();
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(prompt).toHaveValue(/\[Mock Goated Prompter\]/);
  let stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(2);
  expect(stored.versions[0].prompt).toBe("A traveler in a red coat under soft light.");
  expect(stored.versions[1].parent_id).toBe(stored.versions[0].id);
  await page.getByText("What changed", { exact: true }).click();
  await expect(page.getByLabel("Prompt changes")).toContainText("A traveler in a red coat under soft light.");
  await prompt.fill("A different copied prompt: a café beside a quiet harbor.");
  await page.getByLabel("Refinement instructions").fill("Add morning mist.");
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(prompt).toHaveValue(/\[Mock Goated Prompter\]/);
  stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(4);
  expect(stored.versions[2].prompt).toBe("A different copied prompt: a café beside a quiet harbor.");
  expect(stored.versions[3].parent_id).toBe(stored.versions[2].id);
  expect(stored.versions[3].instruction).toBe("Add morning mist.");
});

test("Builder handoff fills the same editable prompt box and carries its target", async ({ page, request }) => {
  const state = await (await request.get("/api/workspace")).json();
  await request.post("/api/workspace", { data: { revision: state.revision, action: "add",
    prompt: "Previous Refine result.", target: "Generic" } });
  await page.goto("/");
  await page.getByLabel("Generated prompt", { exact: true }).fill("Exact Builder prompt.\n\nKeep both paragraphs.");
  await page.getByLabel("Target model", { exact: true }).selectOption("LTX 2.5");
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  await expect(prompt).toHaveValue("Exact Builder prompt.\n\nKeep both paragraphs.");
  await expect(page.getByLabel("Prompt target")).toHaveValue("LTX 2.5");
  await prompt.fill("A copied prompt pasted directly into the same box.");
  await page.getByLabel("Refinement instructions").fill("Keep the subject and soften the light.");
  await expect(page.getByRole("button", { name: "Refine prompt", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await expect(prompt).toHaveValue("A copied prompt pasted directly into the same box.");
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await page.getByLabel("Generated prompt", { exact: true }).fill("Another Builder prompt.");
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(prompt).toHaveValue("Another Builder prompt.");
});

test("clearing a saved prompt keeps the box empty when its target changes", async ({ page, request }) => {
  const state = await (await request.get("/api/workspace")).json();
  await request.post("/api/workspace", { data: { revision: state.revision, action: "add",
    prompt: "Saved prompt that must not come back after clearing.", target: "Generic" } });
  await openRefine(page);
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  await prompt.fill("");
  await page.getByLabel("Prompt target").selectOption("Anima");
  await expect(prompt).toHaveValue("");
  await page.getByLabel("Refinement instructions").fill("Wider framing.");
  await expect(page.getByRole("button", { name: "Refine prompt", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Wider shot", exact: true })).toBeEnabled();
});

for (const [operation, label] of [["workspace", "source save"], ["workspace/refine", "refinement admission"]]) {
test(`failed ${label} keeps the exact prompt and requested changes`, async ({ page }) => {
  await openRefine(page);
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  const source = "A cyclist under the rain.\n\nNeon reflected in the street.";
  await prompt.fill(source);
  await page.getByLabel("Refinement instructions").fill("Make the scene a little brighter.");
  await page.route(`**/api/${operation}`, (route) => route.request().method() === "POST"
    ? route.fulfill({ status: 503, json: { error: "Backend temporarily unavailable." } }) : route.continue());
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Backend temporarily unavailable");
  await expect(prompt).toHaveValue(source);
  await expect(page.getByLabel("Refinement instructions")).toHaveValue("Make the scene a little brighter.");
});
}

test("refinement, direct editing, diff and undo persist without history controls", async ({ page, request }, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openRefine(page);
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  await prompt.fill("A traveler in a red coat under soft light.");
  await page.getByLabel("Prompt target").selectOption("Qwen Image (original)");
  await page.getByRole("button", { name: "Wider shot", exact: true }).click();
  await page.getByLabel("Refine lock Outfit", { exact: true }).check();
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(prompt).toHaveValue(/\[Mock Goated Prompter\]/);
  await page.getByText("What changed", { exact: true }).click();
  await expect(page.getByLabel("Prompt changes")).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(prompt).toHaveValue("A traveler in a red coat under soft light.");
  await expect(page.getByRole("button", { name: "Redo", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Version history" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Version history" })).toHaveCount(0);
  await prompt.fill("A traveler in a blue coat under soft light.");
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(prompt).toHaveValue(/\[Mock Goated Prompter\]/);
  const refined = await prompt.inputValue();
  await page.reload();
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await expect(prompt).toHaveValue(refined);
  const stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(4);
  expect(stored.versions[1].locks).toEqual(["identity", "outfit"]);
  expect(stored.versions[1].target).toBe("Qwen Image (original)");
  expect(stored.versions[2].parent_id).toBe(stored.versions[0].id);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(prompt).toHaveValue("A traveler in a blue coat under soft light.");
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("refine-workspace.png"), fullPage: true });
});

test("stale tab gets a conflict without losing its input or overwriting history", async ({ page, request }) => {
  await openRefine(page);
  const prompt = page.getByLabel("Refinement prompt", { exact: true });
  await prompt.fill("My unsaved starting prompt");
  await page.getByLabel("Refinement instructions").fill("Soften the light.");
  const initial = await (await request.get("/api/workspace")).json();
  expect((await request.post("/api/workspace", { data: { revision: initial.revision, action: "add", prompt: "Other tab's prompt", target: "Generic" } })).ok()).toBe(true);
  await page.getByRole("button", { name: "Refine prompt", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Workspace changed in another tab");
  await expect(prompt).toHaveValue("My unsaved starting prompt");
  const stored = await (await request.get("/api/workspace")).json();
  expect(stored.versions).toHaveLength(1);
  expect(stored.versions[0].prompt).toBe("Other tab's prompt");
});

test("new tabs stay usable on mobile without horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openRefine(page);
  await page.getByLabel("Refinement prompt", { exact: true }).fill("A portrait with a long descriptive scene.");
  await expect(page.getByLabel("Refinement prompt", { exact: true })).toBeVisible();
  for (const name of ["Refine", "Settings", "Prompt Builder"]) {
    await page.getByRole("button", { name, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
