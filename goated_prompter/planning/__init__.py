"""Single-pass supporting planning, independent of Dataset batch workflows."""

from ..options.planning import PLANNING_MODES


def planning_mode(value):
    if value not in PLANNING_MODES:
        raise ValueError("Planning must be Auto, Direct or Always.")
    return value
