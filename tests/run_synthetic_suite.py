"""Run CPU regressions with private-storage and real-model access blocked."""

import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def private_storage_guard(event, args):
    if event in {"open", "os.listdir", "os.scandir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT / "data"):
            raise PermissionError("Synthetic tests cannot access private repository storage.")


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    logging.basicConfig(level=logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="dataset-cleanup-tests-") as temporary:
        with patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(temporary) / "directors")}), \
                patch("goated_prompter.backends.llama_cpp_process.LlamaCppProcessManager.acquire", side_effect=AssertionError("Real model loading is not allowed")):
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(sys.argv[1:]) if len(sys.argv) > 1 else loader.discover("tests", top_level_dir=".")
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            sys.exit(0 if result.wasSuccessful() else 1)
