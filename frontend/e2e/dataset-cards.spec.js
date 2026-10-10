import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { confirmDatasetReview } from "./datasetHelpers.js";

test.use({ hasTouch: true });

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: {} },
  })).ok()).toBe(true);
});

async function planScenes(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByLabel("Dataset idea", { exact: true }).fill("A duck exploring a garden.");
  await page.getByLabel("Trigger text or terms").fill("duck_token");
  await page.getByLabel("Number of prompts").selectOption("2");
  await page.getByRole("button", { name: "Generate 2 scenes only", exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(/mock scene 2/);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
}

for (const [theme, width] of [["dark", 1440], ["light", 1440], ["dark", 390], ["light", 390], ["dark", 360], ["dark", 1920]]) {
  test(`scene cards show each idea beside its finished scene in ${theme} mode at ${width}px`, async ({ page }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width, height: 1000 });
    await planScenes(page);
    const card = page.getByRole("article", { name: "Scene 1 card", exact: true });
    await expect(card.getByRole("group", { name: "Idea 1 planning details", exact: true })).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Repair scene", exact: true })).toHaveCount(0);
    await expect(card.getByLabel("Scene: success", { exact: true })).toBeVisible();
    await expect(card.getByLabel("Planned scene 1")).toHaveValue(/mock scene 1/);
    const idea = await card.getByLabel("Planned idea 1").boundingBox();
    const scene = await card.getByLabel("Planned scene 1").boundingBox();
    if (width === 1440) expect(scene.x).toBeGreaterThan(idea.x + idea.width);
    else expect(scene.y).toBeGreaterThan(idea.y + idea.height);
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((animation) => animation.effect.target.checkVisibility() && Number.isFinite(animation.effect.getTiming().iterations))
      .map((animation) => animation.finished.catch(() => {}))));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`scene-cards-${theme}-${width}.png`), animations: "disabled", fullPage: true });
  });
}

test("editing an idea keeps its scene usable and leaves siblings untouched", async ({ page }) => {
  await planScenes(page);
  const card = page.getByRole("article", { name: "Scene 1 card", exact: true });
  const scene = await card.getByLabel("Planned scene 1").inputValue();
  const sibling = await page.getByLabel("Planned scene 2").inputValue();
  await card.getByLabel("Planned idea 1").fill("A duck reading a map.");
  await expect(card.getByLabel("Planned scene 1")).toHaveValue(scene);
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(sibling);
  await expect(page.getByText("Dataset settings: Saved", { exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Regenerate prompt", exact: true })).toBeEnabled();
});
