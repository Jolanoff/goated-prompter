"""The Style option adds one visual-style section; Auto keeps prompts unchanged except Anima."""

import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.options.styles import CAPTURE_NAMES, STYLE_FAMILIES, STYLE_NAMES, SUB_STYLES
from goated_prompter.prompting.details import LENGTH_ADAPTERS
from goated_prompter.prompting.styles import CAPTURE_ADAPTERS, STYLE_ADAPTERS, SUB_STYLE_ADAPTERS, resolve_style


def message(**changes):
    return assemble_instruction(GoatedPrompterRequest(**{"idea": "two friends playing football", **changes})).system_message


class StyleTests(unittest.TestCase):
    def test_every_named_style_has_text_and_auto_follows_the_request(self):
        self.assertEqual(set(STYLE_FAMILIES) - {"Auto"}, set(STYLE_ADAPTERS))
        self.assertEqual({family: set(subs) for family, subs in SUB_STYLES.items()},
                         {family: set(texts) for family, texts in SUB_STYLE_ADAPTERS.items()}, "every sub-style has its text")
        self.assertEqual(set(CAPTURE_NAMES), set(CAPTURE_ADAPTERS), "every capture has its text")
        self.assertEqual(resolve_style("Auto", "Generic"), "Auto")
        self.assertEqual(resolve_style("Auto", "Anima"), "Anime")
        self.assertEqual(resolve_style("Realistic", "Anima"), "Anime", "Anima cannot render photographs.")

    def test_a_sub_style_adds_its_line_to_its_familys_text(self):
        system = message(target_model="Krea 2", style="Anime / 90s cel anime")
        self.assertEqual(system.count("VISUAL STYLE — Anime / 90s cel anime"), 1)
        self.assertIn(STYLE_ADAPTERS["Anime"] + " " + SUB_STYLE_ADAPTERS["Anime"]["90s cel anime"], system)
        self.assertNotIn(SUB_STYLE_ADAPTERS["Anime"]["Chibi"], system)
        self.assertEqual(resolve_style("Cinematic / Neo-noir", "Anima"), "Anime", "a photographic family stays off Anima")
        self.assertEqual(resolve_style("Painting / Oil", "Anima"), "Painting / Oil")
        self.assertEqual(resolve_style("Anime / Not a sub-style", "Krea 2"), "Auto")
        self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "style": "Comic / Noir"})["style"], "Comic / Noir")

    def test_builder_adds_the_selected_style_once(self):
        self.assertNotIn("VISUAL STYLE", message())
        anime = message(target_model="Krea 2", style="Anime")
        self.assertEqual(anime.count("VISUAL STYLE — Anime"), 1)
        self.assertIn(STYLE_ADAPTERS["Anime"], anime)
        self.assertLess(anime.index("VISUAL STYLE"), anime.index("OUTPUT FORMAT"))
        self.assertIn("VISUAL STYLE — Anime", message(target_model="Anima"))
        self.assertIn("VISUAL STYLE — Product", message(style="Product"))

    def test_capture_only_shapes_realistic_photographs(self):
        self.assertEqual(set(CAPTURE_NAMES), set(CAPTURE_ADAPTERS))
        phone = message(target_model="Krea 2", style="Realistic", capture="Phone snapshot")
        self.assertEqual(phone.count(CAPTURE_ADAPTERS["Phone snapshot"]), 1)
        self.assertNotIn(CAPTURE_ADAPTERS["Phone snapshot"], message(target_model="Krea 2", style="Anime", capture="Phone snapshot"))
        for capture in set(CAPTURE_ADAPTERS) - {"Auto"}:
            self.assertNotIn(CAPTURE_ADAPTERS[capture], message(target_model="Krea 2", style="Realistic"))

    def test_realistic_style_does_not_countermand_krea_density(self):
        for length in ("Short", "Maximum Detail"):
            with self.subTest(length=length):
                system = message(target_model="Krea 2", style="Realistic", prompt_length=length)
                style = system.split("VISUAL STYLE — Realistic\n", 1)[1].split("\n\n", 1)[0]
                self.assertIn("TARGET MODEL ADAPTER\nKrea 2 target:", system)
                self.assertEqual(system.count(LENGTH_ADAPTERS[length]), 1)
                self.assertIn("Photorealistic image", style)
                self.assertNotIn("instead of a long inventory", style)

    def test_precision_directors_do_not_countermand_krea_density(self):
        for director in ("krea_2_high_detail", "maximum_detail_director"):
            for length in ("Short", "Maximum Detail"):
                with self.subTest(director=director, length=length):
                    system = message(target_model="Krea 2", director_preset=director, prompt_length=length)
                    behavior = system.split("DIRECTOR BEHAVIOR", 1)[1].split("\n\n", 1)[0]
                    self.assertIn("TARGET MODEL ADAPTER\nKrea 2 target:", system)
                    self.assertEqual(system.count(LENGTH_ADAPTERS[length]), 1)
                    self.assertNotIn("do not exhaustively inventory", behavior.casefold())
                    self.assertNotIn("or exhaustively enumerate", behavior.casefold())

    def test_dataset_draft_validates_style(self):
        self.assertEqual(validate_dataset_draft(default_dataset_draft())["style"], "Auto")
        self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "style": "Anime"})["style"], "Anime")
        with self.assertRaises(ValueError):
            validate_dataset_draft({**default_dataset_draft(), "style": "Watercolour anime"})
        self.assertEqual(validate_dataset_draft(default_dataset_draft())["capture"], "Auto")
        with self.assertRaises(ValueError):
            validate_dataset_draft({**default_dataset_draft(), "capture": "Polaroid"})
        anime = validate_dataset_draft({**default_dataset_draft(), "style": "Anime", "capture": "Analog film"})
        self.assertEqual(anime["capture"], "Auto", "Capture only describes a Realistic image.")
        self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "style": "Realistic",
                                                 "capture": "Analog film"})["capture"], "Analog film")

    def test_dataset_draft_maps_a_replaced_director_to_style_and_capture(self):
        draft = validate_dataset_draft({**default_dataset_draft(), "director_preset": "smartphone_realism"})
        self.assertEqual((draft["director_preset"], draft["style"], draft["capture"]), ("general_director", "Realistic", "Phone snapshot"))
        kept = validate_dataset_draft({**default_dataset_draft(), "director_preset": "anime_director", "style": "Painting"})
        self.assertEqual((kept["director_preset"], kept["style"]), ("general_director", "Painting"), "A chosen style stays.")


if __name__ == "__main__":
    unittest.main()
