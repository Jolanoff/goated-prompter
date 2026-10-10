"""Builder Remix recasts a saved prompt from the user's library."""

import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, library_path, pick_scenarios

CAR = ("1girl, 1boy, driving_from_front, car, motor_vehicle, driving, car_interior, steering_wheel, seatbelt,\n"
       "A mother is concentrating on driving, her daughter next to her is sleeping, and her two little sons in the back "
       "seat are fighting over snacks; the mother is angry with an anger vein.")
PICNIC = "2girls, 1boy, picnic, park, blanket, sandwich\n\nThree friends share sandwiches on a picnic blanket."
SOLO = "1girl, solo, reading, library, bookshelf\n\nA girl reads alone between tall bookshelves."


class RemixTests(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {LIBRARY_DIR_ENV: str(directory)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def library(self, target, *prompts):
        library_path(target).write_text("\n---\n".join(prompts), encoding="utf-8")

    def test_scenarios_prefer_matches_and_vary_between_runs(self):
        self.library("Anima", CAR, PICNIC, SOLO)
        self.assertEqual(pick_scenarios("Anima", "naruto driving a car", 1, rng=random.Random(1)), (CAR,))
        self.assertEqual(len(pick_scenarios("Anima", "", 5, rng=random.Random(3))), 5)
        orders = {pick_scenarios("Anima", "", 3, rng=random.Random(seed)) for seed in range(20)}
        self.assertGreater(len(orders), 1)

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
