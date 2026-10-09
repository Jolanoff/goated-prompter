"""Real raw failures plus explicitly synthetic audit verdicts/valid controls.

These prove routing/contracts, NOT model-review accuracy. Live verification is
required separately. Defining relations stay fixed; equivalent prose and compatible
lighting/material treatment may vary. Plausible role/grip/support substitution may not.
"""

from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService
from goated_prompter.minimax import MiniMaxService
from goated_prompter.planning.constraints import compile_request
from goated_prompter.planning.semantic_validation import (
    SemanticValidationError, invariant_contract, review_candidate, repair_contract,
)
from goated_prompter.prompting.minimax import validate_output, validate_analysis, validate_minimax_draft
from tests.eval.metrics import measure, useful_fact_coverage
from tests.support.paths import TESTS

FIXTURE = TESTS / "eval/fixtures/model_outputs/current_fixed_engine_failures.json"
RECORDS = {(r["case_id"], r["workflow"]):r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]}
CHECKS = ("action_fidelity", "scene_fidelity", "constraint_validity")


def verdict(checks=CHECKS, issue=None, accepted=()):
    return json.dumps({"checks": {key:"fail" if issue and issue["category"] == key else "pass" for key in checks},
                       "issues": [issue] if issue else [], "accepted_facts": list(accepted)})


def defect(category, kind, source, evidence, message="Defining invariant changed", index=0):
    return {"category":category, "kind":kind, "source_quote":source, "evidence":evidence, "message":message, "index":index}


class SequenceBackend:
    name = "synthetic-audit-frozen-output"
    def __init__(self, outputs): self.outputs, self.calls, self.events = iter(outputs), [], []
    @contextmanager
    def generation_session(self): yield self
    def validate_instruction(self, instruction): pass
    def emit_activity(self, kind, **details): self.events.append({"type":kind, **details})
    def generate(self, instruction):
        self.calls.append(instruction)
        return next(self.outputs)


