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
from goated_prompter.features.dataset.service import validate_dataset_draft
from goated_prompter.features.dataset.intent import DatasetIntentTickets
from goated_prompter.features.dataset.understanding import validate_understanding
from goated_prompter.json_store import atomic_json
from tests.helpers import dataset_understanding_fixture, dataset_idea_fixture, enter_context
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


class UnderstandingBackend(CaptureBackend):
    def __init__(self):
        super().__init__()
        self.summary = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "Arena"}, {"scope": "all_outputs", "text": "Gloves"},
                  {"scope": "all_outputs", "text": "Gloved hands must be readable"}],
            free=[{"scope": "dataset", "text": "Unspecified appearance"}],
            rules=[{"scope": "all_outputs", "text": "Arena"}, {"scope": "all_outputs", "text": "Gloves"}],
            may_vary=[{"scope": "dataset", "text": "Unspecified appearance"}],
            visible_evidence=[{"scope": "all_outputs", "text": "Gloved hands must be readable"}])
        self.raw_outputs = []
        self.raw_idea_outputs = []
        self.raw_scene_outputs = []

    def generate(self, instruction):
        if instruction.diagnostic_stage == "dataset:build_scene":
            self.calls.append(instruction)
            return self.raw_scene_outputs.pop(0) if self.raw_scene_outputs else json.dumps({
                "scene": "A boxer plants both feet at a training bag, extending one glove into the bag while keeping the opposite glove readable, centered in an arena training area from a three-quarter front-side angle with full-body framing.",
                "self_check": "PASS"})
        if instruction.diagnostic_stage == "dataset:ideas":
            self.calls.append(instruction)
            return self.raw_idea_outputs.pop(0) if self.raw_idea_outputs else json.dumps([
                dataset_idea_fixture(row["index"]) for row in json.loads(instruction.user_message)["assignments"]])
        if instruction.diagnostic_stage.startswith("dataset:understanding"):
            self.calls.append(instruction)
            return self.raw_outputs.pop(0) if self.raw_outputs else json.dumps(self.summary)
        return super().generate(instruction)


class DatasetIntentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = UnderstandingBackend()
        enter_context(self, patch("goated_prompter.features.dataset.understanding.create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.dataset.service.create_backend", return_value=self.backend))
        enter_context(self, patch.dict("os.environ", {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp.name) / "directors")}))
        enter_context(self, patch("local_app.get_process_manager"))
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

    async def reopen_app(self):
        await self.client.close()
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"},
                                    settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

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

    async def test_modal_endpoint_returns_complete_new_understanding_brief(self):
        result = await self.analyze(valid_draft(amount=1))
        self.assertEqual(result["brief"], self.backend.summary)
        self.assertIn("visible_evidence", result["brief"])
        self.assertIn("physical_conflicts", result["brief"])
        self.assertNotIn("goal", result["brief"])
        self.assertEqual(len(self.backend.calls), 1)

    async def test_fenced_understanding_brief_reaches_approval_without_retry_or_downstream_work(self):
        self.backend.raw_outputs = ["```json\n" + json.dumps(self.backend.summary) + "\n```"]
        result = await self.analyze(valid_draft(amount=1))
        self.assertEqual(result["brief"], self.backend.summary)
        self.assertTrue(result["confirmation_token"])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:understanding"])
        self.assertTrue(self.backend.calls[0].json_output)
        self.assertFalse(self.app[local.STATE].dataset_checkpoints.snapshot()["jobs"])

    async def test_richer_understanding_reaches_approval_and_ideas_without_losing_interpretation(self):
        self.backend.summary = dataset_understanding_fixture(character_count=2, identity_policy="random_per_prompt",
            requested_generation="Two adults sparring, with one distinct boxing action in each image. At least one must have blond hair, not necessarily both.",
            fixed=[{"scope": "all_outputs", "text": "Two adults; at least one has blond hair."}],
            action_options=[{"scope": "guided:1", "text": "A punch or a block; alternatives, not simultaneous actions."}],
            may_vary=[{"scope": "dataset", "text": "Randomize unspecified identity traits across images; preserve each identity within its scene."}])
        data = valid_draft(amount=1, source_mode="guided", inputs="A punch or a block")
        accepted = await self.analyze(data)
        self.assertEqual(accepted["brief"], self.backend.summary)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202)
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        idea_call = next(call for call in self.backend.calls if call.diagnostic_stage == "dataset:ideas")
        scene_call = next(call for call in self.backend.calls if call.diagnostic_stage == "dataset:build_scene")
        self.assertEqual(json.loads(idea_call.user_message)["confirmed_intent"], accepted["brief"])
        self.assertEqual(json.loads(scene_call.user_message)["confirmed_intent"], accepted["brief"])
        self.assertEqual(sum(call.diagnostic_stage == "dataset:understanding" for call in self.backend.calls), 1)

    async def test_empty_understanding_still_blocks_approval_and_downstream_work(self):
        self.backend.raw_outputs = [""]
        response = await self.client.post("/api/workspace/dataset/understand", json={"input": valid_draft(amount=1)})
        self.assertEqual(response.status, 202)
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["result"])
        self.assertIn("response was empty", job["error"])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:understanding"])
        self.assertFalse(self.app[local.STATE].dataset_checkpoints.snapshot()["jobs"])

    async def test_multiple_character_source_is_reviewed_carried_through_planning_and_retained_after_restart(self):
        from goated_prompter.features.dataset.prompting import dataset_instruction
        from goated_prompter.contracts import GoatedPrompterRequest
        trigger = "2 girls, mira, blue hair, bat wings, bat wings, hana, blonde hair, crystal wings"
        data = valid_draft(amount=1, trigger_type="Multiple characters", trigger=trigger,
            target="Anima", trigger_at_start=True, trigger_connected=True, expand_trigger=False,
            subject="Mira on the left reads the same book with Hana on the right. Traits may be naturally hidden.")
        self.backend.summary = dataset_understanding_fixture(character_count=2, identity_policy="fixed", hard=[
            {"scope": "all_outputs", "text": "Mira and Hana read the same book together."}])
        self.backend.raw_idea_outputs = [json.dumps([dataset_idea_fixture(idea="Hana drapes a bat wing over the table while reading with Mira.")])]
        self.backend.raw_scene_outputs = [json.dumps({"scene": "Mira on the left and Hana on the right read the same open book at a table in a medium two-shot.", "self_check": "PASS"})]
        review = await self.analyze(data)
        source_requirement = review["brief"]["hard"][-1]
        self.assertTrue(source_requirement["text"].endswith(trigger))
        self.assertEqual(review["brief"]["visible_evidence"], [])
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        done = await self.terminal(await response.json())
        self.assertEqual(done["status"], "succeeded", done.get("error"))
        calls = [call for call in self.backend.calls if call.diagnostic_stage in ("dataset:ideas", "dataset:build_scene")]
        self.assertEqual(len(calls), 2)
        for instruction in calls:
            context = json.loads(instruction.user_message)
            self.assertEqual(context["confirmed_intent"]["hard"][-1], source_requirement)
            self.assertEqual(context["confirmed_intent"]["visible_evidence"], [])
        stored = self.app[local.STATE].dataset_checkpoints.snapshot()["jobs"][-1]["approved_intent"]
        self.assertEqual(stored, review["brief"])
        await self.reopen_app()
        reopened = await (await self.client.get("/api/workspace/settings/dataset")).json()
        approved = self.app[local.STATE].dataset_intents.approve(reopened["continuation_token"], reopened["draft"])
        self.assertEqual(approved, review["brief"])
        writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]),
            {**reopened["draft"], "_confirmed_intent": approved}, 1, plan_item=reopened["draft"]["scene_plan"][0])
        self.assertIn(trigger, writer.system_message)
        self.assertIn("not a visibility requirement", writer.system_message)

    async def test_older_multiple_character_approval_is_not_silently_upgraded_on_restart(self):
        data = valid_draft(amount=1, trigger_type="Multiple characters", trigger="Mira, blue hair, Hana, blonde hair")
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        await self.client.close()
        store = self.app[local.STATE].dataset_checkpoints
        recorded = store.snapshot()
        legacy_brief = recorded["jobs"][-1]["approved_intent"]
        legacy_brief["hard"] = [item for item in legacy_brief["hard"] if "Supplied character trigger (verbatim):" not in item["text"]]
        atomic_json(store.path, recorded)
        await self.reopen_app()
        reopened = await (await self.client.get("/api/workspace/settings/dataset")).json()
        retained = self.app[local.STATE].dataset_intents.approve(reopened["continuation_token"], reopened["draft"])
        self.assertEqual(retained, legacy_brief)
        self.assertEqual(self.app[local.STATE].dataset_checkpoints.snapshot()["jobs"][-1]["approved_intent"], legacy_brief)

    async def test_full_four_stage_flow_uses_existing_builder_with_accepted_scene_as_the_entire_input(self):
        from goated_prompter.features.builder.service import assemble_instruction
        data = valid_draft(amount=1, target="Anima", length="Maximum Detail", creativity="Creative")
        accepted = await self.analyze(data)
        with patch("goated_prompter.features.builder.service.assemble_instruction", wraps=assemble_instruction) as builder:
            response = await self.client.post("/api/workspace/dataset", json={"input": data,
                "confirmation_token": accepted["confirmation_token"]})
            self.assertEqual(response.status, 202)
            finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["completed"], 1)
        builder.assert_called_once()
        builder_request = builder.call_args.args[0]
        scene = finished["result"]["scene_plan"][0]["scene"]
        self.assertEqual(builder_request.idea, scene)
        self.assertEqual(builder_request.mode, "Enhance")
        self.assertEqual(builder_request.planning_mode, "Direct")
        self.assertEqual(builder_request.target_model, "Anima")
        self.assertEqual(builder_request.prompt_length, "Maximum Detail")
        self.assertEqual(builder_request.creativity, "Creative")
        self.assertEqual(builder_request.director_preset, data["director_preset"])
        writer = self.backend.calls[-1]
        self.assertEqual(writer.user_message, scene)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls],
            ["dataset:understanding", "dataset:ideas", "dataset:build_scene", "dataset:1"])

    async def test_saved_approved_plan_continues_without_reanalysis_and_keeps_completed_prompt(self):
        data = valid_draft(amount=2)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        planned = await self.terminal(await response.json())
        self.assertEqual(planned["status"], "succeeded", planned.get("error"))
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertTrue(saved.get("continuation_token"))
        first = saved["draft"]["scene_plan"][0]
        first["prompt_status"] = "valid"
        completed = {"index": 1, "input": first["input"], "idea": first["idea"], "scene": first["scene"],
                     "prompt": "ohwx_person: my edited prompt.\n  Preserve spacing."}
        saved["draft"]["results"] = [completed]
        updated = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": saved["draft"]})
        current = await updated.json()
        self.assertEqual(current.get("continuation_token"), saved["continuation_token"])
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset", json={"input": current["draft"],
            "confirmation_token": current["continuation_token"], "resume": True, "valid_only": True})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual(finished["result"]["prompts"][0], completed)
        self.assertEqual(finished["result"]["completed"], 2)
        self.assertEqual([row["scene"] for row in finished["result"]["scene_plan"]],
            [row["scene"] for row in saved["draft"]["scene_plan"]])
        self.assertIn('"text": "Gloves"', self.backend.calls[0].system_message)

    async def test_saved_plan_continues_after_app_restart_without_reanalysis(self):
        data = valid_draft(amount=2, plan_scenes_first=True)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        first = saved["draft"]["scene_plan"][0]
        first["prompt_status"] = "valid"
        completed = {"index": 1, "input": first["input"], "idea": first["idea"], "scene": first["scene"],
                     "prompt": "ohwx_person: retain this manual prompt.\n  And spacing."}
        saved["draft"]["results"] = [completed]
        updated = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": saved["draft"]})
        self.assertEqual(updated.status, 200)
        persisted = self.app[local.STATE].dataset_checkpoints.snapshot()
        self.assertEqual(persisted["jobs"][-1]["approved_intent"], review["brief"])
        self.assertNotIn(review["confirmation_token"], json.dumps(persisted))
        await self.reopen_app()
        self.backend.calls.clear()
        reopened = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(reopened["draft"]["scene_plan"], saved["draft"]["scene_plan"])
        self.assertTrue(reopened.get("continuation_token"), "Reopening lost approval while preserving the scenes.")
        response = await self.client.post("/api/workspace/dataset", json={"input": reopened["draft"],
            "confirmation_token": reopened["continuation_token"], "resume": True, "valid_only": True})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])
        self.assertEqual(finished["result"]["prompts"][0], completed)
        self.assertEqual([row["scene"] for row in finished["result"]["scene_plan"]],
            [row["scene"] for row in saved["draft"]["scene_plan"]])
        self.assertIn('"text": "Gloves"', self.backend.calls[0].system_message)

    async def test_legacy_saved_plan_continues_after_restart_using_explicit_source_rules(self):
        data = valid_draft(amount=1, plan_scenes_first=True, constraints="Keep both gloves readable in the arena.")
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        # Stop the mock checkpoint writers before simulating an older store.
        await self.client.close()
        store = self.app[local.STATE].dataset_checkpoints
        legacy = store.snapshot()
        for row in legacy["jobs"]:
            row.pop("approved_intent", None)
        atomic_json(store.path, legacy)
        await self.reopen_app()
        self.backend.calls.clear()
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertFalse(saved["continuation_token"])
        response = await self.client.post("/api/workspace/dataset", json={"input": saved["draft"],
            "resume": True, "valid_only": True})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:1"])
        self.assertEqual(self.backend.calls[0].user_message, saved["draft"]["scene_plan"][0]["scene"])
        self.assertIn(data["constraints"], self.backend.calls[0].system_message,
                      "Older plans must retain explicit source rules even when their old review was RAM-only.")

    async def test_restart_continuation_does_not_accept_an_unsaved_or_changed_source(self):
        data = valid_draft(amount=1, plan_scenes_first=True)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        await self.reopen_app()
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.backend.calls.clear()
        changed = {**saved["draft"], "length": "Detailed"}
        response = await self.client.post("/api/workspace/dataset", json={"input": changed,
            "resume": True, "valid_only": True})
        self.assertEqual(response.status, 400)
        self.assertIn("current saved scene plan", (await response.json())["error"])
        updated = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": changed})
        self.assertEqual(updated.status, 200)
        current = await updated.json()
        self.assertFalse(current["continuation_token"])
        response = await self.client.post("/api/workspace/dataset", json={"input": current["draft"],
            "resume": True, "valid_only": True})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.backend.calls, [])

    async def test_continuation_requires_approved_source_and_tokens_bind_the_current_plan(self):
        data = valid_draft(amount=1)
        review = await self.analyze(data)
        before = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertFalse(before.get("continuation_token"))
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        token = saved.get("continuation_token")
        self.assertTrue(token)
        self.backend.calls.clear()
        for field, value in (("subject", "Changed concept"), ("constraints", "New hard rule"),
                             ("length", "Detailed"), ("trigger", "new_token")):
            with self.subTest(field=field):
                changed = {**saved["draft"], field: value}
                rejected = await self.client.post("/api/workspace/dataset", json={"input": changed,
                    "confirmation_token": token})
                self.assertEqual(rejected.status, 400, await rejected.text())
        changed = deepcopy(saved["draft"])
        changed["scene_plan"][0]["scene"] = "A different scene."
        rejected = await self.client.post("/api/workspace/dataset", json={"input": changed,
            "confirmation_token": token, "resume": True, "valid_only": True})
        self.assertEqual(rejected.status, 400, await rejected.text())
        self.assertEqual(self.backend.calls, [])
        updated = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": changed})
        current_token = (await updated.json()).get("continuation_token")
        self.assertTrue(current_token)
        self.assertNotEqual(current_token, token)

    async def test_manual_scene_repair_reuses_source_approval_but_still_requires_a_scene_check(self):
        data = valid_draft(amount=1)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        old_token = saved["continuation_token"]
        row = saved["draft"]["scene_plan"][0]
        row.update(scene="An edited training scene.", self_check="", scene_status="not_generated")
        response = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": saved["draft"]})
        edited = await response.json()
        token = edited.get("continuation_token")
        self.assertTrue(token)
        self.assertNotEqual(token, old_token)
        self.backend.calls.clear()
        refused = await self.client.post("/api/workspace/dataset/scene", json={"input": edited["draft"],
            "index": 1, "action": "regenerate_prompt", "confirmation_token": token})
        self.assertEqual(refused.status, 400)
        response = await self.client.post("/api/workspace/dataset/scene", json={"input": edited["draft"],
            "index": 1, "action": "repair_scene", "confirmation_token": token})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:build_scene", "dataset:1"])
        context = json.loads(self.backend.calls[0].user_message)
        self.assertEqual(context["confirmed_intent"], review["brief"])
        self.assertEqual(context["current_scene"], "An edited training scene.")

    async def test_stale_token_cannot_resume_old_input_over_new_saved_source(self):
        data = valid_draft(amount=1)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        updated = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": {**saved["draft"], "length": "Detailed"}})
        self.assertEqual(updated.status, 200)
        current = await updated.json()
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset", json={"input": saved["draft"],
            "confirmation_token": saved["continuation_token"], "resume": True, "valid_only": True})
        self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])
        after = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(after["draft"], current["draft"])
        self.assertEqual(after["revision"], current["revision"])

    async def test_server_invalidates_edited_scene_pass_and_preserves_checked_sibling(self):
        data = valid_draft(amount=2)
        review = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset", json={"input": data,
            "confirmation_token": review["confirmation_token"]})
        self.assertEqual((await self.terminal(await response.json()))["status"], "succeeded")
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        second_scene = deepcopy(saved["draft"]["scene_plan"][1])
        second_prompt = deepcopy(saved["draft"]["results"][1])
        saved["draft"]["scene_plan"][0]["scene"] = "A client edit retaining an obsolete PASS."
        response = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": saved["revision"], "draft": saved["draft"]})
        self.assertEqual(response.status, 200, await response.text())
        current = await response.json()
        row = current["draft"]["scene_plan"][0]
        self.assertEqual(row["self_check"], "")
        self.assertEqual(row["scene_status"], "not_generated")
        self.assertEqual(row["prompt_status"], "not_generated")
        self.assertEqual(current["draft"]["scene_plan"][1], second_scene)
        self.assertEqual(current["draft"]["results"], [second_prompt])
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset/scene", json={"input": current["draft"],
            "confirmation_token": current["continuation_token"], "action": "regenerate_prompt", "index": 1})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.backend.calls, [])

    async def test_corrected_cup_scene_reaches_builder_without_restoring_the_generated_crop(self):
        data = valid_draft(amount=1, trigger_type="Object / product",
            subject="One red ceramic cup with its base touching the table visible.")
        self.backend.summary = dataset_understanding_fixture(identity_policy="not_applicable",
            requested_generation=data["subject"],
            hard=[{"scope": "all_outputs", "text": text} for text in
                  ("Cup base touching table visible.", "Red ceramic cup.", "One cup only.")],
            soft=[{"scope": "all_outputs", "text": "Close camera and warm lighting."}],
            free=[{"scope": "all_outputs", "text": "Background and exact angle."}])
        approved = await self.analyze(data)
        proposal = dataset_idea_fixture(idea="A red ceramic cup rests on a table.",
            placement="Cup on tabletop.", visibility="Base touching table visible.",
            camera="Front three-quarter view.", framing="Tight upper-half crop.", context="Simple table setting.")
        scene = "One red ceramic cup rests upright on the tabletop. A wider front three-quarter composition includes the entire cup base in visible contact with the table, under warm lighting."
        self.backend.raw_idea_outputs = [json.dumps([proposal])]
        self.backend.raw_scene_outputs = [json.dumps({"scene": scene, "self_check": "PASS"})]
        response = await self.client.post("/api/workspace/dataset", json={"input": data,
            "confirmation_token": approved["confirmation_token"]})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["completed"], 1)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls],
            ["dataset:understanding", "dataset:ideas", "dataset:build_scene", "dataset:1"])
        ideas, composer, builder = self.backend.calls[1:]
        for call in (ideas, composer):
            self.assertEqual(json.loads(call.user_message)["confirmed_intent"], approved["brief"])
        self.assertIn("Repair generated conflicts within this same call", composer.system_message)
        self.assertEqual(json.loads(composer.user_message)["assignments"][0]["framing"], proposal["framing"])
        self.assertEqual(builder.user_message, scene)
        self.assertNotIn(proposal["framing"], builder.user_message + builder.system_message)
        self.assertIn('"hard"', builder.system_message)
        self.assertIn("Cup base touching table visible.", builder.system_message)
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(saved["draft"]["scene_plan"][0]["scene"], scene)
        self.assertEqual(saved["draft"]["scene_plan"][0]["framing"], proposal["framing"])
        self.assertTrue(saved["scene_eligibility"]["1"]["usable"])

    async def test_build_scene_returns_one_frozen_scene_and_compact_check_without_geometry_or_evaluator_calls(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=AssertionError("Unexpected evaluator")):
            response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
                "confirmation_token": accepted["confirmation_token"]})
            self.assertEqual(response.status, 202)
            finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas", "dataset:build_scene"])
        row = finished["result"]["scene_plan"][0]
        self.assertEqual(row["self_check"], "PASS")
        self.assertTrue(row["scene"])
        self.assertFalse(row.get("geometry"))

    async def test_repair_is_saved_displayable_and_blocks_writer_until_one_explicit_repair_passes(self):
        from tests.support.dataset import REPAIR, SCENE
        data = valid_draft(amount=1)
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        self.backend.raw_scene_outputs = [json.dumps({"scene": SCENE, "self_check": REPAIR})]
        response = await self.client.post("/api/workspace/dataset", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["completed"], 0)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas", "dataset:build_scene"])
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(saved["draft"]["scene_plan"][0]["self_check"], REPAIR)
        self.assertFalse(saved["scene_eligibility"]["1"]["usable"])
        data = saved["draft"]
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        refused = await self.client.post("/api/workspace/dataset/scene", json={"input": data, "index": 1,
            "action": "regenerate_prompt", "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(refused.status, 400)
        self.assertEqual(self.backend.calls, [])
        repaired = await self.client.post("/api/workspace/dataset/scene", json={"input": data, "index": 1,
            "action": "repair_scene", "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(repaired.status, 202, await repaired.text())
        finished = await self.terminal(await repaired.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["scene_plan"][0]["self_check"], "PASS")
        self.assertEqual(finished["result"]["completed"], 1)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:build_scene", "dataset:1"])
        context = json.loads(self.backend.calls[0].user_message)
        self.assertEqual(context["current_scene"], SCENE)
        self.assertEqual(context["repair_request"], REPAIR)

    async def test_still_unresolved_explicit_repair_does_not_loop_or_write_a_prompt(self):
        from tests.support.dataset import REPAIR, SCENE
        from goated_prompter.features.dataset.plan import scene_plan_signature
        from goated_prompter.features.dataset.assignments import dataset_assignments
        row = {**dataset_idea_fixture(), "input": "", "scene": SCENE, "self_check": REPAIR,
            "scene_status": "repair_required", "prompt_status": "not_generated"}
        data = valid_draft(amount=1, scene_plan=[row])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        self.backend.raw_scene_outputs = [json.dumps({"scene": SCENE, "self_check": REPAIR})]
        response = await self.client.post("/api/workspace/dataset/scene", json={"input": data, "index": 1,
            "action": "repair_scene", "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202)
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["completed"], 0)
        self.assertEqual(finished["result"]["scene_plan"][0]["self_check"], REPAIR)
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:build_scene"])

    async def test_invalid_scene_output_has_no_retry_and_preserves_pending_fixed_ideas(self):
        from tests.support.dataset import SCENE
        data = valid_draft(amount=2)
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        self.backend.raw_scene_outputs = [json.dumps({"scene": SCENE, "self_check": "PASS"}), "not JSON"]
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "failed")
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls],
            ["dataset:ideas", "dataset:build_scene", "dataset:build_scene"])
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        rows = saved["draft"]["scene_plan"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["self_check"], "PASS")
        self.assertEqual(rows[1]["self_check"], "")
        self.assertEqual(rows[1]["scene_status"], "not_generated")
        for field, value in dataset_idea_fixture(2).items():
            self.assertEqual(rows[1][field], value)

    async def test_approved_understanding_creates_compact_ideas_and_keeps_details_through_composition_and_reload(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas", "dataset:build_scene"])
        idea_call, composer = self.backend.calls
        self.assertEqual(json.loads(idea_call.user_message)["confirmed_intent"], accepted["brief"])
        expected = dataset_idea_fixture()
        for field, value in expected.items():
            self.assertEqual(job["result"]["scene_plan"][0][field], value)
            self.assertEqual(json.loads(composer.user_message)["assignments"][0][field], value)
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        for field, value in expected.items():
            self.assertEqual(saved["draft"]["scene_plan"][0][field], value)

    async def test_invalid_ideas_stop_before_composition_without_substitutes_or_saved_changes(self):
        data = valid_draft(amount=1)
        self.app[local.STATE].workflow_settings.update("dataset", 0, draft=data)
        before = await (await self.client.get("/api/workspace/settings/dataset")).json()
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        self.backend.raw_idea_outputs = ["not JSON"]
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202)
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "failed")
        self.assertIn("No automatic retry", job["error"])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:ideas"])
        after = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(after["draft"], before["draft"])
        self.assertEqual(after["revision"], before["revision"])

    async def test_cycled_guided_scope_reaches_ideas_composer_and_writer(self):
        data = valid_draft(amount=3, source_mode="guided", inputs="Training drill\n\nDefensive drill")
        self.backend.summary["rules"].append({"scope": "guided:2", "text": "At the ropes"})
        self.backend.summary["hard"].append({"scope": "guided:2", "text": "At the ropes"})
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202)
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        self.assertEqual(job["result"]["completed"], 3)
        expected = ["guided:1", "guided:2", "guided:1"]
        self.assertEqual([row["guided_scope"] for row in json.loads(self.backend.calls[0].user_message)["assignments"]], expected)
        builders = [call for call in self.backend.calls if call.diagnostic_stage == "dataset:build_scene"]
        self.assertEqual([json.loads(call.user_message)["assignments"][0]["guided_scope"] for call in builders], expected)
        writers = [call for call in self.backend.calls if call.diagnostic_stage in {"dataset:1", "dataset:2", "dataset:3"}]
        for writer, scope in zip(writers, expected):
            if scope == "guided:2":
                self.assertIn("At the ropes", writer.system_message)
            else:
                self.assertNotIn("At the ropes", writer.system_message)
            self.assertEqual(writer.user_message, job["result"]["scene_plan"][int(writer.diagnostic_stage.split(":")[1]) - 1]["scene"])

    async def test_per_idea_regeneration_keeps_siblings_and_uses_the_compact_module(self):
        data = valid_draft(amount=2, constraints="Arena. Gloves.")
        accepted = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset/scenes", json={"input": data,
            "confirmation_token": accepted["confirmation_token"]})
        planned = await self.terminal(await response.json())
        self.assertEqual(planned["status"], "succeeded", planned.get("error"))
        data.update(scene_plan=planned["result"]["scene_plan"], scene_plan_signature=planned["result"]["scene_plan_signature"])
        original = deepcopy(data["scene_plan"])
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        replacement = dataset_idea_fixture(2, idea="A boxer slips a punch and counters.", camera="Side angle.")
        self.backend.raw_idea_outputs = [json.dumps([replacement])]
        response = await self.client.post("/api/workspace/dataset/scene", json={"input": data, "index": 2,
            "action": "regenerate_idea", "confirmation_token": accepted["confirmation_token"]})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.terminal(await response.json())
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["result"]["scene_plan"][0], original[0])
        for field, value in replacement.items():
            self.assertEqual(finished["result"]["scene_plan"][1][field], value)
        idea_call = next(call for call in self.backend.calls if call.diagnostic_stage == "dataset:ideas")
        self.assertEqual([row["index"] for row in json.loads(idea_call.user_message)["assignments"]], [2])

    async def test_unconfirmed_and_forged_tokens_never_start_generation(self):
        from goated_prompter.features.dataset.plan import scene_plan_signature
        from goated_prompter.features.dataset.assignments import dataset_assignments
        data = valid_draft(amount=1, scene_plan=[{"index": 1, "input": "", "idea": "Read", "scene": "Reading on a bench.", "self_check": "PASS"}])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        for path, options in (("dataset", {}), ("dataset/scenes", {}),
                              ("dataset/scene", {"index": 1, "action": "regenerate_prompt"})):
            for token in (None, "forged-token"):
                response = await self.client.post("/api/workspace/" + path,
                    json={"input": data, **options, "confirmation_token": token})
                self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])

    async def test_confirmed_brief_reaches_distinct_idea_scene_and_builder_stages(self):
        data = valid_draft(amount=1, subject="A person boxing.", constraints="Arena. Gloves.")
        result = await self.analyze(data)
        self.backend.calls.clear()
        response = await self.client.post("/api/workspace/dataset", json={"input": data,
            "confirmation_token": result["confirmation_token"]})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(job["result"]["completed"], 1)
        stages = [call.diagnostic_stage for call in self.backend.calls]
        self.assertEqual(stages, ["dataset:ideas", "dataset:build_scene", "dataset:1"])
        for call in self.backend.calls[:2]:
            self.assertEqual(json.loads(call.user_message)["confirmed_intent"], result["brief"])
            self.assertIn("Arena", call.user_message)
            self.assertIn("Gloves", call.user_message)
        writer = self.backend.calls[-1]
        self.assertIn("SCOPED APPROVED REQUIREMENTS", writer.system_message)
        self.assertNotIn("Do not invent identity;", writer.system_message)
        self.assertIn('"hard"', writer.system_message)
        self.assertNotIn('"visible_evidence"', writer.system_message)
        self.assertIn('"text": "Gloves"', writer.system_message)
        self.assertIn("ENHANCE THE ACCEPTED SCENE", writer.system_message)
        self.assertEqual(writer.user_message, job["result"]["scene_plan"][0]["scene"])
        self.assertNotIn("COMPACT IDEA PLAN", writer.user_message)
        self.assertEqual(writer.max_tokens, 768)

    async def test_source_changes_require_reanalysis_and_blocking_questions_have_no_ticket(self):
        data = valid_draft(amount=1)
        result = await self.analyze(data)
        response = await self.client.post("/api/workspace/dataset", json={"input": {**data, "constraints": "Blond hair"},
            "confirmation_token": result["confirmation_token"]})
        self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(len(self.backend.calls), 1)
        self.backend.summary["clarifications"] = ["Breaking what?"]
        blocked = await self.analyze(data)
        self.assertEqual(blocked["confirmation_token"], "")

    async def test_revised_natural_language_is_analyzed_without_mutating_saved_rules(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        original = deepcopy(data)
        self.backend.summary["rules"].append({"scope": "all_outputs", "text": "At least one person has blond hair in every image"})
        revised = {**data, "constraints": data["constraints"] + "\nRandomize people, but one must have blond hair."}
        result = await self.analyze(revised)
        source = json.loads(self.backend.calls[-1].user_message)["source"]
        self.assertEqual(source["constraints"], revised["constraints"])
        self.assertEqual(data, original)
        self.assertIn("blond hair", result["brief"]["rules"][-1]["text"])

    async def test_extra_instructions_require_new_analysis_and_only_new_brief_is_generated(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        first = await self.analyze(data)
        revised = {**data, "constraints": data["constraints"] + "\nAt least one person has blond hair."}
        rejected = await self.client.post("/api/workspace/dataset", json={"input": revised,
            "confirmation_token": first["confirmation_token"]})
        self.assertEqual(rejected.status, 400)
        self.assertEqual(len(self.backend.calls), 1)
        self.backend.summary["rules"].append({"scope": "all_outputs", "text": "At least one person has blond hair."})
        second = await self.analyze(revised)
        self.assertNotEqual(first["confirmation_token"], second["confirmation_token"])
        response = await self.client.post("/api/workspace/dataset", json={"input": revised,
            "confirmation_token": second["confirmation_token"]})
        self.assertEqual(response.status, 202)
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        self.assertEqual(job["result"]["completed"], 1)
        planner = next(call for call in self.backend.calls if call.diagnostic_stage == "dataset:ideas")
        self.assertEqual(json.loads(planner.user_message)["confirmed_intent"], second["brief"])

    async def test_malformed_summary_stops_without_automatic_retry_or_generation(self):
        self.backend.raw_outputs = ["not JSON"] * 3
        response = await self.client.post("/api/workspace/dataset/understand", json={"input": valid_draft(amount=1)})
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "failed")
        self.assertEqual(len(self.backend.calls), 1)
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
