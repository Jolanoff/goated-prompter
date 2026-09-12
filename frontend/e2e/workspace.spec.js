import { test, expect } from "@playwright/test";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test.beforeEach(async ({ request }) => {
  expect(
    (await request.put("/api/settings", { data: { builder: {} } })).ok(),
  ).toBe(true);
});

test("desktop generation, pause/resume, saved prompt persistence and deletion", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1448, height: 1086 });
  await page.goto("/");
  await expect(page.getByText("Local backend connected")).toBeVisible();
  await expect(
    page.getByLabel("Director", { exact: true }).locator("option:checked"),
  ).toHaveText("General Director");
  await expect(page.getByLabel("Mode", { exact: true })).toHaveValue("Enhance");
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("A wandering samurai in a misty forest at dawn.");
  await page
    .getByRole("button", { name: "Generate prompt", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause generation", exact: false }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Pause generation", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Resume generation", exact: false }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Paused Your idea is in good hands" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByLabel("Models directory")).toBeDisabled();
  await expect(page.getByLabel("Keep model loaded")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Unload model" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Directors", exact: true }).click();
  await expect(page.getByLabel("Director instructions")).toBeDisabled();
  await expect(page.getByLabel("Director name")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "New director", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Use in builder" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Back to builder" }).click();
  await page
    .getByRole("button", { name: "Resume generation", exact: false })
    .click();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue(/\[Mock Goated Prompter\]/);
  await page.getByRole("button", { name: "Save Prompt", exact: true }).click();
  await page.getByLabel("Prompt name", { exact: true }).fill("Forest at dawn");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/desktop-workspace.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /Saved Prompts/ }).click();
  await expect(
    page.getByRole("heading", { name: "Forest at dawn" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("goated-prompter.saved-prompts.v1"),
    ),
  ).toBeNull();
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByRole("button", { name: /Saved Prompts/ }).click();
  await expect(
    page.getByRole("heading", { name: "Forest at dawn" }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete Forest at dawn" }).click();
  await expect(
    page.getByRole("heading", { name: "A home for your best ideas." }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("Settings saves directory and retention through the real JSON-backed API", async ({
  page,
  request,
}) => {
  const root = await mkdtemp(join(tmpdir(), "goated-ui-"));
  const original = await (await request.get("/api/settings")).json();
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByLabel("Prompt engine")).toHaveValue("configured");
    for (const label of [
      "Model GGUF path",
      "Projector GGUF path",
      "llama-server executable",
      "Context size",
      "Image min tokens",
      "Max output tokens",
      "GPU layers",
      "Discovered profile",
      "Keep model loaded",
    ]) {
      await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
    }
    await expect(
      page.getByLabel("Director behavior", { exact: true }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Image 1 role", { exact: true })).toHaveCount(
      0,
    );
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await page.getByLabel("Models directory").fill(root);
    await page.getByLabel("Keep model loaded").check();
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status")).toContainText("Settings saved");
    expect(await (await request.get("/api/settings")).json()).toMatchObject({
      models_directory: root,
      keep_model_loaded: true,
      selected_profile: "",
    });
    await page.reload();
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await expect(page.getByLabel("Models directory")).toHaveValue(root);
    await expect(page.getByLabel("Keep model loaded")).toBeChecked();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.getByLabel("Keep model loaded").uncheck();
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status")).toContainText("Settings saved");
    expect(
      (await (await request.get("/api/settings")).json()).keep_model_loaded,
    ).toBe(false);
    await page.getByLabel("Models directory").fill(join(root, "missing"));
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("alert")).toContainText("existing directory");
    await page.getByRole("button", { name: "Back to builder" }).click();
    await expect(
      page.getByRole("button", { name: /^Generate prompt/ }),
    ).toBeEnabled();
  } finally {
    // Keep discovery scoped to this test, never scan the shared temp directory.
    await request.put("/api/settings", {
      data: { ...original, models_directory: root },
    });
    await rm(root, { recursive: true, force: true });
  }
});

test("local engine discovery, partial selection persistence and empty setup", async ({
  page,
  request,
}) => {
  const root = await mkdtemp(join(tmpdir(), "goated-engines-"));
  const original = await (await request.get("/api/settings")).json();
  try {
    await mkdir(join(root, "nested"));
    await mkdir(join(root, "incomplete"));
    for (const folder of [root, join(root, "nested")]) {
      await writeFile(join(folder, "model.gguf"), "");
      await writeFile(join(folder, "mmproj.gguf"), "");
    }
    await writeFile(join(root, "incomplete", "model.gguf"), "");
    expect(
      (
        await request.put("/api/settings", {
          data: { models_directory: root, selected_profile: "nested" },
        })
      ).ok(),
    ).toBe(true);
    // Discovery/settings are real; only advertise local mode instead of the fixture's mock backend.
    await page.route("**/api/bootstrap", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        json: { ...(await response.json()), backend: "local_llama_cpp" },
      });
    });
    await page.goto("/");
    await expect(page.getByLabel("Prompt engine")).toHaveValue("nested");
    await expect(
      page.getByLabel("Prompt engine").locator("option"),
    ).toHaveCount(2);
    let finishSave;
    const saveGate = new Promise((resolve) => {
      finishSave = resolve;
    });
    await page.route("**/api/settings", async (route) => {
      await saveGate;
      await route.continue();
    });
    const put = page.waitForRequest(
      (req) => req.url().endsWith("/api/settings") && req.method() === "PUT",
    );
    await page.getByLabel("Prompt engine").selectOption(".");
    expect((await put).postDataJSON()).toEqual({ selected_profile: "." });
    await expect(
      page.getByRole("button", { name: /^Generate prompt/ }),
    ).toBeDisabled();
    finishSave();
    await expect(page.getByRole("status")).toContainText("Prompt engine saved");
    await page.unroute("**/api/settings");
    await page.reload();
    await expect(page.getByLabel("Prompt engine")).toHaveValue(".");
    await request.put("/api/settings", {
      data: { selected_profile: "removed-profile" },
    });
    await page.reload();
    await expect(page.getByLabel("Prompt engine")).toHaveValue(".");
    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await expect(page.getByText(/incomplete model\./)).toBeVisible();
    await page.getByLabel("Models directory").fill(join(root, "incomplete"));
    await page.getByRole("button", { name: "Save settings" }).click();
    await expect(page.getByRole("status")).toContainText("Settings saved");
    expect(
      (await (await request.get("/api/settings")).json()).selected_profile,
    ).toBe("");
    await page.getByRole("button", { name: "Back to builder" }).click();
    await expect(page.getByLabel("Prompt engine")).toHaveValue("");
    await expect(
      page.getByRole("button", { name: /^Generate prompt/ }),
    ).toBeDisabled();
    await page
      .getByLabel("Generated prompt", { exact: true })
      .fill("Exact output");
    await page.getByLabel("Lock output").check();
    await expect(
      page.getByRole("button", { name: /^Use locked prompt/ }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Set up models in Settings" })
      .click();
    await expect(page.getByLabel("Models directory")).toBeVisible();
  } finally {
    await request.put("/api/settings", {
      data: { ...original, models_directory: root },
    });
    await rm(root, { recursive: true, force: true });
  }
});

test("four stable image slots, explicit sources, text-only isolation and mobile layout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("Local backend connected")).toBeVisible();
  await expect(page.locator("footer.statusbar")).toHaveCount(0);
  const generateButton = page.getByRole("button", {
    name: "Generate prompt",
    exact: false,
  });
  await expect(generateButton).toBeInViewport();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(generateButton).toBeInViewport();
  await expect(page.getByLabel("Subject source")).toHaveValue("Off");
  await expect(page.getByLabel("Subject source")).toBeDisabled();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTioAAAAASUVORK5CYII=",
    "base64",
  );
  await page
    .getByLabel("Upload image 1")
    .setInputFiles({ name: "subject.png", mimeType: "image/png", buffer: png });
  await expect(page.getByLabel("Subject source")).toBeEnabled();
  await expect(
    page.getByLabel("Subject source").locator('option[value="Image 1"]'),
  ).toBeEnabled();
  await expect(
    page.getByLabel("Subject source").locator('option[value="Image 2"]'),
  ).toBeDisabled();
  await page.getByLabel("Upload image 2").setInputFiles({
    name: "lighting.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(
    page.getByLabel("Subject source").locator('option[value="Image 2"]'),
  ).toBeEnabled();
  for (const slot of [3, 4])
    await page.getByLabel(`Upload image ${slot}`).setInputFiles({
      name: `reference-${slot}.png`,
      mimeType: "image/png",
      buffer: png,
    });
  await expect(page.getByText("4 / 4", { exact: true })).toBeVisible();
  await page.getByLabel("Subject source").selectOption("Image 1");
  await page.getByLabel("Lighting source").selectOption("Image 2");
  await page.getByLabel("Colors source").selectOption("Blend");
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("Soft natural lighting on a portrait.");
  await page.getByRole("button", { name: "Text-only preview" }).click();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue(/\[Mock Goated Prompter\]/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/mobile-workspace.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Remove image 1" }).click();
  await expect(
    page.getByRole("img", { name: "Reference 2: lighting.png" }),
  ).toBeVisible();
  await expect(page.getByLabel("Upload image 1")).toBeAttached();
  await expect(
    page.getByRole("img", { name: "Reference 4: reference-4.png" }),
  ).toBeVisible();
  await expect(page.getByLabel("Subject source")).toHaveValue("Off");
  await expect(
    page.getByRole("button", { name: /^Generate prompt/ }),
  ).toBeEnabled();
  await expect(page.getByLabel("Builder save status")).toHaveText("Saved");
  for (const slot of [2, 3, 4])
    await page.getByRole("button", { name: `Remove image ${slot}` }).click();
  for (const attribute of ["Subject", "Lighting", "Colors"]) {
    await expect(page.getByLabel(`${attribute} source`)).toHaveValue("Off");
    await expect(page.getByLabel(`${attribute} source`)).toBeDisabled();
  }
});

test("paused work is recoverable after reload and locked output remains exact", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("Local backend connected")).toBeVisible();
  await page
    .getByLabel("Describe your idea", { exact: true })
    .fill("A foggy valley.");
  await page
    .getByRole("button", { name: "Generate prompt", exact: false })
    .click();
  await page
    .getByRole("button", { name: "Pause generation", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Paused Your idea is in good hands" }),
  ).toBeVisible();
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Resume generation", exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Resume generation", exact: false })
    .click();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue(/A foggy valley/);
  await page
    .getByLabel("Generated prompt", { exact: true })
    .fill("  Keep this exact prompt.\n");
  await page.getByLabel("Lock output").check();
  await page
    .getByRole("button", { name: "Use locked prompt", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Use locked prompt", exact: false }),
  ).toBeEnabled();
  await expect(
    page.getByLabel("Generated prompt", { exact: true }),
  ).toHaveValue("  Keep this exact prompt.\n");
});
