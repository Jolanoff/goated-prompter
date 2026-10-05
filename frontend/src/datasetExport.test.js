import test from "node:test";
import assert from "node:assert/strict";
import { datasetCopyText, datasetJsonl } from "./workflows/datasetExport.js";

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
