"""Assistant test isolation; never installed in application startup."""

import os
from pathlib import Path

from .paths import ROOT


def private_storage_guard(event, args):
    if event in {"open", "os.listdir", "os.scandir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT / "data"):
            raise PermissionError("Synthetic tests cannot access private repository storage.")
