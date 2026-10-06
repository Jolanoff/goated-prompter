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
from tests.helpers import dataset_intent_fixture, dataset_understanding_fixture, dataset_idea_fixture, enter_context
from tests.test_dataset import CaptureBackend, valid_draft


class UnderstandingBackend(CaptureBackend):
    def __init__(self):
        super().__init__()
        self.summary = dataset_understanding_fixture(
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


class DatasetIntentTicketTests(unittest.TestCase):
    def test_new_brief_approval_keeps_local_scope_and_isolated_copy(self):
        data = valid_draft(amount=1, source_mode="guided", inputs="A handshake\nA portrait")
        brief = dataset_understanding_fixture(visible_evidence=[{"scope": "guided:2", "text": "Eyes"}])
        tickets = DatasetIntentTickets()
        registered = tickets.register(data, brief)
        brief["visible_evidence"].clear()
        approved = tickets.approve(registered["confirmation_token"], data)
        self.assertEqual(approved["visible_evidence"], [{"scope": "guided:2", "text": "Eyes"}])
        approved["visible_evidence"].clear()
        self.assertEqual(len(tickets.approve(registered["confirmation_token"], data)["visible_evidence"]), 1)

    def test_new_brief_cannot_reference_missing_guided_scope(self):
        brief = dataset_understanding_fixture(rules=[{"scope": "guided:2", "text": "Gloves"}])
        with self.assertRaises(ValueError):
            DatasetIntentTickets().register(valid_draft(source_mode="guided", inputs="Boxing"), brief)

    def test_new_physical_conflict_requires_answer_and_never_issues_token(self):
        conflict = {"scope": "all_outputs", "conflict": "Full cheek exposure conflicts with glove contact.",
                    "compatible_resolution": None}
        tickets = DatasetIntentTickets()
        with self.assertRaises(ValueError):
            tickets.register(valid_draft(), dataset_understanding_fixture(physical_conflicts=[conflict]))
        result = tickets.register(valid_draft(), dataset_understanding_fixture(physical_conflicts=[conflict],
            clarifications=["May the cheek be partly occluded?"]))
        self.assertEqual(result["confirmation_token"], "")

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
        enter_context(self, patch("goated_prompter.dataset_understanding.create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.dataset.create_backend", return_value=self.backend))
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

    async def test_full_four_stage_flow_uses_existing_builder_with_accepted_scene_as_the_entire_input(self):
        from goated_prompter.core import assemble_instruction
        data = valid_draft(amount=1, target="Anima", length="Maximum Detail", creativity="Creative", visual_style="Anime / manga")
        accepted = await self.analyze(data)
        with patch("goated_prompter.core.assemble_instruction", wraps=assemble_instruction) as builder:
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

    async def test_build_scene_returns_one_frozen_scene_and_compact_check_without_geometry_or_evaluator_calls(self):
        data = valid_draft(amount=1, constraints="Arena. Gloves.")
        accepted = await self.analyze(data)
        self.backend.calls.clear()
        with patch("goated_prompter.scene_planner.ScenePlanner._call", side_effect=AssertionError("Old evaluator invoked")), \
             patch("goated_prompter.dataset.resolve_framing_conflicts", side_effect=AssertionError("Old geometry invoked")):
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
        from tests.test_dataset_scene import REPAIR, SCENE
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
        from tests.test_dataset_scene import REPAIR, SCENE
        from goated_prompter.scene_planner import scene_plan_signature
        from goated_prompter.dataset_assignments import dataset_assignments
        row = {**dataset_idea_fixture(), "input": "", "scene": SCENE, "self_check": REPAIR,
            "scene_status": "repair_required", "prompt_status": "not_generated", "geometry": {}}
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
        from tests.test_dataset_scene import SCENE
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
            self.assertEqual(stages, ["dataset:ideas", "dataset:build_scene", "dataset:1"])
            for call in self.backend.calls[:2]:
                self.assertEqual(json.loads(call.user_message)["confirmed_intent"], result["brief"])
                self.assertIn("Arena", call.user_message)
                self.assertIn("Gloves", call.user_message)
            writer = self.backend.calls[-1]
            self.assertIn("CONFIRMED IDENTITY AND VISIBILITY", writer.system_message)
            self.assertNotIn("Do not invent identity;", writer.system_message)
            self.assertIn('"visible_evidence"', writer.system_message)
            self.assertIn('"text": "Gloves"', writer.system_message)
            self.assertIn("ENHANCE THE ACCEPTED SCENE", writer.system_message)
            self.assertEqual(writer.user_message, job["result"]["scene_plan"][0]["scene"])
            self.assertNotIn("COMPACT IDEA PLAN", writer.user_message)
            self.assertEqual(writer.max_tokens, 768)  # Final target length budget is unchanged.

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
