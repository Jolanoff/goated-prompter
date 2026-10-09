"""Current stage recovery retains siblings and never automatically repairs a scene."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.plan import scene_plan_signature
from tests.helpers import dataset_understanding_fixture
from tests.helpers import dataset_idea_fixture
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(),
            scene_plan=[saved_scene(1), saved_scene(2)], results=[{"index": 2, "input": "", "prompt": "Saved sibling prompt"}])
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.backend = CaptureBackend()
        self.snapshots = []

    def run_service(self, **options):
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=self.backend):
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

    def duplicate_batch(self, *, bad_repair=False, malformed=False):
        self.data.update(amount=3, scene_plan=[], scene_plan_signature="", results=[],
            source_mode="guided" if malformed else "random", inputs="First\nSecond\nThird" if malformed else "")
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:ideas":
                context = json.loads(instruction.user_message)
                indexes = [row["index"] for row in context["assignments"]]
                if len(indexes) == 3:
                    self.backend.calls.append(instruction)
                    rows = [dataset_idea_fixture(index) for index in indexes]
                    if malformed:
                        rows[1]["visibility"] = ""
                    else:
                        rows[1]["idea"] = rows[0]["idea"]
                    return json.dumps(rows)
                if bad_repair:
                    self.backend.calls.append(instruction)
                    return json.dumps([dataset_idea_fixture(2, idea=dataset_idea_fixture(1)["idea"])])
            return original(instruction)
        self.backend.generate = generate

    def test_duplicate_idea_preserves_good_prompts_then_repairs_only_its_index(self):
        self.duplicate_batch()
        result = self.run_service()
        self.assertEqual(result["completed"], 3)
        self.assertEqual([row["index"] for row in result["prompts"]], [1, 2, 3])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas",
            "dataset:build_scene", "dataset:build_scene", "dataset:1", "dataset:3", "dataset:ideas",
            "dataset:build_scene", "dataset:2"])
        repairs = json.loads(self.backend.calls[5].user_message)
        self.assertEqual(repairs["output_contract"]["indexes"], [2])
        self.assertTrue(any([row["index"] for row in snapshot["prompts"]] == [1, 3] for snapshot in self.snapshots))
        for snapshot in self.snapshots:
            self.assertEqual(len(snapshot["scene_plan"]), 3)
        self.assertEqual(result["failed"], 0)

    def test_repeated_repair_remains_partial_without_another_retry_or_discarding_siblings(self):
        self.duplicate_batch(bad_repair=True)
        result = self.run_service()
        self.assertEqual([row["index"] for row in result["prompts"]], [1, 3])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["scene_plan"][1]["failure_stage"], "idea")
        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in self.backend.calls), 2)

    def test_malformed_idea_row_keeps_valid_local_assignments_and_is_repaired_after_good_work(self):
        self.duplicate_batch(malformed=True)
        result = self.run_service()
        self.assertEqual(result["completed"], 3)
        self.assertEqual([row["input"] for row in result["scene_plan"]], ["First", "Second", "Third"])
        self.assertEqual([row["input"] for row in result["prompts"]], ["First", "Second", "Third"])

    def test_scene_only_generation_repairs_duplicates_without_writing_prompts(self):
        self.duplicate_batch()
        result = self.run_service(scenes_only=True)
        self.assertEqual(result["prompts"], [])
        self.assertTrue(all(row["self_check"] == "PASS" for row in result["scene_plan"]))
        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in self.backend.calls), 2)

    def test_twenty_idea_batch_repairs_two_repeats_after_eighteen_prompts(self):
        self.data.update(amount=20, scene_plan=[], scene_plan_signature="", results=[])
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:ideas":
                context = json.loads(instruction.user_message)
                indexes = context["output_contract"]["indexes"]
                if len(indexes) == 20:
                    self.backend.calls.append(instruction)
                    rows = [dataset_idea_fixture(index) for index in indexes]
                    rows[6]["idea"] = rows[0]["idea"]
                    rows[18]["idea"] = rows[0]["idea"]
                    return json.dumps(rows)
                self.assertEqual(indexes, [7, 19])
                self.assertEqual(sum(call.diagnostic_stage.split(":")[-1].isdigit()
                    for call in self.backend.calls), 18)
            return original(instruction)
        self.backend.generate = generate
        result = self.run_service()
        self.assertEqual(result["completed"], 20)
        self.assertEqual(result["failed"], 0)
        self.assertEqual([row["index"] for row in result["prompts"]], list(range(1, 21)))
        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in self.backend.calls), 2)

    def test_transport_failure_in_idea_repair_keeps_good_prompts_and_reports_failed_slot(self):
        self.duplicate_batch()
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:ideas" and len(json.loads(instruction.user_message)["assignments"]) == 1:
                raise BackendGenerationError("Synthetic connection closed during replacement.")
            return original(instruction)
        self.backend.generate = generate
        result = self.run_service()
        self.assertEqual([row["index"] for row in result["prompts"]], [1, 3])
        self.assertEqual(result["failed"], 1)
        self.assertIn("Idea repair failed", result["scene_plan"][1]["failure_reason"])

    def test_replacement_scene_failure_retains_siblings_and_writes_other_replacements(self):
        for failed_index in (2, 3):
            for invalid_json in (False, True):
                for scenes_only in (False, True):
                    with self.subTest(failed_index=failed_index, invalid_json=invalid_json, scenes_only=scenes_only):
                        self.setUp()
                        self.data.update(amount=4, scene_plan=[], scene_plan_signature="", results=[])
                        original = self.backend.generate
                        def generate(instruction):
                            if instruction.diagnostic_stage == "dataset:ideas":
                                context = json.loads(instruction.user_message)
                                indexes = context["output_contract"]["indexes"]
                                if len(indexes) == 4:
                                    self.backend.calls.append(instruction)
                                    rows = [dataset_idea_fixture(index) for index in indexes]
                                    rows[1]["idea"] = rows[2]["idea"] = rows[0]["idea"]
                                    return json.dumps(rows)
                                self.assertEqual(indexes, [2, 3])
                                if not scenes_only:
                                    self.assertEqual([row["index"] for row in self.snapshots[-1]["prompts"]], [1, 4])
                            if instruction.diagnostic_stage == "dataset:build_scene":
                                index = json.loads(instruction.user_message)["assignments"][0]["index"]
                                if index == failed_index:
                                    self.backend.calls.append(instruction)
                                    if invalid_json:
                                        return "not valid scene JSON"
                                    raise BackendGenerationError("Synthetic replacement scene disconnect.")
                            return original(instruction)
                        self.backend.generate = generate
                        result = self.run_service(scenes_only=scenes_only)
                        expected = [index for index in range(1, 5) if index != failed_index]
                        self.assertEqual([row["index"] for row in result["prompts"]], [] if scenes_only else expected)
                        row = result["scene_plan"][failed_index - 1]
                        self.assertEqual(row["failure_stage"], "scene")
                        self.assertEqual((row["idea_status"], row["scene_status"], row["prompt_status"]),
                            ("valid", "failed", "failed"))
                        self.assertTrue(row["failure_reason"])
                        self.assertEqual(row["self_check"], "")
                        self.assertTrue(all(result["scene_plan"][index - 1]["self_check"] == "PASS" for index in expected))
                        self.assertEqual(sum(call.diagnostic_stage == "dataset:build_scene" for call in self.backend.calls), 4)
                        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in self.backend.calls), 2)
                        if not scenes_only:
                            self.assertEqual((result["completed"], result["failed"]), (3, 1))
                            self.assertEqual(self.snapshots[-1]["prompts"], result["prompts"])
                        self.assertEqual(len(self.snapshots[-1]["scene_plan"]), 4)
