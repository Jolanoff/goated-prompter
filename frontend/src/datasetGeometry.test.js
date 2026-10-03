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

test("geometry debugging renders independent camera axes and nonhuman staging without human fields", () => {
  const geometry = { camera_azimuth: "front_three_quarter_left", camera_elevation: "eye_level",
    camera_distance: "full", subject_orientation: "front_three_quarter_left", framing: "full_subject",
    composition: "centered", visibility_focus: ["product label"] };
  assert.deepEqual(geometryRows(geometry), [
    { label: "camera azimuth", value: "front three quarter left" },
    { label: "camera elevation", value: "eye level" },
    { label: "camera distance", value: "full" },
    { label: "subject orientation", value: "front three quarter left" },
    { label: "framing", value: "full subject" },
    { label: "composition", value: "centered" },
    { label: "visibility focus", value: "product label" },
  ]);
  assert.equal(geometry.camera_azimuth, "front_three_quarter_left");
});
