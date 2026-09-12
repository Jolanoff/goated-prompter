"""Core orchestration tests without ComfyUI, Pillow, models, or network access."""

from contextlib import ExitStack, nullcontext, redirect_stdout
from dataclasses import replace
import importlib
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch


# Load core without running the node package's ComfyUI route registration.
PACKAGE = "_goated_core_tests"
package = ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "goated_prompter")]
sys.modules[PACKAGE] = package
core = importlib.import_module(f"{PACKAGE}.core")
image_utils = importlib.import_module(f"{PACKAGE}.image_utils")
reference_map = importlib.import_module(f"{PACKAGE}.reference_map")


class CoreTests(unittest.TestCase):
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
        self.encode = self.stack.enter_context(patch.object(
            core, "encode_comfy_image", side_effect=lambda image, **kwargs: core.EncodedImage(
                "b25l" if image is self.first else "dHdv", "image/png", 16, 16,
            ),
        ))
        self.first, self.second = object(), object()
        self.service = core.GoatedPrompterService(config={})

    def request(self, source="Image 1", **kwargs):
        return core.GoatedPrompterRequest(
            idea="a portrait", image=self.first, image_2=self.second,
            reference_map={key: source for key, _ in reference_map.REFERENCE_ATTRIBUTES},
            **kwargs,
        )

    def test_only_selected_source_is_encoded_and_analyzed(self):
        for source, image in (("Image 1", self.first), ("Image 2", self.second)):
            with self.subTest(source=source):
                self.encode.reset_mock()
                self.session.reset_mock()
                request = self.request(source)
                with patch.object(core, "resolve_reference_map", wraps=core.resolve_reference_map) as resolve:
                    result = self.service.generate(request)
                self.assertIs(resolve.call_args.args[0], request)

                resolve.assert_called_once()
                self.encode.assert_called_once_with(image, max_dimension=1344)
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
        self.assertEqual(self.encode.call_count, 2)
        instructions = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertEqual([item.image_label for item in instructions[:-1]], ["Image 1", "Image 2"])
        self.assertEqual(len(instructions), 3)
        self.assertEqual(result.instruction.resolved_scene.source_for("colors"), "Blend")
        self.assertIn("Image 2 evidence: blue", result.instruction.resolved_scene.value_for("colors"))

    def test_auto_resolution_keeps_both_connected_sources(self):
        result = self.service.generate(replace(self.request(), reference_map=None))
        self.assertEqual(self.encode.call_count, 2)
        self.assertEqual(result.instruction.reference_map.source_for("subject"), "Image 1")
        self.assertEqual(result.instruction.reference_map.source_for("colors"), "Image 2")

    def test_all_user_sources_need_no_image_work(self):
        resolved = reference_map.ResolvedReferenceMap(tuple(
            reference_map.ResolvedReferenceAttribute(key, label, "User Prompt", False, "explicit user transformation")
            for key, label in reference_map.REFERENCE_ATTRIBUTES
        ))
        with patch.object(core, "resolve_reference_map", return_value=resolved):
            result = self.service.generate(self.request())
        self.encode.assert_not_called()
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
                request = self.request() if text_only else core.GoatedPrompterRequest(idea="a portrait")
                generate = self.service.generate_text_only if text_only else self.service.generate
                result = generate(request)
                self.assertEqual(result.prompt, "final prompt")
                self.assertEqual(result.instruction.diagnostic_stage, "final")
                self.assertEqual(result.instruction.diagnostic_context["evidence_sha256"], "NONE")
                self.assertIsNone(result.instruction.image)
                self.session.generate.assert_called_once_with(result.instruction)
                self.session.validate_instruction.assert_called_once_with(result.instruction)
        self.encode.assert_not_called()
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
                        self.assertEqual(message.count(core.CONTROL_CONTRACT), 1)
                        self.assertIn("Mode defines the task. Director behavior must not replace that task", message)
                        self.assertIn("Prompt length controls descriptive density", message)
                        self.assertIn("Creativity controls permissible invention", message)
                        self.assertIn(core.get_mode_adapter(mode), message)
                        self.assertIn(core.get_director_preset(director).instructions, message)
                        self.assertIn(core._LENGTH_ADAPTERS[length], message)
                        self.assertEqual(instruction.max_tokens, 3072 if length == "Maximum Detail" else None)
                        contract = (core.TEXT_ONLY_PRIORITY_CONTRACT if path == "text_only" else
                                    core.LINKED_PRIORITY_CONTRACT if path == "linked_reference" else
                                    core.PRIORITY_CONTRACT)
                        self.assertIn(contract, message)
                        if path == "text_only":
                            self.assertLess(contract.index("selected Mode"), contract.index("Director behavior"))
                            self.assertLess(contract.index("prompt-length settings"), contract.index("Director behavior"))

    def test_edited_director_remains_subject_to_control_contract(self):
        request = replace(self.request(), mode="Dataset Caption", prompt_length="Short",
                          system_prompt_override="Always write a long temporal video prompt.")
        instruction = core.assemble_instruction(request, text_only=True)
        self.assertIn(request.system_prompt_override, instruction.system_message)
        self.assertIn(core.CONTROL_CONTRACT, instruction.system_message)
        self.assertIn("edited Director working copies", instruction.system_message)

    def test_empty_backend_output_still_fails(self):
        self.session.generate.side_effect = None
        self.session.generate.return_value = "  "
        with self.assertRaisesRegex(RuntimeError, "empty prompt"):
            self.service.generate(core.GoatedPrompterRequest(idea="portrait"))

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
        self.encode.assert_not_called()

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
        self.encode.assert_not_called()
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
        self.encode.assert_not_called()
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

    def test_mapping_alias_and_maximum_only_final_budget(self):
        for value in ("Maximum", "Maximum Detail"):
            request = core.GoatedPrompterRequest.from_mapping({"idea": "portrait", "linked_references": "true", "prompt_length": value})
            self.assertTrue(request.linked_references)
            self.assertEqual(request.prompt_length, "Maximum Detail")
            self.assertEqual(core.assemble_instruction(request).max_tokens, 3072)
        self.assertFalse(core.GoatedPrompterRequest.from_mapping({"linked_references": "false"}).linked_references)
        self.assertFalse(core.GoatedPrompterRequest.from_mapping({}).linked_references)
        result = self.service.generate(replace(self.request(), prompt_length="Maximum"))
        analysis, final = [entry.args[0] for entry in self.session.generate.call_args_list]
        self.assertIsNone(analysis.max_tokens)
        self.assertEqual(final.max_tokens, 3072)
        self.assertIn(core._MAXIMUM_DETAIL_GUIDANCE, result.instruction.system_message)
        for length in ("Short", "Medium", "Detailed"):
            self.assertIsNone(core.assemble_instruction(replace(self.request(), prompt_length=length)).max_tokens)

    def test_raw_message_order_and_node_schema_prefix(self):
        images = {field: core.EncodedImage(str(index), "image/png", 16, 16)
                  for index, (field, _label) in enumerate(reference_map.REFERENCE_IMAGE_SLOTS)}
        for family in ("qwen", "gemma"):
            instruction = core.PromptInstruction("system", "user", model_family=family, **images)
            parts = instruction.to_messages()[-1]["content"]
            self.assertEqual([part["image_url"]["url"] for part in parts if part["type"] == "image_url"],
                             [image.data_url for image in images.values()])
            for index, (_field, label) in enumerate(reference_map.REFERENCE_IMAGE_SLOTS):
                self.assertIn(label.upper(), parts[index * 2]["text"])
        nodes = importlib.import_module(f"{PACKAGE}.comfy_node")
        schema = nodes.GoatedPrompter.INPUT_TYPES()
        self.assertEqual(reference_map.REFERENCE_SOURCE_NAMES[:4], ("Auto", "Image 1", "Image 2", "Blend"))
        self.assertEqual(list(schema["optional"]), ["image", "image_2", "image_3", "image_4", "linked_references"])
        self.assertFalse(schema["optional"]["linked_references"][1]["default"])

    def test_node_appended_kwargs_reach_request_without_cached_shortcut(self):
        nodes = importlib.import_module(f"{PACKAGE}.comfy_node")
        required = nodes.GoatedPrompter.INPUT_TYPES()["required"]
        values = {key: specification[1]["default"] for key, specification in required.items()}
        values.update(idea="portrait", generated_prompt="stale cached result", image_3=object(),
                      image_4=object(), linked_references=True, reference_subject_source="Image 4")
        with patch.object(nodes, "GoatedPrompterService") as service:
            service.return_value.generate.return_value.prompt = "fresh"
            result = nodes.GoatedPrompter().direct(**values)
        self.assertEqual(result["result"], ("fresh",))
        request = service.return_value.generate.call_args.args[0]
        self.assertTrue(request.linked_references)
        self.assertIs(request.image_3, values["image_3"])
        self.assertIs(request.image_4, values["image_4"])
        self.assertEqual(request.reference_map["subject"], "Image 4")


class ImageUtilsTests(unittest.TestCase):
    def test_batch_is_sliced_before_cpu_transfer(self):
        batch = Mock(ndim=4, shape=(8, 16, 16, 3))
        first = Mock(ndim=3, shape=(16, 16, 3))
        batch.__getitem__ = Mock(return_value=first)
        image = Mock()
        image.detach.return_value = batch
        # Stop at transfer so no torch, numpy, or Pillow implementation is needed.
        first.to.side_effect = RuntimeError("stop at transfer")
        with patch.dict(sys.modules, {"PIL": SimpleNamespace(Image=Mock())}):
            with self.assertRaises(image_utils.ImageEncodingError):
                image_utils.encode_comfy_image(image)
        batch.__getitem__.assert_called_once_with(0)
        batch.to.assert_not_called()
        first.to.assert_called_once_with(device="cpu")


if __name__ == "__main__":
    unittest.main()
