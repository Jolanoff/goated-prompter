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
    library_status, load_library, parse_library, pick_references, style_profile, style_profile_text)
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

    def test_references_put_matches_first_and_top_up_from_the_rest_of_the_library(self):
        self.write("Anima", CAR, KITCHEN, BEACH)
        picks = pick_references("Anima", "car interior driving", count=2)
        self.assertEqual(picks[0], CAR)
        self.assertIn(picks[1], (KITCHEN, BEACH))
        self.assertEqual(len(pick_references("Anima", "space station orbit", count=2)), 2)
        self.assertEqual(len(pick_references("Anima", "car", count=5)), 3, "Never more than the library holds.")
        self.assertEqual(pick_references("Generic", "car", count=2), ())
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
        self.assertIn("STYLE FROM THE USER'S PROMPT LIBRARY", instruction.system_message)
        self.assertIn(CAR, instruction.system_message)
        self.assertNotIn("STYLE EXAMPLE", instruction.system_message)
        self.assertEqual(instruction.reference_prompts, (CAR, KITCHEN))
        unrelated = assemble_instruction(GoatedPrompterRequest(idea="astronaut in orbit", target_model="Anima"))
        self.assertNotIn("STYLE EXAMPLE", unrelated.system_message, "Any saved prompt beats the built-in example.")
        self.assertEqual(set(unrelated.reference_prompts), {CAR, KITCHEN})

    def test_library_style_is_the_last_guidance_and_the_output_rule_points_to_it(self):
        sectioned = "Subject and action:\nA courier sprints.\n\nComposition and camera:\nLow angle."
        self.write("Krea 2", sectioned)
        system = assemble_instruction(GoatedPrompterRequest(idea="a chef plating dessert", target_model="Krea 2")).system_message
        style, settings, contract = (system.index("STYLE FROM THE USER'S PROMPT LIBRARY"),
                                     system.index("USER SETTINGS"), system.index("Output contract:"))
        self.assertLess(settings, style)
        self.assertLess(style, contract)
        self.assertNotIn("DIRECTOR BEHAVIOR", system, "The default Director's style advice would compete with the library.")
        self.assertIn("Krea 2 target: write the prompt as natural-language text for Krea 2", system)
        self.assertNotIn("exhaustive", system[:style], "Built-in style advice gives way to the library.")
        self.assertIn('YOUR LIBRARY\'S STYLE (1 saved prompt): typically about 11 words; written as labeled sections; '
                      'with the sections "Subject and action:", "Composition and camera:"', system)
        chosen = assemble_instruction(GoatedPrompterRequest(idea="a chef plating dessert", target_model="Krea 2",
                                                            director_preset="photography_director")).system_message
        self.assertIn("DIRECTOR BEHAVIOR", chosen, "A Director the user picked still applies.")
        self.assertIn("written like the user's library prompts above, including labeled sections", system)
        self.assertIn("wins over the style advice of the target adapter and the Director", " ".join(system.split()))
        self.assertNotIn("headings", system[contract:])
        empty = assemble_instruction(GoatedPrompterRequest(idea="a chef plating dessert", target_model="Generic")).system_message
        self.assertIn("in the target adapter's writing style", empty)

    def test_style_profile_measures_structure_sections_and_a_shared_trigger(self):
        sectioned = ["Subject and action:\nA courier sprints.\n\nLighting:\nNoon sun.",
                     "Subject and action:\nA cook laughs.\n\nLighting:\nWindow light.\n\nMood:\nWarm."]
        profile = style_profile(sectioned + ["A plain paragraph about a dog in the rain."])
        self.assertEqual((profile["structure"], profile["sections"]), ("labeled sections", ["Subject and action", "Lighting"]))
        trigger = [f"zidiusArt, snapshot of a woman {word}, windy, shy smile" for word in ("reading", "cooking", "running")]
        profile = style_profile(trigger)
        self.assertEqual((profile["structure"], profile["lead"], profile["median_words"]), ("flowing prose paragraphs", "zidiusArt", 9))
        tags = ["1girl, solo, rain, umbrella, street, night\n\nA girl waits.", "1boy, running, park, dog, sunny\n\nA boy runs."]
        self.assertEqual(style_profile(tags)["structure"], "a leading tag list, then prose")
        self.assertIsNone(style_profile(()))
        self.assertIn("at about 60 words for the selected Maximum Detail length",
                      style_profile_text({**profile, "median_words": 46}, "Maximum Detail"))

    def test_dataset_writer_uses_the_same_references_for_every_image_of_a_batch(self):
        boxing = "1boy, boxing, punching bag, gym, sweat\n\nA boxer slams a heavy bag under harsh gym lights."
        self.write("Krea 2", boxing, KITCHEN)
        data = valid_draft(target="Krea 2")
        writers = [dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, index,
                                       plan_item=saved_scene(index)) for index in (1, 2)]
        self.assertEqual(writers[0].reference_prompts, writers[1].reference_prompts)
        self.assertEqual(set(writers[0].reference_prompts), {boxing, KITCHEN})

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
