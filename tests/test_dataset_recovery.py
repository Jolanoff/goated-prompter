"""Current stage recovery retains siblings and never automatically repairs a scene."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_planner import scene_plan_signature
from tests.helpers import dataset_understanding_fixture
from tests.test_dataset import CaptureBackend, saved_scene, valid_draft


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(),
            scene_plan=[saved_scene(1), saved_scene(2)], results=[{"index": 2, "input": "", "prompt": "Saved sibling prompt"}])
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.backend = CaptureBackend()
        self.snapshots = []

    def run_service(self, **options):
        with patch("goated_prompter.dataset.create_backend", return_value=self.backend):
            return DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=self.data["subject"], prompt_model="Custom"), self.data,
                lambda _: None, lambda row: self.snapshots.append(deepcopy(row)), **options)

    def test_repair_is_one_targeted_call_and_retains_sibling_result(self):
        result = self.run_service(scene_action=("repair_scene", 1))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:build_scene", "dataset:1"])
        self.assertEqual(result["scene_plan"][1], self.data["scene_plan"][1])
        self.assertEqual(result["prompts"][1], self.data["results"][0])

    def test_repair_verdict_never_triggers_an_automatic_repair(self):
        self.data["scene_plan"][0].update(self_check="REPAIR:\nRequired glove hidden.\nMove the glove outward.", scene_status="repair_required")
        result = self.run_service()
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual([row["index"] for row in result["prompts"]], [2])

    def test_prompt_failure_skips_only_its_item_and_can_retry(self):
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage.startswith("dataset:1"):
                self.backend.calls.append(instruction)
                raise BackendGenerationError("synthetic disconnect")
            return original(instruction)
        self.backend.generate = generate
        result = self.run_service()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["scene_plan"][0]["scene"], self.data["scene_plan"][0]["scene"])
        self.assertEqual([row["index"] for row in result["prompts"]], [2])
        self.backend.generate = original
        self.backend.calls.clear()
        self.data.update(scene_plan=result["scene_plan"], results=result["prompts"])
        result = self.run_service(scene_action=("regenerate_prompt", 1))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:1"])
        self.assertEqual(result["completed"], 2)

    def test_valid_only_skips_pending_scene_without_ideation(self):
        self.data["scene_plan"][0].update(self_check="", scene_status="not_generated")
        result = self.run_service(valid_only=True)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual(result["completed"], 1)

    def test_interruption_leaves_fixed_ideas_and_completed_scene_durable(self):
        self.data.update(scene_plan=[], scene_plan_signature="")
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:build_scene" and json.loads(instruction.user_message)["assignments"][0]["index"] == 2:
                raise BackendGenerationError("interrupted second scene")
            return original(instruction)
        self.backend.generate = generate
        with self.assertRaisesRegex(BackendGenerationError, "interrupted second scene"):
            self.run_service()
        rows = self.snapshots[-1]["scene_plan"]
        self.assertEqual(rows[0]["self_check"], "PASS")
        self.assertTrue(rows[1]["idea"])
        self.assertEqual(rows[1]["self_check"], "")
