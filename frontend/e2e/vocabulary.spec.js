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

async function explore(page) {
  await open(page);
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await expect(page.locator(".vocabulary-entry-count")).toContainText("81 of 81");
}

test("explorer filters and sorts actual categories, searches aliases and navigates inheritance", async ({ page }) => {
  await explore(page);
  await page.getByLabel("Filter entry category").selectOption("body");
  await page.getByLabel("Sort vocabulary entries").selectOption("id");
  await page.getByLabel("Search vocabulary entries").fill("core:body.human");
  await expect(page.locator(".vocabulary-entry-choice")).toHaveCount(2);
  await page.locator(".vocabulary-entry-choice").filter({ has: page.getByText("core:body.human", { exact: true }) }).click();
  const detail = page.getByRole("article", { name: "Entry details" });
  await expect(detail.getByRole("heading", { name: "Human", exact: true })).toBeVisible();
  await expect(page.getByLabel("Search vocabulary entries")).toHaveValue("core:body.human");
  await detail.getByText("Body resources and capabilities", { exact: true }).click();
  await expect(detail).toContainText("Declared by this entry");
  await expect(detail).toContainText("Resolved including inheritance");
  await detail.getByRole("button", { name: "Humanoid", exact: true }).first().click();
  await expect(detail.getByRole("heading", { name: "Humanoid", exact: true })).toBeVisible();
  await page.getByLabel("Search vocabulary entries").fill("no_such_entry");
  await expect(page.getByText("No entries match these filters.")).toBeVisible();
  await expect(page.getByText("Start with an entry", { exact: true })).toBeVisible();
});

test("disabled Adult pack remains explorable with cross-pack reference navigation", async ({ page, request }) => {
  expect((await request.patch("/api/vocabulary/packs/adult", { data: { enabled: false } })).ok()).toBe(true);
  await explore(page);
  await page.getByLabel("Explore pack").selectOption("bundled:adult");
  await page.getByLabel("Filter entry rating").selectOption("adult");
  await page.getByLabel("Search vocabulary entries").fill("reverse cowgirl");
  await expect(page.locator(".vocabulary-entry-choice")).toHaveCount(1);
  await page.locator(".vocabulary-entry-choice").click();
  const detail = page.getByRole("article", { name: "Entry details" });
  await expect(detail).toContainText("Pack disabled; browsing only");
  await expect(detail.locator('.vocabulary-rating[data-rating="adult"]')).toBeVisible();
  const reference = detail.locator(".vocabulary-reference-list button").first();
  await reference.click();
  await expect(page.getByLabel("Explore pack")).toHaveValue("core:core");
  await expect(detail).toContainText("Owned by Core");
  const response = await request.get("/api/vocabulary/packs");
  expect((await response.json()).packs.find((pack) => pack.id === "adult").enabled).toBe(false);
});

test("retrieval inspection reports rating exclusions and unknowns without generation", async ({ page, request }) => {
  await explore(page);
  await page.getByRole("button", { name: "Test a request", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Test a request", exact: true })).toBeVisible();
  await page.getByLabel("Vocabulary sample request").fill("Reverse cowgirl on a sofa");
  await page.getByText("Optional character descriptions", { exact: true }).click();
  await page.getByLabel("Inspection characters").fill("unidentified being\nunidentified being");
  await page.getByRole("button", { name: "Inspect retrieval", exact: true }).click();
  const results = page.getByLabel("Retrieval results", { exact: true });
  await expect(results).toContainText("General and Mature ratings allowed");
  await results.getByText(/^Excluded \(/).click();
  await expect(results).toContainText("rating adult is not allowed");
  await page.getByRole("switch", { name: "Allow Adult rating in inspection" }).click();
  await expect(results).toHaveCount(0);
  await page.getByRole("button", { name: "Inspect retrieval", exact: true }).click();
  await expect(results).toContainText("Unknown");
  await results.getByRole("button", { name: "Reverse cowgirl", exact: true }).click();
  await expect(page.getByRole("article", { name: "Entry details" })).toContainText("adult:position.reverse_cowgirl");
  const jobs = await request.get("/api/bootstrap");
  expect((await jobs.json()).active_job).toBeFalsy();
});

test("explorer ignores a stale search response", async ({ page }) => {
  await page.route("**/api/vocabulary/packs/core/entries?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("q") === "slow") {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({ status: 500, json: { error: "Stale failure" } });
    } else await route.continue();
  });
  await explore(page);
  await page.getByLabel("Search vocabulary entries").fill("slow");
  await page.waitForRequest((request) => request.url().includes("q=slow"));
  await page.getByLabel("Search vocabulary entries").fill("lantern");
  await expect(page.locator(".vocabulary-entry-choice")).toHaveCount(1);
  await expect(page.locator(".vocabulary-entry-choice")).toContainText("Lantern");
  await expect(page.getByText("Stale failure", { exact: true })).toHaveCount(0);
});

test("explorer retries a failed catalogue and browses an installed pack", async ({ page, request }) => {
  expect((await request.post("/api/vocabulary/packs", { data: zip("ui_custom") })).ok()).toBe(true);
  await page.route("**/api/vocabulary/packs/core/entries?*", (route) => route.fulfill({ status: 503, json: { error: "Catalogue unavailable" } }));
  await open(page);
  await page.getByRole("button", { name: "Browse", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Catalogue unavailable");
  await page.unroute("**/api/vocabulary/packs/core/entries?*");
  await page.getByRole("button", { name: "Retry explorer", exact: true }).click();
  await expect(page.locator(".vocabulary-entry-count")).toContainText("81 of 81");
  await page.getByLabel("Explore pack").selectOption("installed:ui_custom");
  await expect(page.locator(".vocabulary-entry-choice")).toHaveCount(1);
  await page.locator(".vocabulary-entry-choice").click();
  await expect(page.getByRole("article", { name: "Entry details" })).toContainText("Owned by Custom studio pack");
});

for (const width of [1440, 390]) {
  test(`explorer detail and retrieval layout fits ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await explore(page);
    await page.getByLabel("Search vocabulary entries").fill("lantern");
    await expect(page.locator(".vocabulary-entry-choice")).toHaveCount(1);
    await page.locator(".vocabulary-entry-choice").click();
    await expect(page.getByRole("article", { name: "Entry details" })).toContainText("core:item.lantern");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("explorer-dark.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("button", { name: /Switch to light mode/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: testInfo.outputPath("explorer-light.png"), fullPage: true, animations: "disabled" });
  });
}
