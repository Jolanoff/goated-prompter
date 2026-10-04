import { test } from "node:test";
import assert from "node:assert/strict";
import { editDatasetPlan, invalidateDatasetPrompts, isDatasetSceneUsable, datasetRetryStage } from "./workflows/datasetState.js";

const draft = { scene_plan: [1, 2].map((index) => ({ index, idea: `idea ${index}`, scene: `scene ${index}`,
  geometry: { camera_view: "front" }, idea_status: "valid", scene_status: "valid", prompt_status: "valid" })),
  results: [1, 2].map((index) => ({ index, prompt: `prompt ${index}` })), quality_report: { score: 100 } };

test("idea edits invalidate only that scene, geometry and prompt", () => {
  const patch = editDatasetPlan(draft, 1, "idea", "new idea");
  assert.equal(patch.scene_plan[0].idea, "new idea");
  assert.equal(patch.scene_plan[0].scene, "");
  assert.deepEqual(patch.scene_plan[0].geometry, {});
  assert.equal(patch.scene_plan[0].scene_status, "not_generated");
  assert.equal(patch.scene_plan[0].prompt_status, "not_generated");
  assert.equal(patch.scene_plan[1], draft.scene_plan[1]);
  assert.deepEqual(patch.results, [draft.results[1]]);
  assert.equal(draft.scene_plan[0].scene, "scene 1");
});

test("scene edits keep idea and discard stale geometry and only its prompt", () => {
  const patch = editDatasetPlan(draft, 1, "scene", "new scene");
  assert.equal(patch.scene_plan[0].idea, draft.scene_plan[0].idea);
  assert.equal(patch.scene_plan[0].scene, "new scene");
  assert.deepEqual(patch.scene_plan[0].geometry, {});
  assert.equal(patch.scene_plan[0].prompt_status, "not_generated");
  assert.equal(patch.scene_plan[1], draft.scene_plan[1]);
  assert.deepEqual(patch.results, [draft.results[1]]);
});

test("target, length, director and descriptive creativity preserve idea, scene and geometry", () => {
  for (const settings of [{ target: "Qwen Image" }, { length: "Detailed" }, { director_preset: "photography_director" }, { creativity: "Dice" }]) {
    const patch = invalidateDatasetPrompts(draft, settings);
    assert.deepEqual(patch.results, []);
    patch.scene_plan.forEach((row, index) => {
      assert.equal(row.idea, draft.scene_plan[index].idea);
      assert.equal(row.scene, draft.scene_plan[index].scene);
      assert.equal(row.geometry, draft.scene_plan[index].geometry);
      assert.equal(row.prompt_status, "not_generated");
    });
    assert.deepEqual(patch.quality_report, {});
  }
});

test("scene selection consumes server eligibility instead of guessing from prose or geometry", () => {
  assert.equal(isDatasetSceneUsable({ usable: true, source_kind: "manual_prose" }), true);
  assert.equal(isDatasetSceneUsable({ usable: false, reason: "Invalid geometry" }), false);
  assert.equal(isDatasetSceneUsable(draft.scene_plan[0]), false);
  assert.equal(isDatasetSceneUsable(undefined), false);
});

test("manual idea/scene edits clear stale failure metadata only for the edited item", () => {
  const failed = { ...draft, scene_plan: draft.scene_plan.map((row) => ({ ...row,
    scene_status: "failed", prompt_status: "failed", failure_reason: "Camera conflict", failure_stage: "scene", replacement_attempted: true })) };
  for (const stage of ["idea", "scene"]) {
    const changed = editDatasetPlan(failed, 1, stage, "Corrected content");
    assert.equal(changed.scene_plan[0].failure_reason, undefined);
    assert.equal(changed.scene_plan[0].failure_stage, undefined);
    assert.equal(changed.scene_plan[0].replacement_attempted, undefined);
    assert.equal(changed.scene_plan[1], failed.scene_plan[1]);
  }
});

test("retrying a failed scene keeps its good idea and never requests idea replacement", () => {
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], scene_status: "failed" }), "scene");
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], scene: "", scene_status: "not_generated" }), "scene");
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], prompt_status: "failed" }, { usable: true }), "prompt");
  assert.equal(datasetRetryStage({ idea: "", scene: "", scene_status: "failed" }), "idea");
});

test("writer settings keep scene failure reasons but clear obsolete prompt-only errors", () => {
  const failed = { ...draft, scene_plan: [
    { ...draft.scene_plan[0], scene_status: "failed", failure_reason: "Rear/face conflict", failure_stage: "scene" },
    { ...draft.scene_plan[1], prompt_status: "failed", failure_reason: "Invalid JSON", failure_stage: "prompt" },
  ] };
  const changed = invalidateDatasetPrompts(failed, { target: "Qwen Image" });
  assert.equal(changed.scene_plan[0], failed.scene_plan[0]);
  assert.equal(changed.scene_plan[1].failure_reason, undefined);
  assert.equal(changed.scene_plan[1].prompt_status, "not_generated");
});
