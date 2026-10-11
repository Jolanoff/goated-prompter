"""Fixed corpus selection with a local seed, never a model-sampling override."""

from copy import deepcopy
import random


def select_cases(cases, case_ids=None, workflow=None, seed=None, limit=None):
    requested = set(case_ids or ())
    known = {case["id"] for case in cases}
    if requested - known:
        raise ValueError("Unknown case IDs: " + ", ".join(sorted(requested - known)))
    selected = [case for case in cases if (not requested or case["id"] in requested)
                and (not workflow or workflow in case.get("workflows", [case.get("workflow")]))]
    if requested and requested - {case["id"] for case in selected}:
        raise ValueError("A selected case does not support the requested workflow.")
    if seed is not None:
        random.Random(seed).shuffle(selected)
    if limit is not None:
        if limit < 1:
            raise ValueError("Case limit must be positive.")
        selected = selected[:limit]
    if not selected:
        raise ValueError("No cases match this selection.")
    return deepcopy(selected)
