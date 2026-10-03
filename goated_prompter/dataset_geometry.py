"""Canonical Dataset staging facts and conservative physical compatibility checks.

Orientations describe the side presented to the camera, never world-space heading.
This is a staging validator, not an anatomy or inverse-kinematics solver.
"""

import re

from .dataset_quality import explicit_geometry_issues
from .dataset_visible_content import visible_content_error


FRAMING_VALUES = frozenset("extreme_close_up face_close_up head_and_shoulders upper_body waist_up three_quarter_body full_body full_body_with_environment wide extreme_wide".split())
FRAMING_ALIASES = {
    "close_up": "face_close_up", "closeup": "face_close_up",
    "medium_close_up": "upper_body", "medium_shot": "waist_up",
    "medium_full": "three_quarter_body", "cowboy_shot": "three_quarter_body",
    "long_shot": "full_body_with_environment",
}
CAMERA_VIEW_VALUES = frozenset("front front_three_quarter profile_left profile_right rear_three_quarter_left rear_three_quarter_right direct_rear overhead high_angle low_angle extreme_close_genital close_genital between_legs from_below_crotch over_shoulder_intimate looking_down_body looking_up_body side_intimate rear_intimate top_down_intimate under_table through_legs ground_level birds_eye worms_eye ".split())
CAMERA_HEIGHT_VALUES = frozenset("ground_level knee_level waist_level chest_level eye_level slightly_above_eye_level high overhead crotch_level hip_level between_legs_level floor_looking_up".split())
CAMERA_DISTANCE_VALUES = frozenset("extreme_close close medium_close medium medium_full full long very_long macro extreme_close_detail".split())
HIP_ORIENTATION_VALUES = frozenset("front front_three_quarter front_three_quarter_left front_three_quarter_right profile_left profile_right rear_three_quarter_left rear_three_quarter_right direct_rear tilted_up tilted_down arched thrust_forward spread thrust_back closed raised_left raised_right".split())
TORSO_ORIENTATION_VALUES = HIP_ORIENTATION_VALUES | frozenset("twisted_left twisted_right bent_forward leaning_backward arched_back hunched pressed_flat twisted_strong_left twisted_strong_right leaning_over".split())
BODY_ORIENTATION_VALUES = HIP_ORIENTATION_VALUES | frozenset("bent_forward leaning_backward lying_face_up lying_face_down lying_on_left_side lying_on_right_side on_all_fours on_all_fours_arched kneeling_upright kneeling_forward bent_over bent_over_deep legs_up legs_spread legs_together one_leg_raised missionary doggy cowgirl reverse_cowgirl spooning prone_bone standing_bent_over standing_facing sitting_straddle lying_legs_open lying_legs_closed side_lying_open".split())
HEAD_DIRECTION_VALUES = frozenset("toward_camera away_from_camera left right up down up_left up_right down_left down_right toward_action toward_held_object toward_secondary_subject over_left_shoulder over_right_shoulder looking_at_partner looking_at_genital looking_down_at_self eyes_rolled head_thrown_back chin_to_chest".split())
GAZE_DIRECTION_VALUES = frozenset("toward_camera away_from_camera left right up down up_left up_right down_left down_right toward_action toward_held_object toward_secondary_subject toward_ground toward_reflection toward_background_object eyes_closed unfocused".split())
EXPRESSION_VALUES = frozenset("neutral relaxed focused concentrating curious confused surprised shocked amused submissive dominant smiling laughing playful mischievous embarrassed awkward deadpan serious determined frustrated annoyed angry worried nervous fearful excited joyful ecstatic sad disappointed disgusted skeptical confident proud sleepy exhausted strained custom".split())
POSE_TYPE_VALUES = frozenset("standing_neutral standing_relaxed standing_dynamic standing_balancing standing_leaning walking running jumping landing crouching squatting kneeling sitting_upright sitting_relaxed sitting_leaning sitting_on_floor lying_face_up lying_face_down lying_on_side reaching bending twisting dancing falling slipping climbing hanging cowgirl_leaning balancing reverse_cowgirl reverse_cowgirl_leaning spooning standing_sex side_lying straddle against_wall_lifted against_wall oral_giving oral_receiving oral_69 handjob fingering fellatio cunnilingus bent_over_table bent_over_furniture on_all_fours presenting legs_spread_sitting legs_spread_lying legs_up_lying kneeling_presenting kneeling_oral arching_back thrusting grinding riding restrained being_ridden bound spread_eagle froggy pile_driver full_nelson mating_press amazon reverse_amazon lap_sitting sitting_sex standing_lifted standing_bent_over lifting carrying throwing catching pushing pulling holding gesturing selfie_pose posed_portrait missionary missionary_legs_up missionary_legs_on_shoulders doggy_arched doggy_face_down prone_bone cowgirl doggy custom".split())
MOVEMENT_VALUES = frozenset("still subtle active fast explosive falling airborne".split())
FACE_VISIBILITY_VALUES = frozenset("full three_quarter profile partial mostly_hidden hidden".split())
BODY_VISIBILITY_VALUES = frozenset("face_only head_and_shoulders upper_body waist_up three_quarter_body full_body partial_body".split())
HAND_VISIBILITY_VALUES = frozenset("none_visible left_visible right_visible both_visible partially_visible".split())
FEET_VISIBILITY_VALUES = HAND_VISIBILITY_VALUES
SUBJECT_POSITION_VALUES = frozenset("center left right upper_left upper_right lower_left lower_right foreground midground background".split())
SUBJECT_SCALE_VALUES = frozenset("dominant large medium small environmental".split())
ACTION_VISIBILITY_VALUES = frozenset("clear partially_occluded subtle".split())
CONTACT_STATE_VALUES = frozenset("none holding touching supporting leaning_on sitting_on standing_on lying_on pushing pulling carrying wearing".split())
OCCLUSION_VALUES = frozenset("none minor moderate major".split())
DEPTH_POSITION_VALUES = frozenset("foreground same_plane midground background".split())
COMPOSITION_VALUES = frozenset("centered rule_of_thirds symmetrical asymmetrical diagonal layered environmental action_centered portrait_centered".split())
TURN_AMOUNT_VALUES = frozenset("none slight moderate strong".split())

