"""MiniMax contracts stay independent of MiniMax prompt text and planning."""

import subprocess
import sys
import unittest

from goated_prompter.features.minimax import contract as minimax_contract
from tests.support.paths import ROOT


class MiniMaxContractTests(unittest.TestCase):
    def test_contract_module_does_not_load_prompt_text_or_planning(self):
        script = ("import sys, goated_prompter.features.minimax.contract; "
                  "print(sorted(name for name in ('goated_prompter.features.minimax.prompting', 'goated_prompter.planning.constraints') "
                  "if name in sys.modules))")
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_lazy_planning_imports_resolve_from_the_contract_module(self):
        draft = minimax_contract.validate_minimax_draft({"planning_mode": "Direct"})
        self.assertEqual(draft["planning_mode"], "Direct")
        with self.assertRaisesRegex(ValueError, "Temporal endpoint completeness"):
            minimax_contract.validate_temporal_endpoints(
                "[Shot 1] A dancer spins.", {"user_request": "<shot1> 0-4s A dancer spins and stops."})


if __name__ == "__main__":
    unittest.main()
