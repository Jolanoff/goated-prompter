import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileView } from "./testSupport.js";

// compileView also compiles the JSX views the explorer imports (PackSelector.jsx).
const { EntryDetails, ExplorerView, RetrievalResults } = await import(await compileView(new URL("./VocabularyExplorer.jsx", import.meta.url)));
const noop = () => {};
const pack = { id: "adult", name: "Adult", origin: "bundled", rating: "adult", enabled: false, valid: true };
const raw = { id: "adult:position.sample", name: "Sample position", category: "position", aliases: ["Direct alias"],
  tags: ["direct_tag"], extends: ["core:position.sample"], components: {
    participants: { slots: { actor: { count: 1, kind: "being" } } },
    requirements: { participants: { actor: { all_of: ["core:limb.hand"] } } },
    spatial: { participants: { actor: { posture: "core:posture.standing" } } },
    claims: { actor: [{ resource: "core:limb.hand", count: 1, mode: "exclusive", purpose: "hold" }] } } };
const resolved = { ...raw, rating: "adult", description: "Inherited description", aliases: ["Direct alias", "Parent alias"],
  tags: ["direct_tag", "parent_tag"], components: { ...raw.components, body: { provides: ["core:limb.hand"] } } };
const references = [{ id: "core:position.sample", name: "Parent position", kind: "extends", declared: true, exists: true, pack: "core", origin: "core" },
  { id: "core:limb.hand", name: "Hand", kind: "capability", declared: true, exists: true, pack: "core", origin: "core" }];
const detail = { pack, declared: raw, resolved, references, problems: [] };
const renderDetail = (value = detail) => renderToStaticMarkup(createElement(EntryDetails, { detail: value, onNavigate: noop, onBack: noop }));
const renderExplorer = (patch = {}, mode = "browse") => renderToStaticMarkup(createElement(ExplorerView, { visible: true, packs: [pack], mode, state: {
  pack, catalogue: { entries: [{ ...resolved, rating: "adult" }], total: 17, matched: 1,
    categories: [{ id: "position", name: "Positions", count: 9 }], ratings: ["general", "mature", "adult"],
    sorts: { name: "Name", id: "ID" }, problems: [] },
  loading: false, error: "", filters: { q: "", category: "", rating: "", sort: "name" }, filter: noop, selectPack: noop,
  entry: null, detail: null, detailLoading: false, detailError: "", navigate: noop, clearEntry: noop,
  sample: { request: "", characters: "", nsfw: false }, editSample: noop, result: null, inspecting: false, inspectionError: "", inspect: noop, reload: noop, ...patch,
} }));

