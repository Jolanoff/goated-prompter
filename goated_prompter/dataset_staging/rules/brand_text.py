"""Visual readability only. Exact lettering/brand protection stays in workflows."""

import re
from . import Rule, issue
from .visibility import required_readability


def brand_text_visibility(context):
    problems = required_readability(context, "logo/text element")
    if (not problems and context.geometry.get("occlusion") == "major"
            and re.search(r"\b(?:logo|mark|text|lettering|inscription)\b", context.focus)):
        problems.append(issue("mark_text_occluded", ("occlusion", "visibility_focus"),
            "Major occlusion hides a required important mark/text element. Keep it visibly readable; literal spelling is checked by the existing workflow."))
    return problems


BRAND_TEXT_RULES = (Rule("brand_text_visibility", brand_text_visibility),)
