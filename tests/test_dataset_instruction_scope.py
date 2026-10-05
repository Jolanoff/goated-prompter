"""Stage contracts have one owner and cannot import contradictory responsibilities."""

import json
import unittest

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import default_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.scene_planner import scene_planner_instruction, scene_composer_instruction, SCENE_FORMAT_CORRECTION


class DatasetInstructionScopeTests(unittest.TestCase):
    def setUp(self):
        self.data = {**default_dataset_draft(), "amount": 1, "subject": "A performer", "trigger": "person_token"}
        self.assignments = dataset_assignments(self.data)

    def test_fast_planner_invents_ideas_instead_of_echoing_nonexistent_supplied_ideas(self):
        instruction = scene_planner_instruction(self.data, self.assignments)
        self.assertNotIn("exact unchanged supplied", instruction.system_message)
        self.assertNotIn("idea (exact unchanged", instruction.system_message)
        self.assertNotIn("idea", json.loads(instruction.user_message)["assignments"][0])
        self.assertEqual(instruction.system_message.count("OUTPUT FORMAT"), 1)
        corrected = scene_planner_instruction(self.data, self.assignments, correction=SCENE_FORMAT_CORRECTION)
        self.assertNotIn("exact supplied ideas", corrected.system_message)
        self.assertIn("previous_response", corrected.system_message)

    def test_fixed_scene_composer_does_not_receive_ideation_context(self):
        instruction = scene_composer_instruction(self.data, self.assignments, [{"index": 1, "idea": "A fixed event"}])
        context = json.loads(instruction.user_message)
        for key in ("variety", "existing_ideas", "recently_used_ideas", "requested_amount"):
            self.assertNotIn(key, context)
        self.assertEqual(context["assignments"][0]["idea"], "A fixed event")
        self.assertIn("echo its text and index exactly", instruction.system_message)

    def test_dataset_writer_does_not_inherit_builder_framing_and_semantic_invention_defaults(self):
        instruction = dataset_instruction(GoatedPrompterRequest(idea="A performer"), self.data, 1)
        for unrelated in ("FRAME COMPLETENESS DEFAULT", "WHAT DO YOU WANT?", "PRESERVATION CONSTRAINTS",
                          "Creativity controls SEMANTIC invention only"):
            self.assertNotIn(unrelated, instruction.system_message)
        self.assertEqual(instruction.system_message.count("SCENE-LOCKED VISUAL ENRICHMENT"), 1)

    def test_common_instruction_density_is_reduced_without_changing_stage_budgets(self):
        fast = scene_planner_instruction(self.data, self.assignments)
        composer = scene_composer_instruction(self.data, self.assignments, [{"index": 1, "idea": "A fixed event"}])
        writer = dataset_instruction(GoatedPrompterRequest(idea="A performer"), self.data, 1)
        for instruction, ceiling in ((fast, 2300), (composer, 1800), (writer, 1600)):
            self.assertLess(len(instruction.system_message.split()), ceiling, instruction.diagnostic_stage)
        self.assertEqual((fast.max_tokens, composer.max_tokens, writer.max_tokens), (1024, 1280, 768))