test("explorer groups actual categories with counts and provides search, rating and sorting controls", () => {
  const markup = renderExplorer();
  for (const expected of ["Positions", "1 of 17 entries", "Search vocabulary entries", "Filter entry category", "Filter entry rating", "Sort vocabulary entries", "Sample position"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.match(markup, /Adult · bundled · disabled/);
  assert.match(markup, /visible here but unavailable to Dataset retrieval/);
  assert.doesNotMatch(markup, /Update pack|Remove pack|Save entry/);
});

test("entry details expose ownership, ratings and declarations separately from inherited information", () => {
  const markup = renderDetail();
  for (const expected of ["adult:position.sample", "Owned by Adult", "Pack disabled; browsing only", "Direct alias", "Parent alias", "Inherited description", "Declared", "Inherited", "Resolved including inheritance", "Declared by this entry", "Parent position"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.match(markup, /data-rating="adult"/);
  assert.match(markup, /Not declared here/);
  assert.match(markup, /No schema references declared|Declared reference/);
});

test("technical sections display only declared or registry-resolved component data", () => {
  const markup = renderDetail();
  for (const expected of ["Participant slots", "Requirements and constraints", "Spatial relationships", "Resource usage", "Body resources and capabilities", "All of", "exclusive", "hold", "standing"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.doesNotMatch(markup, /&quot;components&quot;|&quot;participants&quot;/);
});

test("missing references are not presented as valid navigation or fabricated resolved fields", () => {
  const markup = renderDetail({ ...detail, resolved: null, problems: ["core:position.sample does not exist"],
    references: [{ ...references[0], exists: false }] });
  assert.match(markup, /Resolution unavailable/);
  assert.match(markup, /missing or unavailable/);
  assert.match(markup, /Only validated declarations are shown/);
  assert.doesNotMatch(markup, /Resolved including inheritance|Inherited description|Parent alias/);
});

test("empty, loading and failed catalogue/detail states provide useful feedback", () => {
  assert.match(renderExplorer({ catalogue: null, loading: true }), /Loading entries/);
  assert.match(renderExplorer({ catalogue: null, error: "Pack missing" }), /Pack missing/);
  assert.match(renderExplorer({ catalogue: { entries: [], total: 17, matched: 0, categories: [], ratings: [], sorts: {}, problems: [] } }), /No entries match these filters/);
  assert.match(renderExplorer({ detailLoading: true }), /Loading entry details/);
  assert.match(renderExplorer({ detailError: "Reference removed" }), /Retry entry/);
});

test("retrieval inspection labels unknown status, matching reasons, needs and explicit exclusions", () => {
  const result = { nsfw: true, cast: [], warnings: [], entries: [{ id: raw.id, name: raw.name, pack: "adult", rating: "adult", category: "position",
    status: "unknown", score: 2.5, description: "Entry description", why: ["alias matches the request"], needs: ["a wide surface"],
    warnings: ["Anatomy undeclared"], binding: { actor: ["Character 1"] }, checked_with: [], note: "" }],
    excluded: [{ id: "adult:position.other", pack: "adult", reason: "conflict: cast cannot bind" }],
    suppressed: [{ id: "adult:position.similar", pack: "adult", because: "near duplicate" }] };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  for (const expected of ["Unknown", "alias matches the request", "a wide surface", "Anatomy undeclared", "conflict: cast cannot bind", "near duplicate", "Adult ratings allowed"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.match(markup, /not content approval/);
  assert.doesNotMatch(markup, /Physically proven|LLM response/);
});

test("sample form makes non-generation and the rating-filter limitation explicit", () => {
  const markup = renderExplorer({}, "test");
  assert.match(markup, /No LLM, scene generation or saved changes/);
  assert.match(markup, /Normal Dataset eligibility checks still apply/);
  assert.match(markup, /Allow Adult rating in inspection/);
  assert.match(markup, /Optional character descriptions/);
});

test("entry and resolver text are escaped rather than rendered as markup", () => {
  const markup = renderDetail({ ...detail, declared: { ...raw, name: "<script>alert(1)</script>" } });
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
});

test("retrieval inspection shows detected intent, named entries versus ideas, closed categories and per-scene suggestions", () => {
  const idea = (id, name, category, extra = {}) => ({ id, name, pack: "adult", rating: "adult", category, status: "eligible", score: 2,
    description: "", why: ["content: the brief asks for adult content"], needs: [], warnings: [], binding: null, checked_with: [],
    note: "", source: "inspiration", scopes: ["content"], attach_to: [], ...extra });
  const result = { nsfw: true, cast: [], warnings: [], entries: [], excluded: [], suppressed: [], seed: 7,
    inspiration: [idea("adult:position.cowgirl", "Cowgirl", "position"), idea("adult:action.restrained", "Wrists restrained", "action"),
      idea("adult:item.handcuffs", "Handcuffs", "item", { attach_to: ["adult:action.restrained"] })],
    intent: { content: "adult", themes: [{ pack: "adult", name: "Adult", why: "the brief says \"adult\" (request)" }],
      fixed: {}, ruled_out: { item: ["accessory"] }, per_scene: 3, categories: [
        { id: "position", name: "Positions", state: "open", reached: [{ scope: "category", why: "the brief says \"position\" (randomized)" }],
          ideas: ["adult:position.cowgirl"], empty: null, reason: "" },
        { id: "space", name: "Spaces", state: "closed", reached: [{ scope: "category", why: "the brief says \"location\" (randomized)" }],
          ideas: [], empty: "the request fixes the space: Bed", reason: "the request fixes the space: Bed" },
        { id: "posture", name: "Postures", state: "not reached", reached: [], ideas: [], empty: "not reached by the brief",
          reason: "nothing in the brief names, implies or randomizes it" }] },
    scenes: [{ scene: 1, entries: [], ideas: ["adult:position.cowgirl", "adult:action.restrained", "adult:item.handcuffs"] },
      { scene: 2, entries: [], ideas: [] }] };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  for (const expected of ["Detected intent", "How the request was read", "What the Director gets", "Content level</dt><dd>Adult</dd>", "Adult (the brief says &quot;adult&quot; (request))",
    "Category wording: the brief says &quot;position&quot; (randomized)", "Open", "Closed", "Not reached",
    "the request fixes the space: Bed", "nothing in the brief names, implies or randomizes it", "Ruled out by the request</dt><dd>item (accessory)</dd>",
    "named by the request", "Ideas (optional inspiration)", "Idea", "Offered only with</strong> Wrists restrained",
    "Per-scene suggestions (seed 7)", "Scene 1: Cowgirl; Wrists restrained; Handcuffs", "Compatible"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.doesNotMatch(markup, /Scene 2/, "a scene with nothing offered is not listed");
});

test("retrieval inspection says which packs the content level offered and which need their theme", () => {
  const intent = (activation) => ({ nsfw: true, cast: [], warnings: [], entries: [], excluded: [], suppressed: [], inspiration: [],
    intent: { content: "adult", themes: [], fixed: {}, ruled_out: {}, per_scene: 3, categories: [], activation } });
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result: intent([
    { pack: "adult", name: "Adult", state: "content", why: "the brief asks for adult content" },
    { pack: "niche", name: "Niche", state: "inactive", why: "needs its theme: the content level alone does not offer this pack" }]),
  onNavigate: noop, packs: [pack] }));
  assert.ok(markup.includes("Packs offered by content level</dt><dd>Adult</dd>"));
  assert.ok(markup.includes("Packs not offered (need their theme)</dt><dd>Niche</dd>"));
  const without = renderToStaticMarkup(createElement(RetrievalResults, { result: intent(undefined), onNavigate: noop, packs: [pack] }));
  assert.doesNotMatch(without, /Packs offered by content level|Packs not offered/, "results from before activation still render");
});

test("retrieval inspection explains related and unused partial matches", () => {
  const result = { nsfw: true, cast: [], warnings: [], entries: [], excluded: [], suppressed: [], inspiration: [],
    intent: { content: null, themes: [], fixed: {}, ruled_out: {}, per_scene: 3, categories: [],
      related: [{ id: "x:item.guitar", why: "it provides what Strum a song, which the request names, needs" }],
      rejected: [{ id: "x:space.play_room", why: "only one word of a longer name or alias" }], uncertain: { place: ["at play"] } } };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  assert.ok(markup.includes("Related to the request (optional)</dt><dd>x:item.guitar (it provides what Strum a song, which the request names, needs)"));
  assert.ok(markup.includes("Partial matches not used</dt><dd>x:space.play_room (only one word of a longer name or alias)"));
  assert.ok(markup.includes("Possible place (uncertain text guess)</dt><dd>at play</dd>"));
  assert.doesNotMatch(markup, /Fixed by the request/, "a guess is never shown as fixed");
});

test("older results without intent or ideas still render", () => {
  const result = { nsfw: false, cast: [], warnings: ["no relevant vocabulary for this request"], entries: [], excluded: [], suppressed: [] };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  assert.match(markup, /No entries retrieved for this sample/);
  assert.doesNotMatch(markup, /Detected intent|Per-scene suggestions/);
  assert.match(markup, /Try: Name a position, action, place or item/);
});

test("the inspection payload carries the optional brief details the engine reads", async () => {
  const { inspectionPayload, PREVIEW_SCENES } = await import("./useVocabularyExplorer.js");
  assert.deepEqual(inspectionPayload({ request: "Two adults", nsfw: true, characters: " adult man \n\n adult man ", randomized: "positions",
    avoid: "no toys\n \nno bondage", seed: "42" }), { request: "Two adults", nsfw: true, characters: ["adult man", "adult man"],
    randomized: "positions", avoid: ["no toys", "no bondage"], seed: 42, scenes: PREVIEW_SCENES });
  assert.equal(inspectionPayload({ request: "x", nsfw: false, characters: "", seed: "" }).seed, 0);
  assert.equal(inspectionPayload({ request: "x", nsfw: false, characters: "", seed: "99999999999" }).seed, 2147483647);
  assert.deepEqual(inspectionPayload({ request: "x", nsfw: false, characters: "" }).avoid, []);
});

test("sample form offers what may vary, avoid and seed as optional brief details", () => {
  const markup = renderExplorer({}, "test");
  for (const expected of ["Optional brief details", "Inspection randomized", "Inspection avoid", "Inspection seed"]) {
    assert.ok(markup.includes(expected), expected);
  }
});

test("browsing and testing are separate views; the tester has no built-in example requests", () => {
  const browse = renderExplorer();
  assert.doesNotMatch(browse, /Vocabulary sample request|Inspect retrieval/);
  const tester = renderExplorer({}, "test");
  for (const expected of ["Test a request", "adult man"]) {
    assert.ok(tester.includes(expected), expected);
  }
  assert.doesNotMatch(tester, /Example requests|Two men, positions vary|Couple, no toys|A fantasy scene/);
  assert.doesNotMatch(tester, /Filter entry category/);
});

test("a cast with no matching body gets an actionable hint", () => {
  const result = { nsfw: true, cast: [], entries: [], excluded: [], suppressed: [],
    warnings: ["Character 1: no vocabulary body matches, so compatibility involving them is unknown"] };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  assert.match(markup, /Try: Describe characters with words a body entry knows, such as man, woman or person/);
});

test("inspection sends the same pack scope a Dataset run uses: chosen ids or a run's recorded selection", async () => {
  const { inspectionPayload, scopeProblem } = await import("./useVocabularyExplorer.js");
  const sample = { request: "A boat", nsfw: false, characters: "" };
  assert.equal("packs" in inspectionPayload(sample), false);
  assert.equal("recorded" in inspectionPayload(sample), false);
  assert.deepEqual(inspectionPayload(sample, { mode: "choose", selected: ["boats"] }).packs, ["boats"]);
  const recorded = { version: 1, enabled: true, selected: [], packs: [] };
  const fromRun = inspectionPayload(sample, { mode: "run", run: { packs: recorded } });
  assert.equal(fromRun.recorded, recorded);
  assert.equal("packs" in fromRun, false);
  assert.match(scopeProblem({ mode: "run", run: null }), /Load a stored Dataset run/);
  assert.match(scopeProblem({ mode: "run", run: { packs: { recorded: false } } }), /not recorded/);
  assert.match(scopeProblem({ mode: "run", run: { packs: { ...recorded, enabled: false } } }), /no vocabulary/);
  assert.equal(scopeProblem({ mode: "run", run: { packs: recorded } }), "");
  assert.equal(scopeProblem({ mode: "choose", selected: [] }), "");
});

test("inspecting a stored run shows that run's recorded packs, not the global selection", () => {
  const recorded = { version: 1, enabled: true, selected: [], packs: [
    { id: "core", role: "core", origin: "core", version: "2.0.0", fingerprint: `sha256:${"d".repeat(64)}` }] };
  const markup = renderExplorer({ scope: { mode: "run", selected: null, runId: "run-1", run: { run_id: "run-1", packs: recorded,
    status: { exact: true, drift: [], disabled_globally: [] } }, runError: "", runLoading: false }, editScope: noop, loadRun: noop }, "test");
  assert.match(markup, /Packs: a stored Dataset run&#x27;s/);
  assert.match(markup, /Run run-1: Recorded packs unchanged/);
  assert.match(markup, /v2\.0\.0/);
  assert.doesNotMatch(markup, /aria-label="Use Adult"/);
  const chosen = renderExplorer({ scope: { mode: "choose", selected: ["adult"], runId: "", run: null }, editScope: noop, loadRun: noop }, "test");
  assert.match(chosen, /aria-label="Use Adult"[^>]*checked=""/);
  assert.match(chosen, /Off in Pack Manager; used for this run only/);
  const legacy = renderExplorer({ scope: { mode: "run", selected: null, runId: "old", run: { run_id: "old", packs: { recorded: false }, status: null } },
    editScope: noop, loadRun: noop }, "test");
  assert.match(legacy, /Not recorded/);
  assert.match(legacy.match(/<button[^>]*>[^<]*(<svg[^]*?<\/svg>)?Inspect retrieval<\/button>/)[0], /disabled=""/);
});

test("results name the packs that answered", () => {
  const markup = renderExplorer({ result: { nsfw: false, entries: [], ideas: [], scenes: [], warnings: [], cast: [], excluded: [], suppressed: [],
    intent: null, seed: 0, selection: { version: 1, enabled: true, selected: ["boats"], packs: [
      { id: "boats", role: "selected", origin: "installed", version: "1.0.0", fingerprint: "" },
      { id: "harbor", role: "dependency", origin: "bundled", version: "1.0.0", fingerprint: "" }] } } }, "test");
  assert.match(markup, /Packs used: boats v1\.0\.0, harbor v1\.0\.0 \(dependency\)/);
});

test("the preview counts eligible ideas, distinct offers and suggestions, and long pools page without shrinking", () => {
  const idea = (n) => ({ id: `adult:position.p${n}`, name: `Pose ${n}`, pack: "adult", rating: "adult", category: "position", status: "eligible",
    score: 2, description: "", why: [], needs: [], warnings: [], binding: null, checked_with: [], note: "", source: "inspiration",
    scopes: ["category"], attach_to: [] });
  const inspiration = Array.from({ length: 30 }, (_, n) => idea(n));
  const scenes = Array.from({ length: 6 }, (_, n) => ({ scene: n + 1, entries: [], ideas: [`adult:position.p${n % 4}`] }));
  const result = { nsfw: true, cast: [], warnings: [], entries: [], excluded: [], suppressed: [], seed: 1, inspiration, scenes,
    coverage: { images: 6, named_per_image: 0, eligible: { position: 30 }, offered: { position: 4 }, distinct: 4, suggestions: 6,
      offered_ids: ["adult:position.p0", "adult:position.p1", "adult:position.p2", "adult:position.p3"] } };
  const markup = renderToStaticMarkup(createElement(RetrievalResults, { result, onNavigate: noop, packs: [pack] }));
  for (const expected of ["eligible ideas in the pool", "different ideas offered in 6 images", "suggestions across 6 images",
    "30 eligible · 4 offered in the preview", "18 more eligible entries not shown here; still in the pool.", "Show 12 more", "Show all 30", "Offered in preview"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.equal((markup.match(/vocabulary-match-heading/g) || []).length, 12, "12 shown at first; the other 18 stay in the pool");
  const older = renderToStaticMarkup(createElement(RetrievalResults, { result: { ...result, coverage: undefined }, onNavigate: noop, packs: [pack] }));
  assert.ok(older.includes("different ideas offered in 6 images"), "older results count from their scenes");
  assert.ok(older.includes("30 eligible · 4 offered in the preview"));
});

test("the preview size goes into the payload and the form offers it", async () => {
  const { inspectionPayload, PREVIEW_SCENES } = await import("./useVocabularyExplorer.js");
  assert.equal(inspectionPayload({ request: "x", nsfw: false, characters: "", previewImages: "20" }).scenes, 20);
  assert.equal(inspectionPayload({ request: "x", nsfw: false, characters: "", previewImages: "999" }).scenes, PREVIEW_SCENES);
  assert.match(renderExplorer({}, "test"), /Inspection preview images/);
});
