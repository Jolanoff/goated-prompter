import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { sortPacks } from "./vocabularyLibrary.js";

const packs = [
  { id: "Spaces/Z", name: "Zulu", category: "Spaces", entries: ["one"] },
  { id: "Lighting/A", name: "Gamma", category: "Lighting", entries: ["one", "two", "three"] },
  { id: "Spaces/B", name: "Beta", category: "Spaces", entries: ["one", "two"] },
  { id: "Spaces/A", name: "Alpha", category: "Spaces", entries: ["one"] },
];
const ids = (rows) => rows.map((row) => row.id);

async function renderLibrary(packs) {
  const sourceUrl = new URL("./VocabularyLibrary.jsx", import.meta.url);
  const source = (await readFile(sourceUrl, "utf8")).replace('import "./vocabulary-library.css";', "");
  const { code } = await transformWithEsbuild(source, sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  const Library = (await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`)).default;
  return renderToStaticMarkup(createElement(Library, { open: true, catalog: { packs, categories: [] }, selected: [],
    onApply() {}, onCancel() {} }));
}

test("the library sorts by name, category or entry count without changing the catalog", () => {
  assert.deepEqual(ids(sortPacks(packs, "name")), ["Spaces/A", "Spaces/B", "Lighting/A", "Spaces/Z"]);
  assert.deepEqual(ids(sortPacks(packs, "category")), ["Lighting/A", "Spaces/A", "Spaces/B", "Spaces/Z"]);
  assert.deepEqual(ids(sortPacks(packs, "entries")), ["Lighting/A", "Spaces/B", "Spaces/A", "Spaces/Z"]);
  assert.deepEqual(ids(packs), ["Spaces/Z", "Lighting/A", "Spaces/B", "Spaces/A"]);
  assert.deepEqual(sortPacks([], "entries"), []);
});

test("the library shows bracket-linked packs in both directions once, not same-category suggestions", async () => {
  const html = await renderLibrary([
    { id: "Spaces/Anchor", name: "Anchor", category: "Spaces", entries: ["a room with [Props]"],
      links: [{ slot: "Props", packs: ["Objects/Props"] }] },
    { id: "Objects/Props", name: "Props", category: "Objects & Props", entries: ["a prop in [Anchor]"],
      links: [{ slot: "Anchor", packs: ["Spaces/Anchor"] }] },
    { id: "Lighting/Referrer", name: "Referrer", category: "Lighting", entries: ["light in [Anchor]"],
      links: [{ slot: "Anchor", packs: ["Spaces/Anchor"] }] },
    { id: "Spaces/Unlinked", name: "Unlinked", category: "Spaces", entries: ["a plain room"] },
  ]);
  assert.match(html, /Linked Packs/);
  assert.equal((html.match(/aria-label="Preview linked Props /g) || []).length, 1);
  assert.match(html, /aria-label="Preview linked Referrer \(Lighting\)"/);
  assert.doesNotMatch(html, /Preview linked Unlinked|Related Packs|Works with|View all related packs|More packs in/);
});

test("an unlinked pack has no category-based recommendations", async () => {
  const html = await renderLibrary(packs);
  assert.match(html, /No linked packs\./);
  assert.doesNotMatch(html, /aria-label="Preview (?:linked|related) /);
});

test("linked suggestions are not capped at four packs", async () => {
  const targets = Array.from({ length: 6 }, (_, index) => ({
    id: `Objects/Prop-${index}`, name: `Prop ${index}`, category: "Objects & Props", entries: ["a prop"],
  }));
  const html = await renderLibrary([
    { id: "Spaces/Anchor", name: "Anchor", category: "Spaces", entries: ["a room with [Props]"],
      links: [{ slot: "Props", packs: targets.map((pack) => pack.id) }] }, ...targets,
  ]);
  assert.equal((html.match(/aria-label="Preview linked /g) || []).length, 6);
});
