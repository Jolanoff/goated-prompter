import json
import unittest
from unittest.mock import Mock

from goated_prompter.planning.result import PlanningResult
from goated_prompter.planning.scene_planner import supporting_pass
from goated_prompter.planning.complexity import needs_planning
from goated_prompter.backends.base import BackendGenerationError


class PlanningContractTests(unittest.TestCase):
    def test_outer_contract_keeps_workflow_schema_and_direct_bypass(self):
        session = Mock()
        result = supporting_pass(session, "Direct", "a complex interaction", Mock(), Mock())
        self.assertIsInstance(result, PlanningResult)
        self.assertTrue(result.success)
        self.assertEqual(tuple(result), (None, "direct"))
        session.generate.assert_not_called()

    def test_auto_failure_is_diagnostic_and_always_error_is_clear(self):
        session = Mock()
        session.generate.side_effect = BackendGenerationError("offline")
        result = supporting_pass(session, "Auto", "two people counterbalance each other", Mock(), Mock())
        self.assertFalse(result.success)
        self.assertTrue(result.fallback_allowed)
        self.assertEqual(result.status, "fallback")
        self.assertTrue(result.warnings)
        session.emit_activity.assert_called_once()
        with self.assertRaisesRegex(BackendGenerationError, "Required scene planning failed"):
            supporting_pass(session, "Always", "a cup", Mock(), Mock())

    def test_structural_mechanics_detect_complexity_without_domain_mapping(self):
        self.assertTrue(needs_planning("One hand braces the object while the other hand rotates the tool."))
        self.assertTrue(needs_planning("Each worker supports a lower corner."))
        self.assertFalse(needs_planning('A cup with text "two people counterbalance each other".'))
