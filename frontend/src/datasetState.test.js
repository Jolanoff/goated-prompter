import { test } from "node:test";
import assert from "node:assert/strict";
import { editDatasetPlan, invalidateDatasetPrompts } from "./workflows/datasetState.js";

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

test("target, length and director changes preserve idea, scene and geometry", () => {
  for (const settings of [{ target: "Qwen Image" }, { length: "Detailed" }, { director_preset: "photography_director" }]) {
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
