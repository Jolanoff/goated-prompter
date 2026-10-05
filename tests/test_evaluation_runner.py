import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from tests.eval.runner import live_case, load_replay, novelty_cases
from tests.eval.metrics import measure
from tests.test_minimax import BASE


class EvaluationRunnerTests(unittest.TestCase):
    def test_directory_replay_keeps_workflow_runs_and_skips_raw_support_fixtures(self):
        run = {"run_id": "frozen", "records": [{"sample_id": "cup", "workflow": "builder", "prompt": "A cup."}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.json").write_text(json.dumps(run), encoding="utf-8")
            (root / "scene.json").write_text(json.dumps({"raw": "scene text"}), encoding="utf-8")
            (root / "audit.json").write_text(json.dumps({"run_id": "audit", "records": [{"id": "cap", "raw": "audit response"}]}), encoding="utf-8")
            result = load_replay(root)
            self.assertEqual(result["sources"], ["frozen"])
            self.assertEqual(result["records"], run["records"])
            self.assertEqual(result["skipped_supporting_fixtures"], ["audit.json", "scene.json"])
            self.assertEqual(load_replay(root / "run.json"), run)

    def test_replay_rejects_malformed_workflow_run_instead_of_hiding_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bad.json"
            for run, error in (
                ({"records": [{"sample_id": "cup", "workflow": "builder"}]}, "run_id"),
                ({"run_id": "bad", "records": [{"workflow": "builder"}]}, "sample_id"),
                ({"run_id": "bad", "records": "not a list"}, "records"),
            ):
                with self.subTest(run=run):
                    path.write_text(json.dumps(run), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        load_replay(root)

    def test_replay_rejects_empty_directory_and_explicit_raw_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "No evaluation runs"):
                load_replay(root)
            path = root / "raw.json"
            path.write_text(json.dumps({"raw": "scene text"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "run_id"):
                load_replay(path)
            with self.assertRaisesRegex(ValueError, "No evaluation runs"):
                load_replay(root)

    def test_committed_fixture_directory_replays_only_evaluation_samples(self):
        result = load_replay(Path(__file__).parent / "eval/fixtures/model_outputs")
        self.assertEqual(len(result["records"]), 10)
        self.assertEqual({row["workflow"] for row in result["records"]}, {"builder", "dataset", "minimax"})
        self.assertIn("complex_pose_fidelity.json", result["skipped_supporting_fixtures"])
        self.assertIn("semantic_constraint_reviews.json", result["skipped_supporting_fixtures"])

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
