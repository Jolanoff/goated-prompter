"""Scene-level group checks; individual head/gaze/pose lives in prose."""

import re
from . import Rule, issue


def explicit_group_count(context):
    expected = context.geometry.get("primary_subject_count")
    # Only check an explicit whole-group count, not incidental numbers/props.
    match = re.search(r"\b(?:exactly|a total of) (\d+) (?:people|characters|persons|subjects)\b", context.scene)
    if match and expected is not None and int(match[1]) != expected:
        return [issue("group_count_conflict", ("primary_subject_count",),
            "The explicit scene-level subject count contradicts primary_subject_count.", repair="Preserve the requested group count and keep individual staging in scene prose.")]
    return []


MULTI_CHARACTER_RULES = (Rule("explicit_group_count", explicit_group_count),)
