"""Dataset-only affirmative description contract and narrow leakage checks."""

import json
import re

from .prompting.target_models import canonical_target


VISIBLE_CONTENT_CONTRACT = """VISIBLE CONTENT ONLY
Describe only the visible intended image state.
Express subject count, composition, environment, anatomy, cleanliness and other constraints through positive visible description. Apply exclusions and restrictions silently rather than verbalizing what is absent or what the generator should avoid.
Do not expose internal validation rules, quality-control language, negative-conditioning instructions, preservation rules or prompt-engineering metadata in the generated positive prompt.
If the user explicitly requests rendered text, preserve that literal visible text. Protected trigger text also remains exact.
Describe the finished image itself, not instructions for preventing generation errors."""

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
    r"|(?:^|[,\n])\s*(?:negative\s+prompt|negative\s+conditioning)\s*:"
    r"|(?:^|[\n])\s*PLANNED\s+GEOMETRY\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|(?<!\w)\'(?:\\.|[^\'\\\n])+\'(?!\w)|“[^”]*”|‘[^’]*’')

# Full-clause allowlist: detection above is deliberately broader than cleanup.
# Unknown qualifiers, useful actions or scene details must be repaired by the LLM,
# not deleted along with a forbidden phrase.
_EXCLUDED_ITEM = (
    r"(?:(?:other|another|extra|additional|duplicate)\s+)?(?:people|persons?|characters?|objects?|props?|limbs?|fingers?)"
    r"|(?:bad|correct)\s+anatomy|distorted\s+hands|masterpiece|text|logos?|watermarks?|signature"
    r"|blur|background\s+clutter|distracting\s+elements|distortions?"
)
_EXCLUSION_CLAUSE = re.compile(
    r"(?:no|without|avoid|do\s+not\s+(?:show|include|add|render)|don't\s+(?:show|include|add|render))\s+"
    r"(?:any\s+)?(?:" + _EXCLUDED_ITEM + r")"
    r"(?:\s+(?:and|or)\s+(?:no\s+)?(?:" + _EXCLUDED_ITEM + r"))*"
    r"(?:\s+(?:in\s+(?:the\s+)?(?:frame|image|scene|background)|present|visible|anywhere))*",
    re.IGNORECASE,
)
_META_CLAUSE = re.compile(
    r"masterpiece|(?:best|worst|low)\s+quality|(?:bad|correct)\s+anatomy|extra\s+limbs|watermark|signature",
    re.IGNORECASE,
)


class PositiveContentError(ValueError):
    """Positive prose needs content repair, not a format/schema correction."""


def _sanitize_positive_text(text, protected_terms):
    # Mask quoted text and anchors only for boundary detection. Never modify or
    # remove a clause containing either, even when leakage appears beside it.
    spans = [match.span() for match in _QUOTED.finditer(text)]
    if text.count('"') % 2 or text.count('“') != text.count('”'):
        return text  # Unclosed literal text: boundaries cannot be trusted.
    for term in protected_terms:
        if term:
            spans.extend(match.span() for match in re.finditer(re.escape(term), text))
    masked = list(text)
    for start, end in spans:
        masked[start:end] = "x" * (end - start)
    masked = "".join(masked)
    clauses, start = [], 0
    for boundary in re.finditer(r"[,;.!?\r\n]+", masked):
        if (boundary.group() == "." and boundary.start() > 0 and boundary.end() < len(text)
                and text[boundary.start() - 1].isdigit() and text[boundary.end()].isdigit()):
            continue  # Preserve decimal lens/settings values.
        clauses.append((start, boundary.start()))
        start = boundary.end()
    clauses.append((start, len(text)))
    kept, removed = [], []
    for start, end in clauses:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        clause = text[start:end]
        protected = any(left < end and right > start for left, right in spans)
        if (not protected and visible_content_error(clause)
                and (_EXCLUSION_CLAUSE.fullmatch(clause) or _META_CLAUSE.fullmatch(clause))):
            removed.append((start, end))
        else:
            kept.append((start, end))
    if not removed:
        return text
    if not kept:
        return ""
    first, last = kept[0], kept[-1]
    result = text[first[0]:first[1]] if removed[0][0] < first[0] else text[:first[1]]
    previous_end = first[1]
    for start, end in kept[1:]:
        if any(previous_end <= left < start for left, _ in removed):
            gap = masked[previous_end:start]
            sentence = re.search(r"[.!?]", gap)
            separator = (sentence.group() + " " if sentence else "\n" if "\n" in gap
                         else "; " if ";" in gap else ", ")
            result += separator + text[start:end]
        else:
            result += text[previous_end:end]
        previous_end = end
    if removed[-1][0] > last[1]:
        ending = re.search(r"[.!?]\s*$", text)
        first_tail = next(left for left, _ in removed if left > last[1])
        preceding_ending = re.search(r"[.!?]", masked[last[1]:first_tail])
        if ending:
            result += ending.group().rstrip()
        elif preceding_ending:
            result += preceding_ending.group()
    else:
        result += text[last[1]:]
    return result


