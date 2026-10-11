"""Frozen replay loader contracts without production-service execution."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.eval.runner import load_replay
from tests.support.paths import TESTS


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
        result = load_replay(TESTS / "eval/fixtures/model_outputs")
        self.assertEqual(len(result["records"]), 10)
        self.assertEqual({row["workflow"] for row in result["records"]}, {"builder", "dataset", "minimax"})
        self.assertIn("semantic_constraint_reviews.json", result["skipped_supporting_fixtures"])
