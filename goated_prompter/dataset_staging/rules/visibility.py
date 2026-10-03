"""Explicit feature-visibility contradictions, without anatomy assumptions."""

import re
from . import Rule, issue


def focused_feature_visibility(context):
    problems = []
    for feature in context.geometry.get("visibility_focus", []):
        pattern = r"\b" + re.escape(feature.casefold()) + r"\b[^.;,]{0,35}\b(?:outside (?:the )?frame|out of frame|fully hidden|completely obscured)\b"
        if context.asserted(pattern):
            problems.append(issue("required_feature_hidden", ("visibility_focus", "framing", "occlusion"),
                f"The required visible feature {feature!r} is explicitly hidden or outside the frame.",
                repair="Keep the fixed idea and show its required feature with a compatible view, crop or occlusion."))
    return problems


def required_readability(context, noun):
    content = context.action + " " + context.focus
    requested = re.search(r"\b(?:readable|clearly visible|unobscured|whole|entire|complete)\b", content)
    if requested and context.geometry.get("occlusion") == "major":
        return [issue("required_readability_occluded", ("occlusion", "visibility_focus"),
            f"Major occlusion conflicts with the explicitly requested readable/complete {noun}.",
            repair="Preserve the required element and make its requested features meaningfully visible.")]
    return []


VISIBILITY_RULES = (Rule("focused_feature_visibility", focused_feature_visibility),)
