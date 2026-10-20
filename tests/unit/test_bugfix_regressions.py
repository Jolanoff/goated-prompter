"""Regression tests for the code-review fixes: library deletes, Director file names, idle timeouts, request paths."""

import asyncio
import importlib.util
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import Request

from goated_prompter import prompt_library
from goated_prompter.backends.interruptible_http import interruptible_urlopen
from goated_prompter.json_store import atomic_json
from goated_prompter.presets import _free_destination, _safe_filename


class LibraryTests(unittest.TestCase):
    def test_delete_leaves_no_orphan_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = prompt_library.library_snapshot("Generic", directory)
            for text in ("alpha", "beta", "gamma"):
                snapshot = prompt_library.update_library("Generic", snapshot["revision"], "add", prompt=text, directory=directory)
            before = prompt_library.library_path("Generic", directory).read_text(encoding="utf-8").count("\n---\n")
            snapshot = prompt_library.update_library("Generic", snapshot["revision"], "delete", index=1, directory=directory)
            after = prompt_library.library_path("Generic", directory).read_text(encoding="utf-8").count("\n---\n")
            self.assertEqual(snapshot["prompts"], ("alpha", "gamma"))
            self.assertEqual(after, before - 1)

    def test_merged_z_image_library_starts_with_the_old_base_and_turbo_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z-image-base.txt").write_text("# old\nalpha\n---\nbeta\n", encoding="utf-8")
            (root / "z-image-turbo.txt").write_text("beta\n---\ngamma\n", encoding="utf-8")
            prompt_library.ensure_library_files(directory)
            self.assertEqual(prompt_library.library_snapshot("Z-Image Turbo", directory)["prompts"], ("alpha", "beta", "gamma"))
            self.assertTrue((root / "z-image-base.txt").exists(), "the old files are kept")

    def test_tokenize_keeps_non_ascii_letters(self):
        self.assertEqual(prompt_library.tokenize("café 1girl"), ["café", "girl"])


class DirectorFileNameTests(unittest.TestCase):
    def test_non_ascii_names_get_distinct_files(self):
        self.assertNotEqual(_safe_filename("导演"), _safe_filename("Режиссёр"))
        self.assertTrue(_safe_filename("导演").endswith(".json"))

    def test_taken_slug_gets_a_hash_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / _safe_filename("Café")).write_text("{}", encoding="utf-8")
            second = _free_destination(root, "Cafe")
            self.assertNotEqual(second.name, _safe_filename("Cafe"))


class JsonStoreTests(unittest.TestCase):
    def test_replace_retries_permission_errors(self):
        import os
        real = os.replace
        calls = []

        def flaky(source, destination):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("held open")
            return real(source, destination)

        with tempfile.TemporaryDirectory() as directory, mock.patch("goated_prompter.json_store.os.replace", flaky):
            atomic_json(Path(directory) / "x.json", {"a": 1})
            self.assertEqual(len(calls), 3)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.path == "/steady":
            for _ in range(6):
                self.wfile.write(b"data: x\n\n")
                self.wfile.flush()
                time.sleep(0.4)
        elif self.path == "/heartbeat":
            for _ in range(12):
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(0.2)
        else:
            self.wfile.write(b"data: x\n\n")
            self.wfile.flush()
            time.sleep(4)


class IdleTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def read(self, path, timeout):
        request = Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=b"{}", method="POST")
        with interruptible_urlopen(request, timeout=timeout, register=lambda f: None, unregister=lambda f: None) as response:
            data = b""
            for line in response:  # like the stream consumer: real output restarts the deadline
                data += line
                if line.startswith(b"data:"):
                    response.touch_deadline()
            return data

    def test_progress_restarts_the_deadline(self):
        self.assertTrue(self.read("/steady", timeout=1.0))

    def test_heartbeats_alone_do_not(self):
        with self.assertRaises(TimeoutError):
            self.read("/heartbeat", timeout=1.0)

    def test_silence_times_out(self):
        with self.assertRaises(TimeoutError):
            self.read("/stall", timeout=1.0)


@unittest.skipUnless(importlib.util.find_spec("aiohttp"), "Requires aiohttp")
class RequestPathTests(unittest.TestCase):
    def test_generate_rejects_server_only_paths(self):
        from goated_prompter.features.builder import routes

        class Request:
            app = {routes.STATE: object()}

            async def json(self):
                return {"settings": {"director_llama_server": "C:/Windows/System32/calc.exe"}, "text_only": True}

        with self.assertRaises(ValueError):
            asyncio.run(routes.generate(Request()))


if __name__ == "__main__":
    unittest.main()
