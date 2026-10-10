"""Core orchestration tests without Pillow, models, or network access."""

from contextlib import ExitStack, nullcontext, redirect_stdout
from dataclasses import replace
import importlib
from io import StringIO
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, call, patch
from tests.support.paths import ROOT


# Isolate core module state from the other test suites.
PACKAGE = "_goated_core_tests"
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "goated_prompter")]
sys.modules[PACKAGE] = package
core = importlib.import_module(f"{PACKAGE}.features.builder.service")
contracts = importlib.import_module(f"{PACKAGE}.contracts")
image_utils = importlib.import_module(f"{PACKAGE}.image_utils")
reference_map = importlib.import_module(f"{PACKAGE}.reference_map")
prompting_base = importlib.import_module(f"{PACKAGE}.prompting.base")


class CoreTests(unittest.TestCase):
    def test_minimax_structured_capability_dispatches_format_repair(self):
        valid = 'integrated_multimodal_description: [Shot 1] A runner shouts "Go!" (quietly).\noverall_soundscape: Footsteps.\nnon_diegetic_music: None.'
        self.session.generate.side_effect = ["A runner moves.", valid]
        result = self.service.generate(self.request("Off", mode="Video", target_model="MiniMax H3"))
        self.assertEqual(result.prompt, valid)
        self.assertEqual(self.session.generate.call_count, 2)
        repair = self.session.generate.call_args_list[1].args[0]
        self.assertIn("MINIMAX H3 FORMAT CORRECTION", repair.system_message)
        self.assertTrue(repair.user_message.startswith(self.session.generate.call_args_list[0].args[0].user_message))
        self.assertIn("LOCAL REPAIR CONTRACT", repair.user_message)

    def test_minimax_nonvideo_mode_retains_plain_image_task(self):
        self.session.generate.side_effect = ["A runner beside a sign."]
        result = self.service.generate(self.request("Off", mode="Enhance", target_model="MiniMax H3"))
        self.assertEqual(result.prompt, "A runner beside a sign.")
        self.assertEqual(self.session.generate.call_count, 1)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(StringIO()))
        self.backend = Mock(name="backend")
        self.backend.name = "test-backend"
        self.session = Mock(name="session")
        self.backend.generation_session.return_value = nullcontext(self.session)
        self.session.generate.side_effect = lambda instruction: (
            '{"subject": "observed subject", "colors": "blue"}'
            if instruction.diagnostic_stage.startswith("evidence:") else "  final prompt  "
        )
        self.stack.enter_context(patch.object(core, "create_backend", return_value=self.backend))
        self.stack.enter_context(patch.object(core, "resolve_director_config", return_value=({}, None)))
        self.stack.enter_context(patch.object(core, "debug_prompts_enabled", return_value=False))
        self.cache_get = self.stack.enter_context(patch.object(core, "get_cached_evidence", return_value=None))
        self.stack.enter_context(patch.object(core, "cache_evidence"))
        self.first = core.EncodedImage("b25l", "image/png", 16, 16)
        self.second = core.EncodedImage("dHdv", "image/png", 16, 16)
        self.service = core.GoatedPrompterService(config={})

    def request(self, source="Image 1", **kwargs):
        return contracts.GoatedPrompterRequest(
            idea="a portrait", image=self.first, image_2=self.second,
            reference_map={key: source for key, _ in reference_map.REFERENCE_ATTRIBUTES},
            **kwargs,
        )

    def test_only_selected_source_is_validated_and_analyzed(self):
        for source, image in (("Image 1", self.first), ("Image 2", self.second)):
            with self.subTest(source=source):
                self.backend.validate_vision_input.reset_mock()
                self.session.reset_mock()
                request = self.request(source)
                with patch.object(core, "resolve_reference_map", wraps=core.resolve_reference_map) as resolve:
                    result = self.service.generate(request)
                self.assertIs(resolve.call_args.args[0], request)

                resolve.assert_called_once()
                self.backend.validate_vision_input.assert_called_once_with(image)
                self.assertEqual(self.session.generate.call_count, 2)
                analysis, final = [entry.args[0] for entry in self.session.generate.call_args_list]
                self.assertEqual(analysis.image_label, source)
                self.assertIn(source.upper(), analysis.to_messages()[-1]["content"][0]["text"])
                self.assertTrue(all(item.source == source for item in final.reference_map.attributes))
                self.assertIsNone(final.image)
                self.assertIsNone(final.image_2)
                self.assertEqual(final.diagnostic_context["image_references"], 2)
                self.assertEqual(result.prompt, "final prompt")
                self.assertEqual(result.backend_name, "test-backend")
                self.assertEqual(result.prompt_model, request.selected_prompt_model)
                self.assertEqual(result.director_profile, "")
                self.assertEqual(result.director_preset, final.director_preset)
                self.assertEqual(self.session.validate_instruction.call_args_list, [call(analysis), call(final)])
        self.assertEqual(self.backend.generation_session.call_count, 2)
        self.backend.generate.assert_not_called()

    def test_checkpoints_surround_each_model_call(self):
        events = []
        self.session.generate.side_effect = lambda instruction: (
            events.append("model") or ('{"subject": "observed"}'
            if instruction.diagnostic_stage.startswith("evidence:") else "final prompt")
        )
        service = core.GoatedPrompterService(config={}, checkpoint=lambda: events.append("checkpoint"))
        service.generate(self.request("Blend"))
        self.assertEqual(events, ["checkpoint", "checkpoint", "model", "checkpoint",
                                  "checkpoint", "model", "checkpoint", "checkpoint", "model", "checkpoint"])

    def test_blend_analyzes_both_sources(self):
        request = self.request()
        request.reference_map["colors"] = "Blend"
        result = self.service.generate(request)
        self.assertEqual(self.backend.validate_vision_input.call_count, 2)
        instructions = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertEqual([item.image_label for item in instructions[:-1]], ["Image 1", "Image 2"])
        self.assertEqual(len(instructions), 3)
        self.assertEqual(result.instruction.resolved_scene.source_for("colors"), "Blend")
        self.assertIn("Image 2 evidence: blue", result.instruction.resolved_scene.value_for("colors"))

    def test_auto_resolution_keeps_both_connected_sources(self):
        result = self.service.generate(replace(self.request(), reference_map=None))
        self.assertEqual(self.backend.validate_vision_input.call_count, 2)
        self.assertEqual(result.instruction.reference_map.source_for("subject"), "Image 1")
        self.assertEqual(result.instruction.reference_map.source_for("colors"), "Image 2")

    def test_all_user_sources_need_no_image_work(self):
        resolved = reference_map.ResolvedReferenceMap(tuple(
            reference_map.ResolvedReferenceAttribute(key, label, "User Prompt", False, "explicit user transformation")
            for key, label in reference_map.REFERENCE_ATTRIBUTES
        ))
        with patch.object(core, "resolve_reference_map", return_value=resolved):
            result = self.service.generate(self.request())
        self.backend.validate_vision_input.assert_not_called()
        self.cache_get.assert_not_called()
        self.session.generate.assert_called_once()
        self.assertIs(result.instruction.reference_map, resolved)
        self.assertIsNone(result.instruction.image)

    def test_text_only_assembly_ignores_images_map_and_scene(self):
        request = self.request()
        scene = Mock()
        with patch.object(core, "resolve_reference_map") as resolve:
            instruction = core.assemble_instruction(request, resolved_scene=scene, text_only=True)
            expected = core.assemble_instruction(replace(request, image=None, image_2=None), text_only=True)
        self.assertEqual(instruction, expected)
        self.assertIsNone(instruction.resolved_scene)
        self.assertIsNone(instruction.reference_map)
        self.assertEqual(instruction.user_message, "a portrait")
        self.assertNotIn("VISUAL GROUNDING", instruction.system_message)
        scene.compiler_input.assert_not_called()
        resolve.assert_not_called()
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            core.assemble_instruction(replace(request, idea=" "), resolved_scene=scene, text_only=True)

    def test_text_generation_contracts(self):
        for text_only in (False, True):
            with self.subTest(text_only=text_only):
                self.session.reset_mock()
                request = self.request() if text_only else contracts.GoatedPrompterRequest(idea="a portrait")
                generate = self.service.generate_text_only if text_only else self.service.generate
                result = generate(request)
                self.assertEqual(result.prompt, "final prompt")
                self.assertEqual(result.instruction.diagnostic_stage, "final")
                self.assertEqual(result.instruction.diagnostic_context["evidence_sha256"], "NONE")
                self.assertIsNone(result.instruction.image)
                self.session.generate.assert_called_once_with(result.instruction)
                self.session.validate_instruction.assert_called_once_with(result.instruction)
        self.backend.validate_vision_input.assert_not_called()
        self.cache_get.assert_not_called()
        with self.assertRaisesRegex(ValueError, "Enter a text prompt first"):
            self.service.generate_text_only(replace(self.request(), idea=""))

    def test_control_precedence_across_generation_paths(self):
        for path in ("text_only", "no_image", "raw_reference", "resolved_reference", "linked_reference"):
            for mode, director in (("Dataset Caption", "Video Director"), ("Enhance", "Maximum Detail Director")):
                for length in ("Short", "Maximum Detail"):
                    with self.subTest(path=path, mode=mode, director=director, length=length):
                        request = replace(self.request(), mode=mode, director_preset=director,
                                          prompt_length=length, creativity="Strict")
                        if path == "no_image":
                            request = replace(request, image=None, image_2=None, reference_map=None)
                        if path == "linked_reference":
                            request = replace(request, linked_references=True)
                        if path in {"resolved_reference", "linked_reference"}:
                            instruction = self.service.generate(request).instruction
                        else:
                            instruction = core.assemble_instruction(request, text_only=path == "text_only")
                        message = instruction.system_message
                        self.assertEqual(message.count(prompting_base.SETTINGS_PRECEDENCE), 1)
                        self.assertNotIn("MODE, DETAIL, AND DIRECTOR RESPONSIBILITIES", message)
                        self.assertIn(core.get_mode_adapter(mode), message)
                        self.assertIn(core.get_director_preset(director).instructions, message)
                        self.assertIn(core._LENGTH_ADAPTERS[length], message)
                        self.assertIsNone(instruction.max_tokens)
                        self.assertTrue(instruction.unlimited_tokens)
                        # Without reference images or evidence, reference priorities do not apply.
                        contract = (core.TEXT_ONLY_PRIORITY_CONTRACT if path in {"text_only", "no_image"} else
                                    core.LINKED_PRIORITY_CONTRACT if path == "linked_reference" else
                                    core.PRIORITY_CONTRACT)
                        self.assertIn(contract, message)
                        if path == "text_only":
                            # The Director outranks creativity, length and Mode when they compete.
                            self.assertLess(contract.index("Director behavior"), contract.index("prompt-length settings"))
                            self.assertLess(contract.index("Director behavior"), contract.index("Selected Mode"))

    def test_edited_director_remains_subject_to_control_contract(self):
        request = replace(self.request(), mode="Dataset Caption", prompt_length="Short",
                          system_prompt_override="Always write a long temporal video prompt.")
        instruction = core.assemble_instruction(request, text_only=True)
        self.assertIn(request.system_prompt_override, instruction.system_message)
        self.assertIn(prompting_base.SETTINGS_PRECEDENCE, instruction.system_message)
        self.assertLess(instruction.system_message.index(prompting_base.SETTINGS_PRECEDENCE),
                        instruction.system_message.index(request.system_prompt_override))

    def test_empty_backend_output_still_fails(self):
        self.session.generate.side_effect = None
        self.session.generate.return_value = "  "
        with self.assertRaisesRegex(RuntimeError, "empty prompt"):
            self.service.generate(contracts.GoatedPrompterRequest(idea="portrait"))

    def test_qwen21_generation_returns_plain_text_from_legacy_json(self):
        self.session.generate.side_effect = None
        self.session.generate.return_value = (
            '{"rewritten_prompt":"A warm photograph of a red bicycle.",'
            '"wh_ratio":"3:2"}'
        )
        result = self.service.generate(contracts.GoatedPrompterRequest(idea="red bicycle", target_model="Qwen2.1"))
        self.assertEqual(result.prompt, "A warm photograph of a red bicycle.")
        self.session.generate.return_value = '{"rewritten_prompt":'
        with self.assertRaisesRegex(RuntimeError, "invalid prompt"):
            self.service.generate(contracts.GoatedPrompterRequest(idea="red bicycle", target_model="Qwen2.1"))

    def test_qwen21_plain_text_works_at_every_detail_level(self):
        self.session.generate.side_effect = None
        self.session.generate.return_value = 'A red bicycle beside a sign reading "你好".'
        for length in ("Short", "Medium", "Detailed", "Maximum Detail", "Maximum"):
            for generate in (self.service.generate, self.service.generate_text_only):
                with self.subTest(length=length, path=generate.__name__):
                    self.session.reset_mock()
                    result = generate(contracts.GoatedPrompterRequest(idea="red bicycle", target_model="Qwen2.1", prompt_length=length))
                    self.assertEqual(result.prompt, self.session.generate.return_value)
                    self.assertIsNone(result.instruction.max_tokens)
                    self.assertTrue(result.instruction.unlimited_tokens)
                    self.assertIn(core._LENGTH_ADAPTERS[length], result.instruction.system_message)
                    self.session.generate.assert_called_once()

    def test_qwen21_text_and_edit_keep_task_guidance_but_request_plain_output(self):
        text = self.service.assemble(contracts.GoatedPrompterRequest(idea="a poster", target_model="Qwen2.1"))
        self.assertIn('Return only the complete plain prompt text', text.system_message)
        self.assertNotIn('Qwen Image 2.1 image-editing rewrite', text.system_message)
        self.assertIsNone(text.max_tokens)
        self.assertTrue(text.unlimited_tokens)
        edit = self.service.assemble(self.request("Image 2", target_model="Qwen2.1"))
        self.assertIn('Qwen Image 2.1 image-editing rewrite', edit.system_message)
        self.assertNotIn('Qwen Image 2.1 text-to-image rewrite', edit.system_message)
        self.assertIn('Available source tags: <image2>', edit.system_message)
        self.assertNotIn('Available source tags: <image1>', edit.system_message)
        text_only = self.service.assemble(self.request(target_model="Qwen2.1"), text_only=True)
        self.assertIn('Return only the complete plain prompt text', text_only.system_message)

    def test_qwen21_official_edit_payload_survives_evidence_compilation(self):
        expected = '{"rewritten_prompt":"Change the sky in the image to sunset.","wh_ratio":"","ratio_follow":"<image2>"}'
        self.session.generate.side_effect = lambda instruction: (
            '{"subject":"observed person"}' if instruction.diagnostic_stage.startswith("evidence:") else expected)
        result = self.service.generate(self.request("Image 2", target_model="Qwen2.1"))
        self.assertEqual(result.prompt, json.loads(expected)["rewritten_prompt"])
        self.assertIsNone(result.instruction.image)
        self.assertIsNotNone(result.instruction.resolved_scene)
        self.assertIn('IMAGE EDITING', result.instruction.system_message)
        self.assertEqual(self.session.generate.call_count, 2)
        self.assertTrue(all(call.args[0].unlimited_tokens and call.args[0].max_tokens is None
                            for call in self.session.generate.call_args_list))

    def test_qwen21_all_off_uses_t2i_and_legacy_empty_field_is_removed_losslessly(self):
        self.session.generate.side_effect = None
        self.session.generate.return_value = json.dumps({"rewritten_prompt": 'A sign reads "你好".', "wh_ratio": "3:2", "ratio_follow": ""})
        result = self.service.generate(self.request("Off", linked_references=True, target_model="Qwen2.1"))
        self.assertEqual(result.prompt, 'A sign reads "你好".')
        self.backend.validate_vision_input.assert_not_called()
        self.assertIn('TEXT TO IMAGE', result.instruction.system_message)

    def test_qwen21_format_repair_uses_same_session_and_original_request(self):
        expected = 'A red bicycle.'
        self.session.generate.side_effect = ['{"rewritten_prompt":', expected]
        result = self.service.generate(contracts.GoatedPrompterRequest(idea="red bicycle", target_model="Qwen2.1"))
        self.assertEqual(result.prompt, expected)
        first, retry = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertTrue(retry.user_message.startswith(first.user_message))
        self.assertIn("LOCAL REPAIR CONTRACT", retry.user_message)
        self.assertIn('FORMAT CORRECTION', retry.system_message)
        self.assertEqual(retry.diagnostic_stage, 'final:format_retry')
        self.assertTrue(first.unlimited_tokens and retry.unlimited_tokens)
        self.backend.generation_session.assert_called_once()

    def test_qwen21_repair_preserves_selected_image_evidence(self):
        expected = 'Change the sky in the image.'
        self.session.generate.side_effect = ['{"subject":"observed person"}', '{"rewritten_prompt":[]}', expected]
        result = self.service.generate(self.request("Image 2", target_model="Qwen2.1"))
        self.assertEqual(result.prompt, expected)
        calls = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertEqual(len(calls), 3)
        self.assertIs(calls[1].resolved_scene, calls[2].resolved_scene)
        self.backend.validate_vision_input.assert_called_once()

    def test_qwen21_cancellation_stops_format_retry(self):
        class Cancelled(Exception):
            pass
        checkpoints = []
        def checkpoint():
            checkpoints.append(True)
            if len(checkpoints) == 4:
                raise Cancelled()
        self.session.generate.side_effect = None
        self.session.generate.return_value = '{"rewritten_prompt":"Incomplete'
        with self.assertRaises(Cancelled):
            core.GoatedPrompterService(config={}, checkpoint=checkpoint).generate(
                contracts.GoatedPrompterRequest(idea="red bicycle", target_model="Qwen2.1"))
        self.session.generate.assert_called_once()

    def test_image_order_does_not_hash_when_debug_disabled(self):
        with patch.object(core, "_image_descriptor") as descriptor:
            core._log_image_order(self.request())
        descriptor.assert_not_called()


