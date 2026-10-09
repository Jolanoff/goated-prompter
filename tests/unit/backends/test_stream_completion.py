import json
import unittest

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from local_app import Job
import local_app
from pathlib import Path
import tempfile
from goated_prompter.core import GoatedPrompterRequest
from unittest.mock import Mock


def event(text="", reason=None):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": reason}]}) + "\n\n").encode()


class StreamCompletionTests(unittest.TestCase):
    def setUp(self):
        self.backend = OpenAICompatibleBackend({"base_url": "http://localhost:1/v1", "model": "test"})

    def check_failure(self, lines, state, partial="partial"):
        with self.assertRaises(BackendGenerationError) as raised:
            self.backend._stream_response(iter(lines), False)
        self.assertEqual(raised.exception.completion_state, state)
        self.assertEqual(raised.exception.partial_text, partial)
        return raised.exception

    def test_clean_stop_does_not_wait_for_done_or_delayed_tail(self):
        def lines():
            yield event("answer", "stop")
            self.fail("reader waited for a delayed trailing event")
        self.assertEqual(self.backend._stream_response(lines(), False), "answer")

    def test_abrupt_eof_and_done_without_reason_are_not_success(self):
        self.check_failure([event("partial")], "interrupted")
        self.check_failure([event("partial"), b"data: [DONE]\n\n"], "interrupted")

    def test_malformed_event_preserves_partial(self):
        self.check_failure([event("partial"), b"data: {oops}\n"], "malformed_stream")
        self.check_failure([event("partial"), b"data: []\n"], "malformed_stream")

    def test_token_limit_never_success(self):
        error = self.check_failure([event("partial", "length")], "token_limit")
        self.assertEqual(error.finish_reason, "length")

    def test_disconnect_preserves_partial(self):
        def lines():
            yield event("partial")
            raise ConnectionResetError("provider disconnected")
        with self.assertRaises(BackendGenerationError) as raised:
            self.backend._stream_response(lines(), False)
        self.assertEqual(raised.exception.completion_state, "interrupted")
        self.assertEqual(raised.exception.partial_text, "partial")

    def test_cancellation_preserves_partial(self):
        def lines():
            yield event("partial")
            raise BackendGenerationError("cancelled", completion_state="cancelled")
        with self.assertRaises(BackendGenerationError) as raised:
            self.backend._stream_response(lines(), False)
        self.assertEqual(raised.exception.completion_state, "cancelled")
        self.assertEqual(raised.exception.partial_text, "partial")

    def test_trace_does_not_invent_stop(self):
        job = Job()
        job.record_llm_activity({"type": "request"})
        job.record_llm_activity({"type": "response_delta", "text": "partial"})
        job.record_llm_activity({"type": "response_complete"})
        trace = job.snapshot()["llm_trace"]
        self.assertIsNone(trace["finish_reason"])
        self.assertEqual(trace["completion_state"], "interrupted")

    def test_transport_cancel_preferred_to_model_process_kill(self):
        calls = []
        job = Job()
        job.set_interrupt(lambda: calls.append("kill"))
        job.register_interrupt(lambda: calls.append("transport"))
        job.cancel()
        self.assertEqual(calls, ["transport"])

    def test_partial_diagnostics_survive_retry_but_not_ram_release(self):
        job = Job()
        job.record_llm_activity({"type": "request", "stage": "first"})
        job.record_llm_activity({"type": "response_delta", "text": "partial"})
        job.record_llm_activity({"type": "error", "message": "disconnected", "completion_state": "interrupted"})
        job.record_llm_activity({"type": "request", "stage": "retry"})
        diagnostic = job.snapshot()["partial_responses"][0]
        self.assertEqual(diagnostic["partial_text"], "partial")
        self.assertEqual(diagnostic["completion_state"], "interrupted")
        job.clear_private_data()
        self.assertEqual(job.snapshot()["partial_responses"], [])

    def test_interrupted_builder_job_is_not_failed_success_or_a_finished_prompt(self):
        class InterruptedService:
            def __init__(self, **kwargs):
                pass
            def generate(self, request):
                raise BackendGenerationError("Unexpected EOF", completion_state="interrupted", partial_text="partial")
        with tempfile.TemporaryDirectory() as directory:
            state = local_app.LocalState(lambda: {"backend": "mock"}, InterruptedService, Path(directory) / "settings.json")
            job = Job()
            state.execute(job, GoatedPrompterRequest(idea="a cup"), {"backend": "mock"}, False)
        self.assertEqual(job.status, "interrupted")
        self.assertEqual(job.completion_state, "interrupted")
        self.assertIsNone(job.result)

    def test_dataset_transport_retry_exhaustion_keeps_original_completion_state(self):
        from goated_prompter.dataset import DatasetService, default_dataset_draft
        from goated_prompter.prompting.dataset import dataset_instruction
        data = {**default_dataset_draft(), "subject": "a person", "trigger": "subject", "amount": 1}
        session = Mock()
        session.generate.side_effect = BackendGenerationError("EOF", completion_state="interrupted", partial_text="partial")
        scene = {"scene": "A person stands beside a table.", "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea="a person"), data, 1, plan_item=scene)
        with self.assertRaises(BackendGenerationError) as raised:
            DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data, 1, lambda _message: None, scene, retries=1)
        self.assertEqual(raised.exception.completion_state, "interrupted")
        self.assertEqual(raised.exception.partial_text, "partial")
        self.assertEqual(session.generate.call_count, 2)
