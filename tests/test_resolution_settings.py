"""Canvas guidance, independently revisioned workflow drafts and saved instructions."""

import asyncio
from math import gcd
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.prompt_workflows import workflow_instruction
from goated_prompter.resolution import RESOLUTION_PRESETS, normalize_resolution, resolution_guidance
from goated_prompter.workflow_settings import WorkflowSettingsStore
from goated_prompter.workspace_store import WorkspaceConflict


class ResolutionTests(unittest.TestCase):
    def test_presets_are_exact_ratios_and_canonical_pixel_dimensions(self):
        self.assertEqual(list(RESOLUTION_PRESETS), ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"])
        for ratio, (width, height) in RESOLUTION_PRESETS.items():
            factor = gcd(width, height)
            expected = tuple(int(part) for part in ratio.split(":"))
            ef = gcd(*expected)
            self.assertEqual((width // factor, height // factor), (expected[0] // ef, expected[1] // ef))
            self.assertEqual(normalize_resolution({"aspect_ratio": ratio, "width": 1, "height": 1}),
                             {"aspect_ratio": ratio, "width": width, "height": height})

    def test_drafts_accept_incomplete_dimensions_but_generation_rejects_them(self):
        for width in ("", 0, 1, 999999):
            value = {"aspect_ratio": "Custom", "width": width, "height": 512}
            self.assertEqual(normalize_resolution(value, draft=True), value)
            with self.assertRaises(ValueError):
                normalize_resolution(value)
        for value in ([], {"aspect_ratio": "unknown"}, {"aspect_ratio": "Custom", "width": True, "height": 512},
                      {"aspect_ratio": "Custom", "width": 512.5, "height": 512}):
            with self.assertRaises(ValueError):
                normalize_resolution(value)

    def test_canvas_guides_orientation_density_and_motion_without_forcing_detail(self):
        small = resolution_guidance({"aspect_ratio": "Custom", "width": 320, "height": 480})
        self.assertIn("aspect ratio 2:3", small)
        self.assertIn("Portrait frame", small)
        self.assertIn("Small output", small)
        self.assertIn("throughout subject and camera movement", small)
        large = resolution_guidance({"aspect_ratio": "Custom", "width": 3840, "height": 2160})
        self.assertIn("Large output", large)
        self.assertIn("Landscape frame", large)
        self.assertIn("ultrawide", resolution_guidance({"aspect_ratio": "21:9"}))
        self.assertEqual(resolution_guidance(None), "")

    def test_builder_and_workflow_receive_same_resolution_contract(self):
        request = GoatedPrompterRequest.from_mapping({"idea": "A group portrait", "resolution": {"aspect_ratio": "9:16"}})
        guidance = resolution_guidance(request.resolution)
        self.assertIn(guidance, assemble_instruction(request, text_only=True).system_message)
        self.assertIn(guidance, workflow_instruction(request, "explore", request.idea, "", [], "creative").system_message)
        self.assertNotIn("OUTPUT CANVAS", assemble_instruction(GoatedPrompterRequest(idea="Portrait")).system_message)


class SettingsStoreTests(unittest.TestCase):
    def test_revision_is_per_workflow_and_failed_writes_keep_original_store(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowSettingsStore(Path(temp) / "workflow_settings.json", local.read_store, local.atomic_json)
            self.assertFalse(store.path.exists())
            refine = store.update("refine", 0, draft={"changes": "Wider shot", "locks": []})
            explore = store.update("explore", 0, draft={"base": "City", "target": "Anima"})
            self.assertEqual(refine["revision"], explore["revision"])
            with self.assertRaises(WorkspaceConflict):
                store.update("refine", 0, draft={"changes": "Stale"})
            before = store.path.read_bytes()
            with patch.object(store, "write", side_effect=OSError("Read only")):
                with self.assertRaises(OSError):
                    store.update("explore", 1, instructions={"system": "Custom instructions"})
            self.assertEqual(store.path.read_bytes(), before)
            reloaded = WorkflowSettingsStore(store.path, local.read_store, local.atomic_json)
            self.assertEqual(reloaded.snapshot("refine")["draft"]["changes"], "Wider shot")


class CaptureBackend(GoatedPrompterBackend):
    name = "capture"

    def __init__(self):
        self.calls = []

    def generate(self, instruction):
        self.calls.append(instruction)
        return "A readable scene."


class SettingsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = CaptureBackend()
        self.enterContext(patch("goated_prompter.prompt_workflows.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def get(self, path):
        response = await self.client.get(path)
        self.assertEqual(response.status, 200)
        return await response.json()

    async def finish(self, response):
        self.assertEqual(response.status, 202, await response.text())
        job = await response.json()
        for _ in range(200):
            job = await self.get(f"/api/jobs/{job['id']}")
            if job["status"] in local.TERMINAL:
                self.assertEqual(job["status"], "succeeded", job)
                return job
            await asyncio.sleep(.01)
        self.fail("Job did not finish")

    async def test_saved_system_and_direction_instructions_are_authoritative_and_resettable(self):
        response = await self.client.post("/api/workspace/settings/explore/instructions", json={"revision": 0, "action": "save",
                                         "instructions": {"system": "Use grounded graphic design.", "creative": "Creative custom marker."}})
        self.assertEqual(response.status, 200)
        saved = await response.json()
        self.assertEqual(saved["instructions"]["system"], "Use grounded graphic design.")
        self.assertIn("Clarify the source", saved["instructions"]["faithful"])
        await self.finish(await self.client.post("/api/workspace/explore", json={"revision": 0, "base": "Portrait",
                          "instructions": {"system": "Stale client override"}, "settings": {"resolution": {"aspect_ratio": "9:16"}}}))
        for instruction in self.backend.calls:
            self.assertIn("Use grounded graphic design.", instruction.system_message)
            self.assertNotIn("Stale client override", instruction.system_message)
            self.assertIn("720 x 1280", instruction.system_message)
            self.assertIn("Do not output a JSON object", instruction.system_message)
        self.assertIn("Creative custom marker", self.backend.calls[1].system_message)
        self.assertNotIn("Creative custom marker", self.backend.calls[0].system_message)
        refine = await self.get("/api/workspace/settings/refine")
        self.assertEqual(refine["overrides"], {})
        reset = await self.client.post("/api/workspace/settings/explore/instructions", json={"revision": saved["revision"], "action": "reset"})
        self.assertEqual(reset.status, 200)
        restored = await reset.json()
        self.assertEqual(restored["instructions"], restored["defaults"])

    async def test_drafts_persist_during_jobs_but_instruction_changes_are_locked(self):
        job = local.Job()
        self.app[local.STATE].jobs[job.id] = job
        response = await self.client.put("/api/workspace/settings/refine", json={"revision": 0, "draft": {"changes": "Keep face", "locks": []}})
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/workspace/settings/refine/instructions", json={"revision": 1, "action": "reset"})
        self.assertEqual(response.status, 409)
        self.assertEqual((await self.get("/api/workspace/settings/refine"))["draft"]["changes"], "Keep face")

    async def test_incomplete_resolution_can_be_saved_but_not_generated(self):
        incomplete = {"aspect_ratio": "Custom", "width": "", "height": 512}
        response = await self.client.put("/api/settings", json={"builder": {"resolution": incomplete}})
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.get("/api/settings"))["builder"]["resolution"], incomplete)
        response = await self.client.put("/api/workspace/settings/explore", json={"revision": 0, "draft": {"resolution": incomplete}})
        self.assertEqual(response.status, 200)
        for path, body in (("/api/generate", {"settings": {"idea": "Portrait", "resolution": incomplete}}),
                           ("/api/workspace/explore", {"revision": 0, "base": "Portrait"})):
            response = await self.client.post(path, json=body)
            self.assertEqual(response.status, 400)
        self.assertEqual(self.backend.calls, [])

    async def test_resolution_survives_comparison_refinement_and_saved_prompt(self):
        resolution = {"aspect_ratio": "Custom", "width": 320, "height": 480}
        await self.finish(await self.client.post("/api/workspace/explore", json={"revision": 0, "base": "Portrait", "settings": {"resolution": resolution}}))
        workspace = await self.get("/api/workspace")
        self.assertEqual(workspace["comparisons"][0]["resolution"], resolution)
        added = await self.client.post("/api/workspace", json={"revision": workspace["revision"], "action": "add", "prompt": "Portrait", "resolution": resolution})
        version = await added.json()
        await self.finish(await self.client.post("/api/workspace/refine", json={"revision": version["revision"], "changes": "Clearer subject"}))
        self.assertIn("Small output", self.backend.calls[-1].system_message)
        workspace = await self.get("/api/workspace")
        self.assertEqual(workspace["versions"][-1]["resolution"], resolution)
        record = {"id": "test", "title": "Saved version", "prompt": "A readable scene.", "target": "Generic", "createdAt": "now", "resolution": resolution}
        response = await self.client.post("/api/prompts", json=record)
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.get("/api/prompts"))["prompts"], [record])


if __name__ == "__main__":
    unittest.main()
