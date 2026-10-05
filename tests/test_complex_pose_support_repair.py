"""Captured support failures with supplied audit verdicts, never model qualification."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import geometry_issues
from goated_prompter.dataset_staging.engine import geometry_repair_locks, semantic_geometry_fields
from goated_prompter.planning.semantic_validation import SemanticValidationError, _parse_review, invariant_contract
from goated_prompter.scene_planner import ScenePlanner
from tests.test_dataset_quality_planning import draft


RECORDS = json.loads((Path(__file__).parent / "eval/fixtures/model_outputs/complex_pose_support.json").read_text(encoding="utf-8"))["records"]


def diagnosis(source, evidence, category="action_fidelity"):
    return {"category": category, "kind": "action_drift", "source_quote": source,
            "evidence": evidence, "message": "The quoted supporting mechanics must be corrected to preserve source support.", "index": 1}


def checked_issues(record):
    """Synthetic, exact-provenance verdicts; not output from a real reviewer."""
    row = record["row"]
    quote = "one-arm" if record["id"] == "asymmetric_balance" else "shoulder-supported"
    if record["id"] == "asymmetric_balance":
        detail_evidence, scene_evidence = "Standing on right leg with knee straight", "straight and bears the full body weight"
    elif record["mode"] == "Fast":
        detail_evidence, scene_evidence = "interlocked hands supporting head", "upper torso and head are supported by interlocked hands"
    else:
        detail_evidence, scene_evidence = "arms bent to grip upper arms for stability", "hands gripping the upper arms or shoulders"
    issues = [diagnosis(quote, detail_evidence), diagnosis(quote, scene_evidence)]
    if row["geometry"]["contact_state"] == "standing_on":
        issues.append(diagnosis(quote, "standing_on", "scene_fidelity"))
    statuses = {"action_fidelity": "fail", "scene_fidelity": "fail" if len(issues) == 3 else "pass"}
    verdict = json.dumps({"checks": statuses, "issues": issues, "accepted_facts": []})
    return _parse_review(verdict, json.dumps(row), invariant_contract(record["source"], planned=row), tuple(statuses))["issues"]


def repair_control(record):
    """Hand-authored control for plumbing only; no expert physical verdict."""
    result = deepcopy(record["row"])
    if record["id"] == "asymmetric_balance":
        detail = "Right palm bears weight on floor; left arm extends outward; left knee folds near left shoulder; opposite leg extends sideways above floor; hips counterbalance above the supporting palm."
    else:
        detail = "Shoulders and upper back bear weight against the mat; hips raised above shoulders; legs folded around upper torso; knees bent beside chest; feet near upper torso; hands brace the back; head rests on mat."
    result["scene"] = detail
    result["geometry"]["pose_detail"] = detail
    result["geometry"]["contact_state"] = "supporting"
    return result


class SupportRepairTests(unittest.TestCase):
    def test_captured_mechanics_still_pass_default_structural_checks(self):
        # Do not relabel these failures as detected without a qualified audit.
        for record in RECORDS:
            with self.subTest(case=(record["mode"], record["id"])):
                self.assertEqual(geometry_issues(record["row"], "Character"), [])
                self.assertIn("pose_detail", geometry_repair_locks(record["row"], dataset_type="Character"))

    def test_exact_evidence_localizes_fields_without_pose_or_anatomy_inference(self):
        for record in RECORDS:
            expected = {"pose_detail"}
            if record["row"]["geometry"]["contact_state"] == "standing_on":
                expected.add("contact_state")
            self.assertEqual(semantic_geometry_fields(record["row"], checked_issues(record)), expected)
        row = {"geometry": {"pose_type": "custom", "pose_detail": "Unknown widget rests on a striped plinth.",
                             "camera_azimuth": "front_three_quarter", "required_visible_parts": ["face", "feet"]}}
        self.assertEqual(semantic_geometry_fields(row, [diagnosis("widget", "striped plinth")]), {"pose_detail"})
        self.assertEqual(semantic_geometry_fields(row, [diagnosis("widget", "front")]), set())
        self.assertEqual(semantic_geometry_fields(row, [diagnosis("widget", "feet")]), {"required_visible_parts"})

    def test_omissions_uncertainty_and_unquoted_diagnoses_do_not_unlock_fields(self):
        row = RECORDS[2]["row"]
        issues = [diagnosis("one-arm", ""), diagnosis("one-arm", "not in the row"),
                  {**diagnosis("one-arm", row["geometry"]["pose_detail"]), "kind": "uncertain"}]
        self.assertFalse(semantic_geometry_fields(row, issues))
        self.assertFalse(semantic_geometry_fields({"geometry": []}, issues))
        self.assertFalse(semantic_geometry_fields(row, [{**diagnosis("one-arm", row["geometry"]["pose_detail"]), "index": 2}]))

    def test_escaped_evidence_can_identify_a_free_text_field(self):
        row = {"index": 1, "geometry": {"pose_detail": 'A widget rests against a surface marked "left".'}}
        evidence = json.dumps(row["geometry"]["pose_detail"])[1:-1]
        self.assertEqual(semantic_geometry_fields(row, [diagnosis("widget", evidence)]), {"pose_detail"})

    def test_both_modes_can_repair_quoted_bad_mechanics_without_overwriting_control(self):
        for record in RECORDS:
            with self.subTest(case=(record["mode"], record["id"])):
                original = deepcopy(record["row"])
                good = repair_control(record)
                issues = checked_issues(record)
                data = draft(amount=1, source_mode="guided", inputs=record["source"], planning_mode=record["mode"])
                session = Mock(); session.generate.return_value = json.dumps([good])
                planner = ScenePlanner(lambda: None, semantic_validation=True)
                with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=[SemanticValidationError(issues), ()]) as audit:
                    result = planner._check_scenes(session, data, dataset_assignments(data), [original], "qwen", lambda _: None)[0]
                self.assertEqual(result, good)
                self.assertEqual(session.generate.call_count, 1)
                self.assertEqual(audit.call_count, 2)  # Full repaired candidate audited.
                context = json.loads(session.generate.call_args.args[0].user_message)
                self.assertNotIn("pose_detail", context["locked_geometry"])
                self.assertEqual(context["locked_geometry"]["framing"], original["geometry"]["framing"])
                self.assertEqual(context["locked_geometry"]["required_visible_parts"], original["geometry"]["required_visible_parts"])
                self.assertIsNone(context["locked_scene_prose"])
                contract = planner._scene_repair_contracts[1]
                self.assertNotIn("pose_detail", contract["planned_geometry"])
                self.assertNotIn("pose_detail", contract["action_critical_facts"])
                self.assertEqual(contract["known_semantic_defects"], issues)
                self.assertEqual(contract["original_requirements"], data["subject"] + "\n" + record["source"])
                self.assertEqual(audit.call_args.args[2], json.dumps(good, ensure_ascii=False))

    def test_support_repair_does_not_modify_a_valid_sibling_or_unrelated_fields(self):
        from tests.test_complex_pose_staging import CASES, pose_row
        record = RECORDS[2]; original = deepcopy(record["row"])
        sibling = pose_row(CASES[0]); sibling["index"] = 2
        preserved = deepcopy(sibling)
        good = repair_control(record)
        attempted = deepcopy(good)
        attempted["geometry"].update(framing="wide", camera_elevation="above", required_visible_parts=["face"])
        data = draft(amount=2, source_mode="guided", inputs=record["source"] + "\n" + CASES[0][1], planning_mode="Quality")
        session = Mock(); session.generate.return_value = json.dumps([attempted])
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        sibling_fact = sibling["geometry"]["pose_detail"]
        planner._accepted_scene_facts[2] = (sibling_fact,)
        with patch("goated_prompter.planning.semantic_validation.review_candidate",
                   side_effect=[SemanticValidationError(checked_issues(record)), (), (sibling_fact,)]):
            result = planner._check_scenes(session, data, dataset_assignments(data), [original, sibling], "qwen", lambda _: None)
        self.assertEqual(result, [good, preserved])
        self.assertEqual(session.generate.call_count, 1)
        self.assertNotIn(2, planner._scene_repair_contracts)
        self.assertEqual(planner._accepted_scene_facts[2], (sibling_fact,))

    def test_repaired_mechanics_still_undergo_complete_constraint_validation(self):
        record = RECORDS[2]; original = deepcopy(record["row"])
        good = repair_control(record)
        bad = deepcopy(good); bad["scene"] += " The character wears a hat."
        data = draft(amount=1, source_mode="guided", inputs=record["source"], constraints="no hat", planning_mode="Quality")
        session = Mock(); session.generate.side_effect = [json.dumps([bad]), json.dumps([good])]
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate", return_value=()) as audit:
            result = planner.repair_scene(session=session, data=data, assignments=dataset_assignments(data),
                row=original, errors=["Wrong support mechanics"], semantic_issues=checked_issues(record), progress=lambda _: None)
        self.assertEqual(result, good)
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(audit.call_count, 1)  # Forbidden candidate fails before full audit.
        self.assertEqual(json.loads(session.generate.call_args.args[0].user_message)["locked_geometry"]["framing"], "full_body")

    def test_metadata_repair_can_release_newly_diagnosed_support_fields_on_next_attempt(self):
        record = RECORDS[2]
        original = deepcopy(record["row"])
        original["geometry"]["camera_elevation"] = "invalid_elevation"
        first = deepcopy(record["row"])
        good = repair_control(record)
        issues = checked_issues(record)
        data = draft(amount=1, source_mode="guided", inputs=record["source"], planning_mode="Quality")
        session = Mock(); session.generate.side_effect = [json.dumps([first]), json.dumps([good])]
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=[SemanticValidationError(issues), ()]):
            result = planner.repair_scene(session=session, data=data, assignments=dataset_assignments(data),
                row=original, errors=["Invalid camera_elevation"], progress=lambda _: None)
        self.assertEqual(result, good)
        contexts = [json.loads(call.args[0].user_message) for call in session.generate.call_args_list]
        self.assertIn("pose_detail", contexts[0]["locked_geometry"])
        self.assertIsNotNone(contexts[0]["locked_scene_prose"])
        self.assertNotIn("pose_detail", contexts[1]["locked_geometry"])
        self.assertNotIn("contact_state", contexts[1]["locked_geometry"])
        self.assertIsNone(contexts[1]["locked_scene_prose"])
        self.assertIn("known_semantic_defects", contexts[1]["repair_contract"])

    def test_still_bad_repaired_candidate_is_not_accepted_by_valid_json(self):
        record = RECORDS[2]; issues = checked_issues(record)
        data = draft(amount=1, source_mode="guided", inputs=record["source"], planning_mode="Quality")
        session = Mock(); session.generate.return_value = json.dumps([record["row"]])
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=SemanticValidationError(issues)):
            result = planner._check_scenes(session, data, dataset_assignments(data), [deepcopy(record["row"])], "qwen", lambda _: None)[0]
        self.assertEqual(result["scene_status"], "failed")
        self.assertEqual(session.generate.call_count, 3)
        self.assertEqual(result["geometry"]["pose_detail"], record["row"]["geometry"]["pose_detail"])

    def test_generated_idea_is_supporting_data_not_original_source(self):
        record = RECORDS[2]; row = deepcopy(record["row"])
        row["idea"] = "A deliberately wrong generated summary"
        data = draft(amount=1, source_mode="guided", inputs=record["source"])
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate", return_value=()) as audit:
            planner._audit_scene(Mock(), data, dataset_assignments(data), row, "qwen")
        contract = audit.call_args.args[1]
        self.assertNotIn(row["idea"], contract["original_requirements"])
        self.assertEqual(contract["action_critical_facts"]["idea"], row["idea"])

    def test_previous_accepted_fact_cannot_lock_newly_diagnosed_bad_mechanics(self):
        record = RECORDS[2]; row = record["row"]; issues = checked_issues(record)
        data = draft(amount=1, source_mode="guided", inputs=record["source"])
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        planner._accepted_scene_facts[1] = (row["geometry"]["pose_detail"], "neutral studio floor")
        with patch("goated_prompter.planning.semantic_validation.review_candidate", side_effect=SemanticValidationError(issues)):
            with self.assertRaises(SemanticValidationError):
                planner._audit_scene(Mock(), data, dataset_assignments(data), row, "qwen")
        self.assertEqual(planner._accepted_scene_facts[1], ("neutral studio floor",))

    def test_replacement_idea_clears_prior_repair_contract_for_same_local_source(self):
        record = RECORDS[2]; row = deepcopy(record["row"])
        data = draft(amount=1, source_mode="guided", inputs=record["source"])
        planner = ScenePlanner(lambda: None, semantic_validation=True)
        planner._scene_repair_contracts[1] = {**invariant_contract(data["subject"] + "\n" + record["source"], planned=row),
                                             "previous_response": "old defective scene"}
        planner._accepted_scene_facts[1] = ("old fact",)
        row["idea"] = "A deliberately replaced short summary"
        with patch("goated_prompter.planning.semantic_validation.review_candidate", return_value=()) as audit:
            planner._audit_scene(Mock(), data, dataset_assignments(data), row, "qwen")
        self.assertNotIn("previous_response", audit.call_args.args[1])
        self.assertFalse(audit.call_args.args[1]["accepted_facts"])
        self.assertNotIn(1, planner._scene_repair_contracts)