def sanitize_positive_prompt(prompt, target, protected_terms=()):
    """Remove only standalone leakage clauses, never global word replacements.

    Call after target normalization. JSON required fields are left intact if
    cleanup would empty them so the validator can request content repair.
    """
    if canonical_target(target) == "Anima":
        protected_terms = (*protected_terms, *_anima_quality_tags(prompt))
    if target != "Ideogram4":
        return _sanitize_positive_text(prompt, protected_terms)
    value = json.loads(prompt)

    def clean_field(container, key):
        original = container[key]
        if isinstance(original, str):
            cleaned = _sanitize_positive_text(original, protected_terms)
            if cleaned.strip():
                container[key] = cleaned

    clean_field(value, "high_level_description")
    for key in value["style_description"]:
        clean_field(value["style_description"], key)
    composition = value["compositional_deconstruction"]
    clean_field(composition, "background")
    for element in composition["elements"]:
        clean_field(element, "desc")
    return json.dumps(value, ensure_ascii=False)


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
    # Lazy import avoids initializing staging while this module is imported by
    # its validator. New registry fields automatically get metadata protection.
    from .dataset_staging.schema import GEOMETRY_FIELDS
    metadata = (*GEOMETRY_FIELDS, "camera_view", "camera_height", "idea_status", "scene_status", "prompt_status")
    staging_leakage = re.search(r"\b(?:" + "|".join(map(re.escape, metadata)) + r")\s*[:=]", text, re.I)
    if _LEAKAGE.search(text) or staging_leakage:
        return "Exclusion or quality/meta language leaked into positive content. Describe the intended visible state affirmatively; apply exclusions silently."
    return None


def positive_prompt_error(prompt, target, protected_terms=()):
    """Check all Ideogram prose fields, not its keys, palettes or literal text."""
    if canonical_target(target) == "Anima":
        protected_terms = (*protected_terms, *_anima_quality_tags(prompt))
    if target != "Ideogram4":
        return visible_content_error(prompt, protected_terms)
    value = json.loads(prompt)
    descriptions = [value["high_level_description"], value["compositional_deconstruction"]["background"]]
    descriptions.extend(content for content in value["style_description"].values() if isinstance(content, str))
    descriptions.extend(element["desc"] for element in value["compositional_deconstruction"]["elements"])
    return next((error for text in descriptions
                 if (error := visible_content_error(text, protected_terms))), None)


def _anima_quality_tags(text):
    """Allow supported standalone positive tags, not arbitrary quality prose."""
    return tuple(match[1] for match in re.finditer(
        r"(?:^|[,\n])\s*(masterpiece|best quality|score_\d+(?:_up)?)\s*(?=[,\n]|$)", text, re.I))
