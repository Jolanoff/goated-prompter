"""Seeded random cases, the GPU dry run and baseline/candidate comparison, without inference."""

import contextlib
import copy
import io
import json
import unittest

from tests.gpu import compare as gpu_compare
from tests.gpu.cases import random_cases
from tests.gpu.common import capture, token_usage
from tests.gpu.run import main as gpu_main
from tests.gpu.workflows import WORKFLOWS


def run(prompt, *, revision="a", code="1", engine=None, usage=None):
    call = {"stage": "final", "finish_reason": "stop", "raw": prompt}
    if usage:
        call["usage"] = usage
    return {"run_id": revision, "revision": revision, "code_digest": code, "dirty": False,
            "engine": engine or {"model": "m", "context_size": 8192}, "scenario_seed": 3, "corpus_digest": "c",
            "records": [{"sample_id": "object|builder|Generic|Detailed|general_director|Balanced|Direct|1",
                         "workflow": "builder", "request": "A chipped blue cup.", "anchors": {}, "rules": "",
                         "target": "Generic", "trigger": "eval_subject", "prompt": prompt,
                         "completion_state": "completed", "calls": [call], "latency_seconds": 1.0}]}


class RandomCaseTests(unittest.TestCase):
    def test_same_seed_reproduces_cases_and_records_it(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow):
                cases = random_cases(workflow, 41, 4)
                self.assertEqual(cases, random_cases(workflow, 41, 4))
                self.assertNotEqual([case["request"] for case in cases],
                                    [case["request"] for case in random_cases(workflow, 42, 4)])
                self.assertEqual([case["random"] for case in cases], [{"seed": 41, "index": i} for i in range(1, 5)])
                self.assertTrue(all(case["workflows"] == [workflow] and case["id"].startswith(f"random-{workflow}-41-")
                                    for case in cases))

    def test_minimax_cases_include_camera_direction(self):
        self.assertTrue(all("The camera " in case["request"] for case in random_cases("minimax", 5, 6)))

    def test_random_cases_require_seed_and_positive_count(self):
        with self.assertRaisesRegex(ValueError, "--seed"):
            random_cases("builder", None, 1)
        with self.assertRaisesRegex(ValueError, "positive"):
            random_cases("builder", 1, 0)

    def test_gpu_dry_run_prints_random_cases_without_inference(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            gpu_main(["--dry-run", "--workflow", "dataset", "--random", "2", "--seed", "9"])
        report = json.loads(output.getvalue())
        self.assertFalse(report["inference"])
        self.assertEqual(report["random_cases"]["seed"], 9)
        self.assertEqual([case["id"] for case in report["cases"]], ["random-dataset-9-1", "random-dataset-9-2"])


class CaptureTests(unittest.TestCase):
    def test_usage_is_recorded_only_when_reported(self):
        calls = []
        capture(calls, {"type": "request", "stage": "final"})
        capture(calls, {"type": "response_complete", "finish_reason": "stop",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        capture(calls, {"type": "request", "stage": "repair"})
        capture(calls, {"type": "response_complete", "finish_reason": "stop"})
        self.assertIsNone(token_usage(calls))
        self.assertEqual(token_usage(calls[:1]), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})


class CompareTests(unittest.TestCase):
    def test_trigger_loss_is_a_regression_and_semantics_are_not_evaluated(self):
        report = gpu_compare.compare(run("eval_subject is a chipped blue cup on a table."),
                                     run("A chipped blue cup on a table.", revision="b", code="2"))
        checks = report["samples"][0]["checks"]
        self.assertEqual(checks["trigger_fidelity"]["change"], "regressed")
        self.assertEqual(report["deterministic_checks"]["regressed"], 1)
        self.assertEqual(report["semantic_quality"], "not_evaluated")
        self.assertEqual(report["samples"][0]["semantic_quality"], "not_evaluated")
        self.assertFalse(report["same_code"])

    def test_length_alone_is_descriptive_not_a_regression(self):
        report = gpu_compare.compare(run("eval_subject is a chipped blue cup on a table."),
                                     run("eval_subject is a chipped blue ceramic cup resting on an oak table by a window.",
                                         revision="b", code="2"))
        self.assertEqual(report["deterministic_checks"]["regressed"], 0)
        self.assertEqual(report["deterministic_checks"]["improved"], 0)
        words = report["samples"][0]["descriptive"]["prompt_words"]
        self.assertLess(words["baseline"], words["candidate"])

    def test_token_usage_is_reported_when_available(self):
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        report = gpu_compare.compare(run("eval_subject cup.", usage=usage), run("eval_subject cup.", usage=usage))
        self.assertEqual(report["samples"][0]["token_usage"]["candidate"], usage)
        self.assertTrue(report["same_code"])

    def test_mismatched_runs_are_refused(self):
        baseline = run("eval_subject cup.")
        engine = run("eval_subject cup.", engine={"model": "other", "context_size": 8192})
        seed = run("eval_subject cup.")
        seed["scenario_seed"] = 4
        samples = copy.deepcopy(baseline)
        samples["records"][0]["sample_id"] += "x"
        inputs = copy.deepcopy(baseline)
        inputs["records"][0]["request"] = "A different cup."
        for candidate, message in ((engine, "Engine"), (seed, "seed"), (samples, "Samples differ"), (inputs, "Input differs")):
            with self.subTest(message=message), self.assertRaisesRegex(gpu_compare.ComparisonError, message):
                gpu_compare.compare(baseline, candidate)


if __name__ == "__main__":
    unittest.main()
