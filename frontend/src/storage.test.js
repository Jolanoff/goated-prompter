import { test } from "node:test";
import assert from "node:assert/strict";
import {
  loadSaved,
  inputDefaults,
  SAVED_KEY,
  hydrateBuilder,
  builderSnapshot,
  createBuilderSaver,
  referenceAttributes,
} from "./storage.js";

function storage() {
  const data = new Map();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
  };
}

test("legacy reader preserves exact text without modifying browser data", () => {
  const local = storage();
  const records = [
    {
      id: "one",
      title: "Portrait",
      prompt: "  text\n",
      createdAt: new Date().toISOString(),
    },
  ];
  assert.deepEqual(loadSaved(local), []);
  local.setItem(SAVED_KEY, JSON.stringify(records));
  assert.deepEqual(loadSaved(local), records);
  assert.equal(local.getItem(SAVED_KEY), JSON.stringify(records));
});

test("malformed storage is not silently discarded", () => {
  const local = storage();
  local.setItem(SAVED_KEY, "[{}]");
  assert.throws(() => loadSaved(local));
  assert.equal(local.getItem(SAVED_KEY), "[{}]");
});

test("inaccessible legacy storage propagates a read failure", () => {
  assert.throws(() =>
    loadSaved({
      getItem() {
        throw new Error("Access denied");
      },
    }),
  );
});

test("defaults preserve false and numeric schema values", () => {
  assert.deepEqual(
    inputDefaults({
      mode: [["Enhance"], {}],
      preserve: ["BOOLEAN", { default: false }],
      tokens: ["INT", { default: 768 }],
    }),
    { mode: "Enhance", preserve: false, tokens: 768 },
  );
});

test("builder hydration normalizes Maximum and excludes images, runtime and preserve defaults", () => {
  const result = hydrateBuilder(
    {
      idea: ["STRING", { default: "default" }],
      preserve_subject: ["BOOLEAN", { default: true }],
      reference_subject_source: [["Auto"], {}],
    },
    {
      idea: "draft",
      prompt_length: "Maximum",
      generated_prompt: " exact\n",
      lock_generated_prompt: true,
      images: ["bytes"],
      selected_profile: "engine",
    },
  );
  assert.equal(result.idea, "draft");
  assert.equal(result.prompt_length, "Maximum Detail");
  for (const key of referenceAttributes)
    assert.equal(result[`reference_${key}_source`], "Off");
  assert.equal(result.generated_prompt, " exact\n");
  assert.equal(Object.hasOwn(result, "lock_generated_prompt"), false);
  assert.equal(Object.hasOwn(result, "images"), false);
  assert.equal(Object.hasOwn(result, "selected_profile"), false);
  assert.equal(Object.hasOwn(result, "preserve_subject"), false);
  assert.deepEqual(
    builderSnapshot({ image_1_role: "Auto", filenames: ["x"] }),
    {},
  );
});

test("autosave serializes writes, coalesces edits, and retries the latest failed draft", async () => {
  const writes = [],
    statuses = [];
  let release;
  let fail = false;
  const saver = createBuilderSaver(
    async (snapshot) => {
      writes.push(snapshot);
      if (writes.length === 1)
        await new Promise((resolve) => {
          release = resolve;
        });
      if (fail) throw new Error("Offline");
    },
    (status) => statuses.push(status),
    10000,
  );
  saver.hydrate({ idea: "initial" });
  await saver.flush();
  assert.equal(writes.length, 0);
  saver.stage({ idea: "first" });
  const pending = saver.flush();
  saver.stage({ idea: "second" });
  saver.stage({ idea: "latest" });
  assert.equal(writes.length, 1);
  release();
  await pending;
  assert.deepEqual(writes, [{ idea: "first" }, { idea: "latest" }]);
  fail = true;
  saver.stage({ idea: "offline draft" });
  await assert.rejects(saver.flush(), /Offline/);
  assert.equal(statuses.at(-1), "Save failed");
  fail = false;
  await saver.flush();
  assert.deepEqual(writes.at(-1), { idea: "offline draft" });
  assert.equal(statuses.at(-1), "Saved");
  saver.dispose();
});

test("director hydration resolves legacy labels and defaults to stable IDs without hidden overrides", () => {
  const library = {
    default: "General Director",
    presets: [
      { id: "general", label: "General Director" },
      { id: "photo", label: "Photography Director" },
    ],
  };
  const inputs = {
    director_preset: [["General Director"], {}],
    mode: [["Enhance"], {}],
    system_prompt_override: ["STRING", { default: "hidden" }],
  };
  for (const [saved, id] of [
    [{}, "general"],
    [{ director_preset: "Photography Director" }, "photo"],
    [{ director_preset: "photo" }, "photo"],
    [{ director_preset: "deleted" }, "general"],
  ]) {
    const result = hydrateBuilder(
      inputs,
      { ...saved, mode: "Custom", system_prompt_override: "old draft" },
      library,
    );
    assert.equal(result.director_preset, id);
    assert.equal(result.mode, "Custom");
    assert.equal(Object.hasOwn(result, "system_prompt_override"), false);
    assert.deepEqual(builderSnapshot(result), result);
  }
});

test("reverting a pending edit returns autosave to Saved without a write", async () => {
  const statuses = [];
  let writes = 0;
  const saver = createBuilderSaver(
    async () => {
      writes += 1;
    },
    (status) => statuses.push(status),
    10000,
  );
  saver.hydrate({ idea: "original" });
  saver.stage({ idea: "changed" });
  saver.stage({ idea: "original" });
  await saver.flush();
  assert.equal(writes, 0);
  assert.equal(statuses.at(-1), "Saved");
  saver.dispose();
});

test("explicit reload discards queued edits without sending them after an in-flight acknowledgement", async () => {
  const writes = [];
  let release;
  const saver = createBuilderSaver(async (snapshot) => {
    writes.push(snapshot);
    await new Promise((resolve) => { release = resolve; });
  }, () => {}, 10000);
  saver.hydrate({ base: "Saved" });
  saver.stage({ base: "In flight" });
  const pending = saver.flush();
  saver.stage({ base: "Discard this queued change" });
  const discard = saver.discard();
  release();
  await Promise.all([pending, discard]);
  saver.hydrate({ base: "Reloaded from server" });
  await saver.flush();
  assert.deepEqual(writes, [{ base: "In flight" }]);
  saver.dispose();
});
