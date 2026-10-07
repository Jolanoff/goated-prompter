"""Frozen scene and compact PASS/REPAIR behavior; no live model responses."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset_scene import DatasetSceneService, scene_instruction, validate_scene, validate_self_check
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_eligibility import scene_eligibility
from goated_prompter.scene_planner import ScenePlanner, validate_saved_scene_plan
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.test_dataset import valid_draft


REPAIR = "REPAIR:\nThe user requires both an extreme close-up of only his eyes and clearly visible shoes; the eyes-only crop excludes the shoes.\nShould the image show only eyes, or widen the crop to include the shoes?"
SCENE = "A boxer extends one glove into a training bag, with planted feet and the opposite glove readable in a full-body three-quarter arena view."


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

    def test_scene_check_compares_four_specific_relationships_before_pass(self):
        instruction = scene_instruction(self.data, self.assignment, self.idea)
        for obligation in ("Every HARD requirement", "Camera/framing", "Spatial relationships", "No invented detail"):
            self.assertIn(obligation, instruction.system_message)
        self.assertIn("one compact self-check", instruction.system_message)

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
