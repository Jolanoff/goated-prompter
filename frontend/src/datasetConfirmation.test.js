import { test } from "node:test";
import assert from "node:assert/strict";
import { datasetRequestSignature, reviseDatasetRequest } from "./workflows/datasetState.js";

test("request approval ignores result bookkeeping but detects every source and saved-scene edit", () => {
  const input = { subject: "Two people boxing", trigger: "person 1, person 2", amount: 2, target: "Generic",
    length: "Medium", constraints: "Arena. Gloves.", scene_plan: [{ index: 1, scene: "Boxing" }], results: [] };
  const signature = datasetRequestSignature(input);
  assert.equal(signature, datasetRequestSignature({ ...input, results: [{ prompt: "Old output" }], quality_report: { score: 100 } }));
  for (const patch of [{ subject: "New concept" }, { trigger: "new_token" }, { amount: 3 }, { target: "Anima" },
    { constraints: "Blond hair" }, { length: "Detailed" }, { scene_plan: [{ index: 1, scene: "Edited scene" }] }]) {
    assert.notEqual(signature, datasetRequestSignature({ ...input, ...patch }));
  }
  assert.equal(signature, datasetRequestSignature(Object.fromEntries(Object.entries(input).reverse())));
});

test("extra instructions create an isolated revised request without discarding old results", () => {
  const input = { constraints: "Arena. Gloves.", scene_plan: [{ scene: "Existing scene" }],
    scene_plan_signature: "saved", results: [{ prompt: "Manually edited output" }], quality_report: { score: 100 } };
  const before = structuredClone(input);
  const revised = reviseDatasetRequest(input, "  One person must have blond hair.  ");
  assert.equal(revised.constraints, "Arena. Gloves.\nOne person must have blond hair.");
  assert.deepEqual(revised.scene_plan, []);
  assert.equal(revised.scene_plan_signature, "");
  assert.deepEqual(revised.results, input.results);
  assert.deepEqual(input, before);
  assert.equal(reviseDatasetRequest(input, "  "), input);
});
