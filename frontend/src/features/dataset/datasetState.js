import { maxSeed } from "./options.js";

/** Dataset's explicit dependency boundary: idea with its scene -> prompt. */
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
  const source = Object.fromEntries(Object.entries(draft || {})
    .filter(([key]) => !["results", "result_job_id", "plan_scenes_first"].includes(key)));
  if (source.scene_plan) source.scene_plan = source.scene_plan.map((row) => Object.fromEntries(
    Object.entries(row).filter(([key]) => key !== "prompt_status" &&
      !(row.failure_stage === "prompt" && ["failure_stage", "failure_reason"].includes(key))),
  ));
  return JSON.stringify(canonicalValue(source));
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

/** The seed for the next batch run, like ComfyUI's control: same, last plus one, or new. */
export function nextDatasetSeed(draft, random = Math.random) {
  const seed = Number.isInteger(draft.seed) ? draft.seed : 0;
  if (draft.seed_mode === "fixed") return seed;
  if (draft.seed_mode === "increment") return seed >= maxSeed ? 0 : seed + 1;
  return Math.floor(random() * (maxSeed + 1));
}

export function freshDatasetRequest(draft) {
  return { ...draft, scene_plan: [], scene_plan_signature: "" };
}

export function hasCompletedDatasetPrompt(row, results) {
  return row.prompt_status === "valid" && results.some((item) => item.index === row.index && item.prompt?.trim() &&
    ["input", "idea", "scene"].every((field) => item[field] === (row[field] || "")));
}

function understandingText(item) {
  if (item.scope !== "all_outputs") return item.text;
  return item.text.replace(/^(?:every|each|all)\s+(?:images?|outputs?|prompts?)(?:\s*[:—-]\s*|\s+)/i, "").trim();
}

function requirementKey(item) {
  return `${item.scope}:${understandingText(item)}`;
}

function scopedRequirement(item) {
  const scope = item.scope === "all_outputs" ? ""
    : item.scope === "dataset" ? "Across the dataset: " : `Guided input ${item.scope.split(":")[1]}: `;
  return `${scope}${understandingText(item)}`;
}

function uniqueRequirements(items) {
  return [...new Map(items.map((item) => [requirementKey(item), item])).values()];
}

export function datasetUnderstandingSummary(brief) {
  const mustVary = uniqueRequirements(brief?.must_vary || []);
  const variationKeys = new Set(mustVary.map(requirementKey));
  const fixed = uniqueRequirements(brief?.fixed || []).filter((item) => !variationKeys.has(requirementKey(item)));
  const classifiedKeys = new Set([...fixed, ...mustVary].map(requirementKey));
  const contract = brief?.hard?.length ? brief.hard : ["rules", "visible_evidence", "interactions", "visibility_to_preserve"]
    .flatMap((field) => brief?.[field] || []);
  const required = uniqueRequirements(contract).filter((item) => !classifiedKeys.has(requirementKey(item)));
  return {
    consistent: fixed.map(scopedRequirement),
    mayVary: uniqueRequirements([...(brief?.may_vary || []), ...(brief?.free || [])]).map(scopedRequirement),
    mustVary: mustVary.map(scopedRequirement),
    everyImage: required.filter((item) => item.scope === "all_outputs").map(scopedRequirement),
    scoped: required.filter((item) => item.scope !== "all_outputs").map(scopedRequirement),
  };
}

function reviewAuthority(field, item, brief) {
  if (["hard", "soft", "free", "physical_conflicts"].includes(field)) return field;
  if (field === "may_vary") return "free";
  if (field === "natural_occlusions") return ["hard", "soft", "free"].find((kind) =>
    (brief[kind] || []).some((entry) => requirementKey(entry) === requirementKey(item))) || "context";
  return "hard";
}

