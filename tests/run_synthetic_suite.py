"""Run CPU regressions with private-storage and real-model access blocked."""

import argparse
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.safety import private_storage_guard, synthetic_storage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Fully qualified test modules, classes or methods")
    parser.add_argument("--suite", choices=("all", "unit", "integration"), default="all")
    parser.add_argument("--workflow", help="Domain directory, such as dataset, minimax or backends")
    parser.add_argument("--task-key", default="synthetic-suite")
    args = parser.parse_args(argv)
    from tests.support.artifacts import task_paths
    try:
        _, scratch = task_paths(args.task_key, "cpu")
    except ValueError as exc:
        parser.error(str(exc))
    if args.tests and (args.suite != "all" or args.workflow):
        parser.error("Use explicit test names or --suite/--workflow selection, not both.")
    starts = [ROOT / "tests"] if args.suite == "all" else [ROOT / "tests" / args.suite]
    if args.workflow:
        if args.workflow not in {path.name for suite in ("unit", "integration") for path in (ROOT / "tests" / suite).iterdir() if path.is_dir() and not path.name.startswith("_")}:
            parser.error("Unknown workflow/domain directory.")
        starts = [ROOT / "tests" / suite / args.workflow for suite in ("unit", "integration")
                  if args.suite in ("all", suite) and (ROOT / "tests" / suite / args.workflow).is_dir()]
        if not starts:
            parser.error("The selected suite has no tests for this workflow/domain.")
    logging.basicConfig(level=logging.CRITICAL)
    with synthetic_storage(scratch):
        with patch("goated_prompter.backends.llama_cpp_process.LlamaCppProcessManager.acquire", side_effect=AssertionError("Real model loading is not allowed")):
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(args.tests) if args.tests else unittest.TestSuite(
                loader.discover(str(start), top_level_dir=str(ROOT)) for start in starts)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    sys.exit(main())
