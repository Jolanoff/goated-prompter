import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  expect((await request.put("/api/settings", { data: { builder: {} } })).ok()).toBe(true);
});

for (const width of [1600, 1448, 1100, 900, 720, 390, 360]) {
  test(`workspace appearance at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1086 });
    await page.goto("/");
    await expect(page.getByText("Local backend connected")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect(page.getByRole("heading", { name: "Describe your idea" })).toBeVisible();
    await expect(page.getByLabel("Prompt engine")).toHaveCSS("opacity", "0.7");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: `test-results/appearance-${process.env.APPEARANCE_PHASE || "after"}-${width}.png`, fullPage: true });
    const generate = page.getByRole("button", { name: /Generate prompt/ });
    const bounds = await generate.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.getByLabel("Describe your idea", { exact: true }).focus();
    await expect(page.getByLabel("Describe your idea", { exact: true })).toHaveCSS("outline-style", "none");
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await expect(page.getByLabel("Models directory")).toBeVisible();
    await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
    await expect(page.getByLabel("Preset instructions")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  });
}

for (const width of [1448, 390]) {
  test(`control states and save dialog at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1086 });
    await page.goto("/");
    await expect(page.getByText("Local backend connected")).toBeVisible();

    // The existing theme is fixed dark, even when the OS prefers light.
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await expect(page.locator("html")).toHaveCSS("color-scheme", "dark");
      await expect(page.locator("html")).toHaveCSS("background-color", "rgb(13, 14, 19)");
    }
    const end = page.getByRole("button", { name: /End generation/ });
    await expect(end).toBeDisabled();
    await expect(end).toHaveCSS("opacity", "0.5");
    await expect(end).toHaveCSS("cursor", "not-allowed");

    const output = page.getByLabel("Generated prompt", { exact: true });
    await output.fill("A cinematic forest with warm evening light.");
    await expect(output).toHaveCSS("color", "rgb(189, 192, 212)");
    await expect(output).toHaveCSS("border-color", "rgb(146, 115, 237)");
    const lock = page.getByLabel("Lock output");
    await lock.check();
    const track = lock.locator("+ span");
    await expect(track).toHaveCSS("width", "28px");
    await expect(track).toHaveCSS("height", "16px");
    await expect(track).toHaveCSS("border-color", "rgb(171, 144, 245)");
    await expect.poll(() => track.evaluate(el => getComputedStyle(el, "::after").translate))
      .toBe(width <= 1190 ? "11px" : "12px");
    await lock.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(lock).toBeFocused();
    await expect(track).toHaveCSS("outline-color", "rgb(198, 175, 255)");

    const save = page.getByRole("button", { name: "Save Prompt", exact: true });
    await save.hover();
    await expect(save).toHaveCSS("background-image", "none");
    await expect(save).toHaveCSS("background-color", "rgb(44, 41, 60)");
    await save.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveCSS("border-radius", "15px");
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(16);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 16);
    const name = page.getByLabel("Prompt name", { exact: true });
    await expect(page.getByRole("button", { name: "Close save dialog" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(name).toBeFocused();
    const confirm = page.getByRole("button", { name: "Save", exact: true });
    await name.fill("");
    await expect(confirm).toBeDisabled();
    await name.fill("Evening light");
    await expect(confirm).toBeEnabled();
    await page.mouse.move(0, 0);
    await expect(confirm).toHaveCSS("background-image", "linear-gradient(110deg, rgb(147, 110, 234), rgb(121, 83, 203))");
    await page.screenshot({ path: `test-results/dialog-${width}.png` });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();

    const upload = page.getByLabel("Upload image 1");
    await upload.focus();
    await expect(upload.locator("..")).toHaveCSS("outline-color", "rgb(172, 149, 255)");
    await upload.setInputFiles({
      name: "reference.png",
      mimeType: "image/png",
      buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTioAAAAASUVORK5CYII=", "base64"),
    });
    const preview = page.getByRole("img", { name: "Reference 1: reference.png" });
    await expect(preview).toBeVisible();
    await expect(preview).toHaveCSS("object-fit", "cover");
    await preview.hover();
    await expect(preview.locator("..")).toHaveCSS("border-style", "solid");
    await expect(preview.locator("..")).toHaveCSS("border-color", "rgb(72, 64, 85)");
    await expect(page.getByLabel("Subject source")).toHaveCSS("opacity", "1");
    await page.getByRole("button", { name: "Remove image 1" }).click();
    await expect(upload).toBeAttached();
    await expect(page.getByLabel("Subject source")).toHaveCSS("opacity", "0.7");
    await expect(page.getByRole("button", { name: /Use locked prompt/ })).toBeInViewport();

    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(output).toHaveCSS("transition-duration", "0s");
  });
}
