import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { datasetConfirmationPayload } from "./datasetState.js";

async function loadOverlay() {
  const sourceUrl = new URL("./DatasetUnderstandingOverlay.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  return (await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`)).default;
}

function brief(overrides = {}) {
  return { version: 9, path: "sfw_character", summary: "Two adults greet each other", people: 2,
    characters: [{ label: "First reader", gender: "male", custom: "", pronoun: "he" },
      { label: "Second reader", gender: "custom", custom: "elf", pronoun: "she" }],
    fixed: "The two readers", randomized: "Lighting and framing", must: [], avoid: [],
    input: { request: "Two adults greet each other", rules: [], amount: 2, nsfw: false },
    settings: { style: "Auto", target: "Generic", director: "general_director", length: "Medium", creativity: "Balanced" },
    ...overrides };
}

async function render(understanding) {
  const Overlay = await loadOverlay();
  return renderToStaticMarkup(createElement(Overlay, { understanding, onCancel() {} }));
}

test("while the request is read the overlay shows the animation, its status and a Cancel button", async () => {
  const markup = await render({ status: "analyzing", input: {}, brief: null });
  assert.match(markup, /<div class="dataset-pulse" aria-hidden="true">/);
  assert.match(markup, /role="status"[^>]*>Reading your request…<\/p>/);
  assert.match(markup, /<button[^>]*>Cancel<\/button>/);
  assert.doesNotMatch(markup, /<button[^>]*disabled/);
});

test("the understood request is never shown and nothing asks for confirmation", async () => {
  const markup = await render({ status: "confirming", input: {}, confirmation_token: "synthetic",
    brief: brief({ summary: "Two adults reading", must: ["Keep both recognizable"] }) });
  assert.match(markup, /Request understood\. Starting the scenes…/);
  assert.doesNotMatch(markup, /Two adults reading|Keep both recognizable|First reader|Confirm/);
  assert.match(markup, /<button[^>]*>Cancel<\/button>/);
});

test("a stopped request shows its reason and can be closed", async () => {
  const markup = await render({ status: "failed", input: {}, error: "Scene writing could not start <script>x</script>" });
  assert.match(markup, /role="alert"[^>]*>Scene writing could not start &lt;script&gt;/);
  assert.doesNotMatch(markup, /dataset-pulse|<script>/);
  assert.match(markup, /<button[^>]*>Close<\/button>/);
});

test("confirmation submission preserves scenes-only choice, source, approval and chosen seed", () => {
  const review = { brief: brief(), input: { seed: 73, seed_mode: "fixed", inputs: "Read\nWalk" },
    operation: "dataset/scenes", confirmation_token: "synthetic" };
  assert.deepEqual(datasetConfirmationPayload(review), review);
  assert.equal(datasetConfirmationPayload({ ...review, operation: "dataset" }).operation, "dataset");
});

test("confirmation sends no separate vocabulary: the packs travel in the reviewed input", () => {
  const review = { brief: brief(), input: { vocabulary_packs: ["Spaces/Fantasy"] }, operation: "dataset",
    confirmation_token: "synthetic", status: "ready", baseSignature: "x" };
  const payload = datasetConfirmationPayload(review);
  assert.deepEqual(Object.keys(payload).sort(), ["brief", "confirmation_token", "input", "operation"]);
  assert.deepEqual(payload.input.vocabulary_packs, ["Spaces/Fantasy"]);
});
