"""Lexical normalization and obvious field-specific aliases, never physics."""

import re
from .schema import GEOMETRY_FIELDS
from .vocabulary import FRAMING_ALIASES, BODY_PART_ALIASES, POSE_TYPE_VALUES

FIELD_ALIASES = {
    "framing": FRAMING_ALIASES,
    "camera_azimuth": {"front_facing": "front", "rear": "direct_rear"},
    "camera_elevation": {"high_angle": "high", "low_angle": "low", "birds_eye": "overhead", "worms_eye": "ground_level", "top_down": "overhead", "slightly_above_eye_level": "slightly_above"},
    "face_visibility": {"full_frontal": "full", "fully_frontal": "full"},
}


def normalize_geometry_value(value):
    return re.sub(r"[\s_-]+", "_", value.strip().lower()) if isinstance(value, str) else value


def normalize_field(name, value):
    spec = GEOMETRY_FIELDS.get(name)
    if spec is not None and spec.item_values is not None and isinstance(value, list):
        parts = [BODY_PART_ALIASES.get(normalize_geometry_value(part), normalize_geometry_value(part))
                 if isinstance(part, str) else part for part in value]
        return list(dict.fromkeys(parts)) if all(isinstance(part, str) for part in parts) else parts
    if spec is not None and spec.values is not None:
        value = normalize_geometry_value(value)
        if isinstance(value, str):
            value = FIELD_ALIASES.get(name, {}).get(value, value)
    return value


GAZE_PROSE = {
    "eyes_closed": r"\b(?:eyes (?:are )?closed|closed eyes)\b",
    "toward_camera": r"\b(?:eyes (?:are )?(?:directed|looking)|looking|gazing|staring) (?:directly |straight )?(?:at|toward|into) (?:the )?(?:camera|viewer)\b",
    "toward_ground": r"\b(?:looking|gazing|staring) (?:down )?(?:at|toward) (?:the )?ground\b",
}


def primary_subject_gaze(scene, dataset_type):
    """Infer only a single-subject Character assertion, never another actor's eyes.

    A tiny explicit grammar is intentionally incomplete. Unknown subjects,
    possessive eyes and multi-clause/multi-subject prose defer to local repair.
    """
    if dataset_type != "Character":
        return None
    text = scene.casefold().strip()
    if re.search(r"\b(?:mirror|reflection|reflected|collage|inset|split.screen|no|not|never|without|avoid)\b", text):
        return None
    subject = r"(?:she|he|the (?:woman|man|character|person|subject))"
    if not re.fullmatch(subject + r"\b[^.!?;]*[.!?]?", text):
        return None
    # A new actor, even inside a relative clause, makes ownership uncertain.
    remainder = re.sub(r"^" + subject + r"\b", "", text)
    if re.search(r"\b(?:she|he|they|whose|who|his|her|their|dog|cat|animal|child|children|woman|man|person|people|character|subject)\b", remainder):
        return None
    directions = {direction for direction, pattern in GAZE_PROSE.items() if re.search(pattern, text)}
    if len(directions) != 1:
        return None
    direction = next(iter(directions))
    pattern = GAZE_PROSE[direction]
    # Gaze must be the main predicate or a subject-preserving participle.
    owned = r"(?:^" + subject + r" (?:is )?|\bwhile )" + pattern
    return direction if re.search(owned, text) else None


def normalize_geometry(value, *, profile=None, scene=""):
    """Correct only lexical aliases and unambiguous category mistakes.

    Head orientation alone never establishes an eye direction. Conflicting
    expression/head facts stay invalid for local repair instead of being lost.
    """
    cleaned = {name: normalize_field(name, content) for name, content in value.items()}
    pose = cleaned.get("pose_type")
    detail = cleaned.get("pose_detail")
    if isinstance(pose, str) and pose.strip() and pose not in POSE_TYPE_VALUES and isinstance(detail, str) and len(detail.split()) >= 4:
        cleaned["pose_type"] = "custom"  # Preserve actual geometry, never invent a replacement.
    if cleaned.get("leg_position") == "custom" and isinstance(detail, str) and len(detail.split()) >= 4:
        # No canonical leg state is asserted by this placeholder. The actual
        # directions/bends remain in pose_detail; omit the optional helper rather
        # than invent a conventional leg arrangement or another taxonomy value.
        cleaned.pop("leg_position")
    gaze = cleaned.get("gaze_direction")
    if not isinstance(gaze, str) or gaze == "custom" or gaze in GEOMETRY_FIELDS["gaze_direction"].values:
        return cleaned
    for destination in ("expression", "head_direction"):
        if profile is not None and destination not in profile.allowed:
            continue
        values = profile.values_for(destination) if profile is not None else GEOMETRY_FIELDS[destination].values
        if gaze not in values or cleaned.get(destination, gaze) != gaze:
            continue
        cleaned[destination] = gaze
        del cleaned["gaze_direction"]
        direction = primary_subject_gaze(scene, "Character" if profile is not None and profile.rule_groups == ("character",) else None)
        if cleaned.get("secondary_subject_count", 0) or cleaned.get("primary_subject_count", 1) != 1:
            direction = None
        if direction:
            cleaned["gaze_direction"] = direction
        break
    return cleaned
