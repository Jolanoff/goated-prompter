import { test } from "node:test";
import assert from "node:assert/strict";
import { editDatasetPlan, invalidateDatasetPrompts, isDatasetSceneUsable, datasetRetryStage, datasetSceneSignature, isDatasetSceneCurrent,
  freshDatasetRequest, hasCompletedDatasetPrompt, nextDatasetSeed } from "./datasetState.js";

const draft = { scene_plan: [1, 2].map((index) => ({ index, idea: `idea ${index}`, scene: `scene ${index}`,
  self_check: "PASS", idea_status: "valid", scene_status: "valid", prompt_status: "valid" })),
  results: [1, 2].map((index) => ({ index, prompt: `prompt ${index}` })) };

test("fresh generation clears reusable scenes in an isolated request without discarding the saved batch", () => {
  const current = { ...draft, subject: "A duck exploring", amount: 2, trigger: "duck_token", target: "Generic",
    scene_plan_signature: "current-plan", result_job_id: "saved-job" };
  const before = structuredClone(current);
  const fresh = freshDatasetRequest(current);
  assert.deepEqual(fresh, { ...current, scene_plan: [], scene_plan_signature: "" });
  assert.deepEqual(current, before);
});

test("completed prompts must match the checked scene, idea, input and index before Continue skips them", () => {
  const row = { ...draft.scene_plan[0], input: "Guided action" };
  const result = { index: row.index, input: row.input, idea: row.idea, scene: row.scene, prompt: "Exact edited prompt." };
  assert.equal(hasCompletedDatasetPrompt(row, [result]), true);
  for (const patch of [{ index: 2 }, { input: "Other action" }, { idea: "Other idea" }, { scene: "Other scene" }, { prompt: "  " }]) {
    assert.equal(hasCompletedDatasetPrompt(row, [{ ...result, ...patch }]), false);
  }
  for (const prompt_status of ["not_generated", "failed"]) {
    assert.equal(hasCompletedDatasetPrompt({ ...row, prompt_status }, [result]), false);
  }
  assert.equal(hasCompletedDatasetPrompt(row, []), false);
});

test("scene signatures ignore key order and downstream prompt bookkeeping", () => {
  const saved = { ...draft.scene_plan[0], prompt_status: "failed", failure_reason: "Writer failed" };
  const reordered = { self_check: "PASS", scene: "scene 1", idea: "idea 1", index: 1, prompt_status: "not_generated" };
  assert.equal(datasetSceneSignature(saved), datasetSceneSignature(reordered));
  const record = { draft: { scene_plan: [saved] }, scene_eligibility: { 1: { usable: true } } };
  assert.equal(isDatasetSceneCurrent(reordered, record), true);
  assert.equal(isDatasetSceneCurrent(reordered, { ...record, scene_eligibility: { 1: { usable: false } } }), false);
});

test("scene signatures ignore the whitespace the server collapses when saving", () => {
  const saved = { ...draft.scene_plan[0], scene: "A duck reads a map on a bench." };
  assert.equal(datasetSceneSignature({ ...saved, scene: "  A duck\nreads a map   on a bench.  " }), datasetSceneSignature(saved));
});

test("scene signatures include the selected position even when the scene prose is unchanged", () => {
  const row = { ...draft.scene_plan[0], selected_position: "supported seated pose" };
  const record = { draft: { scene_plan: [row] }, scene_eligibility: { 1: { usable: true } } };
  assert.equal(isDatasetSceneCurrent({ ...row }, record), true);
  for (const selected_position of [undefined, "supported standing pose"]) {
    const revised = { ...row, selected_position };
    assert.notEqual(datasetSceneSignature(row), datasetSceneSignature(revised));
    assert.equal(isDatasetSceneCurrent(revised, record), false);
  }
});

test("scene edits clear stale selection metadata while writer settings preserve it", () => {
  const selected = { ...draft, scene_plan: [{ ...draft.scene_plan[0], selected_position: "supported seated pose" }] };
  assert.equal(editDatasetPlan(selected, 1, "scene", "A new natural description.").scene_plan[0].selected_position, undefined);
  assert.equal(invalidateDatasetPrompts(selected, { target: "Anima" }).scene_plan[0].selected_position, "supported seated pose");
});

test("selected settings participate in scene signatures but do not override scene edits", () => {
  const row = { ...draft.scene_plan[0], selected_setting: "synthetic room alpha" };
  assert.notEqual(datasetSceneSignature(row), datasetSceneSignature({ ...row, selected_setting: "synthetic room beta" }));
  const edited = editDatasetPlan({ ...draft, scene_plan: [row] }, 1, "scene", "Updated prose.");
  assert.equal(edited.scene_plan[0].selected_setting, undefined);
});

test("edits retain SceneSpec for reconciliation but clear old verification", () => {
  const row = { ...draft.scene_plan[0], scene_spec: { action: "greeting" }, scene_validation: { checked: true } };
  const edited = editDatasetPlan({ ...draft, scene_plan: [row] }, 1, "scene", "A supported new pose.").scene_plan[0];
  assert.equal(edited.scene_spec, row.scene_spec);
  assert.equal(edited.scene_validation, undefined);
  assert.equal(edited.edited_stage, "scene");
  assert.notEqual(datasetSceneSignature(row), datasetSceneSignature(edited));
});

