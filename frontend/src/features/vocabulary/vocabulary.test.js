import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";

const source = new URL("./VocabularyTab.jsx", import.meta.url);
const { code } = await transformWithEsbuild(await readFile(source, "utf8"), source.pathname,
  { loader: "jsx", jsx: "automatic", sourcemap: false });
const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
  `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, source).href : import.meta.resolve(specifier))}`);
const { PackManagerView } = await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`);

function pack(id, overrides = {}) {
  return { id, name: `${id} pack`, description: `Knowledge from ${id}`, version: "1.2.3", entries: 12,
    rating: "general", origin: "installed", bundled: false, mandatory: false, enabled: true,
    valid: true, problems: [], requires: { core: ">=1.0.0" }, ...overrides };
}
function render(overrides = {}) {
  const state = { snapshot: { packs: [], problems: [], max_archive_bytes: 20 * 1024 * 1024 },
    loading: false, saving: false, error: "", notice: "", removing: null, target: null, file: null,
    reload() {}, upload() {}, setFile() {}, chooseUpdate() {}, setRemoving() {}, toggle() {}, remove() {}, ...overrides };
  return renderToStaticMarkup(createElement(PackManagerView, { visible: true, state }));
}
const snapshot = (packs, problems = []) => ({ packs, problems, max_archive_bytes: 20 * 1024 * 1024 });

test("pack cards display full metadata and General, Mature and Adult ratings without hiding adult packs", () => {
  const markup = render({ snapshot: snapshot([pack("general"), pack("mature", { rating: "mature" }), pack("adult", { rating: "adult" })]) });
  for (const text of ["General", "Mature", "Adult", "User-installed", "1.2.3", "12", "Knowledge from adult", "core", "&gt;=1.0.0", "3 enabled / 3 available"]) {
    assert.ok(markup.includes(text), text);
  }
  assert.match(markup, /data-rating="adult"/);
  assert.match(markup, /eligible NSFW requests/);
});

test("Core is locked on and bundled optional packs have toggles but never destructive actions", () => {
  const markup = render({ snapshot: snapshot([
    pack("core", { mandatory: true, bundled: true, origin: "core" }),
    pack("fantasy", { bundled: true, origin: "bundled", enabled: false }),
    pack("adult", { bundled: true, origin: "bundled", rating: "adult" }),
  ]) });
  assert.match(markup, /aria-label="Enable core pack"[^>]*disabled=""[^>]*checked=""/);
  assert.match(markup, /aria-label="Enable fantasy pack"/);
  assert.match(markup, /Always enabled/);
  assert.match(markup, /Mandatory Core/);
  assert.doesNotMatch(markup, /Update ZIP|>Remove<|Confirm removal/);
});

test("user packs can be updated or removed but removal requires a separate confirmation", () => {
  const custom = pack("custom");
  const normal = render({ snapshot: snapshot([custom]) });
  assert.match(normal, /Update ZIP/);
  assert.match(normal, /aria-label="Remove custom pack"/);
  assert.doesNotMatch(normal, /Remove pack<\/button>/);
  const confirmation = render({ snapshot: snapshot([custom]), removing: custom });
  assert.match(confirmation, /Confirm removal of custom pack/);
  assert.match(confirmation, /Existing Dataset outputs are not changed/);
  assert.match(confirmation, />Cancel<\/button>/);
  assert.match(confirmation, />Remove pack<\/button>/);
});

test("broken and incompatible packs remain visible with actionable diagnostics and unknown metadata", () => {
  const markup = render({ snapshot: snapshot([pack("broken", { valid: false, version: null, entries: null, rating: null,
    problems: ["broken: unsupported schema", "broken requires missing >=1.0.0"] })], ["The registry cannot load"]) });
  assert.match(markup, /broken pack/);
  assert.match(markup, /unsupported schema/);
  assert.match(markup, /requires missing/);
  assert.match(markup, /Rating unavailable/);
  assert.match(markup, /Unavailable/);
  assert.match(markup, /aria-label="Enable broken pack"[^>]*disabled/);
  assert.match(markup, /Vocabulary cannot load/);
  assert.match(markup, /Update ZIP/);
});

test("loading, empty, request errors and successful operations have distinct feedback", () => {
  assert.match(render({ snapshot: null, loading: true }), /role="status">Loading vocabulary packs/);
  assert.match(render(), /No packs found/);
  assert.match(render({ error: "ZIP is unsafe" }), /role="alert"><span>ZIP is unsafe/);
  assert.match(render({ notice: "Pack installed" }), /role="status">.*Pack installed/);
  assert.match(render(), /Restore the bundled vocabulary files/);
});

test("update mode identifies the expected pack and keeps import disabled without a ZIP", () => {
  const markup = render({ target: pack("custom") });
  assert.match(markup, /Update custom pack/);
  assert.match(markup, /Choose a ZIP with pack id/);
  assert.match(markup, /Cancel update/);
  assert.match(markup, /disabled=""><[^>]*svg.*Update pack/s);
  assert.match(markup, /accept=".zip,application\/zip"/);
});

test("busy operations disable toggles, updates, removal and uploads", () => {
  const markup = render({ snapshot: snapshot([pack("custom")]), saving: true, file: { name: "custom.zip" } });
  assert.match(markup, /aria-busy="true"/);
  assert.match(markup, /aria-label="Enable custom pack"[^>]*disabled/);
  assert.match(markup, /disabled="" aria-label="Remove custom pack"/);
  assert.match(markup, /Applying changes/);
});

test("pack descriptions and validation messages are escaped; AI creation workflow remains available", () => {
  const markup = render({ snapshot: snapshot([pack("custom", { description: "<script>alert(1)</script>",
    problems: ["<img src=x onerror=alert(1)>"] })]) });
  assert.doesNotMatch(markup, /<script>|<img/);
  assert.match(markup, /&lt;script&gt;/);
  assert.match(markup, /vocabulary\/SKILL.md/);
  assert.doesNotMatch(markup, /Vocabulary Explorer|Visual Pack Creator/);
});
