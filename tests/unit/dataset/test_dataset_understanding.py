"""Dataset Understanding (brief version 11): who, how many, what happens, what stays and what varies. Scripted model
answers only; nothing here is live-model evidence."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.prompt_library import copied_reference

# Two answers a model gave for "magical world" (an earlier debug trace): a punctuation-only fixed and blank randomized,
# then an empty fixed, each with a stray "intent" key from the retired interpretation. Both must be usable as they are.
MAGICAL_FIRST = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": ",[],", '
                 '"randomized": " ", "must": [], "avoid": [], "intent": {"elements": [], "relations": []}}')
MAGICAL_SECOND = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": "", '
                  '"randomized": "setting, lighting, camera, mood, style", "must": [], "avoid": []}')
TWO_MEN = json.dumps({"path": "character", "summary": "Two men having sex", "fixed": "Two adult men",
                      "randomized": "Position, place, lighting", "must": [], "avoid": [],
                      "characters": [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}]})


class Understanding(unittest.TestCase):
    def understand(self, answers, **data):
        backend = MockBackend()
        replies = iter(answers)
        calls = []

        def generate(instruction):
            calls.append(instruction)
            return next(replies)
        values = {**default_dataset_draft(), "subject": "magical world", "amount": 3, "seed": 5, "seed_mode": "fixed", **data}
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(understanding, "create_backend", return_value=backend), \
                patch.object(understanding, "DebugTrace", return_value=Mock()), \
                patch.object(understanding, "resolve_director_config", return_value=({}, None)):
            result = understanding.understand({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), values,
                                              progress=lambda _: None)
        return result, calls

    def test_two_men_having_sex_keeps_two_men_and_the_activity(self):
        result, calls = self.understand([TWO_MEN], subject="2 males having sex", nsfw=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["path"], result["people"]), ("nsfw_character", 2))
        self.assertEqual([(person["label"], person["gender"], person["pronoun"]) for person in result["characters"]],
                         [("man 1", "male", "he"), ("man 2", "male", "he")])
        self.assertIn("sex", result["summary"])
        self.assertEqual(result["input"]["request"], "2 males having sex", "the request itself is kept word for word")

    def test_understanding_never_chooses_vocabulary(self):
        result, calls = self.understand([TWO_MEN], subject="2 males having sex", nsfw=True)
        self.assertEqual(result["version"], 11)
        self.assertNotIn("intent", result)
        self.assertEqual(set(calls[0].json_schema["properties"]), set(understanding.MODEL_FIELDS))
        for word in ("pack", "vocabulary"):
            self.assertNotIn(word, calls[0].user_message.casefold())

    def test_broad_request_with_malformed_optional_text_is_understood_in_one_call(self):
        result, calls = self.understand([MAGICAL_FIRST])
        self.assertEqual(len(calls), 1, "a recoverable answer is not regenerated")
        self.assertEqual((result["path"], result["fixed"], result["randomized"]), ("non_character", "", ""))
        self.assertEqual(result["summary"], "A magical world.")
        self.assertNotIn("intent", result, "a stray intent is not kept")
        self.assertEqual(understanding.validate_brief(result), result)

    def test_the_second_magical_world_answer_is_also_valid(self):
        result, calls = self.understand([MAGICAL_SECOND])
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["fixed"], result["randomized"]), ("", "setting, lighting, camera, mood, style"))

    def test_missing_summary_falls_back_to_the_request_never_to_an_invention(self):
        answer = json.loads(MAGICAL_SECOND)
        answer["summary"] = "  "
        result, _ = self.understand([json.dumps(answer)])
        self.assertEqual(result["summary"], "magical world")

    def test_nsfw_switch_keeps_a_place_request_without_people(self):
        result, calls = self.understand([MAGICAL_FIRST], nsfw=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["path"], result["people"], result["input"]["nsfw"]), ("non_character", 0, True))
        self.assertIn("without people", calls[0].system_message)

    def test_nsfw_sexual_request_without_people_is_still_sent_back(self):
        errors = understanding.model_errors(understanding.recover(json.loads(MAGICAL_FIRST)), True,
                                            {"subject": "two people having sex", "source_mode": "random"})
        self.assertTrue(any("path must be" in error for error in errors), errors)

    def test_unrecoverable_answers_still_fail_after_one_retry(self):
        broken = json.dumps({**json.loads(MAGICAL_FIRST), "path": "landscape"})
        with self.assertRaisesRegex(ValueError, "invalid answer twice"):
            self.understand([broken, broken])

    def test_a_saved_version_10_brief_with_intent_stays_readable(self):
        result, _ = self.understand([MAGICAL_SECOND])
        saved = {**result, "version": 10, "intent": {"elements": [], "relations": []}}
        self.assertEqual(understanding.validate_brief(saved), saved)


class LibraryReferences(unittest.TestCase):
    """The Prompt Library may guide wording, never add a template's content to a Dataset prompt."""
    TEMPLATE = "Soft window light falls across the quiet room while dust drifts slowly through the warm afternoon air."

    def test_copy_check_names_the_copied_passage(self):
        copied = copied_reference("A man reads. Soft window light falls across the quiet room while dust drifts slowly.",
                                  [self.TEMPLATE])
        self.assertEqual(copied, "soft window light falls across the quiet room while dust")

    def test_wording_the_request_itself_contains_is_not_a_copy(self):
        idea = "the quiet room while dust drifts slowly through the warm afternoon air"
        prompt = "A man reads in " + idea + "."
        self.assertTrue(copied_reference(prompt, [self.TEMPLATE]))
        self.assertEqual(copied_reference(prompt, [self.TEMPLATE], allowed=[idea]), "")

    def test_retry_after_copying_is_written_without_the_templates(self):
        from goated_prompter.features.builder import service as builder
        backend = MockBackend()
        instructions = []

        def generate(instruction):
            instructions.append(instruction)
            return self.TEMPLATE if len(instructions) == 1 else "A reader sits by a bright window with a book."
        request = GoatedPrompterRequest(idea="a reader by a window", planning_mode="Direct", target_model="Krea 2")
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(builder, "create_backend", return_value=backend), \
                patch.object(builder, "pick_references", return_value=(self.TEMPLATE,)):
            result = builder.GoatedPrompterService({"backend": "mock"}).generate_text_only(request)
        self.assertEqual(result.prompt, "A reader sits by a bright window with a book.")
        self.assertEqual(len(instructions), 2)
        self.assertIn("TEMPLATES FROM THE USER'S PROMPT LIBRARY", instructions[0].system_message)
        self.assertNotIn(self.TEMPLATE, instructions[1].system_message)
        self.assertIn("copied wording", instructions[1].system_message)


if __name__ == "__main__":
    unittest.main()
