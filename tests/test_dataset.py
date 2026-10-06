"""Dataset validation, prompt contracts, batching and HTTP integration."""

import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from tests.helpers import enter_context, confirmed_dataset_payload
from goated_prompter.backends.base import BackendRunawayError, GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import (
    DatasetService, dataset_instruction, default_dataset_draft, validate_dataset_draft,
    validate_trigger_contract,
)
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_quality import analyze_dataset_quality
from goated_prompter.dataset_triggers import trigger_contract_error, trigger_presence_error, trigger_terms


def valid_draft(**changes):
    return {**default_dataset_draft(), "trigger": "ohwx_person",
            "subject": "A woman with short black hair and a red jacket.", **changes}


class CaptureBackend(GoatedPrompterBackend):
    name = "dataset-capture"

    def __init__(self):
        self.calls = []
        self.sessions = 0

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        yield self

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage.startswith("dataset:scene_planner"):
            data = json.loads(instruction.user_message)
            from tests.test_dataset_geometry import character_geometry
            return json.dumps([{"index": index, "idea": f"Distinct activity {index}", "scene": f"Distinct adventure {index}",
                                "geometry": character_geometry(action_focus=f"Distinct activity {index}")}
                               for index in data["indexes"]])
        if instruction.diagnostic_stage.startswith("dataset:idea_planner"):
            data = json.loads(instruction.user_message)
            prefix = "Revised event" if data.get("existing_ideas") else "Replacement concept"
            return json.dumps([{"index": row["index"], "idea": f"{prefix} {row['index']}"}
                               for row in data["assignments"]])
        if instruction.diagnostic_stage.startswith("dataset:scene_composer"):
            data = json.loads(instruction.user_message)
            return json.dumps([{"index": row["index"], "idea": row["idea"],
                                "scene": f"Composed physical scene {row['index']}", "geometry": {
                                     "camera_azimuth": "front", "framing": "full_body", "body_orientation": "front",
                                    "head_direction": "toward_action", "gaze_direction": "toward_action",
                                    "pose_type": "standing_neutral", "action_focus": row["idea"],
                                    "face_visibility": "full", "visibility_focus": ["face"]}}
                               for row in data["assignments"]])
        if instruction.diagnostic_stage == "dataset:deep_review":
            return json.dumps([{"index": int(index), "issues": []}
                               for index in re.findall(r"(?m)^PROMPT (\d+)$", instruction.user_message)])
        return f"A distinct visual setup {len(self.calls)} featuring ohwx_person in the requested concept"


class RunawayOnceBackend(CaptureBackend):
    def generate(self, instruction):
        if instruction.diagnostic_stage.startswith("dataset:scene_planner"):
            return super().generate(instruction)
        self.calls.append(instruction)
        if len(self.calls) == 2:
            raise BackendRunawayError('The prompt engine entered a repetition loop around "no visible".')
        return "A finite distinct visual setup featuring ohwx_person in the requested concept"


class AlwaysRunawayBackend(CaptureBackend):
    def generate(self, instruction):
        if instruction.diagnostic_stage.startswith("dataset:scene_planner"):
            return super().generate(instruction)
        self.calls.append(instruction)
        raise BackendRunawayError("The prompt engine exceeded 7,000 generated characters without finishing.")


