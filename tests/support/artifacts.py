"""Task-scoped scratch and result paths for opt-in test commands."""

from pathlib import Path
import re

from .paths import ROOT


def task_paths(task_key, test_type):
    for value in (task_key, test_type):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Task keys and test types must be lowercase names separated by hyphens.")
    return (ROOT / "quality-artifacts" / "tasks" / task_key / test_type,
            ROOT / "quality-artifacts" / "temp" / task_key / test_type)


def new_output(path, task_key, test_type):
    result, scratch = task_paths(task_key, test_type)
    path = Path(path).resolve()
    allowed = [ROOT.resolve() / root.relative_to(ROOT) for root in (result, scratch)]
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValueError("Generated output must be inside this task's quality-artifacts result or scratch directory.")
    if path.exists():
        raise ValueError("Output already exists; choose a new path or explicitly handle replacement outside the runner.")
    return path
