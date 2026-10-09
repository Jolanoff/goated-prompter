"""Exercise real sockets, not a model or a mocked network transport."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.features.builder.service import PromptInstruction


class InterruptibleHTTPTests(unittest.TestCase):
    def run_request(self, mode, *, timeout=30):
        entered, release = threading.Event(), threading.Event()
        registry = set()
        result, errors = [], []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                if mode == "headers":
                    entered.set()
                    release.wait(4)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                line = ("data: " + json.dumps({"choices": [{"delta": {"content": "partial "}}]}) + "\n\n").encode()
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                    entered.set()
                    if mode == "heartbeat":
                        while not release.wait(.02):
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                    else:
                        release.wait(4)
                except OSError:
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        backend = OpenAICompatibleBackend({
            "base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "test",
            "timeout": timeout, "_activity_callback": lambda _event: None,
            "_register_interrupt": registry.add, "_unregister_interrupt": registry.discard,
        })

        def generate():
            try:
                with patch("goated_prompter.backends.openai_compatible.log_request"), patch("goated_prompter.backends.openai_compatible.log_response"):
                    result.append(backend.generate(PromptInstruction("system", "user")))
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=generate, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(registry)
            if mode != "heartbeat":
                for interrupt in list(registry):
                    interrupt()
            worker.join(2)
            self.assertFalse(worker.is_alive(), "Socket cancellation must not wait for the model timeout")
            self.assertEqual(result, [])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], BackendGenerationError)
            if mode == "heartbeat":
                self.assertIn("within 1 seconds", str(errors[0]))
            self.assertEqual(registry, set(), "Completed transports must unregister their callbacks")
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            worker.join(2)
            serving.join(2)

    def test_cancel_during_headers_and_streaming(self):
        for mode in ("headers", "stream"):
            with self.subTest(mode=mode):
                self.run_request(mode)

    def test_heartbeats_do_not_extend_the_total_request_deadline(self):
        self.run_request("heartbeat", timeout=1)

    def test_successful_stream_and_json_keep_the_existing_response_contract(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                streaming = payload.get("stream")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
                self.end_headers()
                if streaming:
                    for text, finish in (("valid ", None), ("output", "stop")):
                        self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}) + "\n\n").encode())
                        self.wfile.flush()
                else:
                    self.wfile.write(json.dumps({"choices": [{"message": {"content": "valid output"}, "finish_reason": "stop"}]}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        registry = set()
        try:
            for streaming in (False, True):
                backend = OpenAICompatibleBackend({"base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "test",
                    "_register_interrupt": registry.add, "_unregister_interrupt": registry.discard,
                    "_activity_callback": (lambda _event: None) if streaming else None})
                with patch("goated_prompter.backends.openai_compatible.log_request"), patch("goated_prompter.backends.openai_compatible.log_response"):
                    self.assertEqual(backend.generate(PromptInstruction("system", "user")), "valid output")
                self.assertEqual(registry, set())
        finally:
            server.shutdown()
            server.server_close()
            serving.join(2)
