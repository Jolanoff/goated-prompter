import test from "node:test";
import assert from "node:assert/strict";
import { geometryRows } from "./workflows/datasetGeometry.js";

test("geometry debugging separates gaze and emotion and renders canonical labels", () => {
  const geometry = { gaze_direction: "toward_action", expression: "shocked",
    pose_type: "custom", pose_detail: "one-foot balance", primary_subject_count: 1,
    visibility_focus: ["face", "falling oranges"] };
  assert.deepEqual(geometryRows(geometry), [
    { label: "gaze direction", value: "toward action" }, { label: "expression", value: "shocked" },
    { label: "pose type", value: "custom" }, { label: "pose detail", value: "one-foot balance" },
    { label: "primary subject count", value: "1" }, { label: "visibility focus", value: "face, falling oranges" },
  ]);
  assert.equal(geometry.gaze_direction, "toward_action");
  assert.deepEqual(geometryRows(), []);
});
