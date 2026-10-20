"""Target envelopes, semantic creativity and specialist-only Directors."""

import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.presets import get_director_preset
from goated_prompter.prompting.target_models import TARGET_CAPABILITIES, get_model_adapter, get_target_capabilities, resolve_target_length
from goated_prompter.options.targets import TARGET_MODEL_NAMES
from goated_prompter.workflow_settings import validate_draft


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
        # One Z-Image target serves Base and Turbo, so its prompts never rely on a negative prompt.
        self.assertTrue(get_target_capabilities("Z-Image").positive_description_only)
        self.assertFalse(get_target_capabilities("Z-Image").supports_negative_prompt)

    def test_legacy_targets_migrate_without_ambiguous_selector_entries(self):
        for legacy, current in (("Qwen2.1", "Qwen Image 2.1"), ("Qwen Image", "Qwen Image (original)"),
                                ("Z-Image Base", "Z-Image"), ("Z-Image Turbo", "Z-Image"), ("MiniMax", "MiniMax H3")):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, TARGET_MODEL_NAMES)
                self.assertEqual(GoatedPrompterRequest(idea="A book", target_model=legacy).target_model, current)
                self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "target": legacy})["target"], current)
                self.assertEqual(validate_draft("refine", {"target": legacy})["target"], current)
                self.assertEqual(get_model_adapter(legacy), get_model_adapter(current))
        self.assertIn("Qwen/Qwen-Image checkpoint", get_model_adapter("Qwen Image (original)"))

    def test_krea_only_says_how_to_write_and_leaves_the_medium_to_the_style(self):
        adapter = get_model_adapter("Krea 2")
        self.assertIn("State the medium in words", adapter)
        self.assertIn("rewards concrete natural-language description", adapter)
        self.assertNotIn("exhaustive", adapter, "How long the prompt is belongs to Length.")
        self.assertIn('"Composition and camera:"', adapter)
        for owned_elsewhere in ("anime", "photographic", "aesthetic freedom"):
            self.assertNotIn(owned_elsewhere, adapter)

    def test_flux_maximum_detail_stays_moderate(self):
        message = self.instruction("FLUX.2 Klein", prompt_length="Maximum Detail")
        self.assertIn("roughly 40 to 100 words", message)
        self.assertIn("The model has no negative prompt", message)
        self.assertIn("Moderately detailed, focused", message)
        self.assertNotIn("Exhaustively cover", message)
        self.assertIn(resolve_target_length("FLUX.2 Klein", "Maximum Detail"), message)

    def test_anima_keeps_negative_terms_out_of_the_positive_prompt(self):
        self.assertIn("Avoid redundant tags, excessive tag counts, negative prompt terms", get_model_adapter("Anima"))

    def test_z_image_exclusions_are_owned_by_the_compiler(self):
        from goated_prompter.planning.constraints import COMPILED_CONTRACT
        for idea, forbidden in (("A portrait; no jewelry", "jewelry"),
                                ("A quiet courtyard; without vehicles", "vehicles")):
            with self.subTest(idea=idea):
                instruction = assemble_instruction(GoatedPrompterRequest(idea=idea, target_model="Z-Image"), text_only=True)
                adapter = instruction.system_message.split("TARGET MODEL ADAPTER\n", 1)[1].split("\n\nUSER SETTINGS", 1)[0]
                self.assertNotIn("state anything to exclude as a positive fact", adapter)
                self.assertEqual(instruction.system_message.count(COMPILED_CONTRACT), 1)
                self.assertIn(f'"forbidden": ["{forbidden}"]', instruction.system_message)
                self.assertIn("Apply them silently by omission", instruction.system_message)
                self.assertNotIn(forbidden, instruction.user_message)

    def test_z_image_preserves_negative_words_in_requested_lettering(self):
        idea = 'A sign with text "No jewelry".'
        instruction = assemble_instruction(GoatedPrompterRequest(idea=idea, target_model="Z-Image"), text_only=True)
        self.assertEqual(instruction.user_message, idea)
        self.assertNotIn('"forbidden":', instruction.system_message)

    def test_anima_adapter_uses_the_owner_supplied_plain_text_contract_once(self):
        adapter = get_model_adapter("Anima")
        self.assertEqual(adapter.count("Anima target:"), 1)
        for requirement in ("hybrid of Danbooru/Gelbooru-style tags and concise natural-language scene prose",
                "one comma-separated sequence of relevant lowercase tags", "correct subject-count tag",
                "keeping them correctly assigned in multi-character scenes",
                "Avoid redundant tags, excessive tag counts, negative prompt terms",
                "Preserve supplied tag wording, order, weights, repetitions and locked trigger prefixes"):
            self.assertIn(requirement, adapter)
        self.assertEqual(adapter.count("\n"), 0)

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
        self.assertIn("one flowing paragraph of four to eight sentences", message)
        self.assertNotIn("Do not invent dialogue", get_model_adapter("LTX 2.5"), "How much is invented belongs to Creativity.")
        self.assertIn("words to be read or heard (signs, captions, dialogue) only when the request asks", message)
        self.assertIn("Creativity alone sets how much is invented", message)

    def test_all_lengths_and_creativity_preserve_target_hard_structure(self):
        for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
            for creativity in ("Strict", "Balanced", "Creative", "Dice"):
                with self.subTest(length=length, creativity=creativity):
                    message = self.instruction("Ideogram4", prompt_length=length, creativity=creativity)
                    self.assertIn("All required JSON keys and their order remain intact", message)
                    self.assertIn("Each setting has one job and none overrides another.", message)
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
        for director in ("krea_2_pose_lock", "krea_2_identity_edit", "krea_2_high_detail"):
            with self.subTest(director=director):
                preset = get_director_preset(director)
                self.assertIn(preset.instructions, self.instruction("Krea 2", director_preset=director))
                message = self.instruction("Generic", director_preset=director, system_prompt_override="Unrelated Krea-only instruction")
                self.assertNotIn(preset.instructions, message)
                self.assertNotIn("Unrelated Krea-only instruction", message)
                self.assertNotIn("DIRECTOR BEHAVIOR", message)


if __name__ == "__main__":
    unittest.main()
