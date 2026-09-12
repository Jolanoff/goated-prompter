import { test, expect } from "@playwright/test";
import { referenceAttributes, referenceSources } from "../src/storage.js";
import { mkdir } from "node:fs/promises";

test.beforeEach(async ({ request }) => {
  expect(
    (await request.put("/api/settings", { data: { builder: {} } })).ok(),
  ).toBe(true);
});

test("builder JSON restores all visible fields and eleven linked sources without images", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("Persistent idea");
  await page
    .getByLabel("Director", { exact: true })
    .selectOption({ label: "Photography Director" });
  await page.getByLabel("Mode", { exact: true }).selectOption("Photography");
  await page.getByLabel("Prompt length").selectOption("Maximum Detail");
  await page.getByLabel("Workflow rules").fill("Keep these rules");
  await page
    .getByLabel("Generated prompt", { exact: true })
    .fill("  Exact output\n");
  await page.getByLabel("Lock output").check();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTioAAAAASUVORK5CYII=",
    "base64",
  );
  for (const slot of [1, 4])
    await page.getByLabel(`Upload image ${slot}`).setInputFiles({
      name: `private-${slot}.png`,
      mimeType: "image/png",
      buffer: png,
    });
  for (const [index, key] of referenceAttributes.entries()) {
    const control = page.getByLabel(
      `${key[0].toUpperCase() + key.slice(1)} source`,
    );
    await expect(control.locator("option")).toHaveText(referenceSources);
    await control.selectOption(index % 2 ? "Image 4" : "Blend");
  }
  await expect(page.locator(".reference-map select")).toHaveCount(11);
  await expect(page.locator(".preserve-grid")).toHaveCount(0);
  await expect(page.getByLabel("Image 1 role")).toHaveCount(0);
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  const saved = await (await request.get("/api/settings")).json();
  expect(saved.builder.idea).toBe("Persistent idea");
  expect(saved.builder.prompt_length).toBe("Maximum Detail");
  expect(Object.keys(saved.builder)).toHaveLength(20);
  expect(saved.builder.mode).toBe("Photography");
  expect(saved.builder).not.toHaveProperty("system_prompt_override");
  expect(JSON.stringify(saved)).not.toMatch(
    /private-|data:image|image_1_role|preserve_subject/,
  );
  await page.reload();
  await expect(
    page.getByLabel("Describe your idea", { exact: true }),
  ).toHaveValue("Persistent idea");
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue("  Exact output\n");
  await expect(page.getByLabel("Lock output")).toBeChecked();
  await expect(page.getByLabel("Prompt length")).toHaveValue("Maximum Detail");
  await expect(page.getByLabel("Workflow rules")).toHaveValue(
    "Keep these rules",
  );
  await expect(page.getByLabel("Mode", { exact: true })).toHaveValue(
    saved.builder.mode,
  );
  await expect(page.getByLabel("Target model", { exact: true })).toHaveValue(
    saved.builder.target_model,
  );
  await expect(page.getByLabel("Creativity", { exact: true })).toHaveValue(
    saved.builder.creativity,
  );
  await expect(page.getByLabel("Director", { exact: true })).toHaveValue(
    saved.builder.director_preset,
  );
  await expect(
    page.getByLabel("Director behavior", { exact: true }),
  ).toHaveCount(0);
  for (const [index, key] of referenceAttributes.entries())
    await expect(
      page.getByLabel(`${key[0].toUpperCase() + key.slice(1)} source`),
    ).toHaveValue(index % 2 ? "Image 4" : "Blend");
  await expect(page.locator('input[type="file"]')).toHaveCount(4);
  await expect(page.getByRole("alert")).toContainText("Missing references");
  await expect(
    page.getByRole("button", { name: /^Use locked prompt/ }),
  ).toBeEnabled();
  await page.getByRole("button", { name: /^Use locked prompt/ }).click();
  await expect(
    page.getByRole("button", { name: /^Use locked prompt/ }),
  ).toBeEnabled();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue("  Exact output\n");
});

test("completed job recovery wins over a slower bootstrap and is saved", async ({
  page,
  request,
}) => {
  const job = await (
    await request.post("/api/generate", {
      data: {
        settings: {
          lock_generated_prompt: true,
          generated_prompt: "Recovered newer output",
        },
      },
    })
  ).json();
  await page.addInitScript(
    (id) => sessionStorage.setItem("goated-prompter.active-job", id),
    job.id,
  );
  let recovered;
  const gate = new Promise((resolve) => {
    recovered = resolve;
  });
  await page.route(`**/api/jobs/${job.id}`, async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({ response, json: result });
    if (result.status === "succeeded") recovered();
  });
  await page.route("**/api/bootstrap", async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue("Recovered newer output");
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/settings")).json()).builder
          .generated_prompt,
    )
    .toBe("Recovered newer output");
});

