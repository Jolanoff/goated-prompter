"""Deterministic coverage of fixture reuse, selection and execution safeguards."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from tests.eval import runner
from tests.evaluation import run_supporting_planning as supporting
from tests.gpu.run import main as gpu_main
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support import artifacts, safety
from tests.support.dataset import saved_scene, valid_draft
from tests.support.scenarios import select_cases


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": str(index), "workflows": ["builder", "dataset"], "anchors": {"scene": [str(index)]}}
                      for index in range(10)]

    def test_fixed_and_seeded_selection_are_repeatable_without_global_random_changes(self):
        state = random.getstate()
        self.assertEqual(select_cases(self.cases), self.cases)
        selected = select_cases(self.cases, workflow="dataset", seed=73, limit=3)
        self.assertEqual(selected, select_cases(self.cases, workflow="dataset", seed=73, limit=3))
        self.assertNotEqual(selected, select_cases(self.cases, workflow="dataset", seed=74, limit=3))
        self.assertEqual(random.getstate(), state)
        selected[0]["anchors"]["scene"].clear()
        self.assertTrue(all(case["anchors"]["scene"] for case in self.cases))

    def test_unknown_cases_incompatible_workflows_and_empty_selection_are_errors(self):
        for kwargs in ({"case_ids": ["missing"]}, {"workflow": "minimax"}, {"case_ids": ["0"], "workflow": "minimax"}, {"limit": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                select_cases(self.cases, **kwargs)
        self.assertEqual(select_cases(supporting.CASES, ["hoop"], "builder")[0]["id"], "hoop")

    def test_domain_fixtures_return_independent_mutable_defaults(self):
        for fixture in (dataset_understanding_fixture, dataset_idea_fixture, saved_scene, valid_draft):
            with self.subTest(fixture=fixture.__name__):
                first, second = fixture(), fixture()
                self.assertEqual(first, second)
                self.assertIsNot(first, second)
                for key, value in first.items():
                    if isinstance(value, list):
                        value.append("test-only mutation")
                        self.assertNotEqual(value, second[key])


class ExecutionSafetyTests(unittest.TestCase):
    def test_synthetic_storage_restores_environment_and_removes_owned_files_on_failure(self):
        previous = os.environ.get("GOATED_PROMPTER_USER_DIR")
        previous_temp = tempfile.tempdir
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "interrupted"):
                with safety.synthetic_storage(Path(directory)) as storage:
                    self.assertEqual(Path(tempfile.gettempdir()), storage)
                    self.assertEqual(os.environ["GOATED_PROMPTER_USER_DIR"], str(storage / "directors"))
                    (storage / "synthetic.json").write_text("{}")
                    raise ValueError("interrupted")
            self.assertFalse(storage.exists())
        self.assertEqual(os.environ.get("GOATED_PROMPTER_USER_DIR"), previous)
        self.assertEqual(tempfile.tempdir, previous_temp)

    def test_privacy_guard_checks_synthetic_repository_storage_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(safety, "ROOT", Path(directory)):
            for event in ("open", "os.listdir", "os.scandir"):
                with self.subTest(event=event), self.assertRaises(PermissionError):
                    safety.private_storage_guard(event, (str(Path(directory) / "data" / "synthetic.json"),))
            safety.private_storage_guard("open", (str(Path(directory) / "tests" / "fixture.json"),))
            safety.private_storage_guard("open", (1,))

    def test_artifact_paths_reject_traversal_outside_task_and_existing_results(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(artifacts, "ROOT", Path(directory)):
            for task in ("../other", "issue/45", "", "Issue-45"):
                with self.subTest(task=task), self.assertRaises(ValueError):
                    artifacts.task_paths(task, "gpu")
            results, scratch = artifacts.task_paths("fixture", "gpu")
            output = results / "results.json"
            self.assertEqual(artifacts.new_output(output, "fixture", "gpu"), output)
            self.assertEqual(artifacts.new_output(scratch / "run.json", "fixture", "gpu"), scratch / "run.json")
            with self.assertRaises(ValueError):
                artifacts.new_output(Path(directory) / "quality-artifacts" / "baselines" / "old.json", "fixture", "gpu")
            results.mkdir(parents=True)
            output.write_text("retained evidence")
            with self.assertRaises(ValueError):
                artifacts.new_output(output, "fixture", "gpu")
            self.assertEqual(output.read_text(), "retained evidence")
            def redirected(path):
                if path.is_relative_to(results):
                    return Path(directory) / "quality-artifacts" / "baselines" / path.relative_to(results)
                return path
            with patch.object(Path, "resolve", autospec=True, side_effect=redirected), self.assertRaises(ValueError):
                artifacts.new_output(results / "fresh.json", "fixture", "gpu")


class GPUCommandTests(unittest.TestCase):
    def call(self, argv):
        with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()):
            result = gpu_main(argv)
        return result, stdout.getvalue()

    def test_help_explains_the_shared_dispatch_and_existing_runner_options(self):
        with redirect_stdout(StringIO()) as stdout, self.assertRaises(SystemExit) as stopped:
            gpu_main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("--probe supporting-planning", stdout.getvalue())
        self.assertIn("--workflow", stdout.getvalue())
        self.assertIn("--max-runs", stdout.getvalue())

    def test_dry_run_selects_each_workflow_without_reading_config_or_starting_models(self):
        with patch("goated_prompter.backends.llama_cpp_process.LlamaCppProcessManager.acquire") as acquire, \
                patch.object(runner, "live_case") as live:
            for workflow, case in (("builder", "object"), ("dataset", "object"), ("minimax", "motion")):
                with self.subTest(workflow=workflow):
                    _, text = self.call(["--dry-run", "--workflow", workflow, "--case", case, "--seed", "73", "--config", "does-not-exist.json"])
                    payload = json.loads(text)
                    self.assertFalse(payload["inference"])
                    self.assertEqual(payload["scenario_seed"], 73)
                    self.assertEqual([case["id"] for case in payload["cases"]], [case])
            live.assert_not_called()
            acquire.assert_not_called()

    def test_live_opt_in_workflow_and_run_ceiling_are_required_before_execution(self):
        base = ["--workflow", "builder", "--case", "object"]
        with patch.object(runner, "live_case") as live:
            for argv in (base, ["--dry-run"], base + ["--allow-live", "--config", "missing.json", "--task-key", "fixture", "--max-runs", "0"],
                         base + ["--allow-live", "--config", "missing.json", "--task-key", "fixture", "--max-runs", "1", "--repeats", "2"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as stopped:
                    self.call(argv)
                self.assertEqual(stopped.exception.code, 2)
            live.assert_not_called()

    def test_gpu_dispatch_reuses_both_existing_runners(self):
        with patch.object(runner, "main", return_value=7) as workflow:
            self.assertEqual(gpu_main(["--workflow", "dataset", "--dry-run"]), 7)
            workflow.assert_called_once_with(["--workflow", "dataset", "--dry-run"], gpu=True)
        with patch.object(supporting, "main", return_value=8) as planning:
            self.assertEqual(gpu_main(["--probe", "supporting-planning", "--workflow", "minimax", "--dry-run"]), 8)
            planning.assert_called_once_with(["--workflow", "minimax", "--dry-run"], gpu=True)

    def run_fixture(self, root, config):
        config_path = root / "endpoint.json"
        config_path.write_text(json.dumps(config))
        argv = ["--workflow", "builder", "--case", "object", "--allow-live", "--config", str(config_path),
                "--task-key", "fixture", "--max-runs", "2", "--repeats", "2"]
        with patch.object(artifacts, "ROOT", root), patch.object(runner, "run_metadata", return_value={"run_id": "synthetic-command-test"}):
            return self.call(argv)

    def test_real_engine_command_refuses_mock_and_managed_backends(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "live_case") as live:
            for backend in ("mock", "debug", "local_llama_cpp"):
                with self.subTest(backend=backend), self.assertRaises(SystemExit) as stopped:
                    self.run_fixture(Path(directory), {"backend": backend})
                self.assertEqual(stopped.exception.code, 2)
            live.assert_not_called()

    def test_declining_continuation_stops_after_one_result_and_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runner, "live_case", return_value={"sample_id": "fixed", "workflow": "builder", "prompt": "Synthetic output."}) as live, \
                patch("builtins.input", return_value="no"):
            root = Path(directory)
            self.run_fixture(root, {"backend": "openai_compatible"})
            live.assert_called_once()
            output = root / "quality-artifacts/tasks/fixture/gpu/results.json"
            result = json.loads(output.read_text())
            self.assertEqual(len(result["records"]), 1)
            self.assertEqual(result["selected_case_ids"], ["object"])
            self.assertEqual(list((root / "quality-artifacts/temp/fixture/gpu").iterdir()), [])
            with self.assertRaises(SystemExit):
                self.run_fixture(root, {"backend": "openai_compatible"})
            self.assertEqual(json.loads(output.read_text()), result)

    def test_execution_failure_stops_without_prompting_for_another_run(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runner, "live_case", return_value={"sample_id": "failed", "workflow": "builder", "error": "Synthetic failure"}) as live, \
                patch("builtins.input") as approval:
            result, _ = self.run_fixture(Path(directory), {"backend": "openai_compatible"})
            self.assertEqual(result, 1)
            live.assert_called_once()
            approval.assert_not_called()

    def test_explicit_workflow_runs_once_even_if_custom_corpus_repeats_its_name(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runner, "live_case", return_value={"sample_id": "fixed", "workflow": "builder", "prompt": "Synthetic output."}) as live, \
                patch.object(runner, "run_metadata", return_value={"run_id": "synthetic-ceiling-test"}), \
                patch.object(artifacts, "ROOT", Path(directory)), patch("builtins.input") as approval:
            root = Path(directory)
            corpus = root / "corpus.json"
            corpus.write_text(json.dumps({"cases": [{"id": "fixed", "workflows": ["builder", "builder"]}], "novelty": []}))
            config = root / "endpoint.json"
            config.write_text(json.dumps({"backend": "openai_compatible"}))
            self.call(["--workflow", "builder", "--corpus", str(corpus), "--case", "fixed", "--allow-live",
                       "--config", str(config), "--task-key", "fixture", "--max-runs", "1"])
            live.assert_called_once()
            approval.assert_not_called()

    def test_supporting_probe_dry_run_and_ceiling_do_not_start_generation(self):
        base = ["--probe", "supporting-planning", "--workflow", "builder", "--case", "hoop"]
        with patch.object(supporting.GoatedPrompterService, "generate") as generate, \
                patch.object(supporting, "get_process_manager") as manager:
            _, text = self.call(base + ["--dry-run"])
            self.assertEqual(json.loads(text)["conditions"], ["Direct", "Auto"])
            with self.assertRaises(SystemExit):
                self.call(base + ["--allow-live", "--config", "missing.json", "--task-key", "fixture", "--max-runs", "1"])
            generate.assert_not_called()
            manager.assert_not_called()
