/** Dataset's explicit dependency boundary: idea -> checked scene -> prompt. */
export function invalidateDatasetPrompts(draft, patch = {}) {
  return { ...patch, results: [],
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

export function datasetRequestSignature(draft) {
  return JSON.stringify(canonicalValue(Object.fromEntries(Object.entries(draft || {})
    .filter(([key]) => !["results", "result_job_id"].includes(key)))));
}

export function reviseDatasetRequest(input, additions) {
  if (!additions.trim()) return input;
  return { ...input, constraints: [input.constraints.trim(), additions.trim()].filter(Boolean).join("\n"),
    scene_plan: [], scene_plan_signature: "" };
}

export function datasetReviewQuestions(brief) {
  return brief?.clarifications || [];
}

export function canConfirmDatasetReview(review, busy, additions = "") {
  return review?.status === "ready" && !!review.confirmation_token && !busy &&
    !additions.trim() && !datasetReviewQuestions(review.brief).length;
}

export function datasetUnderstandingSections(brief) {
  if (!brief?.requested_generation) return [];
  const labels = {
    fixed: "What stays fixed", may_vary: "What may vary", must_vary: "What must vary",
    rules: "Rules every output must follow", visible_evidence: "Required visible evidence",
    interactions: "Required interactions", natural_occlusions: "Natural overlaps and occlusions",
    visibility_to_preserve: "What must remain visible", physical_conflicts: "Physical conflicts and possible resolutions",
  };
  if (brief.action_options) labels.action_options = "Action alternatives—not all in one image";
  return Object.entries(labels).map(([field, label]) => ({ label,
    items: (brief[field] || []).map((item) => {
      const scope = item.scope === "all_outputs" ? "Every output"
        : item.scope === "dataset" ? "Across the dataset" : `Guided input ${item.scope.split(":")[1]}`;
      const text = field === "physical_conflicts"
        ? `${item.conflict} ${item.compatible_resolution || "Needs clarification; no compatible resolution established."}`
        : item.text;
      return `${scope}: ${text}`;
    }),
  }));
}

const ideaDetailLabels = { placement: "Placement", visibility: "Visibility", camera: "Camera", framing: "Framing", context: "Context" };

export function datasetIdeaDetails(row) {
  return Object.entries(ideaDetailLabels).filter(([field]) => row?.[field]?.trim())
    .map(([field, label]) => ({ field, label, text: row[field] }));
}

export function datasetSceneSignature(row) {
  if (!row) return null;
  // Only the scene dependency boundary, not writer status or failure bookkeeping.
  return JSON.stringify(canonicalValue({ index: row.index, input: row.input || "",
    idea: row.idea, scene: row.scene || "",
    scene_status: row.scene_status || "valid", self_check: row.self_check,
    ...Object.fromEntries(datasetIdeaDetails(row).map(({ field, text }) => [field, text])) }));
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
  return { results: draft.results.filter((row) => row.index !== index),
    scene_plan: draft.scene_plan.map((row) => {
      if (row.index !== index) return row;
      const { failure_reason, failure_stage, ...scene } = row;
      scene.self_check = "";
      if (stage === "idea") for (const field of Object.keys(ideaDetailLabels)) delete scene[field];
      return stage === "idea"
      ? { ...scene, idea: text, scene: "",
        idea_status: "valid", scene_status: "not_generated", prompt_status: "not_generated" }
      : { ...scene, scene: text,
        scene_status: "not_generated", prompt_status: "not_generated" };
    }) };
}
