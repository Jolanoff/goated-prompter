"""MiniMax contracts live outside the prompting package and stay importable from older paths."""

import subprocess
import sys
import unittest

from goated_prompter import minimax, minimax_contract
from goated_prompter.prompting import minimax as prompting_minimax
from tests.support.paths import ROOT

CONTRACT_NAMES = ("default_minimax_draft", "validate_minimax_draft", "parse_reference_tokens", "parse_shot_outline",
                  "validate_analysis", "validate_output", "validate_temporal_endpoints", "frame_instruction",
                  "reference_scaffold", "requested_spoken_lines", "exact_dialogue", "reference_warnings")


class MiniMaxContractTests(unittest.TestCase):
    def test_existing_import_paths_reexport_the_contract_functions(self):
        for name in CONTRACT_NAMES:
            with self.subTest(name=name):
                self.assertIs(getattr(prompting_minimax, name), getattr(minimax_contract, name))
        for name in ("validate_minimax_draft", "default_minimax_draft", "frame_instruction", "parse_reference_tokens",
                     "parse_shot_outline", "requested_spoken_lines", "validate_analysis", "validate_output",
                     "reference_warnings"):
            with self.subTest(service_name=name):
                self.assertIs(getattr(minimax, name), getattr(minimax_contract, name))
        for name in ("analysis_instruction", "generation_instruction"):
            self.assertIs(getattr(minimax, name), getattr(prompting_minimax, name))

    def test_contract_module_does_not_load_prompt_text_or_planning(self):
        script = ("import sys, goated_prompter.minimax_contract; "
                  "print(sorted(name for name in ('goated_prompter.prompting.minimax', 'goated_prompter.planning.constraints') "
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
