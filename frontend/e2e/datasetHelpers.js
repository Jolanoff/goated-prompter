import { expect } from "@playwright/test";

export async function confirmDatasetReview(page) {
  const dialog = page.getByRole("dialog", { name: "Review your Dataset request", exact: true });
  const confirm = dialog.getByRole("button", { name: /^Confirm and/ });
  await expect(confirm).toBeEnabled();
  await confirm.click();
}

export async function analyzeDatasetRequest(request, input) {
  const response = await request.post("/api/workspace/dataset/understand", { data: { input } });
  expect(response.status()).toBe(202);
  const job = await response.json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).status).toBe("succeeded");
  return (await (await request.get(`/api/jobs/${job.id}`)).json()).result;
}
