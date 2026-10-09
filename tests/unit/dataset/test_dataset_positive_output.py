"""Active positive-output safeguards, without legacy scene evaluators."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.dataset import DatasetService, validate_positive_content
from goated_prompter.dataset_visible_content import (
    PositiveContentError, positive_prompt_error, sanitize_positive_prompt,
)
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.prompting.dataset import dataset_instruction
from tests.support.dataset import valid_draft, saved_scene


class DatasetPositiveOutputTests(unittest.TestCase):
    def test_standalone_exclusions_are_removed_without_losing_visible_action(self):
        raw = "ohwx_person punches a bag; no extra people; diffuse light reveals fabric tension."
        expected = "ohwx_person punches a bag; diffuse light reveals fabric tension."
        self.assertEqual(sanitize_positive_prompt(raw, "Generic"), expected)
        self.assertIsNone(positive_prompt_error(expected, "Generic"))
        self.assertEqual(sanitize_positive_prompt(expected, "Generic"), expected)

    def test_mixed_action_and_exclusion_is_not_deleted_and_requires_correction(self):
        raw = "ohwx_person punches a bag without extra people beside the hanging target."
        self.assertEqual(sanitize_positive_prompt(raw, "Generic"), raw)
        with self.assertRaises(PositiveContentError):
            validate_positive_content(raw, valid_draft())

    def test_literal_lettering_and_protected_trigger_are_not_sanitized(self):
        raw = 'best quality holds a sign reading "No extra people; no text" beside a bag.'
        self.assertEqual(sanitize_positive_prompt(raw, "Generic", ("best quality",)), raw)
        self.assertIsNone(positive_prompt_error(raw, "Generic", ("best quality",)))

    def test_meaningful_absence_and_decimal_values_remain_exact(self):
        raw = "ohwx_person rests beside an unoccupied chair, without hesitation; f/2.8 light separates an empty street."
        self.assertEqual(sanitize_positive_prompt(raw, "Generic"), raw)
        self.assertIsNone(positive_prompt_error(raw, "Generic"))

    def test_unclosed_literal_boundaries_are_not_guessed(self):
        raw = 'A sign reads "No extra people; a person rests.'
        self.assertEqual(sanitize_positive_prompt(raw, "Generic"), raw)

    def test_scene_status_metadata_is_rejected_but_rendered_metadata_is_preserved(self):
        self.assertIsNotNone(positive_prompt_error("ohwx_person stands. self_check: PASS", "Generic"))
        self.assertIsNone(positive_prompt_error('A board reads "self_check: PASS".', "Generic"))

    def test_ideogram_cleanup_preserves_keys_palettes_and_rendered_text(self):
        value = {"high_level_description": "A boxer punches a bag; no extra people.",
            "style_description": {"aesthetics": "Soft contrast.", "lighting": "Diffuse light.",
                "photo": "Eye level.", "medium": "Photography.", "color_palette": ["#112233"]},
            "compositional_deconstruction": {"background": "Training room; no watermark.",
                "elements": [{"type": "text", "text": "No extra people", "desc": "Red lettering; no logos."}]}}
        cleaned = json.loads(sanitize_positive_prompt(json.dumps(value), "Ideogram4"))
        self.assertEqual(cleaned["high_level_description"], "A boxer punches a bag.")
        self.assertEqual(cleaned["compositional_deconstruction"]["background"], "Training room.")
        self.assertEqual(cleaned["compositional_deconstruction"]["elements"][0],
            {"type": "text", "text": "No extra people", "desc": "Red lettering."})
        self.assertEqual(cleaned["style_description"], value["style_description"])
        self.assertEqual(list(cleaned), list(value))
        self.assertIsNone(positive_prompt_error(json.dumps(cleaned), "Ideogram4"))

    def test_empty_required_json_description_is_left_for_validation_not_erased(self):
        value = {"high_level_description": "no extra people", "style_description": {},
            "compositional_deconstruction": {"background": "Room.", "elements": []}}
        cleaned = sanitize_positive_prompt(json.dumps(value), "Ideogram4")
        self.assertEqual(json.loads(cleaned)["high_level_description"], "no extra people")
        self.assertIsNotNone(positive_prompt_error(cleaned, "Ideogram4"))

    def test_allowlisted_cleanup_costs_no_extra_model_call(self):
        data, scene = valid_draft(amount=1), saved_scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.return_value = "ohwx_person punches a bag; no extra people."
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene)
        self.assertEqual(result, "ohwx_person punches a bag.")
        session.generate.assert_called_once()

    def test_remaining_leakage_retries_final_output_without_changing_scene(self):
        data, scene = valid_draft(amount=1), saved_scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.side_effect = ["ohwx_person punches a bag without extra people beside it.",
            "ohwx_person punches a bag beside the empty wall."]
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene)
        self.assertEqual(result, "ohwx_person punches a bag beside the empty wall.")
        self.assertEqual(session.generate.call_count, 2)
        self.assertTrue(all(call.args[0].user_message == scene["scene"] for call in session.generate.call_args_list))
