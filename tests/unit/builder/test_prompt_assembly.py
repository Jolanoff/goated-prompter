"""Builder system prompts contain only sections that apply to the request."""

import json
import re
import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.image_utils import EncodedImage
from goated_prompter.options.targets import TARGET_MODEL_NAMES
from goated_prompter.output_repetition import remove_contradictory_solo
from goated_prompter.prompting.base import PRIORITY_CONTRACT, SETTINGS_PRECEDENCE, TEXT_ONLY_PRIORITY_CONTRACT
from goated_prompter.prompting.target_models import QWEN21_EDIT_EXAMPLE, TARGET_EXAMPLES
from goated_prompter.workflow_output import normalize_workflow_output, requested_visible_text

IMAGE = EncodedImage("Zm91cg==", "image/png", 16, 16)


def system_message(**changes):
    request = GoatedPrompterRequest(**{"idea": "a lantern on a windowsill", **changes})
    return assemble_instruction(request).system_message


class BuilderPromptAssemblyTests(unittest.TestCase):
    def test_reference_priorities_only_with_reference_images(self):
        for changes in ({}, {"mode": "Photography", "target_model": "FLUX.2 Klein"}):
            with self.subTest(changes=changes):
                message = system_message(**changes)
                self.assertIn(TEXT_ONLY_PRIORITY_CONTRACT, message)
                self.assertNotIn(PRIORITY_CONTRACT, message)
                self.assertNotIn("reference", message.split("MODE ADAPTER")[0].casefold())
        with_image = system_message(image=IMAGE)
        self.assertIn(PRIORITY_CONTRACT, with_image)
        self.assertEqual(with_image.count(SETTINGS_PRECEDENCE), 1)

    def test_no_meta_contract_ui_labels_or_internal_terms(self):
        for target in TARGET_MODEL_NAMES:
            for changes in ({}, {"image": IMAGE}):
                with self.subTest(target=target, image=bool(changes)):
                    message = system_message(target_model=target, **changes)
                    for phrase in ("MODE, DETAIL, AND DIRECTOR RESPONSIBILITIES", "WHAT DO YOU WANT",
                                   "Reference Map", "working copies"):
                        self.assertNotIn(phrase, message)

    def test_anima_format_only_for_anima(self):
        for target in TARGET_MODEL_NAMES:
            with self.subTest(target=target):
                tail = system_message(target_model=target).split("OUTPUT FORMAT")[-1]
                self.assertEqual("Anima" in tail, target == "Anima")

    def test_short_and_medium_do_not_mention_maximum_detail(self):
        for target in TARGET_MODEL_NAMES:
            for length in ("Short", "Medium"):
                with self.subTest(target=target, length=length):
                    self.assertNotIn("Maximum", system_message(target_model=target, prompt_length=length))

    def test_inactive_target_specific_director_adds_nothing(self):
        active = system_message(target_model="Krea 2", director_preset="krea_2_high_detail")
        inactive = system_message(target_model="FLUX.2 Klein", director_preset="krea_2_high_detail")
        self.assertIn("DIRECTOR BEHAVIOR", active)
        self.assertNotIn("DIRECTOR BEHAVIOR", inactive)
        self.assertNotIn("inactive", inactive)

    def test_each_target_carries_one_valid_style_example(self):
        self.assertEqual(set(TARGET_EXAMPLES), set(TARGET_MODEL_NAMES) - {"MiniMax H3"})
        for target in TARGET_MODEL_NAMES:
            with self.subTest(target=target):
                message = system_message(target_model=target)
                self.assertEqual(message.count("STYLE EXAMPLE"), int(target in TARGET_EXAMPLES))
                if target in TARGET_EXAMPLES:
                    request, output = TARGET_EXAMPLES[target]
                    self.assertIn(output, message)
                    self.assertLess(message.index("STYLE EXAMPLE"), message.index("USER SETTINGS"))
                    normalize_workflow_output(output, target, expected_visible_text=requested_visible_text(request),
                                              mode="Enhance")
        json.loads(TARGET_EXAMPLES["Ideogram4"][1])

    def test_anima_example_never_pairs_solo_with_several_characters(self):
        tags = [tag.strip() for tag in TARGET_EXAMPLES["Anima"][1].split("\n\n")[0].split(",")]
        characters = sum(int(match[1]) for tag in tags if (match := re.fullmatch(r"(\d+)(?:boys?|girls?|others?)", tag)))
        self.assertGreater(characters, 1, "The example should show multi-character count tags.")
        self.assertNotIn("solo", tags)
        message = system_message(target_model="Anima", idea="three boys jumping on top of a train")
        self.assertIn("use solo only when exactly one character appears", message)

    def test_solo_is_removed_only_when_count_tags_describe_several_characters(self):
        group = ("3boys , caesar anthonio zeppeli, jojo no kimyou na bouken, 1boy, green eyes, solo, blonde hair, "
                 "ash ketchum, pokemon, 1boy, black hair,midoriya izuku, 1boy, freckles\n\n"
                 "Three boys leap across a moving train, one of them riding solo ahead.")
        self.assertEqual(remove_contradictory_solo(group), group.replace(", solo,", ",", 1))
        for text, expected in (
            ("solo, 2girls, beach", "2girls, beach"),
            ("1boy, 1girl, (solo:1.2), rain", "1boy, 1girl, rain"),
            ("multiple girls, solo, park", "multiple girls, park"),
            ("1boy, solo, 1boy, train", "1boy, 1boy, train"),
            ("1girl, solo, rain\n\nShe walks solo.", "1girl, solo, rain\n\nShe walks solo."),
            ("3boys, solo focus, train", "3boys, solo focus, train"),
        ):
            with self.subTest(text=text):
                self.assertEqual(remove_contradictory_solo(text), expected)

    def test_builder_applies_the_solo_guard_to_anima_only(self):
        from unittest.mock import patch
        from goated_prompter.features.builder.service import GoatedPrompterService
        from tests.unit.planning.test_supporting_planning import ScriptedBackend
        output = "3boys, solo, train\n\nThree boys jump on a train."
        for target, expected in (("Anima", "3boys, train\n\nThree boys jump on a train."), ("Generic", output)):
            with self.subTest(target=target):
                backend = ScriptedBackend(output)
                with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
                    result = GoatedPrompterService(config={"backend": "mock"}).generate(
                        GoatedPrompterRequest(idea="three boys jumping on top of a train", target_model=target,
                                              planning_mode="Direct"))
                self.assertEqual(result.prompt, expected)

    def test_qwen21_edit_uses_the_edit_example(self):
        message = system_message(target_model="Qwen Image 2.1", image=IMAGE)
        self.assertIn(QWEN21_EDIT_EXAMPLE[1], message)
        self.assertNotIn(TARGET_EXAMPLES["Qwen Image 2.1"][1], message)

    def test_example_can_be_omitted(self):
        request = GoatedPrompterRequest(idea="a lantern", target_model="Anima")
        self.assertNotIn("STYLE EXAMPLE", assemble_instruction(request, include_target_example=False).system_message)


if __name__ == "__main__":
    unittest.main()
