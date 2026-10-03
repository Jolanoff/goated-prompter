"""Narrow prose contradictions, separate from structured rules and Dataset quality."""

from dataclasses import dataclass
from . import GeometryContext, Rule, issue
from ..profiles import get_profile


@dataclass(frozen=True)
class ProseCheck:
    code: str
    group: str
    fields: tuple[str, ...]
    patterns: tuple[str, ...]
    message: str
    unless: str = ""


REAR = r"\b(?:direct|straight) rear view\b|\bcamera directly behind\b"
TURN = r"\bhead (?:is )?turned (?:back )?over (?:her |his |their |one )?shoulder\b"
FRONTAL = r"\bfull(?:y)? frontal face\b|\bface (?:is )?(?:clearly )?fully frontal\b"
PROSE_CHECKS = (
    ProseCheck("rear_front_conflict", "character", ("camera_azimuth", "face_visibility"), (REAR, FRONTAL),
        "Explicit direct rear view and fully frontal face conflict without a plausible turn. Check camera/body/head geometry.", TURN),
    ProseCheck("rear_gaze_conflict", "character", ("camera_azimuth", "gaze_direction"),
        (REAR, r"\blooking (?:straight |directly )?(?:at|into) (?:the )?(?:camera|viewer)\b"),
        "Direct rear view cannot support camera-directed gaze without a plausible over-shoulder head turn.", TURN + "|" + FRONTAL),
    ProseCheck("profile_face_conflict", "character", ("camera_azimuth", "face_visibility"),
        (r"\b(?:straight |side |direct )?profile view\b|\bin profile\b", r"\bboth sides of (?:the |her |his |their )?face (?:are )?equally visible\b"),
        "A profile camera view cannot show both sides of the face equally."),
    ProseCheck("body_head_conflict", "character", ("body_orientation", "head_direction"),
        (r"\bbody (?:is )?fully facing away\b", r"\bhead (?:is )?fully frontal(?: toward (?:the )?camera)?\b"),
        "A fully away body cannot support a fully frontal head toward the camera."),
    ProseCheck("crop_visibility_conflict", "character", ("framing", "feet_visibility"),
        (r"\btight (?:face|facial) close[- ]up\b|\btight upper[- ]body crop\b", r"\b(?:shoes|feet) (?:are )?(?:clearly |fully )?visible\b|\b(?:clearly|fully) (?:showing|shows) (?:her |his |their )?(?:shoes|feet)\b"),
        "A tight face/upper-body crop cannot also clearly show feet or shoes in the same view."),
    ProseCheck("camera_direction_conflict", "common", ("camera_azimuth",),
        (r"\bcamera (?:is )?(?:directly )?in front\b", r"\bcamera (?:is )?directly behind\b"),
        "One camera is specified both directly in front and directly behind the subject."),
)


def prose_issues(context):
    return [issue(check.code, check.fields, check.message, severity="warning") for check in PROSE_CHECKS
            if (check.group == "common" or check.group in context.rule_groups)
            and all(context.asserted(pattern) for pattern in check.patterns)
            and (not check.unless or not context.asserted(check.unless))]


def explicit_geometry_issues(text, dataset_type="Character"):
    """Legacy report shape; quality may consume this, never the reverse."""
    context = GeometryContext({"scene": text}, {}, dataset_type, get_profile(dataset_type).rule_groups)
    return [{"code": problem.code, "severity": problem.severity, "message": problem.message} for problem in prose_issues(context)]


PROSE_RULES = (Rule("prose_contradictions", prose_issues),)