GEOMETRY_ENUMS = {
    "framing": FRAMING_VALUES, "camera_view": CAMERA_VIEW_VALUES,
    "camera_height": CAMERA_HEIGHT_VALUES, "camera_distance": CAMERA_DISTANCE_VALUES,
    "body_orientation": BODY_ORIENTATION_VALUES, "torso_orientation": TORSO_ORIENTATION_VALUES,
    "hip_orientation": HIP_ORIENTATION_VALUES, "head_direction": HEAD_DIRECTION_VALUES,
    "gaze_direction": GAZE_DIRECTION_VALUES, "expression": EXPRESSION_VALUES,
    "pose_type": POSE_TYPE_VALUES, "movement": MOVEMENT_VALUES,
    "face_visibility": FACE_VISIBILITY_VALUES, "body_visibility": BODY_VISIBILITY_VALUES,
    "hand_visibility": HAND_VISIBILITY_VALUES, "feet_visibility": FEET_VISIBILITY_VALUES,
    "subject_position": SUBJECT_POSITION_VALUES, "subject_scale": SUBJECT_SCALE_VALUES,
    "action_visibility": ACTION_VISIBILITY_VALUES, "contact_state": CONTACT_STATE_VALUES,
    "occlusion": OCCLUSION_VALUES, "depth_position": DEPTH_POSITION_VALUES,
    "composition": COMPOSITION_VALUES, "head_turn": TURN_AMOUNT_VALUES,
}
CUSTOM_DETAIL_FIELDS = {"pose_type": "pose_detail", "expression": "expression_detail"}
FREE_TEXT_FIELDS = {"action_focus", *CUSTOM_DETAIL_FIELDS.values()}
COUNT_FIELDS = {"primary_subject_count", "secondary_subject_count"}
GEOMETRY_FIELDS = {*GEOMETRY_ENUMS, *FREE_TEXT_FIELDS, *COUNT_FIELDS, "visibility_focus"}
CHARACTER_REQUIRED_FIELDS = frozenset("framing camera_view body_orientation head_direction gaze_direction face_visibility".split())


class GeometryValidationError(ValueError):
    def __init__(self, message, correction):
        super().__init__(message)
        self.correction = correction


def _short_text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 160
            or "\n" in value or "\r" in value or "```" in value):
        raise ValueError("Geometry fields must contain short single-line descriptions.")
    if error := visible_content_error(value):
        raise ValueError(error)
    return value.strip()


def normalize_geometry_value(value):
    """Canonicalize enum spelling without guessing or translating its meaning."""
    return re.sub(r"[\s_-]+", "_", value.strip().lower()) if isinstance(value, str) else value


