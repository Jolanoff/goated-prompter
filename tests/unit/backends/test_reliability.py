"""Regression cases found during code review; no model or private disk data."""

import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend, _response_text
from goated_prompter.backends.base import BackendGenerationError, BackendConfigurationError
from goated_prompter.core import PromptInstruction


class ReliabilityTests(unittest.TestCase):
    def backend(self, **settings):
        return OpenAICompatibleBackend({"base_url": "http://127.0.0.1:1/v1", "model": "test", **settings})

    def stream(self, text="partial", finish=None, done=False):
        lines = [("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}) + "\n").encode()]
        return lines + ([b"data: [DONE]\n"] if done else [])

    def test_abrupt_eof_cannot_emit_a_success_event(self):
        events = []
        with self.assertRaisesRegex(BackendGenerationError, "completion reason"):
            self.backend(_activity_callback=events.append)._stream_response(self.stream(), False)
        self.assertFalse(any(event["type"] == "response_complete" for event in events))

    def test_provider_completion_conventions_and_failures(self):
        for finish, done in (("stop", False), ("stop", True)):
            self.assertEqual(self.backend()._stream_response(self.stream("complete", finish, done), False), "complete")
        with self.assertRaises(BackendGenerationError):
            self.backend()._stream_response(self.stream("partial", None, True), False)
        for finish in ("length", "content_filter", "tool_calls"):
            with self.subTest(finish=finish), self.assertRaises(BackendGenerationError):
                self.backend()._stream_response(self.stream(finish=finish, done=True), False)
            with self.assertRaises(BackendGenerationError):
                _response_text({"choices": [{"message": {"content": "partial"}, "finish_reason": finish}]})
        with self.assertRaisesRegex(BackendGenerationError, "invalid streaming event"):
            self.backend()._stream_response([b"data: not-json\n"], False)

    def test_hard_capped_requests_preflight_without_sending(self):
        instruction = PromptInstruction("system", "x" * 20000, max_tokens=2560, hard_max_tokens=2560)
        with patch("goated_prompter.backends.openai_compatible.urlopen") as send:
            with self.assertRaisesRegex(BackendConfigurationError, "coarse input estimate"):
                self.backend(context_size=8192).generate(instruction)
        send.assert_not_called()
