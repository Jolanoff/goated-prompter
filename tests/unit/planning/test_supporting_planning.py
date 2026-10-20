"""Optional planning contracts; scripted outputs test integration, not LLM quality."""

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import GoatedPrompterBackend, BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import GoatedPrompterService, assemble_instruction
from goated_prompter.features.builder.evidence import clear_evidence_cache
from goated_prompter.image_utils import EncodedImage
from goated_prompter.planning.complexity import needs_planning
from goated_prompter.planning.constraints import compile_request
from goated_prompter.planning.scene_plan import PromptScenePlan
from goated_prompter.planning.scene_planner import scene_planning_instruction
from goated_prompter.planning.validation import validate_plan
from goated_prompter.presets import DIRECTOR_PRESETS
from goated_prompter.options.targets import TARGET_MODEL_NAMES
from tests.helpers import enter_context
from tests.support.paths import ROOT


HOOP = ("a performer suspended sideways from a hoop, one knee hooked over the top, "
        "opposite leg extended downward, torso twisted toward the viewer")
PAIR = "two people counterbalancing each other, holding one hand while leaning in opposite directions"
HOOP_PLAN = {"primary_action": "Suspended sideways from the hoop", "subjects": ["one performer"],
    "pose_detail": "One knee hooked over the top provides support/contact; opposite leg extends downward; torso twists toward the viewer.",
    "important_visibility": ["hooked knee contact with hoop", "opposite extended leg and torso twist"]}
PAIR_PLAN = {"subjects": ["person A", "person B"], "primary_action": "counterbalance each other",
    "interactions": ["A and B grip one shared hand; lean in opposite directions, tension through their grip stabilizing the opposing weight."],
    "pose_detail": "Each person's feet support their own weight; their connected hands supply reciprocal balance."}


