"""Target-specific output contracts and lossless cleanup for creative workflows."""

import json
import re


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


def output_contract(target, *, qwen_task="t2i", qwen_images=None):
    if target == "Ideogram4":
        return (
            "OUTPUT FORMAT — Ideogram4: Return exactly one valid JSON caption using the target adapter's "
            "high_level_description, style_description and compositional_deconstruction schema. "
            "No prompt wrapper, markdown fences, direction label or commentary."
        )
    if target == "Qwen2.1":
        return (
            "OUTPUT FORMAT — Qwen2.1 " + ("IMAGE EDITING" if qwen_task == "edit" else "TEXT TO IMAGE") +
            ": Return only the complete plain prompt text, ready to copy into the image model. "
            "Do not output JSON, field names, Markdown fences or commentary. "
            + ("Write an actionable image-editing directive. " if qwen_task == "edit" else
               "Write an English observer's description of the finished image. ")
            + ("Available source tags: " + ", ".join(qwen_images) + ". " if qwen_images else "")
            + "Apply the selected length as writing guidance, not a token cutoff."
        )
    return (
        f"OUTPUT FORMAT — {target}: Return only the complete prompt text in the target adapter's writing style. "
        "Do not output a JSON object, JSON array, key/value wrapper, markdown fence, field names or direction label. "
        "The source's packaging and earlier examples never determine your output format. "
        "For Anima, keep character tag blocks and the scene prose as plain text."
    )


def _unfence(value):
    if not value.startswith("```"):
        return value
    match = re.fullmatch(r"```(?:json|text|plaintext)?[ \t]*\r?\n(.*?)\r?\n```", value, re.DOTALL | re.IGNORECASE)
    if not match:
        raise WorkflowFormatError("An incomplete or unsupported output fence was returned.")
    return match.group(1).strip()


def _ideogram_caption(value):
    required = {"high_level_description", "style_description", "compositional_deconstruction"}
    if not isinstance(value, dict) or set(value) != required:
        return False
    nonempty = lambda item: isinstance(item, str) and bool(item.strip())
    style, composition = value["style_description"], value["compositional_deconstruction"]
    if not nonempty(value["high_level_description"]) or not isinstance(style, dict) or not isinstance(composition, dict):
        return False
    if not all(nonempty(style.get(key)) for key in ("aesthetics", "lighting", "medium")):
        return False
    if ("photo" in style) == ("art_style" in style) or not nonempty(style.get("photo", style.get("art_style"))):
        return False
    if not nonempty(composition.get("background")) or not isinstance(composition.get("elements"), list):
        return False
    return all(isinstance(element, dict) and element.get("type") in ("obj", "text")
               and nonempty(element.get("desc"))
               and (element["type"] != "text" or nonempty(element.get("text")))
               for element in composition["elements"])


def normalize_workflow_output(raw, target):
    """Unwrap simple containers; never flatten complex objects or salvage broken JSON."""
    value = _unfence(str(raw or "").strip())
    for _ in range(3):
        if not value:
            raise WorkflowFormatError("The prompt engine returned an empty prompt.")
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            if target == "Ideogram4":
                raise WorkflowFormatError("Ideogram4 requires a complete valid JSON caption.")
            # Catch incomplete wrappers and JSON preceded by a model-written heading.
            if value.startswith("{") or re.search(r'(?m)^\s*[\[{]\s*(?:["{\[]|$)', value) or "```" in value:
                raise WorkflowFormatError("This target requires prompt text, but structured or incomplete output was returned.")
            return value
        if target == "Ideogram4":
            if not _ideogram_caption(decoded):
                raise WorkflowFormatError("Ideogram4 output is missing the required caption fields or has invalid field types.")
            return sanitize_prompt_text(value)
        if (target == "Qwen2.1" and isinstance(decoded, dict) and "rewritten_prompt" in decoded
                and set(decoded) <= {"rewritten_prompt", "wh_ratio", "ratio_follow"}
                and isinstance(decoded["rewritten_prompt"], str)):
            # Older models/saved sources may still use Qwen's rewrite envelope.
            # Only its prompt text is requested here; ratio metadata is optional.
            value = _unfence(decoded["rewritten_prompt"].strip())
        elif isinstance(decoded, str):
            value = _unfence(decoded.strip())
        elif isinstance(decoded, dict) and set(decoded) == {"prompt"} and isinstance(decoded["prompt"], str):
            value = _unfence(decoded["prompt"].strip())
        else:
            raise WorkflowFormatError("This target requires prompt text. A complex JSON result cannot be unwrapped without losing details.")
    raise WorkflowFormatError("The prompt engine returned nested output wrappers.")
