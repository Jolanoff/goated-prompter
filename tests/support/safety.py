"""Assistant test isolation; never installed in application startup."""

import os
from pathlib import Path
from contextlib import contextmanager
import tempfile
from unittest.mock import patch

from .paths import ROOT


def private_storage_guard(event, args):
    if event in {"open", "os.listdir", "os.scandir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT / "data"):
            raise PermissionError("Synthetic tests cannot access private repository storage.")


@contextmanager
def synthetic_storage(scratch):
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="storage-", dir=scratch) as temporary:
        with patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(temporary) / "directors"),
                                     "GOATED_PROMPTER_LIBRARY_DIR": str(Path(temporary) / "prompt_library")}), \
                patch.object(tempfile, "tempdir", temporary):
            yield Path(temporary)
