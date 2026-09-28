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
from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import (
    DatasetService, dataset_instruction, default_dataset_draft, validate_dataset_draft,
)
from goated_prompter.dataset_coverage import analyze_dataset_quality, build_coverage_plan


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
        if instruction.diagnostic_stage == "dataset:deep_review":
            return json.dumps([{"index": int(index), "issues": []}
                               for index in re.findall(r"(?m)^PROMPT (\d+)$", instruction.user_message)])
        return f"Distinct visual setup {len(self.calls)}"


class DatasetUnitTests(unittest.TestCase):
    def test_validation_bounds_and_guided_requirements(self):
        self.assertEqual(validate_dataset_draft(valid_draft(amount=25), generation=True)["amount"], 25)
        for value in (0, 26, 2.5, True):
            with self.subTest(amount=value), self.assertRaises(ValueError):
                validate_dataset_draft(valid_draft(amount=value), generation=True)
        with self.assertRaisesRegex(ValueError, "guided input"):
            validate_dataset_draft(valid_draft(source_mode="guided", inputs=" \n "), generation=True)
        guided = validate_dataset_draft(valid_draft(source_mode="guided", inputs="portrait\nprofile"), generation=True)
        self.assertEqual(guided["source_mode"], "guided")

    def test_instruction_is_category_style_target_and_trigger_aware(self):
        data = valid_draft(visual_style="Anime / manga", target="Anima", amount=2,
                           coverage_enabled=True)
        coverage = build_coverage_plan(data)
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model="Anima"),
                                          data, 2, model_family="qwen", plan_item=coverage["plan"][1])
        self.assertIn("one consistent character", instruction.system_message)
        self.assertIn("anime/manga", instruction.system_message)
        self.assertIn('"ohwx_person"', instruction.system_message)
        self.assertIn("Anima target", instruction.system_message)
        self.assertIn("COVERAGE ASSIGNMENT", instruction.user_message)
        self.assertIn("Framing", instruction.user_message)
        self.assertTrue(instruction.unlimited_tokens)

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
        self.assertIn("USER-DIRECTED VARIATION", instruction.system_message)
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
        self.assertTrue({"exact_duplicate", "trigger_position", "internal_marker", "empty_output"} <= issues)
        self.assertLess(report["metrics"]["uniqueness"], 100)

    def test_service_reuses_session_and_enforces_exact_prefix(self):
        backend = CaptureBackend()
        partials = []
        data = valid_draft(amount=3, source_mode="guided", inputs="standing\nrunning")
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"],
                                        prompt_length=data["length"])
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _message: None, partials.append)
        self.assertEqual(backend.sessions, 1)
        self.assertEqual(len(backend.calls), 3)
        self.assertTrue(all("COVERAGE ASSIGNMENT" not in call.user_message for call in backend.calls))
        self.assertIn("USER-DIRECTED VARIATION", backend.calls[0].system_message)
        self.assertIn("EARLIER RESULT 1", backend.calls[1].user_message)
        self.assertEqual([item["input"] for item in result["prompts"]], ["standing", "running", "standing"])
        self.assertTrue(all(item["prompt"].startswith("ohwx_person,") for item in result["prompts"]))
        self.assertEqual([item["completed"] for item in partials], [1, 2, 3])


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
