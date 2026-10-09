"""Shared workflow contracts stay a dependency leaf and remain importable from core."""

import subprocess
import sys
import unittest

from goated_prompter import contracts, core
from tests.support.paths import ROOT

WORKFLOW_MODULES = (
    "goated_prompter.core", "goated_prompter.dataset", "goated_prompter.minimax",
    "goated_prompter.refinement", "goated_prompter.dataset_understanding",
    "goated_prompter.workspace_api",
)


class ContractsTests(unittest.TestCase):
    def test_core_reexports_the_same_contract_objects(self):
        self.assertIs(core.GoatedPrompterRequest, contracts.GoatedPrompterRequest)
        self.assertIs(core.PromptInstruction, contracts.PromptInstruction)
        self.assertIs(core.GenerationResult, contracts.GenerationResult)
        self.assertIs(core._as_bool, contracts.as_bool)
        self.assertIs(core._effective_model_family, contracts.effective_model_family)

    def test_contracts_import_does_not_load_workflow_services(self):
        script = (
            "import sys; import goated_prompter.contracts; "
            f"loaded = sorted(set({WORKFLOW_MODULES!r}) & set(sys.modules)); "
            "print(','.join(loaded))"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "")

    def test_planning_modules_import_without_core(self):
        script = (
            "import sys; import goated_prompter.planning.video_planner, "
            "goated_prompter.planning.semantic_validation; "
            "print('goated_prompter.core' in sys.modules)"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")

    def test_boolean_coercion_is_unchanged(self):
        for value, expected in (("true", True), (" YES ", True), ("on", True), ("1", True),
                                ("false", False), ("", False), ("no", False), (1, True), (0, False), (None, False)):
            with self.subTest(value=value):
                self.assertIs(contracts.as_bool(value), expected)


if __name__ == "__main__":
    unittest.main()
