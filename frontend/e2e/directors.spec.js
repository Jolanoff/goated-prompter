import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  expect(
    (await request.put("/api/settings", { data: { builder: {} } })).ok(),
  ).toBe(true);
});

test("saved instruction presets edit, restore, create, rename with stable IDs, reload and delete", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const builder = page.getByLabel("Instruction preset", { exact: true });
  await expect(builder).toHaveValue("general_director");
  await expect(builder.locator("option:checked")).toHaveText("General-Purpose Prompt");
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("Keep my builder draft");
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  const instructions = page.getByLabel("Preset instructions");
  const original = await instructions.inputValue();
  await expect(page.getByLabel("Instruction preset name")).toHaveValue("General-Purpose Prompt");
  await expect(page.getByLabel("Instruction preset name")).toHaveAttribute(
    "readonly",
    "",
  );
  await instructions.fill("Saved built-in instructions");
  const put = page.waitForRequest(
    (req) => req.url().endsWith("/api/presets") && req.method() === "PUT",
  );
  await page.getByRole("button", { name: "Save changes" }).click();
  const payload = (await put).postDataJSON();
  expect(payload).not.toHaveProperty("recommended_mode");
  expect(payload).toEqual({
    id: "general_director",
    name: "General Director",
    instructions: "Saved built-in instructions",
  });
  await expect(page.getByRole("status")).toContainText("Instruction preset saved");
  await expect(page.locator(".director-choice.selected")).toContainText(
    "Edited",
  );
  await page.reload();
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  await expect(instructions).toHaveValue("Saved built-in instructions");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Reset built-in" }).click();
  await expect(instructions).toHaveValue(original);
  await expect(
    page.getByRole("button", { name: "Reset built-in" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "New instruction preset", exact: true }).click();
  await expect(instructions).toHaveValue("");
  const name = `Browser Director ${Date.now()}`;
  await page.getByLabel("Instruction preset name").fill(name);
  await instructions.fill("My persistent direction");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(
    page.getByRole("button", { name: "Use in builder" }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Prompt Builder", exact: true })
    .click();
  await expect(builder).toHaveValue("general_director");
  await expect(
    page.getByLabel("Describe your idea", { exact: true }),
  ).toHaveValue("Keep my builder draft");
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  await page.getByRole("button", { name: "Use in builder" }).click();
  const id = await builder.inputValue();
  expect(id).not.toBe(name);
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  await page.getByLabel("Instruction preset name").fill(`${name} renamed`);
  await instructions.fill("Renamed saved instructions");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toContainText("Instruction preset saved");
  await page.getByRole("button", { name: "Use in builder" }).click();
  await expect(builder).toHaveValue(id);
  await expect(builder.locator("option:checked")).toHaveText(`${name} renamed`);
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  await page.reload();
  await expect(builder).toHaveValue(id);
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  await expect(instructions).toHaveValue("Renamed saved instructions");
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Delete instruction preset", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Instruction preset deleted");
  await page
    .getByRole("button", { name: "Prompt Builder", exact: true })
    .click();
  await expect(builder).toHaveValue("general_director");
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  expect(
    (await (await request.get("/api/settings")).json()).builder.director_preset,
  ).toBe("general_director");
  await page.reload();
  await expect(builder.locator("option").filter({ hasText: name })).toHaveCount(
    0,
  );
});

test("Manage instruction presets opens the active builder preset after viewing another", async ({ page }) => {
  await page.goto("/");
  const builder = page.getByLabel("Instruction preset", { exact: true });
  await expect(builder).toHaveValue("general_director");
  const options = await builder.locator("option").evaluateAll((items) =>
    items.map((item) => ({ id: item.value, label: item.textContent })),
  );
  const active = options.find((item) => item.id === "general_director");
  const other = options.find((item) => item.id !== active.id);
  await page.getByRole("button", { name: "Manage instruction presets", exact: true }).click();
  await expect(page.getByLabel("Instruction preset name")).toHaveValue(active.label);
  const instructions = await page.getByLabel("Preset instructions").inputValue();
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await builder.selectOption(other.id);
  await page.getByRole("button", { name: "Manage instruction presets", exact: true }).click();
  await expect(page.getByLabel("Instruction preset name")).toHaveValue(other.label);
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await builder.selectOption(active.id);
  await page.getByRole("button", { name: "Manage instruction presets", exact: true }).click();
  await expect(page.getByLabel("Instruction preset name")).toHaveValue(active.label);
  await expect(page.getByLabel("Preset instructions")).toHaveValue(instructions);
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
});

test("dirty drafts warn on selection, new and navigation; failed saves retain drafts on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Instruction presets", exact: true }).click();
  await page.getByLabel("Preset instructions").fill("Unsaved direction");
  expect(
    await page.evaluate(
      () =>
        !window.dispatchEvent(new Event("beforeunload", { cancelable: true })),
    ),
  ).toBe(true);
  for (const button of [
    page.getByRole("button", { name: "Settings", exact: true }),
    page.getByRole("button", { name: "New instruction preset", exact: true }),
    page.locator(".director-choice").nth(1),
  ]) {
    page.once("dialog", (dialog) => dialog.dismiss());
    await button.click();
    await expect(page.getByLabel("Preset instructions")).toHaveValue(
      "Unsaved direction",
    );
  }
  await page.route("**/api/presets", (route) =>
    route.request().method() === "PUT"
      ? route.fulfill({ status: 503, json: { error: "Disk offline" } })
      : route.continue(),
  );
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("alert")).toContainText("Draft kept");
  await expect(page.getByLabel("Preset instructions")).toHaveValue(
    "Unsaved direction",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Prompt Builder", exact: true })
    .click();
  expect(
    await page.evaluate(() =>
      window.dispatchEvent(new Event("beforeunload", { cancelable: true })),
    ),
  ).toBe(true);
});
