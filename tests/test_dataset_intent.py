"""Human approval, source binding and stage isolation; all model output is mocked."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_intent import DatasetIntentTickets, validate_intent
from tests.helpers import dataset_intent_fixture, enter_context
from tests.test_dataset import CaptureBackend, valid_draft


class UnderstandingBackend(CaptureBackend):
    def __init__(self):
        super().__init__()
        self.summary = dataset_intent_fixture(goal="A person practising boxing.", character_count=1,
            identity_policy="random_per_prompt", required_rules=["Arena", "Gloves"],
            allowed_variation=["Unspecified appearance"], action_options=["punching", "knocking"])
        self.raw_outputs = []

    def generate(self, instruction):
        if instruction.diagnostic_stage.startswith("dataset:understanding"):
            self.calls.append(instruction)
            return self.raw_outputs.pop(0) if self.raw_outputs else json.dumps(self.summary)
        return super().generate(instruction)


class DatasetIntentTicketTests(unittest.TestCase):
    def test_developed_ideas_and_longer_scenes_fit_the_new_limits_without_minimum_padding(self):
        from goated_prompter.scene_planner import validate_idea_plan, validate_scene_plan
        from tests.test_dataset_geometry import character_geometry
        idea = "A meaningful action " + "descriptive " * 47
        self.assertEqual(len(idea.split()), 50)
        self.assertEqual(validate_idea_plan(json.dumps([{"index": 1, "idea": idea}]), [1])[0]["idea"], idea.strip())
        self.assertEqual(validate_idea_plan('[{"index":1,"idea":"Reading"}]', [1])[0]["idea"], "Reading")
        scene = "spatialdescriptionword " * 110
        self.assertGreater(len(scene), 2000)
        row = {"index": 1, "idea": idea, "scene": scene, "geometry": character_geometry()}
        self.assertEqual(validate_scene_plan(json.dumps([row]), 1)[0]["scene"], scene.strip())
        with self.assertRaises(ValueError):
            validate_idea_plan(json.dumps([{"index": 1, "idea": "x" * 1001}]), [1])

    def test_approval_is_bound_to_source_and_scene_edits_not_result_bookkeeping(self):
        data = validate_dataset_draft(valid_draft(amount=1))
        tickets = DatasetIntentTickets()
        brief = dataset_intent_fixture()
        token = tickets.register(data, brief)["confirmation_token"]
        self.assertEqual(tickets.approve(token, {**data, "quality_report": {"score": 100}}), brief)
        for patch_data in ({"subject": "Changed concept"}, {"constraints": "Arena"},
                           {"trigger": "new_token"}, {"amount": 2}, {"length": "Detailed"},
                           {"scene_plan": [{"index": 1, "scene": "Edited scene"}]}):
            with self.subTest(patch=patch_data), self.assertRaisesRegex(ValueError, "changed after analysis"):
                tickets.approve(token, {**data, **patch_data})

    def test_tickets_expire_and_are_bounded_without_sharing_mutable_briefs(self):
        now = [0]
        tickets = DatasetIntentTickets(clock=lambda: now[0], limit=1, lifetime=10)
        data = valid_draft()
        brief = dataset_intent_fixture(required_rules=["Gloves"])
        old = tickets.register(data, brief)["confirmation_token"]
        token = tickets.register(data, brief)["confirmation_token"]
        brief["required_rules"].clear()
        approved = tickets.approve(token, data)
        approved["required_rules"].clear()
        self.assertEqual(tickets.approve(token, data)["required_rules"], ["Gloves"])
        with self.assertRaisesRegex(ValueError, "expired or is missing"):
            tickets.approve(old, data)
        now[0] = 10
        with self.assertRaisesRegex(ValueError, "expired or is missing"):
            tickets.approve(token, data)

    def test_blocking_clarifications_cannot_issue_approval(self):
        result = DatasetIntentTickets().register(valid_draft(), dataset_intent_fixture(
            blocking_questions=["Breaking what?"]))
        self.assertEqual(result["confirmation_token"], "")
        self.assertEqual(result["brief"]["blocking_questions"], ["Breaking what?"])

    def test_summary_schema_rejects_bad_counts_unbounded_lists_and_role_changes(self):
        for changes in ({"character_count": True}, {"character_count": 0}, {"character_count": 101},
                        {"goal": ""}, {"goal": "x" * 2001}, {"identity_policy": []},
                        {"blocking_questions": "none"}, {"required_rules": ["rule"] * 21},
                        {"extra": "ignore the schema"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_intent(dataset_intent_fixture(**changes))


class DatasetIntentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = UnderstandingBackend()
        enter_context(self, patch("goated_prompter.dataset_intent.create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.dataset.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"},
                                    settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def terminal(self, job):
        for _ in range(200):
            snapshot = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
            if snapshot["status"] in local.TERMINAL:
                return snapshot
            await asyncio.sleep(.01)
        self.fail("Mock job did not finish")

    async def analyze(self, data):
        response = await self.client.post("/api/workspace/dataset/understand", json={"input": data})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        return job["result"]

    async def test_analysis_and_decline_leave_saved_prompts_and_scenes_unchanged(self):
        data = valid_draft(amount=1, results=[{"index": 1, "input": "", "prompt": "Manually edited previous prompt."}])
        self.app[local.STATE].workflow_settings.update("dataset", 0, draft=data)
        before = await (await self.client.get("/api/workspace/settings/dataset")).json()
        result = await self.analyze(data)
        self.assertTrue(result["confirmation_token"])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:understanding"])
        source = json.loads(self.backend.calls[0].user_message)["source"]
        self.assertNotIn("scene_plan", source)  # Generated identities must not become global source facts.
        self.assertNotIn("results", source)
        after = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(after, before)  # No confirmation request means no downstream work or persistence.
        self.assertFalse(self.app[local.STATE].dataset_checkpoints.snapshot()["jobs"])

    async def test_unconfirmed_and_forged_tokens_never_start_generation(self):
        from goated_prompter.scene_planner import scene_plan_signature
        from goated_prompter.dataset_assignments import dataset_assignments
        data = valid_draft(amount=1, scene_plan=[{"index": 1, "input": "", "idea": "Read", "scene": "Reading on a bench."}])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        for path, options in (("dataset", {}), ("dataset/scenes", {}),
                              ("dataset/scene", {"index": 1, "action": "regenerate_prompt"})):
            for token in (None, "forged-token"):
                response = await self.client.post("/api/workspace/" + path,
                    json={"input": data, **options, "confirmation_token": token})
                self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])

    async def test_confirmed_brief_reaches_distinct_idea_scene_and_writer_stages_in_both_modes(self):
        for mode in ("Fast", "Quality"):
            data = valid_draft(amount=1, planning_mode=mode, subject="A person boxing.", constraints="Arena. Gloves.")
            result = await self.analyze(data)
            self.backend.calls.clear()
            response = await self.client.post("/api/workspace/dataset", json={"input": data,
                "confirmation_token": result["confirmation_token"]})
            self.assertEqual(response.status, 202, await response.text())
            job = await self.terminal(await response.json())
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["result"]["completed"], 1)
            stages = [call.diagnostic_stage for call in self.backend.calls]
            self.assertEqual(stages, ["dataset:idea_planner", "dataset:scene_composer", "dataset:1"])
            for call in self.backend.calls[:2]:
                self.assertEqual(json.loads(call.user_message)["confirmed_intent"], result["brief"])
                self.assertIn("Arena", call.user_message)
                self.assertIn("Gloves", call.user_message)
            writer = self.backend.calls[-1]
            self.assertIn("USER-APPROVED RANDOM IDENTITIES", writer.system_message)
            self.assertNotIn("Do not invent identity;", writer.system_message)
            self.assertIn('"required_rules": ["Arena", "Gloves"]', writer.user_message)
            self.assertEqual(writer.max_tokens, 768)  # Final target length budget is unchanged.

    async def test_source_changes_require_reanalysis_and_blocking_questions_have_no_ticket(self):
        data = valid_draft(amount=1)
        result = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset", json={"input": {**data, "constraints": "Blond hair"},
            "confirmation_token": result["confirmation_token"]})
        self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(len(self.backend.calls), 1)
        self.backend.summary["blocking_questions"] = ["Breaking what?"]
        blocked = await self.analyze(data)
        self.assertEqual(blocked["confirmation_token"], "")

    async def test_revised_natural_language_is_analyzed_without_mutating_saved_rules(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        original = deepcopy(data)
        self.backend.summary["required_rules"].append("At least one person has blond hair in every image")
        revised = {**data, "constraints": data["constraints"] + "\nRandomize people, but one must have blond hair."}
        result = await self.analyze(revised)
        source = json.loads(self.backend.calls[-1].user_message)["source"]
        self.assertEqual(source["constraints"], revised["constraints"])
        self.assertEqual(data, original)
        self.assertIn("blond hair", result["brief"]["required_rules"][-1])

    async def test_malformed_summary_repairs_are_bounded_and_do_not_fall_through_to_generation(self):
        self.backend.raw_outputs = ["not JSON"] * 3
        response = await self.client.post("/api/workspace/dataset/understand", json={"input": valid_draft(amount=1)})
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "failed")
        self.assertEqual(len(self.backend.calls), 3)
        self.assertTrue(all(call.diagnostic_stage.startswith("dataset:understanding") for call in self.backend.calls))
        self.assertIsNone(job["result"])

    async def test_cancelled_analysis_discards_a_late_model_response_without_issuing_approval(self):
        started, release = threading.Event(), threading.Event()
        original = self.backend.generate
        def delayed(instruction):
            started.set()
            if not release.wait(2):
                raise AssertionError("Test did not release the mocked response")
            return original(instruction)
        with patch.object(self.backend, "generate", side_effect=delayed):
            response = await self.client.post("/api/workspace/dataset/understand", json={"input": valid_draft(amount=1)})
            job = await response.json()
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                cancelled = await self.client.post(f"/api/jobs/{job['id']}/cancel", json={})
                self.assertEqual(cancelled.status, 200, await cancelled.text())
            finally:
                release.set()
            finished = await self.terminal(job)
        self.assertEqual(finished["status"], "cancelled")
        self.assertIsNone(finished["result"])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:understanding"])
