import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { planDatasetScenes } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

async function openDataset(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset idea", { exact: true })).toBeVisible();
}

async function expectPage(page, name) {
  await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toHaveCount(1);
  await expect(page.getByRole("tabpanel", { name, exact: true })).toBeVisible();
}

for (const width of [1440, 390, 360]) {
  test(`Dataset polish leaves space between tab buttons at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openDataset(page);
    const tabs = await page.getByRole("tablist", { name: "Dataset pages" }).getByRole("tab").all();
    const boxes = await Promise.all(tabs.map((tab) => tab.boundingBox()));
    for (let index = 1; index < boxes.length; index++) {
      expect(boxes[index].x - boxes[index - 1].x - boxes[index - 1].width).toBeGreaterThanOrEqual(8);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`tab-spacing-${width}.png`), animations: "disabled" });
  });
}

for (const theme of ["dark", "light"]) for (const width of [1440, 390]) {
  test(`Dataset polish preserves the Advanced options background in ${theme} mode at ${width}px`, async ({ page }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width, height: 1000 });
    await openDataset(page);
    const advanced = page.locator(".dataset-advanced");
    const colors = () => advanced.evaluate((element) => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, border: style.borderTopColor };
    });
    const collapsedColors = await colors();
    await advanced.getByText("Advanced options", { exact: true }).click();
    await expect(page.getByLabel("Consistency and variation rules")).toBeVisible();
    await advanced.evaluate((element) => Promise.all(element.getAnimations()
      .map((animation) => animation.finished.catch(() => {}))));
    expect(await colors()).toEqual(collapsedColors);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`advanced-${theme}-${width}.png`), animations: "disabled", fullPage: true });
    await advanced.getByText("Advanced options", { exact: true }).click();
    await advanced.evaluate((element) => Promise.all(element.getAnimations()
      .map((animation) => animation.finished.catch(() => {}))));
    expect(await colors()).toEqual(collapsedColors);
  });
}

for (const width of [1440, 390]) {
  test(`workflow tabs show separate pages and preserve configuration at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openDataset(page);
    await expectPage(page, "Configure");
    await expect(page.getByRole("region", { name: "Scene Planner ideas" })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Dataset results" })).toHaveCount(0);
    await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
    await page.getByLabel("Trigger text or terms").fill("duck_token");
    await page.getByLabel("Number of prompts").selectOption("2");

    await page.getByRole("tab", { name: "Scenes", exact: true }).click();
    await expectPage(page, "Scenes");
    await expect(page.getByLabel("Dataset idea", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "No scenes yet", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Dataset results" })).toHaveCount(0);

    await page.getByRole("tab", { name: "Dataset", exact: true }).click();
    await expectPage(page, "Dataset");
    await expect(page.getByRole("heading", { name: "No prompts yet", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Scene Planner ideas" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`dataset-page-${width}.png`), animations: "disabled" });

    await page.getByRole("tab", { name: "Configure", exact: true }).click();
    await expectPage(page, "Configure");
    await expect(page.getByLabel("Dataset idea", { exact: true })).toHaveValue("A duck exploring a garden.");
    await expect(page.getByLabel("Trigger text or terms")).toHaveValue("duck_token");
    await expect(page.getByLabel("Number of prompts")).toHaveValue("2");
    await page.screenshot({ path: testInfo.outputPath(`configure-page-${width}.png`), animations: "disabled" });
  });
}

test("tabs support arrow keys and Home/End without leaving the selected page below", async ({ page }) => {
  await openDataset(page);
  await page.getByRole("tab", { name: "Configure", exact: true }).focus();
  for (const [key, name] of [["ArrowRight", "Scenes"], ["ArrowRight", "Dataset"],
    ["ArrowRight", "Configure"], ["End", "Dataset"], ["Home", "Configure"], ["ArrowLeft", "Dataset"]]) {
    await page.keyboard.press(key);
    await expectPage(page, name);
    await expect(page.getByRole("tab", { name, exact: true })).toBeFocused();
  }
});

test("confirmed planning and generation open their own pages without losing edits between them", async ({ page }) => {
  await openDataset(page);
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  await planDatasetScenes(page);
  await expectPage(page, "Scenes");
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expectPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/duck_token/);
  await page.getByLabel("Dataset prompt 1").fill("duck_token: my edited prompt.");
  await page.getByRole("tab", { name: "Scenes", exact: true }).click();
  await expectPage(page, "Scenes");
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveCount(0);
  await page.getByRole("tab", { name: "Configure", exact: true }).click();
  await expect(page.getByLabel("Dataset idea", { exact: true })).toHaveValue("A duck exploring a garden.");
  await page.getByRole("tab", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue("duck_token: my edited prompt.");
});
