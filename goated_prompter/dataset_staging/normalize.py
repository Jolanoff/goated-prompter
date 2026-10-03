"""Lexical normalization and obvious field-specific aliases, never physics."""

import re
from .schema import GEOMETRY_FIELDS
from .vocabulary import FRAMING_ALIASES

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


def normalize_geometry(value, *, profile=None, scene=""):
    """Correct only lexical aliases and unambiguous category mistakes.

    Head orientation alone never establishes an eye direction. Conflicting
    expression/head facts stay invalid for local repair instead of being lost.
    """
    cleaned = {name: normalize_field(name, content) for name, content in value.items()}
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
        text = scene.casefold()
        if re.search(r"\b(?:mirror|reflection|collage|inset|split.screen)\b", text):
            break
        directions = {direction for direction, pattern in GAZE_PROSE.items()
                      for match in re.finditer(pattern, text)
                      if not re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$", text[max(0, match.start() - 40):match.start()])}
        if len(directions) == 1:
            cleaned["gaze_direction"] = directions.pop()
        break
    return cleaned
