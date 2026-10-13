"""Each workflow operation has one runner; Builder runs through the same table."""

import types
import unittest

from goated_prompter.contracts import GenerationResult, GoatedPrompterRequest
from goated_prompter.local_jobs import Job
from goated_prompter.workflow_runners import WORKFLOW_RUNNERS, execute_workflow


class FakeService:
    calls = []

    def __init__(self, config, checkpoint):
        self.config = config

    def _result(self, request, text_only):
        FakeService.calls.append(text_only)
        return GenerationResult(prompt="a red bicycle", backend_name="mock", instruction=None,
                                director_preset=request.director_preset)

    def generate(self, request):
        return self._result(request, False)

    def generate_text_only(self, request):
        return self._result(request, True)


class FakeWorkspace:
    def __init__(self, error=None):
        self.error, self.versions = error, []

    def add_version(self, prompt, target, source):
        if self.error:
            raise self.error
        self.versions.append((prompt, target, source))
        return {"current_id": "v1"}


def state(workspace):
    return types.SimpleNamespace(service_factory=FakeService, workspace=workspace)


class WorkflowRunnerTests(unittest.TestCase):
    def setUp(self):
        FakeService.calls = []

    def test_every_admitted_operation_has_a_runner(self):
        self.assertEqual(set(WORKFLOW_RUNNERS), {"builder", "minimax", "dataset_understanding",
                                                 "dataset", "dataset_scenes", "refine"})
        self.assertIs(WORKFLOW_RUNNERS["dataset"], WORKFLOW_RUNNERS["dataset_scenes"])

    def test_unknown_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown workflow operation"):
            execute_workflow(state(FakeWorkspace()), Job(), GoatedPrompterRequest(idea="x"), {}, {"operation": "review"})

    def test_builder_runner_saves_a_version_and_respects_text_only(self):
        for text_only in (False, True):
            with self.subTest(text_only=text_only):
                job, workspace = Job(), FakeWorkspace()
                execute_workflow(state(workspace), job, GoatedPrompterRequest(idea="bicycle"), {},
                                 {"operation": "builder", "text_only": text_only})
                snapshot = job.snapshot()
                self.assertEqual(snapshot["status"], "succeeded")
                self.assertEqual(snapshot["result"]["prompt"], "a red bicycle")
                self.assertEqual(snapshot["result"]["version_id"], "v1")
                self.assertEqual(snapshot["result"]["planning_status"], "direct")
                self.assertEqual(workspace.versions, [("a red bicycle", "Generic", "Builder generation")])
                self.assertEqual(FakeService.calls[-1], text_only)

    def test_builder_history_failure_keeps_the_prompt(self):
        job = Job()
        execute_workflow(state(FakeWorkspace(OSError("disk full"))), job, GoatedPrompterRequest(idea="bicycle"), {},
                         {"operation": "builder", "text_only": False})
        result = job.snapshot()["result"]
        self.assertEqual(result["prompt"], "a red bicycle")
        self.assertIn("version history could not be saved: disk full", result["history_error"])
        self.assertNotIn("version_id", result)


if __name__ == "__main__":
    unittest.main()
