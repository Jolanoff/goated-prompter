"""Target-specific output contracts and lossless cleanup for creative workflows."""

import json
import re

from .prompting.target_models import canonical_target, get_target_capabilities


class WorkflowFormatError(ValueError):
    """The model's output needs a format-correction pass before it can be saved."""


def sanitize_prompt_text(value):
    """Remove prompt punctuation and renderer metadata the UI does not want copied."""
    text = str(value or "")
    text = re.sub(
        r"(?i)(?:^|[,\n]\s*)\b(?:aspect\s*ratio|resolution|output\s*canvas|canvas\s*size|wh_ratio|ratio_follow)\b\s*[:=\-]?\s*(?:\d{1,5}\s*[x×:]\s*\d{1,5}|\d{1,4}\s*:\s*\d{1,4}|auto)\b\. ?",
        lambda match: "\n" if match.group(0).startswith("\n") else "",
        text,
    )
    text = text.replace(";", ",").replace("(", "").replace(")", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r",\s*,+", ", ", text)
    text = re.sub(r"^[ \t]+|[ \t]+$", "", text, flags=re.MULTILINE)
    return text.strip()


def _unfence(value):
    if not value.startswith("```"):
        return value
    match = re.fullmatch(r"```(?:json|text|plaintext)?[ \t]*\r?\n(.*?)\r?\n```", value, re.DOTALL | re.IGNORECASE)
    if not match:
        raise WorkflowFormatError("An incomplete or unsupported output fence was returned.")
    return match.group(1).strip()


def _ideogram_caption(value):
    required = ["high_level_description", "style_description", "compositional_deconstruction"]
    if not isinstance(value, dict) or list(value) != required:
        return False
    nonempty = lambda item: isinstance(item, str) and bool(item.strip())
    style, composition = value["style_description"], value["compositional_deconstruction"]
    if not nonempty(value["high_level_description"]) or not isinstance(style, dict) or not isinstance(composition, dict):
        return False
    if not all(nonempty(style.get(key)) for key in ("aesthetics", "lighting", "medium")):
        return False
    if ("photo" in style) == ("art_style" in style) or not nonempty(style.get("photo", style.get("art_style"))):
        return False
    style_order = (["aesthetics", "lighting", "photo", "medium"] if "photo" in style
                   else ["aesthetics", "lighting", "medium", "art_style"])
    if list(style) != style_order + (["color_palette"] if "color_palette" in style else []):
        return False
    def palette(item, maximum):
        return (isinstance(item, list) and len(item) <= maximum
                and all(isinstance(color, str) and re.fullmatch(r"#[0-9A-F]{6}", color) for color in item))
    if "color_palette" in style and not palette(style["color_palette"], 16):
        return False
    if list(composition) != ["background", "elements"]:
        return False
    if not nonempty(composition.get("background")) or not isinstance(composition.get("elements"), list):
        return False
    for element in composition["elements"]:
        if not isinstance(element, dict) or element.get("type") not in ("obj", "text") or not nonempty(element.get("desc")):
            return False
        keys = ["type"] + (["bbox"] if "bbox" in element else [])
        if element["type"] == "text":
            if not nonempty(element.get("text")):
                return False
            keys += ["text"]
        keys += ["desc"] + (["color_palette"] if "color_palette" in element else [])
        if list(element) != keys:
            return False
        if "bbox" in element:
            box = element["bbox"]
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(number) is not int or not 0 <= number <= 1000 for number in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                return False
        if "color_palette" in element and not palette(element["color_palette"], 5):
            return False
    return True


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowFormatError("Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def requested_visible_text(text):
    """Extract only explicitly labeled quoted lettering, not arbitrary quoted ideas."""
    return tuple(match[1] if match[1] is not None else match[2] for match in re.finditer(
        r'\b(?:text|lettering|inscription|sign|label|title|slogan|reads?|says?|printed|written)\b[^\n.;"“]{0,80}(?:"([^"\n]+)"|“([^”\n]+)”)',
        text, re.I))


def normalize_workflow_output(raw, target, *, expected_visible_text=()):
    """Unwrap simple containers; never flatten complex objects or salvage broken JSON."""
    target = canonical_target(target)
    structured = get_target_capabilities(target).output_format == "json"
    value = _unfence(str(raw or "").strip())
    for _ in range(3):
        if not value:
            raise WorkflowFormatError("The prompt engine returned an empty prompt.")
        try:
            decoded = json.loads(value, object_pairs_hook=_unique_object)
        except WorkflowFormatError:
            raise
        except (ValueError, RecursionError):
            if structured:
                raise WorkflowFormatError("Ideogram4 requires a complete valid JSON caption.")
            # Catch incomplete wrappers and JSON preceded by a model-written heading.
            if value.startswith("{") or re.search(r'(?m)^\s*[\[{]\s*(?:["{\[]|$)', value) or "```" in value:
                raise WorkflowFormatError("This target requires prompt text, but structured or incomplete output was returned.")
            return value
        if structured:
            if not _ideogram_caption(decoded):
                raise WorkflowFormatError("Ideogram4 output is missing the required caption fields or has invalid field types.")
            rendered = [element["text"] for element in decoded["compositional_deconstruction"]["elements"]
                        if element["type"] == "text"]
            if any(literal not in rendered for literal in expected_visible_text):
                raise WorkflowFormatError("Ideogram4 literal text fields must preserve the requested text exactly.")
            return value
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
