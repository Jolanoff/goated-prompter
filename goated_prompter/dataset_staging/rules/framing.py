"""Compositional extent, never inferred from anatomical placement."""

import re
from . import Rule, issue
from ..vocabulary import FRAMING_VALUES, FRAMING_ALIASES

FRAMING_RANK = {
    "extreme_close_up": 0, "detail_close_up": 0, "face_close_up": 0,
    "head_and_shoulders": 1, "upper_body": 2, "waist_up": 3, "three_quarter_body": 4,
    "full_body": 5, "full_subject": 5, "full_body_with_environment": 6,
    "full_subject_with_environment": 6, "wide": 7, "extreme_wide": 8,
}


WHOLE_SUBJECT_PATTERN = r"\b(?:whole|entire|complete|full) (?:product|object|subject|logo|sign|text block|landmark|building)\b"
CROP_WORDING = r"\b(?:extreme\s+close[- ]?up|detail\s+close[- ]?up|face\s+close[- ]?up|close[- ]?up|head[- ]and[- ]shoulders|upper[- ]body|waist[- ]up|three[- ]quarter[- ]body)(?:\s+(?:crop|framing|shot|view))?\b"


# Read only explicit camera/crop labels, not the anatomy claimed visible. Use
# the canonical vocabulary rather than guessing composition from body parts.
_CROP_LABELS = sorted((FRAMING_VALUES | FRAMING_ALIASES.keys()) - {"medium"}, key=len, reverse=True)
_EXPLICIT_CROP = re.compile(r"\b(" + "|".join(
    re.escape(label).replace("_", r"[- _]+") for label in _CROP_LABELS)
    + r")\b", re.I)
_SOURCE_CROP = re.compile(r"(?:^|[,;\n])\s*(" + "|".join(
    re.escape(label).replace("_", r"[- _]+") for label in _CROP_LABELS)
    + r")(?:\s+(?:framing|composition|shot|crop|view))?\s*(?=[,;\n]|$)", re.I)


def requested_framing(source):
    """Read a standalone explicit crop tag; ambiguous prose is not classified.

    This lexical projection never derives composition from anatomy or pose.
    Conflicting crop tags remain unresolved instead of silently choosing one.
    """
    values = {FRAMING_ALIASES.get(label, label) for match in _SOURCE_CROP.finditer(source)
              for label in (re.sub(r"[- _]+", "_", match[1].casefold()),)}
    return next(iter(values)) if len(values) == 1 else None


def _crop_family(value):
    value = FRAMING_ALIASES.get(value, value)
    return value.removesuffix("_with_environment")


def framing_text_errors(text, framing, *, protected_terms=()):
    """Reject explicit different crops; missing/implicit wording stays unverified.

    This is not a semantic coverage verdict, and cannot infer a crop from visible
    feet, torso, whole-body anatomy, perspective, or camera distance alone.
    """
    if framing not in FRAMING_VALUES:
        return []
    from ...planning.rule_compiler import QUOTED
    for term in sorted((term for term in protected_terms if term), key=len, reverse=True):
        text = text.replace(term, "[protected]")
    text = QUOTED.sub("[literal]", text).replace("–", "-").replace("—", "-")
    errors = []
    for match in _EXPLICIT_CROP.finditer(text):
        label = re.sub(r"[- _]+", "_", match[1].casefold())
        # "Full body of ..." and "head and shoulders of ..." are anatomy, not
        # camera labels. Require a compositional qualifier unless the phrase
        # already explicitly names a shot/close-up. Distance alone stays separate.
        qualifier = re.match(r"\s+(?:composition\b|framing\b|view\b|shot\b|crop\b|portrait\b|is\s+framed\b)", text[match.end():], re.I)
        shot_label = label.endswith("_shot")
        closeup_label = (label.endswith("close_up") or _crop_family(label).endswith("close_up"))
        distance_label = re.match(r"\s+(?:camera\s+)?distance\b", text[match.end():], re.I)
        if distance_label or not (qualifier or shot_label or closeup_label):
            continue
        if re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$", text[max(0, match.start() - 40):match.start()], re.I):
            continue
        if _crop_family(label) != _crop_family(framing):
            errors.append(f"Explicit {match[1]!r} framing conflicts with locked {framing!r}. Preserve the locked crop and actual pose/contacts; correct only the composition wording.")
    return list(dict.fromkeys(errors))


def scene_crop(context):
    return [issue("scene_crop_drift", ("scene",), message) for message in
            framing_text_errors(context.row.get("scene", ""), context.geometry.get("framing"))]


def minimum_framing(context):
    content = (context.action + " " + context.focus).casefold()

    if "character" in context.rule_groups:
        return None  # Pose locates anatomy; no standing-body crop assumptions.

    if re.search(WHOLE_SUBJECT_PATTERN, content):
        return "full_subject"
    return None


def requested_extent(context):
    minimum = minimum_framing(context)
    crop = context.geometry.get("framing")
    if minimum and crop in FRAMING_RANK and FRAMING_RANK[crop] < FRAMING_RANK[minimum]:
        return [issue("required_detail_crop", ("framing", "visibility_focus"),
            "The fixed action or required whole-subject visibility needs a wider crop to make the central interaction readable.")]
    return []


def widen_framing(context):
    geometry = dict(context.geometry)
    minimum = minimum_framing(context)
    crop = geometry.get("framing")
    if not minimum or crop not in FRAMING_RANK or FRAMING_RANK[crop] >= FRAMING_RANK[minimum]:
        return {**context.row, "geometry": geometry} if "geometry" in context.row else context.row
    geometry["framing"] = minimum
    if "camera_distance" in geometry:
        geometry["camera_distance"] = "full"
    replacement = "full-body view" if minimum == "full_body" else "whole-subject view"
    scene = re.sub(CROP_WORDING, replacement, context.row.get("scene", ""), flags=re.I)
    return {**context.row, "scene": scene, "geometry": geometry,
            "coverage_conflicts": list(dict.fromkeys([*context.row.get("coverage_conflicts", []), "framing"]))}


COMMON_FRAMING_RULES = (Rule("required_extent", requested_extent),)
CHARACTER_FRAMING_RULES = (Rule("scene_crop", scene_crop),)