test("a scene edit invalidates batch coverage without discarding a sibling's individual evidence", () => {
  const current = { ...draft, scene_plan: draft.scene_plan.map((row) => ({ ...row,
    scene_validation: { text_signature: `checked-${row.index}` },
    batch_validation: { valid: true, signature: "batch-checked", errors: [] } })) };
  const before = structuredClone(current);
  const edited = editDatasetPlan(current, 1, "scene", "New scene");
  assert.equal(edited.scene_plan[0].scene_validation, undefined);
  assert.equal(edited.scene_plan[1].scene_validation, current.scene_plan[1].scene_validation);
  assert.equal(edited.scene_plan[1].scene, current.scene_plan[1].scene);
  assert.ok(edited.scene_plan.every((row) => row.batch_validation.valid === false));
  assert.notEqual(datasetSceneSignature(current.scene_plan[1]), datasetSceneSignature(edited.scene_plan[1]));
  assert.deepEqual(current, before);
});

test("scene signatures invalidate source, idea, prose, self-check and scene-state changes", () => {
  const row = draft.scene_plan[0];
  for (const change of [{ input: "new source" }, { idea: "new event" }, { scene: "new scene" },
    { self_check: "" }, { scene_status: "not_generated" }]) {
    assert.notEqual(datasetSceneSignature(row), datasetSceneSignature({ ...row, ...change }));
  }
  assert.equal(isDatasetSceneCurrent(undefined, undefined), false);
  assert.equal(isDatasetSceneCurrent(row, {}), false);
});

for (const stage of ["idea", "scene"]) test(`${stage} edits invalidate its check and prompt, not siblings`, () => {
  const changed = editDatasetPlan(draft, 1, stage, "new content");
  assert.equal(changed.scene_plan[0][stage], "new content");
  assert.equal(changed.scene_plan[0].self_check, "");
  assert.equal(changed.scene_plan[0].scene_status, "not_generated");
  assert.equal(changed.scene_plan[0].prompt_status, "not_generated");
  assert.equal(changed.scene_plan[1], draft.scene_plan[1]);
  assert.deepEqual(changed.results, [draft.results[1]]);
  assert.equal(draft.scene_plan[0].self_check, "PASS");
});

test("writer controls preserve checked scene state and only invalidate prompts", () => {
  for (const settings of [{ target: "Qwen Image" }, { length: "Detailed" }, { director_preset: "photography_director" }, { creativity: "Dice" }]) {
    const changed = invalidateDatasetPrompts(draft, settings);
    assert.deepEqual(changed.results, []);
    changed.scene_plan.forEach((row, index) => {
      assert.equal(row.idea, draft.scene_plan[index].idea);
      assert.equal(row.scene, draft.scene_plan[index].scene);
      assert.equal(row.self_check, "PASS");
      assert.equal(row.prompt_status, "not_generated");
    });
  }
});

test("scene selection consumes server eligibility instead of guessing from prose", () => {
  assert.equal(isDatasetSceneUsable({ usable: true, source_kind: "frozen_scene" }), true);
  assert.equal(isDatasetSceneUsable({ usable: false, reason: "Check pending" }), false);
  assert.equal(isDatasetSceneUsable(draft.scene_plan[0]), false);
  assert.equal(isDatasetSceneUsable(undefined), false);
});

test("manual edits clear stale failure metadata only for the edited item", () => {
  const failed = { ...draft, scene_plan: draft.scene_plan.map((row) => ({ ...row,
    scene_status: "failed", prompt_status: "failed", failure_reason: "Interrupted", failure_stage: "scene" })) };
  for (const stage of ["idea", "scene"]) {
    const changed = editDatasetPlan(failed, 1, stage, "Corrected content");
    assert.equal(changed.scene_plan[0].failure_reason, undefined);
    assert.equal(changed.scene_plan[0].failure_stage, undefined);
    assert.equal(changed.scene_plan[1], failed.scene_plan[1]);
  }
});

test("retry stages regenerate the idea unless its scene is usable", () => {
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], scene_status: "failed" }), "idea");
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], scene: "", scene_status: "not_generated" }), "idea");
  assert.equal(datasetRetryStage({ ...draft.scene_plan[0], prompt_status: "failed" }, { usable: true }), "prompt");
  assert.equal(datasetRetryStage({ idea: "", scene: "", scene_status: "failed" }), "idea");
});

test("an unsuccessful duplicate-idea repair retries the idea rather than composing its rejected event", () => {
  const rejected = { idea: "Repeated event retained for inspection", scene: "", self_check: "",
    idea_status: "failed", scene_status: "failed", prompt_status: "failed", failure_stage: "idea" };
  assert.equal(datasetRetryStage(rejected, { usable: false }), "idea");
  assert.equal(datasetRetryStage({ ...rejected, failure_stage: undefined }, { usable: false }), "idea");
});

test("writer settings preserve scene failures but clear prompt-only errors", () => {
  const failed = { ...draft, scene_plan: [
    { ...draft.scene_plan[0], scene_status: "failed", failure_reason: "Scene interrupted", failure_stage: "scene" },
    { ...draft.scene_plan[1], prompt_status: "failed", failure_reason: "Invalid JSON", failure_stage: "prompt" },
  ] };
  const changed = invalidateDatasetPrompts(failed, { target: "Qwen Image" });
  assert.equal(changed.scene_plan[0], failed.scene_plan[0]);
  assert.equal(changed.scene_plan[1].failure_reason, undefined);
  assert.equal(changed.scene_plan[1].prompt_status, "not_generated");
});

test("the next batch seed is kept, increased by one or redrawn", () => {
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "fixed" }), 41);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "increment" }), 42);
  assert.equal(nextDatasetSeed({ seed: 4294967295, seed_mode: "increment" }), 0);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "randomize" }, () => 0.5), 2147483648);
});
