"""Durable history, workflow isolation, cancellation and model-session contracts."""

import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.prompt_workflows import workflow_instruction
from goated_prompter.workspace_store import WorkspaceStore, WorkspaceConflict


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "workspace.json"
        self.store = WorkspaceStore(self.path, local.read_store, local.atomic_json)

    def test_undo_redo_and_branching_preserve_all_versions_on_disk(self):
        initial = self.store.add_version("Original", "Generic", "Start", revision=0)
        root = initial["current_id"]
        edited = self.store.add_version("First edit", "Generic", "Refine", parent_id=root, revision=1)
        first = edited["current_id"]
        undone = self.store.navigate("undo", 2)
        self.assertEqual(undone["current_id"], root)
        redone = self.store.navigate("redo", 3)
        self.assertEqual(redone["current_id"], first)
        self.store.navigate("undo", 4)
        branch = self.store.add_version("Another edit", "Generic", "Refine", parent_id=root, revision=5)
        self.assertEqual(branch["redo"], [])
        self.assertEqual(len(branch["versions"]), 3)
        restored = self.store.navigate("restore", 6, first)
        self.assertEqual(restored["current_id"], first)
        self.assertEqual(self.store.snapshot(), restored)
        reloaded = WorkspaceStore(self.path, local.read_store, local.atomic_json)
        self.assertEqual(reloaded.snapshot(), restored)

    def test_stale_revision_and_failed_write_never_change_history(self):
        original = self.store.add_version("Original", "Generic", "Start", revision=0)
        with self.assertRaises(WorkspaceConflict):
            self.store.add_version("Stale", "Generic", "Start", revision=0)
        with patch.object(self.store, "write", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.store.add_version("Lost", "Generic", "Edit", revision=1)
        self.assertEqual(self.store.snapshot(), original)

    def test_corrupt_file_is_not_overwritten(self):
        self.path.write_text('{"broken": true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "has not been overwritten"):
            self.store.add_version("New", "Generic", "Start")
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"broken": true}')


class ControlledBackend(GoatedPrompterBackend):
    name = "controlled"

    def __init__(self):
        self.calls = []
        self.sessions = 0
        self.exits = 0
        self.block_at = None
        self.fail_at = None
        self.entered = threading.Event()
        self.release = threading.Event()

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        try:
            yield self
        finally:
            self.exits += 1

    def generate(self, instruction):
        self.calls.append(instruction)
        if len(self.calls) == self.block_at:
            self.entered.set()
            if not self.release.wait(5):
                raise ValueError("Test backend timed out")
        if len(self.calls) == self.fail_at:
            raise ValueError("Test inference failed")
        source = instruction.user_message.split("<source>\n", 1)[1].split("\n</source>", 1)[0]
        direction = instruction.diagnostic_stage.split(":")[1] if instruction.diagnostic_stage.startswith("explore:") else "refined"
        return f"{direction}: {source}"


class WorkflowEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = ControlledBackend()
        self.enterContext(patch("goated_prompter.prompt_workflows.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        self.backend.release.set()
        await self.client.close()

    async def snapshot(self):
        return await (await self.client.get("/api/workspace")).json()

    async def mutate(self, **payload):
        snapshot = await self.snapshot()
        response = await self.client.post("/api/workspace", json={"revision": snapshot["revision"], **payload})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def start(self, operation, **payload):
        snapshot = await self.snapshot()
        response = await self.client.post(f"/api/workspace/{operation}", json={"revision": snapshot["revision"], **payload})
        self.assertEqual(response.status, 202, await response.text())
        return await response.json()

    async def terminal(self, job):
        for _ in range(300):
            snapshot = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
            if snapshot["status"] in local.TERMINAL:
                return snapshot
            await asyncio.sleep(.01)
        self.fail(f"Job did not finish: {snapshot}")

    async def test_refinement_is_isolated_and_persists_parent_changes_and_locks(self):
        initial = await self.mutate(action="add", prompt="A person in a red coat", target="Qwen Image")
        job = await self.start("refine", changes="Wider framing", locks=["identity", "outfit"],
                               settings={"target_model": "Generic", "custom_instructions": "Unrelated builder rules"})
        result = await self.terminal(job)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["kind"], "refine")
        saved = await self.snapshot()
        version = saved["versions"][-1]
        self.assertEqual(version["parent_id"], initial["current_id"])
        self.assertEqual(version["instruction"], "Wider framing")
        self.assertEqual(version["locks"], ["identity", "outfit"])
        self.assertEqual(version["target"], "Qwen Image")
        instruction = self.backend.calls[0]
        self.assertIsNone(instruction.image)
        self.assertNotIn("Unrelated builder rules", instruction.system_message)
        self.assertIn("minimum changes", instruction.system_message)
        self.assertIn("<source>\nA person in a red coat\n</source>", instruction.user_message)
        self.assertIn("REQUESTED CHANGES\nWider framing", instruction.user_message)
        undone = await self.mutate(action="undo")
        self.assertEqual(undone["current_id"], initial["current_id"])
        redone = await self.mutate(action="redo")
        self.assertEqual(redone["current_id"], version["id"])

    async def test_explore_one_session_distinct_rules_previous_outputs_and_persistence(self):
        job = await self.start("explore", base="A forest portrait", locks=["identity"])
        result = await self.terminal(job)
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNone(result["result"]["prompt"])
        self.assertEqual(self.backend.sessions, 1)
        self.assertEqual(self.backend.exits, 1)
        self.assertEqual(len(self.backend.calls), 3)
        for call, direction in zip(self.backend.calls, ("faithful", "creative", "experimental")):
            self.assertIn("DIRECTION\n" + direction, call.user_message)
            self.assertIn("<source>\nA forest portrait\n</source>", call.user_message)
        self.assertEqual([call.user_message.count("PREVIOUS DIRECTION —") for call in self.backend.calls], [0, 1, 2])
        self.assertEqual(len({call.system_message for call in self.backend.calls}), 3)
        snapshot = await self.snapshot()
        self.assertEqual(snapshot["versions"], [])
        self.assertEqual(len(snapshot["comparisons"][0]["results"]), 3)

    async def test_cancel_keeps_completed_direction_and_blocks_mutations(self):
        self.backend.block_at = 2
        job = await self.start("explore", base="A forest portrait")
        self.assertTrue(await asyncio.to_thread(self.backend.entered.wait, 2))
        snapshot = await self.snapshot()
        self.assertEqual(len(snapshot["comparisons"][0]["results"]), 1)
        for url, payload in (("/api/generate", {}), ("/api/workspace", {"action": "clear_history", "revision": snapshot["revision"]}),
                             ("/api/workspace/explore", {"base": "Other", "revision": snapshot["revision"]})):
            response = await self.client.post(url, json=payload)
            self.assertEqual(response.status, 409)
        response = await self.client.post(f"/api/jobs/{job['id']}/cancel", json={})
        self.assertEqual(response.status, 200)
        self.backend.release.set()
        ended = await self.terminal(job)
        self.assertEqual(ended["status"], "cancelled")
        self.assertEqual(len((await self.snapshot())["comparisons"][0]["results"]), 1)
        self.assertEqual(len(self.backend.calls), 2)
        self.assertEqual(self.backend.exits, 1)

    async def test_failure_retains_previous_versions_and_partial_comparisons(self):
        baseline = await self.mutate(action="add", prompt="Original", target="Generic")
        self.backend.fail_at = 1
        job = await self.start("refine", changes="New lighting")
        result = await self.terminal(job)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(await self.snapshot(), baseline)
        self.backend.fail_at = 3
        job = await self.start("explore", base="A city")
        result = await self.terminal(job)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len((await self.snapshot())["comparisons"][0]["results"]), 1)

    async def test_validation_and_stale_revision_do_not_start_inference(self):
        for operation, payload in (("refine", {"changes": "Test"}), ("explore", {"base": ""}),
                                   ("explore", {"base": "Test", "locks": ["unknown"]}),
                                   ("explore", {"base": "Test", "settings": {"target_model": "bogus"}})):
            response = await self.client.post(f"/api/workspace/{operation}", json={"revision": 0, **payload})
            self.assertEqual(response.status, 400, await response.text())
        await self.mutate(action="add", prompt="Original", target="Generic")
        response = await self.client.post("/api/workspace/refine", json={"revision": 0, "changes": "Stale"})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.backend.calls, [])

    async def test_disk_failure_retains_generated_text_for_recovery(self):
        baseline = await self.mutate(action="add", prompt="Original", target="Generic")
        with patch.object(self.app[local.STATE].workspace, "write", side_effect=OSError("Disk full")):
            job = await self.start("refine", changes="New lighting")
            result = await self.terminal(job)
        self.assertEqual(result["status"], "failed")
        self.assertIn("saving failed", result["error"])
        self.assertEqual(result["result"]["recovery_prompt"], "refined: Original")
        self.assertEqual(await self.snapshot(), baseline)

    async def test_explicit_empty_locks_and_manual_edit_preserve_user_choice(self):
        await self.mutate(action="add", prompt="Original", target="Generic", locks=[])
        job = await self.start("refine", changes="New lighting", locks=[])
        self.assertEqual((await self.terminal(job))["status"], "succeeded")
        edited = await self.mutate(action="add", prompt="Manual correction", target="Generic", edit=True)
        self.assertEqual([version["locks"] for version in edited["versions"]], [[], [], []])


