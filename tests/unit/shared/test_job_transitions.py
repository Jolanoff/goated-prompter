"""Job outcome transitions owned by Job, matching the snapshots the API already returns."""

import json
import unittest

from goated_prompter.features.dataset.ideas import validate_ideas
from goated_prompter.job_lifecycle import DATASET_CHECKPOINT_KINDS, JOB_FAMILIES, TERMINAL_JOB_STATUSES
from goated_prompter.local_jobs import TERMINAL, Job
from goated_prompter.strict_json import reject_duplicate_keys
from goated_prompter.workflow_output import WorkflowFormatError, normalize_workflow_output


class JobTransitionTests(unittest.TestCase):
    def test_cancelled_outcome(self):
        job = Job()
        before = job.revision
        job.mark_cancelled()
        snapshot = job.snapshot()
        self.assertEqual((snapshot["status"], snapshot["completion_state"]), ("cancelled", "cancelled"))
        self.assertEqual(snapshot["status_reason"], "Generation stopped because cancellation was requested.")
        self.assertEqual(snapshot["events"][-1]["type"], "cancel")
        self.assertIsNotNone(snapshot["finished_at"])
        self.assertEqual(snapshot["revision"], before + 1)

    def test_failed_and_interrupted_outcomes(self):
        for completion_state, status in (("provider_error", "failed"), ("token_limit", "failed"),
                                         ("interrupted", "interrupted")):
            with self.subTest(completion_state=completion_state):
                job = Job()
                before = job.revision
                job.mark_failed("Engine unavailable.", completion_state)
                snapshot = job.snapshot()
                self.assertEqual((snapshot["status"], snapshot["completion_state"]), (status, completion_state))
                self.assertEqual(snapshot["error"], "Engine unavailable.")
                self.assertEqual(snapshot["status_reason"], "Engine unavailable.")
                self.assertEqual(snapshot["events"][-1], {**snapshot["events"][-1], "type": "error",
                                                          "message": "Engine unavailable."})
                self.assertEqual(snapshot["revision"], before + 1)

    def test_abandoned_outcome_is_silent_and_keeps_terminal_jobs(self):
        job = Job()
        before = job.snapshot()
        job.mark_abandoned("Shutdown timeout.")
        after = job.snapshot()
        self.assertEqual((after["status"], after["completion_state"], after["error"]),
                         ("interrupted", "interrupted", "Shutdown timeout."))
        self.assertEqual((after["revision"], after["events"]), (before["revision"], before["events"]))
        finished = Job()
        finished.mark_cancelled()
        finished.mark_abandoned("Shutdown timeout.")
        self.assertEqual(finished.snapshot()["status"], "cancelled")

    def test_pause_and_resume(self):
        job = Job()
        job.request_pause()
        self.assertFalse(job.gate.is_set())
        self.assertEqual(job.snapshot()["status"], "pause_requested")
        job.status = "paused"
        revision = job.revision
        job.request_pause()
        self.assertEqual((job.status, job.revision), ("paused", revision + 1))
        job.resume()
        self.assertTrue(job.gate.is_set())
        self.assertEqual(job.snapshot()["status"], "running")
        self.assertEqual(job.snapshot()["events"][-1]["type"], "status")

    def test_private_activity_is_live_but_checkpointed_events_carry_no_engine_text(self):
        job = Job()
        secret = "SYNTHETIC_PRIVATE_ENTRY"
        job.record_llm_activity({"type": "request", "private_content": True, "stage": "dataset:ideas", "model": "test",
            "messages": [{"role": "system", "content": secret}], "parameters": {"temperature": 0.7}})
        for event_type in ("response_delta", "reasoning_delta"):
            job.record_llm_activity({"type": event_type, "text": secret[:8]})
            job.record_llm_activity({"type": event_type, "text": secret[8:]})
        job.record_llm_activity({"type": "error", "message": f"OpenAI-compatible backend returned HTTP 400: {secret}",
                                 "partial_text": secret, "completion_state": "interrupted", "finish_reason": secret})
        snapshot = job.snapshot()
        trace = snapshot["llm_trace"]
        self.assertTrue(trace["private_content"])
        self.assertEqual(trace["messages"], [{"role": "system", "content": secret}])
        self.assertEqual(trace["output"], secret)
        self.assertEqual(trace["reasoning"], secret)
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["finish_reason"], "other")
        self.assertIn("HTTP 400", trace["issue"])
        self.assertNotIn(secret, trace["issue"])
        self.assertNotIn(secret, json.dumps(snapshot["events"]))
        self.assertTrue(snapshot["partial_responses"][0]["private_content"])
        job.record_llm_activity({"type": "request", "stage": "final", "model": "test", "messages": [], "parameters": {}})
        job.record_llm_activity({"type": "response_delta", "text": "Ordinary public response"})
        job.record_llm_activity({"type": "response_complete", "finish_reason": "stop"})
        self.assertEqual(job.snapshot()["llm_trace"]["output"], "Ordinary public response")
        self.assertEqual(job.snapshot()["llm_trace"]["status"], "complete")
        self.assertNotIn("private_content", job.snapshot()["llm_trace"])


class JobConstantTests(unittest.TestCase):
    def test_constants_have_one_definition(self):
        self.assertEqual(TERMINAL_JOB_STATUSES, frozenset(TERMINAL))
        self.assertEqual(DATASET_CHECKPOINT_KINDS, {"dataset", "dataset_scenes"})
        self.assertLessEqual(DATASET_CHECKPOINT_KINDS, JOB_FAMILIES["dataset"])


class StrictJsonTests(unittest.TestCase):
    def test_hook_keeps_message_and_exception_type(self):
        hook = reject_duplicate_keys("Repeated.", KeyError)
        self.assertEqual(json.loads('{"a": 1, "b": {"a": 2}}', object_pairs_hook=hook), {"a": 1, "b": {"a": 2}})
        with self.assertRaisesRegex(KeyError, "Repeated."):
            json.loads('{"a": 1, "a": 2}', object_pairs_hook=hook)

    def test_workflow_parsers_still_reject_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError, "Ideas returned duplicate JSON keys."):
            validate_ideas('{"ideas": [], "ideas": []}', [1])
        with self.assertRaisesRegex(WorkflowFormatError, "Duplicate JSON keys are not allowed."):
            normalize_workflow_output('{"high_level_description": "a", "high_level_description": "b"}', "Ideogram4")


if __name__ == "__main__":
    unittest.main()
