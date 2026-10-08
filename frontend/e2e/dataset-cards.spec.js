import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { confirmDatasetReview, openDatasetPage } from "./datasetHelpers.js";

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
  test(`scene cards show icon hints without redundant PASS text in ${theme} mode at ${width}px`, async ({ page, request }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("goated-prompter.theme", value), theme);
    await page.setViewportSize({ width, height: 1000 });
    await planScenes(page);
    const record = await (await request.get("/api/workspace/settings/dataset")).json();
    const item = record.draft.scene_plan[0];
    const card = page.getByRole("article", { name: "Scene 1 card", exact: true });
    const hints = card.getByRole("group", { name: "Idea 1 planning details", exact: true });
    await expect(hints.getByRole("button")).toHaveCount(5);
    await expect(card.getByLabel("Scene 1 self-check", { exact: true })).toHaveCount(0);
    await expect(card.getByLabel("Scene: success", { exact: true })).toBeVisible();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    const idea = await card.getByLabel("Planned idea 1").boundingBox();
    const scene = await card.getByLabel("Planned scene 1").boundingBox();
    if (width === 1440) expect(scene.x).toBeGreaterThan(idea.x + idea.width);
    else expect(scene.y).toBeGreaterThan(idea.y + idea.height);

    await hints.getByRole("button", { name: "Camera", exact: true }).hover();
    const tooltip = card.getByRole("tooltip");
    await expect(tooltip).toContainText("Camera angle");
    await expect(tooltip).toContainText(item.camera);
    const tooltipBox = await tooltip.boundingBox();
    expect(tooltipBox.x).toBeGreaterThanOrEqual(0);
    expect(tooltipBox.x + tooltipBox.width).toBeLessThanOrEqual(width);
    await tooltip.hover();
    await expect(tooltip).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`camera-hint-${theme}-${width}.png`), animations: "disabled" });
    await page.mouse.move(0, 0);
    await expect(tooltip).not.toBeVisible();

    for (const [label, field] of [["Placement", "placement"], ["Visibility", "visibility"], ["Camera", "camera"],
      ["Framing", "framing"], ["Context", "context"]]) {
      const icon = hints.getByRole("button", { name: label, exact: true });
      await icon.focus();
      await expect(tooltip).toContainText(item[field]);
      await expect(icon).toHaveAttribute("aria-describedby", await tooltip.getAttribute("id"));
      await page.keyboard.press("Escape");
      await expect(tooltip).not.toBeVisible();
      await expect(icon).toBeFocused();
    }
    await hints.getByRole("button", { name: "Context", exact: true }).tap();
    await expect(tooltip).toContainText(item.context);
    await card.getByLabel("Planned scene 1").focus();
    await expect(tooltip).not.toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((animation) => animation.effect.target.checkVisibility() && Number.isFinite(animation.effect.getTiming().iterations))
      .map((animation) => animation.finished.catch(() => {}))));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`scene-cards-${theme}-${width}.png`), animations: "disabled", fullPage: true });
  });
}

test("repair warnings remain visible and editing an idea removes its stale icon hints", async ({ page, request }) => {
  await planScenes(page);
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  record.draft.scene_plan[0].self_check = "REPAIR:\nRequired glove is hidden.\nMove the glove into view.";
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: record.draft },
  })).ok()).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  const card = page.getByRole("article", { name: "Scene 1 card", exact: true });
  await expect(card.getByLabel("Scene 1 self-check", { exact: true })).toContainText("Required glove is hidden");
  await expect(card.getByRole("button", { name: "Regenerate prompt", exact: true })).toBeDisabled();
  await expect(card.getByLabel("Scene: success", { exact: true })).toHaveCount(0);
  const sibling = await page.getByLabel("Planned scene 2").inputValue();
  await card.getByLabel("Planned idea 1").fill("A duck reading a map.");
  await expect(card.getByRole("group", { name: "Idea 1 planning details", exact: true })).toHaveCount(0);
  await expect(card.getByLabel("Planned scene 1")).toHaveValue("");
  await expect(card.getByLabel("Scene 1 self-check", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Planned scene 2")).toHaveValue(sibling);
});
