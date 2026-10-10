"""Current Dataset contracts and final-output invariants; synthetic storage/models."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import GoatedPrompterBackend, BackendRunawayError, BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService, default_dataset_draft, validate_dataset_draft, saved_dataset_draft
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.plan import scene_plan_signature
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


class DatasetUnitTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        self.row = saved_scene()
        self.instruction = dataset_instruction(GoatedPrompterRequest(idea=self.data["subject"]), self.data, 1, plan_item=self.row)

    def generate(self, responses):
        session = Mock()
        session.generate.side_effect = responses
        result = DatasetService({}, lambda: None)._generate(session, self.instruction, self.data, 1, lambda _: None, self.row)
        return result, session

    def test_bounds_and_guided_requirements(self):
        for changes in ({"amount": True}, {"amount": 26}, {"source_mode": "guided", "inputs": ""},
                        {"length": "Huge"}, {"trigger_connected": 1}, {"creativity": "invalid"}, {"plan_scenes_first": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_dataset_draft(valid_draft(**changes), generation=True)

    def test_trigger_length_boundary_for_saved_and_generation_drafts(self):
        for options in ({}, {"generation": True}, {"generation": True, "planning": True}):
            for length in (201, 999, 1000):
                with self.subTest(options=options, length=length):
                    trigger = "t" * length
                    self.assertEqual(validate_dataset_draft(valid_draft(trigger=trigger), **options)["trigger"], trigger)
            with self.subTest(options=options, length=1001), self.assertRaisesRegex(ValueError, "at most 1000 characters"):
                validate_dataset_draft(valid_draft(trigger="t" * 1001), **options)

    def test_guided_lines_cycle_without_invented_staging(self):
        data = valid_draft(amount=3, source_mode="guided", inputs="First action\nSecond action")
        self.assertEqual(dataset_assignments(data), [{"index": 1, "input": "First action"},
            {"index": 2, "input": "Second action"}, {"index": 3, "input": "First action"}])

    def test_current_schema_has_no_staging_or_quality_fields(self):
        data = validate_dataset_draft(valid_draft(planning_mode="Quality", quality_report={"score": 100}))
        self.assertNotIn("planning_mode", data)
        self.assertNotIn("quality_report", data)
        for field in ("geometry", "coverage_conflicts", "replacement_attempted"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_dataset_draft(valid_draft(scene_plan=[{**self.row, field: {}}]))

    def test_archived_final_prompts_survive_without_executable_legacy_plan(self):
        old = valid_draft(scene_plan=[{"index": 1, "input": "", "scene": "Old scene", "geometry": {"camera_view": "rear"}}],
            scene_plan_signature="old", results=[{"index": 1, "input": "", "prompt": "Saved final prompt", "geometry": {}}])
        before = deepcopy(old)
        cleaned = saved_dataset_draft(old)
        self.assertEqual(cleaned["results"], [{"index": 1, "input": "", "prompt": "Saved final prompt"}])
        self.assertEqual(cleaned["scene_plan"], [])
        self.assertEqual(old, before)

    def test_transport_retry_does_not_add_semantic_review_or_change_scene(self):
        result, session = self.generate([BackendGenerationError("disconnect"), "ohwx_person punches the training bag."])
        self.assertIn("ohwx_person", result)
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(session.generate.call_args.args[0].user_message, self.row["scene"])

    def test_complete_preloop_output_is_validated_without_retry(self):
        prefix = "ohwx_person punches a training bag. " + "Cloth tension and diffuse lighting clarify the frozen impact. " * 4
        result, session = self.generate([BackendRunawayError("loop", recoverable_text=prefix)])
        self.assertEqual(result, prefix.strip())
        session.generate.assert_called_once()

    def test_output_recovery_keeps_scene_and_reduced_budget(self):
        result, session = self.generate([BackendRunawayError("loop"), "missing trigger", "ohwx_person punches a bag."])
        self.assertIn("ohwx_person", result)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertLess(calls[1].hard_max_tokens, calls[0].hard_max_tokens)
        self.assertEqual(calls[2].hard_max_tokens, calls[1].hard_max_tokens)
        self.assertTrue(all(call.user_message == self.row["scene"] for call in calls))

    def test_invalid_outputs_are_bounded(self):
        session = Mock(); session.generate.return_value = "Missing the protected token."
        with self.assertRaises(BackendGenerationError):
            DatasetService({}, lambda: None)._generate(session, self.instruction, self.data, 1, lambda _: None, self.row)
        self.assertEqual(session.generate.call_count, 4)

    def test_one_session_and_only_current_stages(self):
        backend = CaptureBackend()
        snapshots = []
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=self.data["subject"], prompt_model="Custom"), self.data, lambda _: None, snapshots.append)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:ideas", "dataset:1"])
        self.assertEqual(backend.sessions, 1)
        self.assertEqual(result["completed"], 1)
        self.assertNotIn("quality_report", result)
        self.assertNotIn("geometry", result["prompts"][0])
        self.assertEqual(snapshots[0]["scene_plan"][0]["self_check"], "")

    def test_output_settings_reuse_plan_but_concept_changes_do_not(self):
        signature = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.assertEqual(signature, scene_plan_signature({**self.data, "length": "Detailed", "target": "Anima"}, dataset_assignments(self.data)))
        self.assertNotEqual(signature, scene_plan_signature({**self.data, "subject": "Different"}, dataset_assignments(self.data)))

    def test_old_frozen_idea_pass_plans_need_replanning_under_the_new_contract(self):
        from goated_prompter.features.dataset.plan import reusable_scene_plan
        assignments = dataset_assignments(self.data)
        with patch("goated_prompter.features.dataset.plan.SCENE_PLAN_VERSION", 7):
            old_signature = scene_plan_signature(self.data, assignments)
        data = {**self.data, "scene_plan": [self.row], "scene_plan_signature": old_signature}
        self.assertIsNone(reusable_scene_plan(data, assignments))
        self.assertEqual(data["scene_plan"], [self.row])
