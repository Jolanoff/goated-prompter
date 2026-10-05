"""Regression for the retired planner crop-to-anatomy fixup."""
import unittest
from goated_prompter.dataset_staging import geometry_errors, validate_planned_geometry
from tests.test_dataset_geometry import character_geometry


class PlannerFeetFixupTests(unittest.TestCase):
    def test_planner_never_rewrites_visibility_from_framing(self):
        for framing in ("waist_up", "face_close_up", "full_body", "full_body_with_environment"):
            for feet in ("left_visible", "right_visible", "none_visible", "partially_visible", "both_visible"):
                with self.subTest(framing=framing, feet=feet):
                    geometry = character_geometry(framing=framing, feet_visibility=feet, body_visibility="upper_body")
                    self.assertEqual(validate_planned_geometry(geometry, dataset_type="Character"), geometry)
                    self.assertFalse(geometry_errors({"geometry":geometry,"scene":"A compact composition."}, dataset_type="Character"))

    def test_nonhuman_planner_does_not_gain_human_fields(self):
        for kind in ("Object / product", "Animal", "Multiple characters"):
            geometry = {"framing":"full_subject","camera_azimuth":"front", "composition":"centered",
                        "primary_subject_count":2,"action_visibility":"clear"}
            self.assertEqual(validate_planned_geometry(geometry,dataset_type=kind),geometry)

    def test_unknown_fields_and_invalid_visibility_remain_structural_errors(self):
        for changes in ({"unsupported":"value"}, {"feet_visibility":None}):
            with self.assertRaises(ValueError):
                validate_planned_geometry(character_geometry(**changes),dataset_type="Character")
