import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { canConfirmDatasetReview, datasetConfirmationPayload } from "./datasetState.js";

async function loadReviewModal() {
  const sourceUrl = new URL("./DatasetConfirmationModal.jsx", import.meta.url);
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

test("confirmation contains no routing, vocabulary or scene-planning diagnostics", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {},
    confirmation_token: "synthetic", brief: brief({ must: ["Wear blue coats"] }),
    routing: [{ scope: "all_outputs", vocabulary: { loaded: 100, eligible: 3, rejected: 0 } }] } }));
  assert.doesNotMatch(markup, /Vocabulary diagnostics|Request routing|Supplied mechanics|P1\.hand|Show details/);
  assert.equal(markup.split("Wear blue coats").length - 1, 1);
  assert.match(markup, /Confirm understanding/);
  assert.doesNotMatch(markup.match(/<button[^>]*>Confirm<\/button>/)[0], /disabled/);
});

test("the brief is displayed directly and missing approval still gates confirmation", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {},
    confirmation_token: "", brief: brief({ summary: "Two adults reading", must: ["Keep both recognizable"] }),
    summary: { requested_generation: "Obsolete summary" } } }));
  assert.match(markup, /Two adults reading/);
  assert.match(markup, /Keep both recognizable/);
  assert.doesNotMatch(markup, /Obsolete summary/);
  assert.match(markup, /<button[^>]*disabled=""[^>]*>Confirm<\/button>/);
});

const broadMaleRoute = { scope: "all_outputs", nsfw: true,
  cast: { mode: "pair", count: 2, male: 2, female: 0, unspecified: 0, source: "approved_cast" },
  user_categories: [], director_categories: [], effective_categories: [], excluded_categories: [],
  position_pools: ["standing", "seated"], private_position_count: 12,
  kink_styling: false, ownership_styling: false };

test("review modal does not expose server routing", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {},
    brief: brief({ summary: "Concept does not contain the server routing" }),
    routing: [broadMaleRoute] } }));
  assert.doesNotMatch(markup, /aria-label="Request routing"|NSFW detected|Eligible vocabulary pools/);
});

test("vocabulary diagnostics stay outside the confirmation screen", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {},
    brief: brief({ summary: "Adults sharing an activity" }), routing: [{ ...broadMaleRoute,
      vocabulary: { loaded: 100, eligible: 7, rejected: 0, diagnostics: [], unresolved_constraints: [] } }] } }));
  assert.doesNotMatch(markup, /compatible TXT choices|Vocabulary diagnostics|100 loaded/);
  assert.doesNotMatch(markup, /structured arrangements|Approve selected|unresolved_structure/);
});

test("the modal renders each requirement once without a duplicated details view", async () => {
  const Modal = await loadReviewModal();
  const contract = brief({ randomized: 'Vary destinations marked "DUCK & friends".',
    must: ["Keep the required group."], avoid: ["No tattoos"] });
  const review = { status: "ready", confirmation_token: "synthetic", operation: "dataset",
    input: { subject: "Traveling friends", amount: 2, trigger: "duck, 2 men" }, brief: contract };
  const markup = renderToStaticMarkup(createElement(Modal, { review, busy: false,
    onRevise() {}, onConfirm() {}, onCancel() {} }));
  assert.equal(markup.split("Vary destinations marked").length - 1, 1);
  assert.match(markup, /<details class="dataset-review-details"><summary>Output settings<\/summary>/);
  assert.doesNotMatch(markup, /Also:|Rules every output must follow/);
  assert.match(markup, /DUCK &amp; friends/);
  assert.equal(markup.split("Keep the required group.").length - 1, 1);
  assert.equal(markup.split("No tattoos").length - 1, 1);
  assert.doesNotMatch(markup.match(/<button[^>]*>Confirm<\/button>/)[0], /disabled/);
});

test("confirmation waits for analysis, clarification answers and extra-instruction reanalysis", () => {
  const ready = { status: "ready", confirmation_token: "synthetic-token", brief: { clarifications: [] } };
  assert.equal(canConfirmDatasetReview(ready, false), true);
  assert.equal(canConfirmDatasetReview(ready, false, "Show the gloves"), false);
  assert.equal(canConfirmDatasetReview(ready, true), false);
  assert.equal(canConfirmDatasetReview({ ...ready, status: "analyzing" }, false), false);
  assert.equal(canConfirmDatasetReview({ ...ready, confirmation_token: "" }, false), false);
  assert.equal(canConfirmDatasetReview({ ...ready, brief: { clarifications: ["Which object?"] } }, false), false);
  assert.equal(canConfirmDatasetReview({ ...ready, brief: { clarifications: ["Which object?"] } }, false), false);
});

