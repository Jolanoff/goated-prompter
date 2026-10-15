/** JSONL preserves originating idea and scene; TXT/copy remain final-prompt-only. */
export function datasetCopyText(draft) {
  return (draft?.results || []).map((item) => item.prompt.replace(/[\r\n]+/g, " ").trim()).join("\n");
}

export function datasetJsonl(draft) {
  return (draft?.results || []).map((item) => {
    const row = draft.scene_plan?.find((row) => row.index === item.index);
    return JSON.stringify({
      index: item.index, input: item.input || "", idea: item.idea || null, scene: item.scene || null,
      prompt: item.prompt, trigger: draft.trigger, target: draft.target,
      source: item.input || null,
      ...(row ? { validation_status: row.prompt_status || "unverified", quality_warnings: row.quality_warnings || [],
        ...(row.batch_validation ? { batch_validation: row.batch_validation } : {}) } : {}),
    });
  }).join("\n");
}

const settingFields = ["subject", "trigger_type", "custom_type", "constraints", "amount", "trigger",
  "trigger_at_start", "trigger_connected", "expand_trigger", "director_preset",
  "target", "length", "creativity", "style", "source_mode", "inputs", "seed", "seed_mode"];
const jobFields = ["id", "kind", "status", "completion_state", "revision", "created_at", "finished_at", "result",
  "error", "progress", "progress_at", "status_reason", "events", "llm_trace", "partial_responses",
  "llm_stages", "workflow_revision", "input_signature"];

function pick(value, fields) {
  return Object.fromEntries(fields.filter((field) => value && Object.hasOwn(value, field))
    .map((field) => [field, value[field]]));
}

