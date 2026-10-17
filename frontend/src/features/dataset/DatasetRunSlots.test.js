import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Children } from "react";
import { transformWithEsbuild } from "vite";

async function loadPages() {
  const sourceUrl = new URL("./DatasetRunPages.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  return import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`);
}

function elements(element) {
  if (!element?.props) return [];
  return [element, ...Children.toArray(element.props.children).flatMap(elements)];
}

const scene = (slot) => ({ slot, subjects: { Alex: { skin: "s", build: "b", hair: "h", detail: "d", clothing: "c" } },
  actions: `reads at location${slot}`, position: { Alex: "seated" }, space: `location${slot}`,
  lighting: "day", mood: "calm", camera: "wide", extras: "books" });
const record = (slot, status, extra = {}) => ({ slot, status, input: `input ${slot}`, concept: null, stage: null,
  reasons: [], tries: 1, ...extra });

// Image 2 failed in description; image 4's final prompt failed in Builder.
const partial = {
  complete: false, requested: 4, written: 3,
  missing: [{ slot: 2, stage: "description", reasons: ["an answer was missing"], tries: 3, input: "input 2" }],
  slots: [record(1, "written"), record(2, "failed", { stage: "description", reasons: ["an answer was missing"] }),
    record(3, "written"), record(4, "written")],
  scenes: [scene(1), scene(3), scene(4)],
  prompts: [{ slot: 1, index: 1, prompt: "Prompt from location1.", trigger_ok: true },
    { slot: 3, index: 3, prompt: "Prompt from location3.", trigger_ok: true },
    { slot: 4, index: 4, prompt: "", trigger_ok: false, error: "loop" }],
};

test("slot records keep each image's own scene, prompt, input and status", async () => {
  const { runSlots } = await loadPages();
  const records = runSlots(partial);
  assert.deepEqual(records.map(({ slot, status }) => [slot, status]),
    [[1, "written"], [2, "failed"], [3, "written"], [4, "written"]]);
  assert.equal(records[1].scene, null);
  assert.equal(records[1].prompt, null);
  assert.equal(records[1].input, "input 2");
  assert.equal(records[2].scene.space, "location3");
  assert.equal(records[2].prompt.prompt, "Prompt from location3.");
  assert.equal(records[3].prompt.error, "loop");
});

test("results without slot records fall back to item slots, then positions", async () => {
  const { runSlots } = await loadPages();
  const legacy = { scenes: [scene(1), scene(3)], prompts: [{ index: 1, prompt: "a" }, { index: 3, prompt: "c" }],
    missing: [{ slot: 2, stage: "staging", reasons: ["x"] }] };
  assert.deepEqual(runSlots(legacy).map(({ slot, status }) => [slot, status]), [[1, "written"], [2, "failed"], [3, "written"]]);
  const positional = { scenes: [{ space: "a" }, { space: "b" }], prompts: [{ prompt: "one" }, { prompt: "two" }] };
  assert.deepEqual(runSlots(positional).map((row) => [row.slot, row.scene.space, row.prompt.prompt]), [[1, "a", "one"], [2, "b", "two"]]);
  assert.deepEqual(runSlots(null), []);
});

test("the Dataset page pairs each prompt with its own image after a failed middle image", async () => {
  const { RunPrompts } = await loadPages();
  const page = RunPrompts({ run: { status: "done", result: partial }, onCopy: () => {}, onDownload: () => {} });
  const cards = elements(page).filter((element) => element.type === "article");
  assert.deepEqual(cards.map((card) => card.props["aria-label"]), ["Image 1", "Image 2", "Image 3", "Image 4"]);
  const third = elements(cards[2]);
  assert.equal(third.find((element) => element.type === "textarea").props.value, "Prompt from location3.");
  assert.equal(third.find((element) => element.props?.scene)?.props.scene.space, "location3");
  assert.equal(elements(cards[1]).some((element) => element.type === "textarea"), false, "a failed image has no prompt box");
});

test("the Scenes page shows failed images in place without renumbering", async () => {
  const { RunScenes } = await loadPages();
  const page = RunScenes({ run: { status: "done", result: partial }, onCopy: () => {}, onDownload: () => {} });
  const cards = elements(page).filter((element) => element.type === "article");
  assert.deepEqual(cards.map((card) => card.props["aria-label"]), ["Image 1", "Image 2", "Image 3", "Image 4"]);
  assert.equal(elements(cards[3]).find((element) => element.props?.scene)?.props.scene.space, "location4");
  assert.ok(elements(cards[1]).find((element) => element.props?.record)?.props.record.stage === "description");
});

test("partial TXT, Copy all and JSON exports keep slots and never write blank prompts", async () => {
  const { RunPrompts, writtenPrompts } = await loadPages();
  assert.deepEqual(writtenPrompts(partial).map((item) => item.slot), [1, 3]);
  const run = { status: "done", brief: { version: 9 }, result: partial };
  const before = structuredClone(run);
  const downloads = [];
  let copied;
  const page = RunPrompts({ run, onCopy: (text) => { copied = text; }, onDownload: (...args) => downloads.push(args) });
  const buttons = elements(page).filter((element) => element.type === "button");
  const click = (label) => buttons.find((button) => Children.toArray(button.props.children).includes(label)).props.onClick();
  click("Copy all");
  assert.equal(copied, "Prompt from location1.\nPrompt from location3.");
  click("TXT");
  assert.deepEqual(downloads[0], ["dataset-prompts.txt", "Prompt from location1.\n\nPrompt from location3.", "text/plain;charset=utf-8"]);
  click("JSON");
  const exported = JSON.parse(downloads[1][1]);
  assert.deepEqual(exported.slots.map((row) => [row.slot, row.status, row.input]),
    [[1, "written", "input 1"], [2, "failed", "input 2"], [3, "written", "input 3"], [4, "written", "input 4"]]);
  assert.deepEqual(exported.scenes.map((row) => row.slot), [1, 3, 4]);
  assert.deepEqual(exported.prompts.map((row) => row.slot), [1, 3, 4]);
  assert.deepEqual(run, before, "exports never change the run");
});

test("incomplete-run notice names images by slot", async () => {
  const { RunPrompts } = await loadPages();
  const page = RunPrompts({ run: { status: "done", result: partial }, onCopy: () => {}, onDownload: () => {} });
  const notes = elements(page).find((element) => element.props?.run);
  const rendered = notes.type(notes.props);
  const text = JSON.stringify(elements(rendered).map((element) => element.props?.children));
  assert.match(text, /image 2/);
  assert.doesNotMatch(text, /concept 2/);
});

test("prompt failures are reported separately from completed scenes", async () => {
  const { RunPrompts } = await loadPages();
  const result = { ...partial, requested: 3, written: 3, missing: [],
    prompt_summary: { written: 0, missing: [1, 2, 3] } };
  const page = RunPrompts({ run: { status: "error", result }, onCopy: () => {}, onDownload: () => {} });
  const notes = elements(page).find((element) => element.props?.run);
  const rendered = notes.type(notes.props);
  const text = JSON.stringify(elements(rendered).map((element) => element.props?.children));
  assert.match(text, /final prompts written/);
  assert.match(text, /image 1, image 2, image 3/);
  assert.doesNotMatch(text, /scenes written/);
});