class LinkedCoreTests(unittest.TestCase):
    setUp = CoreTests.setUp
    request = CoreTests.request

    def linked_request(self, **kwargs):
        return replace(self.request("Off"), linked_references=True, **kwargs)

    def test_all_eleven_rows_are_independent_strict_sources(self):
        for key, _label in reference_map.REFERENCE_ATTRIBUTES:
            for source in ("Off", "Image 1", "Image 2", "Image 3", "Image 4", "Blend"):
                with self.subTest(attribute=key, source=source):
                    request = self.linked_request(image_3=object(), image_4=object(),
                        idea="cinematic wearing a coat, replace subject and face, change pose, camera, composition, scene, lighting, colors, mood, materials")
                    request.reference_map[key] = source
                    resolved = reference_map.resolve_reference_map(request)
                    for item in resolved.attributes:
                        self.assertEqual(item.source, source if item.key == key else "Off")
                        self.assertEqual(item.preserve, item.key == key and source != "Off")

    def test_missing_sources_validated_despite_transformations(self):
        for key, _label in reference_map.REFERENCE_ATTRIBUTES:
            request = self.linked_request(idea="cinematic wearing a coat, replace subject and face")
            request.reference_map[key] = "Image 4"
            with self.assertRaisesRegex(ValueError, "Image 4 is not connected"):
                self.service.generate(request)
        self.session.generate.assert_not_called()
        self.backend.validate_vision_input.assert_not_called()

    def test_selected_image_four_only_and_cache_identity(self):
        fourth = core.EncodedImage("Zm91cg==", "image/png", 16, 16)
        request = self.linked_request(image_4=fourth)
        request.reference_map["subject"] = "Image 4"
        result = self.service.generate(request)
        analysis, final = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertEqual(analysis.image_label, "Image 4")
        self.assertIs(analysis.image, fourth)
        self.assertEqual(final.diagnostic_context["image_references"], 3)
        self.assertFalse(reference_map.reference_images(final))
        self.assertEqual(result.instruction.resolved_scene.value_for("subject"), "observed subject")
        self.assertIn("No reference evidence", final.resolved_scene.value_for("face"))
        self.backend.validate_vision_input.assert_called_once_with(fourth)
        self.cache_get.assert_called_once()
        self.assertIn("strict source lock wins", final.system_message)
        self.assertNotIn("explicit current WHAT DO YOU WANT? transformation", final.system_message)

    def test_sparse_blend_uses_all_present_stable_slots(self):
        for fields in (("image_2", "image_4"), ("image", "image_3", "image_4"),
                       ("image", "image_2", "image_3", "image_4")):
            with self.subTest(fields=fields):
                self.session.reset_mock()
                images = {field: core.EncodedImage("Zm91cg==", "image/png", 16, 16) if field in fields else None
                          for field, _ in reference_map.REFERENCE_IMAGE_SLOTS}
                request = self.linked_request(**images)
                request.reference_map["colors"] = "Blend"
                result = self.service.generate(request)
                labels = tuple(reference_map.reference_images(request))
                calls = [entry.args[0] for entry in self.session.generate.call_args_list]
                self.assertEqual([item.image_label for item in calls[:-1]], list(labels))
                self.assertEqual(result.instruction.reference_map.source_labels, labels)
                for _field, label in reference_map.REFERENCE_IMAGE_SLOTS:
                    self.assertEqual(label + " evidence:" in result.instruction.resolved_scene.value_for("colors"), label in labels)
        request = self.linked_request(image=None, image_2=None, image_4=object())
        request.reference_map["subject"] = "Blend"
        with self.assertRaisesRegex(ValueError, "at least two"):
            self.service.generate(request)

    def test_all_off_needs_no_vision_and_rejects_empty_idea(self):
        self.backend.validate_vision_input.side_effect = AssertionError("vision should not be used")
        request = self.linked_request(image_3=object(), image_4=object())
        result = self.service.generate(request)
        self.session.generate.assert_called_once()
        self.backend.validate_vision_input.assert_not_called()
        self.cache_get.assert_not_called()
        self.assertFalse(reference_map.reference_images(result.instruction))
        self.assertNotIn("VISUAL GROUNDING", result.instruction.system_message)
        self.assertTrue(all(not item.preserve for item in result.instruction.reference_map.attributes))
        assembled = core.assemble_instruction(request)
        self.assertFalse(reference_map.reference_images(assembled))
        for method in (self.service.generate, core.assemble_instruction):
            with self.assertRaisesRegex(ValueError, "All reference attributes are Off.*Enter an idea"):
                method(replace(request, idea=""))

    def test_text_only_sanitizes_all_images_linked_and_preserve_flags(self):
        request = self.linked_request(image_3=object(), image_4=object(), preserve_colors=True)
        request.reference_map["mood"] = "Image 4"
        with patch.object(self.service, "_generate", return_value="result") as generate:
            self.assertEqual(self.service.generate_text_only(request), "result")
        sanitized = generate.call_args.args[0]
        self.assertFalse(sanitized.linked_references)
        self.assertFalse(reference_map.reference_images(sanitized))
        self.assertIsNone(sanitized.reference_map)
        self.assertTrue(all(not getattr(sanitized, "preserve_" + key) for key in core._PRESERVATION_ADAPTERS))

    def test_legacy_auto_roles_flags_and_regex_priority_unchanged(self):
        request = replace(self.request("Auto"), image_2_role="Scene")
        resolved = reference_map.resolve_reference_map(request)
        self.assertEqual(resolved.source_for("scene"), "Image 2")
        self.assertTrue(next(item.preserve for item in resolved.attributes if item.key == "face"))
        request = replace(self.request(), idea="cinematic portrait wearing a coat")
        resolved = reference_map.resolve_reference_map(request)
        self.assertEqual(resolved.source_for("outfit"), "User Prompt")
        self.assertEqual(resolved.source_for("mood"), "User Prompt")

    def test_mapping_alias_and_maximum_are_uncapped(self):
        for value in ("Maximum", "Maximum Detail"):
            request = contracts.GoatedPrompterRequest.from_mapping({"idea": "portrait", "linked_references": "true", "prompt_length": value})
            self.assertTrue(request.linked_references)
            self.assertEqual(request.prompt_length, "Maximum Detail")
            instruction = core.assemble_instruction(request)
            self.assertIsNone(instruction.max_tokens)
            self.assertTrue(instruction.unlimited_tokens)
        self.assertFalse(contracts.GoatedPrompterRequest.from_mapping({"linked_references": "false"}).linked_references)
        self.assertFalse(contracts.GoatedPrompterRequest.from_mapping({}).linked_references)
        result = self.service.generate(replace(self.request(), prompt_length="Maximum"))
        analysis, final = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertIsNone(analysis.max_tokens)
        self.assertIsNone(final.max_tokens)
        self.assertTrue(analysis.unlimited_tokens)
        self.assertTrue(final.unlimited_tokens)
        self.assertIn(core._MAXIMUM_DETAIL_GUIDANCE, result.instruction.system_message)
        for length in ("Short", "Medium", "Detailed"):
            self.assertIsNone(core.assemble_instruction(replace(self.request(), prompt_length=length)).max_tokens)

    def test_raw_message_order_and_reference_source_prefix(self):
        images = {field: core.EncodedImage(str(index), "image/png", 16, 16)
                  for index, (field, _label) in enumerate(reference_map.REFERENCE_IMAGE_SLOTS)}
        for family in ("qwen", "gemma"):
            instruction = contracts.PromptInstruction("system", "user", model_family=family, **images)
            parts = instruction.to_messages()[-1]["content"]
            self.assertEqual([part["image_url"]["url"] for part in parts if part["type"] == "image_url"],
                             [image.data_url for image in images.values()])
            for index, (_field, label) in enumerate(reference_map.REFERENCE_IMAGE_SLOTS):
                self.assertIn(label.upper(), parts[index * 2]["text"])
        self.assertEqual(importlib.import_module(f"{PACKAGE}.options.references").REFERENCE_SOURCE_NAMES[:4], ("Auto", "Image 1", "Image 2", "Blend"))

    def test_selected_reference_must_be_a_decoded_upload(self):
        request = replace(self.request(), image=object())
        with self.assertRaisesRegex(ValueError, "decoded uploads"):
            self.service.generate(request)
        self.session.generate.assert_not_called()

    def test_unselected_invalid_reference_does_not_block_generation(self):
        result = self.service.generate(replace(self.request("Image 2"), image=object()))
        self.assertEqual(result.prompt, "final prompt")
        self.backend.validate_vision_input.assert_called_once_with(self.second)


class ImageUtilsTests(unittest.TestCase):
    def test_encoded_upload_exposes_data_url(self):
        image = image_utils.EncodedImage("b25l", "image/png", 16, 16)
        self.assertEqual(image.data_url, "data:image/png;base64,b25l")


if __name__ == "__main__":
    unittest.main()
