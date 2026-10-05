"""Transport failures retry the same request, not a fabricated output defect."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_planner import ScenePlanner
from tests.test_dataset_quality_planning import draft, scene


class PlannerRetryOwnershipTests(unittest.TestCase):
    def test_transport_retry_keeps_composer_contract_and_has_no_format_correction(self):
        data = draft(amount=1)
        session = Mock()
        session.generate.side_effect = [BackendGenerationError("temporary connection failure"), json.dumps([scene()])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data,
            assignments=dataset_assignments(data), ideas=[{"index": 1, "idea": scene()["idea"]}], progress=lambda _message: None)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(result, [scene()])
        self.assertEqual(calls[1].system_message, calls[0].system_message)
        self.assertEqual(calls[1].user_message, calls[0].user_message)
        self.assertIn("transport_retry", calls[1].diagnostic_stage)

    def test_transport_during_local_repair_preserves_last_output_and_diagnosis(self):
        data = draft(amount=1)
        session = Mock()
        session.generate.side_effect = ["not JSON", BackendGenerationError("temporary connection failure"), json.dumps([scene()])]
        result = ScenePlanner(lambda: None).repair_scene(session=session, data=data,
            assignments=dataset_assignments(data), row=scene(), progress=lambda _message: None)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(result, scene())
        self.assertEqual(calls[2].system_message, calls[1].system_message)
        self.assertEqual(json.loads(calls[2].user_message)["previous_response"], "not JSON")
        self.assertNotIn("temporary connection failure", calls[2].system_message)
        self.assertEqual(session.generate.call_count, 3)
