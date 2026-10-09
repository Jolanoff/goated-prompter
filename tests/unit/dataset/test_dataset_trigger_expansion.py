"""Expansion keeps subjects; protected mode keeps the supplied wording."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError, BackendRunawayError
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService, validate_trigger_contract
from goated_prompter.dataset_triggers import trigger_presence_error, trigger_contract_error, restore_numeric_trigger_spelling
from goated_prompter.prompting.dataset import dataset_instruction
from tests.support.dataset import valid_draft


class TriggerExpansionTests(unittest.TestCase):
    def test_number_word_trigger_spelling_keeps_the_scene_and_avoids_a_writer_retry(self):
        data = valid_draft(amount=1, trigger="duck, 2 men", trigger_type="Multiple characters")
        scene = "At a mountain trailhead, one red duck stands between two men, one checking a map."
        row = {"idea": "Travel together", "scene": scene, "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = scene
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result, scene.replace("two men", "2 men"))
        self.assertEqual(row["scene"], scene)
        self.assertEqual(instruction.user_message, scene)
        session.generate.assert_called_once()
        self.assertIsNone(trigger_presence_error(result, data["trigger"], data["target"]))

    def test_numeric_spelling_preserves_qualifiers_counts_and_literal_boundaries(self):
        prompt = 'At least two men stand beside one red duck; not both wear hats. A sign reads "two men".'
        expected = 'At least 2 men stand beside one red duck; not both wear hats. A sign reads "two men".'
        self.assertEqual(restore_numeric_trigger_spelling(prompt, "duck, 2 men", "Generic"), expected)
        for text in ('A sign reads "two men".', "A sign reads 'two men'.", 'A sign reads “two men”.',
                'A sign reads "two men; two men stand nearby.', "Twenty-two men stand together.",
                "A sign reads 'two men; two men stand nearby.", "twenty two men stand together",
                "one hundred and two men stand together",
                "three men travel together", "two men_token travel together", "two men-extra travel together",
                "two men2 travel together"):
            with self.subTest(text=text):
                self.assertEqual(restore_numeric_trigger_spelling(text, "2 men", "Generic"), text)

    def test_numeric_spelling_accepts_possessive_apostrophes_without_editing_lettering(self):
        for prompt in ("Two men share bread; the subjects' hands are near the plate.",
                "Two men share bread; the men's hands are near the plate.",
                "Two men share bread; the men’s hands are near the plate.",
                "Two men hold a sign reading ‘two men’; the subjects’ hands support it."):
            with self.subTest(prompt=prompt):
                self.assertEqual(restore_numeric_trigger_spelling(prompt, "2 men", "Generic"),
                    prompt.replace("Two men", "2 men"))

    def test_numeric_spelling_does_not_rewrite_identifiers_other_triggers_or_existing_exact_terms(self):
        for trigger, text in (("2_men", "two_men stand together"), ("2men", "twomen stand together"),
                ("2 men1", "two men1 stand together"), ("22 men", "twenty-two men stand together"),
                ("2 men, two men", "two men stand together"), ("2 men", "2 men meet two men on a trail.")):
            with self.subTest(trigger=trigger):
                self.assertEqual(restore_numeric_trigger_spelling(text, trigger, "Generic"), text)

    def test_numeric_spelling_does_not_change_compound_or_fractional_numbers(self):
        for text in ("Twenty–two men stand together.", "Twenty—two men stand together.",
                "one point two men", "one hundred & two men", "0.two men", "-two men"):
            with self.subTest(text=text):
                self.assertEqual(restore_numeric_trigger_spelling(text, "2 men", "Generic"), text)

    def test_expanded_numeric_trigger_keeps_generated_spelling(self):
        data = valid_draft(amount=1, trigger="duck, 2 men", expand_trigger=True)
        scene = "One red duck and two men travel together."
        row = {"scene": scene, "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = scene
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result, scene)
        session.generate.assert_called_once()

    def test_numeric_spelling_changes_only_the_ideogram_description_not_text_elements(self):
        caption = {"high_level_description": 'Two men hold a sign reading "two men" beside a red duck.',
            "style_description": {"aesthetics": "two men"},
            "compositional_deconstruction": {"background": "two men", "elements": [
                {"type": "text", "text": "two men", "desc": "two men"}]}}
        restored = json.loads(restore_numeric_trigger_spelling(json.dumps(caption), "duck, 2 men", "Ideogram4"))
        self.assertEqual(restored["high_level_description"], '2 men hold a sign reading "two men" beside a red duck.')
        self.assertEqual(restored["style_description"], caption["style_description"])
        self.assertEqual(restored["compositional_deconstruction"], caption["compositional_deconstruction"])

    def test_numeric_spelling_restores_only_exact_noun_phrases_for_each_supported_count(self):
        numbers = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")
        for count, word in enumerate(numbers, 1):
            with self.subTest(count=count):
                prompt = f"At most {word} red cups rest on a table."
                expected = f"At most {count} red cups rest on a table."
                self.assertEqual(restore_numeric_trigger_spelling(prompt, f"{count} red cups", "Generic"), expected)
                self.assertEqual(restore_numeric_trigger_spelling(prompt, f"{count} blue cups", "Generic"), prompt)
        prompt = "At least two men and three women travel together; none wear hats."
        self.assertEqual(restore_numeric_trigger_spelling(prompt, "2 men, 3 women", "Generic"),
            "At least 2 men and 3 women travel together; none wear hats.")
        self.assertEqual(restore_numeric_trigger_spelling("two human males travel", "2 men", "Generic"),
            "two human males travel")

    def test_a_missing_or_different_count_still_requires_writer_correction(self):
        data = valid_draft(amount=1, trigger="duck, 2 men")
        row = {"scene": "One red duck and two men travel.", "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.side_effect = ["One red duck and three men travel.", "One red duck and two men travel."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(output, "One red duck and 2 men travel.")
        self.assertEqual(session.generate.call_count, 2)

    def data(self, **changes):
        return valid_draft(amount=1, trigger="a banana, an apple", trigger_connected=False,
                           expand_trigger=True, **changes)

    def test_report_accepts_user_fruit_subject_examples_with_expansion(self):
        examples = (
            "A banana character in a suit punches an apple character in a dress on a dojo floor.",
            "A banana character dominates the frame while grappling an apple character on a padded mat.",
            "An anthropomorphic apple character drives a knife into an anthropomorphic banana character in an alley.",
            "A muscular anthropomorphic banana in a black suit hurls a small apple in a pink dress across a dojo.",
            "The banana character slaps the apple character, both fully visible on a wooden stage.",
            "An apple character headbutts the banana character beside a kitchen counter in bright daylight.",
        )
        data = self.data()
        for prompt in examples:
            with self.subTest(prompt=prompt):
                self.assertIsNone(trigger_presence_error(prompt, data["trigger"], "Generic", expand=True))

    def test_expansion_does_not_allow_missing_subjects_or_partial_words(self):
        for prompt, missing in (("A banana character poses in a suit.", "an apple"),
                                ("An apple character dances in a dress.", "a banana"),
                                ("A pineapple is beside a banana-shaped toy.", "an apple"),
                                ("A banal performer eats applesauce.", "a banana")):
            with self.subTest(prompt=prompt):
                error = trigger_presence_error(prompt, "a banana, an apple", "Generic", expand=True)
                self.assertIn(missing, error)
                self.assertNotIn("exact required", error)
        self.assertIsNotNone(trigger_presence_error("ohwx_person_extra stands in a studio.", "ohwx_person", "Generic", expand=True))
        self.assertIsNotNone(trigger_presence_error("OHWX_PERSON stands in a studio.", "ohwx_person", "Generic", expand=True))
        self.assertIsNone(trigger_presence_error("A muscular ohwx_person stands in a studio.", "a ohwx_person", "Generic", expand=True))
        self.assertIsNotNone(trigger_presence_error("A muscular OHWX_PERSON stands in a studio.", "a ohwx_person", "Generic", expand=True))

    def test_multiword_subject_attributes_stay_in_order_in_one_clause(self):
        self.assertIsNone(trigger_presence_error("The red anthropomorphic apple dances.", "a red apple", "Generic", expand=True))
        for prompt in ("The green apple dances.", "An apple beside a red car.", "A red car. An apple rolls away.", "A red car and an apple roll away."):
            self.assertIsNotNone(trigger_presence_error(prompt, "a red apple", "Generic", expand=True))
        self.assertIsNone(trigger_presence_error("1 tall man stands in a dojo.", "1 man", "Generic", expand=True))
        self.assertIsNotNone(trigger_presence_error("2 tall men stand in a dojo.", "1 man", "Generic", expand=True))

    def test_repeated_long_phrases_do_not_backtrack_unboundedly(self):
        trigger = "apple " * 25 + "banana"
        self.assertIsNotNone(trigger_presence_error("banana. " + "apple " * 100, trigger, "Generic", expand=True))
        self.assertIsNone(trigger_presence_error("APPLE " * 30 + "banana", trigger, "Generic", expand=True))

    def test_disabled_expansion_requires_exact_case_and_uninterrupted_term(self):
        for prompt in ("A banana faces an apple.", "a muscular banana faces an apple.", "a banana faces an anthropomorphic apple."):
            self.assertIn("exact required", trigger_presence_error(prompt, "a banana, an apple", "Generic"))
        self.assertIsNone(trigger_presence_error("On the mat, a banana faces an apple.", "a banana, an apple", "Generic"))

    def test_ideogram_checks_only_high_level_description(self):
        prompt = json.dumps({"high_level_description": "A muscular banana grapples the apple character on a padded mat.",
                             "compositional_deconstruction": {"elements": []}})
        self.assertIsNone(trigger_presence_error(prompt, "a banana, an apple", "Ideogram4", expand=True))
        self.assertIsNotNone(trigger_presence_error(prompt, "a banana, an apple", "Ideogram4"))
        elsewhere = json.dumps({"high_level_description": "A banana poses on a mat.",
                                "elements": [{"desc": "An apple in a dress."}]})
        self.assertIn("an apple", trigger_presence_error(elsewhere, "a banana, an apple", "Ideogram4", expand=True))

    def test_preference_checks_use_expanded_subjects_not_exact_wording(self):
        self.assertIsNone(trigger_contract_error("The banana character grapples the apple character on a mat.",
            "a banana, an apple", "Generic", connected=False, expand=True))
        self.assertIsNone(trigger_contract_error("The banana poses.", "a banana", "Generic", at_start=True, expand=True))
        self.assertIsNotNone(trigger_contract_error("In a dojo, the banana poses.", "a banana", "Generic", at_start=True, expand=True))
        self.assertIsNone(trigger_contract_error("A muscular banana, the anthropomorphic apple, face one another.",
            "a banana, an apple", "Generic", connected=True, expand=True))

    def test_writer_retries_only_final_wording_when_expansion_is_disabled(self):
        data = {**self.data(), "expand_trigger": False}
        row = {"idea": "Banana punches apple", "scene": "A banana punches an apple on a wooden mat.", "self_check": "PASS"}
        original = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.side_effect = ["A muscular banana punches the apple character on a wooden mat.",
                                       "On a wooden mat, a banana punches an apple."]
        output = DatasetService({}, lambda: None)._generate(session, original, data, 1, lambda _: None, row)
        self.assertEqual(output, "On a wooden mat, a banana punches an apple.")
        self.assertEqual(session.generate.call_count, 2)
        retry = session.generate.call_args.args[0]
        self.assertTrue(retry.user_message.startswith(original.user_message))
        self.assertEqual(retry.user_message, original.user_message)
        self.assertEqual(retry.hard_max_tokens, original.hard_max_tokens)
        self.assertIn("FINAL OUTPUT CORRECTION", retry.system_message)
        self.assertIn(":output_retry_1", retry.diagnostic_stage)

    def test_strict_retries_are_bounded_and_runaway_prefix_is_not_exempt(self):
        data = {**self.data(), "expand_trigger": False}
        row = {"scene": "A banana punches an apple on a mat.", "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = "The banana punches the apple on a mat."
        with self.assertRaisesRegex(BackendGenerationError, "after 3 retries"):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(session.generate.call_count, 4)
        prefix = "The banana punches the apple on a wooden mat in a dojo. " + "Their clothes ripple with the force of the impact. " * 3
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop", recoverable_text=prefix), "On a mat, a banana punches an apple."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertIn("a banana", output)
        self.assertEqual(session.generate.call_count, 2)

    def test_expanded_output_does_not_retry(self):
        data = self.data()
        prompt = "A muscular banana punches the apple character on a wooden dojo mat."
        row = {"scene": "A banana punches an apple on a mat.", "self_check": "PASS"}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = prompt
        messages = []
        self.assertEqual(DatasetService({}, lambda: None)._generate(session, instruction, data, 1, messages.append, row), prompt)
        self.assertEqual(session.generate.call_count, 1)
        self.assertFalse(any("Trigger warning" in message for message in messages))
        self.assertNotIn("exact uninterrupted text", instruction.system_message)
        self.assertIn("Required subjects/attributes", instruction.system_message)
        # Unknown semantic paraphrases remain a non-destructive review warning.
        warnings = []
        validate_trigger_contract("Two fruits grapple on a padded mat.", data, warnings.append)
        self.assertTrue(warnings)