class DatasetUnitTests(unittest.TestCase):
    def test_legacy_prose_writer_reuses_scene_without_fabricating_idea_provenance(self):
        from goated_prompter.scene_planner import scene_plan_signature
        data = valid_draft(amount=1, planning_mode="Quality",
            scene_plan=[{"index": 1, "input": "", "scene": "A person reads a book on a bench."}])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        backend = CaptureBackend()
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"]),
                data, lambda _message: None, lambda _result: None)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:1"])
        self.assertNotIn("idea", result["prompts"][0])
        self.assertEqual(result["prompts"][0]["scene"], data["scene_plan"][0]["scene"])

    def test_obsolete_fields_are_removed_without_losing_supported_draft(self):
        data = valid_draft(results=[{"index": 1, "prompt": "A studio portrait.", "input": "portrait"}])
        legacy = {**data, "discarded_experiment": {"enabled": True}, "frame_mode": "Close-up"}
        for generation in (False, True):
            with self.subTest(generation=generation):
                self.assertEqual(validate_dataset_draft(legacy, generation=generation), data)
        self.assertIn("discarded_experiment", legacy)
        with self.assertRaises(ValueError):
            validate_dataset_draft({**legacy, "amount": 26})

    def test_long_trigger_paraphrase_is_kept_without_retry_and_reported(self):
        from unittest.mock import Mock
        data = valid_draft(amount=1, trigger_connected=False, expand_trigger=True,
            trigger="Two adult characters spending a private romantic weekend together",
            subject="A couple's romantic evening.")
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        instruction = dataset_instruction(request, data, 1)
        self.assertNotIn("distributed into", instruction.system_message)
        session = Mock()
        output = "An adult couple sharing dessert under string lights, their faces visible in the warm evening light."
        session.generate.return_value = output
        progress = []
        result = DatasetService({}, lambda: None)._generate(
            session, instruction, data, 1, progress.append)
        self.assertEqual(result, output)
        self.assertEqual(session.generate.call_count, 1)
        self.assertTrue(any("Trigger warning" in message for message in progress))
        report = analyze_dataset_quality(data, [{"index": 1, "input": "", "prompt": result}])
        missing = next(issue for issue in report["prompts"][0]["issues"] if issue["code"] == "trigger_missing")
        self.assertEqual(missing["severity"], "warning")

    def test_format_retry_does_not_restore_long_detail_after_loop(self):
        from unittest.mock import Mock
        data = valid_draft(amount=1, length="Maximum Detail")
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        original = dataset_instruction(request, data, 1)
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop"), '{"prompt":',
            "A portrait of ohwx_person in a quiet studio with soft light."]
        DatasetService({}, lambda: None)._generate(session, original, data, 1, lambda _: None)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertLess(calls[1].hard_max_tokens, calls[0].hard_max_tokens)
        self.assertEqual(calls[2].hard_max_tokens, calls[1].hard_max_tokens)
        self.assertNotIn("Prompt length — Maximum Detail", calls[2].system_message)

    def test_writer_uses_scene_locks_and_omits_previous_prose(self):
        from goated_prompter.core import assemble_instruction
        data = valid_draft()
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        instruction = dataset_instruction(request, data, 2,
            [{"index": 1, "prompt": "contaminating previous prose"}],
            plan_item={"scene": "Cycling together along a country road"})
        builder = assemble_instruction(request, text_only=True)
        self.assertTrue(instruction.system_message.startswith("You are the Dataset final writer"))
        self.assertIn("Dataset Creativity — Balanced", instruction.system_message)
        self.assertIn("Semantic decisions are locked; descriptive enrichment is allowed", instruction.system_message)
        self.assertNotIn("contaminating previous prose", instruction.user_message)
        self.assertIn("Cycling together", instruction.user_message)
        self.assertNotIn("FRAME COMPLETENESS DEFAULT", instruction.system_message)
        self.assertIn("FRAME COMPLETENESS DEFAULT", builder.system_message)
        self.assertIn("Preserve explicit counts", builder.system_message)
        self.assertNotIn("one thousand", builder.system_message)
        self.assertIn("Increase distance or field of view", builder.system_message)

    def test_planner_rejects_invalid_rows_and_records_failures_without_failing_batch(self):
        from goated_prompter.scene_planner import ScenePlanner
        planner = ScenePlanner(lambda: None)
        data = valid_draft(amount=2, source_mode="guided", inputs="cycling\ntennis")
        from unittest.mock import Mock
        session = Mock()
        session.generate.return_value = '[{"index": 2, "scene": "wrong order"}]'
        progress = []
        rows = planner.plan_batch(session=session, data=data, assignments=dataset_assignments(data),
                                  family="qwen", progress=progress.append)
        self.assertEqual(session.generate.call_count, 8)  # Chunk retry + 3 local attempts per item, never re-ideation.
        self.assertTrue(all(row["scene_status"] == "failed" and row["failure_reason"] for row in rows))
        self.assertFalse(any("new idea" in message for message in progress))

    def test_recovery_accepts_complete_valid_prefix_without_retry(self):
        from unittest.mock import Mock
        data = valid_draft(amount=1)
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        instruction = dataset_instruction(request, data, 1)
        prefix = ("A photograph of ohwx_person cycling alongside a partner on a quiet country road, "
                  "both moving together through the scene with clear gestures and coherent shadows "
                  "in soft daylight, framed with the road and nearby trees visible.")
        session = Mock()
        session.generate.side_effect = BackendRunawayError("loop", recoverable_text=prefix)
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(result, prefix)
        self.assertEqual(session.generate.call_count, 1)

    def test_validation_bounds_and_guided_requirements(self):
        self.assertEqual(validate_dataset_draft(valid_draft(amount=25), generation=True)["amount"], 25)
        for value in (0, 26, 2.5, True):
            with self.subTest(amount=value), self.assertRaises(ValueError):
                validate_dataset_draft(valid_draft(amount=value), generation=True)
        with self.assertRaisesRegex(ValueError, "guided input"):
            validate_dataset_draft(valid_draft(source_mode="guided", inputs=" \n "), generation=True)
        guided = validate_dataset_draft(valid_draft(source_mode="guided", inputs="portrait\nprofile"), generation=True)
        self.assertEqual(guided["source_mode"], "guided")
        for key in ("trigger_at_start", "trigger_connected", "expand_trigger"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "enabled or disabled"):
                validate_dataset_draft(valid_draft(**{key: "yes"}), generation=True)
        legacy = validate_dataset_draft(valid_draft(
            aspect_ratio="Widescreen (16:9)", custom_aspect_ratio="", frame_mode="Close-up"))
        self.assertNotIn("aspect_ratio", legacy)
        self.assertNotIn("frame_mode", legacy)

    def test_instruction_is_category_style_target_and_trigger_aware(self):
        data = valid_draft(visual_style="Anime / manga", target="Anima", amount=2)
        assignments = dataset_assignments(data)
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model="Anima"),
                                          data, 2, model_family="qwen", plan_item=assignments[1])
        self.assertIn("MODE ADAPTER", instruction.system_message)
        self.assertIn("anime/manga", instruction.system_message)
        self.assertIn('"ohwx_person"', instruction.system_message)
        self.assertIn("TRIGGER EXPANSION DISABLED", instruction.system_message)
        self.assertIn("Anima target", instruction.system_message)
        self.assertIn("DATASET CONCEPT", instruction.user_message)
        self.assertNotIn("TRIGGER DESCRIPTION", instruction.user_message)
        self.assertNotIn("COVERAGE ASSIGNMENT", instruction.user_message)
        self.assertFalse(instruction.unlimited_tokens)
        self.assertEqual(instruction.hard_max_tokens, 768)
        self.assertEqual(instruction.max_tokens, 768)

    def test_guided_assignments_cycle_without_prescribing_scene_details(self):
        data = valid_draft(amount=12, source_mode="guided", inputs=" portrait\n\naction ", variety="Wide")
        assignments = dataset_assignments(data)
        self.assertEqual([row["input"] for row in assignments[:4]], ["portrait", "action", "portrait", "action"])
        self.assertEqual([row["index"] for row in assignments], list(range(1, 13)))
        self.assertTrue(all(set(row) == {"index", "input"} for row in assignments))
        self.assertTrue(all(row["input"] == "" for row in dataset_assignments(valid_draft(inputs="ignored"))))

    def test_obsolete_coverage_settings_are_discarded_without_losing_saved_content(self):
        legacy = valid_draft(coverage_enabled=True, coverage_axes=["framing"], plan_seed=1,
            plan_signature="old", coverage_plan=[{"index": 1, "input": "", "facets": {"framing": "face close-up"}}],
            scene_plan=[{"index": 1, "input": "", "idea": "Reading", "scene": "Reading a book.",
                         "coverage_conflicts": ["framing"]}],
            results=[{"index": 1, "input": "", "prompt": "A finished prompt.", "coverage_conflicts": ["framing"]}],
            quality_report={"signature": "old", "metrics": {"planned_coverage": 100}})
        cleaned = validate_dataset_draft(legacy)
        for key in ("coverage_enabled", "coverage_axes", "coverage_plan", "plan_seed", "plan_signature"):
            self.assertNotIn(key, cleaned)
            self.assertNotIn(key, default_dataset_draft())
        self.assertEqual(cleaned["scene_plan"][0]["scene"], "Reading a book.")
        self.assertEqual(cleaned["results"][0]["prompt"], "A finished prompt.")
        self.assertNotIn("coverage_conflicts", cleaned["scene_plan"][0])
        self.assertNotIn("coverage_conflicts", cleaned["results"][0])
        self.assertEqual(cleaned["quality_report"], {})
        legacy["quality_report"]["metrics"] = {"coverage": 100}
        self.assertEqual(validate_dataset_draft(legacy)["quality_report"], {})

    def test_user_rules_direct_the_scene_without_coverage_assignments(self):
        data = valid_draft(amount=2, constraints="Every scene must focus on romance.")
        instruction = dataset_instruction(
            GoatedPrompterRequest(idea=data["subject"], target_model=data["target"]),
            data, 1, plan_item=dataset_assignments(data)[0])
        self.assertIn("WORKFLOW RULES", instruction.system_message)
        self.assertIn("Every scene must focus on romance", instruction.user_message)
        self.assertNotIn("COVERAGE ASSIGNMENT", instruction.user_message)

    def test_quality_report_finds_trigger_duplicates_format_and_leakage(self):
        data = valid_draft(amount=4)
        plan = dataset_assignments(data)
        results = [
            {"index": 1, "input": "", "prompt": "ohwx_person, a distinct studio portrait with soft daylight and a red jacket"},
            {"index": 2, "input": "", "prompt": "ohwx_person, a distinct studio portrait with soft daylight and a red jacket"},
            {"index": 3, "input": "", "prompt": "ITEM\n3 of 3\nmissing trigger"},
            {"index": 4, "input": "", "prompt": ""},
        ]
        report = analyze_dataset_quality(data, results, plan)
        self.assertEqual(report["status"], "issues")
        issues = {issue["code"] for record in report["prompts"] for issue in record["issues"]}
        self.assertTrue({"exact_duplicate", "trigger_missing", "internal_marker", "empty_output"} <= issues)
        self.assertLess(report["metrics"]["uniqueness"], 100)

    def test_service_reuses_session_and_allows_natural_trigger_placement(self):
        backend = CaptureBackend()
        partials = []
        data = valid_draft(amount=3, source_mode="guided", inputs="standing\nrunning")
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"],
                                        prompt_length=data["length"])
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _message: None, partials.append)
        self.assertEqual(backend.sessions, 1)
        self.assertEqual(len(backend.calls), 4)
        self.assertTrue(all("COVERAGE ASSIGNMENT" not in call.user_message for call in backend.calls))
        self.assertEqual(backend.calls[0].diagnostic_stage, "dataset:scene_planner")
        self.assertIn("CURRENT SCENE", backend.calls[1].user_message)
        self.assertTrue(all("EARLIER RESULT" not in call.user_message for call in backend.calls))
        self.assertEqual([item["input"] for item in result["prompts"]], ["standing", "running", "standing"])
        self.assertTrue(all("ohwx_person" in item["prompt"] for item in result["prompts"]))
        self.assertTrue(all(not item["prompt"].startswith("ohwx_person") for item in result["prompts"]))
        self.assertEqual([item["completed"] for item in partials], [0, 0, 1, 2, 3])
        self.assertEqual(len(partials[0]["scene_plan"]), 3)
        for partial in partials[1:]:
            self.assertTrue(all("idea" in item and "scene" in item for item in partial["prompts"]))
        self.assertTrue(all(set(item) == {"index", "input", "idea", "scene", "geometry", "prompt"}
                            for item in result["prompts"]))

    def test_service_reports_engine_waiting_and_validation_progress(self):
        backend = CaptureBackend()
        progress = []
        data = valid_draft(amount=1)
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, progress.append, lambda _result: None)
        self.assertEqual(progress, [
            "Starting the prompt engine for the dataset…",
            "Scene Planner · chunk 1–1 · planning…",
            "Waiting for prompt engine · dataset prompt 1/1",
            "Checking dataset prompt 1/1",
        ])

    def test_service_retries_runaway_output_with_finite_loop_correction(self):
        backend = RunawayOnceBackend()
        progress = []
        data = valid_draft(amount=1)
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, progress.append, lambda _result: None)
        self.assertEqual(len(backend.calls), 3)
        self.assertIn("MODE ADAPTER", backend.calls[1].system_message)
        self.assertIn("LOOP CORRECTION", backend.calls[2].system_message)
        self.assertEqual(backend.calls[2].diagnostic_stage, "dataset:1:loop_retry_1")
        self.assertTrue(any("1/3" in message for message in progress))
        self.assertIn("ohwx_person", result["prompts"][0]["prompt"])

    def test_prompt_fails_after_three_runaway_retries(self):
        backend = AlwaysRunawayBackend()
        data = valid_draft(amount=1)
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _message: None, lambda _result: None)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertIn("exceeded", result["scene_plan"][0]["failure_reason"])
        self.assertEqual(len(backend.calls), 5)  # Planner + four writer attempts, never replacement ideation.
        self.assertTrue(all(call.system_message.count("LOOP CORRECTION:") == 1
                            for call in backend.calls[2:5]))
        self.assertIn("Prompt length — Short", backend.calls[4].system_message)
        self.assertLessEqual(backend.calls[4].hard_max_tokens, backend.calls[1].hard_max_tokens)

    def test_connected_starting_and_distributed_trigger_contracts(self):
        self.assertEqual(trigger_terms("woman, cake", False), ("woman", "cake"))
        self.assertEqual(trigger_terms("1 man and 1 girl", False), ("1 man", "1 girl"))
        self.assertIsNone(trigger_contract_error(
            "A party where a woman shares a decorated cake", "woman, cake", "Generic",
            connected=False, at_start=False,
        ))
        self.assertIn("beginning placement", trigger_contract_error(
            "A portrait of ohwx_person", "ohwx_person", "Generic",
            connected=True, at_start=True,
        ))
        self.assertIsNone(trigger_contract_error(
            "ohwx_person in a city portrait", "ohwx_person", "Generic",
            connected=True, at_start=False,
        ))
        self.assertIn("remained adjacent", trigger_contract_error(
            "A party featuring a woman, cake and decorations", "woman, cake", "Generic",
            connected=False, at_start=False,
        ))
        self.assertIn("remained adjacent", trigger_contract_error(
            "An expedition featuring 1 man and 1 girl", "1 man and 1 girl", "Generic",
            connected=False, at_start=False,
        ))
        self.assertIn("missing", trigger_presence_error(
            "A party featuring a woman", "woman, cake", "Generic",
        ))
        # Trigger wording, placement and grouping misses are warnings, not
        # reasons to discard an otherwise finished prompt.
        connected_data = valid_draft(trigger="woman, cake", trigger_connected=True,
                                     trigger_at_start=True)
        self.assertEqual(
            validate_trigger_contract("A woman celebrates while sharing a cake", connected_data),
            "A woman celebrates while sharing a cake",
        )

class DatasetEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_draft_loads_and_autosaves_without_obsolete_fields(self):
        from goated_prompter.workflow_settings import empty_settings
        data = valid_draft(results=[{"index": 1, "prompt": "A studio portrait.", "input": "portrait"}])
        store = empty_settings()
        store["dataset"] = {"revision": 7, "draft": {**data, "discarded_experiment": True}, "overrides": {}}
        path = Path(self.temp.name) / "workflow_settings.json"
        path.write_text(json.dumps(store), encoding="utf-8")
        response = await self.client.get("/api/workspace/settings/dataset")
        self.assertEqual(response.status, 200, await response.text())
        record = await response.json()
        self.assertEqual(record["draft"], data)
        self.assertEqual(record["revision"], 7)
        response = await self.client.put("/api/workspace/settings/dataset", json={
            "revision": 7, "draft": {**data, "another_removed_control": "unused"}})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["draft"], data)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["dataset"]["draft"], data)
        self.assertEqual(persisted["dataset"]["revision"], 8)
        self.assertEqual(persisted["refine"], store["refine"])
        stale = await self.client.put("/api/workspace/settings/dataset", json={"revision": 7, "draft": data})
        self.assertEqual(stale.status, 409)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = CaptureBackend()
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
        self.fail("Dataset job did not finish")

    def confirmed(self, data, **options):
        return confirmed_dataset_payload(self.app[local.STATE], data, **options)

    async def test_dataset_endpoint_generates_batch_and_draft_roundtrips(self):
        data = valid_draft(amount=3, visual_style="Photorealistic")
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data))
        self.assertEqual(response.status, 202, await response.text())
        result = await self.terminal(await response.json())
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["kind"], "dataset")
        self.assertEqual(result["result"]["completed"], 3)
        messages = [event["message"] for event in result["events"]]
        self.assertTrue(any("Waiting for prompt engine" in message for message in messages))
        self.assertTrue(any("prompt 3/3 completed" in message for message in messages))
        self.assertEqual(result["events"][-1]["type"], "success")
        self.assertNotIn("coverage", result["result"])
        self.assertIn("quality_report", result["result"])
        self.assertEqual(self.backend.sessions, 1)
        record = await (await self.client.get("/api/workspace/settings/dataset")).json()
        saved = await self.client.put("/api/workspace/settings/dataset",
                                      json={"revision": record["revision"], "draft": data})
        self.assertEqual(saved.status, 200, await saved.text())
        self.assertEqual((await saved.json())["draft"], data)

    async def test_invalid_batch_never_starts_inference(self):
        for data in (valid_draft(amount=26), valid_draft(trigger=""),
                     valid_draft(source_mode="guided", inputs="")):
            response = await self.client.post("/api/workspace/dataset", json={"input": data})
            self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])

    async def test_scene_only_endpoint_persists_editable_plan_and_reuses_across_targets(self):
        data = valid_draft(amount=2, trigger="")
        response = await self.client.post("/api/workspace/dataset/scenes", json=self.confirmed(data))
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        result = job["result"]
        self.assertEqual(job["kind"], "dataset_scenes")
        self.assertNotIn("prompts", result)
        self.assertEqual(len(self.backend.calls), 2)
        data.update(scene_plan=result["scene_plan"], scene_plan_signature=result["scene_plan_signature"])
        data["scene_plan"][0]["scene"] = "An adult character reads a book while sitting on a red couch."
        data["scene_plan"][0]["idea"] = "Reading on a red couch"
        record = await (await self.client.get("/api/workspace/settings/dataset")).json()
        response = await self.client.put("/api/workspace/settings/dataset",
            json={"revision": record["revision"], "draft": data})
        self.assertEqual(response.status, 200, await response.text())
        saved = await response.json()
        self.assertTrue(saved["scene_plan_current"])
        reloaded = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(reloaded["draft"]["scene_plan"], data["scene_plan"])
        data.update(trigger="ohwx_person", target="Qwen Image", length="Detailed")
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data))
        final = await self.terminal(await response.json())
        self.assertEqual(final["status"], "succeeded", final)
        self.assertEqual(len(self.backend.calls), 4)
        self.assertEqual(final["result"]["prompts"][0]["scene"], data["scene_plan"][0]["scene"])
        self.assertEqual(final["result"]["prompts"][0]["idea"], data["scene_plan"][0]["idea"])
        self.assertIn(data["scene_plan"][0]["idea"], self.backend.calls[2].user_message)
        self.assertIn(data["scene_plan"][0]["scene"], self.backend.calls[2].user_message)
        data["results"] = final["result"]["prompts"]
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(saved["draft"]["results"], final["result"]["prompts"])
        response = await self.client.put("/api/workspace/settings/dataset",
            json={"revision": saved["revision"], "draft": data})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["draft"]["results"], final["result"]["prompts"])

    async def test_removed_coverage_endpoints_are_not_available(self):
        for path in ("plan", "coverage"):
            response = await self.client.post(f"/api/workspace/dataset/{path}", json={"input": valid_draft()})
            self.assertEqual(response.status, 405, await response.text())  # Only the SPA's GET fallback remains.
        self.assertEqual(self.backend.calls, [])

    async def test_per_scene_endpoint_preserves_other_items_and_stage_boundaries(self):
        data = valid_draft(amount=2)
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data))
        generated = (await self.terminal(await response.json()))["result"]
        data.update(scene_plan=generated["scene_plan"], scene_plan_signature=generated["scene_plan_signature"],
                    results=generated["prompts"])
        for action, stages in (("regenerate_prompt", ["dataset:1"]),
                               ("repair_scene", ["dataset:scene_composer:repair", "dataset:1"]),
                               ("regenerate_idea", ["dataset:idea_planner", "dataset:scene_composer", "dataset:1"])):
            self.backend.calls.clear()
            response = await self.client.post("/api/workspace/dataset/scene",
                json=self.confirmed(data, action=action, index=1))
            self.assertEqual(response.status, 202, await response.text())
            job = await self.terminal(await response.json())
            self.assertEqual(job["status"], "succeeded", job)
            result = job["result"]
            self.assertEqual([call.diagnostic_stage for call in self.backend.calls], stages)
            self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])
            self.assertEqual(result["prompts"][1], data["results"][1])
            if action != "regenerate_idea":
                self.assertEqual(result["scene_plan"][0]["idea"], data["scene_plan"][0]["idea"])
            self.assertEqual(validate_dataset_draft({**data, "scene_plan": result["scene_plan"],
                                                    "results": result["prompts"]})["results"], result["prompts"])

    async def test_invalid_per_scene_actions_do_not_start_inference(self):
        data = valid_draft(amount=2)
        for action, index in (("unknown", 1), ("repair_scene", True), ("repair_scene", 3), ("regenerate_prompt", 1)):
            response = await self.client.post("/api/workspace/dataset/scene",
                json={"input": data, "action": action, "index": index})
            self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])

    async def test_valid_only_api_writes_good_index_and_persists_failed_reason(self):
        from tests.test_dataset_quality_planning import saved
        from tests.test_scene_composer import rows
        data = saved(valid_draft(amount=2), rows(2))
        data["scene_plan"][0].update(idea="", scene="", geometry={}, idea_status="failed", scene_status="failed",
            prompt_status="failed", failure_stage="scene", failure_reason="Direct rear camera cannot show a full face.", replacement_attempted=True)
        data["results"] = []
        settings = await (await self.client.get("/api/workspace/settings/dataset")).json()
        response = await self.client.put("/api/workspace/settings/dataset",
            json={"revision": settings["revision"], "draft": data})
        self.assertEqual(response.status, 200, await response.text())
        persisted = await response.json()
        self.assertTrue(persisted["idea_plan_current"])
        self.assertFalse(persisted["scene_plan_current"])
        self.assertTrue(persisted["scene_plan_matches_settings"])
        self.assertEqual(persisted["draft"]["scene_plan"][0]["failure_reason"], data["scene_plan"][0]["failure_reason"])
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data, valid_only=True))
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual([row["index"] for row in job["result"]["prompts"]], [2])
        self.assertEqual(job["result"]["scene_plan"][0], data["scene_plan"][0])
        self.assertEqual([call.diagnostic_stage for call in self.backend.calls], ["dataset:2"])

    async def test_valid_only_api_rejects_invalid_flag_and_missing_valid_plan(self):
        for path, flag in (("/api/workspace/dataset", "yes"), ("/api/workspace/dataset", True),
                           ("/api/workspace/dataset/scenes", True)):
            response = await self.client.post(path, json={"input": valid_draft(), "valid_only": flag})
            self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.backend.calls, [])

    async def test_manual_idea_edit_keeps_plan_current_for_local_scene_repair(self):
        data = valid_draft(amount=2)
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data))
        generated = (await self.terminal(await response.json()))["result"]
        data.update(scene_plan=generated["scene_plan"], scene_plan_signature=generated["scene_plan_signature"],
                    results=[generated["prompts"][1]])
        data["scene_plan"][0].update(idea="Edited activity", scene="", geometry={}, scene_status="not_generated", prompt_status="not_generated")
        settings = await (await self.client.get("/api/workspace/settings/dataset")).json()
        response = await self.client.put("/api/workspace/settings/dataset",
            json={"revision": settings["revision"], "draft": data})
        self.assertEqual(response.status, 200, await response.text())
        saved = await response.json()
        self.assertTrue(saved["idea_plan_current"])
        self.assertFalse(saved["scene_plan_current"])
        response = await self.client.post("/api/workspace/dataset/scene",
            json=self.confirmed(data, action="repair_scene", index=1))
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(job["result"]["scene_plan"][0]["idea"], "Edited activity")
        self.assertEqual(job["result"]["prompts"][1], generated["prompts"][1])

    async def test_guided_cycle_keeps_expanded_plan_through_api_save_and_generation(self):
        data = valid_draft(amount=3, source_mode="guided", inputs="reading on a red couch\nlying on floor")
        expanded = {"reading on a red couch": "She sits on a red couch reading a book, eyes focused on its open pages.",
                    "lying on floor": "She lies on the floor holding a book above her, arms raised and gaze on the pages."}
        original_generate = self.backend.generate

        def generate(instruction):
            if instruction.diagnostic_stage.startswith("dataset:idea_planner"):
                self.backend.calls.append(instruction)
                context = json.loads(instruction.user_message)
                return json.dumps([{"index": row["index"], "idea": row["input"]} for row in context["assignments"]])
            if not instruction.diagnostic_stage.startswith("dataset:scene_composer"):
                return original_generate(instruction)
            self.backend.calls.append(instruction)
            context = json.loads(instruction.user_message)
            from tests.test_dataset_geometry import character_geometry
            return json.dumps([{"index": row["index"], "idea": row["input"], "scene": expanded[row["input"]],
                                "geometry": character_geometry(action_focus=row["input"])}
                               for row in context["assignments"]])

        enter_context(self, patch.object(self.backend, "generate", side_effect=generate))
        response = await self.client.post("/api/workspace/dataset/scenes", json=self.confirmed(data))
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(len(self.backend.calls), 2)
        self.assertFalse(any("failed validation" in event["message"] or "unavailable" in event["message"]
                             for event in job["events"]))
        data.update(scene_plan=job["result"]["scene_plan"], scene_plan_signature=job["result"]["scene_plan_signature"])
        self.assertEqual(data["scene_plan"][0]["scene"], expanded["reading on a red couch"])
        self.assertEqual(data["scene_plan"][2]["scene"], data["scene_plan"][0]["scene"])
        settings = await (await self.client.get("/api/workspace/settings/dataset")).json()
        response = await self.client.put("/api/workspace/settings/dataset",
            json={"revision": settings["revision"], "draft": data})
        self.assertEqual(response.status, 200, await response.text())
        self.assertTrue((await response.json())["scene_plan_current"])
        saved = await (await self.client.get("/api/workspace/settings/dataset")).json()
        self.assertEqual(saved["draft"]["scene_plan"], data["scene_plan"])
        response = await self.client.post("/api/workspace/dataset", json=self.confirmed(data))
        final = await self.terminal(await response.json())
        self.assertEqual(final["status"], "succeeded", final)
        self.assertEqual(len(self.backend.calls), 5)  # No extra planner/repair call.
        self.assertEqual(final["result"]["prompts"][2]["scene"], expanded["reading on a red couch"])

    async def test_quality_endpoint_is_inference_free_without_coverage(self):
        data = valid_draft(amount=4)
        prompts = [{"index": index, "input": "", "prompt": f"ohwx_person, distinct prompt number {index} with useful visual detail"}
                   for index in range(1, 5)]
        data.update(results=prompts)
        response = await self.client.post("/api/workspace/dataset/quality", json={"input": data})
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(set(payload), {"report"})
        report = payload["report"]
        self.assertEqual(len(report["prompts"]), 4)
        self.assertNotIn("coverage", report["metrics"])
        self.assertNotIn("planned_coverage", report["metrics"])
        self.assertEqual(self.backend.calls, [])

    async def test_optional_deep_review_uses_bounded_chunks(self):
        data = valid_draft(amount=5)
        data.update(results=[{"index": index, "input": "", "prompt": f"ohwx_person, distinct visual prompt {index} with consistent black hair and red jacket"}
                             for index in range(1, 6)])
        response = await self.client.post("/api/workspace/dataset/review", json={"input": data})
        self.assertEqual(response.status, 202, await response.text())
        result = await self.terminal(await response.json())
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(result["kind"], "dataset_review")
        self.assertTrue(result["result"]["report"]["deep_review"]["completed"])
        calls = [call for call in self.backend.calls if call.diagnostic_stage == "dataset:deep_review"]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call.max_tokens == 2048 and not call.unlimited_tokens for call in calls))


if __name__ == "__main__":
    unittest.main()
