import json
from pathlib import Path
import unittest

from tests.eval.metrics import annotation_template, measure, summarize
from tests.eval.report import markdown, regressions


class EvaluationTests(unittest.TestCase):
    def test_current_compact_plan_is_valid_in_idea_evaluation(self):
        from tests.support.dataset import saved_scene
        row = self.sample(workflow="dataset", output_kind="ideas", scene_plan=[saved_scene()], prompt="")
        measured = measure(row)
        self.assertTrue(measured["format_valid"])
        self.assertTrue(measured["accepted"])

    def test_obsolete_unchecked_plan_is_not_valid_in_idea_evaluation(self):
        row = self.sample(workflow="dataset", output_kind="ideas", scene_plan=[{
            "index": 1, "input": "", "idea": "Old idea", "scene": "Old unchecked scene"}], prompt="")
        self.assertFalse(measure(row)["format_valid"])

    def sample(self, **patch):
        return {"sample_id": "one", "workflow": "builder", "prompt": "A cup on a table.",
                "completion_state": "completed", "anchors": {"scene": ["cup"], "action": [], "pose": [], "constraint": []}, **patch}

    def test_missing_review_not_success(self):
        report = summarize([self.sample()])
        self.assertFalse(report["semantic_review_complete"])
        self.assertIsNone(report["workflows"]["builder"]["averages"]["scene_fidelity"])
        self.assertIn("not reviewed", markdown({"run_id": "test", **report}))

    def test_missing_call_history_does_not_invent_first_pass_validity_or_cost(self):
        measured = measure(self.sample())
        self.assertIsNone(measured["first_pass_valid"])
        self.assertIsNone(measured["calls_per_result"])
        self.assertIsNone(measured["repair_rate"])

    def test_cost_counts_reviews_but_output_repairs_exclude_transport_and_self_review(self):
        calls = [{"stage": stage, "finish_reason": "stop"} for stage in (
            "dataset:scene_planner", "dataset:1", "semantic:review:dataset:final:1",
            "semantic:review:dataset:final:1:format_retry", "dataset:1:transport_retry_1", "dataset:1:format_retry_2")]
        measured = measure(self.sample(workflow="dataset", calls=calls, trigger="cup"))
        self.assertEqual(measured["model_calls"], 6)
        self.assertEqual(measured["calls_per_result"], 6)
        self.assertEqual(measured["repair_calls"], 1)
        self.assertEqual(measured["transport_retry_calls"], 1)
        self.assertTrue(measured["repair_rate"])
        self.assertTrue(measured["trigger_fidelity"])

    def test_trigger_fidelity_measures_exact_case_sensitive_wording(self):
        self.assertTrue(measure(self.sample(trigger="cup"))["trigger_fidelity"])
        self.assertFalse(measure(self.sample(trigger="Cup"))["trigger_fidelity"])
        self.assertIsNone(measure(self.sample())["trigger_fidelity"])

    def test_pipeline_repair_is_not_hidden_by_a_valid_first_writer_attempt(self):
        calls = [{"stage": "dataset:scene_composer:repair", "finish_reason": "stop"},
                 {"stage": "dataset:1", "finish_reason": "stop", "validation_events": [
                     {"type": "validation", "workflow": "dataset", "attempt": 0, "accepted": True}]}]
        self.assertFalse(measure(self.sample(workflow="dataset", calls=calls))["first_pass_valid"])

    def test_missing_prompt_is_a_trigger_failure_not_an_unmeasured_success(self):
        self.assertIs(measure(self.sample(prompt="", trigger="cup", error="writer failed"))["trigger_fidelity"], False)

    def test_self_review_annotations_cannot_pass_independent_review_gate(self):
        row = self.sample()
        label = annotation_template([row])[0]
        label.update(reviewer="writer model", review_kind="self_review", semantic_repetition=False, target_usability=True)
        label["anchors"]["scene"]["cup"] = True
        report = summarize([row], [label])
        self.assertTrue(report["samples"][0]["review_complete"])
        self.assertFalse(report["semantic_review_complete"])
        self.assertFalse(report["samples"][0]["independent_review"])
        label.update(reviewer="external human", review_kind="human")
        self.assertTrue(summarize([row], [label])["semantic_review_complete"])

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
        baseline = {"samples": [{"sample_id": "one", "review_complete": True, "review_kind": "human", "scene_fidelity": 1, "prompt_words": 10}]}
        report = {"samples": [{"sample_id": "one", "review_complete": True, "review_kind": "human", "scene_fidelity": .5, "prompt_words": 1000}]}
        self.assertIn("scene_fidelity regressed", regressions(report, baseline)[0])

    def test_regression_comparison_requires_explicit_independent_provenance(self):
        for kind in (None, "", "unspecified", "self_review", "exploratory"):
            row = {"sample_id": "one", "review_complete": True, "review_kind": kind}
            self.assertTrue(regressions({"samples": [row]}, {"samples": [row]}))

    def test_reviewed_usability_failure_is_not_hidden_by_valid_format_and_anchors(self):
        row = self.sample()
        label = annotation_template([row])[0]
        label.update(reviewer="unit-test synthetic", target_usability=False, semantic_repetition=False)
        label["anchors"]["scene"]["cup"] = True
        self.assertEqual(summarize([row], [label])["workflows"]["builder"]["failures"], ["one"])