class ScriptedBackend(GoatedPrompterBackend):
    name = "planning-test"
    supports_vision = True

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.sessions = self.exits = 0

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        try:
            yield self
        finally:
            self.exits += 1

    def generate(self, instruction):
        self.calls.append(instruction)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class SupportingPlanningTests(unittest.TestCase):
    def test_direct_constraint_repair_is_low_sampling_and_never_replaces_the_user_action(self):
        result, backend = self.builder(GoatedPrompterRequest(idea="A person runs beside a bus. no hats", planning_mode="Direct"),
            "A person runs beside a bus wearing a red hat.", "A person runs beside a bus.")
        self.assertEqual(result.prompt, "A person runs beside a bus.")
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["final", "final:constraint_retry"])
        self.assertEqual((backend.calls[1].temperature, backend.calls[1].top_p), (.25, .85))
        self.assertTrue(backend.calls[1].user_message.startswith(backend.calls[0].user_message))
        self.assertIn("LOCAL REPAIR CONTRACT", backend.calls[1].user_message)

    def setUp(self):
        directory = enter_context(self, tempfile.TemporaryDirectory())
        enter_context(self, patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": directory}))
        clear_evidence_cache()
        self.addCleanup(clear_evidence_cache)

    def builder(self, request, *responses, checkpoint=None):
        backend = ScriptedBackend(*responses)
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
            result = GoatedPrompterService(config={"backend": "mock"}, checkpoint=checkpoint).generate(request)
        return result, backend

    def test_default_modes_and_bad_modes(self):
        self.assertEqual(GoatedPrompterRequest(idea="apple").planning_mode, "Auto")
        self.assertEqual(GoatedPrompterRequest.from_mapping({"idea": "apple", "planning_mode": "Direct"}).planning_mode, "Direct")
        with self.assertRaises(ValueError):
            GoatedPrompterRequest(idea="apple", planning_mode="maybe")

    def test_direct_messages_match_pre_feature_golden_for_every_target(self):
        # SHA256 of to_messages() from HEAD core.py before this feature. Isolated
        # built-in Directors ensure saved custom presets cannot affect fixtures.
        # Anima alone uses the updated compact hybrid adapter and flat-prefix format.
        # Regenerated for the slimmed Builder prompt, per-target guidance, library templates and no built-in examples.
        # Updated for the merged Z-Image target and the Anima, FLUX.2 Klein, Qwen Image (original) and Ideogram4 adapters.
        # Updated for the Style/Director split: the precedence text, renamed Directors and medium-neutral adapters.
        # Updated again when each guide was limited to its own job and the Style moved after the library templates.
        # Updated for one precedence rule, emphasis-only Directors and target layouts that templates replace.
        # Updated for the two-or-more-people rule and the Length guide that details the subjects first.
        # Updated when Creativity became the only owner of how much is invented.
        # Updated for show-don't-tell: the request's abstract words become visible signs.
        golden = {
            "Generic": "781f7d8811215dd53637c320a7217859838e4fe20f1f19dbd3d49b4b3a2e9a76",
            "Anima": "a3c9631152d07d8ad21d39794641c13118d51c009c41bda85403695534477e80",
            "Krea 2": "3186cf2417b4ce9b33c94f6d3a853238e6746f5e32666df42683badc46d24ff8",
            "FLUX.2 Klein": "0185c9f19c3e28264502cdad24b3f953f0213a55aeb7e94396259ce41923ac61",
            "Z-Image": "e3662b2be7d29e90d343070ec3f3bbd2ba38937057236e8d8d15ee2776292c82",
            "Qwen Image (original)": "2c34c26cfcfea5b06d224f5404c9a97fc35b90be60db10c0e0d5b9c95297872a",
            "Qwen Image 2.1": "26bec9d57854d4f5de589ecfb4fa75f2740f16ef8efde4df2bfcda6b54ca0556",
            "MiniMax H3": "7086d0ade15d77e6e1da7821025ab6a5860e233f68ca0795ecc75d9ac98530e9",
            "LTX 2.5": "f583a882752c561e1cf246a4f071d0e96d9a3a2b2e61cca8b2fd0a2829b91e60",
            "Ideogram4": "b1ca4371bb23acdac8476d268b682ff4ecf39a83703345316420f0406eb57835"}
        self.assertEqual(set(golden), set(TARGET_MODEL_NAMES))
        for target, digest in golden.items():
            with self.subTest(target=target):
                request = GoatedPrompterRequest(idea='Two people hold one hand and lean in opposite directions. A placard reads "BALANCE".',
                    target_model=target, creativity="Strict", prompt_length="Medium", planning_mode="Direct")
                messages = json.dumps(assemble_instruction(request).to_messages(), ensure_ascii=False, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(messages.encode()).hexdigest(), digest)

    def test_direct_complex_has_only_final_call_and_no_planning_contract(self):
        request = GoatedPrompterRequest(idea=HOOP + ", no hat", planning_mode="Direct")
        result, backend = self.builder(request, "Final prompt")
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.instruction.to_messages(), assemble_instruction(request).to_messages())
        self.assertNotIn("SUPPORTING INTERPRETATION", result.instruction.system_message)
        self.assertNotIn("no hat", result.instruction.user_message)
        self.assertIn('"forbidden": ["hat"]', result.instruction.system_message)
        self.assertEqual(result.planning_status, "direct")

    def test_auto_simple_is_exact_direct_without_added_call(self):
        text = "red apple on a wooden table"
        request = GoatedPrompterRequest(idea=text)
        result, backend = self.builder(request, "A red apple rests on a wooden table.")
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.instruction.to_messages(), assemble_instruction(replace(request, planning_mode="Direct")).to_messages())

    def test_detector_uses_structure_not_length_or_literal_text(self):
        for text in (HOOP, PAIR, "two wrestlers mid-throw"):
            self.assertTrue(needs_planning(text), text)
        for text in ("red apple on a wooden table", "A car drives down a rainy street.",
                     'a sign reads "two wrestlers mid-throw"', "red apple with a richly textured red peel " * 20):
            self.assertFalse(needs_planning(text), text)

    def test_auto_pose_one_plan_keeps_mechanics_and_original_request(self):
        request = GoatedPrompterRequest(idea=HOOP, creativity="Strict")
        result, backend = self.builder(request, json.dumps(HOOP_PLAN), HOOP)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["builder:scene_planning", "final"])
        self.assertEqual((backend.sessions, backend.exits), (1, 1))
        self.assertEqual(result.planning_status, "planned")
        self.assertEqual(result.instruction.user_message, HOOP)
        for phrase in ("knee hooked", "leg extends downward", "torso twists", "support/contact"):
            self.assertIn(phrase, result.instruction.system_message)
        self.assertEqual(result.prompt, HOOP)
        self.assertEqual(backend.calls[0].hard_max_tokens, 1200)
        self.assertTrue(backend.calls[1].unlimited_tokens)
        self.assertEqual(backend.calls[1].temperature, .3, "The writer's temperature follows Creativity (Strict).")
        self.assertIn("Creativity — Strict", backend.calls[0].system_message, "The planner's staging follows Creativity too.")

    def test_pair_plan_keeps_separate_roles_and_shared_contact(self):
        result, backend = self.builder(GoatedPrompterRequest(idea=PAIR), json.dumps(PAIR_PLAN), PAIR)
        self.assertIn("reciprocal balance", result.instruction.system_message)
        self.assertIn("grip one shared hand", result.instruction.system_message)
        self.assertEqual(json.loads(backend.calls[0].user_message)["user_request"], PAIR)

    def test_always_simple_adds_exactly_one_call(self):
        result, backend = self.builder(GoatedPrompterRequest(idea="apple", planning_mode="Always"),
            '{"staging":"apple resting on the supplied surface"}', "Apple")
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result.planning_status, "planned")

    def test_auto_failures_use_exact_original_direct_input(self):
        for response in ("bad JSON", '[]', '{"primary_action":42}', '{"primary_action":"x","primary_action":"y"}',
                         TimeoutError("timeout"), BackendGenerationError("model failed"), RuntimeError("engine failed")):
            with self.subTest(response=response), self.assertLogs("goated_prompter.planning.scene_planner", level="WARNING"):
                request = GoatedPrompterRequest(idea=HOOP + ", no hat")
                result, backend = self.builder(request, response, "Final prompt")
                self.assertEqual(result.planning_status, "fallback")
                self.assertEqual(len(backend.calls), 2)
                self.assertEqual(result.instruction.to_messages(), assemble_instruction(replace(request, planning_mode="Direct")).to_messages())

    def test_always_failure_does_not_write_final(self):
        backend = ScriptedBackend("bad JSON")
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend), self.assertRaisesRegex(BackendGenerationError, "Required scene planning failed"):
            GoatedPrompterService(config={"backend": "mock"}).generate(GoatedPrompterRequest(idea="apple", planning_mode="Always"))
        self.assertEqual(len(backend.calls), 1)

    def test_cancellation_during_planning_is_not_fallback(self):
        class Cancelled(Exception):
            pass
        backend = ScriptedBackend(json.dumps(HOOP_PLAN))
        def checkpoint():
            if backend.calls:
                raise Cancelled()
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend), self.assertRaises(Cancelled):
            GoatedPrompterService(config={"backend": "mock"}, checkpoint=checkpoint).generate(GoatedPrompterRequest(idea=HOOP))
        self.assertEqual(len(backend.calls), 1)

    def test_compiler_separates_high_confidence_rules_and_preserves_literals(self):
        compiled = compile_request('woman with short black hair, no hat, outfit can change, a sign reads "NO HAT!"')
        self.assertEqual(compiled.required, ("short black hair",))
        self.assertEqual(compiled.forbidden, ("hat",))
        self.assertEqual(compiled.variable, ("outfit",))
        self.assertIn('"NO HAT!"', compiled.positive_request)
        self.assertNotIn("no hat", compiled.writer_request())
        self.assertNotIn("outfit can change", compiled.writer_request())

    def test_compiler_defers_negative_concepts_names_and_conditional_rules(self):
        for text in ("no smoking sign", "portrait, No Man's Land", "portrait, no smoking sign", "portrait, no hat unless indoors",
                     "portrait, no hat is allowed", 'portrait, dialogue "No, don’t!"', "portrait, no hat and holding a cat"):
            compiled = compile_request(text)
            self.assertEqual(compiled.positive_request, text, text)
            self.assertFalse(compiled.forbidden, text)

    def test_compiled_exclusions_do_not_reach_final_as_raw_negative_commands(self):
        request = GoatedPrompterRequest(idea=HOOP + ", no hat, outfit can change")
        result, _ = self.builder(request, json.dumps(HOOP_PLAN), HOOP)
        combined = result.instruction.system_message + result.instruction.user_message
        self.assertNotIn("no hat", combined)
        self.assertNotIn("outfit can change", combined)
        self.assertIn('"forbidden": ["hat"]', combined)

    def test_workflow_rules_reach_planner_and_safe_exclusions_are_silent(self):
        request = GoatedPrompterRequest(idea="performer", custom_instructions=HOOP + "; no hat; preserve the requested face")
        result, backend = self.builder(request, json.dumps(HOOP_PLAN), HOOP)
        self.assertEqual(result.planning_status, "planned")
        context = json.loads(backend.calls[0].user_message)
        self.assertIn(HOOP, context["user_workflow_rules"])
        self.assertEqual(context["constraints"]["forbidden"], ["hat"])
        self.assertIn("preserve the requested face", result.instruction.system_message)
        self.assertNotIn("no hat", result.instruction.system_message + result.instruction.user_message)

    def test_compiler_never_drops_a_positive_fact_in_a_mixed_clause(self):
        text = "a person; short black hair and no hat"
        self.assertEqual(compile_request(text).positive_request, text)
        text = "two dancers, do not use source wardrobe, source environment or source audio"
        self.assertEqual(compile_request(text).positive_request, text)
        self.assertFalse(compile_request(text).forbidden)

    def test_compact_scalar_details_normalize_without_loosening_other_types(self):
        compiled = compile_request(HOOP)
        payload = {"primary_action": "Suspended sideways from the hoop", "subjects": "one performer"}
        self.assertEqual(validate_plan(json.dumps(payload), compiled)["subjects"], ["one performer"])
        with self.assertRaises(ValueError):
            validate_plan(json.dumps({**payload, "subjects": [{"id": "invented object"}]}), compiled)

    def test_empty_image_only_direction_does_not_invent_requested_constraints(self):
        self.assertEqual(compile_request("", has_context=True).writer_request(), "")
        compiled = compile_request("no hat", has_context=True)
        self.assertIn("preserved reference scene", compiled.writer_request())
        self.assertNotIn("no hat", compiled.writer_request())

    def test_plans_cannot_reintroduce_compiled_exclusion_prose_except_literal_text(self):
        compiled = compile_request("a person; no hat")
        for wording in ("person with no hat", "person without a hat", "hat-free person"):
            with self.assertRaisesRegex(ValueError, "verbalized"):
                validate_plan(json.dumps({"staging": wording}), compiled)
        compiled = compile_request('a person, no hat, a sign reads "NO HAT!"')
        self.assertEqual(compiled.forbidden, ("hat",))
        self.assertTrue(validate_plan(json.dumps({"staging": 'person beside a sign that reads "NO HAT!"'}), compiled))

    def test_redundant_standalone_absence_notes_are_removed_without_removing_staging(self):
        compiled = compile_request(HOOP + ", no hat")
        payload = {**HOOP_PLAN, "important_visibility": ["No hat is present on the performer.", "hooked knee contact"]}
        details = validate_plan(json.dumps(payload), compiled)
        self.assertEqual(details["important_visibility"], ["hooked knee contact"])
        self.assertEqual(details["pose_detail"], HOOP_PLAN["pose_detail"])
        with self.assertRaises(ValueError):
            validate_plan(json.dumps({**payload, "important_visibility": ["no hat and both hands visible"]}), compiled)

    def test_compiled_facts_are_not_duplicated_in_writer_user_prose(self):
        request = GoatedPrompterRequest(idea=HOOP + ", no hat")
        result, _ = self.builder(request, json.dumps(HOOP_PLAN), HOOP)
        self.assertNotIn("hat", result.instruction.user_message)
        self.assertEqual(result.instruction.system_message.count('"forbidden": ["hat"]'), 1)

    def test_only_provable_same_clause_world_axis_conflicts_are_rejected(self):
        compiled = compile_request(HOOP)
        with self.assertRaisesRegex(ValueError, "orientation"):
            validate_plan('{"pose_detail":"The leg extends straight down, parallel to the ground."}', compiled)
        for description in ("The leg extends straight down. An arm is parallel to the ground.",
                            "The leg extends straight down and the arm is parallel to the ground.",
                            "The leg extends straight down while the arm is parallel to the ground.",
                            "The leg may be vertically down or parallel to the ground depending on the moment.",
                            "The vertical leg appears parallel to the ground in the tilted camera frame."):
            self.assertTrue(validate_plan(json.dumps({"pose_detail": description}), compiled))

    def test_target_director_creativity_length_adapters_remain_unchanged(self):
        compiled = compile_request(PAIR + '. A placard reads "BALANCE".')
        plan = PromptScenePlan(validate_plan(json.dumps(PAIR_PLAN), compiled), compiled)
        for target in TARGET_MODEL_NAMES:
            for creativity in ("Strict", "Dice"):
                for director in DIRECTOR_PRESETS[:3]:
                    with self.subTest(target=target, creativity=creativity, director=director.id):
                        request = GoatedPrompterRequest(idea=compiled.original, target_model=target,
                            creativity=creativity, director_preset=director.id, prompt_length="Short")
                        direct = assemble_instruction(request)
                        planned = assemble_instruction(request, prompt_scene_plan=plan)
                        self.assertEqual(planned.system_message.replace("\n\n" + plan.supporting_input(), ""), direct.system_message)
                        self.assertEqual(planned.user_message, direct.user_message)
                        self.assertIn('"BALANCE"', planned.user_message)
                        self.assertEqual(plan.details["primary_action"], "counterbalance each other")

    def test_reference_evidence_precedes_planning_and_preserved_identity_is_intact(self):
        image = EncodedImage("aW1hZ2U=", "image/png", 32, 32)
        request = GoatedPrompterRequest(idea=HOOP + ", no hat", image=image, linked_references=True,
            reference_map={"subject": "Image 1", "face": "Image 1", "pose": "Off"})
        evidence = json.dumps({"subject": "person with short black hair", "face": "round face"})
        result, backend = self.builder(request, evidence, json.dumps(HOOP_PLAN), HOOP)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["evidence:image_1", "builder:scene_planning", "final"])
        context = json.loads(backend.calls[1].user_message)
        self.assertIn("short black hair", json.dumps(context["preserved_reference_evidence"]))
        self.assertIn("short black hair", result.instruction.system_message)
        self.assertNotIn("no hat", result.instruction.system_message + result.instruction.user_message)
        self.assertIsNotNone(backend.calls[0].image)
        self.assertIsNone(backend.calls[1].image)
        self.assertIsNone(backend.calls[2].image)

    def test_legacy_user_transformation_evidence_cannot_reintroduce_compiled_rules(self):
        image = EncodedImage("b3RoZXIgaW1hZ2U=", "image/png", 32, 32)
        request = GoatedPrompterRequest(idea="Change the pose to " + HOOP + ", no hat", image=image)
        result, backend = self.builder(request, '{"subject":"observed performer","pose":"standing"}', json.dumps(HOOP_PLAN), HOOP)
        self.assertTrue(any(item.source == "User Prompt" for item in result.instruction.resolved_scene.attributes))
        self.assertNotIn("no hat", json.dumps(json.loads(backend.calls[1].user_message)))
        self.assertNotIn("no hat", result.instruction.system_message + result.instruction.user_message)

    def test_validation_rejects_unknown_fields_changed_constraints_and_subject_count(self):
        compiled = compile_request(PAIR + ", no hat")
        for details in ({"primary_action": "x", "idea_history": []}, {"primary_action": "x", "forbidden": []},
                        {"primary_action": "x", "subjects": ["one person"]}, {"primary_action": "x" * 1000}):
            with self.assertRaises(ValueError):
                validate_plan(json.dumps(details), compiled)

    def test_builder_text_only_planning_does_not_touch_reference_evidence(self):
        backend = ScriptedBackend(json.dumps(HOOP_PLAN), HOOP)
        request = GoatedPrompterRequest(idea=HOOP, image=EncodedImage("aW1hZ2U=", "image/png", 32, 32),
            linked_references=True, reference_map={"subject": "Image 1"})
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
            result = GoatedPrompterService(config={"backend": "mock"}).generate_text_only(request)
        self.assertEqual(len(backend.calls), 2)
        self.assertIsNone(result.instruction.resolved_scene)
        self.assertIsNone(result.instruction.image)
        self.assertNotIn("preserved_reference_evidence", json.loads(backend.calls[0].user_message))

    def test_planning_package_has_no_dataset_batch_imports(self):
        directory = ROOT / "goated_prompter" / "planning"
        for path in directory.glob("*.py"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?:from|import)\s+[^\n]*dataset")


if __name__ == "__main__":
    unittest.main()
