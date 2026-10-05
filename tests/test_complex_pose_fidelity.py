"""Conservative crop/contact gates and exact captured failure replays, no inference."""
import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError, BackendRunawayError
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import geometry_issues
from goated_prompter.dataset_staging.engine import geometry_repair_locks
from goated_prompter.dataset_staging.rules.framing import framing_text_errors, requested_framing
from goated_prompter.planning.semantic_validation import invariant_contract, repair_contract, _parse_review
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.scene_planner import ScenePlanner
from tests.test_complex_pose_staging import CASES, pose_row
from tests.test_dataset_quality_planning import draft


def fixtures():
    path = Path(__file__).parent / "eval/fixtures/model_outputs/complex_pose_fidelity.json"
    return json.loads(path.read_text(encoding="utf-8"))["records"]


class CropFidelityTests(unittest.TestCase):
    def test_framing_not_inferred_from_visible_anatomy_or_distance(self):
        for text in ("Feet and knees visible beside the head.",
                     "The full body remains visible, tightly folded in a waist-up composition.",
                     "A waist-up shot taken at an extreme close camera distance.",
                     "A medium distance camera keeps feet beside the head.",
                     "Bare hands support the full body above the floor."):
            with self.subTest(text=text):
                self.assertEqual(framing_text_errors(text, "waist_up"), [])

    def test_anatomy_of_a_subject_does_not_assert_a_camera_crop(self):
        for text in ("Hands touch the head and shoulders of the curled figure.",
                     "The full body of the performer folds into a waist-up composition.",
                     "The upper body of the acrobat twists above the hips."):
            for crop in ("waist_up", "full_body"):
                if crop == "full_body" and "waist-up composition" in text:
                    continue  # That phrase actually does declare a different crop.
                with self.subTest(text=text, crop=crop):
                    self.assertFalse(framing_text_errors(text, crop))
        self.assertTrue(framing_text_errors("A head-and-shoulders portrait of the curled figure.", "waist_up"))
        self.assertTrue(framing_text_errors("A full-body shot of the performer.", "waist_up"))

    def test_shot_aliases_remain_explicit_without_a_second_composition_noun(self):
        self.assertFalse(framing_text_errors("A medium shot of a folded figure.", "waist_up"))
        self.assertTrue(framing_text_errors("A medium shot of a folded figure.", "face_close_up"))
        self.assertFalse(framing_text_errors("A waist-up shot of a figure at a medium close camera distance.", "waist_up"))

    def test_inherent_closeup_label_is_a_crop_even_before_a_verb(self):
        # Exact opening from the authorized Quality hands writer: this was
        # accepted by the pre-followup gate because it did not end with "of".
        text = "A photorealistic extreme close-up centers on a woman's face, framed intimately by her raised hands."
        self.assertTrue(framing_text_errors(text, "face_close_up"))
        self.assertFalse(framing_text_errors(text, "extreme_close_up"))
        self.assertFalse(framing_text_errors("A waist-up shot at an extreme close-up camera distance.", "waist_up"))
        self.assertFalse(framing_text_errors("A waist-up shot at close-up distance.", "waist_up"))

    def test_explicit_crops_use_existing_canonical_aliases(self):
        for text in ("Upper-body composition with feet beside the head.",
                     "A medium shot with folded feet at the temples.",
                     "A waist_up view of a curled figure.",
                     "A waist–up shot of an inverted figure."):
            self.assertFalse(framing_text_errors(text, "waist_up"))
        for text in ("A full-body shot of a contortionist.",
                     "A tight face close-up portrait.", "A low-angle, close-up shot.",
                     "The full body is framed in a studio."):
            self.assertTrue(framing_text_errors(text, "waist_up"))
        self.assertFalse(framing_text_errors("A full-body view in a studio.", "full_body_with_environment"))

    def test_longest_label_is_not_mistaken_for_nested_closeup(self):
        self.assertFalse(framing_text_errors("An extreme close-up of a face.", "extreme_close_up"))
        self.assertTrue(framing_text_errors("An extreme close-up of a face.", "face_close_up"))
        self.assertFalse(framing_text_errors("A face close-up of folded hands.", "face_close_up"))

    def test_only_standalone_source_crop_tags_project_to_locks(self):
        for source, expected in (("upper body, feet behind neck", "waist_up"),
                                 ("close-up, hands beside face", "face_close_up"),
                                 ("curled pose, waist-up framing", "waist_up"),
                                 ("upper body, waist-up", "waist_up"),
                                 ("waist-up, full-body", None),
                                 ("feet and knees clearly visible", None),
                                 ("Stretch the upper body", None),
                                 ("medium", None)):
            self.assertEqual(requested_framing(source), expected)

    def test_guided_crop_wins_over_a_valid_but_widened_planner_field(self):
        row = pose_row(CASES[0]); row["geometry"]["framing"] = "full_body"
        data = draft(amount=1, source_mode="guided", inputs="upper body, feet behind neck, feet visible")
        replacement = deepcopy(row)  # Model attempts the same wrong crop again.
        session = Mock(); session.generate.return_value = json.dumps([replacement])
        result = ScenePlanner(lambda: None)._check_scenes(session, data, dataset_assignments(data),
            [row], "qwen", lambda _: None)[0]
        self.assertEqual(result["geometry"]["framing"], "waist_up")
        self.assertEqual(result["geometry"]["pose_detail"], row["geometry"]["pose_detail"])
        self.assertEqual(session.generate.call_count, 1)

    def test_guided_crop_repair_handles_non_object_geometry_without_crashing(self):
        row = pose_row(CASES[0]); row["geometry"] = []
        data = draft(amount=1, source_mode="guided", inputs="upper body, feet behind neck, feet visible")
        session = Mock(); session.generate.return_value = json.dumps([pose_row(CASES[0])])
        result = ScenePlanner(lambda: None)._check_scenes(session, data, dataset_assignments(data),
            [row], "qwen", lambda _: None)[0]
        self.assertEqual(result["geometry"]["framing"], "waist_up")
        self.assertEqual(session.generate.call_count, 1)

    def test_literals_and_trigger_spelling_do_not_become_camera_requirements(self):
        text = 'A waist-up shot with a sign reading "full-body view".'
        self.assertFalse(framing_text_errors(text, "waist_up"))
        self.assertFalse(framing_text_errors("full_body of a curled person in a waist-up shot.", "waist_up", protected_terms=("full_body",)))
        self.assertFalse(framing_text_errors("Not a full-body shot; a waist-up shot.", "waist_up"))
        self.assertFalse(framing_text_errors("A full-body shot.", None))

    def test_scene_crop_repair_changes_prose_not_valid_custom_geometry(self):
        original = pose_row(CASES[0])
        original["scene"] = "A full-body shot. " + original["geometry"]["pose_detail"]
        self.assertEqual([p.fields for p in geometry_issues(original, "Character")], [("scene",)])
        self.assertEqual(geometry_repair_locks(original, dataset_type="Character")["framing"], "waist_up")
        wrong = deepcopy(original)
        wrong["geometry"]["framing"] = "full_body"
        good = pose_row(CASES[0])
        session = Mock()
        session.generate.side_effect = [json.dumps([wrong]), json.dumps([good])]
        data = draft(amount=1)
        result = ScenePlanner(lambda: None).repair_scene(session=session, data=data,
            assignments=dataset_assignments(data), row=original, errors=["Explicit crop conflicts"], progress=lambda _: None)
        self.assertEqual(result, good)
        self.assertEqual(session.generate.call_count, 2)

    def test_captured_writer_crop_drifts_are_rejected_without_live_review(self):
        for captured in fixtures()[1:]:
            with self.subTest(case=captured["id"]):
                row = {"index": 1, "idea": captured["source"], "input": captured["source"],
                       "scene": captured["scene"], "geometry": captured["geometry"]}
                data = draft(amount=1, trigger="pose_subject", planning_mode="Fast")
                instruction = dataset_instruction(GoatedPrompterRequest(idea=captured["source"]), data, 1, plan_item=row)
                session = Mock()
                session.generate.return_value = captured["writer_raw"]
                with self.assertRaises(BackendGenerationError) as caught:
                    DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data,
                        1, lambda _: None, row, retries=0)
                self.assertIn("framing conflicts with locked", str(caught.exception))
                self.assertEqual(session.generate.call_count, 1)  # No self-audit pass.

    def test_writer_repairs_only_crop_and_keeps_contract_through_transport_retry(self):
        row = pose_row(CASES[0]); data = draft(amount=1)
        instruction = dataset_instruction(GoatedPrompterRequest(idea=row["idea"]), data, 1, plan_item=row)
        wrong = "person_token in a full-body shot; knees beside shoulders, lower legs behind head, ankles behind neck, feet visible beside head."
        good = wrong.replace("full-body", "waist-up")
        session = Mock()
        session.generate.side_effect = [wrong, BackendGenerationError("connection lost"), good]
        result = DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data,
            1, lambda _: None, row)
        self.assertIn("waist-up shot", result)
        for call in session.generate.call_args_list[1:]:
            correction = call.args[0]
            self.assertIn("Explicit 'full-body' framing conflicts with locked 'waist_up'", correction.system_message)
            self.assertIn(row["geometry"]["pose_detail"], correction.user_message)
            self.assertIn('"required_visible_parts": ["face", "torso", "feet"]', correction.user_message)
            self.assertEqual(correction.hard_max_tokens, instruction.hard_max_tokens)

    def test_ideogram_checks_style_prose_and_preserves_literal_text_element(self):
        from tests.test_dataset_visible_content import caption
        row = pose_row(CASES[0]); data = draft(amount=1, target="Ideogram4", planning_mode="Fast")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=row["idea"]), data, 1, plan_item=row)
        wrong = caption()
        wrong["style_description"]["photo"] = "A full-body view at eye level."
        wrong["compositional_deconstruction"]["elements"].append({"type": "text", "text": "full-body shot", "desc": "Printed lettering on a sign."})
        corrected = deepcopy(wrong)
        corrected["style_description"]["photo"] = "A waist-up view at eye level."
        session = Mock(); session.generate.side_effect = [json.dumps(wrong), json.dumps(corrected)]
        result = json.loads(DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data,
            1, lambda _: None, row))
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(result["style_description"]["photo"], corrected["style_description"]["photo"])
        self.assertEqual(result["compositional_deconstruction"]["elements"][-1]["text"], "full-body shot")

    def test_loop_prefix_with_wrong_crop_cannot_bypass_fidelity_gate(self):
        row = pose_row(CASES[0]); data = draft(amount=1)
        instruction = dataset_instruction(GoatedPrompterRequest(idea=row["idea"]), data, 1, plan_item=row)
        prefix = "person_token in a full-body shot; hips supported on the floor, knees beside shoulders, lower legs folded behind the head, ankles passing behind the neck, and both feet clearly visible beside the head."
        session = Mock(); session.generate.side_effect = [BackendRunawayError("loop", recoverable_text=prefix), prefix.replace("full-body", "waist-up")]
        result = DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data,
            1, lambda _: None, row)
        self.assertIn("waist-up shot", result)
        self.assertEqual(session.generate.call_count, 2)
        self.assertLess(session.generate.call_args.args[0].hard_max_tokens, instruction.hard_max_tokens)