function sensitiveKey(key) {
  const normalized = key.replace(/[^a-z0-9]/gi, "").toLowerCase();
  return /(?:apikey|privatekey|signingkey|secret|password|passwd|credential|authorization|cookie|headers|accesstoken|refreshtoken|authtoken|sessiontoken|confirmationtoken|connectionstring)/.test(normalized) ||
    ["token", "tokens", "auth", "config", "configuration", "environment", "env", "baseurl", "endpoint", "modelpath", "executable",
      "catalogid", "selectedposition", "selectedsetting", "privatevocabulary", "vocabularyentries", "vocabularysource"].includes(normalized);
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

const vocabularyDiagnosticFields = ["loaded", "eligible", "rejected", "diagnostics", "unresolved_constraints", "filtering_rules"];

function secretValues(value, sensitive = false, field = "") {
  if (typeof value === "string") return sensitive && value.length >= 4 ? [value] : [];
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap((item) => secretValues(item, sensitive, field));
  return Object.entries(value).flatMap(([key, child]) => secretValues(child, sensitive || sensitiveKey(key)
    || (value.private_vocabulary === true && key === "choices")
    || (field === "vocabulary" && !vocabularyDiagnosticFields.includes(key))
    || (field === "diagnostics" && key === "entry"), key));
}

const contentFields = new Set(["subject", "trigger", "inputs", "constraints", "input", "idea", "scene", "prompt",
  "dataset_idea", "requested_generation", "text"]);

function redactText(text, secrets, detectCredentials) {
  for (const secret of secrets) text = text.replaceAll(secret, "[REDACTED]");
  if (!detectCredentials) return text;
  return text
    .replace(/\b(Bearer|Basic)\s+[^\s,;"']+/gi, "$1 [REDACTED]")
    .replace(/(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|confirmation[_ -]?token|client[_ -]?secret|private[_ -]?key|token|password|secret)\s*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&]+)/gi, "$1[REDACTED]")
    .replace(/https?:\/\/[^\s<>"';]+/gi, redactUrl)
    .replace(/\bsk-[a-z0-9_-]{8,}\b/gi, "[REDACTED]")
    .replace(/\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+\b/gi, "[REDACTED]");
}

const rawDiagnosticFields = new Set(["content", "output", "reasoning", "partial_text", "issue", "message", "error"]);

function sanitize(value, secrets, field = "", privateDiagnostics = false) {
  if (privateDiagnostics && field === "choices") return {};
  if (privateDiagnostics && ["messages", "response_format"].includes(field)) return "[PRIVATE CONTENT OMITTED]";
  if (privateDiagnostics && field === "finish_reason" && value !== null &&
    !/^(stop|length|content_filter|tool_calls|function_call|other)$/.test(value)) return "other";
  if (typeof value === "string") return privateDiagnostics && rawDiagnosticFields.has(field)
    ? "[PRIVATE CONTENT OMITTED]" : redactText(value, secrets, !contentFields.has(field));
  if (Array.isArray(value)) return value.map((item) => sanitize(item, secrets, field, privateDiagnostics));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !sensitiveKey(key) && !(field === "vocabulary" && !vocabularyDiagnosticFields.includes(key))
      && !(field === "diagnostics" && !["line", "record", "rule", "reason"].includes(key)))
    .map(([key, child]) => [key, sanitize(child, secrets, key, privateDiagnostics)]));
  return value;
}

function hasPrivateDiagnostics(draft, job) {
  const rows = [...(draft?.scene_plan || []), ...(job?.result?.scene_plan || [])];
  return rows.some((row) => row.scene_spec?.private_vocabulary)
    || job?.llm_trace?.private_content === true
    || job?.partial_responses?.some((row) => row.private_content === true)
    || JSON.stringify(job?.llm_trace?.messages || []).includes("MORE SEXUAL CONTENT RULES");
}

const legacyKinds = ["dataset", "dataset_scenes", "dataset_understanding"];
const v2Kind = "dataset_v2_scenes";
const v2ResultFields = ["run_id", "stage", "complete", "requested", "written", "missing", "slots", "concepts", "scenes", "prompts"];

/** A V2 run (Confirm -> scenes -> prompts): its status, slots, concepts, scenes and prompts, the vocabulary it used
 * (pack selection with versions and fingerprints, entries and ideas by id and image, exclusions, Visual Direction)
 * and the packs its run record holds. The vocabulary block is renamed so the legacy TXT vocabulary filter never
 * strips it; it carries ids, names and reasons only, never pack wording. */
function v2RunSnapshot(run, job, runPacks) {
  const result = run?.result || (job?.kind === v2Kind ? job.result : null);
  if (!run && !result) return null;
  return {
    job_id: run?.jobId || job?.id || null,
    status: run?.status || job?.status || null,
    error: run?.error || job?.error || "",
    brief: run?.brief || null,
    visual_direction_settings: run?.visual_direction ?? null,
    ...pick(result, v2ResultFields),
    vocabulary_retrieval: result?.vocabulary || null,
    vocabulary_packs: { requested: run?.vocabulary_packs ?? null, recorded: runPacks?.packs ?? null,
      status: runPacks?.status ?? null, ...(runPacks?.error ? { load_error: runPacks.error } : {}) },
  };
}

/** A click-time projection of current state, never a write or a checkpoint release. */
export function datasetGenerationLog({ draft, review, job, record, state, run, runPacks } = {}, exportedAt = new Date()) {
  const datasetJob = [...legacyKinds, v2Kind].includes(job?.kind) ? job : null;
  // A V2 job's result is exported once, under v2_run, never through the legacy job projection.
  const v2 = datasetJob?.kind === v2Kind;
  const jobSnapshot = v2 ? pick(datasetJob, jobFields.filter((field) => field !== "result"))
    : datasetJob ? pick(datasetJob, jobFields) : null;
  const v2Run = v2RunSnapshot(run, datasetJob, runPacks);
  const snapshot = {
    schema_version: 1,
    exported_at: exportedAt.toISOString(),
    settings: pick(draft, settingFields),
    dataset_idea: draft?.subject || "",
    scene_plan: draft?.scene_plan || [],
    generated_prompts: draft?.results || [],
    understanding: review ? { ...pick(review, ["operation", "options", "status", "jobId", "brief", "routing", "error", "notice"]),
      input: pick(review.input, settingFields) } : null,
    job: jobSnapshot,
    v2_run: v2Run,
    state: pick(state, ["active", "starting", "error", "settings_status", "settings_error", "settings_conflict",
      "stale_scene_plan", "valid_scene_count", "novelty_notice"]),
    metadata: { ...pick(record, ["revision", "checkpoint", "scene_eligibility", "scene_plan_matches_settings",
      "idea_limits", "scene_limits"]), ...pick(draft, ["scene_plan_signature", "result_job_id"]) },
  };
  // Also remove credentials repeated in free-form errors or transport messages.
  // V2 results are searched through their export projection: their vocabulary block holds diagnostics, not the
  // legacy private TXT vocabulary whose every value is treated as a secret.
  const secrets = [...new Set(secretValues({ draft, review, job: v2 ? jobSnapshot : datasetJob, record,
    run: run && { ...run, result: undefined }, runPacks, v2_run: v2Run }))].sort((a, b) => b.length - a.length);
  return JSON.stringify(sanitize(snapshot, secrets, "", hasPrivateDiagnostics(draft, datasetJob)), null, 2);
}