class SemanticInvariantTests(unittest.TestCase):
    def test_builder_pose_detail_remains_an_action_critical_fact_without_dataset_geometry(self):
        plan = {"primary_action": "A climber reaches upward.",
                "pose_detail": "The supporting elbow remains bent."}
        contract = invariant_contract("A climber reaches upward.", planned=plan)
        self.assertEqual(contract["action_critical_facts"]["pose_detail"], plan["pose_detail"])
        self.assertNotIn("planned_geometry", contract)

    def test_captured_real_constraint_audits_replay_with_separate_issue_kinds(self):
        fixture=json.loads((FIXTURE.parent/"semantic_constraint_reviews.json").read_text(encoding="utf-8"))
        for row in fixture["records"]:
            with self.subTest(sample=row["id"]):
                contract=invariant_contract(row["source"],constraints=compile_request(row["source"],has_context=True).workflow_data())
                backend=SequenceBackend([row["raw"]])
                if row["expected_accepted"]:
                    review_candidate(backend,contract,row["candidate"],stage="captured-review",checks=("constraint_validity",))
                else:
                    with self.assertRaises(SemanticValidationError) as caught:
                        review_candidate(backend,contract,row["candidate"],stage="captured-review",checks=("constraint_validity",))
                    self.assertEqual(caught.exception.issues[0]["kind"],row["expected_issue_kind"])

    def test_long_prompt_pass_cannot_hide_synonymous_exclusion_language(self):
        source="A guard holds a sign reading \"NO ENTRY\". No hats."
        candidate="The guard wears a navy uniform, hair neatly combed back without any headwear. The sign reads \"NO ENTRY\"."
        issue=defect("constraint_validity","exclusion_leakage","No hats.","without any headwear")
        backend=SequenceBackend([verdict(("constraint_validity",),accepted=["navy uniform","without any headwear"]),
                                 verdict(("constraint_validity",),issue)])
        with self.assertRaises(SemanticValidationError) as caught:
            review_candidate(backend,invariant_contract(source,constraints=compile_request(source,has_context=True).workflow_data()),
                candidate,stage="long",checks=("constraint_validity",))
        self.assertEqual(caught.exception.accepted_facts,("navy uniform",))
        self.assertEqual(json.loads(backend.calls[1].user_message)["candidate"],"without any headwear")
        self.assertIn(":exclusion_review",backend.calls[1].diagnostic_stage)

    def test_ordinary_negation_is_reviewed_not_automatically_banned(self):
        source="A vase of flowers. No weapons."
        candidate="Flowers stand upright without visible drooping."
        backend=SequenceBackend([verdict(("constraint_validity",)),verdict(("constraint_validity",))])
        review_candidate(backend,invariant_contract(source,constraints=compile_request(source,has_context=True).workflow_data()),
            candidate,stage="ordinary",checks=("constraint_validity",))
        self.assertEqual(len(backend.calls),2)

    def test_experimental_review_is_opt_in_after_live_false_negatives(self):
        from goated_prompter.planning.semantic_validation import enabled, constraints_enabled
        self.assertFalse(enabled({"backend":"local_llama_cpp"}))
        self.assertFalse(enabled({"backend":"openai_compatible"}))
        self.assertTrue(enabled({"backend":"mock","semantic_validation":True}))
        self.assertTrue(constraints_enabled({"backend":"local_llama_cpp"}))
        self.assertFalse(constraints_enabled({"backend":"local_llama_cpp","semantic_constraints":False}))
        self.assertFalse(constraints_enabled({"backend":"mock"}))

    def test_constraint_only_gate_does_not_claim_technical_action_review(self):
        row=RECORDS[("literal","minimax")]
        bad=row["calls"][-1]["raw"]
        good=bad.replace(" and a peaked cap","")
        issue=defect("constraint_validity","forbidden_content","hats","peaked cap")
        backend=SequenceBackend([bad,verdict(("constraint_validity",),issue),good,verdict(("constraint_validity",))])
        with patch("goated_prompter.minimax.create_backend",return_value=backend):
            result=MiniMaxService({"backend":"mock","semantic_constraints":True},lambda:None).run(
                GoatedPrompterRequest(idea=row["request"]),{"user_request":row["request"],"planning_mode":"Direct"},lambda _:None)
        self.assertNotIn("peaked cap",result["prompt"])
        for instruction in (backend.calls[1],backend.calls[3]):
            self.assertEqual(json.loads(instruction.user_message)["checks"],["constraint_validity"])

    def test_fenced_review_is_normalized_but_fabricated_facts_stay_invalid(self):
        review_candidate(SequenceBackend(["```json\n" + verdict() + "\n```"]),invariant_contract("A chair."),"A chair.",stage="fence")
        bad = "```json\n" + verdict(accepted=["invented fact"]) + "\n```"
        with self.assertRaises(SemanticValidationError):
            review_candidate(SequenceBackend([bad,bad]),invariant_contract("A chair."),"A chair.",stage="fence-evidence")

    def test_six_raw_action_constraint_failures_are_auditable_without_rewriting_them(self):
        samples = [
            ("climb", "builder", "one arm locked off", "fully extended and locked off", "action_fidelity", "action_drift"),
            ("climb", "dataset", "one arm locked off", "fully extended and locked off", "action_fidelity", "action_drift"),
            ("combat", "builder", "partner balanced over the hip", "feet planted firmly on the mat", "action_fidelity", "action_drift"),
            ("combat", "dataset", "grips the other's sleeve", "sleeve with a firm underhook", "action_fidelity", "action_drift"),
            ("literal", "minimax", "no hats", "peaked cap", "constraint_validity", "forbidden_content"),
            ("dialogue", "minimax", "counterbalance holding one hand", "single hand planted firmly on the ground", "action_fidelity", "action_drift"),
        ]
        for cid, workflow, source, evidence, category, kind in samples:
            with self.subTest(case=cid, workflow=workflow):
                row = RECORDS[(cid,workflow)]
                # Exact accepted bad text from the real fixture, not a simplified surrogate.
                candidate = row["prompt"]
                contract = invariant_contract(row["request"] + "\n" + row["rules"],
                    constraints=compile_request(row["request"],has_context=True).workflow_data())
                session = SequenceBackend([verdict(issue=defect(category, kind, source, evidence))])
                with self.assertRaises(SemanticValidationError) as caught:
                    review_candidate(session, contract, candidate, stage="fixture")
                self.assertEqual(caught.exception.issues[0]["kind"], kind)
                self.assertIn(candidate, session.calls[0].user_message.replace('\\"','"').replace('\\n','\n'))

    def test_builder_rejects_raw_straight_arm_drift_and_fully_checks_repair(self):
        row = RECORDS[("climb","builder")]
        bad = row["calls"][-1]["raw"]
        good = bad.replace("fully extended and locked off", "bent at the elbow in a sustained lock-off")
        issue = defect("action_fidelity", "action_drift", "one arm locked off", "fully extended and locked off")
        backend = SequenceBackend([bad, verdict(issue=issue), good, verdict((*CHECKS,"repair_preservation"))])
        with patch("goated_prompter.core.create_backend", return_value=backend):
            result = GoatedPrompterService(config={"backend":"mock", "semantic_validation":True}).generate_text_only(
                GoatedPrompterRequest(idea=row["request"], planning_mode="Direct"))
        self.assertEqual(result.prompt, good)
        self.assertIn("LOCAL REPAIR CONTRACT", backend.calls[2].user_message)
        self.assertIn("one arm locked off", backend.calls[2].user_message)
        self.assertEqual([e["accepted"] for e in backend.events if e["type"] == "validation"], [False, True])

    def test_minimax_raw_cap_is_semantically_rejected_and_repair_keeps_literal(self):
        row = RECORDS[("literal","minimax")]
        bad = row["calls"][-1]["raw"]
        good = bad.replace(" and a peaked cap", "")
        issue = defect("constraint_validity", "forbidden_content", "hats", "peaked cap")
        checks = (*CHECKS,"temporal_fidelity")
        backend = SequenceBackend([bad, verdict(checks,issue), good, verdict((*checks,"repair_preservation"))])
        data = {"user_request":row["request"],"planning_mode":"Direct","director_preset":"general_director"}
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend":"mock","semantic_validation":True},lambda:None).run(
                GoatedPrompterRequest(idea=row["request"]),data,lambda _:None)
        self.assertNotIn("peaked cap",result["prompt"])
        self.assertIn("NO ENTRY",result["prompt"])
        self.assertIn("required",backend.calls[2].user_message)

    def test_raw_dialogue_requires_explicit_endpoint_but_dialogue_stays_exact(self):
        row = RECORDS[("dialogue","minimax")]
        data = validate_minimax_draft({"user_request":row["request"],"duration_seconds":10})
        plan = validate_analysis('{"references":[],"first_frame":null,"last_frame":null}',data)
        with self.assertRaisesRegex(ValueError,"endpoint completeness"):
            validate_output(row["calls"][-1]["raw"],data,plan)
        # Synthetic timing-only control; it STILL has wrong support mechanics and
        # must undergo the separate semantic gate before production acceptance.
        control = row["calls"][-1]["raw"].replace("overall_soundscape:", "At 00:10.000, they finish recovering balance.\n\noverall_soundscape:")
        normalized = validate_output(control,data,plan)
        self.assertIn("No, don't stop—go!",normalized)
        self.assertIn("00:10.000",normalized)

    def test_equivalent_relation_wording_can_pass_and_reverse_grip_drift_is_synthetic(self):
        source = "One athlete maintains an underhook beneath the partner's arm."
        contract = invariant_contract(source)
        valid = "The athlete's arm stays threaded beneath the partner's upper arm."
        review_candidate(SequenceBackend([verdict()]),contract,valid,stage="synthetic-equivalent")
        bad = "The athlete takes a sleeve grip instead."
        with self.assertRaises(SemanticValidationError):
            review_candidate(SequenceBackend([verdict(issue=defect("action_fidelity","action_drift","underhook","sleeve grip"))]),
                             contract,bad,stage="synthetic-reverse-grip")

    def test_fabricated_evidence_malformed_review_and_unknown_never_pass(self):
        contract = invariant_contract("A person holds a box.")
        candidate = "A person holds a box."
        wrong = verdict(issue=defect("action_fidelity","action_drift","holds a box","not in the output"))
        for responses in ([wrong,wrong],["{}","{}"]):
            with self.subTest(responses=responses),self.assertRaises(SemanticValidationError):
                review_candidate(SequenceBackend(responses),contract,candidate,stage="schema")
        unknown = json.loads(verdict(issue=defect("action_fidelity","uncertain","holds a box","", "Cannot resolve the relationship")))
        unknown["checks"]["action_fidelity"] = "unknown"
        with self.assertRaises(SemanticValidationError):
            review_candidate(SequenceBackend([json.dumps(unknown)]),contract,candidate,stage="unknown")

    def test_repair_regression_rejected_after_original_defect_fixed(self):
        contract = invariant_contract("Two workers support a pane.", accepted_facts=["Two workers"])
        issue = defect("repair_preservation","repair_regression","Two workers","one worker")
        with self.assertRaises(SemanticValidationError):
            review_candidate(SequenceBackend([verdict((*CHECKS,"repair_preservation"),issue)]),contract,
                             "A scene with one worker.",stage="repair",checks=(*CHECKS,"repair_preservation"))
        self.assertIn("Do not introduce",repair_contract(contract,"Two workers support glass.","Fix target format"))

    def test_coverage_and_repair_metrics_do_not_reward_paraphrase(self):
        before = {"useful_details":{"lighting":["left window"],"action":["hip supports partner"]}}
        after = {"useful_details":{"lighting":["left window","left window"],"action":["hip supports partner"]}}
        self.assertEqual(useful_fact_coverage(before,after)["new_useful_facts"],[])
        self.assertEqual(useful_fact_coverage(before,after)["net_useful_fact_gain"],0)
        row = {"sample_id":"repair","workflow":"dataset","prompt":"Two workers support glass.","completion_state":"completed",
               "calls":[{"stage":"dataset:1","finish_reason":"stop","validation_events":[{"type":"validation","workflow":"dataset","attempt":0,"accepted":False}]},
                        {"stage":"semantic:review:dataset:final:format_retry","finish_reason":"stop"},
                        {"stage":"dataset:1:semantic_retry_1","finish_reason":"stop","validation_events":[{"type":"validation","workflow":"dataset","attempt":1,"accepted":True}]}]}
        result = measure(row)
        self.assertEqual(result["repair_calls"],1)
        self.assertEqual(result["repair_status"],"repaired_successfully")
        self.assertFalse(result["first_pass_valid"])
        self.assertIsNone(result["repair_introduced_regression"])

    def test_contract_reuses_defining_fields_without_locking_all_scene_decoration(self):
        plan = {"scene":"A climber on warm granite in soft light.","interactions":["The right heel contacts a distinct hold."],
                "primary_action":"The supporting elbow remains bent."}
        contract = invariant_contract("A climber reaches upward.",planned=plan)
        self.assertEqual(contract["action_critical_facts"]["interactions"],plan["interactions"])
        self.assertEqual(contract["action_critical_facts"]["primary_action"],plan["primary_action"])
        self.assertNotIn("scene",contract["action_critical_facts"])
        self.assertEqual(contract["planned_scene"],plan["scene"])

    def test_audit_format_correction_receives_prior_audit_and_exact_bad_quotes(self):
        session = SequenceBackend([verdict(accepted=["made-up lighting"]),verdict(accepted=["A chair"])])
        review_candidate(session,invariant_contract("A chair."),"A chair.",stage="quote-repair")
        correction = json.loads(session.calls[1].user_message)
        self.assertIn("made-up lighting",correction["audit_format_error"])
        self.assertIn("made-up lighting",correction["previous_invalid_audit"])
        self.assertEqual(correction["candidate"],"A chair.")

    def test_reviewer_cannot_quote_contract_instructions_as_user_requirements(self):
        contract = invariant_contract("A chair.")
        issue = defect("scene_fidelity","scene_drift","supporting interpretations","A chair")
        with self.assertRaises(SemanticValidationError):
            review_candidate(SequenceBackend([verdict(issue=issue),verdict(issue=issue)]),contract,"A chair.",stage="source")

    def test_temporal_endpoint_rule_is_not_specific_to_ten_seconds(self):
        from goated_prompter.prompting.minimax import validate_temporal_endpoints
        data = {"user_request":"The subject raises a box, then sets it down at 7.25 seconds.","duration_seconds":10}
        with self.assertRaisesRegex(ValueError,"7.25"):
            validate_temporal_endpoints("[Shot 1] The subject raises and lowers a box.",data)
        validate_temporal_endpoints("[Shot 1] At 00:07.250, the box rests on the floor.",data)

    def test_semantic_rejection_does_not_become_format_or_transport_failure(self):
        row={"sample_id":"rejected","workflow":"dataset","target":"Generic","error":"wrong support",
             "completion_state":"provider_error","calls":[{"stage":"dataset:1","finish_reason":"stop","validation_events":[
             {"type":"validation","workflow":"dataset","attempt":0,"accepted":False,"format_valid":True}]}]}
        result=measure(row)
        self.assertTrue(result["format_valid"])
        self.assertTrue(result["transport_success"])
        self.assertFalse(result["accepted"])
        row["calls"][0]["finish_reason"]=None
        self.assertIsNone(measure(row)["transport_success"])

    def test_length_pairs_measure_fact_delta_and_cannot_offset_action_failure(self):
        from tests.eval.metrics import summarize, annotation_template
        common={"workflow":"dataset","case_id":"sanding","target":"Generic","director":"general_director",
                "style":"Photorealistic","creativity":"Balanced","planning":"Auto","run":1,
                "request":"A woodworker sands a chair leg.","rules":"","completion_state":"completed","anchors":{"action":["manual sanding"]}}
        low={**common,"sample_id":"detailed","length":"Detailed","prompt":"A woodworker sands a chair leg."}
        high={**common,"sample_id":"maximum","length":"Maximum Detail","prompt":"A woodworker sands a chair leg. Fine dust gathers on the bench."}
        labels=annotation_template([low,high])
        for label in labels:
            label.update(reviewer="synthetic explicit review",anchors={"action":{"manual sanding":True}},
                useful_details={"action":["manual sanding"]},target_usability=True,semantic_repetition=False,
                domain_action_relevance=True,generic_pose=False,pose_simplified=False)
        labels[1]["useful_details"]["surface"]=["fine dust gathers"]
        pair=summarize([low,high],labels)["length_coverage_pairs"][0]
        self.assertEqual(pair["new_useful_facts"],["fine dust gathers"])
        self.assertTrue(pair["useful_coverage_increased"])
        labels[1]["anchors"]["action"]["manual sanding"]=False
        self.assertFalse(summarize([low,high],labels)["length_coverage_pairs"][0]["useful_coverage_increased"])
        high["rules"]="no dust"
        self.assertEqual(summarize([low,high],labels)["length_coverage_pairs"],[])
