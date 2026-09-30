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
from goated_prompter.backends.base import BackendRunawayError, GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import (
    DatasetService, dataset_instruction, default_dataset_draft, validate_dataset_draft,
    validate_trigger_contract,
)
from goated_prompter.dataset_coverage import analyze_dataset_quality, build_coverage_plan
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
        if instruction.diagnostic_stage == "dataset:plan":
            data = json.loads(instruction.user_message)
            return json.dumps([{"index": index, "scene": f"Distinct adventure {index}"}
                               for index in range(1, data["amount"] + 1)])
        if instruction.diagnostic_stage == "dataset:deep_review":
            return json.dumps([{"index": int(index), "issues": []}
                               for index in re.findall(r"(?m)^PROMPT (\d+)$", instruction.user_message)])
        return f"A distinct visual setup {len(self.calls)} featuring ohwx_person in the requested concept"


class RunawayOnceBackend(CaptureBackend):
    def generate(self, instruction):
        if instruction.diagnostic_stage == "dataset:plan":
            return super().generate(instruction)
        self.calls.append(instruction)
        if len(self.calls) == 2:
            raise BackendRunawayError('The prompt engine entered a repetition loop around "no visible".')
        return "A finite distinct visual setup featuring ohwx_person in the requested concept"


class AlwaysRunawayBackend(CaptureBackend):
    def generate(self, instruction):
        if instruction.diagnostic_stage == "dataset:plan":
            return super().generate(instruction)
        self.calls.append(instruction)
        raise BackendRunawayError("The prompt engine exceeded 7,000 generated characters without finishing.")


