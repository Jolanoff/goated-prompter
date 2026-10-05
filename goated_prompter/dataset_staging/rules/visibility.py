"""Explicit feature-visibility contradictions, without anatomy assumptions."""

import re
from . import Rule, issue


def focused_feature_visibility(context):
    problems = []
    for feature in context.geometry.get("visibility_focus", []):
        pattern = r"\b" + re.escape(feature.casefold()).replace("_", "[- ]") + r"\b[^.;,]{0,35}\b(?:outside (?:the )?frame|out of frame|fully hidden|completely obscured)\b"
        if context.asserted(pattern):
            problems.append(issue("required_feature_hidden", ("visibility_focus", "occlusion"),
                f"The required visible feature {feature!r} is explicitly hidden or outside the frame.",
                repair="Keep the fixed idea, requested framing and pose; make the required feature visible with compatible placement/view or occlusion."))
    return problems


def anatomical_visibility(context):
    g = context.geometry
    parts = g.get("required_visible_parts", [])
    problems = []
    if g.get("body_visibility") == "custom" and not parts:
        problems.append(issue("custom_visibility_parts", ("required_visible_parts",),
            "Custom body visibility requires explicit required_visible_parts; preserve the crop."))
    for part, field in (("feet", "feet_visibility"), ("hands", "hand_visibility")):
        if part in parts and g.get(field) == "none_visible":
            problems.append(issue("required_anatomy_hidden", (field,),
                f"Required {part} cannot also be none_visible. Preserve framing and pose geometry; correct visibility metadata."))
    if "face" in parts and g.get("face_visibility") == "hidden":
        problems.append(issue("required_anatomy_hidden", ("face_visibility",), "Required face cannot also be hidden."))
    # Reuse only explicit hidden/out-of-frame prose checks, not inferred layout.
    extra = {**g, "visibility_focus": parts}
    from dataclasses import replace
    problems.extend(focused_feature_visibility(replace(context, geometry=extra)))
    return problems


def required_readability(context, noun):
    content = context.action + " " + context.focus
    requested = re.search(r"\b(?:readable|clearly visible|unobscured|whole|entire|complete)\b", content)
    if requested and context.geometry.get("occlusion") == "major":
        return [issue("required_readability_occluded", ("occlusion", "visibility_focus"),
            f"Major occlusion conflicts with the explicitly requested readable/complete {noun}.",
            repair="Preserve the required element and make its requested features meaningfully visible.")]
    return []


VISIBILITY_RULES = (Rule("focused_feature_visibility", focused_feature_visibility),
                    Rule("anatomical_visibility", anatomical_visibility))
