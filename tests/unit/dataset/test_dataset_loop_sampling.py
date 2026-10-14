"""Gemma writer retries discourage loops without changing other Dataset stages."""

import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendRunawayError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService
from tests.support.dataset import CaptureBackend, valid_draft


class DatasetLoopSamplingTests(unittest.TestCase):
    def test_only_gemma_writer_retries_receive_a_repetition_penalty(self):
        for family in ("gemma", "qwen"):
            for failure in ("missing_trigger", "runaway"):
                with self.subTest(family=family, failure=failure):
                    backend = CaptureBackend()
                    generate = backend.generate
                    def respond(instruction):
                        if instruction.diagnostic_stage == "dataset:1":
                            backend.calls.append(instruction)
                            if failure == "runaway":
                                raise BackendRunawayError("synthetic loop")
                            return "A boxer punches a training bag."
                        return generate(instruction)
                    backend.generate = respond
                    config = {"backend": "mock", "local_llama_cpp": {"model_path": f"synthetic/{family}.gguf"}}
                    with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
                        result = DatasetService(config, lambda: None).run(
                            GoatedPrompterRequest(idea="A fully clothed boxer trains."),
                            valid_draft(amount=1), lambda _: None, lambda _: None)
                    self.assertEqual(result["completed"], 1)
                    writers = [call for call in backend.calls if call.diagnostic_stage.startswith("dataset:1")]
                    self.assertEqual(len(writers), 2)
                    self.assertEqual(writers[1].user_message, writers[0].user_message)
                    self.assertIsNone(getattr(writers[0], "repeat_penalty", None))
                    self.assertEqual(getattr(writers[1], "repeat_penalty", None), 1.1 if family == "gemma" else None)
                    self.assertTrue(all(getattr(call, "repeat_penalty", None) is None
                        for call in backend.calls if not call.diagnostic_stage.startswith("dataset:1")))
