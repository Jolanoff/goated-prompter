import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { openDatasetPage } from "../e2e/datasetHelpers.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
const fixture = JSON.parse(await readFile(process.env.GOATED_UNDERSTANDING_REPLAY ||
  path.join(root, "tests/fixtures/understanding_review.json"), "utf8"));

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`served UI displays a real-API Understanding replay at ${viewport.width}px without downstream generation`, async ({ page, request }, testInfo) => {
    const savedPrompt = "Previously saved synthetic prompt; do not replace.";
    const before = await (await request.get("/api/workspace/settings/dataset")).json();
    expect((await request.put("/api/workspace/settings/dataset", { data: {
      revision: before.revision, draft: { ...fixture.input, results: [{ index: 1, input: "", prompt: savedPrompt }] },
    } })).ok()).toBe(true);
    const errors = [];
    const downstream = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (event) => {
      if (event.method() === "POST" && /\/api\/workspace\/dataset(?:\/scenes|\/scene)?$/.test(new URL(event.url()).pathname)) downstream.push(event.url());
    });
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByRole("button", { name: "Dataset", exact: true }).click();
    await openDatasetPage(page, "Dataset");
    await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(savedPrompt);
    await openDatasetPage(page, "Configure");
    const response = page.waitForResponse((item) => item.url().endsWith("/api/workspace/dataset/understand") && item.status() === 202);
    await page.getByRole("button", { name: `Generate ${fixture.input.amount} prompts`, exact: true }).click();
    const jobId = (await (await response).json()).id;
    await expect.poll(async () => (await (await request.get(`/api/jobs/${jobId}`)).json()).status).toBe("succeeded");
    const job = await (await request.get(`/api/jobs/${jobId}`)).json();
    expect(job.result.brief).toEqual(fixture.brief);
    const dialog = page.getByRole("dialog", { name: "Confirm understanding" });
    await expect(dialog.getByText(fixture.brief.requested_generation, { exact: true })).toBeVisible();
    await expect(dialog.locator(".dataset-review-identity")).toContainText("Randomized per independent prompt");
    for (const heading of ["Concept", "Requirements", "Open creative choices", "Output settings"]) {
      await expect(dialog.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    }
    await expect(dialog.locator(".dataset-review-details")).toHaveCount(0);
    if (viewport.width === 1280) expect((await dialog.boundingBox()).width).toBeGreaterThan(850);
    await expect(dialog.getByText(fixture.brief.expansion_freedom, { exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("populated-understanding.png") });
    await expect(dialog.getByText("Show details", { exact: true })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Confirm & Generate" })).toBeEnabled();
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(errors).toEqual([]);
    expect(downstream).toEqual([]);
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await openDatasetPage(page, "Dataset");
    await expect(page.getByLabel("Dataset prompt 1")).toHaveValue(savedPrompt);
    const after = await (await request.get("/api/workspace/settings/dataset")).json();
    expect(after.draft.results[0].prompt).toBe(savedPrompt);
    expect(after.draft.scene_plan).toEqual([]);
    expect(downstream).toEqual([]);
  });
}