test("the current brief renders constraints, cast and settings safely and blocks busy confirmation", async () => {
  const Modal = await loadReviewModal();
  const contract = brief({ summary: "Boxing <script>not markup</script>", fixed: "Preserve the contact",
    randomized: "Background and light", must: ["Two adults with readable gloves", 'Show literal "DUCK"'],
    avoid: ["No tattoos <script>not markup</script>"],
    input: { guided_inputs: ["Punch", "Block"] } });
  const review = { status: "ready", confirmation_token: "synthetic", operation: "dataset",
    input: { subject: "Boxing", constraints: "Gloves", trigger: "boxer", source_mode: "random" }, brief: contract };
  const render = (item) => renderToStaticMarkup(createElement(Modal, { review: item, busy: false,
    onRevise() {}, onConfirm() {}, onCancel() {} }));
  const markup = render(review);
  for (const heading of ["Summary", "Stays the same", "Changes per image", "Ruled out", "Output settings", "Guided inputs"]) {
    assert.ok(markup.includes(`<h3>${heading}</h3>`), `missing ${heading}`);
  }
  assert.match(markup, /Preserve the contact/);
  assert.match(markup, /<details class="dataset-review-details"><summary>Output settings<\/summary>/);
  assert.doesNotMatch(markup, /Show details|Also:/);
  assert.doesNotMatch(markup, /Every output:/);
  assert.doesNotMatch(markup, /What the dataset will contain|Characters and identity/);
  assert.match(markup, /First reader: male/);
  assert.match(markup, /Second reader: elf/);
  assert.match(markup, /Two adults with readable gloves/);
  assert.match(markup, /Show literal &quot;DUCK&quot;/);
  assert.match(markup, /No tattoos &lt;script&gt;/);
  assert.match(markup, /Generic/);
  assert.match(markup, /<li>Punch<\/li><li>Block<\/li>/);
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.doesNotMatch(markup.match(/<button[^>]*>Confirm<\/button>/)[0], /disabled/);
  for (const status of ["analyzing", "confirming", "failed"]) {
    assert.match(render({ ...review, status }), /<button[^>]*disabled=""[^>]*>Confirm<\/button>/);
  }
  const nonCharacter = render({ ...review, brief: brief({ path: "non_character", people: 0, characters: [] }) });
  assert.doesNotMatch(nonCharacter, /aria-label="People"/);
  assert.equal(nonCharacter.split("None specified").length - 1, 1);
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

test("review lists the selected vocabulary packs, or says none were selected", async () => {
  const Modal = await loadReviewModal();
  const catalog = { categories: [{ id: "Spaces", name: "Spaces" }],
    packs: [{ id: "Spaces/Fantasy", name: "Fantasy", category: "Spaces", entries: ["enchanted forest"] }], problems: [] };
  const markup = renderToStaticMarkup(createElement(Modal, { catalog, review: { status: "ready", confirmation_token: "t",
    input: { vocabulary_packs: ["Spaces/Fantasy"] }, brief: brief() } }));
  assert.match(markup, /<li[^>]*>Fantasy<\/li>/);
  const none = renderToStaticMarkup(createElement(Modal, { catalog, review: { status: "ready", input: {}, confirmation_token: "t",
    brief: brief() } }));
  assert.match(none, /No packs selected/);
  assert.doesNotMatch(markup, /Visual direction|Structured details/);
});

test("review shows the run's Director beside the target model", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { directorLabel: "NSFW Director",
    review: { status: "ready", input: {}, confirmation_token: "t", brief: brief() } }));
  assert.match(markup, /<dt>Director<\/dt><dd>NSFW Director<\/dd>/);
});

test("a saved version 10 brief with an intent shows no intent details", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {}, confirmation_token: "t",
    brief: brief({ version: 10, intent: { available: true, elements: [], relations: [], unresolved: ["x"], warnings: ["y"] } }) } }));
  assert.doesNotMatch(markup, /Structured details|Left unclear/);
});
