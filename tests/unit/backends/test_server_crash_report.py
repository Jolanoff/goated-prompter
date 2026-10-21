"""A dropped owned-server connection explains whether the server stopped; no real server is started."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from goated_prompter.backends import llama_cpp_process as llama
from goated_prompter.backends.base import BackendConnectionError
from goated_prompter.backends.local_llama_cpp import _OwnedServerClient


class ExitedProcess:
    def __init__(self, code):
        self.code = code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("llama-server", timeout)
        return self.code


class ServerCrashReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.log = Path(directory.name) / "server.log"
        patcher = patch.object(llama, "SERVER_LOG_PATH", self.log)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_names_exit_code_and_last_log_lines(self):
        self.log.write_text("loading model\n\nencoding image\nout of memory allocating buffer\n", encoding="utf-8")
        report = llama.LlamaCppProcessManager.failure_report(SimpleNamespace(process=ExitedProcess(3221225477)))
        self.assertIn("0xC0000005", report)
        self.assertIn("out of memory allocating buffer", report)
        self.assertIn(str(self.log), report)

    def test_batch_size_hint_when_image_exceeds_batch(self):
        self.log.write_text("llama-context.cpp: GGML_ASSERT(n_ubatch >= n_tokens) failed\n", encoding="utf-8")
        report = llama.LlamaCppProcessManager.failure_report(SimpleNamespace(process=ExitedProcess(3221226505)))
        self.assertIn("0xC0000409", report)
        self.assertIn("Raise batch_size", report)

    def test_report_for_running_server_and_missing_log(self):
        report = llama.LlamaCppProcessManager.failure_report(SimpleNamespace(process=ExitedProcess(None)), 0)
        self.assertIn("still running", report)
        self.assertNotIn("Last server log lines", report)

    def test_owned_client_adds_report_to_connection_error_only(self):
        client = Mock()
        client.generate.side_effect = BackendConnectionError("The prompt engine disconnected before completion.")
        manager = Mock()
        manager.failure_report.return_value = "The llama.cpp server stopped while answering (exit code 1)."
        wrapped = _OwnedServerClient(client, manager, SimpleNamespace())
        with self.assertRaisesRegex(BackendConnectionError, "disconnected before completion.*exit code 1"):
            wrapped.generate(object())
        client.url = "http://127.0.0.1:8190/v1/chat/completions"
        self.assertEqual(wrapped.url, client.url)


class LaunchBatchSizeTests(unittest.TestCase):
    def config(self, **settings):
        with patch.object(llama, "_resolve_model_file", side_effect=lambda value, *_: Path(value)), \
                patch.object(llama, "_resolve_server_executable", return_value=Path("llama-server")), \
                patch.object(llama, "resolve_models_directory", return_value=None):
            return llama.LlamaCppLaunchConfig.from_mapping(
                {"model_path": "folder/model.gguf", "mmproj_path": "folder/mmproj.gguf", **settings})

    def batch_flags(self, config):
        command = config.command()
        return command[command.index("--batch-size") + 1], command[command.index("--ubatch-size") + 1]

    def test_default_batch_holds_a_whole_image(self):
        self.assertEqual(self.batch_flags(self.config()), ("2048", "2048"))
        self.assertEqual(self.batch_flags(self.config(image_min_tokens=1536)), ("3072", "3072"))

    def test_configured_batch_size_is_used_and_restarts_server(self):
        configured = self.config(batch_size=4096)
        self.assertEqual(self.batch_flags(configured), ("4096", "4096"))
        self.assertNotEqual(configured.compatibility_key, self.config().compatibility_key)

    def test_batch_smaller_than_image_minimum_is_rejected(self):
        with self.assertRaisesRegex(llama.BackendConfigurationError, "batch_size"):
            self.config(image_min_tokens=1024, batch_size=512)


if __name__ == "__main__":
    unittest.main()
