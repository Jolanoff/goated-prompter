"""User prompt library: untracked per-target files searched locally and used as references."""

import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import GoatedPrompterService, assemble_instruction
from goated_prompter.options.targets import TARGET_MODEL_NAMES
from goated_prompter.prompt_library import (LIBRARY_DIR_ENV, copied_reference, ensure_library_files, library_path,
    library_status, load_library, parse_library, pick_references)
from goated_prompter.features.dataset.prompting import dataset_instruction
from tests.support.dataset import saved_scene, valid_draft
from tests.unit.planning.test_supporting_planning import ScriptedBackend

CAR = ("1girl, 1boy, driving_from_front, car, motor_vehicle, driving, car_interior, steering_wheel, seatbelt\n\n"
       "A mother is concentrating on driving while her daughter sleeps beside her and two sons fight over snacks.")
KITCHEN = "1girl, kitchen, cooking, apron, steam\n\nA woman stirs a pot of soup in a sunny kitchen."
BEACH = "2girls, beach, volleyball, jumping, sand\n\nTwo girls leap for a volleyball on a bright beach."


class PromptLibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {LIBRARY_DIR_ENV: str(self.directory)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, target, *prompts, header=True):
        path = library_path(target)
        text = ("# comment line\n" if header else "") + "\n---\n".join(prompts)
        path.write_text(text, encoding="utf-8")
        return path

    def test_first_launch_creates_one_commented_empty_file_per_target_and_never_overwrites(self):
        ensure_library_files()
        self.assertEqual(len(list(self.directory.glob("*.txt"))), len(set(map(lambda t: library_path(t).name, TARGET_MODEL_NAMES))))
        self.assertEqual(library_path("Anima").name, "anima.txt")
        self.assertEqual(library_path("FLUX.2 Klein").name, "flux-2-klein.txt")
        self.assertEqual(load_library("Anima").prompts, ())
        self.write("Anima", KITCHEN)
        ensure_library_files()
        self.assertEqual(load_library("Anima").prompts, (KITCHEN,))

    def test_parser_keeps_blank_lines_inside_prompts_and_drops_comments(self):
        text = "# header\n\n" + CAR + "\n---\n# note\n" + KITCHEN + "\n---\n\n---\n"
        self.assertEqual(parse_library(text), (CAR, KITCHEN))

    def test_search_ranks_matching_subjects_and_tags_and_ignores_unrelated_requests(self):
        self.write("Anima", CAR, KITCHEN, BEACH)
        index = load_library("Anima")
        self.assertEqual(index.search("naruto driving a car with a friend")[0][1], CAR)
        self.assertEqual(index.search("cooking soup")[0][1], KITCHEN)
        self.assertEqual(index.search("space station orbit"), [])
        self.assertEqual(index.search(""), [])

    def test_references_are_sampled_from_the_best_matches(self):
        self.write("Anima", CAR, KITCHEN, BEACH)
        self.assertEqual(pick_references("Anima", "car interior driving", count=2), (CAR,))
        picks = {pick_references("Anima", "car kitchen beach", count=1, rng=random.Random(seed))[0] for seed in range(40)}
        self.assertGreater(len(picks), 1)

    def test_edits_are_picked_up_without_restart(self):
        path = self.write("Anima", KITCHEN)
        self.assertEqual(library_status("Anima")["count"], 1)
        path.write_text(KITCHEN + "\n---\n" + BEACH + "\n---\n" + CAR, encoding="utf-8")
        os.utime(path, ns=(1, 10 ** 18))
        self.assertEqual(library_status("Anima")["count"], 3)

    def test_copy_check_flags_long_shared_runs_only(self):
        self.assertTrue(copied_reference("Then a mother is concentrating on driving while her daughter sleeps beside her.", [CAR]))
        self.assertFalse(copied_reference("Naruto grips the wheel while a girl naps against the window.", [CAR]))

    def test_builder_uses_library_prompts_instead_of_the_built_in_example(self):
        self.assertIn("STYLE EXAMPLE", assemble_instruction(GoatedPrompterRequest(idea="driving a car", target_model="Anima")).system_message)
        self.write("Anima", CAR, KITCHEN)
        instruction = assemble_instruction(GoatedPrompterRequest(idea="naruto driving a car", target_model="Anima"))
        self.assertIn("REFERENCE PROMPTS", instruction.system_message)
        self.assertIn(CAR, instruction.system_message)
        self.assertNotIn(KITCHEN, instruction.system_message)
        self.assertNotIn("STYLE EXAMPLE", instruction.system_message)
        self.assertEqual(instruction.reference_prompts, (CAR,))
        unrelated = assemble_instruction(GoatedPrompterRequest(idea="astronaut in orbit", target_model="Anima"))
        self.assertIn("STYLE EXAMPLE", unrelated.system_message)
        self.assertEqual(unrelated.reference_prompts, ())

    def test_dataset_writer_picks_references_by_the_planned_scene(self):
        boxing = "1boy, boxing, punching bag, gym, sweat\n\nA boxer slams a heavy bag under harsh gym lights."
        self.write("Krea 2", boxing, KITCHEN)
        data = valid_draft(target="Krea 2")
        writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=saved_scene())
        self.assertEqual(writer.reference_prompts, (boxing,))
        self.assertIn(boxing, writer.system_message)

    def test_builder_retries_once_when_the_output_copies_a_reference(self):
        self.write("Generic", "A mother is concentrating on driving while her daughter sleeps beside her in the car.")
        copied = "A mother is concentrating on driving while her daughter sleeps beside her in the car at night."
        fresh = "Naruto steers through traffic while his friend dozes against the passenger window."
        backend = ScriptedBackend(copied, fresh)
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
            result = GoatedPrompterService(config={"backend": "mock"}).generate(
                GoatedPrompterRequest(idea="naruto driving a car with a sleeping friend", planning_mode="Direct"))
        self.assertEqual(result.prompt, fresh)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("library reference", backend.calls[1].system_message)


if __name__ == "__main__":
    unittest.main()
