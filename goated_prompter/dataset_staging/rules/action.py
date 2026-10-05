"""Contextual human hand-dependent action checks; no action brainstorming."""

import re
from . import Rule, issue

HAND_ACTION_PATTERN = r"\b(?:hold\w*|juggl\w*|throw\w*|selfie|paint\w*|carry\w*|carrying)\b"


def hand_action(context):
    action, visibility = context.action, context.geometry.get("hand_visibility")
    mouth_catch = re.search(r"\bcatch\w*\b", action) and re.search(r"\bmouth\b", action)
    hand_dependent = re.search(HAND_ACTION_PATTERN, action) or (re.search(r"\bcatch\w*\b", action) and not mouth_catch)
    if not hand_dependent:
        return []
    if visibility == "none_visible":
        return [issue("hand_action_hidden", ("action_focus", "hand_visibility"),
            "This hand-dependent action needs at least one visible hand. Preserve the idea and make the interaction readable.")]
    if re.search(r"\b(?:both hands|two.handed)\b", action) and visibility in {"left_visible", "right_visible"}:
        return [issue("two_handed_action", ("action_focus", "hand_visibility"),
            "The action explicitly depends on both hands; show both hands or their readable partial visibility.")]
    return []


def custom_pose(context):
    if context.geometry.get("pose_type") == "custom" and len(context.geometry.get("pose_detail", "").split()) < 4:
        return [issue("custom_pose_detail", ("pose_detail",),
            "Custom pose requires specific physical relationships in pose_detail, not a generic label.")]
    return []


def support_contact_metadata(context):
    g = context.geometry
    # A narrow metadata contradiction, not an inferred load path. Missing,
    # unusual or ambiguous support still needs semantic/domain review.
    if g.get("pose_type") != "custom" or g.get("contact_state") != "none":
        return []
    detail = g.get("pose_detail", "")
    pattern = r"\bsupported\b|\b(?:supporting|bearing|bears)\s+(?:(?:the|their|her|his|its|full|entire|body)\s+){0,3}weight\b"
    if any(not re.search(r"\b(?:no|not|never|without)\b[^,.;:]*$", detail[max(0, match.start() - 40):match.start()], re.I)
           for match in re.finditer(pattern, detail, re.I)):
        return [issue("support_contact_metadata", ("contact_state",),
            "contact_state=none contradicts explicit weight support in pose_detail. Correct only contact metadata; preserve actual support/contact geometry and framing.")]
    return []


CHARACTER_ACTION_RULES = (Rule("hand_action", hand_action, "Hand-dependent actions need readable hands. Keep unusual action/pose details instead of replacing the fixed idea."),
                          Rule("custom_pose", custom_pose),
                          Rule("support_contact_metadata", support_contact_metadata))
