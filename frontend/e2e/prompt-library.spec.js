import { test, expect } from "@playwright/test";

async function snapshot(request, target) {
  const response = await request.get(`/api/prompt-library?target=${encodeURIComponent(target)}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function add(request, target, prompt) {
  const state = await snapshot(request, target);
  const response = await request.post(`/api/prompt-library?target=${encodeURIComponent(target)}`, {
    data: { revision: state.revision, prompt },
  });
  expect(response.ok()).toBe(true);
}

async function openLibrary(page, target = "Anima") {
  await page.goto("/");
  await page.getByRole("button", { name: "Prompt Library", exact: true }).click();
  await page.getByLabel("Library target model").selectOption(target);
  await expect(page.getByRole("heading", { name: `${target} prompts`, exact: true })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  expect((await request.put("/api/settings", { data: { builder: { target_model: "Generic" } } })).ok()).toBe(true);
  for (const target of ["Anima", "Generic", "Krea 2"]) {
    let state = await snapshot(request, target);
    while (state.prompts.length) {
      const response = await request.delete(`/api/prompt-library?target=${encodeURIComponent(target)}`, {
        data: { revision: state.revision, index: 0 },
      });
      expect(response.ok()).toBe(true);
      state = await response.json();
    }
  }
});

test("compact library adds, edits, persists, separates targets and confirms deletion", async ({ page, request }) => {
  const prompt = "1girl, kitchen, cooking, apron, steam\n\nA cook stirs soup beside a sunny window.";
  await add(request, "Anima", prompt);
  await openLibrary(page);
  const heading = await page.getByRole("heading", { name: "Prompt Library", exact: true }).boundingBox();
  const sidebar = await page.locator(".sidebar").boundingBox();
  expect(heading.x).toBeGreaterThanOrEqual(sidebar.x + sidebar.width);
  const rows = page.locator(".library-row");
  await expect(rows).toHaveCount(1);
  expect((await rows.first().boundingBox()).height).toBeLessThanOrEqual(80);
  await page.getByRole("button", { name: "New prompt", exact: true }).click();
  await page.getByLabel("Library prompt", { exact: true }).fill("A café at dusk.\n\nWarm light on wet cobblestones.");
  await page.getByRole("button", { name: "Add prompt", exact: true }).click();
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "Edit prompt 1", exact: true }).click();
  await expect(page.getByLabel("Library prompt", { exact: true })).toHaveValue(prompt);
  const edited = "1girl, library, reading, window, rain\n\nA reader turns a page.";
  await page.getByLabel("Library prompt", { exact: true }).fill(edited);
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(rows.first()).toContainText("A reader turns a page.");
  await page.reload();
  await page.getByRole("button", { name: "Prompt Library", exact: true }).click();
  await page.getByLabel("Library target model").selectOption("Anima");
  await expect(rows).toHaveCount(2);
  expect((await snapshot(request, "Anima")).prompts[0]).toBe(edited);
  await page.getByLabel("Library target model").selectOption("Krea 2");
  await expect(page.getByRole("heading", { name: "No prompts for Krea 2 yet" })).toBeVisible();
  await page.getByRole("button", { name: "Add your first prompt" }).click();
  await page.getByLabel("Library prompt", { exact: true }).fill("Subject and action:\nA courier sprints.\n\nLighting:\nNoon sun.");
  await page.getByRole("button", { name: "Add prompt", exact: true }).click();
  await expect(rows).toHaveCount(1);
  await page.getByLabel("Library target model").selectOption("Anima");
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "Delete prompt 1", exact: true }).click();
  await page.locator(".library-delete-confirm").getByRole("button", { name: "Cancel" }).click();
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "Delete prompt 1", exact: true }).click();
  await page.getByRole("button", { name: "Delete prompt", exact: true }).click();
  await expect(rows).toHaveCount(1);
  expect((await snapshot(request, "Anima")).prompts).not.toContain(edited);
  await page.getByRole("button", { name: "Delete prompt 1", exact: true }).click();
  await page.getByRole("button", { name: "Delete prompt", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No prompts for Anima yet" })).toBeVisible();
});

test("failed saves keep drafts across tabs and warn before switching targets", async ({ page, request }) => {
  await add(request, "Anima", "Original prompt.");
  await openLibrary(page);
  await page.getByRole("button", { name: "Edit prompt 1", exact: true }).click();
  await page.getByLabel("Library prompt", { exact: true }).fill("My unsaved writing style.");
  await page.route("**/api/prompt-library?*", (route) => route.request().method() === "PUT"
    ? route.fulfill({ status: 503, json: { error: "Disk offline." } }) : route.continue());
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Draft kept");
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await page.getByRole("button", { name: "Prompt Library", exact: true }).click();
  await expect(page.getByLabel("Library prompt", { exact: true })).toHaveValue("My unsaved writing style.");
  expect(await page.evaluate(() => !window.dispatchEvent(new Event("beforeunload", { cancelable: true })))).toBe(true);
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByLabel("Library target model").selectOption("Generic");
  await expect(page.getByLabel("Library target model")).toHaveValue("Anima");
  await expect(page.getByLabel("Library prompt", { exact: true })).toHaveValue("My unsaved writing style.");
  expect((await snapshot(request, "Anima")).prompts).toEqual(["Original prompt."]);
});

test("stale saves do not overwrite changes from another editor", async ({ page, request }) => {
  await add(request, "Anima", "Original prompt.");
  await openLibrary(page);
  await page.getByRole("button", { name: "Edit prompt 1", exact: true }).click();
  await page.getByLabel("Library prompt", { exact: true }).fill("My stale draft.");
  await add(request, "Anima", "New example from another editor.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("changed elsewhere");
  await expect(page.getByLabel("Library prompt", { exact: true })).toHaveValue("My stale draft.");
  expect((await snapshot(request, "Anima")).prompts).toEqual(["Original prompt.", "New example from another editor."]);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("alert").getByRole("button", { name: "Reload library" }).click();
  await expect(page.locator(".library-row")).toHaveCount(2);
  await expect(page.getByLabel("Library prompt", { exact: true })).toHaveCount(0);
});

test("dense rows and inline editing fit mobile in both themes", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (let index = 0; index < 8; index += 1) {
    await add(request, "Anima", `Prompt ${index + 1}: ${"A long example with tags and paragraphs. ".repeat(12)}`);
  }
  await openLibrary(page);
  for (const theme of ["dark", "light"]) {
    await page.setViewportSize({ width: theme === "dark" ? 390 : 320, height: 844 });
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await page.locator(".library-row").first().boundingBox()).height).toBeLessThanOrEqual(80);
    if (theme === "dark") await page.getByRole("button", { name: "Switch to light mode" }).click();
  }
  await page.getByRole("button", { name: "Open prompt 1", exact: true }).click();
  await expect(page.getByLabel("Library prompt", { exact: true })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("Library prompt", { exact: true }).fill("Mobile edit.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator(".library-row").first()).toContainText("Mobile edit.");
});

test("a late target response cannot replace the currently selected library", async ({ page, request }) => {
  await add(request, "Anima", "Anima example.");
  await add(request, "Generic", "Generic example.");
  await openLibrary(page, "Generic");
  let release;
  const deferred = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/prompt-library?target=Anima", async (route) => {
    await deferred;
    await route.continue();
  });
  const pending = page.waitForRequest("**/api/prompt-library?target=Anima");
  await page.getByLabel("Library target model").selectOption("Anima");
  await pending;
  await page.getByLabel("Library target model").selectOption("Generic");
  await expect(page.locator(".library-row")).toContainText("Generic example.");
  const finished = page.waitForResponse("**/api/prompt-library?target=Anima");
  release();
  await finished;
  await expect(page.getByLabel("Library target model")).toHaveValue("Generic");
  await expect(page.locator(".library-row")).toContainText("Generic example.");
  await expect(page.locator(".library-row")).not.toContainText("Anima example.");
});
