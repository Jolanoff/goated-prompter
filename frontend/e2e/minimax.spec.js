import { test, expect } from "@playwright/test";

const output = "subject_definitions:\n<Subject 1> is the person shown in <Picture 1>.\n\nsummary:\n[reference generation] Transfer only dance movement from <Video 1> to <Subject 1> on a rooftop.\n\nretention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - identity and appearance.\n\ndetailed_description:\nA neon-lit nighttime rooftop.\n[Shot 1] The camera slowly arcs around the dancer for 15 seconds.\n\noverall_soundscape:\nWind and synchronized footfalls.\n\nnon_diegetic_music:\nA generated electronic score with a pulsing synth bass and crisp hi-hats.";

test.beforeEach(async ({ request }) => {
  const path = "/api/workspace/settings/minimax";
  const record = await (await request.get(path)).json();
  expect((await request.put(path, { data: { revision: record.revision, draft: {} } })).ok()).toBe(true);
});

async function open(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "MiniMax H3", exact: true }).click();
  await expect(page.getByLabel("Clip Length", { exact: true })).toHaveValue("10");
}

test("defaults, structured generation, copy, regeneration and edited output persistence stay isolated", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: async (text) => { window.copiedPrompt = text; } } }));
  const submitted = [];
  await page.route("**/api/workspace/minimax", async (route) => {
    submitted.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: { id: `minimax-fixture-${submitted.length}`, kind: "minimax", status: "running", revision: 0 } });
  });
  await page.route("**/api/jobs/minimax-fixture-*", (route) => route.fulfill({ json: {
    id: route.request().url().split("/").at(-1), kind: "minimax", status: "succeeded", revision: 1,
    result: { prompt: output, warnings: [], mode: "Ref2VA", planning_status: "planned" },
  } }));
  await open(page);
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("MiniMax H3");
  await expect(page.getByLabel("Mode", { exact: true })).toHaveValue("auto");
  await expect(page.getByLabel("MiniMax planning")).toHaveValue("Auto");
  await page.getByLabel("MiniMax planning").selectOption("Always");
  await expect(page.getByLabel("Director Preset", { exact: true })).toHaveValue("minimax_director");
  await expect(page.getByLabel("Director Preset", { exact: true }).locator('option[value="anime_director"]')).toHaveCount(1);
  await page.getByLabel("Clip Length").selectOption("15");
  await page.getByLabel("Aspect Ratio", { exact: true }).selectOption("9:16");
  const requestText = "Use the person in <image1> for the dance from <video1> on a rooftop at night with energetic electronic music.";
  await page.getByLabel("Describe your video").fill(requestText);
  await page.getByRole("button", { name: "Generate MiniMax prompt", exact: true }).click();
  const result = page.getByLabel("Generated MiniMax H3 Prompt", { exact: true });
  await expect(result).toHaveValue(output);
  expect(submitted[0].input).toEqual({ model: "MiniMax H3", duration_seconds: 15, mode: "auto", aspect_ratio: "9:16",
    planning_mode: "Always", director_preset: "minimax_director", references: ["image1", "video1"], user_request: requestText });
  await expect(page.getByText("Supporting video scene planning used for the latest generation.")).toBeVisible();
  expect(Object.keys(submitted[0]).sort()).toEqual(["input", "settings"]);
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.copiedPrompt)).toBe(output);
  await page.getByRole("button", { name: "Regenerate", exact: true }).click();
  await expect(page.getByRole("button", { name: "Regenerate", exact: true })).toBeEnabled();
  expect(submitted[1]).toEqual(submitted[0]);
  await result.fill(output + "\nEdited ending.");
  await expect(page.getByLabel("MiniMax H3 settings save status")).toHaveText("MiniMax H3 settings: Saved");
  await page.reload();
  await page.getByRole("button", { name: "MiniMax H3", exact: true }).click();
  await expect(result).toHaveValue(output + "\nEdited ending.");
  await expect(page.getByLabel("Clip Length")).toHaveValue("15");
  await expect(page.getByLabel("Aspect Ratio", { exact: true })).toHaveValue("9:16");
  await expect(page.getByLabel("MiniMax planning")).toHaveValue("Always");
  await page.getByRole("button", { name: "Prompt Builder", exact: true }).click();
  await expect(page.getByLabel("Generated prompt", { exact: true })).not.toHaveValue(output);
  await page.getByRole("button", { name: "MiniMax H3", exact: true }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(result).toHaveValue("");
  await expect(page.getByLabel("Describe your video")).toHaveValue("");
  await expect(page.getByLabel("Clip Length")).toHaveValue("15");
  await expect(page.getByLabel("MiniMax H3 settings save status")).toHaveText("MiniMax H3 settings: Saved");
});

