import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";

const source = new URL("./VocabularyExplorer.jsx", import.meta.url);
const { code } = await transformWithEsbuild(await readFile(source, "utf8"), source.pathname,
  { loader: "jsx", jsx: "automatic", sourcemap: false });
const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
  `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, source).href : import.meta.resolve(specifier))}`);
const { EntryDetails, ExplorerView, RetrievalResults } = await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`);
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
const renderExplorer = (patch = {}) => renderToStaticMarkup(createElement(ExplorerView, { visible: true, packs: [pack], state: {
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
  const markup = renderExplorer();
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
