import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { canConfirmDatasetReview, datasetRequestSignature, datasetUnderstandingSections, datasetUnderstandingSummary,
  reviseDatasetRequest } from "./datasetState.js";

async function loadReviewModal() {
  const sourceUrl = new URL("./DatasetConfirmationModal.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  return (await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`)).default;
}

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

test("mandatory variation appears once in the summary without losing its scope", () => {
  const location = { scope: "dataset", text: "Vary the destinations across the dataset." };
  const local = { scope: "guided:2", text: "Vary only the background for this input." };
  const consistency = { scope: "all_outputs", text: "Exactly one red duck and two men." };
  const brief = { hard: [location, local, consistency, location], fixed: [consistency],
    must_vary: [location, local, location], rules: [location],
    free: [{ scope: "dataset", text: "Choose one shared vehicle once." }] };
  const before = structuredClone(brief);
  assert.deepEqual(datasetUnderstandingSummary(brief), {
    consistent: ["Exactly one red duck and two men."],
    mayVary: ["Across the dataset: Choose one shared vehicle once."],
    mustVary: ["Across the dataset: Vary the destinations across the dataset.",
      "Guided input 2: Vary only the background for this input."], everyImage: [], scoped: [],
  });
  assert.deepEqual(brief, before);
});

test("details show each exact scoped fact once and retain all of its review tags", () => {
  const duck = { scope: "all_outputs", text: "Exactly one red duck." };
  const travel = { scope: "all_outputs", text: "The duck and two men travel together as best friends." };
  const destinations = { scope: "dataset", text: "Vary destinations." };
  const freedom = { scope: "guided:2", text: "Unspecified clothing, setting and composition remain open." };
  const brief = { requested_generation: "Traveling friends", hard: [duck, travel, destinations, duck],
    fixed: [duck], rules: [duck, travel], interactions: [travel], must_vary: [destinations],
    free: [freedom], may_vary: [freedom, freedom] };
  const before = structuredClone(brief);
  const sections = datasetUnderstandingSections(brief);
  assert.deepEqual(sections[0].items, [duck.text, travel.text, "Across the dataset: Vary destinations."]);
  assert.deepEqual(sections[0].annotations, [
    ["What stays fixed", "Rules every output must follow"],
    ["Rules every output must follow", "Required interactions"], ["What must vary"],
  ]);
  assert.deepEqual(sections[2].items, ["Guided input 2: Unspecified clothing, setting and composition remain open."]);
  assert.deepEqual(sections[2].annotations, [["What may vary"]]);
  assert.equal(sections.flatMap(({ items }) => items).length, 4);
  assert.deepEqual(brief, before);
});

test("display deduplication preserves authority, qualifiers, literal whitespace and scopes", () => {
  const same = { scope: "all_outputs", text: "Warm lighting" };
  const brief = { requested_generation: "A sign",
    hard: [same, { scope: "all_outputs", text: 'Show the text "NO  ENTRY"' },
      { scope: "all_outputs", text: 'Show the text "NO ENTRY"' },
      { scope: "all_outputs", text: 'Show the text "no entry"' },
      { scope: "guided:1", text: "Warm lighting" }, { scope: "guided:2", text: "Warm lighting" },
      { scope: "all_outputs", text: "At least one man is blond" },
      { scope: "all_outputs", text: "Both men are blond" }],
    soft: [same], free: [same], fixed: [same],
    rules: [{ scope: "all_outputs", text: "Warm lighting is required" }] };
  const before = structuredClone(brief);
  const sections = datasetUnderstandingSections(brief);
  assert.equal(sections[0].items.length, 8);
  assert.deepEqual(sections[1].items, ["Warm lighting"]);
  assert.deepEqual(sections[2].items, ["Warm lighting"]);
  assert.equal(sections.flatMap(({ items }) => items).length, 11);
  assert.ok(sections.flatMap(({ items }) => items).includes("Warm lighting is required"));
  const summary = datasetUnderstandingSummary(brief);
  assert.deepEqual(summary.consistent, ["Warm lighting"]);
  assert.deepEqual(summary.mayVary, ["Warm lighting"]);
  assert.deepEqual(summary.scoped, ["Guided input 1: Warm lighting", "Guided input 2: Warm lighting"]);
  assert.equal(summary.everyImage.length, 5);
  assert.deepEqual(brief, before);
});

test("legacy review tags retain their categories when no contract arrays are supplied", () => {
  const contact = { scope: "guided:1", text: "One glove contacts the cheek." };
  const overlap = { scope: "guided:1", text: "Contact naturally hides part of the cheek." };
  const brief = { requested_generation: "Sparring", interactions: [contact, contact],
    visible_evidence: [contact], natural_occlusions: [overlap, overlap] };
  const sections = datasetUnderstandingSections(brief);
  const evidence = sections.find(({ label }) => label === "Required visible evidence");
  assert.deepEqual(evidence.items, ["Guided input 1: One glove contacts the cheek."]);
  assert.deepEqual(evidence.annotations, [["Required interactions"]]);
  assert.deepEqual(sections.flatMap(({ items }) => items), [
    "Guided input 1: One glove contacts the cheek.", "Guided input 1: Contact naturally hides part of the cheek.",
  ]);
});

test("overlap explanations and action alternatives retain their authority and category labels", () => {
  const required = { scope: "guided:1", text: "The required hand contact may hide its interface." };
  const context = { scope: "guided:1", text: "A raised sleeve can naturally obscure the wrist." };
  const options = { scope: "guided:2", text: "Punch or block, not both in one frozen image." };
  const brief = { requested_generation: "Sparring", hard: [required, options],
    natural_occlusions: [required, context], interactions: [options], action_options: [options] };
  const sections = datasetUnderstandingSections(brief);
  assert.deepEqual(sections[0].annotations, [["Natural overlaps and occlusions"],
    ["Required interactions", "Action alternatives—not all in one image"]]);
  assert.deepEqual(sections.find(({ label }) => label === "Natural overlaps and occlusions").items,
    ["Guided input 1: A raised sleeve can naturally obscure the wrist."]);
  assert.equal(sections.flatMap(({ items }) => items).length, 3);
});

test("conflict deduplication never hides distinct resolutions or unresolved questions", () => {
  const conflict = { scope: "guided:1", conflict: "Eyes-only crop excludes shoes.", compatible_resolution: null };
  const brief = { requested_generation: "A portrait", physical_conflicts: [conflict, conflict,
    { ...conflict, compatible_resolution: "Show a reflection preserving both requirements." },
    { ...conflict, scope: "guided:2" }], clarifications: ["Which crop is required?"] };
  const sections = datasetUnderstandingSections(brief);
  const conflicts = sections.find(({ label }) => label === "Physical conflicts and possible resolutions");
  assert.equal(conflicts.items.length, 3);
  assert.match(conflicts.items[0], /Needs clarification/);
  assert.match(conflicts.items[1], /Show a reflection/);
  assert.match(conflicts.items[2], /Guided input 2/);
  assert.equal(canConfirmDatasetReview({ status: "ready", confirmation_token: "synthetic", brief }, false), false);
});

test("the modal renders duplicate facts once per view while retaining tag labels", async () => {
  const Modal = await loadReviewModal();
  const fact = { scope: "dataset", text: 'Vary destinations marked "DUCK & friends".' };
  const brief = { requested_generation: "Traveling friends", hard: [fact, fact], must_vary: [fact],
    rules: [fact], expansion_freedom: "Keep the required group.", dataset_contents: "Two prompts",
    character_count: 3, identity_policy: "random_per_prompt", clarifications: [] };
  const review = { status: "ready", confirmation_token: "synthetic", operation: "dataset",
    input: { subject: "Traveling friends", amount: 2, trigger: "duck, 2 men" }, brief };
  const markup = renderToStaticMarkup(createElement(Modal, { review, busy: false,
    onRevise() {}, onConfirm() {}, onCancel() {} }));
  const [summary, details] = markup.split(/<details[^>]*>/);
  assert.equal(summary.split("Vary destinations marked").length - 1, 1);
  assert.equal(details.split("Vary destinations marked").length - 1, 1);
  assert.match(summary, /Must vary/);
  assert.doesNotMatch(summary, /Scoped requirements/);
  assert.match(details, /What must vary/);
  assert.match(details, /Rules every output must follow/);
  assert.match(markup, /DUCK &amp; friends/);
  assert.doesNotMatch(markup.match(/<button[^>]*>Confirm and generate prompts<\/button>/)[0], /disabled/);
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
  const Modal = await loadReviewModal();
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
