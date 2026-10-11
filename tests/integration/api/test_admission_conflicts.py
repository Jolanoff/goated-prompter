"""Workspace routes refuse new work while a job is active, whatever a response's truthiness."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.local_jobs import Job
from tests.helpers import enter_context
from tests.support.dataset import valid_draft
from tests.support.minimax import dance_input


class AdmissionConflictTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = enter_context(self, tempfile.TemporaryDirectory())
        enter_context(self, patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp) / "directors")}))
        # aiohttp before 3.13 treats an empty response mapping as falsy; reproduce that on every version.
        enter_context(self, patch.object(web.StreamResponse, "__bool__", lambda _self: False, create=True))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()
        self.state = self.app[local.STATE]
        self.active = Job()
        self.state.jobs[self.active.id] = self.active

    async def asyncTearDown(self):
        await self.client.close()

    async def test_every_workspace_route_returns_conflict_without_starting_a_job(self):
        workspace = await (await self.client.get("/api/workspace")).json()
        settings = await (await self.client.get("/api/workspace/settings/refine")).json()
        requests = (
            ("/api/workspace/minimax", {"input": dance_input()}),
            ("/api/workspace/dataset/understand", {"input": valid_draft(amount=1)}),
            ("/api/workspace", {"action": "add", "prompt": "A red bicycle.", "revision": workspace["revision"]}),
            ("/api/workspace/settings/refine/instructions", {"action": "reset", "revision": settings["revision"]}),
        )
        for path, payload in requests:
            with self.subTest(path=path):
                response = await self.client.post(path, json=payload)
                self.assertEqual(response.status, 409, await response.text())
                self.assertEqual((await response.json())["active_job"]["id"], self.active.id)
        self.assertEqual(list(self.state.jobs), [self.active.id])


if __name__ == "__main__":
    unittest.main()
