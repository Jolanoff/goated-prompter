/** Dataset's explicit dependency boundary: idea -> scene/geometry -> prompt. */
export function invalidateDatasetPrompts(draft, patch = {}) {
  return { ...patch, results: [], quality_report: {},
    scene_plan: (draft.scene_plan || []).map((row) => ({ ...row, prompt_status: "not_generated" })) };
}

export function editDatasetPlan(draft, index, stage, text) {
  return { quality_report: {}, results: draft.results.filter((row) => row.index !== index),
    scene_plan: draft.scene_plan.map((row) => row.index !== index ? row : stage === "idea"
      ? { ...row, idea: text, scene: "", geometry: {}, coverage_conflicts: [],
        idea_status: "valid", scene_status: "not_generated", prompt_status: "not_generated" }
      : { ...row, scene: text, geometry: {}, coverage_conflicts: [],
        scene_status: text.trim() ? "valid" : "not_generated", prompt_status: "not_generated" }) };
}
