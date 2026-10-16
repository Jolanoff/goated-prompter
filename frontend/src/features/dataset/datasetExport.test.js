import test from "node:test";
import assert from "node:assert/strict";
import { datasetCopyText, datasetGenerationLog } from "./datasetExport.js";

test("Copy all places each prompt on one line without blank separators", () => {
  const draft = { results: [{ prompt: "prompt1" }, { prompt: "prompt2" }] };
  assert.equal(datasetCopyText(draft), "prompt1\nprompt2");
  assert.equal(datasetCopyText(null), "");
  assert.equal(datasetCopyText({ results: [] }), "");
});

test("Copy all flattens prompt line breaks without changing saved prompts", () => {
  const draft = { results: [{ prompt: "First\r\n\r\nprompt." }, { prompt: "Second\nprompt." }] };
  const before = structuredClone(draft);
  assert.equal(datasetCopyText(draft), "First prompt.\nSecond prompt.");
  assert.deepEqual(draft, before);
});

test("generation log is an indented snapshot of settings, review, progress and failures without mutations", () => {
  const context = {
    draft: { subject: "Duck confronting a dinosaur", trigger: "duck_token", amount: 2, target: "Generic" },
    review: { operation: "dataset", status: "ready", jobId: "understanding-1",
      input: { subject: "Duck confronting a dinosaur", constraints: "Both visible" },
      routing: [{ scope: "all_outputs", nsfw: false, position_pools: [], private_position_count: 0 }],
      brief: { requested_generation: "A confrontation", rules: [{ scope: "all_outputs", text: "Both visible" }] } },
    job: { id: "understanding-1", kind: "dataset_understanding", status: "failed", error: "Timeout", revision: 3,
      result: { failed: 1, completed: 1, attempts: 3 }, events: [{ type: "error", message: "Timeout" }],
      llm_trace: { request_number: 4, output: "Partial result", parameters: { temperature: 0.7, max_tokens: 512 } },
      partial_responses: [{ partial_text: "Partial result", completion_state: "timeout" }] },
    record: { revision: 7 },
    state: { error: "Dataset generation failed. Timeout", active: false },
  };
  const before = structuredClone(context);
  const json = datasetGenerationLog(context, new Date("2026-10-07T12:00:00Z"));
  const log = JSON.parse(json);
  assert.match(json, /\n {2}"settings": \{/);
  assert.equal(log.exported_at, "2026-10-07T12:00:00.000Z");
  assert.equal(log.dataset_idea, context.draft.subject);
  assert.equal(log.settings.target, "Generic");
  assert.equal("scene_plan" in log, false);
  assert.equal("generated_prompts" in log, false);
  assert.deepEqual(log.understanding.brief, context.review.brief);
  assert.deepEqual(log.understanding.routing, context.review.routing);
  assert.deepEqual(log.job.partial_responses, context.job.partial_responses);
  assert.equal(log.job.result.attempts, 3);
  assert.equal(log.metadata.revision, 7);
  assert.equal(log.state.error, context.state.error);
  assert.deepEqual(context, before);
});

test("generation log excludes credentials, sensitive configuration and embedded secrets but keeps token usage", () => {
  const log = datasetGenerationLog({ draft: { subject: "An animal", trigger: "animal_token", api_key: "sk-setting-secret" },
    review: { confirmation_token: "review-secret-123", brief: { requested_generation: "An animal" } },
    job: { kind: "dataset_understanding", id: "job", status: "failed", config: { password: "config-secret" },
      error: "Authorization: Bearer bearer-secret-456; https://user:pass@example.test/api?api_key=url-secret&mode=test",
      result: { confirmation_token: "review-secret-123", apiKey: "sk-result-secret", nested: { access_token: "access-secret" },
        token_usage: { prompt_tokens: 20, completion_tokens: 10 }, debug: "key=sk-result-secret; review-secret-123" },
      llm_trace: { parameters: { temperature: 0.4, api_key: "param-secret", headers: { Authorization: "header-secret" } },
        messages: [{ role: "user", content: 'api_key="inline-secret"; token: inline-token; animal_token' }] } },
    record: { config: { api_key: "record-secret" } },
  });
  for (const secret of ["sk-setting-secret", "review-secret-123", "config-secret", "bearer-secret-456", "url-secret",
    "user:pass", "sk-result-secret", "access-secret", "param-secret", "header-secret", "inline-secret", "inline-token", "record-secret"]) {
    assert.ok(!log.includes(secret), `export leaked ${secret}`);
  }
  const value = JSON.parse(log);
  assert.equal(value.settings.trigger, "animal_token");
  assert.deepEqual(value.job.result.token_usage, { prompt_tokens: 20, completion_tokens: 10 });
  assert.equal(value.job.llm_trace.parameters.temperature, 0.4);
  assert.equal("confirmation_token" in value.understanding, false);
  assert.equal("config" in value.job, false);
});

test("generation log supports incomplete and active state and excludes unrelated workflow jobs", () => {
  const empty = JSON.parse(datasetGenerationLog({}));
  assert.equal(empty.understanding, null);
  assert.equal(empty.job, null);
  const running = JSON.parse(datasetGenerationLog({ job: { kind: "dataset_understanding", status: "running", result: null } }));
  assert.equal(running.job.status, "running");
  assert.equal(running.job.result, null);
  const unrelated = JSON.parse(datasetGenerationLog({ job: { kind: "builder", result: { prompt: "Unrelated private prompt" } } }));
  assert.equal(unrelated.job, null);
  for (const kind of ["dataset", "dataset_scenes"]) {
    assert.equal(JSON.parse(datasetGenerationLog({ job: { kind, result: { completed: 1 } } })).job, null, kind);
  }
});

test("credential redaction preserves training triggers ending in token followed by prompt text", () => {
  const prompt = "duck_token: mock scene, access_token_duck on a pond";
  const log = JSON.parse(datasetGenerationLog({ run: { jobId: "j", status: "done", result: v2Result({
    prompts: [{ slot: 1, prompt, trigger_ok: true }] }) } }));
  assert.equal(log.v2_run.prompts[0].prompt, prompt);
});

test("generation log redacts signed URL queries, Basic authorization and private credentials", () => {
  const json = datasetGenerationLog({ job: { kind: "dataset_understanding", result: { private_key: "private-secret", client_secret: "client-secret" },
    error: 'https://example.test/failed?key=query-secret&X-Amz-Signature=signed-secret; Authorization: Basic basic-secret',
    llm_trace: { output: 'client_secret="inline-client-secret"' } } });
  for (const secret of ["private-secret", "client-secret", "query-secret", "signed-secret", "basic-secret", "inline-client-secret"]) {
    assert.ok(!json.includes(secret), `export leaked ${secret}`);
  }
});

test("generation log preserves ordinary basic clothing and a literal token trigger", () => {
  const prompt = "token: walking through a garden in basic clothing.";
  const log = JSON.parse(datasetGenerationLog({ draft: { subject: prompt, trigger: "token" },
    job: { kind: "dataset_understanding", error: "Authorization: Basic abc-secret" } }));
  assert.equal(log.settings.subject, prompt);
  assert.ok(!log.job.error.includes("abc-secret"));
});

test("diagnostic export omits raw content from private transport traces", () => {
  const context = { draft: { subject: "Approved premise" },
    job: { kind: "dataset_v2_scenes", llm_trace: { private_content: true, stage: "dataset_v2:scenes", messages: [{ role: "system",
      content: "SYNTHETIC_PRIVATE_RULE_LINE" }], output: "SYNTHETIC_PRIVATE_RULE_LINE", reasoning: "SYNTHETIC_PRIVATE_RULE_LINE",
      finish_reason: "SYNTHETIC_PRIVATE_RULE_LINE", parameters: { temperature: 0.7,
        response_format: { type: "json_schema", json_schema: { schema: { const: "SYNTHETIC_PRIVATE_RULE_LINE" } } } } },
    partial_responses: [{ stage: "dataset_v2:scenes", partial_text: "SYNTHETIC_PRIVATE_RULE_LINE" }] } };
  const before = structuredClone(context);
  const json = datasetGenerationLog(context);
  assert.ok(!json.includes("SYNTHETIC_PRIVATE_RULE_LINE"));
  assert.equal(JSON.parse(json).settings.subject, "Approved premise");
  assert.equal(JSON.parse(json).job.llm_trace.parameters.temperature, 0.7);
  assert.equal(JSON.parse(json).job.llm_trace.finish_reason, "other");
  assert.deepEqual(context, before);
});

function v2Result(overrides = {}) {
  const fingerprint = `sha256:${"a".repeat(64)}`;
  return { ok: true, kind: "dataset_v2_scenes", run_id: "run-42", stage: "done", complete: false, requested: 2, written: 1,
    concepts: [{ place: "harbour", camera: "low angle", lighting: "golden hour" }],
    slots: [{ slot: 1, status: "written", input: "", concept: { place: "harbour" }, stage: null, reasons: [], tries: 1 },
      { slot: 2, status: "failed", input: "", concept: null, stage: "concepts", reasons: ["answer was not JSON"], tries: 3 }],
    scenes: [{ slot: 1, actions: "two sailors greet", camera: "low angle", lighting: "golden hour" }],
    missing: [{ slot: 2, stage: "concepts", reasons: ["answer was not JSON"], tries: 3, input: "" }],
    prompts: [{ slot: 1, prompt: "sailor_token two sailors greeting at a harbour", trigger_ok: true }],
    vocabulary: { enabled: true, provided: ["scene:action.embrace"],
      selection: { enabled: true, selected: ["scene"], packs: [{ id: "core", role: "core", origin: "core", version: "1.1.0", fingerprint },
        { id: "scene", role: "selected", origin: "installed", version: "2.0.0", fingerprint }] },
      entries: [{ id: "scene:action.embrace", name: "Embrace", pack: "scene", category: "action", rating: "general", status: "feasible", source: "direct", scopes: [] }],
      ideas: [], images: [{ slot: 1, entries: ["scene:action.embrace"], ideas: [] }, { slot: 2, entries: ["scene:action.embrace"], ideas: [] }],
      excluded: [{ id: "scene:position.aerial_carry", reason: "conflict: cannot lift" }], suppressed: [],
      visual: { enabled: true, slots: [{ slot: 1, directions: { camera_angle: "visual:camera_angle.low_angle" } }] } },
    ...overrides };
}

test("generation log exports a V2 run: status, slots, scenes, prompts, failures, packs and vocabulary by image", () => {
  const recorded = { version: 1, enabled: true, selected: ["scene"], packs: v2Result().vocabulary.selection.packs };
  const context = { job: { id: "job-v2", kind: "dataset_v2_scenes", status: "succeeded", result: v2Result(), events: [{ message: "done" }] },
    run: { jobId: "job-v2", brief: { version: 9, summary: "Two sailors greet" }, vocabulary_packs: ["scene"], status: "done", result: v2Result(), error: "",
      visual_direction: { lighting: { enabled: false, variation: "auto" } } },
    runPacks: { runId: "run-42", packs: recorded, status: { exact: true, drift: [], disabled_globally: [] }, error: "" } };
  const before = structuredClone(context);
  const log = JSON.parse(datasetGenerationLog(context));
  const run = log.v2_run;
  assert.equal(run.run_id, "run-42");
  assert.equal(run.status, "done");
  assert.equal(run.brief.summary, "Two sailors greet");
  assert.equal(run.scenes[0].camera, "low angle");
  assert.equal(run.concepts.length, 1);
  assert.equal(run.prompts[0].prompt, "sailor_token two sailors greeting at a harbour");
  assert.deepEqual(run.missing[0].reasons, ["answer was not JSON"]);
  assert.equal(run.slots[1].status, "failed");
  assert.equal(run.vocabulary_retrieval.enabled, true);
  assert.equal(run.vocabulary_retrieval.selection.packs[1].fingerprint, `sha256:${"a".repeat(64)}`);
  assert.deepEqual(run.vocabulary_retrieval.images[1], { slot: 2, entries: ["scene:action.embrace"], ideas: [] });
  assert.equal(run.vocabulary_retrieval.entries[0].id, "scene:action.embrace");
  assert.match(run.vocabulary_retrieval.excluded[0].reason, /conflict/);
  assert.equal(run.vocabulary_retrieval.visual.slots[0].directions.camera_angle, "visual:camera_angle.low_angle");
  assert.deepEqual(run.vocabulary_packs.requested, ["scene"]);
  assert.deepEqual(run.visual_direction_settings, { lighting: { enabled: false, variation: "auto" } });
  assert.equal(run.vocabulary_packs.recorded.packs[0].id, "core");
  assert.equal(run.vocabulary_packs.status.exact, true);
  assert.equal(log.job.kind, "dataset_v2_scenes");
  assert.equal("result" in log.job, false, "the V2 result is exported once, under v2_run");
  assert.deepEqual(context, before);
});

test("a V2 job recovered without the tab's run state is still exported", () => {
  const recovered = JSON.parse(datasetGenerationLog({ job: { id: "job-v2", kind: "dataset_v2_scenes", status: "failed",
    error: "The selected vocabulary packs changed since this run was confirmed", result: v2Result({ stage: "scenes" }) } }));
  assert.equal(recovered.v2_run.status, "failed");
  assert.match(recovered.v2_run.error, /packs changed/);
  assert.equal(recovered.v2_run.vocabulary_retrieval.provided[0], "scene:action.embrace");
  assert.equal(recovered.v2_run.vocabulary_packs.recorded, null);
  const disabled = JSON.parse(datasetGenerationLog({ run: { jobId: "j", status: "done", result: v2Result({
    vocabulary: { enabled: false, provided: [], reason: "turned off in config.json", selection: null } }) } }));
  assert.equal(disabled.v2_run.vocabulary_retrieval.enabled, false);
  assert.match(disabled.v2_run.vocabulary_retrieval.reason, /turned off/);
});

test("V2 exports keep redaction: credentials in run errors, briefs and pack status never leak", () => {
  const text = datasetGenerationLog({ run: { jobId: "j", status: "failed", error: "Authorization: Bearer run-secret-789",
    brief: { summary: "A harbour", api_key: "brief-secret" }, result: v2Result({ debug: "token=result-secret" }) },
    runPacks: { packs: null, status: null, error: "https://user:pass@example.test/x?api_key=pack-secret" } });
  for (const secret of ["run-secret-789", "brief-secret", "user:pass", "pack-secret"]) assert.ok(!text.includes(secret), secret);
  assert.ok(!text.includes("description"), "no pack wording is exported");
});
