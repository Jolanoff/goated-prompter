"""Explicit Dataset continuation keeps current completed prompts; synthetic models only."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.plan import scene_plan_signature
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


class DatasetContinueTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(),
            scene_plan=[saved_scene(1, prompt_status="valid"), saved_scene(2)])
        row = self.data["scene_plan"][0]
        self.saved = {"index": 1, "input": row["input"], "idea": row["idea"], "scene": row["scene"],
                      "prompt": "ohwx_person: my exact edited prompt.\n  Keep spacing."}
        self.data["results"] = [self.saved]
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.backend = CaptureBackend()
        self.snapshots = []

    def run_service(self, **options):
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=self.backend):
            return DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=self.data["subject"], prompt_model="Custom"), self.data,
                lambda _: None, lambda item: self.snapshots.append(deepcopy(item)), **options)

    def test_continue_only_generates_missing_prompt_and_preserves_saved_text(self):
        before = deepcopy(self.data)
        result = self.run_service(valid_only=True, resume=True)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual(result["prompts"][0], self.saved)
        self.assertEqual(result["completed"], 2)
        self.assertTrue(all(item["prompts"][0] == self.saved for item in self.snapshots))
        self.assertEqual(self.data, before)

    def test_continue_does_not_keep_a_prompt_for_a_changed_scene_or_idea(self):
        for field in ("scene", "idea", "input"):
            with self.subTest(field=field):
                self.saved[field] = "Stale source text"
                self.backend.calls.clear()
                result = self.run_service(valid_only=True, resume=True)
                self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:1", "dataset:2"])
                self.assertNotEqual(result["prompts"][0], self.saved)
                self.saved[field] = self.data["scene_plan"][0][field]

    def test_continue_retries_failed_or_invalidated_prompts_not_completed_siblings(self):
        for status in ("failed", "not_generated"):
            with self.subTest(status=status):
                self.data["scene_plan"][0]["prompt_status"] = status
                self.backend.calls.clear()
                result = self.run_service(valid_only=True, resume=True)
                self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:1", "dataset:2"])
                self.assertNotEqual(result["prompts"][0], self.saved)

    def test_continue_excludes_results_for_scenes_that_need_repair(self):
        self.data["scene_plan"][0].update(self_check="REPAIR:\nRequired glove hidden.\nMove it into view.",
                                         scene_status="repair_required")
        result = self.run_service(valid_only=True, resume=True)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual([row["index"] for row in result["prompts"]], [2])

    def test_continue_completed_batch_has_no_prompt_calls(self):
        row = self.data["scene_plan"][1]
        row["prompt_status"] = "valid"
        self.data["results"].append({"index": 2, "input": row["input"], "idea": row["idea"],
                                     "scene": row["scene"], "prompt": "ohwx_person: saved second prompt."})
        result = self.run_service(valid_only=True, resume=True)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(result["prompts"], self.data["results"])

    def test_fresh_scene_planning_clears_old_prompts_in_the_terminal_snapshot(self):
        self.data.update(scene_plan=[], scene_plan_signature="")
        result = self.run_service(scenes_only=True)
        self.assertEqual(result["prompts"], [])
        self.assertTrue(all(item["prompts"] == [] for item in self.snapshots))
        self.assertEqual(self.data["results"], [self.saved])
