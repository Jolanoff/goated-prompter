from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from tests.eval.runner import live_case
from tests.eval.metrics import measure
from tests.support.minimax import BASE


class EvaluationRunnerTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(target="Generic", length="Detailed", director="general_director",
            creativity="Balanced", planning="Direct")

    def test_real_workflow_entrypoints_use_frozen_responses_without_inference(self):
        calls = []
        scene = "eval_subject is a chipped blue ceramic cup on a table."
        def generate(backend, instruction):
            calls.append(instruction)
            text = BASE if instruction.diagnostic_stage.startswith("minimax") else scene
            backend.emit_activity("request", stage=instruction.diagnostic_stage, parameters={"temperature": instruction.temperature}, messages=instruction.to_messages())
            backend.emit_activity("response_delta", text=text)
            backend.emit_activity("response_complete", finish_reason="stop")
            return text
        case = {"id": "cup", "request": "A chipped blue ceramic cup on a table.", "anchors": {}}
        with patch.object(MockBackend, "generate", generate):
            rows = [live_case(case, workflow, {"backend": "mock"}, self.args()) for workflow in ("builder", "minimax")]
        self.assertTrue(calls)
        for row in rows:
            self.assertNotIn("error", row)
            self.assertEqual(row["completion_state"], "completed")
            self.assertEqual(row["finish_reason"], "stop")
            self.assertTrue(measure(row)["format_valid"])
            self.assertGreaterEqual(row["latency_seconds"], 0)
        self.assertEqual(rows[0]["trigger"], "eval_subject")
        self.assertTrue(measure(rows[0])["trigger_fidelity"])
