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
    "General-Purpose Prompt", "Polish a Rough Prompt", "Detailed Scene Description",
    "Recreate a Reference Image", "Describe Facial Features", "Describe Face & Body",
    "Combine Reference Images", "Edit Only the Requested Details", "Krea 2 Identity Edit",
    "Change the Visual Style", "Krea 2 Detailed Prompt", "Krea 2 Match Reference Pose",
    "Photography Director", "Casual Phone Photo", "Front-Camera Selfie", "Mirror Selfie",
    "First-Person View", "Fashion Photography", "Vintage Film Photography",
    "Boudoir Photography", "Krea 2 Phone Photo", "Character Director",
    "Architecture & Interiors", "Product Photography", "Dataset & LoRA Caption",
    "Video Action & Camera Movement", "MiniMax H3 Video Shot",
    "Anime Director", "NSFW Director",
  ]);
  assert.deepEqual(presets, original);
  for (const item of displayed) assert.equal(item, presets.find((p) => p.id === item.id));
  for (const id of ["krea_2_identity_edit", "photography_director", "character_director"]) {
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
  // Unmapped built-ins retain input order and still precede user presets.
  assert.ok(displayed.indexOf(unknown) < displayed.indexOf(custom[0]));
  assert.ok(displayed.indexOf(unknown) < displayed.findIndex((p) => p.id === "anime_director"));
  assert.equal(presetDisplayLabel(unknown), "Future preset");
});
