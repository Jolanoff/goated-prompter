import { test, expect } from "@playwright/test";

test("Dataset builds, persists and exports a trigger-ready batch", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Build a prompt dataset." })).toBeVisible();
  await page.getByLabel("Trigger / prepend text").fill("ohwx_person");
  await page.getByLabel("Describe the consistent concept").fill(
    "A woman with short black hair, green eyes, and a fitted red jacket.",
  );
  await page.getByLabel("Number of prompts").selectOption("3");
  await page.getByLabel("Visual style").selectOption("Anime / manga");
  await page.getByLabel(/Guided inputs Use your one-line ideas/).check();
  await page.getByLabel("Guided dataset inputs").fill(
    "standing portrait in a city at night\nrunning through a sunlit field",
  );
  await page.getByText("Advanced coverage planning (optional)").click();
  await page.getByLabel("Use coverage plan").check();
  await page.getByRole("button", { name: "Create plan" }).click();
  const planner = page.getByRole("region", { name: "Coverage planner" });
  await expect(planner.getByRole("row")).toHaveCount(4);
  await expect(planner.getByText("standing portrait in a city at night", { exact: true })).toBeVisible();
  await expect(planner.getByText("running through a sunlit field", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Generate 3 prompts" }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/^ohwx_person,/);
  await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(/standing portrait/);
  await expect(page.getByLabel("Dataset prompt 2")).toHaveValue(/running through/);
  await expect(page.getByRole("button", { name: "TXT", exact: true })).toBeEnabled();
  const quality = page.getByRole("region", { name: "Dataset quality report" });
  await expect(quality.getByText("Overall", { exact: true })).toBeVisible();
  await expect(quality.getByText(/Prompt checks · \d\/3 passed/)).toBeVisible();
  await expect(quality.getByRole("button", { name: "Deep consistency review" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByText("Dataset settings: Saved")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByLabel("Dataset prompt 3")).toHaveValue(/^ohwx_person,/);
  await expect(page.getByRole("region", { name: "Coverage planner" }).getByRole("row")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "Dataset quality report" }).getByText("Overall", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
