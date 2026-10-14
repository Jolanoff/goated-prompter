"""Fidelity evidence must include passed drafts and stay scoped to one run."""

import unittest
from unittest.mock import Mock, patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.service import DatasetService
from tests.support.dataset import CaptureBackend, checked_writer_responses, saved_scene, valid_draft


class FidelityAuditTests(unittest.TestCase):
    def test_passed_draft_keeps_the_text_for_owner_labelling(self):
        data = valid_draft(amount=1)
        row = saved_scene()
        request = GoatedPrompterRequest(idea=data["subject"])
        instruction = dataset_instruction(request, data, 1, plan_item=row)
        prompt = "ohwx_person punches a training bag at station 1."
        session = Mock()
        checked_writer_responses(session, [prompt], [row])
        service = DatasetService({}, lambda: None)

        self.assertEqual(service._generate(session, instruction, data, 1, lambda _: None, row), prompt)

        self.assertEqual(service.fidelity_audit["checked"], 1)
        self.assertEqual(service.fidelity_audit["drafts"][0]["first_draft"], prompt)
        self.assertFalse(service.fidelity_audit["drafts"][0]["rewritten"])

    def test_reusing_service_starts_a_new_audit_without_mutating_the_previous_result(self):
        data = valid_draft(amount=1)
        request = GoatedPrompterRequest(idea=data["subject"])
        service = DatasetService({"backend": "mock"}, lambda: None)
        with patch("goated_prompter.features.dataset.service.create_backend", side_effect=lambda _: CaptureBackend()):
            first = service.run(request, data, lambda _: None, lambda _: None)
            second = service.run(request, data, lambda _: None, lambda _: None)

        self.assertEqual(first["completed"], 1)
        self.assertEqual(second["completed"], 1)
        self.assertEqual(first["fidelity_audit"]["checked"], 1)
        self.assertEqual(second["fidelity_audit"]["checked"], 1)
        self.assertEqual(len(first["fidelity_audit"]["drafts"]), 1)
        self.assertIsNot(first["fidelity_audit"], second["fidelity_audit"])
