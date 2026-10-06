"""Dataset reuses Builder assembly with a complete accepted scene, not a new idea."""

from dataclasses import replace
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.base import CORE_SYSTEM_PROMPT
from goated_prompter.prompting.creativity import CREATIVITY_ADAPTERS
from goated_prompter.prompting.details import DATASET_OUTPUT_TOKEN_LIMITS
from goated_prompter.prompting.target_models import get_model_adapter, resolve_target_length
from goated_prompter.presets import get_director_preset
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.test_dataset import valid_draft
from tests.test_dataset_scene import REPAIR, SCENE


class DatasetEnhanceTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        self.scene = {**dataset_idea_fixture(), "input": "", "scene": SCENE,
            "self_check": "PASS", "scene_status": "valid"}
        self.request = GoatedPrompterRequest(idea="Original raw concept must not be the final Builder input.", mode="Custom")

    def assemble(self, **changes):
        return dataset_instruction(self.request, {**self.data, **changes}, 1, plan_item=self.scene)

    def test_existing_builder_receives_only_the_complete_accepted_scene_and_staging_locks(self):
        before = deepcopy(self.scene)
        with patch("goated_prompter.core.assemble_instruction", wraps=assemble_instruction) as builder:
            instruction = self.assemble()
        builder.assert_called_once()
        request = builder.call_args.args[0]
        self.assertEqual(request.idea, SCENE)
        self.assertEqual(request.mode, "Enhance")
        self.assertEqual(request.planning_mode, "Direct")
        self.assertTrue(request.preserve_subject and request.preserve_composition and request.preserve_camera)
        self.assertEqual(instruction.user_message, SCENE)
        self.assertIn(CORE_SYSTEM_PROMPT, instruction.system_message)
        self.assertIn("Do not reinterpret its geometry, visibility, action,", instruction.system_message)
        self.assertIn("camera, framing or relationships", instruction.system_message)
        self.assertNotIn(self.request.idea, instruction.user_message)
        self.assertEqual(self.scene, before)
        self.assertFalse(builder.call_args.kwargs["compile_user_constraints"])

    def test_builder_target_creativity_detail_and_director_controls_are_reused(self):
        for target in ("Generic", "Anima"):
            for creativity in CREATIVITY_ADAPTERS:
                for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
                    with self.subTest(target=target, creativity=creativity, length=length):
                        instruction = self.assemble(target=target, creativity=creativity, length=length)
                        self.assertIn(get_model_adapter(target), instruction.system_message)
                        self.assertIn(CREATIVITY_ADAPTERS[creativity], instruction.system_message)
                        self.assertIn(resolve_target_length(target, length), instruction.system_message)
                        self.assertIn(get_director_preset(self.data["director_preset"]).instructions, instruction.system_message)
                        self.assertEqual(instruction.max_tokens, DATASET_OUTPUT_TOKEN_LIMITS[length])
                        self.assertEqual(instruction.hard_max_tokens, instruction.max_tokens)

    def test_edited_director_instructions_remain_active_but_cannot_unlock_staging(self):
        self.request = replace(self.request, system_prompt_override="Use restrained complementary colors and soft rim lighting.")
        instruction = self.assemble()
        self.assertIn(self.request.system_prompt_override, instruction.system_message)
        self.assertIn("ENHANCE THE ACCEPTED SCENE", instruction.system_message)

    def test_repair_pending_failed_or_missing_scenes_never_reach_builder(self):
        with patch("goated_prompter.core.assemble_instruction", wraps=assemble_instruction) as builder:
            for changes in ({"self_check": REPAIR}, {"self_check": ""}, {"scene_status": "failed"}, {"scene": ""}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    dataset_instruction(self.request, self.data, 1, plan_item={**self.scene, **changes})
            with self.assertRaises(ValueError):
                dataset_instruction(self.request, self.data, 1, plan_item={key: value for key, value in self.scene.items() if key != "self_check"})
            with self.assertRaises(ValueError):
                dataset_instruction(self.request, self.data, 1)
        builder.assert_not_called()

    def test_repaired_scene_is_authoritative_not_old_idea_camera_or_layout(self):
        self.scene.update(camera="OBSOLETE CAMERA FROM IDEA", placement="OBSOLETE LAYOUT FROM IDEA",
            scene="The left leg extends outward clear of the partner while the same body-lock contact and full-body three-quarter camera are preserved.")
        instruction = self.assemble()
        self.assertEqual(instruction.user_message, self.scene["scene"])
        self.assertNotIn("OBSOLETE", instruction.user_message + instruction.system_message)
        self.assertNotIn(REPAIR, instruction.user_message + instruction.system_message)

    def test_scoped_requirements_do_not_leak_another_guided_inputs_appearance_rules(self):
        brief = dataset_understanding_fixture(rules=[{"scope": "guided:1", "text": "Blue gloves"},
            {"scope": "guided:2", "text": "Red gloves"}, {"scope": "all_outputs", "text": "Two adults"},
            {"scope": "dataset", "text": "Varied compatible lighting"}])
        instruction = self.assemble(source_mode="guided", inputs="First drill\nSecond drill", _confirmed_intent=brief)
        requirements, _ = json.JSONDecoder().raw_decode(instruction.system_message.split("SCOPED APPROVED REQUIREMENTS\n", 1)[1])
        self.assertEqual(requirements["rules"], [brief["rules"][0], *brief["rules"][2:]])
        self.assertNotIn("Red gloves", instruction.system_message)

    def test_approved_and_absent_briefs_preserve_scene_and_rendering_handoff(self):
        brief = dataset_understanding_fixture(rules=[{"scope": "all_outputs", "text": "Green training outfit"}])
        for approved in (None, brief):
            with self.subTest(approved=bool(approved)):
                data = {**self.data, "_confirmed_intent": approved}
                before = deepcopy((data, self.scene))
                instruction = dataset_instruction(self.request, data, 1, plan_item=self.scene)
                self.assertEqual(instruction.user_message, self.scene["scene"])
                self.assertIn("camera, framing or relationships", instruction.system_message)
                self.assertIn("lighting, materials", instruction.system_message)
                requirements, _ = json.JSONDecoder().raw_decode(
                    instruction.system_message.split("SCOPED APPROVED REQUIREMENTS\n", 1)[1])
                self.assertEqual(requirements["rules"], brief["rules"] if approved else [])
                self.assertEqual((data, self.scene), before)

    def test_final_generation_keeps_one_enhancement_call_without_old_scene_or_semantic_evaluators(self):
        session = Mock()
        session.generate.return_value = "A boxer with ohwx_person extends a glove into the bag in a full-body arena image."
        instruction = self.assemble()
        config = {"backend": "mock", "semantic_validation": True, "support_validation": True, "semantic_constraints": True}
        with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=AssertionError("Unexpected evaluator")):
            result = DatasetService(config, lambda: None)._generate(session, instruction, self.data, 1,
                lambda _message: None, self.scene)
        self.assertIn("ohwx_person", result)
        session.generate.assert_called_once()
