import test from "node:test";
import assert from "node:assert/strict";
import { relatedPacks, sortPacks } from "./vocabularyLibrary.js";

const packs = [
  { id: "Spaces/Z", name: "Zulu", category: "Spaces", entries: ["one"] },
  { id: "Lighting/A", name: "Gamma", category: "Lighting", entries: ["one", "two", "three"] },
  { id: "Spaces/B", name: "Beta", category: "Spaces", entries: ["one", "two"] },
  { id: "Spaces/A", name: "Alpha", category: "Spaces", entries: ["one"] },
];
const ids = (rows) => rows.map((row) => row.id);

test("the library sorts by name, category or entry count without changing the catalog", () => {
  assert.deepEqual(ids(sortPacks(packs, "name")), ["Spaces/A", "Spaces/B", "Lighting/A", "Spaces/Z"]);
  assert.deepEqual(ids(sortPacks(packs, "category")), ["Lighting/A", "Spaces/A", "Spaces/B", "Spaces/Z"]);
  assert.deepEqual(ids(sortPacks(packs, "entries")), ["Lighting/A", "Spaces/B", "Spaces/A", "Spaces/Z"]);
  assert.deepEqual(ids(packs), ["Spaces/Z", "Lighting/A", "Spaces/B", "Spaces/A"]);
  assert.deepEqual(sortPacks([], "entries"), []);
});

test("related packs are other packs in the preview's category, ordered and limited", () => {
  assert.deepEqual(ids(relatedPacks(packs, packs[0])), ["Spaces/A", "Spaces/B"]);
  assert.deepEqual(ids(relatedPacks(packs, packs[0], 1)), ["Spaces/A"]);
  assert.deepEqual(relatedPacks(packs, packs[1]), []);
  assert.deepEqual(relatedPacks(packs, undefined), []);
});
