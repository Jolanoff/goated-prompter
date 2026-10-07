/** JSONL preserves originating idea and scene; TXT/copy remain final-prompt-only. */
export function datasetCopyText(draft) {
  return (draft?.results || []).map((item) => item.prompt.replace(/[\r\n]+/g, " ").trim()).join("\n");
}

export function datasetJsonl(draft) {
  return (draft?.results || []).map((item) => JSON.stringify({
    index: item.index, input: item.input || "", idea: item.idea || null, scene: item.scene || null,
    prompt: item.prompt, trigger: draft.trigger, target: draft.target,
    source: item.input || null,
  })).join("\n");
}

const settingFields = ["subject", "trigger_type", "custom_type", "constraints", "amount", "variety", "trigger",
  "trigger_at_start", "trigger_connected", "expand_trigger", "visual_style", "custom_style", "director_preset",
  "target", "length", "creativity", "source_mode", "inputs"];
const jobFields = ["id", "kind", "status", "completion_state", "revision", "created_at", "finished_at", "result",
  "error", "progress", "progress_at", "status_reason", "events", "llm_trace", "partial_responses",
  "workflow_revision", "input_signature"];

function pick(value, fields) {
  return Object.fromEntries(fields.filter((field) => value && Object.hasOwn(value, field))
    .map((field) => [field, value[field]]));
}

function sensitiveKey(key) {
  const normalized = key.replace(/[^a-z0-9]/gi, "").toLowerCase();
  return /(?:apikey|privatekey|signingkey|secret|password|passwd|credential|authorization|cookie|headers|accesstoken|refreshtoken|authtoken|sessiontoken|confirmationtoken|connectionstring)/.test(normalized) ||
    ["token", "tokens", "auth", "config", "configuration", "environment", "env", "baseurl", "endpoint", "modelpath", "executable"].includes(normalized);
}

function redactUrl(text) {
  try {
    const url = new URL(text);
    url.username = url.password = "";
    for (const key of [...url.searchParams.keys()]) {
      if (sensitiveKey(key) || /signature/i.test(key) || ["key", "sig", "code"].includes(key.toLowerCase())) url.searchParams.set(key, "[REDACTED]");
    }
    return url.href;
  } catch { return "[REDACTED URL]"; }
}

function secretValues(value, sensitive = false) {
  if (typeof value === "string") return sensitive && value.length >= 4 ? [value] : [];
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, child]) => secretValues(child, sensitive || sensitiveKey(key)));
}

function redactText(text, secrets) {
  for (const secret of secrets) text = text.replaceAll(secret, "[REDACTED]");
  return text
    .replace(/\b(Bearer|Basic)\s+[^\s,;"']+/gi, "$1 [REDACTED]")
    .replace(/(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|confirmation[_ -]?token|client[_ -]?secret|private[_ -]?key|token|password|secret)\s*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&]+)/gi, "$1[REDACTED]")
    .replace(/https?:\/\/[^\s<>"';]+/gi, redactUrl)
    .replace(/\bsk-[a-z0-9_-]{8,}\b/gi, "[REDACTED]")
    .replace(/\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+\b/gi, "[REDACTED]");
}

function sanitize(value, secrets) {
  if (typeof value === "string") return redactText(value, secrets);
  if (Array.isArray(value)) return value.map((item) => sanitize(item, secrets));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !sensitiveKey(key)).map(([key, child]) => [key, sanitize(child, secrets)]));
  return value;
}

/** A click-time projection of current state, never a write or a checkpoint release. */
export function datasetGenerationLog({ draft, review, job, record, state } = {}, exportedAt = new Date()) {
  const datasetJob = ["dataset", "dataset_scenes", "dataset_understanding"].includes(job?.kind) ? job : null;
  const snapshot = {
    schema_version: 1,
    exported_at: exportedAt.toISOString(),
    settings: pick(draft, settingFields),
    dataset_idea: draft?.subject || "",
    scene_plan: draft?.scene_plan || [],
    generated_prompts: draft?.results || [],
    understanding: review ? { ...pick(review, ["operation", "options", "status", "jobId", "brief", "error", "notice"]),
      input: pick(review.input, settingFields) } : null,
    job: datasetJob ? pick(datasetJob, jobFields) : null,
    state: pick(state, ["active", "starting", "error", "settings_status", "settings_error", "settings_conflict",
      "stale_scene_plan", "valid_scene_count", "novelty_notice"]),
    metadata: { ...pick(record, ["revision", "checkpoint", "scene_eligibility", "scene_plan_matches_settings",
      "idea_limits", "scene_limits"]), ...pick(draft, ["scene_plan_signature", "result_job_id"]) },
  };
  // Also remove credentials repeated in free-form errors or transport messages.
  const secrets = [...new Set(secretValues({ draft, review, job: datasetJob, record }))].sort((a, b) => b.length - a.length);
  return JSON.stringify(sanitize(snapshot, secrets), null, 2);
}
