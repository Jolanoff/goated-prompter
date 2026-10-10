import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const views = [
  ["Prompt Builder", "builder"], ["Refine", "refine"], ["MiniMax H3", "minimax"],
  ["Dataset", "dataset"], ["Saved Prompts", "saved"],
  ["Instruction presets", "directors"], ["Settings", "settings"],
];

for (const [width, height] of [[1440, 900], [1024, 900], [390, 900], [1024, 480]]) {
  test(`activity log is always accessible without a job at ${width}x${height}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    for (const [label] of views) {
      await page.getByRole("navigation", { name: "Workspace" }).getByRole("button", { name: label, exact: true }).click();
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
      const button = page.getByRole("button", { name: "View LLM activity log", exact: true });
      await expect(button).toBeVisible();
      const box = await button.boundingBox();
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(height);
      if (width > 720) {
        expect(box.x).toBeLessThan(width === 1440 ? 232 : 76);
        expect(box.y).toBeGreaterThan(height - 180);
      }
      await button.click();
      const dialog = page.getByRole("dialog", { name: "LLM activity log", exact: true });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("No generation job is available.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Close LLM activity log", exact: true }).click();
      await expect(dialog).not.toBeVisible();
    }
  });
}

test.beforeEach(async ({ request }) => {
  await request.put("/api/settings", { data: { builder: {} } });
  for (const workflow of ["refine", "minimax", "dataset"]) {
    const path = `/api/workspace/settings/${workflow}`;
    const record = await (await request.get(path)).json();
    expect((await request.put(path, { data: { revision: record.revision, draft: {} } })).ok()).toBe(true);
  }
});

for (const width of [1440, 1024, 768, 390, 360]) {
  test(`all workflows fit a ${width}px viewport with named, selected navigation`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByLabel("Describe your idea", { exact: true })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    for (const [label, id] of views) {
      const nav = page.getByRole("navigation", { name: "Workspace" });
      await nav.getByRole("button", { name: label, exact: true }).click();
      await expect(nav.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.locator("main")).toHaveAttribute("data-view", id);
      await expect(page.locator("main").getByRole("heading", { level: 2 }).first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const smallControls = await page.locator("main .control:visible").evaluateAll((nodes) =>
        nodes.filter((node) => parseFloat(getComputedStyle(node).fontSize) < 13).map((node) => node.outerHTML));
      expect(smallControls).toEqual([]);
      if (width === 1440 || width === 390) {
        await page.screenshot({ path: testInfo.outputPath(`${id}-${width}.png`), fullPage: true });
      }
    }
  });
}

for (const theme of ["dark", "light"]) for (const width of [1440, 390]) {
  test(`all workflows meet WCAG AA automated checks in ${theme} mode at ${width}px`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByLabel("Describe your idea", { exact: true })).toBeVisible();
    for (const [label] of views) {
      await page.getByRole("navigation", { name: "Workspace" }).getByRole("button", { name: label, exact: true }).click();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(results.violations, `${label}: ${JSON.stringify(results.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(({ target }) => target) })))}`).toEqual([]);
    }
  });
}

test("dark mode is the default and explicit theme choices survive reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html")).toHaveCSS("color-scheme", "dark");
  await page.getByRole("button", { name: "Switch to light mode", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveCSS("color-scheme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark mode", exact: true }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("Builder keeps the idea beside the result, and the action bar clear of the navigation rail", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const idea = await page.getByLabel("Describe your idea", { exact: true }).boundingBox();
  const result = await page.getByLabel("Generated prompt", { exact: true }).boundingBox();
  expect(result.x).toBeGreaterThan(idea.x + idea.width);
  expect(Math.abs(result.y - idea.y)).toBeLessThan(45);
  for (const width of [1440, 1100, 960, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const rail = await page.locator("aside").boundingBox();
    const actions = await page.locator(".composer-actions").boundingBox();
    if (width <= 720) {
      // Mobile pins the Builder actions to a full-width bar at the bottom of the viewport.
      expect(actions.x).toBe(0);
      expect(Math.round(actions.width)).toBe(width);
      expect(Math.round(actions.y + actions.height)).toBe(900);
    } else {
      // Desktop keeps Generate inside the idea composer, clear of the rail.
      expect(actions.x).toBeGreaterThan(rail.width);
      expect(actions.x + actions.width).toBeLessThanOrEqual(width);
    }
    await expect(page.getByRole("button", { name: /^Generate prompt/ })).toBeInViewport();
  }
});

test("keyboard skip link and save dialog are accessible and usable on mobile", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 700 });
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to workspace" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  await page.getByLabel("Generated prompt", { exact: true }).fill("A blue ceramic vase on a sunlit workbench.");
  await page.getByRole("button", { name: "Save Prompt", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Save your prompt" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Prompt name", { exact: true })).toBeFocused();
  const box = await dialog.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(700);
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("save-dialog-mobile.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

for (const theme of ["dark", "light"]) {
  test(`populated Dataset and expanded controls stay accessible in ${theme} mode`, async ({ page }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler in a blue coat.");
    await page.getByLabel("Trigger text or terms").fill("ohwx_traveler");
    await page.getByLabel("Number of prompts").selectOption("2");
    await page.getByText("Advanced options", { exact: true }).click();
    await page.getByText("Training trigger & controls", { exact: true }).click();
    await page.getByLabel(/Provide my own scene ideas/).check();
    await page.getByLabel("Guided dataset inputs").fill("standing on a platform\nreading a map");
    await generateDataset(page);
    await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/ohwx_traveler/);
    await expect(page.getByRole("region", { name: "Dataset quality report" })).toHaveCount(0);
    await openDatasetPage(page, "Scenes");
    for (const index of [1, 2]) {
      await expect(page.getByLabel(`Scene ${index} self-check`, { exact: true })).toHaveCount(0);
      await expect(page.getByRole("article", { name: `Scene ${index} card`, exact: true })
        .getByLabel("Scene: success", { exact: true })).toBeVisible();
    }
    await openDatasetPage(page, "Dataset");
    // A contrast audit during the cards' entrance fade measures transient
    // opacity, not the settled theme. Wait for finite animations/transitions.
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((animation) => animation.effect?.target?.checkVisibility() && animation.effect.getComputedTiming().iterations !== Infinity)
      .map((animation) => animation.finished.catch(() => {}))));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(results.violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`dataset-results-${theme}-mobile.png`), fullPage: true });
  });
}

test("Refine prompt, undo, instruction editor and activity log remain accessible", async ({ page, request }, testInfo) => {
  let workspace = await (await request.get("/api/workspace")).json();
  await request.post("/api/workspace", { data: { revision: workspace.revision, action: "add", prompt: "A traveler in a blue coat.", target: "Generic" } });
  workspace = await (await request.get("/api/workspace")).json();
  await request.post("/api/workspace", { data: { revision: workspace.revision, action: "add", prompt: "A traveler in a blue coat in a sunlit station.", target: "Generic", edit: true } });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Refine", exact: true }).click();
  await page.getByText("What changed", { exact: true }).click();
  await page.getByText("Refine advanced settings", { exact: true }).click();
  await expect(page.getByLabel("Refinement prompt", { exact: true })).toBeEditable();
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeEnabled();
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await page.getByLabel("Describe your idea", { exact: true }).fill("A ceramic vase on a sunlit workbench.");
  await page.getByRole("button", { name: /^Generate prompt/ }).click();
  await expect(page.getByLabel("Generated prompt", { exact: true })).toHaveValue(/ceramic vase/);
  await page.getByRole("button", { name: "View LLM activity log", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "LLM activity log" });
  await expect(dialog).toBeVisible();
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("activity-log-mobile.png") });
});
import { generateDataset, openDatasetPage } from "./datasetHelpers.js";
