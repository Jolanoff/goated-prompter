import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ request }) => {
  expect((await request.put("/api/settings", { data: { builder: {} } })).ok()).toBe(true);
});

for (const theme of ["dark", "light"]) {
  for (const width of [1440, 390]) {
    test(`opened dropdowns match the ${theme} studio at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((theme) => localStorage.setItem("goated-prompter.theme", theme), theme);
      await page.goto("/");
      await expect(page.getByLabel("Target model", { exact: true })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const model = page.getByLabel("Target model", { exact: true });
      await expect(model).toHaveCSS("appearance", "base-select");
      await model.click();
      await expect.poll(() => model.evaluate((element) => element.matches(":open"))).toBe(true);
      await expect(model.getByRole("option", { name: "Anima", exact: true })).toBeVisible();
      await model.getByRole("option", { name: "Anima", exact: true }).click();
      await expect(model).toHaveValue("Anima");
      await expect.poll(() => model.evaluate((element) => element.matches(":open"))).toBe(false);
      await model.selectOption("Generic");
      await model.focus();
      await page.keyboard.press("Space");
      await expect.poll(() => model.evaluate((element) => element.matches(":open"))).toBe(true);
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await expect(model).toHaveValue("Anima");

      const preset = page.getByLabel("Instruction preset", { exact: true });
      await preset.click();
      await expect(preset.getByRole("option", { name: "General-Purpose Prompt", exact: true })).toBeVisible();
      const styles = await preset.evaluate((element) => {
        const picker = getComputedStyle(element, "::picker(select)");
        const option = getComputedStyle(element.querySelector("option"));
        return { background: picker.backgroundColor,
          radius: picker.borderRadius, padding: option.paddingTop, font: picker.fontFamily, optionSize: option.fontSize,
          bodyFont: getComputedStyle(document.body).fontFamily, maxHeight: picker.maxHeight };
      });
      expect(styles.background).toBe(theme === "dark" ? "rgb(26, 26, 24)" : "rgb(255, 255, 255)");
      expect(styles.radius).toBe("12px");
      expect(styles.padding).toBe("10px");
      expect(styles.optionSize).toBe("14px");
      expect(styles.font).toBe(styles.bodyFont);
      expect(styles.maxHeight).not.toBe("none");
      await page.screenshot({ path: testInfo.outputPath(`dropdown-${theme}-${width}.png`) });
      await page.keyboard.press("Escape");
      await expect(preset).toBeFocused();
      await expect.poll(() => preset.evaluate((element) => element.matches(":open"))).toBe(false);

      for (const [tab, label] of [["Refine", "Prompt target"], ["MiniMax H3", "Mode"],
        ["Dataset", "Number of prompts"], ["Prompt Library", "Library target model"]]) {
        await page.getByRole("button", { name: tab, exact: true }).click();
        const select = page.getByLabel(label, { exact: true });
        await expect(select).toHaveCSS("appearance", "base-select");
        await select.click();
        await expect.poll(() => select.evaluate((element) => element.matches(":open"))).toBe(true);
        await page.keyboard.press("Escape");
        await expect(select).toBeFocused();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      await page.getByRole("button", { name: /Saved Prompts/ }).click();
      await page.getByRole("button", { name: "Add prompt", exact: true }).click();
      const target = page.getByLabel("Saved prompt target", { exact: true });
      await target.click();
      await expect(target.getByRole("option", { name: "Generic", exact: true })).toBeVisible();
      await target.getByRole("option", { name: "Generic", exact: true }).click();
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).not.toBeVisible();
    });
  }
}

test("styled reference menus preserve disabled choices and selected image sources", async ({ page }) => {
  await page.goto("/");
  const subject = page.getByLabel("Subject source", { exact: true });
  await expect(subject).toBeDisabled();
  await page.getByLabel("Upload image 1").setInputFiles({ name: "reference.png", mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTioAAAAASUVORK5CYII=", "base64") });
  await expect(subject).toBeEnabled();
  await subject.click();
  await expect(subject.getByRole("option", { name: "Image 2", exact: true })).toHaveJSProperty("disabled", true);
  await subject.getByRole("option", { name: "Image 1", exact: true }).click();
  await expect(subject).toHaveValue("Image 1");
  await subject.click();
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(subject).toHaveValue("Image 1");
  await page.getByRole("button", { name: "Remove image 1", exact: true }).click();
  await expect(subject).toBeDisabled();
  await expect(subject).toHaveValue("Off");
});
