"""Dataset-only affirmative description contract and narrow leakage checks."""

import json
import re


VISIBLE_CONTENT_CONTRACT = """VISIBLE CONTENT ONLY / POSITIVE VISUAL DESCRIPTION
Describe WHAT THE IMAGE CONTAINS, like an observer of the finished image, not what the generator
should avoid. This applies to both IDEA and SCENE and every positive final-prompt description.
Apply exclusion constraints silently through subject count, composition and visible states. Only the
woman means describe one woman, not append 'no other people in frame'. Omit absent text, logos, props,
people and defects rather than inventorying their absence. Do not copy internal validation, preservation,
quality or negative-conditioning rules into visible prose, even when they occur in user constraints,
guided input, a fallback plan, Director instructions or target conventions.
Use positive visible descriptions: a quiet sparsely furnished room; a simple background; hands resting
naturally on a table; a clear unobstructed face. Meaningful absence is allowed as a visible state:
an empty abandoned street, a deserted classroom, a bare wall, an unoccupied chair or an otherwise empty
stage. Solitude is useful only when it matters to the scene, not a mandatory repeated exclusion clause.
Do not output exclusion lists such as 'no extra people', 'no text', 'no watermark', 'no bad anatomy',
'no distorted hands', 'without any other people', 'avoid extra limbs' or 'do not show another person'.
Keep quality slogans/tags such as 'masterpiece', 'best quality', 'worst quality', 'low quality' and
'correct anatomy' internal rather than adding them to the positive description. No negative-prompt
headings or syntax. A target's dedicated negative-conditioning field, if supported separately, must
stay structurally separate; never emulate it by concatenating negatives into a positive prompt.
Preserve requested literal in-image text and protected trigger tokens exactly: their wording is visible
content or an explicit anchor, not leaked instructions. A sign reading 'NO ENTRY' is legitimate.
This Dataset rule overrides generic target/Director quality-tag and negative-guidance conventions.
"""

# Phrase patterns, not a ban on "no", "without" or "avoid" in ordinary prose.
_LEAKAGE = re.compile(
    r"\bno\s+(?:(?:other|extra|additional|duplicate)\s+(?:people|persons?|characters?|objects?|props?|limbs?|fingers?)"
    r"|(?:bad|correct)\s+anatomy|distorted\s+hands|masterpiece|text|logos?|watermarks?|signature"
    r"|blur|background\s+clutter)\b"
    r"|\bwithout\s+any\s+other\b"
    r"|\bwithout\s+(?:other|extra|additional)\s+(?:people|persons?|characters?|objects?|props?)\b"
    r"|\b(?:do\s+not|don't)\s+(?:show|include|add|render)\b"
    r"|\bavoid\s+(?:extra\s+(?:limbs|people|fingers)|distortions?|bad\s+anatomy|text|watermarks?|background\s+clutter)\b"
    r"|(?:^|[.;\n])\s*avoid\s+"
    r"|(?:^|[,;\n])\s*(?:masterpiece|best\s+quality|worst\s+quality|low\s+quality|bad\s+anatomy"
    r"|correct\s+anatomy|extra\s+limbs|watermark|signature)\s*(?=[,;.\n]|$)"
    r"|\b(?:best|worst|low)\s+quality\b"
    r"|(?:^|[,\n])\s*(?:negative\s+prompt|negative\s+conditioning)\s*:",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|(?<!\w)\'(?:\\.|[^\'\\\n])+\'(?!\w)|“[^”]*”|‘[^’]*’')


def visible_content_error(text, protected_terms=()):
    """Detect specific exclusion/meta phrases, preserving literal text and tokens."""
    for term in sorted((term for term in protected_terms if term), key=len, reverse=True):
        text = text.replace(term, "[protected anchor]")

    def quoted_content(match):
        before = text[max(0, match.start() - 80):match.start()]
        after = text[match.end():match.end() + 30]
        if (re.search(r"\b(?:reads?|reading|says?|text|lettering|inscription|labeled|printed|written|embroidered|displaying)\b[^.;\n]*$", before, re.I)
                or re.match(r"\s*(?:sign|label|lettering|inscription|text)\b", after, re.I)):
            return "[literal text]"
        return match.group(0)

    text = _QUOTED.sub(quoted_content, text)
    if _LEAKAGE.search(text):
        return "Exclusion or quality/meta language leaked into positive content. Describe the intended visible state affirmatively; apply exclusions silently."
    return None


def positive_prompt_error(prompt, target, protected_terms=()):
    """Check all Ideogram prose fields, not its keys, palettes or literal text."""
    if target != "Ideogram4":
        return visible_content_error(prompt, protected_terms)
    value = json.loads(prompt)
    descriptions = [value["high_level_description"], value["compositional_deconstruction"]["background"]]
    descriptions.extend(content for content in value["style_description"].values() if isinstance(content, str))
    descriptions.extend(element["desc"] for element in value["compositional_deconstruction"]["elements"])
    return next((error for text in descriptions
                 if (error := visible_content_error(text, protected_terms))), None)
