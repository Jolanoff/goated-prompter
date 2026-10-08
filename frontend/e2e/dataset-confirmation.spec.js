import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { confirmDatasetReview, openDatasetPage } from "./datasetHelpers.js";

test.beforeEach(async ({ request }) => {
  const record = await (await request.get("/api/workspace/settings/dataset")).json();
  expect((await request.put("/api/workspace/settings/dataset", {
    data: { revision: record.revision, draft: { subject: "Person 1 and person 2 fighting.",
      trigger_type: "Multiple characters", trigger: "person 1, person 2", trigger_connected: false,
      amount: 2, constraints: "Arena. Both wearing gloves.",
      results: [{ index: 1, input: "", prompt: "Previous manually edited prompt." }] } },
  })).ok()).toBe(true);
});

async function openDataset(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue("Previous manually edited prompt.");
  await openDatasetPage(page, "Configure");
}

test("request review blocks generation, exposes the source, and cancellation preserves the batch", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openDataset(page);
  const calls = [];
  page.on("request", (event) => {
    if (event.method() === "POST" && new URL(event.url()).pathname === "/api/workspace/dataset") calls.push(event);
  });
  const trigger = page.getByRole("button", { name: "Generate 2 prompts", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request" });
  await expect(dialog.getByRole("button", { name: "Confirm and generate prompts" })).toBeEnabled();
  await expect(dialog.getByText("Person 1 and person 2 fighting.", { exact: true }).first()).toBeVisible();
  await expect(dialog.locator(".dataset-review-identity")).toContainText("Randomized per independent prompt");
  await expect(page.getByLabel("Dataset idea", { exact: true })).toBeDisabled();
  expect(calls).toHaveLength(0);
  expect((await (await request.get("/api/workspace/settings/dataset")).json()).draft.scene_plan).toEqual([]);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.keyboard.press("Tab");
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await openDatasetPage(page, "Dataset");
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue("Previous manually edited prompt.");
  const saved = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(saved.results[0].prompt).toBe("Previous manually edited prompt.");
  expect(calls).toHaveLength(0);
});

test("extra instructions require a revised summary and only persist after confirmation", async ({ page, request }) => {
  await openDataset(page);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request" });
  const confirm = dialog.getByRole("button", { name: "Confirm and generate prompts" });
  await expect(confirm).toBeEnabled();
  const addition = "Randomize the people, but at least one must have blond hair in every image.";
  await dialog.getByLabel("Extra instructions or answers").fill(addition);
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("button", { name: "Update summary" }).click();
  await expect(confirm).toBeEnabled();
  await expect(dialog.getByRole("region", { name: "Image requirements" }).getByText(addition, { exact: true })).toBeVisible();
  const before = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(before.constraints).toBe("Arena. Both wearing gloves.");
  expect(before.results[0].prompt).toBe("Previous manually edited prompt.");
  const accepted = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await confirmDatasetReview(page);
  const response = await accepted;
  expect(response.request().postDataJSON().input.constraints).toBe("Arena. Both wearing gloves.\n" + addition);
  expect(response.request().postDataJSON().confirmation_token).toBeTruthy();
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/person 1/);
  const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(after.constraints).toContain(addition);
});

test("blocking questions must be answered and reanalyzed before generation", async ({ page }) => {
  await openDataset(page);
  await page.getByLabel("Dataset idea", { exact: true }).fill("Two people doing unclear breaking.");
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request" });
  const confirm = dialog.getByRole("button", { name: "Confirm and generate prompts" });
  await expect(dialog.getByText("Breaking what?", { exact: true })).toBeVisible();
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Extra instructions or answers").fill("They are breaking a board.");
  await dialog.getByRole("button", { name: "Update summary" }).click();
  await expect(confirm).toBeEnabled();
  await expect(dialog.getByText("Breaking what?", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await openDatasetPage(page, "Scenes");
  await expect(page.getByLabel("Planned idea 1")).toHaveCount(0);
});

test("rejected admission after revised approval keeps the saved request and old prompt", async ({ page, request }) => {
  await openDataset(page);
  await page.getByRole("button", { name: "Generate 2 prompts", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request" });
  await expect(dialog.getByRole("button", { name: "Confirm and generate prompts" })).toBeEnabled();
  await dialog.getByLabel("Extra instructions or answers").fill("One person has blond hair.");
  await dialog.getByRole("button", { name: "Update summary" }).click();
  await page.route("**/api/workspace/dataset", (route) => route.fulfill({ status: 503, json: { error: "Admission unavailable." } }));
  await confirmDatasetReview(page);
  await expect(dialog.getByRole("alert")).toContainText("Admission unavailable.");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  const after = (await (await request.get("/api/workspace/settings/dataset")).json()).draft;
  expect(after.constraints).toBe("Arena. Both wearing gloves.");
  expect(after.results[0].prompt).toBe("Previous manually edited prompt.");
});