test("reference chips insert at the cursor, append, preserve numbering and enforce all limits", async ({ page }) => {
  await open(page);
  const text = page.getByLabel("Describe your video");
  await text.fill("Use here.");
  await text.evaluate((node) => { node.focus(); node.setSelectionRange(4, 8); });
  await page.getByRole("button", { name: "+ Image", exact: true }).click();
  await expect(text).toHaveValue("Use <image1>.");
  await text.evaluate((node) => node.setSelectionRange(0, 0));
  await page.getByRole("button", { name: "<image1>", exact: true }).click();
  await expect(text).toHaveValue("<image1> Use <image1>.");
  await page.getByLabel("Clip Length").focus();
  await page.getByRole("button", { name: "+ Video", exact: true }).click();
  await expect(text).toHaveValue("<image1> Use <image1>. <video1>");
  await text.fill("<IMAGE9> <image1> <video1>");
  await page.getByRole("button", { name: "+ Image", exact: true }).click();
  await expect(page.getByRole("button", { name: "<image2>", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "<image9>", exact: true })).toBeVisible();
  for (let i = 0; i < 6; i++) await page.getByRole("button", { name: "+ Image", exact: true }).click();
  await expect(page.getByRole("button", { name: "+ Image", exact: true })).toBeDisabled();
  await expect(page.getByText("Image limit reached (9).", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "+ Video", exact: true }).click();
  await page.getByRole("button", { name: "+ Video", exact: true }).click();
  await expect(page.getByRole("button", { name: "+ Video", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "+ Audio", exact: true })).toBeDisabled();
  await expect(page.getByText("Combined reference limit reached (12).", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "+ Audio", exact: true }).click();
  await expect(page.getByRole("button", { name: "+ Audio", exact: true })).toBeDisabled();
  await expect(page.getByText(/Audio cannot be the only reference modality/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate MiniMax prompt", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "+ Image", exact: true }).click();
  await expect(page.getByText(/Audio cannot be the only reference modality/)).not.toBeVisible();
  await text.fill("Use <image10>");
  await expect(page.getByRole("button", { name: "Generate MiniMax prompt", exact: true })).toBeDisabled();
});

test("delayed reference cursor restoration cannot steal focus from another control", async ({ page }) => {
  await open(page);
  const text = page.getByLabel("Describe your video");
  await text.fill("Use here.");
  await text.evaluate((node) => { node.focus(); node.setSelectionRange(4, 8); });
  await page.evaluate(() => {
    const original = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => {
      window.requestAnimationFrame = original;
      window.delayedInsertionFrame = callback;
      return 0;
    };
  });
  await page.getByRole("button", { name: "+ Image", exact: true }).click();
  await expect(text).toHaveValue("Use <image1>.");
  const duration = page.getByLabel("Clip Length", { exact: true });
  await duration.focus();
  await page.evaluate(() => window.delayedInsertionFrame(performance.now()));
  const focusStayedOnDuration = await duration.evaluate((node) => document.activeElement === node);
  await page.getByRole("button", { name: "+ Video", exact: true }).click();
  await expect(text).toHaveValue("Use <image1>. <video1>");
  expect(focusStayedOnDuration).toBe(true);
});

test("delayed shot cursor restoration respects a newer focus choice", async ({ page }) => {
  await open(page);
  const text = page.getByLabel("Describe your video");
  await text.fill("A rooftop scene.");
  await page.evaluate(() => {
    const original = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => {
      window.requestAnimationFrame = original;
      window.delayedInsertionFrame = callback;
      return 0;
    };
  });
  await page.getByRole("button", { name: "+ Shot", exact: true }).click();
  await expect(text).toHaveValue("A rooftop scene.\n<shot1> ");
  const duration = page.getByLabel("Clip Length", { exact: true });
  await duration.focus();
  await page.evaluate(() => window.delayedInsertionFrame(performance.now()));
  await expect(duration).toBeFocused();
});

for (const kind of ["shot", "reference"]) {
  test(`delayed ${kind} cursor restoration cannot overwrite a newer text edit`, async ({ page }) => {
    await open(page);
    const text = page.getByLabel("Describe your video");
    await text.fill("cartoonish style");
    await page.evaluate(() => {
      const original = window.requestAnimationFrame;
      window.requestAnimationFrame = (callback) => {
        window.requestAnimationFrame = original;
        window.delayedInsertionFrame = callback;
        return 0;
      };
    });
    await page.getByRole("button", { name: kind === "shot" ? "+ Shot" : "+ Image", exact: true }).click();
    await expect(text).toHaveValue(kind === "shot" ? "cartoonish style\n<shot1> " : "cartoonish style <image1>");
    const edited = "<image1> is an apple\n<shot1> 0-3s apple walks";
    await text.fill(edited);
    await page.evaluate(() => window.delayedInsertionFrame(performance.now()));
    await page.getByRole("button", { name: kind === "shot" ? "+ Shot" : "+ Video", exact: true }).click();
    await expect(text).toHaveValue(edited + (kind === "shot" ? "\n<shot2> " : " <video1>"));
  });
}

test("delayed shot cursor restoration cannot overwrite a newer insertion", async ({ page }) => {
  await open(page);
  const text = page.getByLabel("Describe your video");
  await text.fill("A rooftop scene.");
  await page.evaluate(() => {
    const original = window.requestAnimationFrame;
    window.requestAnimationFrame = (callback) => {
      window.requestAnimationFrame = original;
      window.delayedInsertionFrame = callback;
      return 0;
    };
  });
  const addShot = page.getByRole("button", { name: "+ Shot", exact: true });
  await addShot.click();
  await expect(text).toHaveValue("A rooftop scene.\n<shot1> ");
  await text.evaluate((node) => node.setSelectionRange(node.value.length, node.value.length));
  await addShot.click();
  await expect(text).toHaveValue("A rooftop scene.\n<shot1> \n<shot2> ");
  await expect.poll(() => text.evaluate((node) => node.selectionStart)).toBe(34);
  await page.evaluate(() => window.delayedInsertionFrame(performance.now()));
  await addShot.click();
  await expect(text).toHaveValue("A rooftop scene.\n<shot1> \n<shot2> \n<shot3> ");
});

test("optional shot shortcuts insert in the prompt without registering media", async ({ page }) => {
  await open(page);
  const text = page.getByLabel("Describe your video");
  await text.fill("cartoonish style");
  await page.getByRole("button", { name: "+ Shot", exact: true }).click();
  await expect(text).toHaveValue("cartoonish style\n<shot1> ");
  await text.fill("<image1> is an apple\n<shot1> 0-3s apple walks");
  await page.getByRole("button", { name: "+ Shot", exact: true }).click();
  await expect(text).toHaveValue("<image1> is an apple\n<shot1> 0-3s apple walks\n<shot2> ");
  await expect(page.getByLabel("Registered references").getByRole("button")).toHaveCount(1);
  await text.fill("<shot2> apple walks");
  await expect(page.getByText(/Shots must appear once each in order/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate MiniMax prompt", exact: true })).toBeDisabled();
});

test("autosave errors retain draft and retry; stale tabs cannot overwrite", async ({ page, request }) => {
  await open(page);
  await page.route("**/api/workspace/settings/minimax", (route) => route.request().method() === "PUT"
    ? route.fulfill({ status: 503, json: { error: "Disk offline" } }) : route.continue());
  await page.getByLabel("Describe your video").fill("Keep this rooftop scene.");
  await expect(page.getByRole("alert")).toContainText("Disk offline");
  await page.unroute("**/api/workspace/settings/minimax");
  await page.getByRole("button", { name: "Retry MiniMax H3 save", exact: true }).click();
  await expect(page.getByLabel("MiniMax H3 settings save status")).toHaveText("MiniMax H3 settings: Saved");
  const path = "/api/workspace/settings/minimax";
  const current = await (await request.get(path)).json();
  await request.put(path, { data: { revision: current.revision, draft: { ...current.draft, user_request: "Another tab" } } });
  await page.getByLabel("Describe your video").fill("Retain the stale local edit.");
  await expect(page.getByRole("alert")).toContainText("changed in another tab");
  await expect(page.getByLabel("Describe your video")).toHaveValue("Retain the stale local edit.");
  await expect(page.getByRole("button", { name: "Generate MiniMax prompt", exact: true })).toBeDisabled();
});

test("failed generation keeps the previous editable output", async ({ page }) => {
  await page.route("**/api/workspace/minimax", (route) => route.fulfill({ status: 400, json: { error: "Choose Full Reference for mixed roles." } }));
  await open(page);
  await page.getByLabel("Describe your video").fill("A person dances.");
  await page.getByLabel("Generated MiniMax H3 Prompt").fill("Keep my existing prompt.");
  await page.getByRole("button", { name: "Generate MiniMax prompt", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Choose Full Reference");
  await expect(page.getByLabel("Generated MiniMax H3 Prompt")).toHaveValue("Keep my existing prompt.");
});

test("mobile workflow has accessible controls and no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await expect(page.getByLabel("Describe your video")).toBeVisible();
  await expect(page.getByLabel("Generated MiniMax H3 Prompt")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
