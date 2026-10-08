import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { canConfirmDatasetReview, datasetRequestSignature, datasetUnderstandingSections, datasetUnderstandingSummary,
  reviseDatasetRequest } from "./workflows/datasetState.js";

test("approval shows hard obligations, soft preferences and free choices before rich interpretation", () => {
  const sections = datasetUnderstandingSections({ requested_generation: "One red ceramic cup",
    hard: [{ scope: "all_outputs", text: "Cup base touching table visible" }],
    soft: [{ scope: "all_outputs", text: "Close camera" }],
    free: [{ scope: "guided:2", text: "Background" }] });
  assert.deepEqual(sections.slice(0, 3), [
    { label: "Requirements", items: ["Cup base touching table visible"] },
    { label: "Adjustable preferences", items: ["Close camera"] },
    { label: "Open creative choices", items: ["Guided input 2: Background"] },
  ]);
});

test("request approval ignores result bookkeeping but detects every source and saved-scene edit", () => {
  const input = { subject: "Two people boxing", trigger: "person 1, person 2", amount: 2, target: "Generic",
    length: "Medium", constraints: "Arena. Gloves.", scene_plan: [{ index: 1, scene: "Boxing" }], results: [] };
  const signature = datasetRequestSignature(input);
  assert.equal(signature, datasetRequestSignature({ ...input, results: [{ prompt: "Old output" }], result_job_id: "old-job" }));
  for (const patch of [{ subject: "New concept" }, { trigger: "new_token" }, { amount: 3 }, { target: "Anima" },
    { constraints: "Blond hair" }, { length: "Detailed" }, { scene_plan: [{ index: 1, scene: "Edited scene" }] }]) {
    assert.notEqual(signature, datasetRequestSignature({ ...input, ...patch }));
  }
  assert.equal(signature, datasetRequestSignature(Object.fromEntries(Object.entries(input).reverse())));
});

test("understanding review retains all requirement categories and local scope", () => {
  const brief = { requested_generation: "Two adults boxing", fixed: [{ scope: "all_outputs", text: "Two adults" }],
    may_vary: [{ scope: "dataset", text: "Lighting" }], must_vary: [{ scope: "dataset", text: "Actions" }],
    rules: [{ scope: "guided:2", text: "In a gym" }],
    visible_evidence: [{ scope: "all_outputs", text: "Gloves" }],
    interactions: [{ scope: "all_outputs", text: "Glove-to-cheek contact" }],
    natural_occlusions: [{ scope: "all_outputs", text: "The glove obscures the contact area" }],
    visibility_to_preserve: [{ scope: "all_outputs", text: "Enough of the head remains exposed" }],
    physical_conflicts: [{ scope: "all_outputs", conflict: "Unobstructed cheek conflicts with contact.", compatible_resolution: null }] };
  const sections = datasetUnderstandingSections(brief);
  assert.equal(sections.length, 12);
  assert.equal(sections[3].items[0], "Two adults");
  assert.equal(sections[4].items[0], "Across the dataset: Lighting");
  assert.equal(sections[6].items[0], "Guided input 2: In a gym");
  assert.match(sections[11].items[0], /Needs clarification/);
});

test("understanding summary groups global rules once without repeating their image scope", () => {
  const summary = datasetUnderstandingSummary({ requested_generation: "Duck and dinosaur confronting each other",
    fixed: [{ scope: "all_outputs", text: "Every image must contain the duck" }],
    hard: [{ scope: "all_outputs", text: "Every image must contain the duck" },
      { scope: "all_outputs", text: "EVERY IMAGE must contain the dinosaur" },
      { scope: "all_outputs", text: "Each image must show an active confrontation" }],
    rules: [{ scope: "all_outputs", text: "Each image must show an active confrontation" },
      { scope: "all_outputs", text: "EVERY IMAGE must contain the dinosaur" }],
    may_vary: [{ scope: "dataset", text: "Locations" }],
    free: [{ scope: "dataset", text: "Locations" }], must_vary: [{ scope: "dataset", text: "Poses" }] });
  assert.deepEqual(summary.consistent, ["must contain the duck"]);
  assert.deepEqual(summary.everyImage, ["must contain the dinosaur", "must show an active confrontation"]);
  assert.deepEqual(summary.mayVary, ["Across the dataset: Locations"]);
  assert.deepEqual(summary.mustVary, ["Across the dataset: Poses"]);
  assert.doesNotMatch(JSON.stringify(summary), /every image/i);
});

