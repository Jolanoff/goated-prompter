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
  position_pools: ["anal", "oral"], private_position_count: 12,
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
  assert.match(markup, /<details class="dataset-review-details"><summary>Details and corrections<\/summary>/);
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
  assert.match(markup, /<details class="dataset-review-details"><summary>Details and corrections<\/summary>/);
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
    operation: "dataset/scenes", confirmation_token: "synthetic", vocabulary_packs: ["fantasy"] };
  assert.deepEqual(datasetConfirmationPayload(review), review);
  assert.equal(datasetConfirmationPayload({ ...review, operation: "dataset" }).operation, "dataset");
});

test("confirmation sends the pack choice frozen into the review, never an extra field", () => {
  const review = { brief: brief(), input: {}, operation: "dataset", confirmation_token: "synthetic",
    vocabulary_packs: ["adult", "fantasy"], status: "ready", baseSignature: "x" };
  const payload = datasetConfirmationPayload(review);
  assert.deepEqual(Object.keys(payload).sort(), ["brief", "confirmation_token", "input", "operation", "vocabulary_packs"]);
  assert.deepEqual(payload.vocabulary_packs, ["adult", "fantasy"]);
  assert.notEqual(payload.vocabulary_packs, review.vocabulary_packs);
  // Only core: an empty choice is still sent explicitly.
  assert.deepEqual(datasetConfirmationPayload({ ...review, vocabulary_packs: [] }).vocabulary_packs, []);
});

test("review shows the packs the run will record", async () => {
  const Modal = await loadReviewModal();
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {},
    confirmation_token: "synthetic", brief: brief(), vocabulary_packs: ["fantasy", "my_pack"] } }));
  assert.match(markup, /Vocabulary packs/);
  assert.match(markup, /Core, fantasy, my_pack/);
});

// Understanding v10: structured details in the review.
const part = (id, kind, text, extra = {}) => ({ id, kind, text, status: "fixed", source: "request", character: "", cast: [], of: "",
  member: 0, by: [], to: [], input: 0, terms: [], ...extra });
function intentOf(overrides = {}) {
  return { available: true, truncated: false, unresolved: ['who "she" is'], warnings: ['"smooching" is not worded this way in the request.'],
    elements: [part("s1", "subject", "woman", { character: "woman", cast: ["woman"] }), part("s2", "subject", "men", { character: "man", cast: ["man 1", "man 2"] }),
      part("b1", "body_part", "neck", { of: "s2" }), part("a1", "action", "kisses", { by: ["s1"], to: ["b1"], terms: ["kiss"] }),
      part("k1", "aspect", "lighting", { status: "randomized", source: "suggested" })],
    relations: [{ id: "r1", a: "s1", rel: "behind", b: "s2", status: "fixed" }], ...overrides };
}

