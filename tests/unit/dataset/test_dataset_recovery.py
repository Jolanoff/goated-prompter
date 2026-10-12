"""Current stage recovery retains siblings; scenes arrive with their ideas."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.plan import scene_plan_signature
from goated_prompter.features.dataset.idea_history import RecentIdeaHistory
from tests.helpers import dataset_understanding_fixture
from tests.helpers import dataset_idea_fixture
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


class RecoveryTests(unittest.TestCase):
    def test_frozen_walking_pose_is_not_rejected_by_a_later_passive_idea_hint(self):
        from dataclasses import replace
        from goated_prompter.features.dataset.plan import ScenePlanner
        from tests.support.dataset import frozen_specs
        data = valid_draft(amount=2, subject="exploring a mossy fantasy forest")
        specs = frozen_specs(data)
        specs[2] = replace(specs[2], participants=tuple(replace(item, pose="walking forward", support="ground")
            if item.bodied else item for item in specs[2].participants))
        existing = [saved_scene(1, idea="The explorer walks through a forest at dawn.", scene_spec=specs[1].to_dict())]
        backend = CaptureBackend()
        original = backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:ideas":
                backend.calls.append(instruction)
                return json.dumps([dataset_idea_fixture(2, idea="The explorer walks through the forest at dusk.")])
            return original(instruction)
        backend.generate = generate
        rows = ScenePlanner(lambda: None).plan_ideas(session=backend, data=data, assignments=dataset_assignments(data),
            indexes=[2], existing=[*existing, saved_scene(2, scene_spec=specs[2].to_dict())],
            progress=lambda _: None, allow_partial=True)
        self.assertNotEqual(rows[0].get("idea_status"), "failed", rows[0].get("failure_reason"))

    def setUp(self):
        self.data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(),
            scene_plan=[saved_scene(1), saved_scene(2)], results=[{"index": 2, "input": "", "prompt": "Saved sibling prompt"}])
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.backend = CaptureBackend(scenes=self.data["scene_plan"])
        self.snapshots = []

    def run_service(self, *, idea_history=None, **options):
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=self.backend):
            return DatasetService({"backend": "mock"}, lambda: None, idea_history=idea_history).run(GoatedPrompterRequest(idea=self.data["subject"], prompt_model="Custom"), self.data,
                lambda _: None, lambda row: self.snapshots.append(deepcopy(row)), **options)

    def test_scene_repair_does_not_treat_its_own_event_as_a_recent_run(self):
        self.data.update(amount=1, scene_plan=[], scene_plan_signature="", results=[])
        history = RecentIdeaHistory()
        original = self.backend.generate
        idea_calls, validation_calls = [], []
        def generate(instruction):
            raw = original(instruction)
            if instruction.diagnostic_stage == "dataset:ideas":
                rows = json.loads(raw)
                idea_calls.append(rows[0]["idea"])
                if len(idea_calls) == 2:
                    rows[0]["scene"] += " Both gloves and the planted feet remain clearly visible."
                    self.backend.scenes[1] = rows[0]["scene"]
                return json.dumps(rows)
            if instruction.diagnostic_stage == "dataset:validation:scene":
                observations = json.loads(raw)
                validation_calls.append(observations)
                if len(validation_calls) == 1:
                    observations[0]["conflicts"] = ["The supporting feet are obscured."]
                return json.dumps(observations)
            return raw
        self.backend.generate = generate
        planned = self.run_service(idea_history=history, scenes_only=True)
        self.data.update(scene_plan=planned["scene_plan"], scene_plan_signature=planned["scene_plan_signature"])
        result = self.run_service(idea_history=history, valid_only=True)
        self.assertEqual(idea_calls, [dataset_idea_fixture(1)["idea"]] * 2)
        self.assertEqual(result["completed"], 1, result["scene_plan"][0].get("failure_reason"))
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(validation_calls), 2)
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "valid")
        self.assertEqual(history.recent(self.data), [idea_calls[0]])

    def test_missing_validator_checks_retain_output_unverified_without_regenerating_ideas(self):
        self.data.update(amount=1, scene_plan=[], scene_plan_signature="", results=[])
        original = self.backend.generate
        validation_calls = []
        def generate(instruction):
            raw = original(instruction)
            if instruction.diagnostic_stage == "dataset:validation:prompt":
                observations = json.loads(raw)
                validation_calls.append(observations)
                if len(validation_calls) == 1:
                    observations[0]["requirements"] = observations[0]["requirements"][:-1]
                return json.dumps(observations)
            return raw
        self.backend.generate = generate
        result = self.run_service(idea_history=RecentIdeaHistory())
        self.assertEqual(result["completed"], 1, result["scene_plan"][0].get("failure_reason"))
        self.assertEqual(len(validation_calls), 1)
        ideas = [call for call in self.backend.calls if call.diagnostic_stage == "dataset:ideas"]
        self.assertEqual(len(ideas), 1)
        self.assertIn("Not every approved requirement was checked exactly once.", result["scene_plan"][0]["quality_warnings"])
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "unverified")
        self.assertEqual(result["scene_plan"][0]["scene"], dataset_idea_fixture(1)["scene"])
        self.assertNotIn("failure_stage", result["scene_plan"][0])

    def test_unresolved_support_finding_retains_prompt_unverified_after_one_local_repair(self):
        self.data.update(amount=1, scene_plan=[], scene_plan_signature="", results=[])
        original = self.backend.generate
        validation_calls = []
        def generate(instruction):
            raw = original(instruction)
            if instruction.diagnostic_stage == "dataset:validation:prompt":
                observations = json.loads(raw)
                observations[0]["conflicts"] = ["The physical support is unknown."]
                validation_calls.append(observations)
                return json.dumps(observations)
            return raw
        self.backend.generate = generate
        result = self.run_service(idea_history=RecentIdeaHistory())
        self.assertEqual(len(validation_calls), 2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "unverified")
        self.assertIn("support is unknown", " ".join(result["scene_plan"][0]["quality_warnings"]))
        self.assertEqual(result["scene_plan"][0]["scene"], dataset_idea_fixture(1)["scene"])
        self.assertEqual(sum(call.diagnostic_stage.startswith("dataset:1") for call in self.backend.calls), 2)
        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in self.backend.calls), 1)

    def test_new_idea_is_one_targeted_call_whose_scene_is_written_directly(self):
        result = self.run_service(scene_action=("regenerate_idea", 1))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls],
            ["dataset:ideas", "dataset:validation:scene", "dataset:1", "dataset:validation:prompt"])
        self.assertEqual(result["scene_plan"][0]["scene"], dataset_idea_fixture(1)["scene"])
        self.assertEqual(self.backend.calls[2].user_message, dataset_idea_fixture(1)["scene"])
        self.assertEqual(result["scene_plan"][1], self.data["scene_plan"][1])
        self.assertEqual(result["prompts"][1], self.data["results"][0])

    def test_scene_repair_is_no_longer_a_per_scene_action(self):
        with self.assertRaisesRegex(ValueError, "Unknown per-scene action"):
            self.run_service(scene_action=("repair_scene", 1))
        self.assertEqual(self.backend.calls, [])

    def test_repair_verdict_never_triggers_an_automatic_repair(self):
        self.data["scene_plan"][0].update(self_check="REPAIR:\nRequired glove hidden.\nMove the glove outward.", scene_status="repair_required")
        result = self.run_service()
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2", "dataset:validation:prompt"])
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
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:1", "dataset:validation:prompt"])
        self.assertEqual(result["completed"], 2)

    def test_check_edit_retains_prose_and_checks_it_without_ideation_before_writing(self):
        self.data["scene_plan"][0].update(scene="An edited scene.", self_check="", scene_status="not_generated", edited_stage="scene")
        result = self.run_service(scene_action=("validate_scene", 1))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:validation:scene"])
        self.assertEqual(json.loads(self.backend.calls[0].user_message)[0]["description"], "An edited scene.")
        self.assertEqual(result["scene_plan"][0]["self_check"], "PASS")
        self.assertEqual(result["scene_plan"][0]["scene"], "An edited scene.")
        self.data.update(scene_plan=result["scene_plan"])
        self.backend = CaptureBackend(scenes=self.data["scene_plan"])
        result = self.run_service(valid_only=True)
        self.assertEqual(result["completed"], 2)

    def test_interrupted_writer_leaves_every_idea_and_scene_durable(self):
        self.data.update(scene_plan=[], scene_plan_signature="", results=[])
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:2":
                raise RuntimeError("interrupted second prompt")
            return original(instruction)
        self.backend.generate = generate
        with self.assertRaisesRegex(RuntimeError, "interrupted second prompt"):
            self.run_service()
        rows = self.snapshots[-1]["scene_plan"]
        self.assertEqual([row["self_check"] for row in rows], ["", ""])
        self.assertEqual([row["scene_status"] for row in rows], ["unverified", "unverified"])
        self.assertEqual([row["scene"] for row in rows], [dataset_idea_fixture(1)["scene"], dataset_idea_fixture(2)["scene"]])
        self.assertEqual([row["index"] for row in self.snapshots[-1]["prompts"]], [1])

    def duplicate_batch(self, *, bad_repair=False, malformed=False):
        self.data.update(amount=3, scene_plan=[], scene_plan_signature="", results=[],
            source_mode="guided" if malformed else "random", inputs="First\nSecond\nThird" if malformed else "")
        original = self.backend.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:ideas":
                context = json.loads(instruction.user_message)
                indexes = [row["index"] for row in context["assignments"]]
                if len(indexes) == 3:
                    rows = json.loads(original(instruction))
                    if malformed:
                        rows[1]["scene"] = ""
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
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas:brainstorm", "dataset:planning",
            "dataset:ideas", "dataset:1", "dataset:validation:prompt", "dataset:3", "dataset:validation:prompt",
            "dataset:ideas", "dataset:2", "dataset:validation:prompt"])
        repairs = json.loads(next(call for call in reversed(self.backend.calls) if call.diagnostic_stage == "dataset:ideas").user_message)
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
                chunks.append(indexes)
                if len(chunks) <= 4:
                    rows = json.loads(original(instruction))
                    for row in rows:
                        if row["index"] in (7, 19):
                            row["idea"] = dataset_idea_fixture(1)["idea"]
                    return json.dumps(rows)
                self.assertEqual(indexes, [7, 19])
                self.assertEqual(sum(call.diagnostic_stage.split(":")[-1].isdigit()
                    for call in self.backend.calls), 18)
            return original(instruction)
        chunks = []
        self.backend.generate = generate
        result = self.run_service()
        self.assertEqual(result["completed"], 20)
        self.assertEqual(result["failed"], 0)
        self.assertEqual([row["index"] for row in result["prompts"]], list(range(1, 21)))
        self.assertEqual(chunks, [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15], [16, 17, 18, 19, 20], [7, 19]])

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
        self.assertEqual(result["scene_plan"][1]["failure_reason"], "Synthetic connection closed during replacement.")
        self.assertEqual(result["scene_plan"][1]["failure_stage"], "idea")