class ContactAndContractTests(unittest.TestCase):
    def test_exact_captured_none_support_metadata_is_repaired_without_pose_changes(self):
        captured = fixtures()[0]
        original = {"index": 1, "idea": captured["source"], "scene": captured["scene"], "geometry": captured["geometry"]}
        issues = geometry_issues(original, "Character")
        self.assertEqual([(p.code, p.fields) for p in issues], [("support_contact_metadata", ("contact_state",))])
        corrected = deepcopy(original)
        corrected["geometry"].update(contact_state="sitting_on", framing="full_body", pose_detail="Generic sitting with arms relaxed")
        corrected["scene"] = "A conventional full-body portrait."
        session = Mock(); session.generate.return_value = json.dumps([corrected])
        data = draft(amount=1)
        result = ScenePlanner(lambda: None).repair_scene(session=session, data=data,
            assignments=dataset_assignments(data), row=original, errors=[issues[0].message], progress=lambda _: None)
        self.assertEqual(result["geometry"], {**original["geometry"], "contact_state": "sitting_on"})
        self.assertEqual(result["scene"], original["scene"])
        self.assertEqual(captured["geometry"]["contact_state"], "none")

    def test_support_metadata_gate_does_not_infer_missing_or_negated_load_paths(self):
        for detail, contact in (("Not supported by a surface; airborne in mid-jump.", "none"),
                                ("An unfamiliar folded pose with feet beside head.", "none"),
                                ("Hips supported by floor; knees beside face.", "supporting"),
                                ("Hips supported by floor; knees beside face.", None)):
            row = pose_row(CASES[0]); row["geometry"]["pose_detail"] = detail
            if contact is None: row["geometry"].pop("contact_state", None)
            else: row["geometry"]["contact_state"] = contact
            self.assertNotIn("support_contact_metadata", [p.code for p in geometry_issues(row, "Character")])

    def test_contract_carries_complete_staging_without_mutating_plan(self):
        row = pose_row(CASES[0])
        contract = invariant_contract(CASES[0][1], planned=row)
        self.assertEqual(contract["planned_geometry"], row["geometry"])
        contract["planned_geometry"]["required_visible_parts"].append("knees")
        self.assertNotIn("knees", row["geometry"]["required_visible_parts"])
        self.assertIn('"framing": "waist_up"', repair_contract(contract, "previous", "crop changed"))

    def test_review_has_exact_provenance_for_geometry_only_requirement(self):
        contract = invariant_contract("A folded figure.", planned=pose_row(CASES[0]))
        raw = json.dumps({"checks": {"scene_fidelity": "fail"}, "accepted_facts": [], "issues": [{
            "category": "scene_fidelity", "kind": "scene_drift", "source_quote": "waist_up",
            "evidence": "full-body shot", "message": "Explicit crop replaced locked waist-up.", "index": 0}]})
        self.assertEqual(_parse_review(raw, "A full-body shot.", contract, ("scene_fidelity",))["checks"]["scene_fidelity"], "fail")
        raw = raw.replace('"source_quote": "waist_up"', '"source_quote": "extreme_wide"')
        with self.assertRaisesRegex(ValueError, "provenance"):
            _parse_review(raw, "A full-body shot.", contract, ("scene_fidelity",))
