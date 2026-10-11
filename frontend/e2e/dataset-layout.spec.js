import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { confirmDatasetReview, generateDataset, openDatasetPage } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

for (const width of [1920, 1440, 1100, 768, 390, 360]) {
  test(`Dataset cards remain readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler exploring exhibits.");
    await page.getByLabel("Trigger text or terms").fill("traveler_token");
    await page.getByLabel("Number of prompts").selectOption("2");
    const style = page.getByLabel("Dataset visual style", { exact: true });
    await expect(style).toHaveValue("Auto");
    await style.selectOption("Illustration");
    await generateDataset(page);
    await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/traveler_token/);
    await page.evaluate(() => document.fonts.ready);
    for (const grid of await page.locator(".dataset-card-grid").all()) {
      const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
      expect(columns).toBe(width === 1920 ? 2 : 1);
    }
    const promptBox = await page.getByLabel("Dataset prompt 1").boundingBox();
    expect(promptBox.width).toBeGreaterThan(width >= 1100 ? 650 : width >= 768 ? 500 : 250);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const results = page.getByRole("region", { name: "Dataset results", exact: true });
    await expect(results.locator("details").filter({ has: page.getByText("Scene 1", { exact: true }) })).not.toHaveAttribute("open");
    const workflow = page.getByRole("navigation", { name: "Dataset workflow" });
    await expect(workflow.getByRole("tab", { name: "Dataset", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(results.getByRole("button", { name: "View geometry 1", exact: true })).toHaveCount(0);
    if (width === 390) {
      for (const button of await results.getByRole("button").all()) {
        expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(44);
      }
    }
    await openDatasetPage(page, "Configure");
    await expect(page.getByRole("region", { name: "Configure dataset", exact: true })).toBeVisible();
    await expect(style).toBeVisible();
    await expect(style).toHaveValue("Illustration");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const config = page.locator(".dataset-config-grid");
    expect(await config.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length)).toBe(width > 768 ? 2 : 1);
    await expect(page.locator(".dataset-advanced details").filter({ has: page.getByText("Training trigger & controls", { exact: true }) })).not.toHaveAttribute("open");
    await expect(page.locator(".dataset-advanced")).not.toHaveAttribute("open");
    const actions = page.locator(".dataset-config-actions");
    await expect(actions.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
    await expect(actions.getByRole("button", { name: "Generate 2 prompts", exact: true })).toBeVisible();
    if (width > 768) expect((await page.locator(".dataset-configuration").boundingBox()).height).toBeLessThan(650);
    await openDatasetPage(page, "Scenes");
    await expect(page.getByRole("button", { name: "Regenerate idea", exact: true }).first()).toHaveAttribute("title", "Regenerate idea");
    await expect(page.getByRole("button", { name: "Repair scene", exact: true })).toHaveCount(0);
    await expect(page.getByRole("article", { name: "Scene 1 card", exact: true }).getByLabel("Scene: success", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((animation) => animation.effect.target.checkVisibility() && Number.isFinite(animation.effect.getTiming().iterations))
      .map((animation) => animation.finished.catch(() => {}))));
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`scene-cards-${width}.png`), animations: "disabled", fullPage: true });
    await openDatasetPage(page, "Dataset");
    await page.screenshot({ path: testInfo.outputPath(`dataset-${width}.png`), fullPage: true });
  });
}

test("Dataset respects reduced-motion for cards, loading and disclosures", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler exploring exhibits.");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Generate 2 scenes only", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene/);
  await expect(page.locator(".dataset-card").first()).toHaveCSS("animation-name", "none");
  await expect(page.locator(".dataset-details summary").first()).toHaveCSS("transition-duration", "0s");
  await expect(page.getByRole("button", { name: "Regenerate idea", exact: true }).first()).toHaveCSS("transition-duration", "0s");
  const loaderAnimation = await page.evaluate(() => {
    const loader = document.createElement("span");
    loader.className = "dataset-loader";
    document.querySelector(".dataset-view").append(loader);
    const animation = getComputedStyle(loader).animationName;
    loader.remove();
    return animation;
  });
  expect(loaderAnimation).toBe("none");
});
