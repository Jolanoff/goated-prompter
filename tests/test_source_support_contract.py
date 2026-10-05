"""Syntax-grounded source contacts; mocked reviews are not model qualification."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.planning.semantics import support_requirements
from goated_prompter.planning.semantic_validation import SemanticValidationError, support_enabled
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.scene_planner import scene_planner_instruction, scene_composer_instruction
from goated_prompter.scene_planner import ScenePlanner
from tests.test_complex_pose_support_repair import RECORDS, checked_issues, repair_control
from tests.test_dataset_quality_planning import draft


class SourceSupportContractTests(unittest.TestCase):
    def test_named_support_is_projected_from_arbitrary_source_words(self):
        for anchor in ("shoulder", "forearm", "flux", "trunnion", "pseudopod"):
            source = f"{anchor}-supported folded configuration"
            self.assertEqual(support_requirements(source), [{"source_quote": f"{anchor}-supported",
                "contact_anchor": anchor, "role": "external_contact"}])

    def test_balance_counts_are_lexical_not_anatomical_mappings(self):
        for quantity, count in (("one", 1), ("single", 1), ("two", 2), ("both", 2), ("3", 3)):
            source = f"{quantity}-vane acrobatic balance with a folded configuration"
            self.assertEqual(support_requirements(source), [{"source_quote": f"{quantity}-vane acrobatic balance",
                "contact_anchor": "vane", "role": "balance_support", "contact_count": count}])

    def test_source_quote_retains_case_and_unicode_hyphens(self):
        source = "SHOULDER‑supported pose; ONE–ARM acrobatic balance"
        requirements = support_requirements(source)
        self.assertEqual([item["source_quote"] for item in requirements], ["SHOULDER‑supported", "ONE–ARM acrobatic balance"])
        self.assertEqual([item["contact_anchor"] for item in requirements], ["shoulder", "arm"])
        self.assertTrue(all(item["source_quote"] in source for item in requirements))

    def test_negation_conditionals_alternatives_and_literals_are_not_hard_locks(self):
        for source in ('A sign reads "shoulder-supported".',
                       "<d>one-arm acrobatic balance</d>",
                       "Not shoulder-supported; seated on a bench.",
                       "Without a one-arm acrobatic balance.",
                       "If shoulder-supported, curl the legs.",
                       "A shoulder-supported pose unless suspended.",
                       "A shoulder-supported or hand-supported pose.",
                       "Maybe the performer could try one-arm acrobatic balance.",
                       "Do not use one-arm acrobatic balance."):
            with self.subTest(source=source):
                self.assertFalse(support_requirements(source))

    def test_plain_body_mentions_crop_and_viewing_side_do_not_imply_support(self):
        for source in ("Feet and hands visible beside the head.", "Waist-up curled pose.",
                       "One arm raised while the other hangs loosely.", "Rear three-quarter presentation."):
            self.assertFalse(support_requirements(source))

    def test_compiled_requirements_are_local_without_changing_assignment_envelope(self):
        data = draft(amount=2, source_mode="guided", inputs="shoulder-supported inverted pose\nclose-up, hands frame face")
        assignments = dataset_assignments(data)
        ideas = [{"index": 1, "idea": "The first pose"}, {"index": 2, "idea": "The second gesture"}]
        for instruction in (scene_planner_instruction(data, assignments), scene_composer_instruction(data, assignments, ideas)):
            context = json.loads(instruction.user_message)
            self.assertEqual(context["source_support_requirements"]["1"], support_requirements(data["inputs"].splitlines()[0]))
            self.assertFalse(context["source_support_requirements"]["2"])
            self.assertEqual([row["input"] for row in context["assignments"]], [row["input"] for row in assignments])
            self.assertIn("not merely an internal joint", instruction.system_message)

    def test_unqualified_source_checker_is_not_enabled_by_default(self):
        self.assertFalse(support_enabled({"backend": "mock"}))
        self.assertFalse(support_enabled({"backend": "openai_compatible"}))
        self.assertTrue(support_enabled({"backend": "mock", "support_validation": True}))

    def test_scoped_source_review_is_independent_of_full_technical_review(self):
        record = RECORDS[2]
        data = draft(amount=1, source_mode="guided", inputs=record["source"])
        planner = ScenePlanner(lambda: None, support_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate", return_value=()) as audit:
            planner._audit_scene(Mock(), data, dataset_assignments(data), record["row"], "qwen")
        contract = audit.call_args.args[1]
        self.assertEqual(contract["candidate_scope"], "source_support")
        self.assertEqual(contract["source_support_requirements"], support_requirements(record["source"]))
        self.assertEqual(audit.call_args.kwargs["checks"], ("action_fidelity", "scene_fidelity"))
        self.assertEqual(audit.call_count, 1)

    def test_scoped_diagnosis_can_repair_pose_without_turning_on_full_audit(self):
        record = RECORDS[2]
        data = draft(amount=1, source_mode="guided", inputs=record["source"], planning_mode="Quality")
        good = repair_control(record)
        session = Mock(); session.generate.return_value = json.dumps([good])
        planner = ScenePlanner(lambda: None, support_validation=True)
        with patch("goated_prompter.planning.semantic_validation.review_candidate",
                   side_effect=[SemanticValidationError(checked_issues(record)), ()]) as audit:
            result = planner._check_scenes(session, data, dataset_assignments(data), [deepcopy(record["row"])], "qwen", lambda _: None)[0]
        self.assertEqual(result, good)
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(audit.call_args.kwargs["checks"], ("action_fidelity", "scene_fidelity", "repair_preservation"))
        self.assertEqual(audit.call_args.args[1]["candidate_scope"], "source_support")

    def test_writer_uses_the_same_source_support_contract_in_fast_mode(self):
        record = RECORDS[2]
        row = {**repair_control(record), "input": record["source"]}
        data = draft(amount=1, source_mode="guided", inputs=record["source"], planning_mode="Fast")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=record["source"]), data, 1, plan_item=row)
        self.assertIn("SOURCE SUPPORT REQUIREMENTS", instruction.user_message)
        prompt = "person_token balances on one planted arm against the floor, one knee near a shoulder and the opposite leg extended."
        session = Mock(); session.generate.return_value = prompt
        with patch("goated_prompter.planning.semantic_validation.review_candidate", return_value=()) as audit:
            result = DatasetService({"backend": "mock", "support_validation": True}, lambda: None)._generate(
                session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result, prompt)
        self.assertEqual(audit.call_args.args[1]["candidate_scope"], "source_support")
        self.assertNotIn(row["idea"], audit.call_args.args[1]["original_requirements"])
        self.assertEqual(audit.call_args.args[1]["source_support_requirements"], support_requirements(record["source"]))
