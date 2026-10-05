import json
from pathlib import Path
import unittest

from tests.eval.metrics import annotation_template, measure, summarize
from tests.eval.report import markdown, regressions


class EvaluationTests(unittest.TestCase):
    def sample(self, **patch):
        return {"sample_id": "one", "workflow": "builder", "prompt": "A cup on a table.",
                "completion_state": "completed", "anchors": {"scene": ["cup"], "action": [], "pose": [], "constraint": []}, **patch}

    def test_missing_review_not_success(self):
        report = summarize([self.sample()])
        self.assertFalse(report["semantic_review_complete"])
        self.assertIsNone(report["workflows"]["builder"]["averages"]["scene_fidelity"])
        self.assertIn("not reviewed", markdown({"run_id": "test", **report}))

    def test_length_does_not_override_failed_anchor(self):
        row = self.sample(prompt="A table. " * 100)
        label = annotation_template([row])[0]
        label.update(reviewer="unit-test synthetic", useful_details={"materials": ["wood", "wood"]})
        label["anchors"]["scene"]["cup"] = False
        measured = measure(row, label)
        self.assertEqual(measured["scene_fidelity"], 0)
        self.assertEqual(measured["useful_detail_facts"], 1)
        self.assertIn("one", summarize([row], [label])["workflows"]["builder"]["failures"])

    def test_leakage_and_forbidden_separate(self):
        self.assertEqual(measure(self.sample(prompt="A person with a hat.", rules="no hats"))["forbidden_content_violations"], 1)
        result = measure(self.sample(prompt="A person without a hat.", rules="no hats"))
        self.assertEqual(result["negative_language_leakage"], 1)
        self.assertEqual(result["forbidden_content_violations"], 0)

    def test_incomplete_and_malformed_are_failures(self):
        self.assertFalse(measure(self.sample(completion_state="interrupted"))["accepted"])
        self.assertTrue(measure(self.sample(completion_state="interrupted"))["format_valid"])
        self.assertFalse(measure(self.sample(target="Ideogram4", prompt="not json"))["format_valid"])

    def test_duplicate_rate_across_runs(self):
        rows = [self.sample(sample_id=str(index), concept="craft", run=index, ideas=["Center clay", "Center clay"]) for index in (1, 2)]
        report = summarize(rows)
        self.assertEqual(report["novelty"]["cross_run_exact_duplicate_rates"]["craft"], .75)

    def test_corpus_has_difficult_cases_and_all_workflows(self):
        corpus = json.loads((Path(__file__).parent / "eval/cases/corpus.json").read_text())
        self.assertGreaterEqual(len(corpus["cases"]), 20)
        self.assertEqual({workflow for row in corpus["cases"] for workflow in row["workflows"]}, {"builder", "dataset", "minimax"})
        self.assertTrue(all(row["runs"] == 5 and row["amount"] == 10 for row in corpus["novelty"]))

    def test_frozen_real_responses_cover_all_workflows_and_do_not_invent_usage(self):
        fixtures = Path(__file__).parent / "eval/fixtures/model_outputs"
        rows = [row for path in fixtures.glob("real_*.json") for row in json.loads(path.read_text(encoding="utf-8"))["records"]]
        report = summarize(rows)
        self.assertEqual(set(report["workflows"]), {"builder", "dataset", "minimax"})
        self.assertFalse(report["semantic_review_complete"])
        self.assertEqual(report["latency"]["measured"], 0)
        self.assertEqual(report["workflows"]["builder"]["negative_language_leakage"], 1)

    def test_current_real_failures_have_raw_calls_and_measured_latency(self):
        fixture = Path(__file__).parent / "eval/fixtures/model_outputs/current_fixed_engine_failures.json"
        run = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(run["source_records"], 39)
        self.assertEqual(run["engine"]["context_size"], 16384)
        self.assertEqual(len(run["records"]), 7)
        self.assertTrue(run["code_digest"])
        self.assertTrue(run["source_sha256"])
        for row in run["records"]:
            self.assertTrue(row["known_failure"])
            self.assertGreater(row["latency_seconds"], 0)
            self.assertTrue(row["calls"])
            for call in row["calls"]:
                self.assertTrue(call["raw"])
                self.assertEqual(call["finish_reason"], "stop")
                self.assertEqual(call["completion_state"], "completed")
        report = summarize(run["records"])
        self.assertEqual(report["latency"]["measured"], 7)
        self.assertEqual(sum(len(result["failures"]) for result in report["workflows"].values()), 7)

    def test_regression_gate_cannot_hide_fidelity_loss_in_more_words(self):
        baseline = {"samples": [{"sample_id": "one", "review_complete": True, "scene_fidelity": 1, "prompt_words": 10}]}
        report = {"samples": [{"sample_id": "one", "review_complete": True, "scene_fidelity": .5, "prompt_words": 1000}]}
        self.assertIn("scene_fidelity regressed", regressions(report, baseline)[0])

    def test_reviewed_usability_failure_is_not_hidden_by_valid_format_and_anchors(self):
        row = self.sample()
        label = annotation_template([row])[0]
        label.update(reviewer="unit-test synthetic", target_usability=False, semantic_repetition=False)
        label["anchors"]["scene"]["cup"] = True
        self.assertEqual(summarize([row], [label])["workflows"]["builder"]["failures"], ["one"])
