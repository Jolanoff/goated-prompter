import test from "node:test";
import assert from "node:assert/strict";
import { datasetCopyText, datasetJsonl, datasetGenerationLog } from "./workflows/datasetExport.js";

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

test("Dataset JSONL preserves index, original input, idea, scene and final prompt", () => {
  const draft = { trigger: "token", target: "Qwen Image", results: [
    { index: 1, input: "reading", idea: "Reading on a red couch", scene: 'Sitting on a red couch reading a "book".', prompt: "Final\nprompt." },
    { index: 2, input: "", idea: "Chasing spilled groceries", scene: "Chasing rolling oranges.", prompt: "Second prompt." },
  ] };
  const rows = datasetJsonl(draft).split("\n").map(JSON.parse);
  assert.equal(rows.length, 2);
  for (const [position, row] of rows.entries()) {
    for (const key of ["index", "input", "idea", "scene", "prompt"]) assert.equal(row[key], draft.results[position][key]);
    assert.equal(row.target, draft.target);
    assert.equal(row.trigger, draft.trigger);
  }
});

test("legacy Dataset exports distinguish missing originating scenes", () => {
  const row = JSON.parse(datasetJsonl({ results: [{ index: 1, input: "", prompt: "Old prompt" }] }));
  assert.equal(row.scene, null);
  assert.equal(row.idea, null);
  assert.equal(row.input, "");
  assert.equal(datasetJsonl(null), "");
});

test("Dataset exports omit retired coverage metadata from legacy results", () => {
  const row = JSON.parse(datasetJsonl({ results: [
    { index: 1, input: "", prompt: "Saved prompt", coverage_conflicts: ["framing"] },
  ] }));
  assert.equal(row.prompt, "Saved prompt");
  assert.equal("coverage_conflicts" in row, false);
});

test("generation log omits retired style and variety settings in legacy drafts and reviews", () => {
  const input = { subject: "A portrait", source_mode: "guided", inputs: "Reading", variety: "Wide",
    visual_style: "Custom", custom_style: "RETIRED STYLE" };
  const before = structuredClone(input);
  const log = JSON.parse(datasetGenerationLog({ draft: input, review: { input } }));
  for (const settings of [log.settings, log.understanding.input]) {
    assert.equal(settings.subject, "A portrait");
    assert.equal(settings.source_mode, "guided");
    assert.equal(settings.inputs, "Reading");
    for (const field of ["variety", "visual_style", "custom_style"]) assert.equal(field in settings, false);
  }
  assert.deepEqual(input, before);
});

test("generation log is an indented snapshot of settings, review, progress and failures without mutations", () => {
  const context = {
    draft: { subject: "Duck confronting a dinosaur", trigger: "duck_token", amount: 2, target: "Generic",
      scene_plan: [{ index: 1, idea: "Confrontation", scene_status: "failed", failure_stage: "scene",
        failure_reason: "Timeout", retry_count: 2 }], results: [{ index: 2, prompt: "duck_token confronts a dinosaur" }] },
    review: { operation: "dataset", status: "ready", jobId: "understanding-1",
      input: { subject: "Duck confronting a dinosaur", constraints: "Both visible" },
      brief: { requested_generation: "A confrontation", rules: [{ scope: "all_outputs", text: "Both visible" }] } },
    job: { id: "dataset-1", kind: "dataset", status: "failed", error: "Timeout", revision: 3,
      result: { failed: 1, completed: 1, attempts: 3 }, events: [{ type: "error", message: "Timeout" }],
      llm_trace: { request_number: 4, output: "Partial result", parameters: { temperature: 0.7, max_tokens: 512 } },
      partial_responses: [{ partial_text: "Partial result", completion_state: "timeout" }] },
    record: { revision: 7, checkpoint: { job_id: "dataset-1" }, scene_eligibility: { 1: { usable: false } } },
    state: { error: "Dataset generation failed. Timeout", active: false },
  };
  const before = structuredClone(context);
  const json = datasetGenerationLog(context, new Date("2026-10-07T12:00:00Z"));
  const log = JSON.parse(json);
  assert.match(json, /\n {2}"settings": \{/);
  assert.equal(log.exported_at, "2026-10-07T12:00:00.000Z");
  assert.equal(log.dataset_idea, context.draft.subject);
  assert.equal(log.settings.target, "Generic");
  assert.deepEqual(log.scene_plan, context.draft.scene_plan);
  assert.deepEqual(log.generated_prompts, context.draft.results);
  assert.deepEqual(log.understanding.brief, context.review.brief);
  assert.deepEqual(log.job.partial_responses, context.job.partial_responses);
  assert.equal(log.job.result.attempts, 3);
  assert.equal(log.metadata.revision, 7);
  assert.equal(log.state.error, context.state.error);
  assert.deepEqual(context, before);
});

test("generation log excludes credentials, sensitive configuration and embedded secrets but keeps token usage", () => {
  const log = datasetGenerationLog({ draft: { subject: "An animal", trigger: "animal_token", api_key: "sk-setting-secret", results: [] },
    review: { confirmation_token: "review-secret-123", brief: { requested_generation: "An animal" } },
    job: { kind: "dataset", id: "job", status: "failed", config: { password: "config-secret" },
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
  assert.deepEqual(empty.scene_plan, []);
  assert.deepEqual(empty.generated_prompts, []);
  assert.equal(empty.understanding, null);
  assert.equal(empty.job, null);
  const running = JSON.parse(datasetGenerationLog({ job: { kind: "dataset_scenes", status: "running", result: null } }));
  assert.equal(running.job.status, "running");
  assert.equal(running.job.result, null);
  const unrelated = JSON.parse(datasetGenerationLog({ job: { kind: "builder", result: { prompt: "Unrelated private prompt" } } }));
  assert.equal(unrelated.job, null);
});

test("credential redaction preserves training triggers ending in token followed by prompt text", () => {
  const prompt = "duck_token: mock scene, access_token_duck on a pond";
  const log = JSON.parse(datasetGenerationLog({ draft: { trigger: "duck_token", results: [{ index: 1, prompt }] } }));
  assert.equal(log.generated_prompts[0].prompt, prompt);
});

test("generation log redacts signed URL queries, Basic authorization and private credentials", () => {
  const json = datasetGenerationLog({ job: { kind: "dataset", result: { private_key: "private-secret", client_secret: "client-secret" },
    error: 'https://example.test/failed?key=query-secret&X-Amz-Signature=signed-secret; Authorization: Basic basic-secret',
    llm_trace: { output: 'client_secret="inline-client-secret"' } } });
  for (const secret of ["private-secret", "client-secret", "query-secret", "signed-secret", "basic-secret", "inline-client-secret"]) {
    assert.ok(!json.includes(secret), `export leaked ${secret}`);
  }
});

test("generation log preserves ordinary basic clothing and a literal token trigger", () => {
  const prompt = "token: walking through a garden in basic clothing.";
  const log = JSON.parse(datasetGenerationLog({ draft: { subject: prompt, trigger: "token",
    results: [{ index: 1, prompt }] }, job: { kind: "dataset", error: "Authorization: Basic abc-secret" } }));
  assert.equal(log.settings.subject, prompt);
  assert.equal(log.generated_prompts[0].prompt, prompt);
  assert.ok(!log.job.error.includes("abc-secret"));
});
