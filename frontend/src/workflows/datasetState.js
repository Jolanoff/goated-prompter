/** Dataset's explicit dependency boundary: idea -> scene/geometry -> prompt. */
export function invalidateDatasetPrompts(draft, patch = {}) {
  return { ...patch, results: [], quality_report: {},
    scene_plan: (draft.scene_plan || []).map((row) => {
      if (row.scene_status === "failed") return row;
      const { failure_reason, failure_stage, ...scene } = row;
      return { ...scene, prompt_status: "not_generated" };
    }) };
}

export function isDatasetSceneUsable(eligibility) {
  return eligibility?.usable === true;
}

export function datasetRetryStage(row, eligibility) {
  if (isDatasetSceneUsable(eligibility)) return "prompt";
  return row.idea?.trim() ? "scene" : "idea";
}

export function editDatasetPlan(draft, index, stage, text) {
  return { quality_report: {}, results: draft.results.filter((row) => row.index !== index),
    scene_plan: draft.scene_plan.map((row) => {
      if (row.index !== index) return row;
      const { failure_reason, failure_stage, replacement_attempted, ...scene } = row;
      return stage === "idea"
      ? { ...scene, idea: text, scene: "", geometry: {},
        idea_status: "valid", scene_status: "not_generated", prompt_status: "not_generated" }
      : { ...scene, scene: text, geometry: {},
        scene_status: text.trim() ? "valid" : "not_generated", prompt_status: "not_generated" };
    }) };
}
