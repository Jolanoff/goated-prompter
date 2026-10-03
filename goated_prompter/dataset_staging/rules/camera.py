"""Prose versus structured camera axes, independent of subject anatomy."""

from . import Rule, issue
from .orientation import ORIENTATION_SIDES

OPPOSITE_VIEW_PROSE = {
    "front": r"camera directly behind|direct rear view",
    "rear": r"camera (?:is )?directly in front|front camera view",
}


def camera_prose(context):
    side = ORIENTATION_SIDES.get(context.geometry.get("camera_azimuth"))
    if side in OPPOSITE_VIEW_PROSE and context.asserted(OPPOSITE_VIEW_PROSE[side]):
        return [issue("camera_prose_conflict", ("camera_azimuth",),
                      f"Scene prose contradicts the structured {side} camera view.")]
    return []


CAMERA_RULES = (Rule("camera_prose", camera_prose),)
