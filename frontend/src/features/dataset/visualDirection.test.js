import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileView } from "../vocabulary/testSupport.js";
import { datasetConfirmationPayload } from "./datasetState.js";
import { VISUAL_KEY, defaultVisualDirection, normalizeVisualDirection, readStoredVisual, updateVisualDirection,
  visualDirectionSummary, writeStoredVisual } from "./visualDirection.js";

const Controls = (await import(await compileView(new URL("./VisualDirectionControls.jsx", import.meta.url)))).default;

test("settings default to every dimension on and automatic, and unknown values never pass", () => {
  const settings = defaultVisualDirection();
  assert.deepEqual(Object.keys(settings), ["framing", "camera_angle", "composition", "lighting", "atmosphere"]);
  assert.ok(Object.values(settings).every((item) => item.enabled && item.variation === "auto"));
  const odd = normalizeVisualDirection({ lighting: { enabled: false, variation: "wild", extra: 1 }, mood: { enabled: true } });
  assert.deepEqual(odd.lighting, { enabled: false, variation: "auto" });
  assert.equal("mood" in odd, false);
  const changed = updateVisualDirection(settings, "framing", { variation: "same" });
  assert.equal(changed.framing.variation, "same");
  assert.equal(settings.framing.variation, "auto", "updates never mutate");
});

test("controls render one toggle and variation per dimension; a dimension that is off disables its variation", () => {
  const settings = updateVisualDirection(defaultVisualDirection(), "lighting", { enabled: false });
  const markup = renderToStaticMarkup(createElement(Controls, { settings, onChange: () => {}, packAvailable: false }));
  for (const label of ["Framing", "Camera angle", "Composition", "Lighting", "Atmosphere"]) {
    assert.match(markup, new RegExp(`aria-label="Visual direction: ${label}"`));
    assert.match(markup, new RegExp(`aria-label="${label} variation"`));
  }
  assert.match(markup, /aria-label="Lighting variation"[^>]*disabled=""/);
  assert.doesNotMatch(markup, /aria-label="Framing variation"[^>]*disabled=""/);
  assert.match(markup, /Select the Visual Direction pack/);
  assert.match(markup, /subjects and actions never change/);
});

test("the review dialog summary and the confirm payload carry the frozen settings", () => {
  const settings = updateVisualDirection(updateVisualDirection(defaultVisualDirection(), "framing", { variation: "same" }),
    "atmosphere", { enabled: false });
  assert.equal(visualDirectionSummary(settings), "Framing (same for every image), Camera angle, Composition, Lighting");
  assert.equal(visualDirectionSummary(Object.fromEntries(Object.keys(settings).map((id) => [id, { enabled: false, variation: "auto" }]))), "Off");
  const review = { brief: {}, input: {}, operation: "dataset", confirmation_token: "t", vocabulary_packs: ["visual"], visual_direction: settings };
  const payload = datasetConfirmationPayload(review);
  assert.deepEqual(payload.visual_direction, settings);
  assert.notEqual(payload.visual_direction, settings, "a copy, so later edits cannot change a confirmed run");
  assert.equal("visual_direction" in datasetConfirmationPayload({ ...review, visual_direction: undefined }), false);
});

test("settings are remembered per browser and survive unavailable storage", () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(readStoredVisual(storage), null);
  writeStoredVisual(updateVisualDirection(defaultVisualDirection(), "camera_angle", { enabled: false }), storage);
  assert.equal(readStoredVisual(storage).camera_angle.enabled, false);
  values.set(VISUAL_KEY, "{broken");
  assert.equal(readStoredVisual(storage), null);
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(readStoredVisual(blocked), null);
  assert.doesNotThrow(() => writeStoredVisual(defaultVisualDirection(), blocked));
});
