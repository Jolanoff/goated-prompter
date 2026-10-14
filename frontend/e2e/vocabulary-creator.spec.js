import { test, expect } from "@playwright/test";

const id = "ui_creator";
async function openCreator(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await page.getByRole("button", { name: "Creator", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack details", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "ID", exact: true })).toBeEnabled();
}

async function metadata(page, name = "Browser creator pack", rating = "general") {
  await page.getByRole("textbox", { name: "ID", exact: true }).fill(id);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await page.getByRole("combobox", { name: "Rating", exact: true }).selectOption(rating);
}

async function objectEntry(page) {
  await page.getByRole("button", { name: "Add entry", exact: true }).click();
  await page.getByRole("textbox", { name: "ID", exact: true }).fill(`${id}:moonlight_lantern`);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Moonlight lantern");
  await page.getByLabel("Category", { exact: true }).fill("item");
  await page.getByRole("combobox", { name: "Add Components field", exact: true }).selectOption("object");
}

async function confirm(page) {
  await page.getByRole("alertdialog", { name: "Confirm creator action" }).getByRole("button", { name: "Confirm", exact: true }).click();
}

test.beforeEach(async ({ request }) => {
  await request.delete(`/api/vocabulary/packs/${id}`);
  await request.patch("/api/vocabulary/packs/adult", { data: { enabled: true } });
});
test.afterEach(async ({ request }) => {
  await request.delete(`/api/vocabulary/packs/${id}`);
  await request.patch("/api/vocabulary/packs/adult", { data: { enabled: true } });
});

test("visual creation, editing, duplication, file moves and confirmed removal preserve a valid draft", async ({ page }) => {
  await openCreator(page); await metadata(page); await objectEntry(page);
  await page.getByRole("button", { name: "Duplicate entry", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "ID", exact: true })).toHaveValue(`${id}:moonlight_lantern_copy`);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Edited lantern");
  await page.getByRole("button", { name: "Pack details & files", exact: true }).click();
  await page.getByLabel("New entry filename", { exact: true }).fill("items.json");
  await page.getByRole("button", { name: "Add entry file", exact: true }).click();
  await page.getByRole("textbox", { name: "Search draft entries", exact: true }).fill("Edited");
  await page.locator(".creator-rail .vocabulary-entry-choice").click();
  await page.getByLabel("Entry file", { exact: true }).selectOption("items.json");
  await expect(page.locator(".creator-rail")).toContainText("items.json");
  await page.getByRole("button", { name: "Remove entry", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Edited lantern");
  await page.getByRole("button", { name: "Remove entry", exact: true }).click(); await confirm(page);
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack is valid", exact: true })).toBeVisible();
});

test("saved editable drafts reopen after reload; unsaved replacement requires confirmation", async ({ page, request }) => {
  await openCreator(page); await metadata(page, "Persistent visual draft"); await objectEntry(page);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Draft saved. Installed packs are unchanged.", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Unsaved change");
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New pack", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("Discard unsaved changes");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Unsaved change");
  await page.getByRole("button", { name: "New pack", exact: true }).click(); await confirm(page);
  await page.reload();
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await page.getByRole("button", { name: "Creator", exact: true }).click();
  await page.getByLabel("Reopen draft", { exact: true }).selectOption({ label: `Persistent visual draft (${id})` });
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Persistent visual draft");
  await page.locator(".creator-rail .vocabulary-entry-choice").click();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Moonlight lantern");
  expect((await (await request.get("/api/vocabulary/packs")).json()).packs.some((pack) => pack.id === id)).toBe(false);
});

test("Adult inheritance selectors, dependency errors and rating validation use existing rules", async ({ page }) => {
  await openCreator(page); await metadata(page, "Adult visual draft", "adult");
  await page.getByRole("button", { name: "Add entry", exact: true }).click();
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Inherited position");
  await page.getByLabel("Category", { exact: true }).fill("position");
  await page.getByRole("combobox", { name: "Add Entry field", exact: true }).selectOption("extends");
  await page.getByRole("button", { name: "Add inherits from", exact: true }).click();
  const parent = page.getByLabel("Inherits from 1", { exact: true });
  await parent.fill("adult:position.reverse_cowgirl");
  await expect(page.locator('datalist option[value="adult:position.reverse_cowgirl"]')).toHaveCount(1);
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.getByLabel("Draft validation")).toContainText("Declare a dependency on adult");
  await page.getByRole("button", { name: "Pack details & files", exact: true }).click();
  await page.getByLabel("New Dependencies key", { exact: true }).fill("adult");
  await page.getByRole("button", { name: "Add dependencies key", exact: true }).click();
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack is valid", exact: true })).toBeVisible();
  await page.locator(".creator-rail .vocabulary-entry-choice").click();
  await page.getByRole("combobox", { name: "Add Entry field", exact: true }).selectOption("rating");
  await page.getByRole("combobox", { name: "Rating", exact: true }).selectOption("general");
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.locator(".creator-field-error")).toContainText(["rated looser"]);
});

