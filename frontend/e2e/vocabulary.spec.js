import { test, expect } from "@playwright/test";

test("the Vocabulary tab lists every registered category and its packs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Vocabulary", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Vocabulary", exact: true })).toBeVisible();
  for (const name of ["Subjects", "Spaces", "Actions & Poses", "Effects & Atmosphere"]) {
    await expect(page.getByRole("region", { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "Spaces", exact: true }).getByRole("heading", { name: "Fantasy" })).toBeVisible();
});

test("the Vocabulary Library searches, previews, and applies or discards a selection", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  const library = page.getByRole("dialog", { name: "Vocabulary Library" });
  await expect(library).toBeVisible();
  await library.getByLabel("Search vocabulary").fill("floating castle");
  await expect(library.getByRole("checkbox")).toHaveCount(1);
  await library.getByRole("button", { name: "Preview Fantasy (Spaces)" }).click();
  await expect(library.getByRole("region", { name: "Pack Preview" })).toContainText("enchanted forest");
  await expect(library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" })).not.toBeChecked();
  await library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" }).check();
  await library.getByLabel("Search vocabulary").fill("");
  await library.getByLabel("Vocabulary category").selectOption("Lighting");
  await library.getByRole("checkbox", { name: "Select Cinematic (Lighting)" }).check();
  await library.getByLabel("Vocabulary category").selectOption("");
  await expect(library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" })).toBeChecked();
  await expect(library.getByRole("status")).toContainText("Selected: Fantasy, Cinematic");
  await library.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Selected: Fantasy, Cinematic")).toBeVisible();

  await page.getByRole("button", { name: "Vocabulary Library" }).click();
  await library.getByRole("checkbox", { name: "Select Fantasy (Spaces)" }).uncheck();
  await library.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Selected: Fantasy, Cinematic")).toBeVisible();
});
