"""Dataset-positive output: internal exclusions stay internal, visible states survive."""

import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError, BackendRunawayError
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_quality import analyze_dataset_quality
from goated_prompter.dataset_visible_content import (
    VISIBLE_CONTENT_CONTRACT, positive_prompt_error, visible_content_error, sanitize_positive_prompt,
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
    return {"high_level_description": "A woman person_token rests her hands on a kitchen table.",
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
        planner = scene_planner_instruction(data, dataset_assignments(data))
        self.assertIn(VISIBLE_CONTENT_CONTRACT, planner.system_message)
        for target in TARGET_MODEL_NAMES:
            with self.subTest(target=target):
                instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model=target),
                                                  {**data, "target": target}, 1)
                self.assertIn(VISIBLE_CONTENT_CONTRACT, instruction.system_message)
        builder = assemble_instruction(GoatedPrompterRequest(idea=data["subject"]), text_only=True)
        self.assertNotIn("VISIBLE CONTENT ONLY", builder.system_message)
        for phrase in BAD:
            self.assertNotIn(phrase.casefold(), VISIBLE_CONTENT_CONTRACT.casefold())
        review = deep_review_instruction(data, [{"index": 1, "prompt": "A woman, no extra people."}])
        self.assertIn("POSITIVE CONTENT AUDIT", review.system_message)

    def test_planner_repairs_negative_prose_in_idea_or_scene(self):
        from tests.test_dataset_geometry import character_geometry
        valid = [{"index": 1, "idea": "Cooking alone", "scene": "A woman cooks in a quiet kitchen, her hands resting naturally on the counter.",
                  "geometry": character_geometry(action_focus="cooking")}]
        for field in ("idea", "scene"):
            invalid = [{**valid[0], field: valid[0][field] + ", no other people"}]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_scene_plan(json.dumps(invalid), 1)
            session = Mock()
            session.generate.side_effect = [json.dumps(invalid), json.dumps(valid)]
            data = draft()
            rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                assignments=dataset_assignments(data), progress=lambda _: None)
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

    def test_writer_accepts_standalone_leakage_cleanup_in_one_generation(self):
        for target in ("Generic", "Anima", "Qwen Image", "Ideogram4"):
            data = draft(target=target)
            instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model=target), data, 1,
                plan_item={"idea": "Cooking at home", "scene": "A woman stands beside a kitchen table."})
            for phrase in BAD[:-1]:  # A negative-prompt section needs content repair.
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
                    self.assertEqual(session.generate.call_count, 1)
                    if target == "Ideogram4":
                        self.assertEqual(json.loads(result), good)
                    else:
                        suffix = (", best quality" if phrase == "best quality" else ", masterpiece"
                                  if phrase == "masterpiece, correct anatomy" else "") if target == "Anima" else ""
                        self.assertEqual(result, "A woman person_token at a kitchen table" + suffix)
                    self.assertIsNone(positive_prompt_error(result, target))

    def test_repeated_leakage_fails_boundedly_and_runaway_prefix_is_not_exempt(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        session = Mock()
        session.generate.return_value = "A woman person_token smiles with no other people while juggling oranges."
        with self.assertRaisesRegex(BackendGenerationError, "after 3 retries"):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 4)
        prefix = "person_token beside a kitchen counter in soft daylight " + "with a visible wooden table " * 6 + ", no watermark."
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop", recoverable_text=prefix),
                                       "person_token sits beside a wooden kitchen table."]
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 1)
        self.assertNotIn("watermark", result)

    def test_sanitizer_removes_complete_clauses_and_repairs_delimiters(self):
        cases = (
            ("a woman juggling oranges, no other people in frame, soft daylight",
             "a woman juggling oranges, soft daylight"),
            ("a blond woman juggling oranges, soft daylight, no other people or distracting elements in frame, photographic realism",
             "a blond woman juggling oranges, soft daylight, photographic realism"),
            ("No watermark. A woman juggles oranges. No other people. Soft daylight.",
             "A woman juggles oranges. Soft daylight."),
            ("A woman juggles oranges, no watermark, no bad anatomy.", "A woman juggles oranges."),
            ("best quality, a woman juggling oranges, soft daylight", "a woman juggling oranges, soft daylight"),
            ("a woman juggling oranges; avoid extra limbs; soft daylight", "a woman juggling oranges; soft daylight"),
            ("a woman juggling oranges\nno watermark\nsoft daylight", "a woman juggling oranges\nsoft daylight"),
            ("a woman juggling oranges, no watermark", "a woman juggling oranges"),
        )
        for original, expected in cases:
            with self.subTest(original=original):
                result = sanitize_positive_prompt(original, "Generic")
                self.assertEqual(result, expected)
                self.assertEqual(sanitize_positive_prompt(result, "Generic"), expected)
                self.assertIsNone(positive_prompt_error(result, "Generic"))

    def test_sanitizer_preserves_visible_absence_literals_and_trigger_anchors(self):
        cases = ("an empty street", "a bare wall", "an unoccupied chair", "a deserted classroom",
                 "she has no shoes", 'a sign reading "NO ENTRY"', 'a sign reading "NO TEXT, worst quality"',
                 "a shirt printed with 'low quality'", "a “no other people” sign hangs on a wall",
                 "A woman in a sparsely furnished room, lens f/1.8, soft daylight.")
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(sanitize_positive_prompt(text, "Generic"), text)
                self.assertIsNone(positive_prompt_error(text, "Generic"))
        text = 'a sign reading "NO TEXT, worst quality", no watermark, bare wall'
        self.assertEqual(sanitize_positive_prompt(text, "Generic"),
                         'a sign reading "NO TEXT, worst quality", bare wall')
        for text, terms in (("no text, soft daylight", ("no text",)),
                            ("no watermark on person_token, a woman juggling", ("person_token",)),
                            ("no other people, best quality, soft daylight", ("no other people, best quality",))):
            with self.subTest(text=text):
                self.assertEqual(sanitize_positive_prompt(text, "Generic", terms), text)

    def test_mixed_or_uncertain_prose_is_left_for_strict_content_validation(self):
        cases = ("A woman juggling oranges with no other people in frame.",
                 "A woman smiles, no other people while juggling oranges, soft daylight.",
                 "A woman smiles, best quality sunlight brightens her face.",
                 'A woman, "no other people", soft daylight.',
                 'A sign reading "hello, no watermark, best quality',
                 "A woman, no text on the bare wall beside her.")
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(sanitize_positive_prompt(text, "Generic"), text)
                self.assertIsNotNone(positive_prompt_error(text, "Generic"))

    def test_ideogram_sanitizes_descriptions_but_preserves_rendered_text_and_structure(self):
        original = caption()
        original["compositional_deconstruction"]["elements"].append(
            {"type": "text", "text": "NO TEXT, worst quality", "desc": 'A sign reading "NO ENTRY".'})
        expected = json.loads(json.dumps(original))
        original["high_level_description"] += ", no other people"
        for key in original["style_description"]:
            original["style_description"][key] += ", best quality"
        original["compositional_deconstruction"]["background"] += ", no additional objects"
        for element in original["compositional_deconstruction"]["elements"]:
            element["desc"] += ", no watermark"
        cleaned = sanitize_positive_prompt(json.dumps(original), "Ideogram4")
        self.assertEqual(json.loads(cleaned), expected)
        self.assertIsNone(positive_prompt_error(cleaned, "Ideogram4"))

    def test_cleanup_cannot_accept_an_empty_description(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        session = Mock()
        session.generate.side_effect = ["no watermark, best quality", "person_token juggling oranges."]
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(result, "person_token juggling oranges.")
        self.assertIn("TRIGGER WORDING CORRECTION", session.generate.call_args.args[0].system_message)
        original = caption()
        original["style_description"]["lighting"] = "no watermark"
        cleaned = sanitize_positive_prompt(json.dumps(original), "Ideogram4")
        # Do not destroy the schema or invent a lighting description.
        self.assertEqual(json.loads(cleaned)["style_description"]["lighting"], "no watermark")
        self.assertIsNotNone(positive_prompt_error(cleaned, "Ideogram4"))

    def test_content_retry_preserves_plan_and_budget_without_echoing_forbidden_phrase(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
            plan_item={"idea": "Juggling and failing", "scene": "A woman tracks a falling orange with her gaze."})
        session = Mock()
        session.generate.side_effect = ["person_token juggles with no other people while tracking a falling orange.",
                                       "person_token juggles, gaze tracking a falling orange."]
        DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(session.generate.call_count, 2)
        retry = session.generate.call_args.args[0]
        self.assertTrue(retry.user_message.startswith(instruction.user_message))
        self.assertIn("LOCAL REPAIR CONTRACT", retry.user_message)
        self.assertEqual(retry.hard_max_tokens, instruction.hard_max_tokens)
        correction = retry.system_message[len(instruction.system_message):]
        self.assertIn("OUTPUT CONTENT CORRECTION", correction)
        self.assertNotIn("FORMAT CORRECTION", correction)
        self.assertNotIn("no other people", correction)
        self.assertIn(":content_retry_1", retry.diagnostic_stage)

    def test_format_errors_use_format_repair_not_content_repair(self):
        data = draft(target="Ideogram4")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model="Ideogram4"), data, 1)
        for invalid in ("{broken JSON", '{"wrong_schema": "A woman"}', "```json\n{broken JSON\n```"):
            with self.subTest(invalid=invalid):
                session = Mock()
                session.generate.side_effect = [invalid, json.dumps(caption())]
                DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
                retry = session.generate.call_args.args[0]
                correction = retry.system_message[len(instruction.system_message):]
                self.assertIn("FORMAT CORRECTION", correction)
                self.assertNotIn("OUTPUT CONTENT CORRECTION", correction)
                self.assertIn(":format_retry_1", retry.diagnostic_stage)

    def test_long_prompt_retains_every_valid_detail_in_one_call(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        prose = "A woman person_token juggles oranges in soft daylight. " + "Her gaze follows the falling fruit. " * 30
        session = Mock()
        session.generate.return_value = prose.rstrip() + " No other people or distracting elements in frame."
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(result, prose.rstrip())
        self.assertEqual(session.generate.call_count, 1)

    def test_generation_validation_order_includes_general_and_positive_cleanup(self):
        from goated_prompter import dataset as module
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        calls = []

        def track(name, function):
            def wrapped(*args, **kwargs):
                calls.append(name)
                return function(*args, **kwargs)
            return wrapped

        session = Mock()
        session.generate.return_value = "person_token juggling oranges, no watermark, soft daylight."
        with patch.object(module, "normalize_workflow_output", side_effect=track("normalize", module.normalize_workflow_output)), \
             patch.object(module, "sanitize_prompt_text", side_effect=track("general", module.sanitize_prompt_text)), \
             patch.object(module, "trigger_presence_error", side_effect=track("trigger", module.trigger_presence_error)), \
             patch.object(module, "sanitize_positive_prompt", side_effect=track("positive_cleanup", module.sanitize_positive_prompt)), \
             patch.object(module, "positive_prompt_error", side_effect=track("positive_validation", module.positive_prompt_error)):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(calls, ["normalize", "general", "trigger", "positive_cleanup", "positive_validation"])

    def test_geometry_metadata_leakage_requires_content_retry_but_literals_survive(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
            plan_item={"idea": "Juggling", "scene": "A woman juggles oranges.", "geometry": {"camera_view": "front"}})
        session = Mock()
        session.generate.side_effect = ["person_token juggles oranges.\nPLANNED GEOMETRY\ncamera_view: front",
                                        "person_token juggles oranges, viewed from the front."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertEqual(output, "person_token juggles oranges, viewed from the front.")
        self.assertEqual(session.generate.call_count, 2)
        self.assertIn("OUTPUT CONTENT CORRECTION", session.generate.call_args.args[0].system_message)
        self.assertIsNone(visible_content_error('A sign reads "camera_view: front".'))
        self.assertIsNone(visible_content_error("A label showing camera_view: front.", ("camera_view: front",)))

    def test_unfixable_recovered_prefix_uses_content_and_loop_repair(self):
        data = draft()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        prefix = "person_token with no other people while juggling oranges beside a kitchen table. " + "Soft daylight falls across the wooden table. " * 5
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop", recoverable_text=prefix),
                                       "person_token juggling oranges beside a table."]
        DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        retry = session.generate.call_args.args[0]
        correction = retry.system_message[len(instruction.system_message):]
        self.assertIn("OUTPUT CONTENT CORRECTION", correction)
        self.assertIn("LOOP CORRECTION", retry.system_message)
        self.assertNotIn("FORMAT CORRECTION", correction)
        self.assertNotIn("no other people", correction)
        self.assertLess(retry.hard_max_tokens, instruction.hard_max_tokens)

    def test_saved_bad_plans_and_manually_edited_results_are_not_silent(self):
        data = draft(scene_plan=[{"index": 1, "input": "", "idea": "Cooking at home",
                                 "scene": "A woman cooks, no other people."}])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        self.assertIsNone(reusable_scene_plan(data, dataset_assignments(data)))
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
