"""The Style option adds one visual-style section; Auto keeps prompts unchanged except Anima."""

import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.options.styles import STYLE_NAMES
from goated_prompter.prompting.styles import STYLE_ADAPTERS, resolve_style


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

    def test_dataset_draft_validates_style(self):
        self.assertEqual(validate_dataset_draft(default_dataset_draft())["style"], "Auto")
        self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "style": "Anime"})["style"], "Anime")
        with self.assertRaises(ValueError):
            validate_dataset_draft({**default_dataset_draft(), "style": "Watercolour anime"})


if __name__ == "__main__":
    unittest.main()
