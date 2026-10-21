"""Exercise real Caption admission without starting an HTTP or model server."""

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from io import BytesIO
import json
from urllib.error import URLError

from PIL import Image

import local_app
from goated_prompter.api.common import STATE
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.features.caption.routes import caption_endpoint
from goated_prompter.local_jobs import Job
from tests.helpers import enter_context
from tests.support.artifacts import task_paths
from tests.support.safety import synthetic_storage
from tests.support.caption import VisionEngine


class CaptionAdmissionTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _, scratch = task_paths("issue-118", "integration")
        self.storage = enter_context(self, synthetic_storage(scratch))
        self.folder = self.storage / "images"
        self.folder.mkdir()
        Image.new("RGB", (12, 16)).save(self.folder / "sample.png")
        self.app = local_app.create_app(config_loader=lambda: {"backend": "mock"},
                                        settings_path=self.storage / "settings.json")
        self.state = self.app[STATE]
        self.started = []
        def start(*args):
            self.started.append(args)
            return {"id": "caption-test", "kind": args[0], "status": "running"}
        self.state.start_job = start

    def request(self, payload):
        class Request:
            app = self.app
            json = AsyncMock(return_value=payload)
        return Request()

    def payload(self, **changes):
        return {"input": {"folder": str(self.folder), "description": "A person lifting a box", **changes}}

    async def test_admission_dispatches_caption_without_builder_state(self):
        response = await caption_endpoint(self.request(self.payload()))
        self.assertEqual(response.status, 202)
        kind, request, config, text_only, workflow = self.started[0]
        self.assertEqual(kind, "caption")
        self.assertEqual(request.idea, "A person lifting a box")
        self.assertEqual(config, {"backend": "mock", "local_llama_cpp": {}})
        self.assertFalse(text_only)
        self.assertEqual(workflow["operation"], "caption")
        self.assertEqual(self.state.saved_settings, {})

    async def test_busy_engine_returns_existing_job_without_admitting(self):
        self.state.jobs["other"] = Job()
        response = await caption_endpoint(self.request(self.payload()))
        self.assertEqual(response.status, 409)
        self.assertIn("active_job", json.loads(response.text))
        self.assertEqual(self.started, [])

    async def test_admitted_workflow_executes_through_application_dispatch(self):
        await caption_endpoint(self.request(self.payload()))
        kind, request, config, text_only, workflow = self.started[0]
        job = Job()
        job.kind = kind
        engine = VisionEngine()
        with patch("goated_prompter.features.caption.runner.create_backend", return_value=engine):
            self.state.execute(job, request, config, text_only, workflow)
        self.assertEqual(job.status, "succeeded", job.error)
        self.assertEqual(job.result["saved"], 1)
        self.assertEqual((self.folder / "sample.txt").read_text(encoding="utf-8"),
                         "A person lifts a box beside a table.\n")
        self.assertEqual(len(engine.calls), 1)

    async def test_invalid_input_never_admitted(self):
        for payload in (self.payload(length="invalid"), self.payload(folder="does-not-exist"),
                        {**self.payload(), "settings": []}, {**self.payload(), "images": []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                await caption_endpoint(self.request(payload))
        self.assertEqual(self.started, [])

    async def test_refused_or_reset_connection_fails_job_without_trying_every_image(self):
        Image.new("RGB", (12, 16)).save(self.folder / "second.png")
        await caption_endpoint(self.request(self.payload()))
        kind, request, config, text_only, workflow = self.started[0]
        engine = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic"})
        for failure in (URLError(ConnectionRefusedError("Connection refused")), ConnectionResetError("Connection reset")):
            with self.subTest(failure=type(failure).__name__):
                job = Job()
                job.kind = kind
                with patch("goated_prompter.features.caption.runner.create_backend", return_value=engine), \
                        patch("goated_prompter.backends.openai_compatible.urlopen", side_effect=failure) as transport, \
                        self.assertLogs(level="ERROR"):
                    self.state.execute(job, request, config, text_only, workflow)
                self.assertEqual(job.status, "failed")
                self.assertEqual(transport.call_count, 1)
                self.assertIsNone(job.result)
                self.assertIn("remaining images", job.error)
                self.assertEqual(list(self.folder.glob("*.txt")), [])

    async def test_connection_loss_preserves_finished_caption_and_stops_remaining_images(self):
        for name in ("a.png", "b.png"):
            Image.new("RGB", (12, 16)).save(self.folder / name)
        await caption_endpoint(self.request(self.payload()))
        kind, request, config, text_only, workflow = self.started[0]
        job = Job()
        job.kind = kind
        engine = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic"})
        response = BytesIO(json.dumps({"choices": [{"message": {"content": "A blue rectangle."},
                                                   "finish_reason": "stop"}]}).encode())
        response.headers = {}
        failure = URLError(ConnectionResetError("Connection reset"))
        with patch("goated_prompter.features.caption.runner.create_backend", return_value=engine), \
                patch("goated_prompter.backends.openai_compatible.urlopen", side_effect=[response, failure, failure]) as transport, \
                self.assertLogs(level="ERROR"):
            self.state.execute(job, request, config, text_only, workflow)
        self.assertEqual(job.status, "failed")
        self.assertEqual(transport.call_count, 2)
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), "A blue rectangle.\n")
        self.assertFalse((self.folder / "b.txt").exists())
        self.assertFalse((self.folder / "sample.txt").exists())

    async def test_stream_disconnect_stops_job_without_saving_partial_caption(self):
        Image.new("RGB", (12, 16)).save(self.folder / "second.png")
        await caption_endpoint(self.request(self.payload()))
        kind, request, config, text_only, workflow = self.started[0]
        job = Job()
        job.kind = kind
        engine = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic",
                                          "_activity_callback": job.record_llm_activity})
        class DisconnectedResponse:
            headers = {"Content-Type": "text/event-stream"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"An unfinished caption"},"finish_reason":null}]}\n'
                raise ConnectionResetError("Connection reset")

        with patch("goated_prompter.features.caption.runner.create_backend", return_value=engine), \
                patch("goated_prompter.backends.openai_compatible.urlopen", return_value=DisconnectedResponse()) as transport, \
                self.assertLogs(level="ERROR"):
            self.state.execute(job, request, config, text_only, workflow)
        self.assertEqual(job.status, "interrupted")
        self.assertEqual(transport.call_count, 1)
        self.assertIn("remaining images", job.error)
        self.assertEqual(list(self.folder.glob("*.txt")), [])
        self.assertEqual(job.partial_responses[0]["partial_text"], "An unfinished caption")
