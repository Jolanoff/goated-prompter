"""The rebuilt HTTP path requires an unmodified, source-bound, eligible brief."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.backends.mock import MockBackend
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.features.dataset.v2.understanding import apply_rules, copied_input


class DatasetRebuildAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.value = {"path": "character", "summary": "Two adults reading", "fixed": "Two readers",
                      "randomized": "Light and framing", "must": [], "avoid": [], "characters": [
                          {"label": "reader", "gender": "custom", "custom": "adult human", "pronoun": "it", "count": 2}]}
        self.data = {**default_dataset_draft(), "subject": "Two adults reading", "amount": 1, "seed": 73,
                     "seed_mode": "fixed", "trigger": "reader"}
        self.backend = MockBackend()
        self.generate = self.enterContext(patch.object(self.backend, "generate", side_effect=lambda _prompt: json.dumps(self.value)))
        self.enterContext(patch("goated_prompter.features.dataset.v2.understanding.create_backend", return_value=self.backend))
        self.enterContext(patch("goated_prompter.features.dataset.v2.understanding.DebugTrace"))
        self.enterContext(patch("goated_prompter.features.dataset.runner.create_backend", return_value=self.backend))
        self.scenes = self.enterContext(patch("goated_prompter.features.dataset.runner.write_scenes", return_value={
            "scenes": [{"slot": 1, "actions": "reading"}], "requested": 1, "written": 1, "complete": True, "missing": [],
            "slots": [{"slot": 1, "status": "written", "input": "", "concept": None, "stage": None, "reasons": [], "tries": 1}]}))
        self.prompts = self.enterContext(patch("goated_prompter.features.dataset.runner.write_prompts", return_value=[
            {"slot": 1, "index": 1, "prompt": "reader reading", "trigger_ok": True}]))
        self.enterContext(patch("local_app.get_process_manager"))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"},
                                    settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.assertTrue(self.client.server.closed, "Synthetic HTTP listener must close")
        self.assertFalse(self.app[local.STATE].tasks, "All owned job tasks must finish")

    async def terminal(self, job):
        async def wait():
            while True:
                result = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
                if result["status"] in local.TERMINAL:
                    return result
                await asyncio.sleep(.01)
        return await asyncio.wait_for(wait(), 5)

    async def analyze(self):
        response = await self.client.post("/api/workspace/dataset/understand", json={"input": self.data})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        return {"input": deepcopy(self.data), "brief": job["result"]["brief"],
                "confirmation_token": job["result"]["confirmation_token"], "settings": {}, "operation": "dataset"}

    async def confirm(self, payload):
        return await self.client.post("/api/workspace/dataset/v2/confirm", json=payload)

    async def test_confirm_routes_scenes_only_and_full_generation_separately(self):
        payload = await self.analyze()
        self.assertTrue(payload["confirmation_token"])
        for operation, expected_calls in (("dataset/scenes", 0), ("dataset", 1)):
            with self.subTest(operation=operation):
                response = await self.confirm({**payload, "operation": operation})
                self.assertEqual(response.status, 202, await response.text())
                job = await self.terminal(await response.json())
                self.assertEqual(job["status"], "succeeded", job.get("error"))
                self.assertEqual(self.prompts.call_count, expected_calls)
                self.assertEqual(job["result"]["stage"], "scenes" if operation.endswith("scenes") else "done")
        self.assertEqual(self.scenes.call_args.args[2], payload["brief"])
        self.assertEqual(self.scenes.call_args.kwargs["vocabulary"], {"packs": []})
        self.assertEqual(set(self.scenes.call_args.kwargs), {"checkpoint", "progress", "on_slot", "vocabulary"},
                         "no Director, Visual Direction or other planning input reaches scene writing")

    async def test_the_drafts_vocabulary_packs_reach_scene_writing_without_a_new_review(self):
        payload = await self.analyze()
        packs = ["Spaces/Fantasy", "Lighting/Cinematic"]
        changed = deepcopy(payload)
        changed["input"]["vocabulary_packs"] = packs  # picked after Understanding: no new review is needed
        response = await self.confirm(changed)
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        self.assertEqual(self.scenes.call_args.kwargs["vocabulary"], {"packs": packs})

    async def test_confirm_refuses_unknown_packs_and_retired_fields(self):
        payload = await self.analyze()
        unknown = deepcopy(payload)
        unknown["input"]["vocabulary_packs"] = ["Spaces/No-Such-Pack"]
        malformed = deepcopy(payload)
        malformed["input"]["vocabulary_packs"] = "Spaces/Fantasy"
        for name, body in (("unknown pack", unknown), ("not a list", malformed),
                           ("retired selection field", {**payload, "vocabulary": {"packs": []}}),
                           ("retired visual field", {**payload, "visual_direction": {}})):
            with self.subTest(name):
                response = await self.confirm(body)
                self.assertEqual(response.status, 400, await response.text())
        self.scenes.assert_not_called()

    async def test_missing_expired_or_fabricated_approval_never_starts_scenes(self):
        payload = await self.analyze()
        for token in ("", "fabricated", None):
            with self.subTest(token=token):
                response = await self.confirm({**payload, "confirmation_token": token})
                self.assertEqual(response.status, 400)
        tickets = self.app[local.STATE].dataset_intents
        tickets.clock = lambda: float("inf")
        response = await self.confirm(payload)
        self.assertEqual(response.status, 400)
        self.scenes.assert_not_called()

    async def test_changed_source_settings_seed_or_interpretation_never_starts_scenes(self):
        payload = await self.analyze()
        for field, value in (("subject", "Different request"), ("inputs", "Different idea"), ("nsfw", True),
                             ("seed", 74), ("target", "Anima"), ("constraints", "No hats")):
            with self.subTest(field=field):
                changed = deepcopy(payload)
                changed["input"][field] = value
                response = await self.confirm(changed)
                self.assertEqual(response.status, 400, await response.text())
        for field, value in (("summary", "Different interpretation"), ("must", ["New requirement"]), ("avoid", ["No books"])):
            with self.subTest(field=field):
                changed = deepcopy(payload)
                changed["brief"][field] = value
                response = await self.confirm(changed)
                self.assertEqual(response.status, 400)
        self.scenes.assert_not_called()

    async def test_confirmation_rechecks_eligibility_even_with_a_registered_ticket(self):
        for patch_data, label in (({"subject": "An adult and a 16-year-old", "nsfw": True}, "person"),
                                  ({"subject": "An adult with a dog", "nsfw": True, "trigger_type": "Animal"}, "dog"),
                                  ({"subject": "A nude teenager", "nsfw": False}, "person")):
            with self.subTest(source=patch_data):
                data = validate_dataset_draft({**self.data, **patch_data})
                value = {**self.value, "characters": [{"label": label, "gender": "custom", "custom": label,
                                                     "pronoun": "it", "count": 1}]}
                # A ticket alone is not sufficient: confirmation must independently recheck eligibility.
                safe = {**data, "subject": "An adult", "nsfw": False}
                brief = apply_rules(value, safe, Mock())
                brief.update(path="nsfw_character" if data["nsfw"] else "sfw_character", input=copied_input(data))
                reviewed = self.app[local.STATE].dataset_intents.register(data, brief)
                response = await self.confirm({**reviewed, "input": data, "settings": {}, "operation": "dataset"})
                self.assertEqual(response.status, 400, await response.text())
        self.scenes.assert_not_called()

    async def test_an_approval_has_no_legacy_scene_or_prompt_route_to_enter(self):
        payload = await self.analyze()
        for endpoint in ("dataset", "dataset/scenes", "dataset/scene"):
            response = await self.client.post(f"/api/workspace/{endpoint}", json={
                "input": self.data, "confirmation_token": payload["confirmation_token"]})
            self.assertIn(response.status, (404, 405), await response.text())
        self.scenes.assert_not_called()