def validate_geometry(value, *, character=False):
    if not isinstance(value, dict) or value.keys() - GEOMETRY_FIELDS:
        raise GeometryValidationError("Geometry must be an object of supported staging fields.",
                                      "Use the supported geometry keys; replace gaze with gaze_direction and pose with pose_type.")
    if character and (missing := CHARACTER_REQUIRED_FIELDS - value.keys()):
        message = "Character geometry is missing: " + ", ".join(sorted(missing))
        raise GeometryValidationError(message, message + ". Keep the fixed idea and stage its visible action.")
    cleaned = {}
    for key, content in value.items():
        if key in COUNT_FIELDS:
            if type(content) is not int or content < 0 or (key == "primary_subject_count" and content < 1):
                raise GeometryValidationError(f"Invalid {key}; expected a {'positive' if key == 'primary_subject_count' else 'nonnegative'} integer.",
                                              f"Use an integer for {key}, not an enum or text.")
            cleaned[key] = content
        elif key == "visibility_focus":
            if not isinstance(content, list) or len(content) > 12:
                raise ValueError("Geometry visibility_focus must be a short array of visible details.")
            cleaned[key] = [_short_text(text) for text in content]
        elif key in GEOMETRY_ENUMS:
            content = normalize_geometry_value(content)
            if key == "framing" and isinstance(content, str):
                content = FRAMING_ALIASES.get(content, content)
            if not isinstance(content, str) or content not in GEOMETRY_ENUMS[key]:
                correction = ("The gaze_direction field describes where the eyes point, not emotion. "
                              "Choose an allowed gaze direction and move emotional state into expression."
                              if key == "gaze_direction" else f"Choose an allowed snake_case value for {key}.")
                raise GeometryValidationError(f"Invalid {key} {content!r}. Expected one of: {', '.join(sorted(GEOMETRY_ENUMS[key]))}.", correction)
            cleaned[key] = content
        else:
            cleaned[key] = _short_text(content)
    return cleaned


def migrate_saved_geometry(value):
    """Map only obvious legacy spellings. Ambiguous facts are omitted, not invented.

    Formatting-only normalization needs no repair. The caller marks semantic
    legacy migrations for local repair, retaining exact ideas, prose and results.
    """
    legacy_fields = {"gaze", "pose"}
    if not isinstance(value, dict) or value.keys() - (GEOMETRY_FIELDS | legacy_fields):
        return validate_geometry(value), False
    if not value.keys() & legacy_fields:
        try:
            return validate_geometry(value), False
        except ValueError:
            pass  # Retain conservative migration of old aliases below.
    legacy = bool(value.keys() & legacy_fields) or any(
        isinstance(value.get(key), str) and re.search(r"[ -]", value[key])
        for key in GEOMETRY_ENUMS)
    if not legacy:
        return validate_geometry(value), False
    cleaned = {}
    aliases = {"full_frontal": "full", "fully_frontal": "full", "full_body": "full_body",
               "face_closeup": "face_close_up", "close_up": "face_close_up"}
    for key, content in value.items():
        if key in legacy_fields:
            _short_text(content)
            if key == "gaze":
                direction = normalize_geometry_value(content)
                if direction in GAZE_DIRECTION_VALUES:
                    cleaned["gaze_direction"] = direction
                elif content.casefold().startswith("focused on "):
                    cleaned.update(gaze_direction="toward_action", expression="focused")
                elif content.casefold() in EXPRESSION_VALUES - {"custom"}:
                    cleaned["expression"] = content.casefold()
            else:
                pose = normalize_geometry_value(content)
                if pose in POSE_TYPE_VALUES - {"custom"}:
                    cleaned["pose_type"] = pose
            continue
        if key in GEOMETRY_ENUMS:
            _short_text(content)
            canonical = normalize_geometry_value(content)
            if key == "framing":
                canonical = FRAMING_ALIASES.get(canonical, canonical)
            canonical = aliases.get(canonical, canonical)
            if canonical in GEOMETRY_ENUMS[key]:
                cleaned[key] = canonical
        else:
            cleaned[key] = content
    return validate_geometry(cleaned), True


