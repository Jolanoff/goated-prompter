import { test } from "node:test";
import assert from "node:assert/strict";
import { datasetRequestSignature, datasetRetryStage, datasetSceneSignature, editDatasetPlan } from "./datasetState.js";

const item = { index: 1, idea: "A boxer slips a punch.", input: "",
  scene: "A boxer on the left ducks under her partner's jab in a sweaty arena, full-body three-quarter view.",
  scene_status: "valid", self_check: "PASS" };

test("idea and scene participate in current-plan and approval signatures", () => {
  const draft = { scene_plan: [item], results: [] };
  for (const field of ["idea", "scene"]) {
    const revised = { ...item, [field]: "Changed text" };
    assert.notEqual(datasetSceneSignature(revised), datasetSceneSignature(item), field);
    assert.notEqual(datasetRequestSignature({ ...draft, scene_plan: [revised] }), datasetRequestSignature(draft), field);
  }
});

test("editing an idea keeps its scene, editing a scene keeps its idea, and siblings stay untouched", () => {
  const sibling = { ...item, index: 2 };
  const draft = { scene_plan: [item, sibling], results: [{ index: 1, prompt: "Old prompt" }, { index: 2, prompt: "Sibling prompt" }] };
  const idea = editDatasetPlan(draft, 1, "idea", "A boxer counters a hook.").scene_plan[0];
  assert.equal(idea.idea, "A boxer counters a hook.");
  assert.equal(idea.scene, item.scene);
  const scene = editDatasetPlan(draft, 1, "scene", "Edited scene").scene_plan[0];
  assert.equal(scene.scene, "Edited scene");
  assert.equal(scene.idea, item.idea);
  for (const stage of ["idea", "scene"]) {
    const updated = editDatasetPlan(draft, 1, stage, "Edited");
    assert.equal(updated.scene_plan[1], sibling);
    assert.deepEqual(updated.results, [draft.results[1]]);
  }
});

test("edits reset only that prompt so it is written again from the edited scene", () => {
  const written = { ...item, prompt_status: "valid" };
  for (const stage of ["idea", "scene"]) {
    const updated = editDatasetPlan({ scene_plan: [written], results: [{ index: 1, prompt: "Old prompt" }] }, 1, stage, "Edited");
    assert.equal(updated.scene_plan[0].prompt_status, "not_generated");
    assert.equal(updated.scene_plan[0].self_check, "");
    assert.deepEqual(updated.results, []);
    assert.equal(written.self_check, "PASS");
  }
});

test("a failed row retries its idea; a usable scene retries only its prompt", () => {
  assert.equal(datasetRetryStage({ ...item, scene_status: "failed", failure_stage: "idea" }, { usable: false }), "idea");
  assert.equal(datasetRetryStage({ ...item, prompt_status: "failed", failure_stage: "prompt" }, { usable: true }), "prompt");
  assert.equal(datasetRetryStage({ index: 1, idea: "", scene: "", scene_status: "failed" }, { usable: false }), "idea");
});

test("approved characters read as one line each with sex, kind and origin", async () => {
  const { datasetCharacterLines } = await import("./datasetState.js");
  assert.deepEqual(datasetCharacterLines({ characters: [
    { name: "Naruto Uzumaki", count: 1, sex: "male", kind: "human", origin: "named", series: "Naruto", traits: "" },
    { name: "random companion", count: 1, sex: "unspecified", kind: "anthro", origin: "random", series: "", traits: "" },
    { name: "guard", count: 2, sex: "female", kind: "robot", origin: "described", series: "", traits: "chrome armor" },
  ] }), [
    "Naruto Uzumaki · male human · from Naruto",
    "random companion · sex open anthro · invented for each image",
    "2 × guard · female robot · as described · chrome armor",
  ]);
  assert.deepEqual(datasetCharacterLines({}), []);
  assert.deepEqual(datasetCharacterLines(null), []);
});