test("a v10 review shows the request part by part; a v9 brief shows no details", async () => {
  const Modal = await loadReviewModal();
  const render = (props) => renderToStaticMarkup(createElement(Modal, { review: { status: "ready", input: {}, confirmation_token: "t", ...props } }));
  assert.doesNotMatch(render({ brief: brief() }), /Structured details/);
  const markup = render({ brief: brief({ version: 10, intent: intentOf() }) });
  for (const expected of ["Structured details", "People and subjects", "woman → kisses → neck (men (man 1, man 2))", "man 1, man 2", "Every image",
    "Varies", "Suggested", "Related ideas (inferred): kiss", "How parts relate", "woman behind men (man 1, man 2)", "Left unclear (not guessed)",
    "is not worded this way", "use Revise"]) {
    assert.ok(markup.includes(expected.replaceAll('"', "&quot;")), expected);
  }
  assert.doesNotMatch(markup, /Remove lighting|aria-label="Related ideas/, "read-only without an edit handler");
  const unavailable = render({ brief: brief({ version: 10, intent: { available: false, elements: [], relations: [], unresolved: [],
    truncated: false, warnings: ["Structured details are unavailable (its structure was invalid)."] } }) });
  assert.match(unavailable, /Structured details are unavailable/);
  assert.doesNotMatch(unavailable, /People and subjects/);
});

test("a ready review offers only the corrections the server allows", async () => {
  const Modal = await loadReviewModal();
  const review = { status: "ready", input: {}, confirmation_token: "t", brief: brief({ version: 10, intent: intentOf() }) };
  const markup = renderToStaticMarkup(createElement(Modal, { review, onEditIntent: () => {} }));
  assert.match(markup, /aria-label="Remove lighting"/, "a suggestion can be removed");
  assert.doesNotMatch(markup, /aria-label="Remove (woman|men|kisses|neck)"/, "what the request states cannot");
  assert.match(markup, /aria-label="Related ideas \(inferred\) for kisses"/);
  assert.match(markup, /Correct who does what/);
  assert.match(markup, /aria-label="Dismiss: who &quot;she&quot; is"/);
  const confirming = renderToStaticMarkup(createElement(Modal, { review: { ...review, status: "confirming" }, onEditIntent: () => {} }));
  assert.doesNotMatch(confirming, /aria-label="Related ideas|aria-label="Remove lighting"/, "no edits while confirming");
});

test("intent annotations cannot become mandatory, variable or excluded requirements", async () => {
  const Modal = await loadReviewModal();
  const intent = intentOf({ warnings: [], unresolved: [], elements: [
    part("s1", "subject", "invented identity", { character: "First reader", cast: ["First reader"] }),
    part("o", "object", "mandatory telescope", { terms: ["optics"] }),
    part("a", "action", "studies", { by: ["s1"], to: ["o"] }),
    part("v", "aspect", "invented variation", { status: "randomized", source: "suggested" }),
    part("x", "object", "invented exclusion", { status: "excluded" }),
  ], relations: [] });
  const contract = brief({ version: 10, fixed: "Authoritative fixed detail", randomized: "Authoritative variation",
    must: ["Authoritative obligation"], avoid: ["Authoritative exclusion"], intent });
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", confirmation_token: "t", brief: contract } }));
  const section = (title) => markup.match(new RegExp(`<section[^>]*aria-label="${title}"[\\s\\S]*?<\\/section>`))[0];
  assert.match(section("Stays the same"), /Authoritative fixed detail.*Authoritative obligation/);
  assert.match(section("Changes per image"), /Authoritative variation/);
  assert.match(section("Ruled out"), /Authoritative exclusion/);
  for (const title of ["Stays the same", "Changes per image", "Ruled out", "People"]) {
    assert.doesNotMatch(section(title), /mandatory telescope|invented identity|invented variation|invented exclusion/);
  }
  const details = markup.split('<details class="dataset-review-details"')[1];
  assert.match(details, /mandatory telescope/);
  assert.match(details, /optics/);
  assert.match(details, /annotations are not additional requirements/);
  assert.doesNotMatch(details, />Every image<|>Ruled out</);
});

test("intent edits are pure, keep what the request states and travel with Confirm", async () => {
  const edits = await import("./datasetIntent.js");
  const intent = intentOf();
  assert.equal(edits.canRemovePart(intent, intent.elements[4]), true);
  assert.equal(edits.canRemovePart(intent, intent.elements[0]), false, "stated, and linked");
  const fewer = edits.removePart(intent, "k1");
  assert.deepEqual(fewer.elements.map((item) => item.id), ["s1", "s2", "b1", "a1"]);
  assert.equal(intent.elements.length, 5, "the original is not mutated");
  assert.deepEqual(edits.setTerms(intent, "a1", " kiss, peck,, kiss , a, b, c, d, e").elements[3].terms, ["kiss", "peck", "a", "b", "c", "d"]);
  assert.deepEqual(edits.linkChoices(intent, intent.elements[3], "by").map((item) => item.id), ["s1", "s2"]);
  assert.ok(!edits.linkChoices(intent, intent.elements[3], "to").some((item) => item.kind === "aspect"));
  assert.equal(edits.setRelationEnd(intent, "r1", "a", "s2").relations[0].a, "s2");
  assert.deepEqual(edits.dismissNote(intent, 0).unresolved, []);
  const review = { brief: brief({ version: 10, intent: fewer }), input: {}, operation: "dataset", confirmation_token: "t", vocabulary_packs: [] };
  assert.deepEqual(datasetConfirmationPayload(review).brief.intent, fewer);
});

test("participant names distinguish identical people, their belongings and groups", async () => {
  const { partName, partSentence } = await import("./datasetIntent.js");
  const intent = intentOf({ elements: [
    part("m1", "subject", "man", { character: "man", member: 1, cast: ["man 1"] }),
    part("m2", "subject", "man", { character: "man", member: 2, cast: ["man 2"] }),
    part("g", "subject", "women", { cast: ["woman 1", "woman 2", "woman 3"] }),
    part("hand", "body_part", "hand", { of: "m2" }),
    part("a", "action", "shakes", { by: ["m1"], to: ["hand"] }),
  ], relations: [] });
  assert.equal(partName(intent, "m1"), "man 1");
  assert.equal(partName(intent, "m2"), "man 2");
  assert.equal(partName(intent, "g"), "women (woman 1, woman 2, woman 3)");
  assert.equal(partSentence(intent, intent.elements[4]), "man 1 → shakes → hand (man 2)");
  assert.equal(partName(intent, "missing"), "missing");
});

test("review is readable before opening corrections, with warnings and uncertainty always visible", async () => {
  const Modal = await loadReviewModal();
  const intent = intentOf({ elements: [...intentOf().elements,
    part("o", "object", "cap", { status: "optional" }),
    part("x", "object", "knives", { status: "excluded" })] });
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", confirmation_token: "t",
    brief: brief({ version: 10, intent }) }, onEditIntent() {} }));
  const boundary = markup.indexOf('<details class="dataset-review-details"');
  assert.ok(boundary > 0, "corrections have one disclosure");
  const upfront = markup.slice(0, boundary), details = markup.slice(boundary);
  assert.match(details, /^<details[^>]*><summary>Details and corrections<\/summary>/, "collapsed by default");
  for (const heading of ["Summary", "What happens", "Stays the same", "Changes per image", "Allowed", "Ruled out"]) {
    assert.ok(upfront.includes(`<h3>${heading}</h3>`), heading);
  }
  assert.match(upfront, /woman → kisses → neck/);
  assert.match(upfront, /cap/);
  assert.doesNotMatch(upfront, /knives/, "annotations alone cannot introduce exclusions");
  assert.match(details, /knives/, "the interpreted exclusion remains inspectable");
  assert.match(upfront, /Details to check/);
  assert.match(upfront, /Left unclear \(not guessed\)/);
  assert.match(upfront, /who &quot;she&quot; is/);
  assert.doesNotMatch(upfront, /<input|<select|Dismiss|Related ideas|Output settings/);
  assert.match(details, /Related ideas \(inferred\)/);
  assert.match(details, /Correct who does what/);
  assert.match(details, /Output settings/);
});

