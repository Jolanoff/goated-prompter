import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

for (const width of [1920, 1440, 1100, 768, 390]) {
  test(`Dataset cards remain readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler exploring exhibits.");
    await page.getByLabel("Trigger text or terms").fill("traveler_token");
    await page.getByLabel("Number of prompts").selectOption("2");
    await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
    await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/traveler_token/);
    await page.evaluate(() => document.fonts.ready);
    const config = page.locator(".dataset-config-grid");
    expect(await config.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length)).toBe(width > 1100 ? 2 : 1);
    for (const grid of await page.locator(".dataset-card-grid").all()) {
      const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
      expect(columns).toBe(width === 1920 ? 2 : 1);
    }
    const promptBox = await page.getByLabel("Dataset prompt 1").boundingBox();
    expect(promptBox.width).toBeGreaterThan(width >= 1100 ? 650 : width >= 768 ? 500 : 250);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const results = page.getByRole("region", { name: "Dataset results", exact: true });
    await expect(results.locator("details").filter({ has: page.getByText("Scene 1", { exact: true }) })).not.toHaveAttribute("open");
    await expect(page.locator("details").filter({ has: page.getByText("Training trigger & controls", { exact: true }) })).not.toHaveAttribute("open");
    await expect(page.getByRole("button", { name: "Repair scene", exact: true }).first()).toHaveAttribute("title", "Repair scene");
    await expect(results.getByRole("button", { name: "View geometry 1", exact: true })).toBeVisible();
    if (width === 390) {
      for (const button of await results.getByRole("button").all()) {
        expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(44);
      }
    }
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((animation) => Number.isFinite(animation.effect.getTiming().iterations))
      .map((animation) => animation.finished.catch(() => {}))));
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`dataset-${width}.png`), fullPage: true });
    await results.getByRole("button", { name: "View geometry 1", exact: true }).click();
    const modal = page.getByRole("dialog", { name: "Geometry 1", exact: true });
    await expect(modal).toBeVisible();
    expect(await modal.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`geometry-modal-${width}.png`) });
    await modal.getByRole("button", { name: "Close geometry", exact: true }).click();
    await expect(modal).not.toBeVisible();
  });
}

test("Dataset respects reduced-motion for cards, loading and disclosures", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A traveler exploring exhibits.");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Plan scenes first", exact: true }).click();
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene/);
  await expect(page.locator(".dataset-card").first()).toHaveCSS("animation-name", "none");
  await expect(page.locator(".dataset-details summary").first()).toHaveCSS("transition-duration", "0s");
  await expect(page.getByRole("button", { name: "Repair scene", exact: true }).first()).toHaveCSS("transition-duration", "0s");
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
