"""Scenes from the user's prompt library: Dataset recasting and Builder Remix."""

import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import IDEAS_SYSTEM, ideas_instruction
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.service import validate_dataset_draft
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, cast_size, library_path, pick_scenarios
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import saved_scene, valid_draft

CAR = ("1girl, 1boy, driving_from_front, car, motor_vehicle, driving, car_interior, steering_wheel, seatbelt,\n"
       "A mother is concentrating on driving, her daughter next to her is sleeping, and her two little sons in the back "
       "seat are fighting over snacks; the mother is angry with an anger vein.")
PICNIC = "2girls, 1boy, picnic, park, blanket, sandwich\n\nThree friends share sandwiches on a picnic blanket."
SOLO = "1girl, solo, reading, library, bookshelf\n\nA girl reads alone between tall bookshelves."


class LibraryRecastTests(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {LIBRARY_DIR_ENV: str(directory)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def library(self, target, *prompts):
        library_path(target).write_text("\n---\n".join(prompts), encoding="utf-8")

    def test_cast_size_reads_count_tags_in_either_anima_layout(self):
        self.assertEqual(cast_size(CAR), 2)
        self.assertEqual(cast_size(PICNIC), 3)
        self.assertEqual(cast_size(SOLO), 1)
        self.assertIsNone(cast_size("A cozy cafe at night."))

    def test_scenarios_prefer_matches_skip_undersized_scenes_and_vary_between_runs(self):
        self.library("Anima", CAR, PICNIC, SOLO)
        self.assertEqual(pick_scenarios("Anima", "naruto driving a car", 1, cast=2, rng=random.Random(1)), (CAR,))
        two = pick_scenarios("Anima", "", 3, cast=2, rng=random.Random(2))
        self.assertEqual(set(two[:2]), {CAR, PICNIC})
        self.assertEqual(two[2], SOLO, "An undersized scene is used only when nothing else fits.")
        self.assertEqual(len(pick_scenarios("Anima", "", 5, rng=random.Random(3))), 5)
        orders = {pick_scenarios("Anima", "", 3, rng=random.Random(seed)) for seed in range(20)}
        self.assertGreater(len(orders), 1)

    def test_library_mode_gives_each_idea_a_saved_scenario_instead_of_a_direction(self):
        self.library("Anima", CAR, PICNIC)
        data = valid_draft(amount=2, target="Anima", source_mode="library",
                           subject="Naruto and a random character doing anything",
                           _confirmed_intent=dataset_understanding_fixture(character_count=2))
        context = json.loads(ideas_instruction(data, dataset_assignments(data), rng=random.Random(4)).user_message)
        scenarios = [row["library_scenario"] for row in context["assignments"]]
        self.assertEqual(set(scenarios), {CAR, PICNIC})
        self.assertTrue(all("creative_direction" not in row for row in context["assignments"]))
        self.assertNotIn("library_extras", context)
        self.assertIn("Remove roles the cast does not fill", IDEAS_SYSTEM.replace("\n", " "))
        self.assertIn("LIBRARY SCENARIOS", IDEAS_SYSTEM)
        self.assertIn("never reuse the saved prompt's character names", IDEAS_SYSTEM.replace("\n", " "))

    def test_library_mode_requires_saved_prompts(self):
        data = valid_draft(target="Anima", source_mode="library")
        with self.assertRaisesRegex(ValueError, "data/prompt_library/anima.txt"):
            validate_dataset_draft(data, generation=True)
        self.library("Anima", CAR)
        validated = validate_dataset_draft({**data, "library_extras": "keep"}, generation=True)
        self.assertNotIn("library_extras", validated, "A setting saved by an earlier build is dropped.")

    def test_library_recasts_are_not_copy_checked_against_their_own_scene(self):
        self.library("Krea 2", "A boxer slams a heavy training bag under harsh gym lights.")
        for mode, expected in (("random", 1), ("library", 0)):
            data = valid_draft(target="Krea 2", source_mode=mode)
            writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=saved_scene())
            self.assertEqual(len(writer.reference_prompts), expected)

    def test_builder_remix_recasts_a_matching_saved_prompt(self):
        with self.assertRaisesRegex(ValueError, "Remix needs saved prompts"):
            assemble_instruction(GoatedPrompterRequest(idea="naruto and a girl driving", mode="Remix", target_model="Anima"))
        self.library("Anima", CAR, SOLO)
        instruction = assemble_instruction(GoatedPrompterRequest(idea="naruto and a girl in a car", mode="Remix", target_model="Anima"))
        self.assertIn("SCENARIO TO RECAST", instruction.system_message)
        self.assertIn(CAR, instruction.system_message)
        self.assertNotIn(CAR, instruction.reference_prompts)


if __name__ == "__main__":
    unittest.main()
