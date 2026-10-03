"""Lexical normalization and obvious field-specific aliases, never physics."""

import re
from .schema import GEOMETRY_FIELDS

FRAMING_ALIASES = {
    "close_up": "face_close_up", "closeup": "face_close_up", "face_closeup": "face_close_up",
    "medium_close_up": "upper_body", "medium_shot": "waist_up",
    "medium_full": "three_quarter_body", "cowboy_shot": "three_quarter_body",
    "long_shot": "full_body_with_environment",
}
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


def normalize_geometry(value):
    return {name: normalize_field(name, content) for name, content in value.items()}
