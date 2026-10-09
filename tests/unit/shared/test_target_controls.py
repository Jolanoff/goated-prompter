"""Target envelopes, semantic creativity and specialist-only Directors."""

import unittest

from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_visible_content import positive_prompt_error, sanitize_positive_prompt
from goated_prompter.presets import get_director_preset
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.target_models import (
    TARGET_MODEL_NAMES, TARGET_CAPABILITIES, get_model_adapter, get_target_capabilities, resolve_target_length,
)
from goated_prompter.workflow_settings import validate_draft
from tests.support.dataset import valid_draft, saved_scene


class TargetControlTests(unittest.TestCase):
    def instruction(self, target, **changes):
        return assemble_instruction(GoatedPrompterRequest(idea="An anime character reading a book", target_model=target,
                                                        **changes), text_only=True).system_message

    def test_capabilities_cover_only_supported_targets(self):
        self.assertEqual(set(TARGET_MODEL_NAMES), set(TARGET_CAPABILITIES))
        self.assertTrue(get_target_capabilities("Anima").supports_negative_prompt)
        self.assertTrue(get_target_capabilities("FLUX.2 Klein").positive_description_only)
        self.assertEqual(get_target_capabilities("Ideogram4").output_format, "json")
        self.assertTrue(get_target_capabilities("MiniMax H3").supports_multishot)
        self.assertTrue(get_target_capabilities("LTX 2.5").supports_audio)
        self.assertTrue(get_target_capabilities("Z-Image Base").supports_negative_prompt)
        self.assertFalse(get_target_capabilities("Z-Image Turbo").supports_negative_prompt)
        self.assertTrue(get_target_capabilities("Z-Image Base").supports_cfg)
        self.assertFalse(get_target_capabilities("Z-Image Turbo").supports_cfg)

    def test_legacy_targets_migrate_without_ambiguous_selector_entries(self):
        for legacy, current in (("Qwen2.1", "Qwen Image 2.1"), ("Qwen Image", "Qwen Image (original)"),
                                ("Z-Image", "Z-Image Base"), ("MiniMax", "MiniMax H3")):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, TARGET_MODEL_NAMES)
                self.assertEqual(GoatedPrompterRequest(idea="A book", target_model=legacy).target_model, current)
                self.assertEqual(validate_dataset_draft(valid_draft(target=legacy))["target"], current)
                self.assertEqual(validate_draft("refine", {"target": legacy})["target"], current)
                self.assertEqual(get_model_adapter(legacy), get_model_adapter(current))
        self.assertIn("Qwen/Qwen-Image checkpoint", get_model_adapter("Qwen Image (original)"))

    def test_krea_preserves_anime_and_all_other_requested_media(self):
        adapter = get_model_adapter("Krea 2")
        for medium in ("anime", "illustration", "graphic design", "3D"):
            self.assertIn(medium, adapter)
        self.assertIn("For photographic requests, use appropriate photographic language", adapter)
        self.assertNotIn("photographic realism", adapter)
        self.assertIn("do not force photographic rendering", adapter)
        message = self.instruction("Krea 2", creativity="Dice")
        self.assertIn("leave useful aesthetic freedom", message)

    def test_flux_maximum_detail_stays_moderate_and_dataset_scene_dense(self):
        message = self.instruction("FLUX.2 Klein", prompt_length="Maximum Detail")
        self.assertIn("moderately detailed natural-language prose", message)
        self.assertIn("Moderately detailed, focused", message)
        self.assertNotIn("Exhaustively cover", message)
        data = valid_draft(target="FLUX.2 Klein", length="Maximum Detail")
        request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"])
        writer = dataset_instruction(request, data, 1, plan_item=saved_scene())
        self.assertIn(resolve_target_length(data["target"], data["length"]), writer.system_message)
        self.assertIn("ENHANCE THE ACCEPTED SCENE", writer.system_message)

    def test_anima_positive_quality_tags_are_allowed_but_negatives_stay_separate(self):
        prompt = 'masterpiece, best quality, score_9, 1girl\nShe reads a book beside a window.'
        self.assertEqual(sanitize_positive_prompt(prompt, "Anima"), prompt)
        self.assertIsNone(positive_prompt_error(prompt, "Anima"))
        self.assertIsNotNone(positive_prompt_error(prompt, "Generic"))
        self.assertIsNotNone(positive_prompt_error(prompt + "\nnegative prompt: bad anatomy", "Anima"))
        self.assertRegex(get_model_adapter("Anima"), r"(?i)negative (?:conditioning|prompt)[^\n]*(?:positive prose|positive prompt)")

    def test_anima_adapter_uses_the_owner_supplied_plain_text_contract_once(self):
        adapter = get_model_adapter("Anima")
        self.assertEqual(adapter.count("Anima target:"), 1)
        self.assertTrue(adapter.startswith("Anima target: Generate a clean hybrid prompt combining "))
        for heading in ("Output structure", "Character handling", "Tag selection", "Scene prose", "Strict preservation"):
            self.assertIn("\n\n" + heading + "\n\n", adapter)
        self.assertIn("\n\nFinal validation\nBefore returning the prompt, ensure that:\n\n", adapter)
        self.assertIn("Use lowercase tags with spaces instead of underscores, except for supported score tags.", adapter)
        self.assertIn("When a locked prefix is supplied, generate only the continuation.", adapter)
        self.assertTrue(adapter.endswith("All protected inputs remain unchanged."))

    def test_observer_adapter_retains_rich_frame_walk_and_lighting(self):
        message = self.instruction("Qwen Image 2.1", prompt_length="Maximum Detail")
        for phrase in ("English observer's description", "walk the frame", "nuanced colors", "occlusion",
                       "direction and quality of light", "exactly one whole-frame composition sentence"):
            self.assertIn(phrase, message)

    def test_h3_target_owns_sections_temporal_and_reference_mechanics(self):
        message = self.instruction("MiniMax H3", mode="Video", director_preset="minimax_h3_director")
        for phrase in ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music",
                       "[Shot N]", "retention_analysis", "identity-only references are not first frames"):
            self.assertIn(phrase, message)
        for director in ("minimax_director", "minimax_h3_director"):
            instructions = get_director_preset(director).instructions
            self.assertNotIn("integrated_multimodal_description", instructions)
            self.assertNotIn("Return only the required MiniMax schema", instructions)

    def test_ltx_target_overrides_video_director_motion_invention(self):
        message = self.instruction("LTX 2.5", mode="Video", director_preset="video_director", prompt_length="Maximum Detail")
        self.assertIn("one focused flowing paragraph", message)
        self.assertIn("Do not automatically invent dialogue, camera movement or cuts", message)
        self.assertIn("take priority over Length and conflicting Director preferences", message)

    def test_all_lengths_and_creativity_preserve_target_hard_structure(self):
        for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
            for creativity in ("Strict", "Balanced", "Creative", "Dice"):
                with self.subTest(length=length, creativity=creativity):
                    message = self.instruction("Ideogram4", prompt_length=length, creativity=creativity)
                    self.assertIn("All required JSON keys and their order remain intact", message)
                    self.assertIn("Semantic invention never changes required target syntax or output format", message)
                    self.assertIn("Mode defines the task. Director behavior must not replace that task", message)
                    self.assertIn("OUTPUT FORMAT — Ideogram4", message)

    def test_control_sections_stay_in_order_and_output_contract_is_last(self):
        message = self.instruction("Ideogram4", custom_instructions="Preserve the exact lettering.")
        sections = ("MODE ADAPTER", "TARGET MODEL ADAPTER", "Creativity —", "Prompt length —",
                    "PRESERVATION CONSTRAINTS", "DIRECTOR BEHAVIOR", "WORKFLOW RULES", "OUTPUT FORMAT — Ideogram4")
        self.assertEqual([message.index(section) for section in sections], sorted(message.index(section) for section in sections))
        from goated_prompter.prompting.output import output_contract
        self.assertTrue(message.endswith(output_contract("Ideogram4")))

    def test_precision_directors_do_not_set_verbosity_and_legacy_ids_survive(self):
        for legacy in ("Maximum Detail Director", "Krea 2 High Detail"):
            director = get_director_preset(legacy)
            self.assertIn("Precision", director.label)
            self.assertNotIn("long-form", director.instructions)
            self.assertNotIn("dense but coherent", director.instructions)
        self.assertEqual(get_director_preset("Maximum Detail Director").id, "maximum_detail_director")
        self.assertIn("Community", get_director_preset("Krea 2 Identity Edit").label)

    def test_krea_specific_directors_are_target_gated_even_with_working_copy(self):
        for director in ("krea_2_smartphone_realism", "krea_2_pose_lock", "krea_2_identity_edit", "krea_2_high_detail"):
            with self.subTest(director=director):
                preset = get_director_preset(director)
                self.assertIn(preset.instructions, self.instruction("Krea 2", director_preset=director))
                message = self.instruction("Generic", director_preset=director, system_prompt_override="Unrelated Krea-only instruction")
                self.assertNotIn(preset.instructions, message)
                self.assertNotIn("Unrelated Krea-only instruction", message)
                self.assertIn("Director is inactive", message)


if __name__ == "__main__":
    unittest.main()
