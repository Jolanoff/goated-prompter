"""Regression coverage for model-produced JSON leakage and bounded format repair."""

import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError, GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.prompt_catalog import TARGET_MODEL_NAMES
from goated_prompter.prompt_workflows import PromptWorkflowService
from goated_prompter.workflow_output import WorkflowFormatError, normalize_workflow_output


CAPTION = {
    "high_level_description": "Mira waits in a sunlit urban plaza.",
    "style_description": {"aesthetics": "Anime illustration", "lighting": "Daylight", "medium": "Digital illustration", "art_style": "Cel shading"},
    "compositional_deconstruction": {"background": "Urban plaza", "elements": [{"type": "obj", "desc": "Mira wears a blue jacket."}]},
}


class OutputFormatTests(unittest.TestCase):
    def test_every_non_ideogram_target_unwraps_prompt_without_changing_text(self):
        prompt = 'mira, red_hair, blue_jacket\nMira waits beside a sign reading "OPEN" in the sunlit plaza.'
        for target in TARGET_MODEL_NAMES:
            if target == "Ideogram4":
                continue
            for raw in (prompt, json.dumps({"prompt": prompt}), "```json\n" + json.dumps({"prompt": prompt}) + "\n```", json.dumps(prompt)):
                with self.subTest(target=target, raw=raw):
                    self.assertEqual(normalize_workflow_output(raw, target), prompt)

    def test_ideogram_keeps_caption_json_and_rejects_prompt_wrappers(self):
        raw = json.dumps(CAPTION, ensure_ascii=False, indent=2)
        self.assertEqual(normalize_workflow_output(raw, "Ideogram4"), raw)
        self.assertEqual(normalize_workflow_output("```json\n" + raw + "\n```", "Ideogram4"), raw)
        for invalid in ("A sunlit plaza", '{"prompt":"A sunlit plaza"}', '{"high_level_description":"Incomplete"}'):
            with self.subTest(invalid=invalid), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(invalid, "Ideogram4")

    def test_broken_or_complex_json_is_not_flattened_or_silently_saved(self):
        invalid = ('{"prompt": "A surreal anime still', '{"prompt":"Mira", "lighting":"Daylight"}',
                   '["One", "Two"]', "```json\n{", "Here is your prompt:\n{\n  \"prompt\": \"Mira",
                   json.dumps(CAPTION), '{"prompt":""}')
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(raw, "Anima")


class ScriptedBackend(GoatedPrompterBackend):
    name = "scripted"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate(self, instruction):
        self.calls.append(instruction)
        return next(self.outputs)


class FormatRepairTests(unittest.TestCase):
    def run_workflow(self, backend, target="Anima", checkpoint=lambda: None, progress=None, saved=None):
        progress = progress if progress is not None else []
        saved = saved if saved is not None else []
        workflow = {"operation": "explore", "base": "Mira waits in a sunlit urban plaza. Anime illustration.", "locks": ["identity"]}
        with patch("goated_prompter.prompt_workflows.create_backend", return_value=backend):
            return PromptWorkflowService({"backend": "mock"}, checkpoint).run(
                GoatedPrompterRequest(idea=workflow["base"], target_model=target), workflow, progress.append,
                lambda direction, prompt: saved.append((direction, prompt)))

    def test_simple_wrappers_cost_no_extra_inference_and_cannot_contaminate_later_examples(self):
        backend = ScriptedBackend(['{"prompt":"Mira in the sunlit plaza."}', "Mira in the same plaza, framed through an arch.", '{"prompt":"Mira in the same plaza, with graphic framing."}'])
        saved = []
        result = self.run_workflow(backend, saved=saved)
        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(len(saved), 3)
        self.assertEqual(result["directions"][0]["prompt"], "Mira in the sunlit plaza.")
        for call in backend.calls:
            self.assertNotIn('{"prompt":', call.user_message)
        self.assertIn("<example>\nMira in the sunlit plaza.\n</example>", backend.calls[1].user_message)

    def test_malformed_third_direction_gets_one_retry_before_persistence(self):
        backend = ScriptedBackend(["Mira in the plaza.", "Mira in the plaza, low angle.", '{"prompt": "A surreal anime still', "Mira in the plaza, graphic framing."])
        saved, progress = [], []
        result = self.run_workflow(backend, saved=saved, progress=progress)
        self.assertEqual(len(backend.calls), 4)
        self.assertEqual(len(saved), 3)
        self.assertIn("Correcting output format (one retry)", progress)
        self.assertEqual(backend.calls[3].user_message, backend.calls[2].user_message)
        self.assertEqual(result["directions"][-1]["prompt"], "Mira in the plaza, graphic framing.")

    def test_failed_repair_is_bounded_and_keeps_only_completed_directions(self):
        backend = ScriptedBackend(["Mira in the plaza.", "Mira in the plaza, low angle.", '{"prompt":', '{"prompt":'])
        saved = []
        with self.assertRaisesRegex(BackendGenerationError, "invalid format twice"):
            self.run_workflow(backend, saved=saved)
        self.assertEqual(len(backend.calls), 4)
        self.assertEqual([direction for direction, _ in saved], ["faithful", "creative"])

    def test_cancel_before_retry_does_not_start_another_call_or_save_bad_output(self):
        backend = ScriptedBackend(['{"prompt":'])
        saved, cancelled = [], []

        class Cancelled(Exception):
            pass

        def checkpoint():
            if cancelled:
                raise Cancelled()

        class Progress(list):
            def append(self, value):
                if value.startswith("Correcting"):
                    cancelled.append(True)

        with self.assertRaises(Cancelled):
            self.run_workflow(backend, saved=saved, checkpoint=checkpoint, progress=Progress())
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(saved, [])

    def test_ideogram_schema_survives_all_three_directions(self):
        raw = json.dumps(CAPTION)
        backend = ScriptedBackend([raw, raw, raw])
        result = self.run_workflow(backend, target="Ideogram4")
        self.assertEqual(len(backend.calls), 3)
        for direction in result["directions"]:
            self.assertEqual(json.loads(direction["prompt"]), CAPTION)


if __name__ == "__main__":
    unittest.main()
