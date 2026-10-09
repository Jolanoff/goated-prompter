"""Supporting-probe wiring with synthetic service responses, never inference."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.eval.runner import load_replay
from tests.evaluation import run_supporting_planning as supporting
from tests.support import artifacts


class SupportingRunnerTests(unittest.TestCase):
    def test_legacy_probe_preserves_original_requests_modes_and_output_shape(self):
        requests = []

        class Service:
            def __init__(self, config):
                self.activity = config["_activity_callback"]

            def generate(self, request):
                requests.append(request)
                self.activity({"type": "request", "stage": "final", "parameters": {}, "messages": []})
                self.activity({"type": "response_delta", "text": "Synthetic supporting prompt."})
                self.activity({"type": "response_complete", "finish_reason": "stop"})
                return SimpleNamespace(prompt="Synthetic supporting prompt.", planning_status=request.planning_mode)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(supporting, "GoatedPrompterService", Service), \
                patch.object(supporting, "get_process_manager") as manager, redirect_stdout(StringIO()):
            config = Path(directory) / "endpoint.json"
            config.write_text(json.dumps({"backend": "openai_compatible"}))
            output = Path(directory) / "legacy.json"
            supporting.main(["--config", str(config), "--case", "hoop", "--artifacts", str(output)])
            records = json.loads(output.read_text())
            self.assertIsInstance(records, list)
            self.assertEqual([request.planning_mode for request in requests], ["Direct", "Auto"])
            self.assertTrue(all(request.idea == supporting.CASES[0]["request"] for request in requests))
            self.assertEqual([record["mode"] for record in records], ["Direct", "Auto"])
            self.assertEqual(records[0]["calls"][0]["output"], "Synthetic supporting prompt.")
            self.assertEqual(records[0]["calls"][0]["raw"], records[0]["calls"][0]["output"])
            manager.return_value.request_unload.assert_called_once_with()

    def test_gpu_probe_preserves_minimax_inputs_and_creates_replayable_records(self):
        inputs = []

        class Service:
            def __init__(self, config, checkpoint):
                self.activity = config["_activity_callback"]

            def run(self, request, data, progress):
                inputs.append(data)
                self.activity({"type": "request", "stage": "minimax:writer", "parameters": {}, "messages": []})
                self.activity({"type": "response_delta", "text": "Synthetic MiniMax output."})
                self.activity({"type": "response_complete", "finish_reason": "stop"})
                return {"prompt": "Synthetic MiniMax output.", "planning_status": data["planning_mode"]}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(supporting, "MiniMaxService", Service), \
                patch.object(supporting, "get_process_manager") as manager, \
                patch.object(supporting, "run_metadata", return_value={"run_id": "synthetic-supporting-test"}), \
                patch.object(artifacts, "ROOT", Path(directory)), \
                patch("builtins.input", return_value="yes"), redirect_stdout(StringIO()):
            config = Path(directory) / "endpoint.json"
            config.write_text(json.dumps({"backend": "openai_compatible"}))
            supporting.main(["--config", str(config), "--case", "motion", "--workflow", "minimax",
                             "--allow-live", "--task-key", "fixture", "--max-runs", "2"], gpu=True)
            output = Path(directory) / "quality-artifacts/tasks/fixture/gpu/results.json"
            result = load_replay(output)
            self.assertEqual([record["planning"] for record in result["records"]], ["Direct", "Auto"])
            self.assertTrue(all(record["workflow"] == "minimax" for record in result["records"]))
            self.assertTrue(all(data["duration_seconds"] == 10 and data["references"] == [] for data in inputs))
            self.assertTrue(all(data["user_request"] == supporting.CASES[2]["request"] for data in inputs))
            self.assertEqual(len({record["sample_id"] for record in result["records"]}), 2)
            manager.assert_not_called()
