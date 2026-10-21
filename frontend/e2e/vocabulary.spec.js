import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ request }) => {
  const path = "/api/workspace/settings/dataset";
  const current = await (await request.get(path)).json();
  expect((await request.put(path, { data: { revision: current.revision, draft: {} } })).ok()).toBe(true);
});

test("the Vocabulary tab lists every registered category and its packs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Vocabulary", exact: true })).toBeVisible();
  for (const name of ["Subjects", "Spaces", "Actions & Poses", "Effects & Atmosphere"]) {
    await expect(page.getByRole("region", { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "Spaces", exact: true }).getByRole("heading", { name: "Fantasy" })).toBeVisible();
});

test("the Vocabulary Library searches, previews, and applies or discards a selection", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  const library = page.getByRole("dialog", { name: "Vocabulary Library" });
  await expect(library).toBeVisible();
  await library.getByLabel("Search vocabulary").fill("floating castle");
  await expect(library.getByRole("checkbox")).toHaveCount(1);
  await library.getByRole("button", { name: "Preview Fantasy (Spaces)" }).click();
  await expect(library.getByRole("region", { name: "Pack Preview" })).toContainText("enchanted forest");
  await expect(library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" })).not.toBeChecked();
  await library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" }).check();
  await library.getByLabel("Search vocabulary").fill("");
  await library.getByRole("button", { name: "Lighting", exact: true }).click();
  await library.getByRole("checkbox", { name: "Select Cinematic (Lighting)" }).check();
  await library.getByRole("button", { name: "All", exact: true }).click();
  await expect(library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" })).toBeChecked();
  await expect(library.getByRole("heading", { name: "Selected Packs (2)" })).toBeVisible();
  await expect(library.getByRole("button", { name: "Remove Fantasy (Spaces)" })).toBeVisible();
  await library.getByRole("button", { name: "Apply (2)", exact: true }).click();
  await expect(library).not.toBeVisible();
  const selection = page.getByRole("region", { name: "Vocabulary", exact: true }).locator(".pack-picker-help");
  await expect(selection).toHaveText("Selected: Fantasy, Cinematic");

  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  await library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" }).uncheck();
  await library.getByRole("button", { name: "Cancel" }).click();
  await expect(library).not.toBeVisible();
  await expect(selection).toHaveText("Selected: Fantasy, Cinematic");
  await expect.poll(async () => {
    const record = await (await request.get("/api/workspace/settings/dataset")).json();
    return record.draft.vocabulary_packs;
  }).toEqual(["Spaces/Fantasy", "Lighting/Cinematic"]);
});

test("the library sorts, expands entries, browses related packs and clears staged selections", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  const library = page.getByRole("dialog", { name: "Vocabulary Library" });
  await library.getByRole("button", { name: "Spaces", exact: true }).click();
  await library.getByLabel("Sort vocabulary packs").selectOption("name");
  const rows = library.getByRole("region", { name: "Available Packs" }).getByRole("listitem");
  await expect(rows.first()).toContainText("Fantasy");
  await library.getByRole("button", { name: "Preview Fantasy (Spaces)" }).click();
  const preview = library.getByRole("region", { name: "Pack Preview" });
  await expect(preview.getByText("Showing 12 of 20", { exact: true })).toBeVisible();
  await preview.getByRole("button", { name: "Show all entries" }).click();
  await expect(preview.getByText("Showing 20 of 20", { exact: true })).toBeVisible();
  await preview.getByRole("button", { name: "Show fewer entries" }).click();
  await expect(preview.getByText("Showing 12 of 20", { exact: true })).toBeVisible();
  await preview.getByRole("button", { name: "Select Historical (Spaces)" }).click();
  await expect(library.getByRole("checkbox", { name: "Select Historical (Spaces)" })).toBeChecked();
  await preview.getByRole("button", { name: "Preview related Historical (Spaces)" }).click();
  await expect(preview.getByRole("heading", { name: "Historical", exact: true })).toBeVisible();
  await preview.getByRole("button", { name: "View all related packs" }).click();
  await expect(library.getByRole("button", { name: "Spaces", exact: true })).toHaveAttribute("aria-pressed", "true");
  await library.getByRole("button", { name: "Remove Historical (Spaces)" }).click();
  await expect(library.getByRole("checkbox", { name: "Select Historical (Spaces)" })).not.toBeChecked();
  await library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" }).check();
  await library.getByRole("button", { name: "Clear all" }).click();
  await expect(library.getByRole("heading", { name: "Selected Packs (0)" })).toBeVisible();
  await library.getByLabel("Search vocabulary").fill("no matching vocabulary pack");
  await expect(library.getByText("No packs match your search.")).toBeVisible();
  await expect(preview).toContainText("Choose another search or category to find a pack.");
  await library.getByRole("button", { name: "Reset filters" }).click();
  await expect(library.getByRole("checkbox")).toHaveCount(63);
  await library.getByRole("checkbox", { name: "Select Humans (Subjects)" }).check();
  await library.getByLabel("Sort vocabulary packs").selectOption("entries");
  await expect(rows.first()).toContainText("Humans");
  await page.keyboard.press("Escape");
  await expect(library).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Vocabulary Library" })).toBeFocused();
  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  await expect(library.getByRole("heading", { name: "Selected Packs (0)" })).toBeVisible();
  await expect(library.getByLabel("Search vocabulary")).toHaveValue("");
  await library.getByRole("button", { name: "Apply (0)", exact: true }).click();
  await expect(page.getByRole("region", { name: "Vocabulary", exact: true }).locator(".pack-picker-help"))
    .toHaveText("No packs selected: scenes come from your request alone.");
});