export function datasetUnderstandingSections(brief) {
  if (!brief?.requested_generation) return [];
  const labels = {
    hard: "Requirements", soft: "Adjustable preferences", free: "Open creative choices",
    fixed: "What stays fixed", may_vary: "What may vary", must_vary: "What must vary",
    rules: "Rules every output must follow", visible_evidence: "Required visible evidence",
    interactions: "Required interactions", natural_occlusions: "Natural overlaps and occlusions",
    visibility_to_preserve: "What must remain visible", physical_conflicts: "Physical conflicts and possible resolutions",
  };
  if (brief.action_options) labels.action_options = "Action alternatives—not all in one image";
  const facts = new Map();
  return Object.entries(labels).map(([field, label]) => {
    const records = [];
    for (const item of brief[field] || []) {
      const text = field === "physical_conflicts"
        ? `${item.conflict} ${item.compatible_resolution || "Needs clarification; no compatible resolution established."}`
        : item.text;
      const key = field === "physical_conflicts"
        ? JSON.stringify([field, item.scope, item.conflict, item.compatible_resolution])
        : JSON.stringify([reviewAuthority(field, item, brief), requirementKey(item)]);
      const existing = facts.get(key);
      if (existing) {
        if (existing.label !== label && !existing.annotations.includes(label)) existing.annotations.push(label);
      } else {
        const record = { label, text: scopedRequirement({ ...item, text }), annotations: [] };
        facts.set(key, record);
        records.push(record);
      }
    }
    return { label, records };
  }).map(({ label, records }) => ({ label, items: records.map(({ text }) => text),
    ...(records.some(({ annotations }) => annotations.length)
      ? { annotations: records.map(({ annotations }) => annotations) } : {}),
  }));
}

const characterSex = { female: "female", male: "male", mixed: "mixed group", unspecified: "sex open", none: "no sex" };
const characterOrigin = { named: "existing character", described: "as described", random: "invented for each image" };

/** One readable line per approved character, e.g. "Naruto Uzumaki · male human · from Naruto". */
export function datasetCharacterLines(brief) {
  return (brief?.characters || []).map((item) => [
    `${item.count > 1 ? `${item.count} × ` : ""}${item.name}`,
    `${characterSex[item.sex] || item.sex} ${item.kind}`,
    item.series ? `from ${item.series}` : characterOrigin[item.origin] || item.origin,
    item.traits,
  ].filter(Boolean).join(" · "));
}

export function datasetSceneSignature(row) {
  if (!row) return null;
  // Only the scene dependency boundary, not writer status or failure bookkeeping.
  // The server saves scenes with whitespace collapsed, so compare them the same way.
  return JSON.stringify(canonicalValue({ index: row.index, input: row.input || "",
    idea: row.idea, scene: (row.scene || "").trim().split(/\s+/).join(" "),
    scene_status: row.scene_status || "valid", self_check: row.self_check }));
}

export function isDatasetSceneCurrent(row, record) {
  const saved = record?.draft?.scene_plan?.find((item) => item.index === row?.index);
  return !!row && !!saved && datasetSceneSignature(saved) === datasetSceneSignature(row) &&
    isDatasetSceneUsable(record?.scene_eligibility?.[row.index]);
}

export function datasetRetryStage(row, eligibility) {
  if (row.failure_stage === "idea" || row.idea_status === "failed") return "idea";
  return isDatasetSceneUsable(eligibility) ? "prompt" : "idea";
}

export function editDatasetPlan(draft, index, stage, text) {
  return { results: draft.results.filter((row) => row.index !== index),
    scene_plan: draft.scene_plan.map((row) => {
      if (row.index !== index) return row;
      const { failure_reason, failure_stage, ...scene } = row;
      // The idea is a label for its scene, so editing either keeps the other.
      return { ...scene, [stage]: text, self_check: "",
        ...(stage === "idea" ? { idea_status: "valid" } : {}),
        scene_status: "not_generated", prompt_status: "not_generated" };
    }) };
}
