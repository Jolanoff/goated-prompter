"""Regression coverage for model-produced JSON leakage and bounded format repair."""

import json
from copy import deepcopy
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendGenerationError, GoatedPrompterBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.prompting.target_models import TARGET_MODEL_NAMES
from goated_prompter.refinement import RefineService, refine_instruction
from goated_prompter.workflow_output import WorkflowFormatError, normalize_workflow_output, requested_visible_text


CAPTION = {
    "high_level_description": "Mira waits in a sunlit urban plaza.",
    "style_description": {"aesthetics": "Anime illustration", "lighting": "Daylight", "medium": "Digital illustration", "art_style": "Cel shading"},
    "compositional_deconstruction": {"background": "Urban plaza", "elements": [{"type": "obj", "desc": "Mira wears a blue jacket."}]},
}


class OutputFormatTests(unittest.TestCase):
    def test_minimax_named_sections_normalize_and_require_complete_structure(self):
        valid = 'integrated_multimodal_description: A runner shouts "Go!".\noverall_soundscape: Footsteps.\nnon_diegetic_music: None.'
        self.assertEqual(normalize_workflow_output(valid.upper(), "MiniMax H3").splitlines()[0],
                         'integrated_multimodal_description: A RUNNER SHOUTS "GO!".')
        self.assertEqual(normalize_workflow_output("```text\n" + valid + "\n```", "MiniMax H3"), valid)
        invalid = ("A runner moves.", json.dumps({"prompt": valid}),
                   valid.replace("overall_soundscape: Footsteps.\n", ""),
                   valid.replace("non_diegetic_music: None.", "non_diegetic_music:"),
                   valid + "\noverall_soundscape: Duplicate.",
                   "Here is your prompt:\n" + valid,
                   "\n".join(reversed(valid.splitlines())))
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(raw, "MiniMax H3")
        reference = "\n".join(f"{field}: Preserved content." for field in
            ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"))
        self.assertEqual(normalize_workflow_output(reference, "MiniMax H3"), reference)

    def test_every_plain_text_target_unwraps_prompt_without_changing_text(self):
        prompt = 'mira, red_hair, blue_jacket\nMira waits beside a sign reading "OPEN" in the sunlit plaza.'
        for target in TARGET_MODEL_NAMES:
            if target == "Ideogram4":
                continue
            for raw in (prompt, json.dumps({"prompt": prompt}), "```json\n" + json.dumps({"prompt": prompt}) + "\n```", json.dumps(prompt)):
                with self.subTest(target=target, raw=raw):
                    self.assertEqual(normalize_workflow_output(raw, target, mode="Enhance"), prompt)

    def test_ideogram_keeps_caption_json_and_rejects_prompt_wrappers(self):
        raw = json.dumps(CAPTION, ensure_ascii=False, indent=2)
        self.assertEqual(normalize_workflow_output(raw, "Ideogram4"), raw)
        self.assertEqual(normalize_workflow_output("```json\n" + raw + "\n```", "Ideogram4"), raw)
        for invalid in ("A sunlit plaza", '{"prompt":"A sunlit plaza"}', '{"high_level_description":"Incomplete"}'):
            with self.subTest(invalid=invalid), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(invalid, "Ideogram4")

    def test_ideogram_bbox_palettes_and_order_are_strict(self):
        valid = deepcopy(CAPTION)
        valid["style_description"]["color_palette"] = ["#AABBCC"]
        valid["compositional_deconstruction"]["elements"] = [
            {"type": "text", "bbox": [0, 10, 500, 900], "text": '你好  "OPEN"!',
             "desc": "Exact lettering", "color_palette": ["#FFFFFF"]}]
        raw = json.dumps(valid, ensure_ascii=False)
        self.assertEqual(normalize_workflow_output(raw, "Ideogram4"), raw)
        self.assertEqual(json.loads(raw)["compositional_deconstruction"]["elements"][0]["text"], '你好  "OPEN"!')
        for box in ([0, 0, 0, 10], [10, 20, 5, 30], [0, 10, 500, 10], [-1, 0, 50, 50],
                    [0, 0, 1001, 1000], [False, 0, 50, 50], [0.0, 0, 50, 50], [0, 0, 50]):
            invalid = deepcopy(valid)
            invalid["compositional_deconstruction"]["elements"][0]["bbox"] = box
            with self.subTest(box=box), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(json.dumps(invalid), "Ideogram4")
        for palette in (["#aabbcc"], ["red"], ["#ABC"], "#AABBCC", ["#FFFFFF"] * 17):
            invalid = deepcopy(valid)
            invalid["style_description"]["color_palette"] = palette
            with self.subTest(palette=palette), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(json.dumps(invalid), "Ideogram4")
        invalid = deepcopy(valid)
        invalid["style_description"]["photo"] = "Photographic camera"
        wrong_order = {key: valid[key] for key in reversed(valid)}
        unknown = {**valid, "unexpected": "value"}
        for caption in (invalid, wrong_order, unknown):
            with self.subTest(caption=caption), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(json.dumps(caption), "Ideogram4")

    def test_ideogram_photo_order_and_duplicate_keys(self):
        photo = deepcopy(CAPTION)
        photo["style_description"] = {"aesthetics": "Portrait", "lighting": "Daylight", "photo": "Eye-level view", "medium": "Photograph"}
        raw = json.dumps(photo)
        self.assertEqual(normalize_workflow_output(raw, "Ideogram4"), raw)
        duplicate = raw.replace('"high_level_description":', '"high_level_description":"Duplicate", "high_level_description":', 1)
        with self.assertRaises(WorkflowFormatError):
            normalize_workflow_output(duplicate, "Ideogram4")

    def test_ideogram_literal_text_must_match_requested_case_spacing_and_script(self):
        caption = deepcopy(CAPTION)
        literal = "你好  OPEN!"
        caption["compositional_deconstruction"]["elements"] = [{"type": "text", "text": literal, "desc": "Printed title"}]
        expected = requested_visible_text('A poster with the title "你好  OPEN!".')
        self.assertEqual(expected, (literal,))
        self.assertEqual(normalize_workflow_output(json.dumps(caption), "Ideogram4", expected_visible_text=expected), json.dumps(caption))
        for changed in ("你好 OPEN!", "你好  open!", "OPEN!"):
            caption["compositional_deconstruction"]["elements"][0]["text"] = changed
            with self.subTest(changed=changed), self.assertRaisesRegex(WorkflowFormatError, "exactly"):
                normalize_workflow_output(json.dumps(caption), "Ideogram4", expected_visible_text=expected)

    def test_qwen21_extracts_legacy_prompt_and_rejects_unusable_wrappers(self):
        payload = {
            "rewritten_prompt": "A warm editorial photograph of a red bicycle beside a brick wall.",
            "wh_ratio": "3:2",
            "ratio_follow": "",
        }
        raw = json.dumps(payload)
        self.assertEqual(normalize_workflow_output(raw, "Qwen2.1"), payload["rewritten_prompt"])
        self.assertEqual(normalize_workflow_output("```json\n" + raw + "\n```", "Qwen2.1"), payload["rewritten_prompt"])
        for invalid in ('{"rewritten_prompt":', '{"rewritten_prompt":[]}', '{"rewritten_prompt":""}',
                        '{"rewritten_prompt":"A bicycle", "unrelated_details":"Must not be silently lost"}'):
            with self.subTest(invalid=invalid), self.assertRaises(WorkflowFormatError):
                normalize_workflow_output(invalid, "Qwen2.1")

    def test_qwen21_plain_output_preserves_paragraphs_unicode_and_quotes(self):
        payload = {"rewritten_prompt": 'A poster with a header reading "你好".\n\nBelow it, a red bicycle fills the lower panel.', "wh_ratio": "2:3"}
        raw = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(normalize_workflow_output(raw, "Qwen2.1"), payload["rewritten_prompt"])
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        normalized = normalize_workflow_output(pretty, "Qwen2.1")
        self.assertEqual(normalized, payload["rewritten_prompt"])
        legacy = json.dumps({**payload, "ratio_follow": ""}, ensure_ascii=False)
        self.assertEqual(normalize_workflow_output(legacy, "Qwen2.1"), payload["rewritten_prompt"])

    def test_qwen21_does_not_require_ratio_metadata_to_deliver_prompt_text(self):
        prompt = '将图中标题替换为"夏日特惠"，保留其余内容不变。'
        for metadata in ({}, {"wh_ratio": "3:2"}, {"wh_ratio": "", "ratio_follow": ""},
                         {"wh_ratio": "", "ratio_follow": "<image2>"}, {"wh_ratio": "Auto"}):
            raw = json.dumps({"rewritten_prompt": prompt, **metadata}, ensure_ascii=False)
            self.assertEqual(normalize_workflow_output(raw, "Qwen2.1"), prompt)

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
    def test_minimax_malformed_sections_are_repaired_and_not_sanitized(self):
        valid = 'integrated_multimodal_description: [Shot 1] A runner shouts "Go!" (quietly).\noverall_soundscape: Footsteps.\nnon_diegetic_music: None.'
        backend = ScriptedBackend(["A runner moves.", valid])
        result = self.run_workflow(backend, target="MiniMax H3")
        self.assertEqual(result["prompt"], valid)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("MiniMax H3 requires", backend.calls[1].system_message)

    def run_workflow(self, backend, target="Anima", checkpoint=lambda: None, progress=None):
        progress = progress if progress is not None else []
        workflow = {"operation": "refine", "base": "Mira waits in a sunlit urban plaza. Anime illustration.",
                    "changes": "Use stronger framing", "locks": ["identity"]}
        with patch("goated_prompter.refinement.create_backend", return_value=backend):
            return RefineService({"backend": "mock"}, checkpoint).run(
                GoatedPrompterRequest(idea=workflow["base"], target_model=target), workflow, progress.append)

    def test_simple_wrapper_costs_no_extra_inference(self):
        backend = ScriptedBackend(['{"prompt":"Mira in the sunlit plaza."}'])
        result = self.run_workflow(backend)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompt"], "Mira in the sunlit plaza.")

    def test_malformed_output_gets_one_retry(self):
        backend = ScriptedBackend(['{"prompt": "A surreal anime still', "Mira in the plaza, graphic framing."])
        progress = []
        result = self.run_workflow(backend, progress=progress)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("Correcting output format (one retry)", progress)
        self.assertEqual(backend.calls[1].user_message, backend.calls[0].user_message)
        self.assertEqual(result["prompt"], "Mira in the plaza, graphic framing.")

    def test_failed_repair_is_bounded(self):
        backend = ScriptedBackend(['{"prompt":', '{"prompt":'])
        with self.assertRaisesRegex(BackendGenerationError, "invalid format twice"):
            self.run_workflow(backend)
        self.assertEqual(len(backend.calls), 2)

    def test_cancel_before_retry_does_not_start_another_call_or_save_bad_output(self):
        backend = ScriptedBackend(['{"prompt":'])
        cancelled = []

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
            self.run_workflow(backend, checkpoint=checkpoint, progress=Progress())
        self.assertEqual(len(backend.calls), 1)

    def test_ideogram_schema_survives_refinement(self):
        raw = json.dumps(CAPTION)
        backend = ScriptedBackend([raw])
        result = self.run_workflow(backend, target="Ideogram4")
        self.assertEqual(json.loads(result["prompt"]), CAPTION)

    def test_qwen21_refinement_returns_only_prompt_text(self):
        payload = {"rewritten_prompt": "An anime illustration of Mira in a sunlit plaza.", "wh_ratio": "3:2"}
        raw = json.dumps(payload)
        backend = ScriptedBackend([raw])
        result = self.run_workflow(backend, target="Qwen2.1")
        self.assertEqual(result["prompt"], payload["rewritten_prompt"])
        self.assertIn('Return only the complete plain prompt text', backend.calls[0].system_message)
        self.assertTrue(backend.calls[0].unlimited_tokens)

    def test_qwen21_refine_is_uncapped_for_every_length(self):
        for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
            with self.subTest(length=length):
                request = GoatedPrompterRequest(idea="A bicycle", target_model="Qwen2.1", prompt_length=length)
                instruction = refine_instruction(request, "A bicycle", "Red paint", [])
                self.assertTrue(instruction.unlimited_tokens)
                self.assertIsNone(instruction.max_tokens)


if __name__ == "__main__":
    unittest.main()