test("failed autosave retains edits, retries, and old responses never replace newer edits", async ({
  page,
  request,
}) => {
  await page.goto("/");
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let attempts = 0;
  await page.route("**/api/settings", async (route) => {
    if (!route.request().postDataJSON()?.builder) return route.continue();
    attempts++;
    if (attempts === 1) {
      await gate;
      return route.fulfill({ status: 503, json: { error: "Disk offline" } });
    }
    return route.continue();
  });
  await page.getByLabel("Describe your idea", { exact: true }).fill("first");
  await expect.poll(() => attempts).toBe(1);
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("latest draft");
  release();
  await expect(page.getByRole("alert")).toContainText("Draft kept");
  await expect(
    page.getByLabel("Describe your idea", { exact: true }),
  ).toHaveValue("latest draft");
  await page.getByRole("button", { name: "Retry builder save" }).click();
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  expect((await (await request.get("/api/settings")).json()).builder.idea).toBe(
    "latest draft",
  );
  await page.reload();
  await expect(
    page.getByLabel("Describe your idea", { exact: true }),
  ).toHaveValue("latest draft");
});

test("legacy Maximum hydrates once and generation flushes a linked snapshot first", async ({
  page,
}) => {
  await page.route("**/api/bootstrap", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.settings.builder = {
      prompt_length: "Maximum",
      director_preset: "Photography Director",
      mode: "Custom",
      system_prompt_override: "Old hidden instructions",
    };
    await route.fulfill({ response, json: data });
  });
  await page.goto("/");
  await expect(page.getByLabel("Prompt length")).toHaveValue("Maximum Detail");
  await expect(page.getByLabel("Director", { exact: true })).toHaveValue(
    "photography_director",
  );
  await expect(page.getByLabel("Prompt length").locator("option")).toHaveText([
    "Short",
    "Medium",
    "Detailed",
    "Maximum Detail",
  ]);
  const calls = [];
  page.on("request", (req) => {
    if (req.method() === "PUT" || req.url().endsWith("/api/generate"))
      calls.push(req);
  });
  await page.getByLabel("Describe your idea", { exact: true }).fill("Flush me");
  await page.getByRole("button", { name: /^Generate prompt/ }).click();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue(/Flush me/);
  const generation = calls.findIndex((req) =>
    req.url().endsWith("/api/generate"),
  );
  expect(generation).toBeGreaterThan(0);
  expect(calls[generation - 1].postDataJSON().builder.idea).toBe("Flush me");
  expect(calls[generation].postDataJSON().settings.linked_references).toBe(
    true,
  );
  expect(calls[generation].postDataJSON().settings.mode).toBe("Custom");
  expect(calls[generation].postDataJSON().settings).not.toHaveProperty(
    "system_prompt_override",
  );
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
});

test("serialized acknowledgements and settings refresh cannot rehydrate an edited builder", async ({
  page,
  request,
}, testInfo) => {
  await page.goto("/");
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const writes = [];
  await page.route("**/api/settings", async (route) => {
    const payload = route.request().postDataJSON();
    writes.push(payload);
    const response = await route.fetch();
    if (writes.length === 1) await gate;
    await route.fulfill({ response });
  });
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("older snapshot");
  await expect.poll(() => writes.length).toBe(1);
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("newer snapshot");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  release();
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  expect(
    writes
      .filter((payload) => payload.builder)
      .map((payload) => payload.builder.idea),
  ).toEqual(["older snapshot", "newer snapshot"]);
  await page.route("**/api/bootstrap", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.settings.builder = { idea: "stale refresh" };
    await route.fulfill({ response, json: data });
  });
  const models = testInfo.outputPath("models");
  await mkdir(models, { recursive: true });
  await page.getByLabel("Models directory").fill(models);
  await page
    .getByRole("button", { name: "Save settings", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Settings saved");
  expect(writes.at(-1)).not.toHaveProperty("builder");
  await page.getByRole("button", { name: "Back to builder" }).click();
  await expect(
    page.getByLabel("Describe your idea", { exact: true }),
  ).toHaveValue("newer snapshot");
  expect((await (await request.get("/api/settings")).json()).builder.idea).toBe(
    "newer snapshot",
  );
});