for (const width of [1448, 1024, 768, 390, 320]) {
  test(`the library stays usable at ${width}px in both themes`, async ({ page }) => {
    const height = width === 320 ? 640 : width === 390 ? 844 : 1086;
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await page.getByRole("button", { name: "Vocabulary Library" }).click();
    const library = page.getByRole("dialog", { name: "Vocabulary Library" });
    await library.getByRole("button", { name: "Subjects", exact: true }).click();
    await library.getByRole("checkbox", { name: "Select Humans (Subjects)" }).check();
    await library.getByRole("checkbox", { name: "Select Men (Subjects)" }).check();
    await library.getByRole("checkbox", { name: "Select Women (Subjects)" }).check();
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      const bounds = await library.boundingBox();
      expect(bounds.x).toBeGreaterThanOrEqual(8);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8);
      expect(bounds.y).toBeGreaterThanOrEqual(8);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(height - 8);
      expect(await library.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      expect(await library.locator(".vocabulary-library-categories").evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      await expect(library.getByRole("button", { name: "Apply (3)", exact: true })).toBeInViewport();
      await expect(library).toHaveCSS("background-color", theme === "dark" ? "rgb(26, 26, 24)" : "rgb(255, 255, 255)");
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: test.info().outputPath(`library-${width}-${theme}.png`), animations: "disabled" });
      const accessibility = await new AxeBuilder({ page }).include(".vocabulary-library")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(accessibility.violations).toEqual([]);
    }
  });
}

test("the reference layout previews entries and keeps keyboard selection inside the dialog", async ({ page }) => {
  await page.setViewportSize({ width: 1448, height: 1086 });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  const library = page.getByRole("dialog", { name: "Vocabulary Library" });
  await expect(library.getByLabel("Search vocabulary")).toBeFocused();
  await library.getByRole("button", { name: "Expressions", exact: true }).click();
  await library.getByRole("button", { name: "Preview Happy Expressions (Expressions)" }).click();
  const checkbox = library.getByRole("checkbox", { name: "Select Happy Expressions (Expressions)" });
  await checkbox.focus();
  await page.keyboard.press("Space");
  await expect(checkbox).toBeChecked();
  await page.keyboard.press("Space");
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await library.getByRole("button", { name: "Select Angry Expressions (Expressions)" }).click();
  await library.getByRole("button", { name: "All", exact: true }).click();
  await library.getByRole("button", { name: "Apply (2)", exact: true }).focus();
  for (const [key, name] of [["Tab", "Close Vocabulary Library"], ["Shift+Tab", "Apply (2)"]]) {
    await page.keyboard.press(key);
    // A native dialog may visit browser chrome before wrapping to its first or last control.
    if (await page.evaluate(() => document.activeElement === document.body)) await page.keyboard.press(key);
    await expect(library.getByRole("button", { name, exact: true })).toBeFocused();
  }
  await page.evaluate(() => document.fonts.ready);
  await library.getByRole("region", { name: "Pack Preview" }).evaluate((node) => { node.scrollTop = 0; });
  await page.mouse.move(0, 0);
  await page.screenshot({ path: test.info().outputPath("vocabulary-library-desktop.png"), animations: "disabled" });
});

for (const [width, height] of [[1448, 1086], [1366, 768], [1280, 720], [1920, 1080]]) {
  test(`the compact desktop library fits every section at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await page.getByRole("button", { name: "Vocabulary Library" }).click();
    const library = page.getByRole("dialog", { name: "Vocabulary Library" });
    const bounds = await library.boundingBox();
    expect(bounds.width).toBeLessThanOrEqual(1180);
    expect(bounds.height).toBeLessThanOrEqual(820);
    const categories = library.getByRole("group", { name: "Vocabulary category" });
    expect(await categories.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    const alignment = await categories.evaluate((node) => {
      const buttons = [...node.querySelectorAll("button")];
      return {
        rows: new Set(buttons.map((button) => Math.round(button.getBoundingClientRect().top))).size,
        growing: buttons.some((button) => getComputedStyle(button).flexGrow !== "0"),
        rightGap: node.getBoundingClientRect().right - parseFloat(getComputedStyle(node).paddingRight)
          - buttons.at(-1).getBoundingClientRect().right,
      };
    });
    expect(alignment.rows).toBe(1);
    expect(alignment.growing).toBe(false);
    expect(Math.abs(alignment.rightGap)).toBeLessThanOrEqual(1);
    for (const button of await categories.getByRole("button").all()) await expect(button).toBeInViewport();
    await library.getByRole("button", { name: "Preview Happy Expressions (Expressions)" }).click();
    const preview = library.getByRole("region", { name: "Pack Preview" });
    expect(await preview.evaluate((node) => node.scrollHeight <= node.clientHeight)).toBe(true);
    await expect(preview.locator(".vocabulary-library-entry-list > li")).toHaveCount(12);
    await expect(preview.locator(".vocabulary-library-related-list > li")).toHaveCount(4);
    const box = await preview.boundingBox();
    for (const item of await preview.locator(".vocabulary-library-entry-list > li, .vocabulary-library-related-list > li").all()) {
      const rect = await item.boundingBox();
      expect(rect.height).toBeGreaterThanOrEqual(24);
      expect(rect.y + rect.height).toBeLessThanOrEqual(box.y + box.height);
    }
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: test.info().outputPath(`compact-${width}-${height}.png`), animations: "disabled" });
  });
}
