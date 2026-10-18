import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { orderDisplayPresets, presetDisplayLabel } from "./presetPresentation.js";

// Read the real catalog so new or missing built-ins cannot silently escape coverage.
const presets = JSON.parse(execFileSync("python", ["-c",
  "import json; from goated_prompter.presets import DIRECTOR_PRESETS; print(json.dumps([p.to_public_mapping() for p in DIRECTOR_PRESETS]))",
], { cwd: new URL("../../", import.meta.url), encoding: "utf8" }));

test("all built-in display titles follow the requested order without mutating the catalog", () => {
  const original = structuredClone(presets);
  presets.forEach(Object.freeze);
  Object.freeze(presets);
  const displayed = orderDisplayPresets(presets);
  assert.deepEqual(displayed.map(presetDisplayLabel), [
    "General", "Polish a Rough Prompt", "Technical Precision",
    "Recreate a Reference Image", "Describe Facial Features", "Describe Face & Body",
    "Combine Reference Images", "Edit Only the Requested Details", "Krea 2 Identity Edit v1.2 (Community)",
    "Change the Visual Style", "Krea 2 Precision", "Krea 2 Match Reference Pose",
    "Front-Camera Selfie", "Mirror Selfie", "First-Person View", "Fashion & Styling",
    "Boudoir & Intimate", "Character Focus", "Architecture & Interiors", "Product Focus",
    "Dataset & LoRA Caption", "Video Action & Camera Movement", "MiniMax H3", "Explicit Adult",
  ]);
  assert.deepEqual(presets, original);
  for (const item of displayed) assert.equal(item, presets.find((p) => p.id === item.id));
  for (const id of ["krea_2_identity_edit", "fashion_editorial", "character_director"]) {
    const item = presets.find((p) => p.id === id);
    assert.equal(presetDisplayLabel(item), item.label);
  }
});

test("custom labels and order survive after built-ins, including canonical-looking names", () => {
  const custom = [
    { id: "user:z", source: "user", label: "General Director" },
    { id: "general_director", source: "user", label: "My custom name" },
    { id: "user:a", source: "user", label: "Photography Director" },
  ].map(Object.freeze);
  const unknown = Object.freeze({ id: "future_builtin", source: "builtin", label: "Future preset" });
  const input = Object.freeze([custom[0], unknown, ...presets, ...custom.slice(1)]);
  const displayed = orderDisplayPresets(input);
  assert.deepEqual(displayed.slice(-3), custom);
  assert.deepEqual(displayed.slice(-3).map(presetDisplayLabel), custom.map((p) => p.label));
  // Unlisted built-ins follow the listed ones and still precede user presets.
  assert.ok(displayed.indexOf(unknown) < displayed.indexOf(custom[0]));
  assert.ok(displayed.indexOf(unknown) > displayed.findIndex((p) => p.id === "nsfw_director"));
  assert.equal(presetDisplayLabel(unknown), "Future preset");
});
