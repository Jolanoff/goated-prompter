"""Target-specific output contracts and lossless cleanup for creative workflows."""

import json
import re

from .prompting.target_models import get_target_capabilities
from .options.targets import canonical_target
from .minimax_format import normalize_h3_sections
from .output_repetition import MAX_ANIMA_TAGS, anima_tag_count
from .strict_json import reject_duplicate_keys


class WorkflowFormatError(ValueError):
    """The model's output needs a format-correction pass before it can be saved."""


def sanitize_prompt_text(value):
    """Trim the output boundary; target adapters own syntax transformations."""
    return str(value or "").strip()


def _unfence(value):
    if not value.startswith("```"):
        return value
    match = re.fullmatch(r"```(?:json|text|plaintext)?[ \t]*\r?\n(.*?)\r?\n```", value, re.DOTALL | re.IGNORECASE)
    if not match:
        raise WorkflowFormatError("An incomplete or unsupported output fence was returned.")
    return match.group(1).strip()


_PHOTO_ORDER = ("aesthetics", "lighting", "photo", "medium", "color_palette")
_ART_ORDER = ("aesthetics", "lighting", "medium", "art_style", "color_palette")
_ELEMENT_TYPES = ("obj", "text")  # keys in order: type, bbox, (text,) desc, color_palette


def _nonempty(item):
    return isinstance(item, str) and bool(item.strip())


