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

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]),
  );
  return value;
}

export function datasetSceneSignature(row) {
  if (!row) return null;
  // Only the scene dependency boundary, not writer status or failure bookkeeping.
  return JSON.stringify(canonicalValue({ index: row.index, input: row.input || "",
    idea: row.idea, scene: row.scene || "", geometry: row.geometry || {},
    scene_status: row.scene_status || "valid" }));
}

export function isDatasetSceneCurrent(row, record) {
  const saved = record?.draft?.scene_plan?.find((item) => item.index === row?.index);
  return !!row && !!saved && datasetSceneSignature(saved) === datasetSceneSignature(row) &&
    isDatasetSceneUsable(record?.scene_eligibility?.[row.index]);
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
