import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from tests.eval.runner import live_case, novelty_cases
from tests.eval.metrics import measure
from tests.support.minimax import BASE
from tests.helpers import dataset_understanding_fixture, dataset_idea_fixture


class EvaluationRunnerTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(target="Generic", length="Detailed", director="general_director",
            creativity="Balanced", planning="Direct", history="on")

    def test_real_workflow_entrypoints_use_frozen_responses_without_inference(self):
        calls = []
        def generate(backend, instruction):
            calls.append(instruction)
            if instruction.diagnostic_stage == "dataset:understanding":
                text = json.dumps(dataset_understanding_fixture())
            elif instruction.diagnostic_stage == "dataset:ideas":
                text = json.dumps([dataset_idea_fixture()])
            elif instruction.diagnostic_stage == "dataset:build_scene":
                text = json.dumps({"scene": "A chipped blue cup on a table.", "self_check": "PASS"})
            else:
                text = BASE if instruction.diagnostic_stage.startswith("minimax") else "eval_subject is a chipped blue ceramic cup on a table."
            backend.emit_activity("request", stage=instruction.diagnostic_stage, parameters={"temperature": instruction.temperature}, messages=instruction.to_messages())
            backend.emit_activity("response_delta", text=text)
            backend.emit_activity("response_complete", finish_reason="stop")
            return text
        case = {"id": "cup", "request": "A chipped blue ceramic cup on a table.", "dataset_type": "Object / product", "anchors": {}}
        with patch.object(MockBackend, "generate", generate), patch("builtins.input", return_value="yes"):
            rows = [live_case(case, workflow, {"backend": "mock"}, self.args()) for workflow in ("builder", "dataset", "minimax")]
        self.assertEqual(len(calls), 6)
        for row in rows:
            self.assertNotIn("error", row)
            self.assertEqual(row["completion_state"], "completed")
            self.assertEqual(row["finish_reason"], "stop")
            self.assertTrue(measure(row)["format_valid"])
            self.assertGreaterEqual(row["latency_seconds"], 0)
        self.assertEqual(rows[0]["effective_request"], rows[1]["effective_request"])

    def test_dataset_evaluation_stops_if_human_declines_understanding(self):
        args = self.args()
        case = {"id": "cup", "request": "A chipped blue cup on a table.", "dataset_type": "Object / product", "anchors": {}}
        def generate(backend, instruction):
            self.assertEqual(instruction.diagnostic_stage, "dataset:understanding")
            text = json.dumps(dataset_understanding_fixture())
            backend.emit_activity("request", stage=instruction.diagnostic_stage, parameters={}, messages=instruction.to_messages())
            backend.emit_activity("response_delta", text=text)
            backend.emit_activity("response_complete", finish_reason="stop")
            return text
        with patch.object(MockBackend, "generate", generate), patch("builtins.input", return_value="no"):
            row = live_case(case, "dataset", {"backend": "mock"}, args)
        self.assertIn("stopped before downstream", row["error"])
        self.assertEqual(row["evaluation_scope"], "pipeline")
        self.assertEqual(row["trigger"], "eval_subject")
        self.assertEqual(len(row["calls"]), 1)
        self.assertEqual(row["calls"][0]["stage"], "dataset:understanding")

    def test_dataset_receives_the_same_protected_identity_rules_as_builder(self):
        case = {"id": "portrait", "request": "A person with brown eyes. No jewelry.",
                "rules": "Keep brown eyes", "anchors": {}}
        admitted = {}
        def stop_before_inference(config, request, data):
            admitted.update(request=request, data=data)
            raise ValueError("Synthetic admission capture; no inference.")
        with patch("tests.eval.runner.approve_dataset", side_effect=stop_before_inference):
            row = live_case(case, "dataset", {"backend": "mock"}, self.args())
        self.assertIn("Synthetic admission capture", row["error"])
        for rule in ("Keep brown eyes", "no jewelry", "Include the exact subject identifier eval_subject.",
                     "Do not invent stable identity traits or gender; compatible temporary clothing and scene detail are allowed."):
            with self.subTest(rule=rule):
                self.assertIn(rule, admitted["request"].custom_instructions)
                self.assertIn(rule, admitted["data"]["constraints"])

    def test_novelty_uses_approved_ideation_and_matched_settings(self):
        inputs, histories = [], []
        def run(service, request, data, *callbacks, **kwargs):
            inputs.append(data)
            histories.append(service.idea_history)
            return {"scene_plan": [{"index": index, "idea": f"Action {index}", "scene": f"Scene {index}"} for index in range(1, 11)]}
        with patch("goated_prompter.dataset.DatasetService.run", run), \
                patch("tests.eval.runner.approve_dataset", side_effect=lambda config, request, data: {**data, "_confirmed_intent": dataset_understanding_fixture()}):
            rows = novelty_cases({"id": "workshop", "concept": "Repair workshop", "runs": 5, "amount": 10}, {"backend": "mock"}, self.args())
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(len(row["ideas"]) == 10 for row in rows))
        self.assertTrue(all("_confirmed_intent" in row and row["length"] == "Detailed" for row in inputs))
        self.assertIs(histories[0], histories[-1])
        self.assertIsNotNone(histories[0])
