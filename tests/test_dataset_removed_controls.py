"""Retired Dataset controls have no effect, including in older saved drafts."""

from copy import deepcopy
import json
import unittest

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import default_dataset_draft, validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_ideas import ideas_instruction
from goated_prompter.dataset_quality import analyze_idea_diversity
from goated_prompter.dataset_scene import scene_instruction
from goated_prompter.dataset_understanding import understanding_instruction
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.scene_planner import scene_plan_signature
from tests.helpers import dataset_understanding_fixture
from tests.test_dataset import saved_scene, valid_draft


class RemovedDatasetControlsTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=1, results=[{"index": 1, "input": "", "prompt": "Saved portrait."}],
            _confirmed_intent=dataset_understanding_fixture())
        self.legacy = {**self.data, "visual_style": "Custom", "custom_style": "RETIRED STYLE", "variety": "Focused"}

    def test_defaults_and_validation_drop_retired_fields_without_touching_source_or_results(self):
        before = deepcopy(self.legacy)
        defaults = default_dataset_draft()
        cleaned = validate_dataset_draft(self.legacy, generation=True)
        for field in ("visual_style", "custom_style", "variety"):
            self.assertNotIn(field, defaults)
            self.assertNotIn(field, cleaned)
        self.assertEqual(cleaned["source_mode"], "random")
        self.assertEqual(cleaned["subject"], self.data["subject"])
        self.assertEqual(cleaned["results"], self.data["results"])
        self.assertEqual(self.legacy, before)

    def test_legacy_fields_do_not_reach_understanding_scene_or_writer_instructions(self):
        assignments = dataset_assignments(self.data)
        row = saved_scene()
        request = GoatedPrompterRequest(idea="Dataset test")
        for build in (lambda data: understanding_instruction(data),
                lambda data: scene_instruction(data, assignments[0], row),
                lambda data: dataset_instruction(request, data, 1, plan_item=row)):
            with self.subTest(builder=build):
                current = build(self.data)
                self.assertEqual(build(self.legacy), current)
                payload = current.system_message + current.user_message
                for marker in ("visual_style", "custom_style", "RETIRED STYLE"):
                    self.assertNotIn(marker, payload)

    def test_legacy_variety_does_not_change_ideas_payload_or_sampling(self):
        assignments = dataset_assignments(self.data)
        expected = ideas_instruction(self.data, assignments)
        for variety in ("Focused", "Balanced", "Wide", "obsolete"):
            with self.subTest(variety=variety):
                actual = ideas_instruction({**self.legacy, "variety": variety}, assignments)
                self.assertEqual(actual, expected)
                self.assertNotIn("variety", json.loads(actual.user_message)["source"])

    def test_legacy_controls_do_not_change_plan_signature_or_duplicate_warnings(self):
        assignments = dataset_assignments(self.data)
        self.assertEqual(scene_plan_signature(self.legacy, assignments), scene_plan_signature(self.data, assignments))
        rows = [{"index": 1, "idea": "A person juggles oranges in a kitchen."},
                {"index": 2, "idea": "A person juggles oranges in a studio."}]
        expected = analyze_idea_diversity(self.data, rows)
        self.assertTrue(expected["ideas"][0]["issues"])
        self.assertEqual(analyze_idea_diversity(self.legacy, rows), expected)
