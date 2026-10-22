import test from "node:test";
import assert from "node:assert/strict";
import { cleanSelection, filterPacks, linkedPacks, missingLinks, packsByCategory, recordedNames, selectedNames,
  togglePack } from "./catalog.js";

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

const linked = {
  categories: [{ id: "Actions & Poses" }, { id: "Objects & Props" }],
  packs: [
    { id: "Actions & Poses/Dinner", name: "Dinner", category: "Actions & Poses", entries: ["holding [Kitchen & Dining]"],
      links: [{ slot: "Kitchen & Dining", packs: ["Objects/Kitchen"] }, { slot: "Furniture", packs: ["Objects/Furniture"] },
        { slot: "Nowhere", packs: [] }] },
    { id: "Objects/Kitchen", name: "Kitchen & Dining", category: "Objects & Props", entries: ["teapot"] },
    { id: "Objects/Furniture", name: "Furniture", category: "Objects & Props", entries: ["armchair"] },
    { id: "Objects/Plain", name: "Plain", category: "Objects & Props", entries: ["mug"] },
  ],
};

test("linked packs: the ones a pack's slots name and the ones that name it", () => {
  const names = ({ uses, usedBy }) => [uses.map((pack) => pack.name), usedBy.map((pack) => pack.name)];
  assert.deepEqual(names(linkedPacks(linked, "Actions & Poses/Dinner")), [["Kitchen & Dining", "Furniture"], []]);
  assert.deepEqual(names(linkedPacks(linked, "Objects/Kitchen")), [[], ["Dinner"]]);
  assert.deepEqual(names(linkedPacks(linked, "Objects/Plain")), [[], []]);
  assert.deepEqual(names(linkedPacks(null, "x")), [[], []]);
});

test("a chosen pack's slots that no chosen pack fills are reported with their options", () => {
  const rows = (ids) => missingLinks(linked, ids).map(({ pack, slot, options }) => [pack.name, slot, options.map((item) => item.name)]);
  assert.deepEqual(rows(["Actions & Poses/Dinner"]),
    [["Dinner", "Kitchen & Dining", ["Kitchen & Dining"]], ["Dinner", "Furniture", ["Furniture"]], ["Dinner", "Nowhere", []]]);
  assert.deepEqual(rows(["Actions & Poses/Dinner", "Objects/Kitchen"]),
    [["Dinner", "Furniture", ["Furniture"]], ["Dinner", "Nowhere", []]]);
  assert.deepEqual(rows(["Objects/Plain"]), []);
});