test("schema-driven resource and capability controls expose nested visual fields", async ({ page }) => {
  await openCreator(page); await metadata(page); await objectEntry(page);
  await page.getByRole("combobox", { name: "Add Object field", exact: true }).selectOption("size");
  await page.getByRole("combobox", { name: "Size", exact: true }).selectOption("small");
  await page.getByRole("button", { name: "Add provides", exact: true }).click();
  await page.getByLabel("Provides 1", { exact: true }).fill("core:limb.hand");
  await expect(page.locator('datalist option[value="core:limb.hand"]')).toHaveCount(1);
  await page.getByRole("combobox", { name: "Add Components field", exact: true }).selectOption("body");
  await page.getByRole("combobox", { name: "Add Body field", exact: true }).selectOption("resources");
  await page.getByLabel("New Resources key", { exact: true }).fill("left_hand");
  await page.getByRole("button", { name: "Add resources key", exact: true }).click();
  await page.getByLabel("Type", { exact: true }).fill("core:limb.hand");
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack is valid", exact: true })).toBeVisible();
});

test("draft retrieval shows own entries and Adult exclusions without changing installed packs", async ({ page, request }) => {
  await openCreator(page); await metadata(page, "Adult preview pack", "adult"); await objectEntry(page);
  const before = await (await request.get("/api/vocabulary/packs")).json();
  await page.getByLabel("Draft sample request", { exact: true }).fill("Moonlight lantern");
  await page.getByRole("button", { name: "Inspect draft retrieval", exact: true }).click();
  const results = page.getByRole("region", { name: "Draft retrieval inspection" }).getByLabel("Retrieval results", { exact: true });
  await expect(results).toBeVisible();
  await results.getByText(/^Excluded \(/).click();
  await expect(results).toContainText("rating adult is not allowed");
  await page.getByRole("switch", { name: "Allow Adult rating in draft preview" }).click();
  await page.getByRole("button", { name: "Inspect draft retrieval", exact: true }).click();
  await expect(results.getByRole("button", { name: "Moonlight lantern", exact: true })).toBeVisible();
  await results.getByRole("button", { name: "Moonlight lantern", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Moonlight lantern");
  expect((await (await request.get("/api/vocabulary/packs")).json()).packs).toEqual(before.packs);
});

test("all schema component types and participant count ranges remain visually editable", async ({ page }) => {
  await openCreator(page); await metadata(page); await page.getByRole("button", { name: "Add entry", exact: true }).click();
  const components = ["capability", "body", "participants", "requirements", "spatial", "claims", "object", "environment"];
  for (const component of components) await page.getByLabel("Add Components field", { exact: true }).selectOption(component);
  await page.getByLabel("New Slots key", { exact: true }).fill("actor");
  await page.getByRole("button", { name: "Add slots key", exact: true }).click();
  await page.getByLabel("Count format", { exact: true }).selectOption("1");
  await page.getByLabel("Min", { exact: true }).fill("1");
  await page.getByLabel("Max", { exact: true }).fill("2");
  await page.getByLabel("Add Requirements field", { exact: true }).selectOption("space");
  await page.getByLabel("Add Space field", { exact: true }).selectOption("all_of");
  await page.getByRole("button", { name: "Add all of", exact: true }).click();
  await page.getByLabel("All of 1", { exact: true }).fill("core:limb.hand");
  await page.getByLabel("Add Spatial field", { exact: true }).selectOption("participants");
  await page.getByLabel("New Participants key", { exact: true }).fill("actor");
  await page.getByRole("button", { name: "Add participants key", exact: true }).click();
  await page.getByRole("group", { name: "Spatial", exact: true }).getByLabel("Add Actor field", { exact: true }).selectOption("orientation");
  await page.getByRole("button", { name: "Validate pack", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack is valid", exact: true })).toBeVisible();
  await page.getByText("Advanced JSON view", { exact: true }).click();
  const json = JSON.parse(await page.getByLabel("Advanced draft JSON", { exact: true }).inputValue());
  expect(Object.keys(json.files["entries.json"].entries[0].components)).toEqual(components);
  expect(json.files["entries.json"].entries[0].components.participants.slots.actor.count).toEqual({ min: 1, max: 2 });
});

test("valid ZIP export/import roundtrips and explicit install/update keeps enabled settings", async ({ page, request }, testInfo) => {
  await openCreator(page); await metadata(page); await objectEntry(page);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export ZIP", exact: true }).click();
  const file = testInfo.outputPath("creator-pack.zip");
  await (await download).saveAs(file);
  await page.getByRole("button", { name: "New pack", exact: true }).click(); await confirm(page);
  await page.getByLabel("Import creator ZIP", { exact: true }).setInputFiles(file);
  await expect(page.getByRole("textbox", { name: "ID", exact: true })).toHaveValue(id);
  await page.getByRole("button", { name: "Install completed pack", exact: true }).click(); await confirm(page);
  await expect(page.getByText("Pack installed.", { exact: true })).toBeVisible();
  expect((await request.patch(`/api/vocabulary/packs/${id}`, { data: { enabled: false } })).ok()).toBe(true);
  await page.getByRole("textbox", { name: "Version", exact: true }).fill("1.1.0");
  await page.getByRole("button", { name: "Update installed pack", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("enabled setting will be preserved"); await confirm(page);
  await expect(page.getByText("Installed pack updated.", { exact: true })).toBeVisible();
  const updated = (await (await request.get("/api/vocabulary/packs")).json()).packs.find((pack) => pack.id === id);
  expect(updated.version).toBe("1.1.0"); expect(updated.enabled).toBe(false);
});

test("bundled packs are visibly read-only; invalid ZIP has a recoverable error", async ({ page }) => {
  await openCreator(page);
  await page.getByLabel("Open pack in creator", { exact: true }).selectOption("bundled:adult");
  await expect(page.getByText("Read-only bundled pack", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save draft", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Install completed pack", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "New pack", exact: true }).click();
  await page.getByLabel("Import creator ZIP", { exact: true }).setInputFiles({ name: "bad.zip", mimeType: "application/zip", buffer: Buffer.from("not a ZIP") });
  await expect(page.getByRole("alert")).toContainText("not a ZIP");
  await expect(page.getByRole("textbox", { name: "ID", exact: true })).toHaveValue("my_pack");
});

for (const width of [1440, 390]) {
  test(`visual creator fits ${width}px in dark and light themes`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await openCreator(page); await metadata(page); await objectEntry(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: testInfo.outputPath("creator-dark.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("button", { name: /Switch to light mode/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: testInfo.outputPath("creator-light.png"), fullPage: true, animations: "disabled" });
  });
}
