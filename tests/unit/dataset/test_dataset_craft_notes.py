"""Craft notes give IDEAS the library's standard without any of its content."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.craft_notes import filter_notes, leaked_words, library_craft_notes
from goated_prompter.features.dataset.ideas import ideas_instruction
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, library_path
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import valid_draft

SAVED = ["A woman in a dorm room hunches over a desk, highlighting a textbook while a cold noodle cup steams.",
         "A fluffy cat stands in deep forest snow, tail raised, snowflakes in layers around it.",
         "A dancer in a neon nightclub throws her head back under a red strobe, sequins catching the light.",
         "Two friends haggle with a fruit seller at a dusty roadside stall, one holding up three fingers."]
GOOD = ["Name one specific action in progress and the prop it involves.",
        "State where each person stands in the frame and where they look.",
        "Give the light a source and a direction, and say what it falls on.",
        "Add one unusual detail that makes the image memorable."]
LEAKY = ["Set the scene in a dorm room with a textbook on the desk.",
         "Use a neon nightclub with a red strobe.",
         "Add snowflakes and a raised tail for charm."]


class CraftNoteTests(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {LIBRARY_DIR_ENV: str(directory)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write(SAVED)

    def write(self, prompts):
        library_path("Krea 2").write_text("\n---\n".join(prompts), encoding="utf-8")

    def session(self, notes):
        session = Mock()
        session.generate.return_value = json.dumps(notes)
        return session

    def make(self, session):
        return library_craft_notes(session, "Krea 2", progress=lambda _message: None, checkpoint=lambda: None)

    def test_notes_that_name_anything_from_the_saved_prompts_are_dropped(self):
        for note in LEAKY:
            with self.subTest(note=note):
                self.assertTrue(leaked_words(note, SAVED))
        for note in GOOD:
            with self.subTest(note=note):
                self.assertEqual(leaked_words(note, SAVED), [])
        self.assertEqual(filter_notes(GOOD + LEAKY, SAVED), GOOD)
        self.assertEqual(filter_notes(GOOD[:2] + LEAKY, SAVED), [], "Too few clean notes are not worth sending.")

    def test_sample_lists_are_cut_so_a_good_rule_survives_without_the_saved_content(self):
        from goated_prompter.features.dataset.craft_notes import strip_examples
        self.assertEqual(strip_examples("Layer the setting into depth, using atmospheric effects like snowflakes, fog, "
                                        "or a neon nightclub glow to create natural depth."),
                         "Layer the setting into depth, using atmospheric effects to create natural depth.")
        self.assertEqual(strip_examples("Use precise micro-details on materials, such as a textbook, noodle cup or "
                                        "sequins, to ground the image."), "Use precise micro-details on materials, to ground the image.")
        self.assertEqual(strip_examples("Describe how light falls (e.g. a red strobe) on the face."),
                         "Describe how light falls on the face.")
        noisy = [note.rstrip(".") + ", such as a dorm desk or a red strobe." for note in GOOD]
        self.assertEqual(filter_notes(noisy, SAVED), GOOD)
        self.assertEqual(filter_notes(GOOD + ["Make the place concrete, setting it in a dorm room with a textbook."], SAVED),
                         GOOD, "A leak outside a sample list still drops the note.")

    def test_notes_are_made_once_per_library_version_and_never_carry_its_content(self):
        session = self.session(GOOD + LEAKY)
        self.assertEqual(self.make(session), GOOD)
        self.assertEqual(self.make(session), GOOD)
        session.generate.assert_called_once()
        sent = json.loads(session.generate.call_args[0][0].user_message)["saved_prompts"]
        self.assertEqual(sent, SAVED, "Only the notes call sees the saved prompts.")
        self.write(SAVED + ["A chef flambés a pan while a smoke alarm blinks above him."])
        self.make(session)
        self.assertEqual(session.generate.call_count, 2, "An edited library gets fresh notes.")

    def test_a_small_library_or_a_broken_reply_gives_no_notes(self):
        self.write(SAVED[:2])
        session = self.session(GOOD)
        self.assertEqual(self.make(session), [])
        session.generate.assert_not_called()
        self.write(SAVED)
        broken = Mock()
        broken.generate.return_value = "not json"
        self.assertEqual(self.make(broken), [])

    def test_ideas_get_the_notes_but_never_the_saved_prompts(self):
        data = valid_draft(amount=1, target="Krea 2", _confirmed_intent=dataset_understanding_fixture())
        instruction = ideas_instruction(data, dataset_assignments(data), craft_notes=GOOD)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["craft_notes"], GOOD)
        for prompt in SAVED:
            self.assertNotIn(prompt[:30], instruction.user_message + instruction.system_message)
        self.assertIn("They describe how to write, never\nwhat to show.", instruction.system_message)
        self.assertNotIn("craft_notes", json.loads(ideas_instruction(data, dataset_assignments(data)).user_message))


if __name__ == "__main__":
    unittest.main()
