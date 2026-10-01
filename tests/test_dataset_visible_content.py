"""Dataset-positive output: internal exclusions stay internal, visible states survive."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError, BackendRunawayError
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.dataset_coverage import analyze_dataset_quality, effective_coverage_plan
from goated_prompter.dataset_visible_content import (
    VISIBLE_CONTENT_CONTRACT, positive_prompt_error, visible_content_error,
)
from goated_prompter.prompting.dataset import dataset_instruction, deep_review_instruction
from goated_prompter.prompting.scene_planner import scene_planner_instruction
from goated_prompter.prompting.target_models import TARGET_MODEL_NAMES
from goated_prompter.scene_planner import ScenePlanner, validate_scene_plan, reusable_scene_plan, scene_plan_signature


BAD = ("no masterpiece", "no other person in the frame", "no other people", "no extra people",
       "no extra limbs", "no bad anatomy", "no watermark", "no text", "no logos",
       "no distorted hands", "no additional objects", "no blur", "no background clutter",
       "avoid extra limbs", "avoid distortion", "do not show another person",
       "without any other people", "worst quality", "low quality", "best quality",
       "masterpiece, correct anatomy", "Negative prompt: distorted hands")


def draft(**changes):
    return {**default_dataset_draft(), "amount": 1, "trigger": "person_token",
            "subject": "A woman in a kitchen", "constraints": "only the woman", **changes}


def caption():
    return {"high_level_description": "A woman rests her hands on a kitchen table.",
            "style_description": {"aesthetics": "Quiet domestic photography", "lighting": "Soft daylight",
                                  "photo": "Medium frontal view", "medium": "Photograph"},
            "compositional_deconstruction": {"background": "A sparsely furnished kitchen",
                "elements": [{"type": "obj", "desc": "One woman, hands resting naturally on the table."}]}}


class VisibleContentTests(unittest.TestCase):
    def test_specific_exclusion_and_meta_phrases_are_detected(self):
        for phrase in BAD:
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(visible_content_error(phrase))
                self.assertIsNotNone(visible_content_error("A woman stands in a kitchen, " + phrase))

    def test_visible_absence_and_natural_words_are_not_universally_banned(self):
        valid = ("An empty abandoned street at dawn.", "A deserted classroom with a bare white wall.",
                 "An unoccupied chair beside her on an otherwise empty stage.",
                 "A woman stands alone in a quiet, sparsely furnished room.",
                 "Her hands rest naturally on the table, fingers relaxed.",
                 "A close-up portrait fills the frame against a simple background.",
                 "A woman wearing a coat without sleeves.", "She has no shoes on her feet.",
                 "Two runners avoid a puddle as they cross the road.",
                 "A painter displays her latest masterpiece in a gallery.")
        for text in valid:
            with self.subTest(text=text):
                self.assertIsNone(visible_content_error(text))

    def test_literal_visible_text_and_protected_tokens_survive(self):
        for text in ('A sign reads "NO TEXT".', "A shirt printed with 'low quality'.",
                     'A “no other people” sign hangs on a bare wall.'):
            with self.subTest(text=text):
                self.assertIsNone(visible_content_error(text))
        self.assertIsNotNone(visible_content_error('A woman, "no other people".'))
        self.assertIsNone(visible_content_error("A portrait of no text in a kitchen.", ("no text",)))

    def test_ideogram_checks_every_positive_description_but_not_literal_text(self):
        value = caption()
        self.assertIsNone(positive_prompt_error(json.dumps(value), "Ideogram4"))
        paths = (("high_level_description",), ("style_description", "lighting"),
                 ("compositional_deconstruction", "background"),
                 ("compositional_deconstruction", "elements", 0, "desc"))
        for path in paths:
            with self.subTest(path=path):
                changed = caption()
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] += ", no other people"
                self.assertIsNotNone(positive_prompt_error(json.dumps(changed), "Ideogram4"))
        value["compositional_deconstruction"]["elements"].append(
            {"type": "text", "text": "NO TEXT, worst quality", "desc": "Block lettering on a sign."})
        self.assertIsNone(positive_prompt_error(json.dumps(value), "Ideogram4"))

    def test_contract_applies_only_to_dataset_across_all_targets_and_review(self):
        data = draft()
        planner = scene_planner_instruction(data, effective_coverage_plan(data))
        self.assertIn(VISIBLE_CONTENT_CONTRACT, planner.system_message)
        for target in TARGET_MODEL_NAMES:
            with self.subTest(target=target):
                instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model=target),
                                                  {**data, "target": target}, 1)
                self.assertIn(VISIBLE_CONTENT_CONTRACT, instruction.system_message)
        builder = assemble_instruction(GoatedPrompterRequest(idea=data["subject"]), text_only=True)
        self.assertNotIn("VISIBLE CONTENT ONLY / POSITIVE VISUAL DESCRIPTION", builder.system_message)
        review = deep_review_instruction(data, [{"index": 1, "prompt": "A woman, no extra people."}])
        self.assertIn("POSITIVE CONTENT AUDIT", review.system_message)

    def test_planner_repairs_negative_prose_in_idea_or_scene(self):
        valid = [{"index": 1, "idea": "Cooking alone", "scene": "A woman cooks in a quiet kitchen, her hands resting naturally on the counter."}]
        for field in ("idea", "scene"):
            invalid = [{**valid[0], field: valid[0][field] + ", no other people"}]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_scene_plan(json.dumps(invalid), 1)
            session = Mock()
            session.generate.side_effect = [json.dumps(invalid), json.dumps(valid)]
            data = draft()
            rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                coverage=effective_coverage_plan(data), progress=lambda _: None)
            self.assertEqual(rows, valid)
            self.assertEqual(session.generate.call_count, 2)

    def test_single_subject_constraint_is_silent_in_successful_final_output(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
            plan_item={"idea": "Cooking at home", "scene": "A woman stands beside a kitchen table."})
        session = Mock()
        session.generate.return_value = "A woman person_token stands beside a kitchen table in soft daylight."
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 1)
        self.assertIn(data["constraints"], instruction.user_message)
        self.assertIsNone(visible_content_error(result))
        self.assertNotIn("other people", result)

    def test_writer_retries_leakage_preserving_exact_idea_scene_and_token_budget(self):
        for target in ("Generic", "Anima", "Qwen Image", "Ideogram4"):
            data = draft(target=target)
            instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model=target), data, 1,
                plan_item={"idea": "Cooking at home", "scene": "A woman stands beside a kitchen table."})
            for phrase in BAD:
                session = Mock()
                if target == "Ideogram4":
                    bad, good = caption(), caption()
                    bad["style_description"]["lighting"] += ", " + phrase
                    outputs = [json.dumps(bad), json.dumps(good)]
                else:
                    outputs = ["A woman person_token at a kitchen table, " + phrase,
                               "A woman person_token stands beside a kitchen table in soft daylight."]
                session.generate.side_effect = outputs
                with self.subTest(target=target, phrase=phrase):
                    result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
                    self.assertEqual(session.generate.call_count, 2)
                    first, retry = [call.args[0] for call in session.generate.call_args_list]
                    self.assertEqual(first.user_message, retry.user_message)
                    self.assertEqual(first.hard_max_tokens, retry.hard_max_tokens)
                    self.assertIn(VISIBLE_CONTENT_CONTRACT, retry.system_message)
                    self.assertIsNone(positive_prompt_error(result, target))

    def test_repeated_leakage_fails_boundedly_and_runaway_prefix_is_not_exempt(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        session = Mock()
        session.generate.return_value = "person_token, no other people, no watermark."
        with self.assertRaisesRegex(BackendGenerationError, "after 3 retries"):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 4)
        prefix = "person_token beside a kitchen counter in soft daylight " + "with a visible wooden table " * 6 + ", no watermark."
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop", recoverable_text=prefix),
                                       "person_token sits beside a wooden kitchen table."]
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 2)
        self.assertNotIn("watermark", result)

    def test_saved_bad_plans_and_manually_edited_results_are_not_silent(self):
        data = draft(scene_plan=[{"index": 1, "input": "", "idea": "Cooking at home",
                                 "scene": "A woman cooks, no other people."}])
        data["scene_plan_signature"] = scene_plan_signature(data, effective_coverage_plan(data))
        self.assertIsNone(reusable_scene_plan(data, effective_coverage_plan(data)))
        results = [{"index": 1, "input": "", "idea": "Cooking, no text", "scene": "A woman cooks, no other people.",
                    "prompt": "A woman person_token in a kitchen, no watermark."}]
        report = analyze_dataset_quality(data, results)
        codes = {issue["code"] for issue in report["prompts"][0]["issues"]}
        self.assertTrue({"positive_content_leakage", "idea_content_leakage", "scene_content_leakage"} <= codes)
        valid = [{"index": 1, "input": "", "idea": "An empty abandoned street",
                  "scene": "An empty abandoned street at dawn.", "prompt": "An empty abandoned street at dawn, person_token."}]
        codes = {issue["code"] for issue in analyze_dataset_quality(data, valid)["prompts"][0]["issues"]}
        self.assertNotIn("positive_content_leakage", codes)


if __name__ == "__main__":
    unittest.main()
