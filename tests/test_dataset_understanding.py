"""Understanding response-format regressions without inference or private storage."""

from contextlib import nullcontext
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset_understanding import DatasetUnderstandingService, understanding_instruction, validate_understanding
from tests.helpers import dataset_understanding_fixture
from tests.test_dataset import valid_draft


class DatasetUnderstandingTests(unittest.TestCase):
    def run_response(self, raw):
        backend, session = Mock(), Mock()
        backend.generation_session.return_value = nullcontext(session)
        session.generate.return_value = raw
        service = DatasetUnderstandingService({"backend": "mock"}, lambda: None)
        with patch("goated_prompter.dataset_understanding.create_backend", return_value=backend):
            try:
                return service.run(GoatedPrompterRequest(idea="A synthetic cup"), valid_draft(), lambda _message: None)
            finally:
                session.generate.assert_called_once()

    def test_valid_brief_accepts_one_json_fence_without_another_model_call(self):
        brief = dataset_understanding_fixture()
        raw = json.dumps(brief)
        for value in (raw, "```json\n" + raw + "\n```", "```\n" + raw + "\n```", "\ufeff" + raw):
            with self.subTest(wrapper=value[:10]):
                self.assertEqual(self.run_response(value), brief)

    def test_richer_count_identity_and_scoped_action_options_survive_validation(self):
        brief = dataset_understanding_fixture(character_count=2, identity_policy="random_per_prompt",
            fixed=[{"scope": "all_outputs", "text": "Two adults; at least one has blond hair, not necessarily both."}],
            may_vary=[{"scope": "dataset", "text": "Different people across images; preserve each identity within its image."}],
            action_options=[{"scope": "guided:2", "text": "Punch or block; alternatives, not simultaneous actions."}])
        validated = validate_understanding(brief, ("all_outputs", "dataset", "guided:1", "guided:2"))
        self.assertEqual(validated, brief)
        self.assertEqual(validate_understanding(dataset_understanding_fixture(), ("all_outputs", "dataset")),
            dataset_understanding_fixture())

    def test_richer_identity_and_action_metadata_still_rejects_invalid_types_and_scopes(self):
        for changes in ({"character_count": True}, {"character_count": 0}, {"character_count": 101},
                        {"identity_policy": []}, {"identity_policy": "same random person"},
                        {"action_options": "punch"}, {"action_options": [{"scope": "guided:9", "text": "Punch"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_understanding(dataset_understanding_fixture(**changes), ("all_outputs", "dataset"))

    def test_empty_prose_truncated_multiple_or_invalid_briefs_never_proceed(self):
        brief = json.dumps(dataset_understanding_fixture())
        invalid = ("", "  ", None, "Here is the brief:\n" + brief,
            brief + "\nAnother object: " + brief, "```json\n" + brief,
            "<think>Analyze the request.</think>\n" + brief, "[]", "{}",
            brief.replace('"fixed": []', '"fixed": [], "fixed": []'))
        for raw in invalid:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(BackendGenerationError):
                self.run_response(raw)

    def test_empty_response_has_a_specific_error_without_a_fabricated_brief(self):
        with self.assertRaisesRegex(BackendGenerationError, "empty.*No generation started"):
            self.run_response("  ")

    def test_understanding_requests_llama_json_decoding_only_for_its_model_call(self):
        instruction = understanding_instruction(valid_draft())
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(dataset_understanding_fixture())}}]}).encode()
        for owned, json_output in ((True, True), (False, True), (True, False)):
            with self.subTest(owned_llama=owned, json_output=json_output):
                backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic",
                    "_is_llama_cpp": owned})
                with (patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send,
                      patch("goated_prompter.backends.openai_compatible.log_request"),
                      patch("goated_prompter.backends.openai_compatible.log_response")):
                    backend.generate(replace(instruction, json_output=json_output))
                send.assert_called_once()
                payload = json.loads(send.call_args.args[0].data)
                if owned and json_output:
                    self.assertEqual(payload.get("response_format"), {"type": "json_object"})
                else:
                    self.assertNotIn("response_format", payload)