class WorkflowInstructionTests(unittest.TestCase):
    def test_locks_and_target_contract_and_gemma_role_folding(self):
        request = GoatedPrompterRequest(idea="unused", target_model="LTX 2.5")
        instruction = workflow_instruction(request, "refine", "Subject in motion", "Freeze the subject", ["pose"], model_family="gemma")
        self.assertIn("Locks outrank", instruction.system_message)
        self.assertIn("OUTPUT FORMAT — LTX 2.5", instruction.system_message)
        self.assertIn("Do not output a JSON object", instruction.system_message)
        self.assertEqual(len(instruction.to_messages()), 1)
        self.assertEqual(instruction.to_messages()[0]["role"], "user")
        self.assertLess(instruction.max_tokens, 3072)

    def test_exploration_bounds_previous_output_context_without_changing_saved_results(self):
        previous = [{"direction": "faithful", "prompt": "a" * 10000}]
        instruction = workflow_instruction(GoatedPrompterRequest(idea="Test"), "explore", "Test", "", [],
                                           "creative", previous)
        excerpt = instruction.user_message.split("<example>\n", 1)[1].split("\n</example>", 1)[0]
        self.assertLess(len(excerpt), 1900)
        self.assertEqual(len(previous[0]["prompt"]), 10000)

    def test_explore_preserves_source_specificity_in_every_direction_without_json_envelope(self):
        source = "Mira, a red-haired courier in a blue jacket, waits in a sunlit urban plaza. Anime illustration."
        for direction in ("faithful", "creative", "experimental"):
            instruction = workflow_instruction(GoatedPrompterRequest(idea=source, target_model="Anima"), "explore", source, "", [], direction)
            self.assertTrue(instruction.user_message.startswith("SOURCE PROMPT\n<source>\n" + source))
            self.assertIn("Preserve all stated subjects, names, counts", instruction.system_message)
            self.assertIn("setting, time of day", instruction.system_message)
            self.assertIn("never replace a named or described character", instruction.system_message)
            self.assertNotIn("at least two", instruction.system_message)
            self.assertIn("character tag blocks", instruction.system_message)
            self.assertIn("Do not output a JSON object", instruction.user_message)


if __name__ == "__main__":
    unittest.main()
