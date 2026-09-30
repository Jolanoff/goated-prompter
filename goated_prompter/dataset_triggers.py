"""Trigger parsing and placement validation for Dataset prompts."""

import json
import re


def trigger_terms(trigger, connected=True):
    """Return exact required trigger terms in their configured grouping."""
    value = str(trigger or "").strip()
    if not value:
        return ()
    if connected:
        return (value,)
    terms = tuple(
        part.strip()
        for part in re.split(r"(?:[,\r\n]+|\s+and\s+)", value, flags=re.IGNORECASE)
        if part.strip()
    )
    return terms or (value,)


def _terms_are_adjacent(text, terms):
    if len(terms) < 2:
        return False
    separator = r"\s*(?:(?:,|;|/|&)|\band\b)?\s*"
    connected = separator.join(re.escape(term) for term in terms)
    return re.search(connected, text) is not None


def trigger_text_target(prompt, target):
    """Return the target field in which Dataset trigger terms must appear."""
    if target != "Ideogram4":
        return str(prompt or "").strip()
    try:
        value = json.loads(prompt)
    except (ValueError, TypeError) as exc:
        raise ValueError("The Ideogram4 result is not valid JSON.") from exc
    description = value.get("high_level_description") if isinstance(value, dict) else None
    if not isinstance(description, str):
        raise ValueError('The Ideogram4 result has no string "high_level_description" field.')
    return description.strip()


def trigger_contract_error(prompt, trigger, target, *, connected=True, at_start=False):
    """Return a placement/grouping preference issue, or None when satisfied."""
    text = trigger_text_target(prompt, target)
    terms = trigger_terms(trigger, False)
    if not terms:
        return "No trigger text or terms are configured."
    missing = [term for term in terms if term not in text]
    if missing:
        quoted = ", ".join(json.dumps(term, ensure_ascii=False) for term in missing)
        return f"The result is missing the exact required trigger term(s): {quoted}."
    configured = str(trigger or "").strip()
    if connected and configured not in text:
        return "The trigger terms are present, but the requested connected trigger phrase was not preserved."
    if at_start and not text.startswith(configured if connected else terms[0]):
        return "The trigger terms are present, but the requested beginning placement was not followed."
    if not connected and _terms_are_adjacent(text, terms):
        return (
            "The trigger terms are present, but they remained adjacent instead of being distributed "
            "through meaningful prompt positions."
        )
    return None


def trigger_presence_error(prompt, trigger, target):
    """Return an error only when required trigger content is actually absent."""
    text = trigger_text_target(prompt, target)
    terms = trigger_terms(trigger, False)
    if not terms:
        return "No trigger text or terms are configured."
    missing = [term for term in terms if term not in text]
    if not missing:
        return None
    quoted = ", ".join(json.dumps(term, ensure_ascii=False) for term in missing)
    return f"The result is missing the exact required trigger term(s): {quoted}."