class DatasetUnitTests(unittest.TestCase):
    def test_long_trigger_paraphrase_is_kept_without_retry_and_reported(self):
        from unittest.mock import Mock
        data = valid_draft(amount=1, trigger_connected=False,
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

    def test_writer_uses_builder_system_and_omits_previous_prose(self):
        from goated_prompter.core import assemble_instruction
        data = valid_draft()
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        instruction = dataset_instruction(request, data, 2,
            [{"index": 1, "prompt": "contaminating previous prose"}],
            plan_item={"scene": "Cycling together along a country road"})
        builder = assemble_instruction(request, text_only=True)
        self.assertTrue(instruction.system_message.startswith(builder.system_message.split("WORKFLOW RULES")[0].split("Output contract:")[0].rstrip()))
        self.assertNotIn("contaminating previous prose", instruction.user_message)
        self.assertIn("Cycling together", instruction.user_message)
        self.assertIn("FRAME COMPLETENESS DEFAULT", instruction.system_message)
        self.assertIn("FRAME COMPLETENESS DEFAULT", builder.system_message)
        self.assertIn("Preserve explicit counts", builder.system_message)
        self.assertIn("all one thousand", builder.system_message)
        self.assertIn("reference locks still take priority", builder.system_message)

    def test_planner_rejects_invalid_rows_and_falls_back_without_failing_batch(self):
        service = DatasetService({}, lambda: None)
        data = valid_draft(amount=2, source_mode="guided", inputs="cycling\ntennis")
        from unittest.mock import Mock
        session = Mock()
        session.generate.return_value = '[{"index": 2, "scene": "wrong order"}]'
        progress = []
        rows = service._plan(session, data, build_coverage_plan(data), "qwen", progress.append)
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual([row["scene"] for row in rows], ["cycling", "tennis"])
        self.assertTrue(any("unavailable" in message for message in progress))

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
        data = valid_draft(visual_style="Anime / manga", target="Anima", amount=2,
                           coverage_enabled=True)
        coverage = build_coverage_plan(data)
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model="Anima"),
                                          data, 2, model_family="qwen", plan_item=coverage["plan"][1])
        self.assertIn("MODE ADAPTER", instruction.system_message)
        self.assertIn("anime/manga", instruction.system_message)
        self.assertIn('"ohwx_person"', instruction.system_message)
        self.assertIn("TRIGGER EXPANSION DISABLED", instruction.system_message)
        self.assertIn("Anima target", instruction.system_message)
        self.assertIn("DATASET CONCEPT", instruction.user_message)
        self.assertNotIn("TRIGGER DESCRIPTION", instruction.user_message)
        self.assertIn("COVERAGE ASSIGNMENT", instruction.user_message)
        self.assertIn("Framing", instruction.user_message)
        self.assertFalse(instruction.unlimited_tokens)
        self.assertEqual(instruction.hard_max_tokens, 768)
        self.assertEqual(instruction.max_tokens, 768)

    def test_coverage_plan_is_stable_balanced_and_category_aware(self):
        data = valid_draft(amount=12, source_mode="guided", inputs="portrait\naction", variety="Wide",
                           coverage_enabled=True)
        first = build_coverage_plan(data)
        self.assertEqual(first, build_coverage_plan(data))
        shuffled = build_coverage_plan({**data, "plan_seed": 1})
        self.assertNotEqual(first["plan"], shuffled["plan"])
        self.assertEqual([row["input"] for row in first["plan"][:4]], ["portrait", "action", "portrait", "action"])
        self.assertEqual(set(first["plan"][0]["facets"]),
                         {"framing", "viewpoint", "pose_action", "expression", "lighting", "setting"})
        style = build_coverage_plan(valid_draft(trigger_type="Visual style", variety="Focused",
                                                 coverage_enabled=True))
        self.assertEqual(set(style["plan"][0]["facets"]), {"subject_matter", "composition", "scale"})

    def test_coverage_is_off_by_default_and_does_not_direct_the_scene(self):
        data = valid_draft(amount=2, constraints="Every scene must focus on romance.")
        coverage = build_coverage_plan(data)
        self.assertFalse(coverage["enabled"])
        self.assertEqual(coverage["selected_axes"], [])
        self.assertTrue(all(not row["facets"] for row in coverage["plan"]))
        instruction = dataset_instruction(
            GoatedPrompterRequest(idea=data["subject"], target_model=data["target"]),
            data, 1, plan_item=coverage["plan"][0])
        self.assertIn("WORKFLOW RULES", instruction.system_message)
        self.assertIn("Every scene must focus on romance.", instruction.user_message)
        self.assertNotIn("COVERAGE ASSIGNMENT", instruction.user_message)

    def test_quality_report_finds_trigger_duplicates_format_and_leakage(self):
        data = valid_draft(amount=4)
        plan = build_coverage_plan(data)["plan"]
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
        self.assertEqual(backend.calls[0].diagnostic_stage, "dataset:plan")
        self.assertIn("CURRENT SCENE", backend.calls[1].user_message)
        self.assertTrue(all("EARLIER RESULT" not in call.user_message for call in backend.calls))
        self.assertEqual([item["input"] for item in result["prompts"]], ["standing", "running", "standing"])
        self.assertTrue(all("ohwx_person" in item["prompt"] for item in result["prompts"]))
        self.assertTrue(all(not item["prompt"].startswith("ohwx_person") for item in result["prompts"]))
        self.assertEqual([item["completed"] for item in partials], [1, 2, 3])

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
            "Planning dataset scenes…",
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
        with patch("goated_prompter.dataset.create_backend", return_value=backend), \
             self.assertRaisesRegex(Exception, "after 3 retries"):
            DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _message: None, lambda _result: None)
        self.assertEqual(len(backend.calls), 5)
        self.assertTrue(all(call.system_message.count("LOOP CORRECTION:") == 1
                            for call in backend.calls[2:]))
        self.assertIn("Prompt length — Short", backend.calls[-1].system_message)
        self.assertLessEqual(backend.calls[-1].hard_max_tokens, backend.calls[1].hard_max_tokens)

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
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = CaptureBackend()
        self.enterContext(patch("goated_prompter.dataset.create_backend", return_value=self.backend))
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

    async def test_dataset_endpoint_generates_batch_and_draft_roundtrips(self):
        data = valid_draft(amount=3, visual_style="Photorealistic")
        response = await self.client.post("/api/workspace/dataset", json={"input": data})
        self.assertEqual(response.status, 202, await response.text())
        result = await self.terminal(await response.json())
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["kind"], "dataset")
        self.assertEqual(result["result"]["completed"], 3)
        messages = [event["message"] for event in result["events"]]
        self.assertTrue(any("Waiting for prompt engine" in message for message in messages))
        self.assertTrue(any("prompt 3/3 completed" in message for message in messages))
        self.assertEqual(result["events"][-1]["type"], "success")
        self.assertEqual(len(result["result"]["coverage"]["plan"]), 3)
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

    async def test_plan_and_quality_endpoints_are_inference_free(self):
        data = valid_draft(amount=4)
        response = await self.client.post("/api/workspace/dataset/plan", json={"input": data})
        self.assertEqual(response.status, 200, await response.text())
        coverage = await response.json()
        self.assertEqual(len(coverage["plan"]), 4)
        prompts = [{"index": index, "input": "", "prompt": f"ohwx_person, distinct prompt number {index} with useful visual detail"}
                   for index in range(1, 5)]
        data.update(coverage_plan=coverage["plan"], plan_signature=coverage["signature"],
                    coverage_axes=coverage["selected_axes"], results=prompts)
        response = await self.client.post("/api/workspace/dataset/quality", json={"input": data})
        self.assertEqual(response.status, 200, await response.text())
        report = (await response.json())["report"]
        self.assertEqual(len(report["prompts"]), 4)
        self.assertNotIn("coverage", report["metrics"])
        self.assertEqual(self.backend.calls, [])

    async def test_optional_deep_review_uses_bounded_chunks(self):
        data = valid_draft(amount=5)
        coverage = build_coverage_plan(data)
        data.update(coverage_plan=coverage["plan"], plan_signature=coverage["signature"],
                    coverage_axes=coverage["selected_axes"],
                    results=[{"index": index, "input": "", "prompt": f"ohwx_person, distinct visual prompt {index} with consistent black hair and red jacket"}
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
