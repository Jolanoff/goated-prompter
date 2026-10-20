import test from "node:test";
import assert from "node:assert/strict";
import { cleanSelection, filterPacks, packsByCategory, recordedNames, selectedNames, togglePack } from "./catalog.js";

const catalog = {
  categories: [{ id: "Spaces", name: "Spaces" }, { id: "Lighting", name: "Lighting" }, { id: "Objects", name: "Objects" }],
  packs: [
    { id: "Spaces/Fantasy", name: "Fantasy", category: "Spaces", entries: ["enchanted forest", "floating castle"] },
    { id: "Spaces/Horror", name: "Horror", category: "Spaces", entries: ["foggy graveyard"] },
    { id: "Lighting/Cinematic", name: "Cinematic", category: "Lighting", description: "film-set light", entries: ["rim lighting"] },
  ],
  problems: [],
};

test("packs are grouped under every registered category, empty ones included", () => {
  assert.deepEqual(packsByCategory(catalog).map(({ category, packs }) => [category.id, packs.length]),
    [["Spaces", 2], ["Lighting", 1], ["Objects", 0]]);
});

test("search matches pack names, categories, descriptions and entry text; the category filter narrows it", () => {
  const ids = (packs) => packs.map((pack) => pack.id);
  assert.deepEqual(ids(filterPacks(catalog)), ["Spaces/Fantasy", "Spaces/Horror", "Lighting/Cinematic"]);
  assert.deepEqual(ids(filterPacks(catalog, "cinem")), ["Lighting/Cinematic"]);
  assert.deepEqual(ids(filterPacks(catalog, "spaces")), ["Spaces/Fantasy", "Spaces/Horror"]);
  assert.deepEqual(ids(filterPacks(catalog, "CASTLE")), ["Spaces/Fantasy"]);
  assert.deepEqual(ids(filterPacks(catalog, "film-set")), ["Lighting/Cinematic"]);
  assert.deepEqual(ids(filterPacks(catalog, "", "Lighting")), ["Lighting/Cinematic"]);
  assert.deepEqual(ids(filterPacks(catalog, "forest", "Lighting")), []);
});

test("toggling never mutates, and the sent selection drops packs that are gone", () => {
  const start = [];
  const on = togglePack(togglePack(start, "Spaces/Fantasy"), "Lighting/Cinematic");
  assert.deepEqual(start, []);
  assert.deepEqual(on, ["Spaces/Fantasy", "Lighting/Cinematic"]);
  assert.deepEqual(togglePack(on, "Spaces/Fantasy"), ["Lighting/Cinematic"]);
  assert.deepEqual(cleanSelection(catalog, ["gone/pack", "Spaces/Horror", "Spaces/Horror"]), ["Spaces/Horror"]);
  assert.deepEqual(cleanSelection(null, ["Spaces/Horror"]), []);
});

test("selected and recorded packs read as names", () => {
  assert.deepEqual(selectedNames(catalog, ["Lighting/Cinematic", "Spaces/Fantasy"]), ["Cinematic", "Fantasy"]);
  assert.deepEqual(recordedNames({ packs: [{ id: "Spaces/Fantasy", name: "Fantasy", category: "Spaces", entries: 2 }] }),
    ["Fantasy (Spaces)"]);
  assert.deepEqual(recordedNames(null), []);
});