test("understanding grouping preserves local scope, qualifiers and distinct obligations", () => {
  const summary = datasetUnderstandingSummary({ requested_generation: "A fight",
    hard: [{ scope: "all_outputs", text: "At least one person is blond" },
      { scope: "guided:2", text: "Every image must contain two people" },
      { scope: "dataset", text: "Include both indoor and outdoor settings" },
      { scope: "all_outputs", text: "Both gloves remain visible" },
      { scope: "all_outputs", text: "One glove contacts the cheek" },
      { scope: "all_outputs", text: "Part of the face remains visible" }],
    fixed: [{ scope: "guided:1", text: "Exactly one person" }],
    visible_evidence: [{ scope: "all_outputs", text: "Both gloves remain visible" }],
    interactions: [{ scope: "all_outputs", text: "One glove contacts the cheek" }],
    visibility_to_preserve: [{ scope: "all_outputs", text: "Part of the face remains visible" }] });
  assert.deepEqual(summary.everyImage, ["At least one person is blond", "Both gloves remain visible",
    "One glove contacts the cheek", "Part of the face remains visible"]);
  assert.deepEqual(summary.scoped, ["Guided input 2: Every image must contain two people",
    "Across the dataset: Include both indoor and outdoor settings"]);
  assert.deepEqual(summary.consistent, ["Guided input 1: Exactly one person"]);
});

test("understanding summary keeps the concise contract upfront and rich explanations in details", () => {
  const brief = { requested_generation: "Two sparring partners",
    hard: [{ scope: "all_outputs", text: "Both people wear visible gloves and at least one has blond hair" }],
    rules: [{ scope: "all_outputs", text: "Both people wear gloves" }],
    visible_evidence: [{ scope: "all_outputs", text: "Visible gloves and blond hair" }] };
  assert.deepEqual(datasetUnderstandingSummary(brief).everyImage,
    ["Both people wear visible gloves and at least one has blond hair"]);
  assert.ok(datasetUnderstandingSections(brief).some(({ items }) => items.includes("Visible gloves and blond hair")));
  assert.deepEqual(datasetUnderstandingSummary({ ...brief, hard: [] }).everyImage,
    ["Both people wear gloves", "Visible gloves and blond hair"]);
});

test("grouping never deduplicates distinct case-sensitive literal requirements", () => {
  const summary = datasetUnderstandingSummary({ hard: [
    { scope: "all_outputs", text: 'Include the exact text "DUCK"' },
    { scope: "all_outputs", text: 'Include the exact text "duck"' },
  ] });
  assert.equal(summary.everyImage.length, 2);
});

