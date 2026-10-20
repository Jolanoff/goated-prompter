"""Dataset triggers: the user's list of texts (LoRA tokens, character tags, style words), each saying what it is.

A trigger is {"text", "kind", "expand", "start"}:
  kind    character | style | outfit | object | other: what the text covers
  expand  off: code places the exact text and the model never describes what it covers (the text says enough)
          on: the model writes its meaning in every prompt in its own words; the text itself is not placed
          both: code places the exact text and the model also writes its meaning
  start   the text goes first in every prompt (several keep the list order); otherwise it goes where its kind
          belongs (see prompts.place_triggers)

Triggers are numbered from 1 in list order. Understanding links each character and outfit trigger to the person in
the request it belongs to (the character's "triggers"); the review shows the link before anything is written.
Drafts and briefs from before the list carry one "trigger" string and "trigger_at_start"; they read as one "other"
trigger with exact text.
"""

from ....options.dataset import MAX_TRIGGERS, TRIGGER_EXPANSIONS, TRIGGER_KINDS
from ....options.styles import OFF_STYLE

FIELDS = ("text", "kind", "expand", "start")
PERSONAL = ("character", "outfit")  # kinds that belong to one person in the image
MAX_TEXT = 1000


def legacy_trigger(text, at_start=False):
    """The one trigger of an older draft or brief, as a list."""
    text = str(text or "").strip()
    return [{"text": text, "kind": "other", "expand": "off", "start": at_start is True}] if text else []


def validate_triggers(items, *, generation=False):
    """The trigger list with whitespace trimmed. generation: the draft is about to run, so every row needs its text."""
    if not isinstance(items, list) or len(items) > MAX_TRIGGERS:
        raise ValueError(f"Triggers must be a list of at most {MAX_TRIGGERS}.")
    result = []
    for number, item in enumerate(items, 1):
        if isinstance(item, dict):
            item = {key: value for key, value in item.items() if key != "name"}  # a field this list no longer has
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError(f"Trigger {number} needs exactly {', '.join(FIELDS)}.")
        if not isinstance(item["text"], str) or len(item["text"]) > MAX_TEXT:
            raise ValueError(f"Trigger {number}: its text is at most {MAX_TEXT} characters.")
        if item["kind"] not in TRIGGER_KINDS or item["expand"] not in TRIGGER_EXPANSIONS or type(item["start"]) is not bool:
            raise ValueError(f"Trigger {number} has an unknown type or use.")
        trigger = {**item, "text": item["text"].strip()}
        if generation and not trigger["text"]:
            raise ValueError(f"Trigger {number} is empty. Write its text or remove it.")
        result.append(trigger)
    return result


def data_triggers(data):
    """The triggers of a draft (or of the raw data some callers pass): the list, else the older single trigger."""
    items = data.get("triggers")
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict) and str(item.get("text") or "").strip()]
    return legacy_trigger(data.get("trigger"), data.get("trigger_at_start"))


def brief_triggers(brief):
    """The triggers a brief was confirmed with (version 13), or its older single trigger."""
    source = brief["input"]
    if "triggers" in source:
        return list(source["triggers"])
    return legacy_trigger(source.get("trigger"), source.get("trigger_at_start"))


def trigger_text(trigger):
    """A trigger's text as it is placed: without a dangling comma that would leave an empty tag."""
    return trigger["text"].strip().rstrip(",").strip()


def placed(triggers):
    """The triggers whose exact text code places (expand off or both)."""
    return [trigger for trigger in triggers if trigger["expand"] != "on" and trigger_text(trigger)]


def personal_numbers(triggers):
    """The numbers (from 1) of the character and outfit triggers: each belongs to one person in the image."""
    return [number for number, trigger in enumerate(triggers, 1) if trigger["kind"] in PERSONAL]


def owner(brief, number):
    """The label of the character a trigger (by number) belongs to, or None."""
    return next((person["label"] for person in brief["characters"] if number in person.get("triggers", ())), None)


def run_style(brief):
    """(style, capture) for every step of a run. A style trigger of any use carries the style, so the Style setting is
    off entirely (not Auto, which Anima would still read as anime); capture only describes a Realistic image."""
    if any(trigger["kind"] == "style" for trigger in brief_triggers(brief)):
        return OFF_STYLE, "Auto"
    style = brief["settings"]["style"] or "Auto"
    return style, (brief["settings"].get("capture") or "Auto") if style == "Realistic" else "Auto"


def all_text(triggers):
    return "\n".join(trigger["text"] for trigger in triggers)