def resolve_framing_conflicts(row):
    """The fixed action wins over an incidental crop; never change the idea."""
    geometry = validate_geometry(row.get("geometry", {}))
    action = " ".join((row.get("idea", ""), geometry.get("action_focus", ""),
                       " ".join(geometry.get("visibility_focus", [])))).casefold()
    tight = geometry.get("framing") in {
        "extreme_close_up", "face_close_up", "head_and_shoulders", "upper_body", "waist_up", "three_quarter_body"}
    if not tight or not re.search(r"\b(?:shoes?|feet|foot|full.body)\b", action):
        return {**row, "geometry": geometry} if "geometry" in row else row
    geometry["framing"] = "full_body"
    if "camera_distance" in geometry:
        geometry["camera_distance"] = "full"
    if "body_visibility" in geometry:
        geometry["body_visibility"] = "full_body"
    if "feet_visibility" in geometry and geometry.get("occlusion", "none") == "none":
        geometry["feet_visibility"] = "both_visible"
    # Align only incidental crop wording, not the action, props or staging.
    scene = re.sub(r"\b(?:extreme\s+close[- ]?up|face\s+close[- ]?up|close[- ]?up|head[- ]and[- ]shoulders|upper[- ]body|waist[- ]up|three[- ]quarter[- ]body)(?:\s+(?:crop|framing|shot|view))?\b",
                   "full-body view", row.get("scene", ""), flags=re.IGNORECASE)
    return {**row, "scene": scene, "geometry": geometry,
            "coverage_conflicts": list(dict.fromkeys([*row.get("coverage_conflicts", []), "framing"]))}


