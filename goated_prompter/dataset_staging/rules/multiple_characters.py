"""Scene-level group checks; individual head/gaze/pose lives in prose."""

import re
from . import Rule, issue
from .visibility import required_readability
from .framing import FRAMING_RANK


def explicit_group_count(context):
    expected = context.geometry.get("primary_subject_count")
    # Only check an explicit whole-group count, not incidental numbers/props.
    counts = re.findall(r"\b(?:exactly|a total of) (\d+) (?:people|characters|persons|subjects)\b", context.action + " " + context.scene)
    if expected is not None and any(int(count) != expected for count in counts):
        return [issue("group_count_conflict", ("primary_subject_count",),
            "The explicit scene-level subject count contradicts primary_subject_count.", repair="Preserve the requested group count and keep individual staging in scene prose.")]
    return []


def group_visibility(context):
    problems = required_readability(context, "group interaction")
    g = context.geometry
    whole_group = re.search(r"\b(?:whole|entire|full) group\b|\ball (?:people|characters|subjects) (?:fully |completely )?visible\b", context.action + " " + context.focus)
    if whole_group and g.get("primary_subject_count", 1) > 1 and (FRAMING_RANK.get(g.get("framing"), 99) < 5):
        problems.append(issue("group_crop_conflict", ("primary_subject_count", "framing", "subject_scale"),
            "The requested whole group cannot fit in a detail crop. Keep the group count and use a readable scene-level framing and scale."))
    if (g.get("occlusion") == "major" and g.get("action_visibility") == "clear"
            and re.search(r"\b(?:handshake|holding hands|passing|embracing|interaction)\b", context.action)):
        problems.append(issue("group_interaction_occluded", ("occlusion", "action_visibility", "action_focus"),
            "Major occlusion conflicts with the explicitly clear required group interaction. Preserve the interaction and make it visible."))
    return problems


MULTI_CHARACTER_RULES = (Rule("explicit_group_count", explicit_group_count), Rule("group_visibility", group_visibility))
