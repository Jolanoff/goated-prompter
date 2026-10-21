import assert from "node:assert/strict";
import test from "node:test";
import { engineAcceptsImages, engineOptionLabel, noImages } from "./engineImages.js";

test("local profiles accept images only with a matching projector", () => {
  const vision = { id: "a", label: "Vision", ready: true, vision_ready: true };
  const textOnly = { id: "b", label: "Writer", ready: true, vision_ready: false };
  assert.equal(engineAcceptsImages({ configuredBackend: false, selectedProfile: vision }), true);
  assert.equal(engineAcceptsImages({ configuredBackend: false, selectedProfile: textOnly }), false);
  assert.equal(engineOptionLabel(vision), "Vision");
  assert.equal(engineOptionLabel(textOnly), "Writer (text only)");
});

test("configured endpoints follow their declared vision flag", () => {
  const configured = (models) => engineAcceptsImages({ configuredBackend: true, models, selectedProfile: null });
  assert.equal(configured({ backend: "openai_compatible", backend_vision: false }), false);
  assert.equal(configured({ backend: "openai_compatible", backend_vision: true }), true);
  // Backends that do not declare the flag keep the previous behaviour.
  assert.equal(configured({ backend: "mock" }), true);
});

test("no engine leaves image controls unchanged and empty slots stay fixed", () => {
  assert.equal(engineAcceptsImages({ configuredBackend: false, selectedProfile: undefined }), true);
  assert.deepEqual([...noImages], [null, null, null, null]);
  assert.ok(Object.isFrozen(noImages));
});
