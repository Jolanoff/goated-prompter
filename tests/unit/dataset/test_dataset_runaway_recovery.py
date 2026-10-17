"""Runaway recovery uses scripted responses, never a model or private storage."""

from collections import Counter, defaultdict
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch
from tests.helpers import enter_context

from goated_prompter.backends.base import BackendConfigurationError, BackendGenerationError, BackendRunawayError
from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.local_jobs import Job, JobCancelled
from goated_prompter.workflow_output import WorkflowFormatError
from tests.support.dataset_scenes import composer_user


class RunawayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = {"backend": "mock"}
        self.request = GoatedPrompterRequest(idea="Adult reading", planning_mode="Direct", director_preset="general_director")
        self.data = {**default_dataset_draft(), "subject": "Alex reads", "amount": 1, "seed": 73,
                     "seed_mode": "fixed", "constraints": "Alex has one left hand and one right hand."}
        self.value = {"path": "character", "summary": "Alex reads", "fixed": "Alex's identity and anatomy remain fixed",
                      "randomized": "Location and light", "must": [self.data["constraints"]], "avoid": [],
                      "characters": [{"label": "Alex", "gender": "custom", "custom": "adult human reader", "pronoun": "it", "count": 1}]}
        self.brief = understanding.apply_rules(self.value, self.data)
        self.calls, self.scripts = [], defaultdict(list)
        self.backend = MockBackend()
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            enter_context(self, patch.object(module, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))

    def loop(self):
        return BackendRunawayError('The prompt engine entered a repetition loop around "the s".',
                                   recoverable_text="Incomplete response must never be accepted.")

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if self.scripts[stage]:
            value = self.scripts[stage].pop(0)
            if isinstance(value, Exception):
                raise value
            if callable(value):
                return value(instruction)
            return value
        if stage == "dataset_v2:understanding":
            return json.dumps(self.value)
        if stage == "dataset_v2:scenes":
            return json.dumps({"scenes": [self.description(f"location{row['image']}")
                                          for row in composer_user(instruction.user_message)["images"]]})
        return "Alex reads a book, seated with feet on the floor."

    def description(self, place="library"):
        return {"subjects": {"Alex": {field: f"visible {field}" for field in scenes.SUBJECT_FIELDS}},
                "actions": "Alex reads", "position": {"Alex": "Seated, feet on the floor"},
                "space": place, "lighting": "daylight", "mood": "calm", "camera": "wide", "extras": "books"}

    def scene(self):
        return self.description()

    def write_scenes(self, **kwargs):
        return scenes.write_scenes(self.config, self.request, self.brief, progress=lambda _message: None, **kwargs)

    def write_prompts(self, count=1, **kwargs):
        return prompts.write_prompts(self.config, self.request, self.brief, [deepcopy(self.scene()) for _ in range(count)],
                                     progress=lambda _message: None, **kwargs)

    def test_scene_writing_is_one_stage(self):
        result = self.write_scenes()
        self.assertTrue(result["complete"])
        self.assertEqual(Counter(call.diagnostic_stage for call in self.calls), {"dataset_v2:scenes": 1})

    def test_one_prompt_exhausts_loop_recovery_and_the_next_prompt_still_runs(self):
        self.scripts["final"] = [self.loop(), self.loop(), self.loop()]
        published = []
        results = self.write_prompts(2, on_prompt=published.append)
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["prompt"])
        self.assertTrue(results[0]["error"])
        self.assertTrue(results[1]["prompt"])
        self.assertEqual(published, results)
        self.assertEqual(len(self.calls), 4)

    def test_understanding_loop_retries_and_only_returns_a_valid_brief(self):
        self.scripts["dataset_v2:understanding"] = [self.loop()]
        result = understanding.understand(self.config, self.request, self.data, progress=lambda _message: None)
        self.assertEqual(result, self.brief)
        self.assertEqual(len(self.calls), 2)

    def test_understanding_repeated_loops_fail_without_an_unapproved_brief(self):
        self.scripts["dataset_v2:understanding"] = [self.loop() for _ in range(4)]
        with self.assertRaises(BackendRunawayError):
            understanding.understand(self.config, self.request, self.data, progress=lambda _message: None)
        self.assertEqual(len(self.calls), 3)

    def test_the_scene_stage_recovers_with_changed_sampling_and_identical_input(self):
        stage = "dataset_v2:scenes"
        self.scripts[stage] = [self.loop()]
        result = self.write_scenes()
        self.assertTrue(result["complete"])
        calls = [call for call in self.calls if call.diagnostic_stage == stage]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].user_message, calls[1].user_message)
        self.assertNotEqual(calls[0].system_message, calls[1].system_message)
        self.assertNotEqual(calls[0].seed, calls[1].seed)
        self.assertGreater(calls[1].temperature, 0)
        self.assertEqual(calls[0].json_schema, calls[1].json_schema)

    def test_the_scene_stage_has_bounded_failure_and_identifies_failed_slots(self):
        stage = "dataset_v2:scenes"
        self.scripts[stage] = [self.loop() for _ in range(3)]
        result = self.write_scenes()
        self.assertFalse(result["complete"])
        self.assertEqual(result["scenes"], [])
        self.assertEqual((result["missing"][0]["stage"], result["missing"][0]["slot"]), ("scene", 1))
        self.assertEqual(sum(call.diagnostic_stage == stage for call in self.calls), 3)

    def test_completed_scene_is_not_regenerated_when_another_scene_loops(self):
        self.brief["input"]["amount"] = 2
        self.scripts["dataset_v2:scenes"] = [json.dumps({"scenes": [self.description("kept library")]}),
                                             self.loop(), self.loop()]
        result = self.write_scenes()
        self.assertEqual(result["written"], 1)
        self.assertEqual(result["scenes"][0]["space"], "kept library")
        self.assertEqual(result["missing"][0]["slot"], 2)
        calls = [composer_user(call.user_message)["images"] for call in self.calls
                 if call.diagnostic_stage == "dataset_v2:scenes"]
        self.assertEqual([len(value) for value in calls], [2, 1, 1])

    def test_builder_recovery_preserves_requirements_and_successful_prompts(self):
        self.scripts["final"] = ["Alex reads by the window.", self.loop(), "Alex reads beside a lamp."]
        result = self.write_prompts(2)
        self.assertEqual([item["prompt"] for item in result], ["Alex reads by the window.", "Alex reads beside a lamp."])
        self.assertEqual(len(self.calls), 3)
        first, retry = self.calls[1:]
        self.assertEqual(first.user_message, retry.user_message)
        for call in self.calls:
            self.assertIn("CONFIRMED DATASET REQUIREMENTS", call.system_message)
            self.assertIn(self.data["constraints"], call.system_message)
        self.assertNotEqual(first.seed, retry.seed)

    def test_nested_builder_and_trigger_repairs_share_one_budget(self):
        self.brief["input"]["trigger"] = "reader_token"
        self.scripts["final"] = [self.loop(), "Alex reads without the required token.", self.loop(), "reader_token Alex reads."]
        result = self.write_prompts()
        self.assertFalse(result[0]["prompt"])
        self.assertEqual(result[0]["attempts"], 3)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.scripts["final"]), 1)

    def test_invalid_response_after_loop_is_not_accepted(self):
        self.scripts["dataset_v2:understanding"] = [self.loop(), "not json", "{}"]
        with self.assertRaises(ValueError):
            understanding.understand(self.config, self.request, self.data, progress=lambda _message: None)
        self.assertEqual(len(self.calls), 3)

    def test_cancellation_and_shutdown_win_over_recovery(self):
        for operation in (self.write_scenes, self.write_prompts):
            for stopped in ("cancelled", "shutdown"):
                with self.subTest(operation=operation.__name__, stopped=stopped):
                    self.calls.clear()
                    job = Job()
                    def stop(_instruction):
                        if stopped == "cancelled":
                            job.cancel_requested = True
                        else:
                            job.stopping = True
                        raise self.loop()
                    stage = "dataset_v2:scenes" if operation == self.write_scenes else "final"
                    self.scripts[stage] = [stop]
                    with self.assertRaises((JobCancelled, ValueError)):
                        operation(checkpoint=job.checkpoint)
                    self.assertEqual(len(self.calls), 1)

    def test_unrelated_backend_errors_are_not_retried_or_swallowed(self):
        for operation in (self.write_scenes, self.write_prompts):
            for error in (BackendConfigurationError("invalid config"), BackendGenerationError("engine unavailable")):
                with self.subTest(operation=operation.__name__, error=type(error).__name__):
                    self.calls.clear()
                    stage = "dataset_v2:scenes" if operation == self.write_scenes else "final"
                    self.scripts[stage] = [error]
                    with self.assertRaises(type(error)) as caught:
                        operation()
                    self.assertIs(caught.exception, error)
                    self.assertEqual(len(self.calls), 1)

    def test_two_loops_in_a_final_prompt_are_recovered_and_the_loop_text_is_never_kept(self):
        self.scripts["final"] = [self.loop(), self.loop()]
        result = self.write_prompts()
        self.assertTrue(result[0]["prompt"])
        self.assertEqual(len([call for call in self.calls if call.diagnostic_stage == "final"]), 3)
        self.assertNotIn("Incomplete response", json.dumps(result))

    def test_builder_format_repairs_cannot_accept_invalid_output_after_recovery(self):
        self.brief["settings"]["target"] = "Qwen Image 2.1"
        self.scripts["final"] = [self.loop(), "invalid candidate"]
        self.scripts["final:format_retry"] = ["invalid candidate"]
        with patch("goated_prompter.features.builder.service.normalize_workflow_output",
                   side_effect=[WorkflowFormatError("bad format"), WorkflowFormatError("bad format"), "Alex reads."]):
            result = self.write_prompts(2)
        self.assertFalse(result[0]["prompt"])
        self.assertEqual(result[0]["reason"], "invalid_output_after_recovery")
        self.assertEqual(result[0]["attempts"], 3)
        self.assertEqual(result[1]["prompt"], "Alex reads.")
        self.assertEqual(len(self.calls), 4)

    def test_builder_audit_loop_does_not_regenerate_the_successful_writer(self):
        self.config["semantic_validation"] = True
        stage = "semantic:review:builder:final"
        passed = json.dumps({"checks": {key: "pass" for key in ("action_fidelity", "scene_fidelity", "constraint_validity")},
                             "issues": [], "accepted_facts": []})
        self.scripts[stage] = [self.loop(), passed]
        result = self.write_prompts()
        self.assertTrue(result[0]["prompt"])
        counts = Counter(call.diagnostic_stage for call in self.calls)
        self.assertEqual(counts["final"], 1)
        self.assertEqual(counts[stage], 2)

    def test_builder_audit_exhaustion_continues_to_the_next_scene(self):
        self.config["semantic_validation"] = True
        stage = "semantic:review:builder:final"
        passed = json.dumps({"checks": {key: "pass" for key in ("action_fidelity", "scene_fidelity", "constraint_validity")},
                             "issues": [], "accepted_facts": []})
        self.scripts[stage] = [self.loop(), self.loop(), self.loop(), passed]
        result = self.write_prompts(2)
        self.assertFalse(result[0]["prompt"])
        self.assertEqual(result[0]["stage"], stage)
        self.assertEqual(result[0]["attempts"], 3)
        self.assertTrue(result[1]["prompt"])
        counts = Counter(call.diagnostic_stage for call in self.calls)
        self.assertEqual(counts["final"], 2)
        self.assertEqual(counts[stage], 4)

    def test_empty_builder_response_after_loop_is_not_accepted(self):
        self.scripts["final"] = [self.loop(), "", "Alex reads."]
        result = self.write_prompts(2)
        self.assertFalse(result[0]["prompt"])
        self.assertEqual(result[0]["reason"], "invalid_output_after_recovery")
        self.assertTrue(result[1]["prompt"])

    def test_job_result_preserves_successes_and_failed_items_after_the_run(self):
        self.brief["input"]["amount"] = 3
        self.scripts["final"] = ["Alex reads by the window.", self.loop(), self.loop(), self.loop(), "Alex reads by the lamp."]
        job = Job()
        with patch.object(runner, "create_backend", return_value=self.backend):
            runner.run_dataset_v2_scenes(None, job, self.request, self.config, {"brief": self.brief})
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(len(job.result["scenes"]), 3)
        self.assertEqual([row["index"] for row in job.result["prompts"]], [1, 2, 3])
        self.assertEqual([bool(row["prompt"]) for row in job.result["prompts"]], [True, False, True])
        self.assertEqual(job.result["prompts"][1]["attempts"], 3)
        self.assertTrue(any("failed; continuing" in event["message"] for event in job.events))
