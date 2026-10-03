"""Framing tables and deterministic crop widening; never change the fixed idea."""

import re
from . import Rule, issue

FRAMING_RANK = {
    "extreme_close_up": 0, "detail_close_up": 0, "face_close_up": 0,
    "head_and_shoulders": 1, "upper_body": 2, "waist_up": 3, "three_quarter_body": 4,
    "full_body": 5, "full_subject": 5, "full_body_with_environment": 6,
    "full_subject_with_environment": 6, "wide": 7, "extreme_wide": 8,
}
BODY_VISIBILITY_RANK = {"face_only": 0, "head_and_shoulders": 1, "upper_body": 2, "waist_up": 3, "three_quarter_body": 4, "full_body": 5}
MIN_FRAMING_FOR_DETAIL = {"feet": "full_body", "foot": "full_body", "shoes": "full_body", "shoe": "full_body", "full body": "full_body"}
WHOLE_SUBJECT_PATTERN = r"\b(?:whole|entire|complete|full) (?:product|object|subject|logo|sign|text block|landmark|building)\b"
CROP_WORDING = r"\b(?:extreme\s+close[- ]?up|detail\s+close[- ]?up|face\s+close[- ]?up|close[- ]?up|head[- ]and[- ]shoulders|upper[- ]body|waist[- ]up|three[- ]quarter[- ]body)(?:\s+(?:crop|framing|shot|view))?\b"


def minimum_framing(context):
    content = context.action + " " + context.focus
    if "character" in context.rule_groups:
        details = [frame for detail, frame in MIN_FRAMING_FOR_DETAIL.items()
                   if re.search(r"\b" + re.escape(detail).replace(r"\ ", r"[- ]") + r"\b", content)]
        return max(details, key=FRAMING_RANK.get) if details else None
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


def human_crop_visibility(context):
    g = context.geometry
    crop = g.get("framing")
    rank = FRAMING_RANK.get(crop, 99)
    problems = []
    if rank < 5 and g.get("feet_visibility", "none_visible") != "none_visible":
        problems.append(issue("feet_outside_crop", ("framing", "feet_visibility"),
            "The current framing cannot show the claimed feet. Keep the idea unchanged and choose a wider framing."))
    if rank < BODY_VISIBILITY_RANK.get(g.get("body_visibility"), 0):
        problems.append(issue("body_outside_crop", ("framing", "body_visibility"),
            "The framing cannot include the claimed body visibility. Keep the action and choose a compatible crop."))
    if crop in {"full_body", "full_body_with_environment", "full_subject", "full_subject_with_environment"} and g.get("occlusion", "none") == "none":
        for field, expected, message in (
            ("body_visibility", "full_body", "Full-body framing normally requires full_body visibility unless explicitly occluded."),
            ("feet_visibility", "both_visible", "Full-body framing must include both feet unless explicitly occluded."),
        ):
            if g.get(field, expected) != expected:
                problems.append(issue("full_frame_" + field, ("framing", field, "occlusion"), message))
    return problems


def widen_framing(context):
    geometry = dict(context.geometry)
    minimum = minimum_framing(context)
    crop = geometry.get("framing")
    if not minimum or crop not in FRAMING_RANK or FRAMING_RANK[crop] >= FRAMING_RANK[minimum]:
        return {**context.row, "geometry": geometry} if "geometry" in context.row else context.row
    geometry["framing"] = minimum
    if "camera_distance" in geometry:
        geometry["camera_distance"] = "full"
    if "character" in context.rule_groups:
        if "body_visibility" in geometry:
            geometry["body_visibility"] = "full_body"
        if "feet_visibility" in geometry and geometry.get("occlusion", "none") == "none":
            geometry["feet_visibility"] = "both_visible"
    replacement = "full-body view" if minimum == "full_body" else "whole-subject view"
    scene = re.sub(CROP_WORDING, replacement, context.row.get("scene", ""), flags=re.I)
    return {**context.row, "scene": scene, "geometry": geometry,
            "coverage_conflicts": list(dict.fromkeys([*context.row.get("coverage_conflicts", []), "framing"]))}


COMMON_FRAMING_RULES = (Rule("required_extent", requested_extent),)
CHARACTER_FRAMING_RULES = (Rule("human_crop_visibility", human_crop_visibility,
    "Framing must show required limbs/props; full-body frames normally show feet unless explicitly occluded."),)
