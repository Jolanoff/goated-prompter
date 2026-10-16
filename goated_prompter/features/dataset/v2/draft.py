"""The Dataset tab's saved draft: its fields, defaults and validation.

Dataset V2 is the only Dataset pipeline, so the draft holds only what Understanding and a V2 run use. Drafts
saved by the retired legacy pipeline may still carry its fields (a saved scene plan, results, the plan-first
switch); they are dropped when the draft is read, and nothing on disk is rewritten until the next save.
"""

from ....options.creativity import CREATIVITY_NAMES
from ....options.dataset import DATASET_SOURCES, DATASET_TYPES, MAX_SEED, SEED_MODES
from ....options.lengths import PROMPT_LENGTH_NAMES
from ....options.styles import STYLE_NAMES
from ....options.targets import TARGET_MODEL_NAMES, canonical_target
from ....output_repetition import MAX_ANIMA_TAGS, anima_tag_count

MAX_AMOUNT = 25


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "trigger_at_start": False, "trigger_connected": True, "expand_trigger": True, "nsfw": False,
        "amount": 12,
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "constraints": "",
        "creativity": "Balanced", "style": "Auto",
        "seed": 0, "seed_mode": "randomize",
    }


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{label} must be a {'nonempty ' if required else ''}string of at most {limit} characters.")
    return value


def validate_dataset_draft(value, *, generation=False, planning=False):
    """The draft with defaults filled in; fields it does not know are dropped. generation: the draft is about to
    be analyzed or run, so required text must be present; planning: the trigger may still be empty."""
    defaults = default_dataset_draft()
    if not isinstance(value, dict):
        raise ValueError("Invalid Dataset settings fields.")
    result = {**defaults, **{key: item for key, item in value.items() if key in defaults}}
    if result["source_mode"] == "library":
        result["source_mode"] = "random"  # "From my library" was removed; ideas never come from the library.
    result["trigger"] = _text(result["trigger"], "Trigger / prepend", 1000, required=generation and not planning).strip()
    result["subject"] = _text(result["subject"], "Dataset concept", 10000, required=generation).strip()
    for key, label, limit in (("custom_type", "Custom subject kind", 120),
                              ("inputs", "Guided inputs", 50000), ("constraints", "Dataset constraints", 10000)):
        result[key] = _text(result[key], label, limit)
    for key, allowed in (("trigger_type", DATASET_TYPES), ("source_mode", DATASET_SOURCES),
                         ("creativity", CREATIVITY_NAMES), ("style", STYLE_NAMES), ("length", PROMPT_LENGTH_NAMES)):
        if not isinstance(result[key], str) or result[key] not in allowed:
            raise ValueError(f"Invalid Dataset {key}.")
    result["target"] = canonical_target(result["target"])
    if result["target"] not in TARGET_MODEL_NAMES:
        raise ValueError("Invalid target model.")
    if generation and result["target"] == "Anima" and anima_tag_count(result["trigger"], tag_only=True) > MAX_ANIMA_TAGS:
        raise ValueError("Anima allows at most 100 tags. Your supplied trigger already exceeds this limit; edit it before generating.")
    _text(result["director_preset"], "Director preset", 256)
    if type(result["seed"]) is not int or not 0 <= result["seed"] <= MAX_SEED:
        raise ValueError(f"Seed must be a whole number from 0 to {MAX_SEED}.")
    if result["seed_mode"] not in SEED_MODES:
        raise ValueError("Invalid seed mode.")
    if type(result["amount"]) is not int or not 1 <= result["amount"] <= MAX_AMOUNT:
        raise ValueError(f"Dataset prompt amount must be between 1 and {MAX_AMOUNT}.")
    for key in ("trigger_at_start", "trigger_connected", "expand_trigger", "nsfw"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be enabled or disabled.")
    if result["trigger_type"] == "Custom" and generation and not result["custom_type"].strip():
        raise ValueError("Describe the custom subject kind before generating.")
    if result["source_mode"] == "guided" and generation and not any(line.strip() for line in result["inputs"].splitlines()):
        raise ValueError("Add at least one guided input, one per line.")
    return result


def saved_dataset_draft(value):
    """A saved draft as the tab uses it now: fields of the retired pipeline are dropped, the rest validated."""
    if not isinstance(value, dict):
        raise ValueError("Invalid saved Dataset draft.")
    return validate_dataset_draft(value)
