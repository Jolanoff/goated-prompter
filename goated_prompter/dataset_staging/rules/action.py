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


CHARACTER_ACTION_RULES = (Rule("hand_action", hand_action, "Hand-dependent actions need readable hands. Keep unusual action/pose details instead of replacing the fixed idea."),)
