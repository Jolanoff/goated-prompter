"""Single-pass supporting planning, independent of Dataset batch workflows."""

PLANNING_MODES = ("Auto", "Direct", "Always")


def planning_mode(value):
    if value not in PLANNING_MODES:
        raise ValueError("Planning must be Auto, Direct or Always.")
    return value
