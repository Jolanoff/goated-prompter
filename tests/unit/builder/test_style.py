"""The Style option adds one visual-style section; Auto keeps prompts unchanged except Anima."""

import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.service import validate_dataset_draft
from goated_prompter.options.styles import STYLE_NAMES
from goated_prompter.prompting.styles import STYLE_ADAPTERS, resolve_style
from tests.support.dataset import saved_scene, valid_draft


def message(**changes):
    return assemble_instruction(GoatedPrompterRequest(**{"idea": "two friends playing football", **changes})).system_message


class StyleTests(unittest.TestCase):
    def test_every_named_style_has_text_and_auto_follows_the_request(self):
        self.assertEqual(set(STYLE_NAMES) - {"Auto"}, set(STYLE_ADAPTERS))
        self.assertEqual(resolve_style("Auto", "Generic"), "Auto")
        self.assertEqual(resolve_style("Auto", "Anima"), "Anime")
        self.assertEqual(resolve_style("Realistic", "Anima"), "Realistic")

    def test_builder_adds_the_selected_style_once(self):
        self.assertNotIn("VISUAL STYLE", message())
        anime = message(target_model="Krea 2", style="Anime")
        self.assertEqual(anime.count("VISUAL STYLE — Anime"), 1)
        self.assertIn(STYLE_ADAPTERS["Anime"], anime)
        self.assertLess(anime.index("VISUAL STYLE"), anime.index("OUTPUT FORMAT"))
        self.assertIn("VISUAL STYLE — Anime", message(target_model="Anima"))
        self.assertIn("VISUAL STYLE — Product", message(style="Product"))

    def test_dataset_validates_style_and_passes_it_to_the_writer(self):
        self.assertEqual(validate_dataset_draft(valid_draft())["style"], "Auto")
        self.assertEqual(validate_dataset_draft(valid_draft(style="Anime"))["style"], "Anime")
        with self.assertRaises(ValueError):
            validate_dataset_draft(valid_draft(style="Watercolour anime"))
        data = valid_draft(target="Krea 2", style="Anime")
        writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=saved_scene())
        self.assertIn("VISUAL STYLE — Anime", writer.system_message)


if __name__ == "__main__":
    unittest.main()
