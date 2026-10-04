from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from tests.eval.runner import live_case, novelty_cases
from tests.eval.metrics import measure
from tests.test_minimax import BASE


class EvaluationRunnerTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(target="Generic", length="Detailed", director="general_director",
            creativity="Balanced", planning="Direct", style="Photorealistic", variety="Wide", history="on")

    def test_real_workflow_entrypoints_use_frozen_responses_without_inference(self):
        calls = []
        def generate(backend, instruction):
            calls.append(instruction)
            text = BASE if instruction.diagnostic_stage.startswith("minimax") else "eval_subject is a chipped blue ceramic cup on a table."
            backend.emit_activity("request", stage=instruction.diagnostic_stage, parameters={"temperature": instruction.temperature}, messages=instruction.to_messages())
            backend.emit_activity("response_delta", text=text)
            backend.emit_activity("response_complete", finish_reason="stop")
            return text
        case = {"id": "cup", "request": "A chipped blue ceramic cup on a table.", "dataset_type": "Object / product", "anchors": {}}
        with patch.object(MockBackend, "generate", generate):
            rows = [live_case(case, workflow, {"backend": "mock"}, self.args()) for workflow in ("builder", "dataset", "minimax")]
        self.assertEqual(len(calls), 3)
        for row in rows:
            self.assertNotIn("error", row)
            self.assertEqual(row["completion_state"], "completed")
            self.assertEqual(row["finish_reason"], "stop")
            self.assertTrue(measure(row)["format_valid"])
            self.assertGreaterEqual(row["latency_seconds"], 0)
        self.assertEqual(rows[0]["effective_request"], rows[1]["effective_request"])

    def test_novelty_uses_quality_ideation_and_matched_settings(self):
        inputs, histories = [], []
        def run(service, request, data, *callbacks, **kwargs):
            inputs.append(data)
            histories.append(service.idea_history)
            return {"scene_plan": [{"index": index, "idea": f"Action {index}", "scene": f"Scene {index}"} for index in range(1, 11)]}
        with patch("goated_prompter.dataset.DatasetService.run", run):
            rows = novelty_cases({"id": "workshop", "concept": "Repair workshop", "runs": 5, "amount": 10}, {"backend": "mock"}, self.args())
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(len(row["ideas"]) == 10 for row in rows))
        self.assertTrue(all(row["planning_mode"] == "Quality" and row["variety"] == "Wide" and row["length"] == "Detailed" for row in inputs))
        self.assertIs(histories[0], histories[-1])
        self.assertIsNotNone(histories[0])
