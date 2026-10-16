import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileView } from "./testSupport.js";
import { moveEntry, newPackDocument, pathMatches, replaceKey, resolveSchema, schemaDefault, uniqueEntryId, variantIndex } from "./creatorModel.js";

const { default: SchemaForm } = await import(await compileView(new URL("./SchemaForm.jsx", import.meta.url)));
const { CreatorView } = await import(await compileView(new URL("./PackCreator.jsx", import.meta.url)));
const schemas = Object.fromEntries(await Promise.all(["manifest", "entry"].map(async (name) =>
  [name, JSON.parse(await readFile(new URL(`../../../../vocabulary/schemas/${name}.schema.json`, import.meta.url), "utf8"))])));
const noop = () => {};
const form = (schema, value, props = {}) => renderToStaticMarkup(createElement(SchemaForm, {
  schema, root: schemas.entry, value, onChange: noop, title: "Test field", ...props,
}));

test("new pack defaults follow real manifest/file schemas without inventing content", () => {
  const doc = newPackDocument();
  assert.equal(doc.manifest.spec, schemas.manifest.properties.spec.const);
  assert.ok(schemas.manifest.$defs.rating.enum.includes(doc.manifest.rating));
  assert.deepEqual(doc.manifest.files, Object.keys(doc.files));
  assert.deepEqual(doc.files["entries.json"], { spec: 1, entries: [] });
  assert.ok(Object.keys(doc.manifest).every((key) => key in schemas.manifest.properties));
});

test("unique IDs protect add/duplicate operations across files without changing the source", () => {
  const doc = newPackDocument();
  doc.files["entries.json"].entries.push({ id: "my_pack:entry" }, { id: "my_pack:entry_2" });
  doc.files["second.json"] = { spec: 1, entries: [{ id: "my_pack:entry_3" }] };
  assert.equal(uniqueEntryId(doc), "my_pack:entry_4");
  assert.equal(uniqueEntryId(doc, "my_pack:entry_copy"), "my_pack:entry_copy");
  assert.equal(doc.files["entries.json"].entries.length, 2);
});

test("moving an entry preserves its full schema data and leaves siblings unchanged", () => {
  const doc = newPackDocument();
  doc.files["entries.json"].entries = [{ id: "my_pack:a", components: { capability: {} } }, { id: "my_pack:b" }];
  doc.files["second.json"] = { spec: 1, entries: [] };
  const moved = moveEntry(doc, "entries.json", 0, "second.json");
  assert.deepEqual(moved.files["second.json"].entries[0], doc.files["entries.json"].entries[0]);
  assert.deepEqual(moved.files["entries.json"].entries, [{ id: "my_pack:b" }]);
  assert.equal(doc.files["entries.json"].entries.length, 2);
});

test("schema references, exact/range counts, anchors and facing choices retain their real shapes", () => {
  assert.equal(resolveSchema({ $ref: "#/$defs/entryId" }, schemas.entry).type, "string");
  assert.deepEqual(schemaDefault({ $ref: "#/$defs/participants" }, schemas.entry), { slots: {} });
  assert.equal(variantIndex(schemas.entry.$defs.count, 2, schemas.entry), 0);
  assert.equal(variantIndex(schemas.entry.$defs.count, { min: 1, max: 3 }, schemas.entry), 1);
  assert.equal(variantIndex(schemas.entry.$defs.facing, { away_from: "actor" }, schemas.entry), 1);
  assert.match(form(schemas.entry.$defs.count, { min: 1, max: 3 }), /Min/);
  assert.match(form(schemas.entry.$defs.anchor, { relation: "between", of: ["actor", "partner"] }), /Multiple values/);
});

test("every supported component renders recursive visual controls, not a raw JSON editor", () => {
  const samples = {
    capability: { implies: [] }, body: { resources: { hand_left: { type: "core:limb.hand" } }, provides: [] },
    participants: { slots: { actor: { count: { min: 1, max: 2 }, kind: "being", topology: "chain" } } },
    requirements: { participants: { actor: { all_of: ["core:limb.hand"], any_of: ["core:limb.hand", "core:limb.leg"], none_of: [] } }, access: [] },
    spatial: { participants: { actor: { orientation: "upright", facing: { toward: "partner" }, anchors: [{ relation: "on", of: "partner", at: "core:limb.hand", distance: "contact" }] } } },
    claims: { actor: [{ resource: "core:limb.hand", count: 1, mode: "exclusive", purpose: "hold", key: "held_{actor}" }] },
    object: { provides: [], complete_for: [], size: "small", hands: 1, capacity: { beings: 2 } }, environment: { provides: [], capacity: { beings: 4 } },
    visual: { dimension: "lighting", section: "lighting", media: ["anime"], people: { min: 1, max: 2 }, conflicts: [], shows: { whole: true, space: true } },
    visibility: { participants: { actor: { regions: ["core:limb.hand"], whole: true } }, contact: true, space: true },
    capacity: { beings: 2 },
  };
  assert.deepEqual(Object.keys(samples), Object.keys(schemas.entry.$defs.components.properties));
  for (const [component, value] of Object.entries(samples)) {
    const markup = form(schemas.entry.$defs.components.properties[component], value);
    assert.match(markup, /<fieldset/);
    assert.doesNotMatch(markup, /&quot;components&quot;/);
    assert.ok(markup.includes("Test field"), component);
  }
});

