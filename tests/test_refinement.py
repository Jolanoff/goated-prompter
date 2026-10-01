"""Durable refinement history and isolated prompt construction."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.refinement import refine_instruction
from goated_prompter.workspace_store import WorkspaceConflict, WorkspaceStore


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(Path(self.temp.name) / "workspace.json", local.read_store, local.atomic_json)

    def test_undo_redo_and_branching_preserve_versions(self):
        initial = self.store.add_version("Original", "Generic", "Start", revision=0)
        root = initial["current_id"]
        edited = self.store.add_version("First edit", "Generic", "Refine", parent_id=root, revision=1)
        first = edited["current_id"]
        self.store.navigate("undo", 2)
        self.assertEqual(self.store.navigate("redo", 3)["current_id"], first)
        self.store.navigate("undo", 4)
        branch = self.store.add_version("Another edit", "Generic", "Refine", parent_id=root, revision=5)
        self.assertEqual(branch["redo"], [])
        self.assertEqual(len(branch["versions"]), 3)

    def test_stale_revision_does_not_change_history(self):
        original = self.store.add_version("Original", "Generic", "Start", revision=0)
        with self.assertRaises(WorkspaceConflict):
            self.store.add_version("Stale", "Generic", "Start", revision=0)
        self.assertEqual(self.store.snapshot(), original)


class ControlledBackend(GoatedPrompterBackend):
    name = "controlled"

    def __init__(self):
        self.calls = []
        self.sessions = 0

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        yield self

    def generate(self, instruction):
        self.calls.append(instruction)
        source = instruction.user_message.split("<source>\n", 1)[1].split("\n</source>", 1)[0]
        return "refined: " + source


class RefinementEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = ControlledBackend()
        self.enterContext(patch("goated_prompter.refinement.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def terminal(self, job):
        for _ in range(300):
            snapshot = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
            if snapshot["status"] in local.TERMINAL:
                return snapshot
            await asyncio.sleep(.01)
        self.fail("Job did not finish")

    async def test_refinement_persists_parent_changes_and_locks(self):
        initial = await (await self.client.post("/api/workspace", json={
            "revision": 0, "action": "add", "prompt": "A person in a red coat", "target": "Qwen Image",
        })).json()
        response = await self.client.post("/api/workspace/refine", json={
            "revision": initial["revision"], "changes": "Wider framing", "locks": ["identity", "outfit"],
        })
        result = await self.terminal(await response.json())
        self.assertEqual(result["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace")).json()
        version = saved["versions"][-1]
        self.assertEqual(version["parent_id"], initial["current_id"])
        self.assertEqual(version["instruction"], "Wider framing")
        self.assertEqual(version["locks"], ["identity", "outfit"])
        self.assertNotIn("comparisons", saved)

    async def test_removed_explore_route_is_not_available(self):
        response = await self.client.post("/api/workspace/explore", json={"revision": 0, "base": "test"})
        self.assertIn(response.status, {404, 405})


class RefinementInstructionTests(unittest.TestCase):
    def test_locks_target_contract_and_gemma_role_folding(self):
        request = GoatedPrompterRequest(idea="unused", target_model="LTX 2.5")
        instruction = refine_instruction(request, "Subject in motion", "Freeze the subject", ["pose"], model_family="gemma")
        self.assertIn("Locks outrank", instruction.system_message)
        self.assertIn("OUTPUT FORMAT — LTX 2.5", instruction.system_message)
        self.assertEqual(instruction.to_messages()[0]["role"], "user")
        self.assertTrue(instruction.unlimited_tokens)


if __name__ == "__main__":
    unittest.main()
