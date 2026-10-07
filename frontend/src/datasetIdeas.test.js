import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";
import { datasetIdeaDetails, datasetRequestSignature, datasetSceneSignature, editDatasetPlan } from "./workflows/datasetState.js";

const item = { index: 1, idea: "A boxer slips a punch.", placement: "Boxer left, partner right.",
  visibility: "Contact overlap preserves the exposed head.", camera: "Three-quarter angle.", framing: "Full body.",
  context: "Arena center.", input: "", scene: "Composed scene", scene_status: "valid", self_check: "" };

test("compact idea display contains exactly the five descriptions alongside the existing idea", () => {
  assert.deepEqual(datasetIdeaDetails(item).map(({ label }) => label), ["Placement", "Visibility", "Camera", "Framing", "Context"]);
  assert.deepEqual(datasetIdeaDetails({ index: 1, idea: "Legacy plan" }), []);
});

test("all compact descriptions participate in current-plan and approval signatures", () => {
  const draft = { scene_plan: [item], results: [] };
  for (const field of ["placement", "visibility", "camera", "framing", "context"]) {
    const revised = { ...item, [field]: "Changed description" };
    assert.notEqual(datasetSceneSignature(revised), datasetSceneSignature(item), field);
    assert.notEqual(datasetRequestSignature({ ...draft, scene_plan: [revised] }), datasetRequestSignature(draft), field);
  }
});

test("manual idea edits remove stale descriptions; scene edits retain the fixed idea and siblings", () => {
  const sibling = { ...item, index: 2 };
  const draft = { scene_plan: [item, sibling], results: [{ index: 1, prompt: "Old prompt" }, { index: 2, prompt: "Sibling prompt" }] };
  for (const stage of ["idea", "scene"]) {
    const updated = editDatasetPlan(draft, 1, stage, "Manually revised content");
    assert.equal(datasetIdeaDetails(updated.scene_plan[0]).length, stage === "idea" ? 0 : 5);
    assert.equal(updated.scene_plan[1], sibling);
    assert.deepEqual(updated.results, [draft.results[1]]);
    assert.equal(datasetIdeaDetails(item).length, 5);
  }
});

test("manual idea and scene edits invalidate PASS or REPAIR before another prompt can be written", () => {
  const checked = { ...item, self_check: "PASS", prompt_status: "valid" };
  for (const stage of ["idea", "scene"]) {
    const updated = editDatasetPlan({ scene_plan: [checked], results: [{ index: 1, prompt: "Old prompt" }] }, 1, stage, "Edited content");
    assert.equal(updated.scene_plan[0].self_check, "");
    assert.equal(updated.scene_plan[0].scene_status, "not_generated");
    assert.equal(updated.scene_plan[0].prompt_status, "not_generated");
    assert.equal(checked.self_check, "PASS");
    assert.deepEqual(updated.results, []);
  }
});

test("scene self-check changes invalidate both approval and current-scene signatures", () => {
  const checked = { ...item, self_check: "PASS" };
  for (const self_check of ["", "REPAIR:\nFoot hidden.\nMove the leg outward."]) {
    const revised = { ...checked, self_check };
    assert.notEqual(datasetSceneSignature(checked), datasetSceneSignature(revised));
    assert.notEqual(datasetRequestSignature({ scene_plan: [checked] }), datasetRequestSignature({ scene_plan: [revised] }));
  }
});

async function ideaComponents() {
  const sourceUrl = new URL("./workflows/DatasetIdeaDetails.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  return import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`);
}

test("planning hints render as five accessible icons with escaped descriptions, not paragraphs", async () => {
  const { default: Details } = await ideaComponents();
  const markup = renderToStaticMarkup(createElement(Details, { item: { ...item, context: "<script>untrusted</script>" } }));
  for (const label of ["Placement", "Visibility", "Camera", "Framing", "Context"]) {
    assert.ok(markup.includes(`aria-label="${label}"`), `missing ${label} icon`);
  }
  assert.equal((markup.match(/<button\b/g) || []).length, 5);
  assert.match(markup, /Contact overlap preserves the exposed head/);
  assert.match(markup, /Idea suggestions, not requirements/);
  assert.match(markup, /required rules/);
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<(?:script|dl|dt|dd|p)\b|geometry|pose_type/);
  assert.equal(renderToStaticMarkup(createElement(Details, { item: { index: 1, idea: "Legacy" } })), "");
});

test("successful and pending scene checks stay in the status chips instead of repeating below the editor", async () => {
  const { DatasetSceneCheck: Check } = await ideaComponents();
  for (const self_check of ["PASS", " PASS ", "pass", ""]) {
    assert.equal(renderToStaticMarkup(createElement(Check, { item: { ...item, self_check } })), "");
  }
  assert.equal(renderToStaticMarkup(createElement(Check, { item: { index: 1 } })), "");
});

test("scene checks still expose repair instructions as escaped warnings", async () => {
  const { DatasetSceneCheck: Check } = await ideaComponents();
  const repair = "REPAIR:\nRequired left foot hidden.\nMove the left leg outward, keeping the <script>pose</script>.";
  const checked = renderToStaticMarkup(createElement(Check, { item: { ...item, self_check: repair } }));
  assert.match(checked, /Scene needs attention/);
  assert.match(checked, /role="note"/);
  assert.match(checked, /REPAIR:/);
  assert.match(checked, /Required left foot hidden/);
  assert.match(checked, /Move the left leg outward/);
  assert.match(checked, /&lt;script&gt;/);
  assert.doesNotMatch(checked, /<script>/);
  assert.match(renderToStaticMarkup(createElement(Check, { item: { ...item, self_check: "Unknown check response" } })), /Unknown check response/);
});
