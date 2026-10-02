"""Every canonical geometry field, legacy migration and physical compatibility."""

import unittest

from goated_prompter.dataset_geometry import (
    CHARACTER_REQUIRED_FIELDS, CUSTOM_DETAIL_FIELDS, GEOMETRY_ENUMS,
    GeometryValidationError, geometry_errors, migrate_saved_geometry, normalize_geometry_value, validate_geometry,
)


def character_geometry(**changes):
    return {"framing": "full_body", "camera_view": "front_three_quarter",
            "body_orientation": "front_three_quarter_left", "head_direction": "toward_action",
            "gaze_direction": "toward_action", "expression": "focused", "pose_type": "standing_dynamic",
            "action_focus": "juggling oranges", "face_visibility": "three_quarter",
            "hand_visibility": "both_visible", "visibility_focus": ["face", "hands", "falling oranges"], **changes}


class GeometrySchemaTests(unittest.TestCase):
    def test_every_value_of_every_enum_validates(self):
        for field, values in GEOMETRY_ENUMS.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    geometry = {field: value}
                    if value == "custom":
                        geometry[CUSTOM_DETAIL_FIELDS[field]] = "An unusual but interpretable physical state"
                    self.assertEqual(validate_geometry(geometry), geometry)

    def test_every_enum_rejects_unknown_prose_and_wrong_types(self):
        for field in GEOMETRY_ENUMS:
            for value in ("not_an_enum", "arbitrary descriptive prose", [], {}, 1, True, None):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(GeometryValidationError, f"Invalid {field}"):
                    validate_geometry({field: value})
        for field in ("framing", "camera_view", "body_orientation", "gaze_direction"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_geometry({field: "custom"})

    def test_custom_pose_and_expression_details_are_optional(self):
        for field, detail in CUSTOM_DETAIL_FIELDS.items():
            self.assertEqual(validate_geometry({field: "custom"}), {field: "custom"})
            for invalid in ({field: "custom", detail: ""}, {field: "custom", detail: "x\ny"}):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    validate_geometry(invalid)
        geometry = character_geometry(pose_type="custom", pose_detail="one-foot balance while leaning sideways")
        self.assertEqual(validate_geometry(geometry, character=True), geometry)
        self.assertFalse(geometry_errors({"geometry": geometry, "scene": "Balancing with a readable action."}))

    def test_enum_formatting_is_normalized_before_validation(self):
        for value, expected in ((" front three-quarter ", "front_three_quarter"), ("full body", "full_body"),
                                ("eye-level", "eye_level"), ("REAR three  quarter__left", "rear_three_quarter_left")):
            self.assertEqual(normalize_geometry_value(value), expected)
        raw = {"framing": "Full body", "camera_view": "front three-quarter", "camera_height": "eye-level"}
        canonical = {"framing": "full_body", "camera_view": "front_three_quarter", "camera_height": "eye_level"}
        self.assertEqual(validate_geometry(raw), canonical)
        self.assertEqual(migrate_saved_geometry(raw), (canonical, False))
        self.assertFalse(geometry_errors({"geometry": raw, "scene": "One coherent view."}))

    def test_required_character_fields_and_optional_nonhuman_geometry(self):
        self.assertEqual(CHARACTER_REQUIRED_FIELDS, {"framing", "camera_view", "body_orientation",
                                                    "head_direction", "gaze_direction", "face_visibility"})
        base = character_geometry()
        for field in CHARACTER_REQUIRED_FIELDS:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "missing"):
                validate_geometry({key: value for key, value in base.items() if key != field}, character=True)
        self.assertEqual(validate_geometry({"framing": "wide", "composition": "environmental"}),
                         {"framing": "wide", "composition": "environmental"})
        self.assertEqual(validate_geometry({}), {})  # Loadable pending/manual/legacy state.
        minimal = {key: value for key, value in base.items() if key in CHARACTER_REQUIRED_FIELDS}
        self.assertEqual(validate_geometry(minimal, character=True), minimal)
        self.assertFalse(geometry_errors({"geometry": minimal, "idea": "juggling oranges",
                                         "scene": "She juggles oranges with her hands visible."}, character=True))

    def test_counts_are_integers_not_enums_or_booleans(self):
        self.assertEqual(validate_geometry({"primary_subject_count": 1, "secondary_subject_count": 0}),
                         {"primary_subject_count": 1, "secondary_subject_count": 0})
        for field in ("primary_subject_count", "secondary_subject_count"):
            for invalid in (True, -1, 1.5, "1", None):
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    validate_geometry({field: invalid})
        with self.assertRaises(ValueError):
            validate_geometry({"primary_subject_count": 0})

    def test_free_text_arrays_and_details_are_bounded(self):
        for field in ("action_focus", "pose_detail", "expression_detail"):
            for value in ("", "x\ny", "x" * 161, "no extra people", [], 3):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_geometry({field: value})
        for value in ("face", [""], ["x"] * 13, [True], ["no other people"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_geometry({"visibility_focus": value})
        self.assertEqual(validate_geometry({"visibility_focus": ["unusual freeform object"]}),
                         {"visibility_focus": ["unusual freeform object"]})

    def test_gaze_directions_never_accept_emotions_and_correction_is_compact(self):
        for emotion in ("shocked", "aggressive", "ecstatic", "stoic", "focused"):
            with self.subTest(emotion=emotion), self.assertRaises(GeometryValidationError) as caught:
                validate_geometry({"gaze_direction": emotion})
            self.assertIn("Expected one of", str(caught.exception))
            self.assertIn("not emotion", caught.exception.correction)
            self.assertNotIn("Expected one of", caught.exception.correction)
        self.assertEqual(validate_geometry({"gaze_direction": "toward_action", "expression": "shocked"}),
                         {"gaze_direction": "toward_action", "expression": "shocked"})
        with self.assertRaises(ValueError):
            validate_geometry({"gaze": "frustrated"})

    def test_saved_migration_is_conservative_and_does_not_guess_pose_or_sidedness(self):
        migrated, changed = migrate_saved_geometry({"framing": "full body", "camera_view": "profile",
            "gaze": "focused on pigeons", "pose": "invented pose description"})
        self.assertTrue(changed)
        self.assertEqual(migrated, {"framing": "full_body", "gaze_direction": "toward_action", "expression": "focused"})
        self.assertEqual(migrate_saved_geometry({"gaze": "shocked"}), ({"expression": "shocked"}, True))
        self.assertEqual(migrate_saved_geometry({"gaze": "aggressive"}), ({}, True))
        canonical = character_geometry()
        self.assertEqual(migrate_saved_geometry(canonical), (canonical, False))
        with self.assertRaises(ValueError):
            migrate_saved_geometry({"gaze_direction": "aggressive"})


class GeometryCompatibilityTests(unittest.TestCase):
    def errors(self, **geometry):
        return geometry_errors({"geometry": geometry, "scene": "One coherent scene."})

    def test_direct_rear_and_valid_over_shoulder(self):
        self.assertTrue(self.errors(camera_view="direct_rear", face_visibility="full", gaze_direction="toward_camera"))
        self.assertFalse(self.errors(camera_view="direct_rear", face_visibility="hidden", head_direction="away_from_camera"))
        self.assertFalse(self.errors(camera_view="rear_three_quarter_right", body_orientation="rear_three_quarter_right",
            head_direction="over_left_shoulder", gaze_direction="toward_camera", face_visibility="three_quarter"))
        self.assertTrue(self.errors(camera_view="rear_three_quarter_right", face_visibility="full"))
        self.assertTrue(self.errors(camera_view="direct_rear", face_visibility="partial", head_direction="toward_action"))
        self.assertFalse(self.errors(camera_view="direct_rear", face_visibility="partial", head_direction="over_left_shoulder"))
        self.assertFalse(geometry_errors({"geometry": {"camera_view": "direct_rear", "face_visibility": "full"},
                                         "scene": "Her face is visible in a mirror reflection."}))

    def test_crop_feet_and_body_visibility(self):
        for crop in ("extreme_close_up", "face_close_up", "head_and_shoulders", "upper_body", "waist_up", "three_quarter_body"):
            for feet in ("left_visible", "right_visible", "both_visible", "partially_visible"):
                with self.subTest(crop=crop, feet=feet):
                    self.assertTrue(self.errors(framing=crop, feet_visibility=feet))
            self.assertFalse(self.errors(framing=crop, feet_visibility="none_visible"))
        self.assertTrue(self.errors(framing="face_close_up", body_visibility="waist_up"))
        self.assertTrue(self.errors(framing="full_body", body_visibility="upper_body"))
        self.assertTrue(self.errors(framing="full_body", feet_visibility="none_visible"))
        self.assertFalse(self.errors(framing="full_body", feet_visibility="none_visible", occlusion="major", body_visibility="partial_body"))

    def test_camera_body_torso_relative_sides(self):
        for view, body in (("front", "direct_rear"), ("direct_rear", "front"), ("profile_left", "profile_right")):
            with self.subTest(view=view, body=body):
                self.assertTrue(self.errors(camera_view=view, body_orientation=body))
        self.assertTrue(self.errors(torso_orientation="front", hip_orientation="direct_rear"))
        self.assertFalse(self.errors(camera_view="front_three_quarter", body_orientation="front_three_quarter_left",
                                     torso_orientation="twisted_left", hip_orientation="front"))
        self.assertFalse(self.errors(head_direction="down", gaze_direction="up"))  # Subtle eye motion is allowed.

    def test_action_visibility_and_two_handed_actions(self):
        for action in ("holding a bag", "juggling oranges", "throwing a ball", "catching fruit", "selfie", "painting a taxi", "carrying bags"):
            with self.subTest(action=action):
                self.assertTrue(self.errors(action_focus=action, hand_visibility="none_visible"))
                self.assertFalse(self.errors(action_focus=action, hand_visibility="right_visible"))
        self.assertTrue(self.errors(action_focus="holding a box with both hands", hand_visibility="right_visible"))
        self.assertFalse(self.errors(action_focus="holding a box with both hands", hand_visibility="partially_visible"))
        self.assertFalse(self.errors(action_focus="juggling oranges"))
        self.assertFalse(self.errors(action_focus="juggling oranges", visibility_focus=["hands", "oranges"]))
        self.assertFalse(self.errors(action_focus="catching popcorn in her mouth", hand_visibility="none_visible"))
        self.assertTrue(geometry_errors({"idea": "walking in oversized shoes", "geometry": {"framing": "face_close_up"}}))

    def test_selfie_and_closed_eye_contradictions(self):
        self.assertTrue(self.errors(pose_type="selfie_pose", face_visibility="hidden"))
        self.assertFalse(self.errors(pose_type="selfie_pose", face_visibility="full", gaze_direction="toward_camera"))
        self.assertTrue(geometry_errors({"geometry": {"pose_type": "selfie_pose"},
            "scene": "The phone is the camera; the phone is clearly visible in her hand."}))
        self.assertFalse(geometry_errors({"geometry": {"pose_type": "selfie_pose"},
            "scene": "In a mirror selfie, the phone is visible beside her face."}))
        self.assertTrue(geometry_errors({"geometry": {"gaze_direction": "eyes_closed"}, "scene": "Looking directly at the camera."}))
        self.assertTrue(geometry_errors({"geometry": {"gaze_direction": "toward_camera"}, "scene": "Her eyes are closed."}))
        self.assertTrue(geometry_errors({"geometry": {"body_orientation": "direct_rear"}, "scene": "Full frontal face toward camera."}))
        self.assertFalse(geometry_errors({"geometry": {"gaze_direction": "eyes_closed"}, "scene": "A relaxed face with closed eyes."}))


if __name__ == "__main__":
    unittest.main()
