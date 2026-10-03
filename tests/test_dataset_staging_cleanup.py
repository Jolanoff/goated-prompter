"""Deterministic staging corrections and strict profile/semantic boundaries."""

import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import (
    GeometryValidationError, STAGING_PROFILES, geometry_enum_values, geometry_issues,
    geometry_prompt_schema, migrate_saved_geometry, normalize_staging, validate_geometry,
)
from goated_prompter.dataset_staging.vocabulary import GAZE_DIRECTION_VALUES
from goated_prompter.prompting.scene_planner import SCENE_PLANNER_SYSTEM
from goated_prompter.scene_planner import ScenePlanner
from tests.test_dataset_geometry import character_geometry
from tests.test_dataset_quality_planning import draft


class StagingCleanupTests(unittest.TestCase):
    def test_framing_aliases_do_not_request_model_repair_in_either_mode(self):
        for mode in ("Fast", "Quality"):
            for raw, expected in (("medium", "waist_up"), (" medium-shot ", "waist_up"),
                                  ("medium_full", "three_quarter_body")):
                with self.subTest(mode=mode, raw=raw):
                    data, session = draft(amount=1, planning_mode=mode), Mock()
                    row = {"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon.",
                           "geometry": character_geometry(framing=raw, camera_distance="medium", visibility_focus=["ribbon"])}
                    outputs = [json.dumps([row])]
                    if mode == "Quality":
                        outputs.insert(0, json.dumps([{"index": 1, "idea": row["idea"]}]))
                    session.generate.side_effect = outputs
                    result = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                        assignments=dataset_assignments(data), progress=lambda _: None)
                    self.assertEqual(result[0]["geometry"]["framing"], expected)
                    self.assertEqual(result[0]["geometry"]["camera_distance"], "medium")
                    self.assertEqual(result[0]["idea"], row["idea"])
                    self.assertEqual(result[0]["scene"], row["scene"])
                    self.assertEqual(session.generate.call_count, len(outputs))

    def test_obvious_emotion_and_head_states_move_without_inventing_gaze(self):
        for raw, field, expected in (("Ecstatic", "expression", "ecstatic"),
                                     ("shocked", "expression", "shocked"),
                                     ("eyes rolled", "head_direction", "eyes_rolled")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_staging({"gaze_direction": raw}, dataset_type="Character"), {field: expected})
                self.assertNotIn(expected, GAZE_DIRECTION_VALUES)
        geometry = character_geometry(gaze_direction="ecstatic", expression="ecstatic")
        with self.assertRaisesRegex(GeometryValidationError, "missing: gaze_direction") as caught:
            validate_geometry(geometry, dataset_type="Character")
        self.assertIn("Keep the same scene and action", caught.exception.correction)
        for existing in ("neutral", "shocked"):
            original = {"gaze_direction": "ecstatic", "expression": existing}
            self.assertEqual(normalize_staging(original, dataset_type="Character"), original)
            with self.assertRaises(GeometryValidationError):
                validate_geometry(original, dataset_type="Character", require_fields=False)

    def test_explicit_scene_gaze_can_avoid_repair_but_ambiguous_prose_cannot(self):
        raw = {"gaze_direction": "ecstatic"}
        for scene in ("She looks ahead.", "She is not looking at the camera.",
                      "She is looking at the camera with eyes closed.",
                      "She is looking at the camera through a mirror."):
            self.assertNotIn("gaze_direction", normalize_staging(raw, dataset_type="Character", scene=scene))
        expected = {"expression": "ecstatic", "gaze_direction": "toward_camera"}
        self.assertEqual(normalize_staging(raw, dataset_type="Character", scene="She is looking at the camera."), expected)
        data, session = draft(amount=1, planning_mode="Fast"), Mock()
        row = {"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon while looking at the camera.",
               "geometry": character_geometry(gaze_direction="ecstatic", expression="ecstatic", head_direction="toward_camera")}
        session.generate.return_value = json.dumps([row])
        result = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(result[0]["geometry"]["gaze_direction"], "toward_camera")
        self.assertEqual(session.generate.call_count, 1)

    def test_unknown_emotional_gaze_repairs_only_affected_scene_and_preserves_idea(self):
        data, session = draft(amount=2), Mock()
        rows = [{"index": i, "idea": f"Displaying ribbon {i}", "scene": f"She displays ribbon {i}.",
                 "geometry": character_geometry()} for i in (1, 2)]
        bad = {**rows[0], "geometry": {**rows[0]["geometry"], "gaze_direction": "intense pleasure"}}
        session.generate.side_effect = [json.dumps([bad, rows[1]]), json.dumps([rows[0]])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data,
            assignments=dataset_assignments(data), ideas=[{"index": r["index"], "idea": r["idea"]} for r in rows],
            progress=lambda _: None)
        self.assertEqual(result, rows)
        self.assertEqual(session.generate.call_count, 2)
        repair = session.generate.call_args_list[1].args[0]
        self.assertEqual(repair.diagnostic_stage, "dataset:scene_composer:repair")
        self.assertIn("not an emotion or facial expression", repair.system_message)
        assignments = json.loads(repair.user_message)["assignments"]
        self.assertEqual([(r["index"], r["idea"]) for r in assignments], [(1, rows[0]["idea"])])

    def test_valid_gaze_values_are_never_changed(self):
        for value in GAZE_DIRECTION_VALUES:
            geometry = {"gaze_direction": value}
            self.assertEqual(normalize_staging(geometry, dataset_type="Character", scene="Looking at the camera."), geometry)

    def test_profiles_constrain_both_validation_and_schema_values(self):
        for kind, profile in STAGING_PROFILES.items():
            advertised = geometry_enum_values(kind)
            self.assertEqual(set(advertised["framing"]), profile.values_for("framing"))
            self.assertNotIn("medium", advertised["framing"])
            self.assertIn("medium", advertised["camera_distance"])
        for forbidden in ("head_and_shoulders", "waist_up", "full_body", "medium"):
            with self.subTest(framing=forbidden), self.assertRaises(GeometryValidationError):
                validate_geometry({"framing": forbidden}, dataset_type="Object / product")
        self.assertNotIn("subject_orientation", STAGING_PROFILES["Character"].allowed)
        for name in ("pelvis_tilt", "back_arch", "leg_position", "body_orientation"):
            self.assertNotIn(name, STAGING_PROFILES["Custom"].allowed)
        schema = geometry_prompt_schema("Character")
        self.assertIn("Which portion of the subject/image content", schema)
        self.assertIn("How physically near or far the camera", schema)
        self.assertIn("Supported head/eye-position states", schema)
        self.assertNotIn("BODY AND POSE LOGIC", SCENE_PLANNER_SYSTEM)
        self.assertIn("use only the staging fields supplied for that Dataset type", SCENE_PLANNER_SYSTEM)

    def test_value_overrides_apply_to_any_registered_enum_not_only_framing(self):
        profile = replace(STAGING_PROFILES["Custom"], value_overrides={"camera_distance": frozenset({"long"})})
        with patch.dict(STAGING_PROFILES, {"Custom": profile}):
            self.assertEqual(geometry_enum_values("Custom")["camera_distance"], ["long"])
            self.assertEqual(validate_geometry({"camera_distance": "long"}, dataset_type="Custom"), {"camera_distance": "long"})
            with self.assertRaisesRegex(GeometryValidationError, "Invalid camera_distance"):
                validate_geometry({"camera_distance": "medium"}, dataset_type="Custom")

    def test_old_nonhuman_framing_migrates_only_equivalent_extents(self):
        self.assertEqual(migrate_saved_geometry({"framing": "full_body_with_environment"}, dataset_type="Object / product"),
                         ({"framing": "full_subject_with_environment"}, False))
        self.assertEqual(migrate_saved_geometry({"framing": "head_and_shoulders"}, dataset_type="Object / product"), ({}, True))
        self.assertEqual(migrate_saved_geometry({"gaze_direction": "ecstatic", "expression": "neutral"}),
                         ({"expression": "neutral"}, True))
        human = character_geometry(framing="full_subject")
        migrated, warning = migrate_saved_geometry(human, dataset_type="Character")
        self.assertEqual(migrated, {**human, "framing": "full_body"})
        self.assertFalse(warning)

    def test_group_checks_are_scene_level_and_conservative(self):
        geometry = {"framing": "detail_close_up", "camera_azimuth": "front", "composition": "centered",
                    "primary_subject_count": 3, "action_visibility": "clear"}
        row = {"idea": "Show exactly 2 people, the whole group", "geometry": geometry}
        self.assertEqual({p.code for p in geometry_issues(row, "Multiple characters")}, {"group_count_conflict", "group_crop_conflict"})
        row = {"idea": "Two people holding hands", "geometry": {**geometry, "framing": "full_subject", "occlusion": "major"}}
        self.assertIn("group_interaction_occluded", {p.code for p in geometry_issues(row, "Multiple characters")})
        row = {"idea": "A group portrait", "geometry": {**geometry, "framing": "full_subject", "occlusion": "minor"}}
        self.assertFalse(geometry_issues(row, "Multiple characters"))


if __name__ == "__main__":
    unittest.main()
