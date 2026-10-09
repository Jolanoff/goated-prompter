"""Frozen scene and compact PASS/REPAIR behavior; no live model responses."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.dataset_scene import DatasetSceneService, scene_instruction, validate_scene, validate_self_check
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_eligibility import scene_eligibility
from goated_prompter.scene_planner import ScenePlanner, validate_saved_scene_plan
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support.dataset import REPAIR, SCENE, valid_draft


DUCK_REPAIR_PROSE = '''I must return REPAIR because the provided idea and placement conflict with the HARD requirement that the duck and dinosaur must be depicted in a fighting interaction.

REPAIR:
The idea suggests the duck is hiding/peeking, which conflicts with the HARD requirement for a fighting interaction and visible combat cues.
Clarification needed: Should the duck be actively fighting the Stegosaurus (e.g., pecking, being chased, or grappling) rather than hiding behind it?'''


class DatasetSceneTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        self.assignment = dataset_assignments(self.data)[0]
        self.idea = dataset_idea_fixture()
        self.session = Mock()
        self.service = DatasetSceneService(lambda: None)

    def build(self, check="PASS", **options):
        self.session.generate.return_value = json.dumps({"scene": SCENE, "self_check": check})
        return self.service.run(session=self.session, data=self.data, assignment=self.assignment,
            idea=self.idea, progress=lambda _message: None, **options)

    def test_scene_requests_minified_generation_without_changing_repair_lines_or_sampling(self):
        self.idea.update(scene=SCENE, self_check=REPAIR)
        for repair in (False, True):
            with self.subTest(repair=repair):
                instruction = scene_instruction(self.data, self.assignment, self.idea, repair=repair)
                rules = " ".join(instruction.system_message.split())
                self.assertTrue("Return ONLY one minified JSON object on a single line" in rules)
                self.assertTrue("No indentation or optional whitespace outside string values" in rules)
                self.assertTrue("Formatting compaction must not omit facts or change qualifiers" in rules)
                context = json.loads(instruction.user_message)
                self.assertEqual(instruction.user_message, json.dumps(context, ensure_ascii=False, separators=(",", ":")))
                self.assertEqual(context["current_scene"], SCENE)
                if repair:
                    self.assertEqual(context["repair_request"], REPAIR)
                self.assertEqual((instruction.max_tokens, instruction.hard_max_tokens), (1536, 1536))
                self.assertEqual((instruction.temperature, instruction.top_p), (.25, .85))
                self.assertTrue(instruction.json_output)
                self.assertIsNone(instruction.json_schema)

    def test_minified_scene_and_repair_responses_match_pretty_json_in_one_call(self):
        scene = 'A guard holds a sign reading "NO ENTRY" outside a caf\u00e9, viewed at eye level.'
        for check in ("PASS", REPAIR):
            for formatting in ({"indent": 2}, {"separators": (",", ":")}):
                with self.subTest(check=check, formatting=formatting):
                    self.session.reset_mock()
                    self.session.generate.return_value = json.dumps({"scene": scene, "self_check": check},
                        ensure_ascii=False, **formatting)
                    row = self.service.run(session=self.session, data=self.data, assignment=self.assignment,
                        idea=self.idea, progress=lambda _message: None)
                    self.assertEqual(row["scene"], scene)
                    self.assertEqual(row["self_check"], check)
                    self.assertEqual(row["scene_status"], "valid" if check == "PASS" else "repair_required")
                    self.session.generate.assert_called_once()

    def test_build_and_self_check_share_one_call_and_preserve_fixed_idea_descriptions(self):
        before = deepcopy(self.idea)
        row = self.build()
        self.session.generate.assert_called_once()
        self.assertEqual(row["scene"], SCENE)
        self.assertEqual(row["self_check"], "PASS")
        self.assertEqual(row["scene_status"], "valid")
        self.assertNotIn("geometry", row)
        for field, value in before.items():
            self.assertEqual(row[field], value)
        self.assertEqual(self.idea, before)
        instruction = self.session.generate.call_args.args[0]
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"], self.data["_confirmed_intent"])
        self.assertEqual(instruction.diagnostic_stage, "dataset:build_scene")

    def test_build_and_explicit_repair_request_json_decoding_only_for_llama_cpp(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps({"scene": SCENE, "self_check": "PASS"})}}]}).encode()
        self.idea.update(scene=SCENE, self_check=REPAIR)
        for repair in (False, True):
            for owned in (True, False):
                with self.subTest(repair=repair, owned_llama=owned):
                    backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1",
                        "model": "synthetic", "_is_llama_cpp": owned})
                    with patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send, \
                            patch("goated_prompter.backends.openai_compatible.log_request"), \
                            patch("goated_prompter.backends.openai_compatible.log_response"):
                        row = self.service.run(session=backend, data=self.data, assignment=self.assignment,
                            idea=self.idea, progress=lambda _message: None, repair=repair)
                    send.assert_called_once()
                    payload = json.loads(send.call_args.args[0].data)
                    if owned:
                        self.assertEqual(payload.get("response_format"), {"type": "json_object"})
                    else:
                        self.assertNotIn("response_format", payload)
                    self.assertEqual(payload["max_tokens"], 1536)
                    self.assertEqual(row["self_check"], "PASS")

    def test_scene_can_correct_generated_crop_in_its_existing_call(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "One red ceramic cup; base touching the table visible."}],
            soft=[{"scope": "all_outputs", "text": "Close camera."}],
            free=[{"scope": "all_outputs", "text": "Background."}])
        self.idea.update(idea="A red ceramic cup resting on a table.",
            framing="Tight upper-half crop.")
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        self.assertIn("IDEAS are suggestions, not immutable requirements", instruction.system_message)
        self.assertIn("Repair generated conflicts within this same call", instruction.system_message)
        self.assertIn("Only return REPAIR when two actual user HARD requirements", instruction.system_message)
        self.assertNotIn("Preserve the idea's placement, visibility, camera, framing and context", instruction.system_message)
        self.assertNotIn("Do not silently apply a correction", instruction.system_message)
        self.assertEqual(json.loads(instruction.user_message)["assignments"][0]["framing"], "Tight upper-half crop.")
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"]["hard"], self.data["_confirmed_intent"]["hard"])

    def test_scene_output_examples_use_json_for_pass_and_real_hard_conflicts(self):
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        examples = [validate_scene(line) for line in instruction.system_message.splitlines()
            if line.startswith('{"scene":')]
        self.assertGreaterEqual(len(examples), 2, "Both PASS and REPAIR need complete JSON examples.")
        self.assertTrue(any(example["self_check"] == "PASS" for example in examples))
        self.assertTrue(any(example["self_check"].startswith("REPAIR:\n") for example in examples))
        self.assertNotIn("\nREPAIR:\n", instruction.system_message)
        self.assertIn("REPAIR is a value of self_check, never a standalone response", instruction.system_message)

    def test_fighting_scene_corrects_generated_hiding_instead_of_questioning_approved_action(self):
        self.data.update(subject="A duck fighting a Stegosaurus.",
            _confirmed_intent=dataset_understanding_fixture(hard=[
                {"scope": "all_outputs", "text": "The duck and dinosaur must be depicted in a fighting interaction with visible combat cues."}]))
        self.idea.update(idea="A duck hiding behind a Stegosaurus and peeking out.",
            placement="Duck partially obscured behind the dinosaur; only its head and neck visible.",
            framing="Tight framing on the duck's cautious expression.")
        before = deepcopy(self.idea)
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        self.assertIn("Construct a HARD-compliant scene first", instruction.system_message)
        self.assertIn("Do not ask whether they should fight", instruction.system_message)
        example = next((validate_scene(line) for line in instruction.system_message.splitlines()
            if line.startswith('{"scene":') and "Stegosaurus" in line), None)
        self.assertIsNotNone(example, "The repair example must show the fight, not preserve generated hiding.")
        self.session.generate.return_value = json.dumps(example)
        row = self.service.run(session=self.session, data=self.data, assignment=self.assignment,
            idea=self.idea, progress=lambda _message: None)
        context = json.loads(self.session.generate.call_args.args[0].user_message)
        self.assertEqual(context["confirmed_intent"]["hard"], self.data["_confirmed_intent"]["hard"])
        self.assertEqual(context["assignments"][0]["idea"], before["idea"])
        self.assertIn("pecks", row["scene"])
        self.assertIn("lunges", row["scene"])
        self.assertEqual(row["self_check"], "PASS")
        self.assertTrue(scene_eligibility(row, self.data).usable)
        self.assertEqual(self.idea, before)
        self.session.generate.assert_called_once()

    def test_scene_check_compares_four_specific_relationships_before_pass(self):
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        for obligation in ("Every HARD requirement", "Camera/framing", "Spatial relationships", "No invented detail"):
            self.assertIn(obligation, instruction.system_message)
        self.assertIn("one compact self-check", instruction.system_message)

    def test_scene_applies_medium_without_explaining_style_in_its_paragraph(self):
        self.data["visual_style"] = "Anime / manga"
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Apply the selected visual medium silently", rules)
        self.assertIn("Do not add commentary about rendering style", rules)
        self.assertEqual(instruction.diagnostic_stage, "dataset:build_scene")

    def test_scene_check_requires_subject_by_subject_role_satisfaction_not_labels(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(hard=[
            {"scope": "all_outputs", "text": "The safety coordinator manages the crash mat."},
            {"scope": "all_outputs", "text": "The lighting assistant controls the reflector."}])
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("against the actual scene, subject by subject", rules)
        self.assertIn("Presence or a role label is not enough", rules)
        self.assertIn("that character must visibly perform a compatible part of that responsibility in this frozen moment", rules)
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"]["hard"],
            self.data["_confirmed_intent"]["hard"])

    def test_scene_check_requires_temporal_compatibility_in_one_moment(self):
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Temporal compatibility", rules)
        self.assertIn("Do not combine actions from different moments merely because each action is individually possible", rules)

    def test_scene_check_requires_reachable_actions_and_correct_equipment_ownership(self):
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Action reachability and ownership", rules)
        self.assertIn("each subject's location must allow the described action on its target", rules)
        self.assertIn("tools and equipment must be controlled by the correct role", rules)
        self.assertIn("one object or body part cannot be used incompatibly at the same time", rules)

    def test_scene_check_forbids_staging_solely_to_reveal_optional_fixed_traits(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(hard=[
            {"scope": "all_outputs", "text": "The performer has a shoulder scar; it may remain covered."}])
        self.idea.update(visibility="Rotate the performer and remove the shoulder drape to reveal the scar.")
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Never reposition, rotate, undrape or otherwise stage a subject solely to reveal a fixed trait whose visibility was not required", rules)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["confirmed_intent"]["visible_evidence"], [])
        self.assertEqual(context["assignments"][0]["visibility"], self.idea["visibility"])

    def test_scene_compares_supplied_trait_groups_to_subject_ownership_before_pass(self):
        self.data.update(trigger_type="Multiple characters", trigger="Mira, blue hair, bat wings, Hana, blonde hair, crystal wings")
        self.idea.update(idea="Hana drapes a bat wing over the table while reading with Mira.")
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Compare each described trait and body part with its supplied owner", rules)
        self.assertIn("A trait omitted from a shorter paraphrase is not permission to transfer it", rules)
        self.assertIn("Correct transferred traits from IDEAS before PASS", rules)
        self.assertIn("Ownership does not require exposure", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["trigger"], self.data["trigger"])

    def test_all_generated_staging_errors_must_be_corrected_in_the_same_scene_call(self):
        self.idea.update(scene=SCENE, self_check=REPAIR)
        for repair in (False, True):
            with self.subTest(repair=repair):
                instruction = scene_instruction(self.data, self.assignment, self.idea, repair=repair)
                rules = " ".join(instruction.system_message.split())
                self.assertIn("role, timing, reach, ownership and optional-visibility errors from IDEAS or your own generated staging", rules)
                self.assertIn("Return the corrected paragraph with self_check exactly PASS", rules)
                self.assertIn("Only return REPAIR when two actual user HARD requirements cannot both be satisfied", rules)
                self.assertIn("not a second evaluator or repair loop", rules)

    def test_user_conflict_repair_response_blocks_writer_without_a_second_call(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(hard=[
            {"scope": "all_outputs", "text": "Extreme close-up of only his eyes."},
            {"scope": "all_outputs", "text": "Show his shoes clearly."}])
        row = self.build(REPAIR)
        self.assertEqual(row["self_check"], REPAIR)
        self.assertEqual(row["scene"], SCENE)
        self.assertEqual(row["scene_status"], "repair_required")
        self.assertEqual(row["prompt_status"], "not_generated")
        self.assertFalse(scene_eligibility(row, self.data).usable)
        self.assertEqual(scene_eligibility(row, self.data).reason, REPAIR)
        self.session.generate.assert_called_once()

    def test_explicit_repair_supplies_current_scene_and_only_the_local_correction(self):
        self.idea.update(scene=SCENE, self_check=REPAIR, geometry={"obsolete": "Do not use this schema"})
        self.build(repair=True)
        context = json.loads(self.session.generate.call_args.args[0].user_message)
        self.assertEqual(context["current_scene"], SCENE)
        self.assertEqual(context["repair_request"], REPAIR)
        self.assertEqual(context["assignments"][0]["idea"], self.idea["idea"])
        self.assertNotIn("geometry", context)
        self.assertNotIn("obsolete", json.dumps(context))
        self.session.generate.assert_called_once()

    def test_saved_manual_edit_without_current_pass_gets_one_build_check_using_its_prose(self):
        self.idea.update(scene="A manually placed boxer at the left of the image.", self_check="")
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["current_scene"], self.idea["scene"])
        self.assertNotIn("repair_request", context)

    def test_guided_scope_matches_original_line_when_input_cycles(self):
        self.data.update(amount=3, source_mode="guided", inputs="Punch drill\n\nDefense drill",
            _confirmed_intent=dataset_understanding_fixture(rules=[{"scope": "guided:2", "text": "At the ropes"}]))
        self.assignment = dataset_assignments(self.data)[2]
        self.idea = dataset_idea_fixture(3)
        context = json.loads(scene_instruction(self.data, self.assignment, self.idea).user_message)
        self.assertEqual(context["assignments"][0]["guided_scope"], "guided:1")
        self.assertEqual(context["assignments"][0]["input"], "Punch drill")
        self.assertEqual(context["confirmed_intent"]["rules"][0]["scope"], "guided:2")

    def test_missing_idea_or_unanswered_understanding_never_calls_model(self):
        for patch_data, patch_idea in (({"_confirmed_intent": None}, {}),
                ({"_confirmed_intent": dataset_understanding_fixture(clarifications=["Which foot?"])}, {}),
                ({}, {"idea": ""}), ({}, {"index": 2})):
            with self.subTest(patch_data=patch_data, patch_idea=patch_idea), self.assertRaises(ValueError):
                self.service.run(session=self.session, data={**self.data, **patch_data}, assignment=self.assignment,
                    idea={**self.idea, **patch_idea}, progress=lambda _message: None)
        self.session.generate.assert_not_called()

    def test_invalid_output_has_no_retry(self):
        self.session.generate.return_value = '{"scene":"Frozen scene","self_check":"PASS because it seems fine"}'
        with self.assertRaisesRegex(BackendGenerationError, "No automatic retry"):
            self.service.run(session=self.session, data=self.data, assignment=self.assignment,
                idea=self.idea, progress=lambda _message: None)
        self.session.generate.assert_called_once()

    def test_reported_duck_repair_prose_is_not_silently_accepted_as_a_scene(self):
        self.data.update(subject="A duck fighting a Stegosaurus.",
            _confirmed_intent=dataset_understanding_fixture(hard=[
                {"scope": "all_outputs", "text": "The duck and dinosaur must be depicted in a fighting interaction with visible combat cues."}]))
        self.idea.update(idea="A duck hiding behind a Stegosaurus and peeking out.",
            placement="Duck partially obscured behind the dinosaur; only its head and neck visible.",
            framing="Tight framing on the duck's cautious expression.")
        before = deepcopy(self.idea)
        self.session.generate.return_value = DUCK_REPAIR_PROSE
        with self.assertRaisesRegex(BackendGenerationError, "Dataset scene returned invalid output: Expecting value: line 1 column 1") as caught:
            self.service.run(session=self.session, data=self.data, assignment=self.assignment,
                idea=self.idea, progress=lambda _message: None)
        self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)
        self.assertEqual(self.idea, before)
        self.session.generate.assert_called_once()

    def test_complete_json_fence_preserves_scene_and_check_in_one_call(self):
        for check in ("PASS", REPAIR):
            for label in ("", "json", "JSON"):
                with self.subTest(check=check, label=label):
                    self.session.reset_mock()
                    self.session.generate.return_value = f"```{label}\n{json.dumps({'scene': SCENE, 'self_check': check})}\n```"
                    row = self.service.run(session=self.session, data=self.data, assignment=self.assignment,
                        idea=self.idea, progress=lambda _message: None)
                    self.assertEqual(row["scene"], SCENE)
                    self.assertEqual(row["self_check"], check)
                    self.assertEqual(row["scene_status"], "valid" if check == "PASS" else "repair_required")
                    self.session.generate.assert_called_once()

    def test_scene_fence_cannot_hide_incomplete_prose_duplicate_keys_or_extra_values(self):
        good = json.dumps({"scene": SCENE, "self_check": "PASS"})
        invalid = [f"```json\n{good}", f"```text\n{good}\n```",
            f"Explanation\n```json\n{good}\n```", f"```json\n{good}\n```\nExplanation",
            f"```json\n{good}\n{good}\n```",
            '```json\n{"scene":"one","scene":"two","self_check":"PASS"}\n```',
            '```json\n{"scene":"Frozen scene","self_check":"PASS because"}\n```']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_scene(raw)

    def test_backend_error_is_not_retried(self):
        self.session.generate.side_effect = BackendGenerationError("Synthetic engine failure")
        with self.assertRaisesRegex(BackendGenerationError, "Synthetic engine failure"):
            self.build()
        self.session.generate.assert_called_once()

    def test_scene_parser_rejects_giant_evaluator_payloads_missing_checks_and_wrong_shapes(self):
        good = {"scene": SCENE, "self_check": "PASS"}
        invalid = ["not JSON", "[]", "{}", json.dumps({"scene": SCENE}), json.dumps({**good, "scores": [1] * 20}),
            json.dumps({**good, "geometry": {}}), json.dumps({**good, "index": 1}),
            json.dumps({**good, "scene": "x" * 3001}), json.dumps({**good, "scene": " "}),
            json.dumps({**good, "scene": []}), json.dumps({**good, "self_check": True}),
            '{"scene":"one","scene":"two","self_check":"PASS"}']
        for check in ("", "pass", "PASS\n", "PASS: looks good", "REPAIR:", "REPAIR:\nFoot hidden.",
                "REPAIR:\n\nMove foot.", "REPAIR:\nFoot hidden.\nMove foot.\nAnother evaluation.", "x" * 1201):
            invalid.append(json.dumps({**good, "self_check": check}))
        for raw in invalid:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                validate_scene(raw)

    def test_saved_repair_and_pass_roundtrip_and_repair_cannot_be_overridden_by_valid_status(self):
        row = self.build(REPAIR)
        self.assertEqual(validate_saved_scene_plan([row]), [row])
        forged = {**row, "scene_status": "valid", "prompt_status": "valid"}
        cleaned = validate_saved_scene_plan([forged])[0]
        self.assertEqual(cleaned["scene_status"], "repair_required")
        self.assertFalse(scene_eligibility(forged, self.data).usable)
        passed = self.build()
        self.assertEqual(validate_saved_scene_plan([passed]), [passed])
        self.assertTrue(scene_eligibility(passed, self.data).usable)

    def test_pending_or_invalidated_checks_are_not_writer_eligible(self):
        row = self.build()
        for changes in ({"self_check": ""}, {"self_check": "PASS because"}, {"scene_status": "not_generated"}, {"scene": ""}):
            with self.subTest(changes=changes):
                self.assertFalse(scene_eligibility({**row, **changes}, self.data).usable)
        self.assertEqual(validate_self_check("", allow_pending=True), "")

    def test_cancelled_model_response_is_not_returned_as_a_passed_scene(self):
        self.service = DatasetSceneService(Mock(side_effect=[None, RuntimeError("Cancelled")]))
        with self.assertRaisesRegex(RuntimeError, "Cancelled"):
            self.build()
        self.session.generate.assert_called_once()

    def test_partial_scene_failure_preserves_every_fixed_idea_in_the_published_plan(self):
        self.data["amount"] = 2
        ideas = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        snapshots = []
        self.session.generate.side_effect = [json.dumps({"scene": SCENE, "self_check": "PASS"}),
            BackendGenerationError("Second scene interrupted")]
        with self.assertRaisesRegex(BackendGenerationError, "Second scene interrupted"):
            ScenePlanner(lambda: None).compose(session=self.session, data=self.data,
                assignments=dataset_assignments(self.data), ideas=ideas, progress=lambda _message: None,
                plan_update=lambda rows: snapshots.append(deepcopy(rows)))
        self.assertEqual(len(snapshots[-1]), 2)
        self.assertEqual(snapshots[-1][0]["self_check"], "PASS")
        self.assertEqual(snapshots[-1][1]["idea"], ideas[1]["idea"])
        self.assertEqual(snapshots[-1][1]["self_check"], "")
        self.assertEqual(snapshots[-1][1]["scene_status"], "not_generated")
        self.assertEqual(self.session.generate.call_count, 2)
