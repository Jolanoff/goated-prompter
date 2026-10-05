"""Live vocabulary is scoped; saved and user-specified long-tail staging survives."""

import json
import unittest

from goated_prompter.dataset import default_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import (
    geometry_enum_values, geometry_prompt_schema, migrate_saved_geometry, validate_geometry,
)
from goated_prompter.prompting.scene_planner import scene_planner_instruction, scene_composer_instruction
from tests.test_dataset_geometry import character_geometry


class StagingCapabilityTests(unittest.TestCase):
    def test_ordinary_character_schema_never_offers_specialized_menus(self):
        excluded = {
            "pose_type": {"missionary", "doggy", "oral_giving", "bound", "mating_press"},
            "gaze_direction": {"looking_at_genital"},
            "head_direction": {"looking_at_genital"},
            "expression": {"aroused", "orgasmic", "ahegao", "submissive", "dominant"},
            "camera_elevation": {"crotch_level", "between_legs"},
            "contact_state": {"penetrating", "oral_contact", "genital_contact"},
        }
        values = geometry_enum_values("Character")
        schema = geometry_prompt_schema("Character")
        for field, forbidden in excluded.items():
            with self.subTest(field=field):
                self.assertFalse(set(values[field]) & forbidden)
                field_schema = next(line for line in schema.splitlines() if line.startswith(field + ":"))
                for word in forbidden:
                    self.assertNotIn(word, field_schema)
                    with self.assertRaises(ValueError):
                        validate_geometry(character_geometry(**{field: word}), dataset_type="Character")

    def test_fast_and_quality_planning_use_the_same_scoped_values(self):
        data = {**default_dataset_draft(), "amount": 1, "subject": "A person juggling"}
        assignments = dataset_assignments(data)
        for instruction in (scene_planner_instruction(data, assignments),
                            scene_composer_instruction(data, assignments, [{"index": 1, "idea": "Juggling"}])):
            with self.subTest(stage=instruction.diagnostic_stage):
                self.assertNotIn("missionary", instruction.system_message + instruction.user_message)
                self.assertNotIn("aroused", instruction.system_message + instruction.user_message)
                self.assertIn("pose_detail", instruction.system_message)

    def test_custom_pose_retains_user_mechanics_and_required_detail_validation(self):
        geometry = character_geometry(pose_type="custom", pose_detail="Suspended by one knee with both arms reaching sideways")
        self.assertEqual(validate_geometry(geometry, dataset_type="Character"), geometry)
        with self.assertRaises(ValueError):
            validate_geometry({**geometry, "pose_detail": "unusual"}, dataset_type="Character")

    def test_saved_specialized_pose_and_expression_migrate_to_details_without_loss(self):
        geometry = character_geometry(pose_type="missionary", expression="aroused", pose_detail="Original supplied contact relationships")
        migrated, warning = migrate_saved_geometry(geometry, dataset_type="Character")
        self.assertEqual(migrated["pose_type"], "custom")
        self.assertIn("missionary", migrated["pose_detail"])
        self.assertIn("Original supplied contact relationships", migrated["pose_detail"])
        self.assertEqual(migrated["expression"], "custom")
        self.assertEqual(migrated["expression_detail"], "aroused")
        self.assertFalse(warning)
        self.assertEqual(validate_geometry(migrated, dataset_type="Character"), migrated)

    def test_nonhuman_planning_cannot_leak_specialized_camera_or_contact_values(self):
        for dataset_type in ("Animal", "Object / product", "Multiple characters", "Custom"):
            values = json.dumps(geometry_enum_values(dataset_type))
            self.assertNotIn("between_legs", values)
            self.assertNotIn("genital_contact", values)

    def test_scoped_migration_keeps_bounded_detail_instead_of_dropping_it_on_overflow(self):
        geometry = character_geometry(camera_elevation="between_legs", view_detail="x" * 160)
        migrated, warning = migrate_saved_geometry(geometry, dataset_type="Character")
        self.assertTrue(warning)
        self.assertIn("camera elevation between legs", migrated["view_detail"])
        self.assertEqual(len(migrated["view_detail"]), 160)
        self.assertEqual(migrated["framing"], geometry["framing"])