test("richer understanding keeps scoped action alternatives separate from required interactions", () => {
  const sections = datasetUnderstandingSections({ requested_generation: "Two people sparring",
    action_options: [{ scope: "guided:2", text: "Punch or block, not both in one frozen image" }] });
  const actions = sections.find(({ label }) => label === "Action alternatives—not all in one image");
  assert.deepEqual(actions?.items, ["Guided input 2: Punch or block, not both in one frozen image"]);
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

test("writer completion and failure bookkeeping does not invalidate approval of the same scene", () => {
  const scene = { index: 1, idea: "Reading", scene: "A person reads on a bench.", self_check: "PASS",
    scene_status: "valid", prompt_status: "not_generated" };
  const input = { subject: "A reader", scene_plan: [scene], results: [] };
  const signature = datasetRequestSignature(input);
  for (const prompt_status of ["valid", "failed"]) {
    assert.equal(datasetRequestSignature({ ...input, scene_plan: [{ ...scene, prompt_status,
      failure_stage: "prompt", failure_reason: "Writer failed." }] }), signature);
  }
  for (const change of [{ scene: "Edited scene" }, { self_check: "" }, { scene_status: "not_generated" },
    { failure_stage: "scene", failure_reason: "Scene failed." }]) {
    assert.notEqual(datasetRequestSignature({ ...input, scene_plan: [{ ...scene, ...change }] }), signature);
  }
});

test("the existing modal renders the new brief, keeps extra instructions and blocks unresolved questions", async () => {
  const sourceUrl = new URL("./workflows/DatasetConfirmationModal.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  const { default: Modal } = await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`);
  const brief = { requested_generation: "Boxing <script>not markup</script>", expansion_freedom: "Preserve the contact",
    hard: [{ scope: "all_outputs", text: "Two adults with readable gloves" }],
    soft: [{ scope: "all_outputs", text: "Warm lighting" }],
    free: [{ scope: "guided:1", text: "Background <script>not markup</script>" }],
    character_count: 2, identity_policy: "random_per_prompt",
    action_options: [{ scope: "guided:1", text: "Punch or block <script>not markup</script>" }],
    dataset_contents: "One prompt", fixed: [{ scope: "all_outputs", text: "Two adults" }],
    may_vary: [{ scope: "dataset", text: "Lighting" }], must_vary: [{ scope: "dataset", text: "Actions" }],
    rules: [{ scope: "all_outputs", text: "Gloves" }], visible_evidence: [{ scope: "all_outputs", text: "Readable glove" }],
    interactions: [{ scope: "all_outputs", text: "Glove contact" }], natural_occlusions: [{ scope: "all_outputs", text: "Partial cheek" }],
    visibility_to_preserve: [{ scope: "guided:1", text: "Exposed head" }],
    physical_conflicts: [{ scope: "all_outputs", conflict: "Full cheek exposure.", compatible_resolution: null }],
    clarifications: ["Allow partial overlap?"] };
  const review = { status: "ready", confirmation_token: "synthetic", operation: "dataset",
    input: { subject: "Boxing", constraints: "Gloves", trigger: "boxer", source_mode: "random" }, brief };
  const render = (item) => renderToStaticMarkup(createElement(Modal, { review: item, busy: false,
    onRevise() {}, onConfirm() {}, onCancel() {} }));
  const markup = render(review);
  for (const section of datasetUnderstandingSections(brief)) assert.ok(markup.includes(section.label));
  for (const heading of ["Concept", "What stays consistent", "What should vary", "Every image should", "Output settings"]) {
    assert.ok(markup.includes(`<h3>${heading}</h3>`), `missing ${heading}`);
  }
  assert.match(markup, /Preserve the contact/);
  assert.match(markup, /<details[^>]*><summary>Show details/);
  assert.doesNotMatch(markup, /Every output:/);
  assert.match(markup, /What the dataset will contain/);
  assert.match(markup, /Characters and identity/);
  assert.match(markup, /Randomized per independent prompt/);
  assert.match(markup, /Requirements/);
  assert.match(markup, /Adjustable preferences/);
  assert.match(markup, /Open creative choices/);
  assert.match(markup, /Generated ideas are suggestions, not new requirements/);
  assert.match(markup, /Guided input 1: Punch or block &lt;script&gt;/);
  assert.match(markup, /Extra instructions or answers/);
  assert.match(markup, /Update summary/);
  assert.match(markup, /Allow partial overlap\?/);
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.match(markup, /<button[^>]*disabled=""[^>]*>Confirm and generate prompts<\/button>/);
  const resolved = { ...review, brief: { ...brief, physical_conflicts: [], clarifications: [] } };
  assert.doesNotMatch(render(resolved).match(/<button[^>]*>Confirm and generate prompts<\/button>/)[0], /disabled/);
  assert.match(render({ ...resolved, operation: "dataset/scenes" }), /Confirm and generate scenes/);
  assert.match(render({ ...resolved, options: { resume: true } }), /Confirm and continue/);
});

test("extra instructions create an isolated revised request without discarding old results", () => {
  const input = { constraints: "Arena. Gloves.", scene_plan: [{ scene: "Existing scene" }],
    scene_plan_signature: "saved", results: [{ prompt: "Manually edited output" }] };
  const before = structuredClone(input);
  const revised = reviseDatasetRequest(input, "  One person must have blond hair.  ");
  assert.equal(revised.constraints, "Arena. Gloves.\nOne person must have blond hair.");
  assert.deepEqual(revised.scene_plan, []);
  assert.equal(revised.scene_plan_signature, "");
  assert.deepEqual(revised.results, input.results);
  assert.deepEqual(input, before);
  assert.equal(reviseDatasetRequest(input, "  "), input);
});
