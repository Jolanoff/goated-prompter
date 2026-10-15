import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileView } from "./testSupport.js";
import { defaultPackSelection, packChoices, recordedPackSummary, selectionProblem, togglePack } from "./packSelection.js";
import { PACKS_KEY, readStoredPacks, writeStoredPacks } from "../dataset/useDatasetPacks.js";

const { PackSelector, RecordedPacks } = await import(await compileView(new URL("./PackSelector.jsx", import.meta.url)));

function pack(id, overrides = {}) {
  return { id, name: `${id} pack`, version: "1.0.0", origin: "installed", mandatory: false, enabled: true,
    valid: true, problems: [], requires: { core: ">=1.0.0" }, ...overrides };
}
const core = pack("core", { origin: "core", mandatory: true, requires: {} });
const library = [core, pack("harbor", { origin: "bundled" }), pack("boats", { requires: { core: ">=1.0.0", harbor: ">=1.0.0" } }),
  pack("adult", { enabled: false, origin: "bundled" }), pack("broken", { valid: false, problems: ["manifest.json: bad"] }),
  pack("orphan", { requires: { core: ">=1.0.0", gone: ">=1.0.0" }, problems: ["orphan requires gone, which is not available"] })];

test("defaults start from the globally enabled usable optional packs and never list core", () => {
  assert.deepEqual(defaultPackSelection(library), ["boats", "harbor"]);
});

test("core is required, selected packs are distinct from dependencies, and nothing else participates", () => {
  const rows = Object.fromEntries(packChoices(library, ["boats"]).map((row) => [row.id, row]));
  assert.equal(rows.core.role, "core");
  assert.equal(rows.boats.role, "selected");
  assert.equal(rows.harbor.role, "dependency");
  assert.equal(rows.adult.role, "off");
  assert.equal(rows.broken.status, "invalid");
  assert.equal(rows.orphan.status, "blocked");
  assert.deepEqual(rows.orphan.missing, ["gone"]);
  assert.equal(selectionProblem(Object.values(rows)), "");
});

test("multiple and globally disabled packs can be chosen for one run; broken choices are named", () => {
  const rows = packChoices(library, ["adult", "boats", "orphan", "removed"]);
  const byId = Object.fromEntries(rows.map((row) => [row.id, row]));
  assert.equal(byId.adult.role, "selected");
  assert.equal(byId.adult.enabledGlobally, false);
  assert.equal(byId.removed.status, "unavailable");
  assert.match(selectionProblem(rows), /orphan pack \(Dependency missing or invalid\), removed \(Not installed\)/);
  assert.deepEqual(togglePack(["boats"], "adult"), ["adult", "boats"]);
  assert.deepEqual(togglePack(["adult", "boats"], "adult"), ["boats"]);
});

test("the selector locks core, shows versions and states, and never offers unusable packs", () => {
  const markup = renderToStaticMarkup(createElement(PackSelector, { packs: library, selected: ["adult", "boats"], onChange: () => {} }));
  assert.match(markup, /aria-label="Use core pack"[^>]*disabled=""/);
  assert.match(markup, /v1\.0\.0/);
  assert.match(markup, /Required/);
  assert.match(markup, /Added as dependency/);
  assert.match(markup, /Off in Pack Manager; used for this run only/);
  assert.match(markup, /aria-label="Use broken pack"[^>]*disabled=""/);
  assert.match(markup, /aria-label="Use orphan pack"[^>]*disabled=""/);
  assert.match(markup, /Dependency missing or invalid: gone/);
  assert.doesNotMatch(markup, /cannot be used/);
});

test("a stored run shows what it recorded, its drift, and NOT RECORDED for schema 1", () => {
  const recorded = { version: 1, enabled: true, selected: ["boats"], packs: [
    { id: "boats", role: "selected", origin: "installed", version: "1.0.0", fingerprint: `sha256:${"a".repeat(64)}` },
    { id: "core", role: "core", origin: "core", version: "1.0.0", fingerprint: `sha256:${"b".repeat(64)}` },
    { id: "harbor", role: "dependency", origin: "bundled", version: "1.0.0", fingerprint: `sha256:${"c".repeat(64)}` }] };
  const drift = { exact: false, drift: [{ id: "boats", problem: "changed", detail: "its content changed since it was recorded (still version 1.0.0)" }],
    disabled_globally: ["harbor"] };
  const summary = recordedPackSummary(recorded, drift);
  assert.equal(summary.state, "drift");
  assert.equal(summary.rows.find((row) => row.id === "harbor").disabledGlobally, true);
  const markup = renderToStaticMarkup(createElement(RecordedPacks, { recorded, status: drift, names: { boats: "Boats" } }));
  assert.match(markup, /Packs changed since this run/);
  assert.match(markup, /changed: its content changed/);
  assert.match(markup, /Off in Pack Manager now; this run keeps it/);
  assert.match(markup, /aaaaaaaaaaaa/);
  assert.equal(recordedPackSummary(recorded, { exact: true, drift: [], disabled_globally: [] }).state, "exact");
  const legacy = renderToStaticMarkup(createElement(RecordedPacks, { recorded: { recorded: false }, status: null }));
  assert.match(legacy, /Not recorded/);
  assert.match(legacy, /not guessed from current settings/);
  assert.equal(recordedPackSummary({ version: 1, enabled: false, selected: [], packs: [] }).state, "off");
});

test("the Dataset tab remembers its choice per browser and survives unavailable storage", () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(readStoredPacks(storage), null);
  writeStoredPacks(["fantasy", "adult", "fantasy"], storage);
  assert.equal(values.get(PACKS_KEY), JSON.stringify({ selected: ["adult", "fantasy"] }));
  assert.deepEqual(readStoredPacks(storage), ["adult", "fantasy"]);
  values.set(PACKS_KEY, "{not json");
  assert.equal(readStoredPacks(storage), null);
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(readStoredPacks(throwing), null);
  assert.doesNotThrow(() => writeStoredPacks(["x"], throwing));
});
