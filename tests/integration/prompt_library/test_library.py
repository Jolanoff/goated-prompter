"""The editor persists to the same text libraries used by the writer."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from local_app import create_app
from tests.helpers import enter_context
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, library_path, pick_references


class LibraryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        enter_context(self, patch.dict(os.environ, {
            LIBRARY_DIR_ENV: str(self.directory / "library"),
            "GOATED_PROMPTER_USER_DIR": str(self.directory / "presets"),
        }))
        enter_context(self, patch("local_app.get_process_manager"))
        self.client = TestClient(TestServer(create_app(
            config_loader=lambda: {"backend": "mock"}, settings_path=self.directory / "settings.json",
        )), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def snapshot(self, target="Anima"):
        response = await self.client.get("/api/prompt-library", params={"target": target})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_add_edit_delete_preserve_text_comments_and_update_writer_references(self):
        path = library_path("Anima")
        path.parent.mkdir()
        path.write_text("# My examples\nA girl cooks.\n---\n# Keep this note\nA boy runs.\n", encoding="utf-8")
        state = await self.snapshot()
        self.assertEqual(state["prompts"], ["A girl cooks.", "A boy runs."])
        for method, payload, expected in (
            ("POST", {"prompt": "1girl, rain, umbrella, street, night\n\nA girl waits."},
             ["A girl cooks.", "A boy runs.", "1girl, rain, umbrella, street, night\n\nA girl waits."]),
            ("PUT", {"index": 0, "prompt": "A chef laughs.\n\nSteam fills the kitchen."},
             ["A chef laughs.\n\nSteam fills the kitchen.", "A boy runs.", "1girl, rain, umbrella, street, night\n\nA girl waits."]),
            ("DELETE", {"index": 1},
             ["A chef laughs.\n\nSteam fills the kitchen.", "1girl, rain, umbrella, street, night\n\nA girl waits."]),
        ):
            response = await self.client.request(method, "/api/prompt-library?target=Anima",
                                                 json={"revision": state["revision"], **payload})
            self.assertEqual(response.status, 200, await response.text())
            state = await response.json()
            self.assertEqual(state["prompts"], expected)
            self.assertEqual(set(pick_references("Anima", "", count=10)), set(expected))
            status = await (await self.client.get("/api/library?target=Anima")).json()
            self.assertEqual(status["count"], len(expected))
            self.assertIn("# My examples\n", path.read_text(encoding="utf-8"))
            self.assertIn("# Keep this note\n", path.read_text(encoding="utf-8"))
        self.assertEqual((await self.snapshot())["prompts"], expected)
        self.assertEqual((await self.snapshot("Generic"))["prompts"], [])

    async def test_empty_library_initializes_on_add_and_aliases_share_the_target_file(self):
        state = await self.snapshot("Qwen Image")
        response = await self.client.post("/api/prompt-library?target=Qwen%20Image", json={
            "revision": state["revision"], "prompt": "A café at dusk. 中文描述。",
        })
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await self.snapshot("Qwen Image (original)"))["prompts"], ["A café at dusk. 中文描述。"])
        self.assertTrue(library_path("Qwen Image").read_text(encoding="utf-8").startswith("# Goated Prompter"))

    async def test_stale_revision_rejects_edit_and_delete_without_overwriting_external_changes(self):
        state = await self.snapshot()
        path = library_path("Anima")
        path.parent.mkdir()
        path.write_text("External prompt.\n", encoding="utf-8")
        for method, extra in (("PUT", {"prompt": "My old draft."}), ("DELETE", {})):
            response = await self.client.request(method, "/api/prompt-library?target=Anima", json={
                "revision": state["revision"], "index": 0, **extra,
            })
            self.assertEqual(response.status, 409)
            self.assertIn("changed elsewhere", (await response.json())["error"])
            self.assertEqual(path.read_text(encoding="utf-8"), "External prompt.\n")

    async def test_invalid_prompt_and_index_leave_existing_file_unchanged(self):
        path = library_path("Anima")
        path.parent.mkdir()
        path.write_text("Original prompt.\n", encoding="utf-8")
        state = await self.snapshot()
        cases = [("POST", {"prompt": prompt}) for prompt in
                 ("", "  ", None, 42, "# comment only", "Before\n---\nAfter", "x" * 100001)]
        cases += [("PUT", {"prompt": "New prompt.", "index": index}) for index in (-1, 1, True, "0", None)]
        for method, fields in cases:
            with self.subTest(method=method, fields=str(fields)[:80]):
                response = await self.client.request(method, "/api/prompt-library?target=Anima",
                                                     json={"revision": state["revision"], **fields})
                self.assertEqual(response.status, 400, await response.text())
                self.assertEqual(path.read_text(encoding="utf-8"), "Original prompt.\n")

    async def test_unknown_targets_are_rejected_instead_of_creating_new_libraries(self):
        for target in ("../outside", "Anima/../../outside", "Unknown", ""):
            response = await self.client.get("/api/prompt-library", params={"target": target})
            self.assertEqual(response.status, 400)
        self.assertFalse((self.directory / "library").exists())

    async def test_unreadable_utf8_returns_actionable_error_without_overwriting(self):
        path = library_path("Anima")
        path.parent.mkdir()
        path.write_bytes(b"\xff\xfeinvalid")
        response = await self.client.get("/api/prompt-library?target=Anima")
        self.assertEqual(response.status, 400)
        self.assertIn("UTF-8", (await response.json())["error"])
        self.assertEqual(path.read_bytes(), b"\xff\xfeinvalid")
