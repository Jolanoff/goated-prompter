"""Human-only contextual rules, selected only by the Character profile."""

import re
from . import Rule, issue
from .orientation import BODY_ORIENTATION_RULES
from .framing import CHARACTER_FRAMING_RULES
from .action import CHARACTER_ACTION_RULES

FACE_COMPATIBILITY = {
    "direct_rear": frozenset("hidden mostly_hidden partial".split()),
    "rear_three_quarter_left": frozenset("hidden mostly_hidden partial profile three_quarter".split()),
    "rear_three_quarter_right": frozenset("hidden mostly_hidden partial profile three_quarter".split()),
}
OVER_SHOULDER_HEADS = frozenset(("over_left_shoulder", "over_right_shoulder"))


def rear_face(context):
    if context.reflected or context.geometry.get("pose_type") == "custom":
        return []
    g = context.geometry
    view, face, head, gaze = (g.get(field) for field in ("camera_azimuth", "face_visibility", "head_direction", "gaze_direction"))
    allowed = FACE_COMPATIBILITY.get(view)
    if allowed is None:
        return []
    turn = head in OVER_SHOULDER_HEADS
    problems = []
    if face is not None and (face not in allowed or (view == "direct_rear" and face == "partial" and not turn)):
        message = ("Direct rear camera cannot show the claimed face visibility. Choose a coherent rear camera/body/head relationship or explicit requested reflection."
                   if view == "direct_rear" else "Rear three-quarter camera needs an over-shoulder head turn and partial/three-quarter face visibility for camera gaze.")
        problems.append(issue("rear_face_visibility", ("camera_azimuth", "face_visibility", "head_direction"), message))
    if gaze == "toward_camera" and not turn:
        problems.append(issue("rear_camera_gaze", ("camera_azimuth", "gaze_direction", "head_direction"),
            "Direct rear view needs a plausible over-shoulder head turn for camera-directed gaze." if view == "direct_rear"
            else "Rear three-quarter camera needs an over-shoulder head turn and partial/three-quarter face visibility for camera gaze."))
    return problems


def head_gaze(context):
    g = context.geometry
    problems = []
    if g.get("body_orientation") == "direct_rear" and not context.reflected and g.get("pose_type") != "custom":
        if g.get("head_direction") == "toward_camera":
            problems.append(issue("rear_head_rotation", ("body_orientation", "head_direction"),
                "Direct rear body and fully camera-facing head require incompatible rotation; use a rear three-quarter shoulder turn."))
        if context.asserted(r"\b(?:full(?:y)? frontal face|face (?:is )?fully frontal)\b"):
            problems.append(issue("rear_frontal_face_prose", ("body_orientation",),
                "Direct rear body cannot show a fully frontal face; preserve the action and use coherent camera/body/head staging."))
    closed_eye_checks = {
        "eyes_closed": (r"\b(?:looking|gazing|staring) (?:directly |straight )?(?:at|toward|into)\b",
            "Eyes closed cannot simultaneously gaze toward an object or camera. Keep expression separate from gaze direction."),
        "toward_camera": (r"\b(?:eyes (?:are )?closed|closed eyes)\b",
            "Closed eyes cannot simultaneously gaze toward camera. Preserve the scene action and choose a consistent gaze."),
    }
    check = closed_eye_checks.get(g.get("gaze_direction"))
    if check and context.asserted(check[0]):
        problems.append(issue("closed_eye_gaze", ("gaze_direction",), check[1]))
    return problems


def selfie(context):
    g = context.geometry
    if g.get("pose_type") != "selfie_pose":
        return []
    problems = []
    if g.get("face_visibility") in {"hidden", "mostly_hidden"} or g.get("gaze_direction") == "away_from_camera":
        problems.append(issue("selfie_visibility", ("pose_type", "face_visibility", "gaze_direction"),
            "Selfie geometry needs a visible face and plausible camera/device relationship."))
    if context.asserted(r"\b(?:phone|device) (?:is )?(?:fully |clearly )?visible\b") and re.search(r"\b(?:phone|device) (?:is |as )?the camera\b", context.scene):
        problems.append(issue("selfie_camera_visible", ("pose_type",),
            "When the phone is the camera it cannot also appear in the image; retain a visible phone only for a mirror/external-camera selfie."))
    return problems


CHARACTER_RULES = (*BODY_ORIENTATION_RULES, *CHARACTER_FRAMING_RULES, *CHARACTER_ACTION_RULES,
                   Rule("rear_face", rear_face, "Rear three-quarter with an over-shoulder head turn, camera gaze and three-quarter face visibility is valid. Direct rear cannot show a full face without explicit reflection semantics."),
                   Rule("head_gaze", head_gaze, "Keep head direction and gaze separate. Subtle eye motion is valid; do not put emotions in gaze_direction. Orientations describe camera-relative sides, not bending/lying/pose mechanics."),
                   Rule("selfie", selfie, "A phone acting as the camera is not visible except in mirror/external-camera selfies."))
