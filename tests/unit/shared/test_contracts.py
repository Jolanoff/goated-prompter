"""Shared workflow contracts stay a dependency leaf."""

import subprocess
import sys
import unittest

from goated_prompter import contracts
from tests.support.paths import ROOT

WORKFLOW_MODULES = (
    "goated_prompter.features.builder.service", "goated_prompter.features.dataset.service",
    "goated_prompter.features.minimax.service", "goated_prompter.features.refine.service",
    "goated_prompter.features.dataset.understanding", "goated_prompter.workflow_runners",
)


class ContractsTests(unittest.TestCase):
    def test_contracts_import_does_not_load_workflow_services(self):
        script = (
            "import sys; import goated_prompter.contracts; "
            f"loaded = sorted(set({WORKFLOW_MODULES!r}) & set(sys.modules)); "
            "print(','.join(loaded))"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "")

    def test_planning_modules_import_without_builder(self):
        script = (
            "import sys; import goated_prompter.planning.video_planner, "
            "goated_prompter.planning.semantic_validation; "
            "print('goated_prompter.features.builder.service' in sys.modules)"
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
