import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
function zip(id, version = "1.0.0", rating = "mature", requires = { core: ">=1.0.0" }) {
  return execFileSync(python, ["-c", `
import json, sys
from tests.unit.vocabulary.test_vocabulary_packs import archive, tiny_pack, capability
pack_id, version, rating, requires = sys.argv[1:]
files = tiny_pack(pack_id, [capability(pack_id + ':knowledge')], version=version, rating=rating, requires=json.loads(requires))
files['manifest.json']['name'] = pack_id.replace('ui_', '').title() + ' studio pack'
files['manifest.json']['description'] = 'A user-installed pack for the studio.'
sys.stdout.buffer.write(archive(files))
`, id, version, rating, JSON.stringify(requires)], { cwd: root });
}
const uploadFile = (buffer) => ({ name: "studio.zip", mimeType: "application/zip", buffer });
const card = (page, name) => page.locator(".vocabulary-pack").filter({ has: page.getByRole("heading", { name, exact: true }) });
async function open(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pack library", exact: true })).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  for (const id of ["ui_child", "ui_parent", "ui_custom"]) await request.delete(`/api/vocabulary/packs/${id}`);
  for (const id of ["adult", "fantasy"]) expect((await request.patch(`/api/vocabulary/packs/${id}`, { data: { enabled: true } })).ok()).toBe(true);
});
test.afterEach(async ({ request }) => {
  for (const id of ["ui_child", "ui_parent", "ui_custom"]) await request.delete(`/api/vocabulary/packs/${id}`);
  for (const id of ["adult", "fantasy"]) await request.patch(`/api/vocabulary/packs/${id}`, { data: { enabled: true } });
});

test("optional Adult state persists on reload; Core and bundled files remain protected", async ({ page }) => {
  await open(page);
  const core = page.locator(".vocabulary-pack").filter({ hasText: "Mandatory Core" });
  await expect(core.getByRole("switch")).toBeDisabled();
  await expect(core.getByRole("switch")).toBeChecked();
  for (const bundled of await page.locator(".vocabulary-pack").all()) {
    await expect(bundled.getByRole("button", { name: "Update ZIP" })).toHaveCount(0);
    await expect(bundled.getByRole("button", { name: /^Remove/ })).toHaveCount(0);
  }
  const adult = page.locator(".vocabulary-pack").filter({ has: page.locator('.vocabulary-rating[data-rating="adult"]') });
  await adult.getByRole("switch").click();
  await expect(adult.getByRole("switch")).not.toBeChecked();
  await expect(page.locator(".vocabulary-view").getByRole("status")).toContainText("disabled");
  await page.reload();
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await expect(adult.getByRole("switch")).not.toBeChecked();
});

test("install, selected ZIP update and confirmed removal work through the real API", async ({ page }) => {
  await open(page);
  await page.getByLabel("Pack ZIP", { exact: true }).setInputFiles(uploadFile(zip("ui_custom")));
  await page.getByRole("button", { name: "Install ZIP", exact: true }).click();
  const custom = card(page, "Custom studio pack");
  await expect(custom).toContainText("Mature");
  await expect(custom).toContainText("1.0.0");
  await expect(page.getByLabel("Pack ZIP", { exact: true })).toHaveValue("");
  await custom.getByRole("switch").click();
  await expect(custom.getByRole("switch")).not.toBeChecked();
  await custom.getByRole("button", { name: "Update ZIP" }).click();
  await page.getByLabel("Pack ZIP", { exact: true }).setInputFiles(uploadFile(zip("ui_custom", "1.1.0", "adult")));
  await page.getByRole("button", { name: "Update pack", exact: true }).click();
  await expect(custom).toContainText("1.1.0");
  await expect(custom).toContainText("Adult");
  await expect(custom.getByRole("switch")).not.toBeChecked();
  await custom.getByRole("button", { name: "Remove Custom studio pack", exact: true }).click();
  await custom.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(custom).toBeVisible();
  await custom.getByRole("button", { name: "Remove Custom studio pack", exact: true }).click();
  await custom.getByRole("button", { name: "Remove pack", exact: true }).click();
  await expect(custom).toHaveCount(0);
});

test("invalid ZIP and mismatched update leave existing packs intact", async ({ page, request }) => {
  expect((await request.post("/api/vocabulary/packs", { data: zip("ui_custom") })).ok()).toBe(true);
  await open(page);
  await page.getByLabel("Pack ZIP", { exact: true }).setInputFiles(uploadFile(Buffer.from("not a ZIP")));
  await page.getByRole("button", { name: "Install ZIP", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("not a ZIP");
  const custom = card(page, "Custom studio pack");
  await custom.getByRole("button", { name: "Update ZIP" }).click();
  await page.getByLabel("Pack ZIP", { exact: true }).setInputFiles(uploadFile(zip("ui_parent")));
  await page.getByRole("button", { name: "Update pack", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("not ui_custom");
  await expect(custom).toContainText("1.0.0");
});

test("dependency failures are visible and do not falsely flip enabled state", async ({ page, request }) => {
  expect((await request.post("/api/vocabulary/packs", { data: zip("ui_parent") })).ok()).toBe(true);
  expect((await request.post("/api/vocabulary/packs", { data: zip("ui_child", "1.0.0", "general", { core: ">=1.0.0", ui_parent: ">=1.0.0" }) })).ok()).toBe(true);
  await open(page);
  const parent = card(page, "Parent studio pack");
  await parent.getByRole("switch").click();
  await expect(page.getByRole("alert")).toContainText("enabled packs require it");
  await expect(parent.getByRole("switch")).toBeChecked();
  await parent.getByRole("button", { name: "Remove Parent studio pack" }).click();
  await parent.getByRole("button", { name: "Remove pack", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("cannot be removed");
  await expect(parent).toBeVisible();
});

test("request errors can be retried without leaving the tab", async ({ page }) => {
  await page.route("**/api/vocabulary/packs", (route) => route.fulfill({ status: 503, json: { error: "Pack storage offline" } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Pack storage offline");
  await page.unroute("**/api/vocabulary/packs");
  await page.getByRole("button", { name: "Reload packs" }).click();
  await expect(page.getByRole("heading", { name: "Pack library", exact: true })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`pack manager layout fits ${width}px in dark and light themes`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await open(page);
    await expect(page.locator(".vocabulary-packs > li")).toHaveCount(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("dark.png"), fullPage: true });
    await page.getByRole("button", { name: /Switch to light mode/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.screenshot({ path: testInfo.outputPath("light.png"), fullPage: true });
  });
}