def geometry_errors(row, *, character=False):
    """Flag explicit conflicts only; modest eye movement and unusual poses are valid."""
    geometry = row.get("geometry", {})
    try:
        geometry = validate_geometry(geometry, character=character)
    except ValueError as exc:
        return [getattr(exc, "correction", str(exc))]
    scene = row.get("scene", "").casefold().replace("–", "-").replace("—", "-")
    errors = [issue["message"] for issue in explicit_geometry_issues(scene)]
    reflected = bool(re.search(r"\b(?:mirror|reflection|reflected)\b", scene))
    text = "" if reflected or re.search(r"\b(?:collage|inset|split.screen)\b", scene) else scene
    def asserted(pattern):
        return any(not re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$",
                                  text[max(0, match.start() - 40):match.start()])
                   for match in re.finditer(pattern, text))
    view = geometry.get("camera_view")
    body = geometry.get("body_orientation")
    head = geometry.get("head_direction")
    gaze = geometry.get("gaze_direction")
    face = geometry.get("face_visibility")
    crop = geometry.get("framing")
    focus = " ".join(geometry.get("visibility_focus", [])).casefold()
    action = (row.get("idea", "") + " " + geometry.get("action_focus", "")).casefold()
    turn = head in {"over_left_shoulder", "over_right_shoulder"}
    if view == "direct_rear" and not reflected:
        if face in {"full", "three_quarter", "profile"} or (face == "partial" and not turn):
            errors.append("Direct rear camera cannot show the claimed face visibility. Choose a coherent rear camera/body/head relationship or explicit requested reflection.")
        if gaze == "toward_camera" and not turn:
            errors.append("Direct rear view needs a plausible over-shoulder head turn for camera-directed gaze.")
    if view in {"rear_three_quarter_left", "rear_three_quarter_right"} and not reflected:
        if face == "full" or (gaze == "toward_camera" and not turn):
            errors.append("Rear three-quarter camera needs an over-shoulder head turn and partial/three-quarter face visibility for camera gaze.")
    # Only reject clearly opposed sides; leaning/lying and oblique views stay flexible.
    orientations = {"front": "front", "front_three_quarter": "front", "direct_rear": "rear",
                    "rear_three_quarter_left": "rear", "rear_three_quarter_right": "rear"}
    body_side = "front" if body and body.startswith("front") else "rear" if body and (body.startswith("rear") or body == "direct_rear") else None
    if body_side and orientations.get(view) and body_side != orientations[view]:
        errors.append("Camera view and body orientation describe opposing sides relative to camera. Keep one coherent front/rear relationship.")
    if body in {"profile_left", "profile_right"} and view in {"profile_left", "profile_right"} and body != view:
        errors.append("Camera and body specify opposite profile sides relative to camera.")
    if {geometry.get("torso_orientation"), geometry.get("hip_orientation")} == {"front", "direct_rear"}:
        errors.append("Torso and hips require an impossible opposing front/rear twist.")
    if body == "direct_rear" and head == "toward_camera" and not reflected:
        errors.append("Direct rear body and fully camera-facing head require incompatible rotation; use a rear three-quarter shoulder turn.")
    close = crop in {"extreme_close_up", "face_close_up", "head_and_shoulders", "upper_body", "waist_up", "three_quarter_body"}
    if close and geometry.get("feet_visibility", "none_visible") != "none_visible":
        errors.append("The current framing cannot show the claimed feet. Keep the idea unchanged and choose a wider framing.")
    if close and (re.search(r"\b(?:feet|foot|shoes|full body)\b", focus) or
                  (re.search(r"\b(?:walk\w*|run\w*)\b", action) and "shoes" in action)):
        errors.append("The fixed action/shoe visibility needs a wider crop to make the central interaction readable.")
    crop_rank = {"extreme_close_up": 0, "face_close_up": 0, "head_and_shoulders": 1,
                 "upper_body": 2, "waist_up": 3, "three_quarter_body": 4}
    body_rank = {"face_only": 0, "head_and_shoulders": 1, "upper_body": 2, "waist_up": 3,
                 "three_quarter_body": 4, "full_body": 5}
    if crop in crop_rank and body_rank.get(geometry.get("body_visibility"), 0) > crop_rank[crop]:
        errors.append("The framing cannot include the claimed body visibility. Keep the action and choose a compatible crop.")
    if crop in {"full_body", "full_body_with_environment"}:
        occluded = geometry.get("occlusion") in {"minor", "moderate", "major"}
        if geometry.get("body_visibility", "full_body") != "full_body" and not occluded:
            errors.append("Full-body framing normally requires full_body visibility unless explicitly occluded.")
        if geometry.get("feet_visibility", "both_visible") != "both_visible" and not occluded:
            errors.append("Full-body framing must include both feet unless explicitly occluded.")
    hand_action = re.search(r"\b(?:hold\w*|juggl\w*|throw\w*|selfie|paint\w*|carry\w*|carrying)\b", action)
    mouth_catch = re.search(r"\bcatch\w*\b", action) and re.search(r"\bmouth\b", action)
    if geometry and (hand_action or (re.search(r"\bcatch\w*\b", action) and not mouth_catch)):
        if geometry.get("hand_visibility") == "none_visible":
            errors.append("This hand-dependent action needs at least one visible hand. Preserve the idea and make the interaction readable.")
        if re.search(r"\b(?:both hands|two.handed)\b", action) and geometry.get("hand_visibility") in {"left_visible", "right_visible"}:
            errors.append("The action explicitly depends on both hands; show both hands or their readable partial visibility.")
    if geometry.get("pose_type") == "selfie_pose":
        if face in {"hidden", "mostly_hidden"} or gaze == "away_from_camera":
            errors.append("Selfie geometry needs a visible face and plausible camera/device relationship.")
        if not reflected and asserted(r"\b(?:phone|device) (?:is )?(?:fully |clearly )?visible\b") and re.search(r"\b(?:phone|device) (?:is |as )?the camera\b", scene):
            errors.append("When the phone is the camera it cannot also appear in the image; retain a visible phone only for a mirror/external-camera selfie.")
    if gaze == "eyes_closed" and asserted(r"\b(?:looking|gazing|staring) (?:directly |straight )?(?:at|toward|into)\b"):
        errors.append("Eyes closed cannot simultaneously gaze toward an object or camera. Keep expression separate from gaze direction.")
    if gaze == "toward_camera" and asserted(r"\b(?:eyes (?:are )?closed|closed eyes)\b"):
        errors.append("Closed eyes cannot simultaneously gaze toward camera. Preserve the scene action and choose a consistent gaze.")
    if body == "direct_rear" and not reflected and asserted(r"\b(?:full(?:y)? frontal face|face (?:is )?fully frontal)\b"):
        errors.append("Direct rear body cannot show a fully frontal face; preserve the action and use coherent camera/body/head staging.")
    if view in {"front", "front_three_quarter"} and asserted(r"camera directly behind|direct rear view"):
        errors.append("Scene prose contradicts the structured front camera view.")
    if view == "direct_rear" and asserted(r"camera (?:is )?directly in front|front camera view"):
        errors.append("Scene prose contradicts the structured rear camera view.")
    return list(dict.fromkeys(errors))


def geometry_prompt_schema():
    """Compact core schema; optional enum vocabulary uses the same source of truth."""
    core = CHARACTER_REQUIRED_FIELDS | {"pose_type", "expression", "movement", "hand_visibility", "feet_visibility", "body_visibility"}
    lines = [f"{key}: {', '.join(sorted(values))}" for key, values in GEOMETRY_ENUMS.items() if key in core]
    return "\n".join(lines)
