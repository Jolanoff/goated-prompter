"""Caption jobs use synthetic images and never invoke a real model."""

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from goated_prompter.backends.base import BackendConnectionError, BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.caption.contract import validate_caption_input
from goated_prompter.features.caption.runner import run_caption
from goated_prompter.features.caption.prompting import caption_instruction
from goated_prompter.features.caption.runner import save_caption
from goated_prompter.local_jobs import Job, JobCancelled
from tests.helpers import enter_context
from tests.support.artifacts import task_paths
from tests.support.safety import synthetic_storage
from tests.support.caption import VisionEngine


class CaptionTests(unittest.TestCase):
    def setUp(self):
        _, scratch = task_paths("issue-118", "unit")
        storage = enter_context(self, synthetic_storage(scratch))
        self.temp = enter_context(self, tempfile.TemporaryDirectory(dir=storage))
        self.folder = Path(self.temp)
        self.job = Job()
        self.engine = VisionEngine()
        self.config = {"backend": "mock"}
        self.patch = patch("goated_prompter.features.caption.runner.create_backend", return_value=self.engine)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def image(self, name):
        Image.new("RGB", (24, 32), "blue").save(self.folder / name)

    def run_job(self, **changes):
        data = validate_caption_input({"folder": str(self.folder), "description": "People moving boxes", **changes})
        run_caption(None, self.job, GoatedPrompterRequest(idea=""), self.config, {"input": data})
        return self.job.snapshot()["result"]

    def test_sequential_sidecars_preserve_existing_and_include_images(self):
        for name in ("b.png", "a.jpg", "c.webp"):
            self.image(name)
        (self.folder / "b.txt").write_text("Manual caption", encoding="utf-8")
        result = self.run_job(trigger="boxlift", lora_type="action")
        self.assertEqual([row["image"] for row in result["files"]], ["a.jpg", "b.png", "c.webp"])
        self.assertEqual([row["status"] for row in result["files"]], ["saved", "skipped", "saved"])
        self.assertEqual(len(self.engine.calls), 2)
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"),
                         "boxlift, A person lifts a box beside a table.\n")
        self.assertEqual((self.folder / "b.txt").read_text(encoding="utf-8"), "Manual caption")
        self.assertIn("People moving boxes", self.engine.calls[0].user_message)
        self.assertIn("visible", self.engine.calls[0].system_message)
        self.assertEqual(self.engine.calls[0].image.width, 24)

    def test_bad_image_reports_error_and_continues(self):
        (self.folder / "a.png").write_bytes(b"not an image")
        self.image("b.png")
        result = self.run_job()
        self.assertEqual([row["status"] for row in result["files"]], ["error", "saved"])
        self.assertFalse((self.folder / "a.txt").exists())

    def test_cancellation_after_inference_does_not_write_caption(self):
        self.image("a.png")
        self.engine.on_generate = self.job.cancel
        with self.assertRaises(JobCancelled):
            self.run_job()
        self.assertFalse((self.folder / "a.txt").exists())

    def test_duplicate_stems_rejected_before_inference(self):
        self.image("a.png")
        self.image("a.jpg")
        with self.assertRaisesRegex(ValueError, "same caption"):
            self.run_job()
        self.assertEqual(self.engine.calls, [])

    def test_inference_failure_reports_error_without_sidecar(self):
        self.image("a.png")
        def fail():
            raise BackendGenerationError("Engine unavailable")
        self.engine.on_generate = fail
        result = self.run_job()
        self.assertEqual(result["files"][0]["status"], "error")
        self.assertFalse((self.folder / "a.txt").exists())

    def test_empty_folder_rejected(self):
        with self.assertRaisesRegex(ValueError, "No supported images"):
            self.run_job()

    def test_text_only_engine_is_rejected_without_inference(self):
        self.image("a.png")
        self.engine.supports_vision = False
        with self.assertRaisesRegex(ValueError, "vision-capable"):
            self.run_job()
        self.assertEqual(self.engine.calls, [])

    def test_exclusive_sidecar_creation_preserves_file_created_during_inference(self):
        self.image("a.png")
        self.engine.on_generate = lambda: (self.folder / "a.txt").write_text("User caption", encoding="utf-8")
        result = self.run_job()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), "User caption")

    def test_empty_model_response_is_not_saved(self):
        self.image("a.png")
        self.engine.generate = lambda instruction: "   "
        result = self.run_job()
        self.assertEqual(result["errors"], 1)
        self.assertFalse((self.folder / "a.txt").exists())

    def test_completed_sidecar_survives_cancellation_on_next_image(self):
        self.image("a.png")
        self.image("b.png")
        def cancel_second():
            if len(self.engine.calls) == 2:
                self.job.cancel()
        self.engine.on_generate = cancel_second
        with self.assertRaises(JobCancelled):
            self.run_job()
        self.assertTrue((self.folder / "a.txt").is_file())
        self.assertFalse((self.folder / "b.txt").exists())

    def test_partial_write_failure_removes_only_new_sidecar(self):
        sidecar = self.folder / "a.txt"
        original_open = Path.open
        @contextmanager
        def failing_open(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                class FailingStream:
                    def write(self, value):
                        stream.write(value[:3])
                        raise OSError("Disk full")
                yield FailingStream()
        with patch("pathlib.Path.open", autospec=True, side_effect=failing_open):
            with self.assertRaises(OSError):
                save_caption(sidecar, "Caption")
        self.assertFalse(sidecar.exists())

    def test_concept_and_length_rules_remain_distinct(self):
        for concept, phrase in (("style", "Do not describe artistic style"),
                                ("character", "stable identity traits"), ("action", "Do not invent a motion sequence")):
            for length, detail in (("focused", "one short sentence"), ("detailed", "two to five sentences")):
                with self.subTest(concept=concept, length=length):
                    data = {"lora_type": concept, "length": length, "description": "People moving boxes"}
                    instruction = caption_instruction(data, None, "gemma")
                    self.assertIn(phrase, instruction.system_message)
                    self.assertIn(detail, instruction.system_message)
                    self.assertEqual(instruction.model_family, "gemma")

    def test_dropped_connection_reopens_session_and_retries_same_image(self):
        self.image("a.png")
        self.image("b.png")
        sessions = []
        engine = self.engine
        original = engine.generation_session

        def counted_session():
            sessions.append(1)
            return original()
        engine.generation_session = counted_session

        def drop_first_call():
            if len(engine.calls) == 1:
                raise BackendConnectionError("The prompt engine disconnected before completion.")
        engine.on_generate = drop_first_call
        result = self.run_job()
        self.assertEqual([row["status"] for row in result["files"]], ["saved", "saved"])
        self.assertEqual(len(engine.calls), 3)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(any("reconnect" in event["message"] or "connection lost" in event["message"]
                            for event in self.job.snapshot()["events"]))

    def test_image_that_keeps_dropping_connection_is_skipped_and_run_continues(self):
        for name in ("a.png", "b.png", "c.png"):
            self.image(name)
        engine = self.engine

        def drop_on_first_image():
            if len(engine.calls) <= 2:
                raise BackendConnectionError("The prompt engine disconnected before completion.")
        engine.on_generate = drop_on_first_image
        result = self.run_job()
        self.assertEqual([row["status"] for row in result["files"]], ["error", "saved", "saved"])
        self.assertIn("skipped", result["files"][0]["error"])
        self.assertFalse((self.folder / "a.txt").exists())
        self.assertTrue((self.folder / "b.txt").exists())

    def test_engine_that_stays_down_stops_run_and_keeps_finished_files(self):
        for name in ("a.png", "b.png", "c.png", "d.png"):
            self.image(name)
        engine = self.engine

        def down_after_first_image():
            if len(engine.calls) > 1:
                raise BackendConnectionError("Could not reach the engine.")
        engine.on_generate = down_after_first_image
        with self.assertRaisesRegex(BackendConnectionError, "remaining images"):
            self.run_job()
        self.assertTrue((self.folder / "a.txt").exists())
        self.assertEqual(len(engine.calls), 5)
        self.assertFalse((self.folder / "d.txt").exists())

    def test_single_image_regenerates_and_replaces_only_its_caption(self):
        for name in ("a.png", "b.png"):
            self.image(name)
            (self.folder / name).with_suffix(".txt").write_text("Old caption", encoding="utf-8")
        result = self.run_job(image="b.png", trigger="boxlift")
        self.assertEqual([(row["image"], row["status"]) for row in result["files"]], [("b.png", "saved")])
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual((self.folder / "b.txt").read_text(encoding="utf-8"),
                         "boxlift, A person lifts a box beside a table.\n")
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), "Old caption")

    def test_single_image_must_be_in_folder(self):
        self.image("a.png")
        for name in ("missing.png", "../a.png", "a.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_caption_input({"folder": str(self.folder), "description": "Boxes", "image": name})

    def test_captions_reuse_user_words(self):
        instruction = caption_instruction({"lora_type": "action", "length": "detailed",
                                           "description": "two dancers doing a lift"}, None, "qwen")
        self.assertIn("user's own words", instruction.system_message)
        self.assertIn("two dancers doing a lift", instruction.user_message)

    def test_invalid_options_rejected(self):
        for change in ({"lora_type": "other"}, {"length": "other"}, {"target": "other"},
                       {"description": ""}, {"extra": True}, {"folder": "missing-folder"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_caption_input({"folder": str(self.folder), "description": "Boxes", **change})
