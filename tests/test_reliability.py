"""Regression cases found during code review; no model or private disk data."""

import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend, _response_text
from goated_prompter.backends.base import BackendGenerationError, BackendConfigurationError
from goated_prompter.core import PromptInstruction
from goated_prompter.dataset_quality import idea_action_error
from goated_prompter.dataset_staging import geometry_prompt_schema, geometry_enum_values
from goated_prompter.scene_planner import scene_is_usable, scene_unusable_reason


class ReliabilityTests(unittest.TestCase):
    def backend(self, **settings):
        return OpenAICompatibleBackend({"base_url": "http://127.0.0.1:1/v1", "model": "test", **settings})

    def stream(self, text="partial", finish=None, done=False):
        lines = [("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}) + "\n").encode()]
        return lines + ([b"data: [DONE]\n"] if done else [])

    def test_abrupt_eof_cannot_emit_a_success_event(self):
        events = []
        with self.assertRaisesRegex(BackendGenerationError, "completion marker"):
            self.backend(_activity_callback=events.append)._stream_response(self.stream(), False)
        self.assertFalse(any(event["type"] == "response_complete" for event in events))

    def test_provider_completion_conventions_and_failures(self):
        for finish, done in (("stop", False), (None, True), ("stop", True)):
            self.assertEqual(self.backend()._stream_response(self.stream("complete", finish, done), False), "complete")
        for finish in ("length", "content_filter", "tool_calls"):
            with self.subTest(finish=finish), self.assertRaises(BackendGenerationError):
                self.backend()._stream_response(self.stream(finish=finish, done=True), False)
            with self.assertRaises(BackendGenerationError):
                _response_text({"choices": [{"message": {"content": "partial"}, "finish_reason": finish}]})
        with self.assertRaisesRegex(BackendGenerationError, "invalid streaming event"):
            self.backend()._stream_response([b"data: not-json\n"], False)

    def test_unknown_action_paraphrases_and_clothing_are_not_rewrite_triggers(self):
        for idea, prose in (
            ("She runs to catch a bus.", "She is wearing a blue jacket as she races toward the bus."),
            ("She reads a book.", "A portrait of her engrossed in a novel."),
            ("She walks along the beach.", "She strolls along the beach wearing a blue jacket."),
            ("She juggles oranges.", "She sends oranges through the air while dressed in clown clothes."),
            ("She runs to catch a bus.", "She races past a man who stands motionless beside the bus."),
        ):
            with self.subTest(prose=prose):
                self.assertIsNone(idea_action_error(idea, prose))
        self.assertIsNotNone(idea_action_error("She runs to catch a bus.", "She stands motionless beside a bus."))
        self.assertIsNone(idea_action_error("She runs to catch a bus.", "She runs past a man who stands motionless."))

    def test_geometryless_manual_scene_eligibility_is_preserved(self):
        row = {"idea": "Reads a book", "scene": "She reads a book on a bench.", "geometry": {}, "scene_status": "valid"}
        data = {"trigger_type": "Character"}
        self.assertTrue(scene_is_usable(row, data))
        self.assertIsNone(scene_unusable_reason(row, data))
        for patch in ({"idea": ""}, {"scene": ""}, {"scene_status": "geometry_warning"}, {"geometry": {"framing": "full_body"}}):
            self.assertFalse(scene_is_usable({**row, **patch}, data))

    def test_hard_capped_requests_preflight_without_sending(self):
        instruction = PromptInstruction("system", "x" * 20000, max_tokens=2560, hard_max_tokens=2560)
        with patch("goated_prompter.backends.openai_compatible.urlopen") as send:
            with self.assertRaisesRegex(BackendConfigurationError, "coarse input estimate"):
                self.backend(context_size=8192).generate(instruction)
        send.assert_not_called()

    def test_compact_schema_keeps_optional_vocabulary_once(self):
        full = geometry_prompt_schema("Character")
        compact = geometry_prompt_schema("Character", optional_values_in_context=True)
        self.assertLess(len(compact), len(full))
        for field in ("framing", "gaze_direction", "head_direction"):
            for value in geometry_enum_values("Character")[field]:
                self.assertIn(value, compact)
