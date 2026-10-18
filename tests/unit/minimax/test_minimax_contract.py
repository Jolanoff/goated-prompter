"""MiniMax contracts stay independent of MiniMax prompt text and planning."""

import subprocess
import sys
import unittest

from goated_prompter.features.minimax import contract as minimax_contract
from tests.support.paths import ROOT


class MiniMaxContractTests(unittest.TestCase):
    def test_retired_planning_setting_is_removed_without_mutating_existing_drafts(self):
        from goated_prompter.workflow_settings import empty_settings, validate_settings_store
        for mode in ("Auto", "Direct", "Always"):
            with self.subTest(mode=mode):
                draft = {**minimax_contract.default_minimax_draft(), "planning_mode": mode,
                         "user_request": "A car drives down a street.", "generated_prompt": "Saved H3 prompt."}
                store = empty_settings()
                store["minimax"].update(revision=7, draft=draft)
                loaded = validate_settings_store(store)["minimax"]
                self.assertNotIn("planning_mode", loaded["draft"])
                self.assertEqual(loaded["draft"]["generated_prompt"], "Saved H3 prompt.")
                self.assertEqual(loaded["draft"]["user_request"], draft["user_request"])
                self.assertEqual(loaded["revision"], 7)
                self.assertEqual(draft["planning_mode"], mode)

    def test_contract_module_does_not_load_prompt_text_or_planning(self):
        script = ("import sys, goated_prompter.features.minimax.contract; "
                  "print(sorted(name for name in ('goated_prompter.features.minimax.prompting', 'goated_prompter.planning.constraints') "
                  "if name in sys.modules))")
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_lazy_planning_imports_resolve_from_the_contract_module(self):
        draft = minimax_contract.validate_minimax_draft({})
        self.assertNotIn("planning_mode", draft)
        with self.assertRaisesRegex(ValueError, "Temporal endpoint completeness"):
            minimax_contract.validate_temporal_endpoints(
                "[Shot 1] A dancer spins.", {"user_request": "<shot1> 0-4s A dancer spins and stops."})


if __name__ == "__main__":
    unittest.main()
