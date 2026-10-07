import { expect } from "@playwright/test";

export async function openDatasetPage(page, name) {
  await page.getByRole("tab", { name, exact: true }).click();
  await expect(page.getByRole("tabpanel", { name, exact: true })).toBeVisible();
}

export async function confirmDatasetReview(page) {
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request", exact: true });
  const confirm = dialog.getByRole("button", { name: /^Confirm and/ });
  try {
    await expect(confirm).toBeEnabled();
  } catch (error) {
    throw new Error(`Dataset review could not be confirmed: ${await dialog.innerText()}`, { cause: error });
  }
  await confirm.click();
}

export async function generateDataset(page, amount = "2") {
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Plan scenes first", { exact: true }).uncheck();
  const admission = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset") && response.status() === 202);
  await page.getByRole("button", { name: `Generate ${amount} ${Number(amount) === 1 ? "prompt" : "prompts"}`, exact: true }).click();
  await confirmDatasetReview(page);
  return admission;
}

export async function planDatasetScenes(page, amount = "2") {
  await openDatasetPage(page, "Configure");
  await page.getByLabel("Plan scenes first", { exact: true }).check();
  const admission = page.waitForResponse((response) => response.url().endsWith("/api/workspace/dataset/scenes") && response.status() === 202);
  await page.getByRole("button", { name: `Generate ${amount} ${Number(amount) === 1 ? "scene" : "scenes"}`, exact: true }).click();
  await confirmDatasetReview(page);
  await expect(page.getByRole("tab", { name: "Scenes", exact: true })).toHaveAttribute("aria-selected", "true");
  return admission;
}

export async function analyzeDatasetRequest(request, input) {
  const response = await request.post("/api/workspace/dataset/understand", { data: { input } });
  expect(response.status()).toBe(202);
  const job = await response.json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
  return (await (await request.get(`/api/jobs/${job.id}`)).json()).result;
}
