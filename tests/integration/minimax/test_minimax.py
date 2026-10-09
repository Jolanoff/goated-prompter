"""MiniMax endpoints with controlled responses and synthetic storage."""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.minimax import default_minimax_draft
from goated_prompter.workflow_settings import WorkflowSettingsStore, empty_settings
from tests.helpers import enter_context
from tests.support.minimax import DANCE_PLAN, REF, ScriptedBackend, dance_input


class MiniMaxEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = enter_context(self, tempfile.TemporaryDirectory())
        enter_context(self, patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp) / "directors")}))
        self.backend = ScriptedBackend(DANCE_PLAN, REF)
        enter_context(self, patch("goated_prompter.minimax.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        self.backend.release.set()
        await self.client.close()

    async def terminal(self, job):
        for _ in range(300):
            result = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
            if result["status"] in local.TERMINAL:
                return result
            await asyncio.sleep(.01)
        self.fail("Job did not finish")

    async def test_generate_is_text_only_isolated_from_builder_and_history(self):
        history = await (await self.client.get("/api/workspace")).json()
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input()})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(job["result"]["prompt"], REF)
        self.assertEqual(job["kind"], "minimax")
        self.assertEqual(await (await self.client.get("/api/workspace")).json(), history)
        self.assertNotIn("builder", self.app[local.STATE].saved_settings)

    async def test_invalid_contract_rejected_before_inference(self):
        for data in ({"duration_seconds": 16, "user_request": "Test"},
                     {"user_request": "Use <image1>"},
                     {"references": ["video4"], "user_request": "Test"},
                     {"mode": "I2VA", "user_request": "Test"}):
            response = await self.client.post("/api/workspace/minimax", json={"input": data})
            self.assertEqual(response.status, 400, await response.text())
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input(), "images": ["data:image/png;base64,abc"]})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.backend.calls, [])

    async def test_shared_admission_cancellation_discards_output(self):
        self.backend.block = True
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input()})
        job = await response.json()
        self.assertTrue(await asyncio.to_thread(self.backend.entered.wait, 2))
        for url, payload in (("/api/workspace/minimax", {"input": dance_input()}), ("/api/generate", {})):
            self.assertEqual((await self.client.post(url, json=payload)).status, 409)
        self.assertEqual((await self.client.post(f"/api/jobs/{job['id']}/cancel", json={})).status, 200)
        self.backend.release.set()
        result = await self.terminal(job)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["result"])
        self.assertEqual(len(self.backend.calls), 1)

    async def test_settings_migrate_roundtrip_and_detect_stale_revisions(self):
        path = self.app[local.STATE].workflow_settings.path
        old = empty_settings()
        del old["minimax"]
        local.atomic_json(path, old)
        response = await self.client.get("/api/workspace/settings/minimax")
        record = await response.json()
        self.assertEqual(record["draft"], default_minimax_draft())
        draft = {**dance_input(), "generated_prompt": REF}
        saved = await self.client.put("/api/workspace/settings/minimax", json={"revision": record["revision"], "draft": draft})
        self.assertEqual(saved.status, 200)
        reload = WorkflowSettingsStore(path, local.read_store, local.atomic_json)
        self.assertEqual(reload.snapshot("minimax")["draft"], draft)
        stale = await self.client.put("/api/workspace/settings/minimax", json={"revision": 0, "draft": {}})
        self.assertEqual(stale.status, 409)