def _palette(value, maximum):
    """Uppercase #RRGGBB colours (#rgb expanded), invalid entries dropped, at most maximum; None when none are left."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    colours = []
    for item in value:
        match = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})", item.strip()) if isinstance(item, str) else None
        if match:
            digits = match[1] if len(match[1]) == 6 else "".join(digit * 2 for digit in match[1])
            colours.append("#" + digits.upper())
    colours = list(dict.fromkeys(colours))[:maximum]
    return colours or None


def _boxes(elements):
    """Each element's bbox as four integers on Ideogram's 0-1000 scale, or None when it cannot be one.

    Models often write fractions (0-1) or percentages (0-100) instead of the 0-1000 scale; read literally those
    boxes squeeze every element into the top-left corner, so a caption whose boxes all fit those scales is rescaled.
    """
    raw = [element.get("bbox") for element in elements]
    numbers = [box for box in raw if isinstance(box, list) and len(box) == 4
               and all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in box)]
    values = [number for box in numbers for number in box]
    scale = 1
    if values and max(values) <= 1 and any(isinstance(number, float) for number in values):
        scale = 1000
    elif values and max(values) <= 100 and max(values) > 1:
        scale = 10
    result = []
    for box in raw:
        if not any(box is item for item in numbers):
            result.append(None)
            continue
        box = [min(1000, max(0, round(number * scale))) for number in box]
        result.append(box if box[0] < box[2] and box[1] < box[3] else None)
    return result


def _ideogram_caption(value):
    """Ideogram 4 caption JSON in the published schema: keys in the encoder's order, unknown keys dropped,
    palettes cleaned, unusable boxes dropped (the element is placed freely). Raises WorkflowFormatError
    naming what cannot be repaired."""
    if not isinstance(value, dict):
        raise WorkflowFormatError("Ideogram4 output must be one JSON caption object.")
    composition = value.get("compositional_deconstruction")
    if not isinstance(composition, dict):
        raise WorkflowFormatError("Ideogram4 caption needs compositional_deconstruction with background and elements.")
    if not _nonempty(composition.get("background")):
        raise WorkflowFormatError("Ideogram4 compositional_deconstruction.background must be a nonempty description.")
    elements = composition.get("elements")
    if not isinstance(elements, list) or not elements:
        raise WorkflowFormatError("Ideogram4 compositional_deconstruction.elements must list the subjects and objects.")
    caption = {}
    if _nonempty(value.get("high_level_description")):
        caption["high_level_description"] = value["high_level_description"].strip()
    style = value.get("style_description")
    if style is not None:
        if not isinstance(style, dict) or not all(_nonempty(style.get(key)) for key in ("aesthetics", "lighting", "medium")):
            raise WorkflowFormatError("Ideogram4 style_description needs aesthetics, lighting and medium descriptions.")
        photo, art = _nonempty(style.get("photo")), _nonempty(style.get("art_style"))
        if not photo and not art:
            raise WorkflowFormatError("Ideogram4 style_description needs photo (photographs) or art_style (other media).")
        if photo and art:  # exactly one is allowed: keep the one the medium describes
            photo = "photo" in style["medium"].casefold()
        order = _PHOTO_ORDER if photo else _ART_ORDER
        cleaned = {key: style[key].strip() for key in order if key != "color_palette" and _nonempty(style.get(key))}
        if (palette := _palette(style.get("color_palette"), 16)) is not None:
            cleaned["color_palette"] = palette
        caption["style_description"] = cleaned
    boxes = _boxes([element if isinstance(element, dict) else {} for element in elements])
    normalized = []
    for number, (element, box) in enumerate(zip(elements, boxes), 1):
        if not isinstance(element, dict):
            raise WorkflowFormatError(f"Ideogram4 element {number} must be an object.")
        kind = element.get("type")
        if kind not in _ELEMENT_TYPES:
            kind = "text" if _nonempty(element.get("text")) else "obj"
        if not _nonempty(element.get("desc")):
            raise WorkflowFormatError(f"Ideogram4 element {number} needs a nonempty desc.")
        if kind == "text" and not _nonempty(element.get("text")):
            raise WorkflowFormatError(f"Ideogram4 text element {number} needs the literal text to render.")
        item = {"type": kind}
        if box is not None:
            item["bbox"] = box
        if kind == "text":
            item["text"] = element["text"]
        item["desc"] = element["desc"].strip()
        if (palette := _palette(element.get("color_palette"), 5)) is not None:
            item["color_palette"] = palette
        normalized.append(item)
    caption["compositional_deconstruction"] = {"background": composition["background"].strip(), "elements": normalized}
    return caption


def _json_object(value):
    """The one JSON object in a reply that wraps it in a heading or closing remark, or None."""
    start, end = value.find("{"), value.rfind("}")
    return value[start:end + 1] if 0 <= start < end else None


_unique_object = reject_duplicate_keys("Duplicate JSON keys are not allowed.", WorkflowFormatError)


def ideogram_json(caption):
    """A caption serialized the way Ideogram 4 reads it: compact, with literal (not escaped) non-ASCII text."""
    return json.dumps(caption, ensure_ascii=False, separators=(",", ":"))


def requested_visible_text(text):
    """Extract only explicitly labeled quoted lettering, not arbitrary quoted ideas."""
    return tuple(match[1] if match[1] is not None else match[2] for match in re.finditer(
        r'\b(?:text|lettering|inscription|sign|label|title|slogan|reads?|says?|printed|written)\b[^\n.;"“]{0,80}(?:"([^"\n]+)"|“([^”\n]+)”)',
        text, re.I))


def normalize_workflow_output(raw, target, *, expected_visible_text=(), mode=None):
    """Unwrap simple containers; never flatten complex objects or salvage broken JSON. Ideogram4 captions are
    returned in the published schema (see _ideogram_caption), compactly serialized."""
    target = canonical_target(target)
    capabilities = get_target_capabilities(target)
    structured = capabilities.supports_structured_output
    value = _unfence(str(raw or "").strip())
    if structured and capabilities.output_format == "minimax_fields":
        # The adapter preserves non-video tasks; do not turn Dataset images or
        # captions into videos simply because H3 is selected.
        if mode is None or mode == "Video":
            try:
                return normalize_h3_sections(value)
            except ValueError as exc:
                raise WorkflowFormatError(str(exc)) from exc
        structured = False
    for _ in range(3):
        if not value:
            raise WorkflowFormatError("The prompt engine returned an empty prompt.")
        try:
            decoded = json.loads(value, object_pairs_hook=_unique_object)
        except WorkflowFormatError:
            raise
        except (ValueError, RecursionError):
            if structured:
                inner = _json_object(value)
                if inner is not None and inner != value:
                    value = inner  # a caption with a heading or remark around it; parse the caption itself
                    continue
                raise WorkflowFormatError("Ideogram4 requires one complete, valid JSON caption object.")
            # Catch incomplete wrappers and JSON preceded by a model-written heading.
            if value.startswith("{") or re.search(r'(?m)^\s*[\[{]\s*(?:["{\[]|$)', value) or "```" in value:
                raise WorkflowFormatError("This target requires prompt text, but structured or incomplete output was returned.")
            if target == "Anima" and anima_tag_count(value) > MAX_ANIMA_TAGS:
                raise WorkflowFormatError("Anima allows at most 100 tags, including supplied tags. Keep the fixed prefix, "
                                          "reduce added tags and then describe the scene normally; do not truncate the scene.")
            return value
        if structured and isinstance(decoded, str):
            value = _unfence(decoded.strip())  # the caption sent as one JSON string
            continue
        if structured:
            caption = _ideogram_caption(decoded)
            rendered = [element["text"] for element in caption["compositional_deconstruction"]["elements"]
                        if element["type"] == "text"]
            if any(literal not in rendered for literal in expected_visible_text):
                raise WorkflowFormatError("Ideogram4 literal text fields must preserve the requested text exactly.")
            return ideogram_json(caption)
        if (target == "Qwen Image 2.1" and isinstance(decoded, dict) and "rewritten_prompt" in decoded
                and set(decoded) <= {"rewritten_prompt", "wh_ratio", "ratio_follow"}
                and isinstance(decoded["rewritten_prompt"], str)):
            # Older models/saved sources may still use Qwen's rewrite envelope.
            # Only its prompt text is requested here; auxiliary fields are ignored.
            value = _unfence(decoded["rewritten_prompt"].strip())
        elif isinstance(decoded, str):
            value = _unfence(decoded.strip())
        elif isinstance(decoded, dict) and set(decoded) == {"prompt"} and isinstance(decoded["prompt"], str):
            value = _unfence(decoded["prompt"].strip())
        else:
            raise WorkflowFormatError("This target requires prompt text. A complex JSON result cannot be unwrapped without losing details.")
    raise WorkflowFormatError("The prompt engine returned nested output wrappers.")
