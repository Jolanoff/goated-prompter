"""Refinement instruction contracts without endpoint execution."""

import unittest

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.refinement import refine_instruction


class RefinementInstructionTests(unittest.TestCase):
    def test_locks_target_contract_and_gemma_role_folding(self):
        request = GoatedPrompterRequest(idea="unused", target_model="LTX 2.5")
        instruction = refine_instruction(request, "Subject in motion", "Freeze the subject", ["pose"], model_family="gemma")
        self.assertIn("Locks outrank", instruction.system_message)
        self.assertIn("OUTPUT FORMAT — LTX 2.5", instruction.system_message)
        self.assertEqual(instruction.to_messages()[0]["role"], "user")
        self.assertTrue(instruction.unlimited_tokens)
