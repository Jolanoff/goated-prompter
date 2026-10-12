"""Exercise the browser mock through real Dataset orchestration without a browser."""

import unittest
from copy import deepcopy
from unittest.mock import patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import DatasetService
from tests.integration.browser.local_ui_server import DatasetUIMock
from tests.support.dataset import valid_draft


class BrowserDatasetContractTests(unittest.TestCase):
    def test_browser_mock_handles_planning_scene_and_prompt_validation(self):
        data = valid_draft(amount=2)
        backend = DatasetUIMock()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(result["prompts"]), 2)
        self.assertTrue(all(row["scene_spec"]["supports"] for row in result["scene_plan"]))

    def test_browser_wire_counts_include_bounded_planning_and_final_checks(self):
        data = valid_draft(amount=10)
        backend = DatasetUIMock()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend), \
                patch.object(backend, "generate", wraps=backend.generate) as calls:
            planned = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None,
                lambda _: None, scenes_only=True)
            self.assertTrue(planned["ok"], planned)
            self.assertEqual([call.args[0].diagnostic_stage for call in calls.call_args_list], [
                "dataset:ideas:brainstorm", "dataset:planning", "dataset:planning", "dataset:ideas",
                "dataset:ideas", "dataset:validation:scene", "dataset:validation:scene"])
            retained = {**data, "scene_plan": planned["scene_plan"], "scene_plan_signature": planned["scene_plan_signature"]}
            calls.reset_mock()
            written = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), retained,
                lambda _: None, lambda _: None, scene_action=("regenerate_prompt", 1))
            self.assertTrue(written["ok"], written)
            self.assertEqual([call.args[0].diagnostic_stage for call in calls.call_args_list], ["dataset:1", "dataset:validation:prompt"])
            calls.reset_mock()
            replaced = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), retained,
                lambda _: None, lambda _: None, scene_action=("regenerate_idea", 1))
            self.assertTrue(replaced["ok"], replaced)
            self.assertEqual([call.args[0].diagnostic_stage for call in calls.call_args_list], [
                "dataset:ideas", "dataset:validation:scene", "dataset:1", "dataset:validation:prompt"])

    def test_browser_mock_rechecks_explicit_edited_support_without_writing_or_changing_siblings(self):
        data, backend = valid_draft(amount=2), DatasetUIMock()
        request = GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom")
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            planned = DatasetService({"backend": "mock"}, lambda: None).run(request, data,
                lambda _: None, lambda _: None, scenes_only=True)
            rows = deepcopy(planned["scene_plan"])
            manual = "At the center, the subject sits on a bench, supported by the bench, and shapes a clay pot."
            rows[0].update(scene=manual, self_check="", scene_status="not_generated", edited_stage="scene")
            rows[0].pop("scene_validation", None)
            retained = {**data, "scene_plan": rows, "scene_plan_signature": planned["scene_plan_signature"]}
            checked = DatasetService({"backend": "mock"}, lambda: None).run(request, retained,
                lambda _: None, lambda _: None, scene_action=("validate_scene", 1))
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["prompts"], [])
        self.assertEqual(checked["scene_plan"][0]["scene"], manual)
        self.assertEqual(checked["scene_plan"][0]["scene_status"], "valid")
        self.assertEqual(checked["scene_plan"][1], rows[1])