test("member corrections update display cast without mutating approved intent or losing links", async () => {
  const { setMember, partName } = await import("./datasetIntent.js");
  const characters = [1, 2].map((n) => ({ label: `man ${n}`, gender: "male" }));
  const intent = intentOf({ elements: [part("m", "subject", "men", { character: "man", cast: ["man 1", "man 2"] }),
    part("a", "action", "reads", { by: ["m"] })], relations: [] });
  const corrected = setMember(intent, "m", 2, characters);
  assert.equal(corrected.elements[0].member, 2);
  assert.equal(partName(corrected, "m"), "man 2");
  assert.deepEqual(corrected.elements[1].by, ["m"]);
  assert.deepEqual(intent.elements[0].cast, ["man 1", "man 2"]);
  assert.equal(intent.elements[0].member, 0);
  assert.deepEqual(setMember(corrected, "m", 0, characters).elements[0].cast, ["man 1", "man 2"]);
  assert.deepEqual(datasetConfirmationPayload({ brief: brief({ intent: corrected }) }).brief.intent, corrected);
  const Modal = await loadReviewModal();
  const review = { status: "ready", confirmation_token: "t", brief: brief({ version: 10, characters, intent }) };
  const render = (props) => renderToStaticMarkup(createElement(Modal, { review, ...props }));
  assert.match(render({ onEditIntent() {} }), /aria-label="Person represented by men \(man 1, man 2\)"/);
  assert.doesNotMatch(render({}), /Person represented by/);
  assert.doesNotMatch(render({ review: { ...review, status: "confirming" }, onEditIntent() {} }), /Person represented by/);
  const stored = structuredClone(intent);
  delete stored.elements[0].member;
  const oldMarkup = render({ review: { ...review, brief: brief({ version: 10, characters, intent: stored }) }, onEditIntent() {} });
  assert.doesNotMatch(oldMarkup, /Person represented by/, "pre-member briefs must not gain fields the review contract disallows");
  assert.match(oldMarkup, /aria-label="Related ideas/, "existing corrections remain available");
});

test("actions keep their distinct actors, scope and status in review and correction choices", async () => {
  const Modal = await loadReviewModal();
  const intent = intentOf({ warnings: [], unresolved: [], elements: [
    part("m1", "subject", "man", { character: "man", member: 1, cast: ["man 1"] }),
    part("m2", "subject", "man", { character: "man", member: 2, cast: ["man 2"] }),
    part("a1", "action", "reads", { by: ["m1"], input: 1 }),
    part("a2", "action", "waves", { by: ["m2"], to: ["m1"], input: 2 }),
    part("x", "action", "smiling", { by: ["m1"], status: "excluded" }),
    part("o", "action", "dancing", { by: ["m2"], status: "optional" }),
    part("g", "subject", "audience", { status: "excluded" }),
  ], relations: [{ id: "r1", a: "m2", rel: "behind", b: "a1", status: "fixed" }] });
  const markup = renderToStaticMarkup(createElement(Modal, { review: { status: "ready", confirmation_token: "t",
    brief: brief({ version: 10, intent, characters: [1, 2].map((n) => ({ label: `man ${n}`, gender: "male" })) }) }, onEditIntent() {} }));
  const upfront = markup.split('<details class="dataset-review-details"')[0];
  const actions = upfront.match(/<section[^>]*aria-label="What happens"[\s\S]*?<\/section>/)[0];
  assert.match(actions, /Guided input 1: man 1 → reads/);
  assert.match(actions, /Guided input 2: man 2 → waves → man 1/);
  assert.match(actions, /Guided input 1: man 2 behind reads/);
  assert.doesNotMatch(actions, /smiling|dancing/);
  assert.match(upfront, /aria-label="Allowed"[^]*man 2 → dancing/);
  assert.match(upfront, /aria-label="Ruled out"[^]*None specified/);
  assert.doesNotMatch(upfront, /smiling|audience/, "only authoritative exclusions are requirements");
  assert.match(markup.split('<details class="dataset-review-details"')[1], /man 1 → smiling[^]*audience/);
  assert.match(markup, /value="m1">man 1<\/option>/);
  assert.match(markup, /value="m2">man 2<\/option>/);
});