test("boolean declarations use typed controls rather than string inputs", () => {
  for (const schema of [schemas.entry.$defs.entry.properties.abstract, schemas.entry.$defs.visibility.properties.contact]) {
    assert.equal(schemaDefault(schema, schemas.entry), false);
    const markup = form(schema, true);
    assert.match(markup, /type="checkbox"/);
    assert.match(markup, /checked=""/);
    assert.doesNotMatch(form(schema, false), /checked=""/);
  }
});

test("reference controls search capabilities and inheritance equally across content ratings", () => {
  const references = [{ id: "adult:cap.sample", name: "Adult capability", pack: "adult", rating: "adult", capability: true },
    { id: "fantasy:body.sample", name: "Fantasy body", pack: "fantasy", rating: "general", capability: false }];
  const capability = form({ $ref: "#/$defs/entryId" }, "", { references, path: ["components", "capability", "implies", 0] });
  assert.match(capability, /adult:cap.sample/);
  assert.doesNotMatch(capability, /fantasy:body.sample/);
  const inheritance = form({ $ref: "#/$defs/entryId" }, "", { references, path: ["extends", 0] });
  assert.match(inheritance, /adult:cap.sample/); assert.match(inheritance, /fantasy:body.sample/);
});

test("field errors are placed at their schema path and untrusted descriptions are escaped", () => {
  const markup = form({ type: "string" }, "<script>alert(1)</script>", { path: ["manifest", "name"],
    issues: [{ path: ["manifest", "name"], message: "Name is required" }] });
  assert.match(markup, /aria-invalid="true"/); assert.match(markup, /Name is required/);
  assert.doesNotMatch(markup, /<script>/);
  assert.ok(pathMatches({ path: ["files", "entries.json", "entries", 0, "name"] }, ["files", "entries.json", "entries", 0]));
  assert.equal(replaceKey({ actor: 1, partner: 2 }, "actor", "partner").actor, 1);
  assert.deepEqual(replaceKey({ actor: 1 }, "actor", "lead"), { lead: 1 });
});

function renderCreator(patch = {}) {
  return renderToStaticMarkup(createElement(CreatorView, { visible: true, packs: [], state: { schemas, references: { entries: [], categories: [], problems: [] },
    drafts: [], document: newPackDocument(), readOnly: false, dirty: true, saved: null, loading: false, busy: false, error: "", notice: "", validation: null,
    change: noop, startNew: noop, openDraft: noop, openPack: noop, importZIP: noop, save: noop, validate: noop, exportZIP: noop, install: noop, preview: noop, reload: noop,
    ...patch } }));
}

test("creator distinguishes unsaved drafts, validation, export and explicit installation", () => {
  const markup = renderCreator();
  for (const expected of ["Unsaved changes", "Save draft", "Validate pack", "Export ZIP", "Install completed pack", "Advanced JSON view", "Draft navigation", "vocabulary/SKILL.md"]) {
    assert.ok(markup.includes(expected), expected);
  }
  assert.match(markup, /No installation, LLM or scene generation/);
  assert.match(markup, /normal SFW\/NSFW eligibility rules are unchanged/);
});

test("bundled packs disable editing and publication while keeping definitions inspectable", () => {
  const markup = renderCreator({ readOnly: true });
  assert.match(markup, /Read-only bundled pack/); assert.match(markup, /<fieldset disabled=""/);
  assert.match(markup, /disabled="">.*?Save draft/s);
});

test("loading, errors and specific validation issues have distinct feedback", () => {
  assert.match(renderCreator({ loading: true }), /Loading creator schemas and references/);
  assert.match(renderCreator({ error: "Storage unavailable" }), /role="alert"/);
  assert.match(renderCreator({ validation: { valid: false, issues: [{ path: ["manifest", "id"], message: "Duplicate pack ID" }] } }), /Duplicate pack ID/);
});
