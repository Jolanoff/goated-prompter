"""Trigger parsing and placement validation for Dataset prompts."""

import json
import re

from .planning.rule_compiler import QUOTED


_COUNT_WORDS = ("", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")


def fixed_anima_prefix(data):
    """The app owns a protected connected trigger placed before Anima scene prose."""
    if (data["target"] == "Anima" and data["trigger_connected"] and data["trigger_at_start"]
            and not data["expand_trigger"]):
        return data["trigger"].strip()
    return ""


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


def restore_numeric_trigger_spelling(prompt, trigger, target):
    """Restore only an equivalent number-word count to a supplied literal count.

    Do not add missing subjects, infer synonyms, change counts or edit lettering.
    The normal strict validator still checks the resulting exact trigger terms.
    """
    original = text = trigger_text_target(prompt, target)
    terms = trigger_terms(trigger, False)
    unquoted = QUOTED.sub(lambda match: " " * len(match[0]), text)
    if re.search(r'''["“”‘]|(?<![\w\\])'(?=\S)''', unquoted):
        # An unclosed quote makes lettering uncertain; possessives are not quotes.
        return prompt
    for term in terms:
        count = re.fullmatch(r"([1-9]|1[0-9]|20) ([A-Za-z]+(?: [A-Za-z]+)*)", term)
        if not count or _term_present(text, term, False):
            continue
        alias = _COUNT_WORDS[int(count[1])] + " " + count[2]
        protected = [match.span() for match in QUOTED.finditer(text)]
        for required in terms:
            protected.extend(match.span() for match in re.finditer(re.escape(required), text))
        pattern = re.compile(r"(?<![\w'’\-–—])" + re.escape(alias) + r"(?![\w'’\-–—])", re.IGNORECASE)
        def replace_count(match):
            if re.search(r"(?:\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)"
                    r"(?:\s+(?:and|&))?\s+|\bpoint\s+|\d\.\s*)$", text[:match.start()], re.IGNORECASE):
                return match[0]  # Never reinterpret the tail of a compound number.
            if any(start < match.end() and end > match.start() for start, end in protected):
                return match[0]
            return term
        text = pattern.sub(replace_count, text)
    if text == original:
        return prompt
    if target != "Ideogram4":
        return text
    caption = json.loads(prompt)
    caption["high_level_description"] = text
    return json.dumps(caption, ensure_ascii=False)


def _expanded_term_spans(text, term):
    """Conservative lexical subject matching, not semantic equivalence.

    Articles and inserted descriptive words may vary. Subject/attribute words
    stay intact and in order; punctuation and conjunctions cannot bridge two
    unrelated clauses. Custom identifier spelling stays protected. Bounded
    token transitions avoid exponential backtracking on repeated long phrases.
    """
    matches = [match for match in re.finditer(r"\w+(?:[-']\w+)*", term)
               if match.group().casefold() not in {"a", "an", "the"}]
    if not matches:
        return [match.span() for match in re.finditer(re.escape(term), text)]
    tokens = list(re.finditer(r"\w+(?:[-']\w+)*", text))
    word = r"(?!(?:and|or|but|while|with|beside)\b)\w+(?:[-']\w+)*"
    gap = r"(?:\s+" + word + r"){0,6}\s+"
    positions = {}
    for number, current in enumerate(matches):
        anchor = current.group()
        protected = "_" in anchor or (re.search(r"[A-Za-z]", anchor) and re.search(r"\d", anchor))
        key = anchor if protected else anchor.casefold()
        join, distance = gap, 7
        if number and (separator := re.search(r"[,;/&]", term[matches[number - 1].end():current.start()])):
            join = r"(?:\s+" + word + r"){0,6}\s*" + re.escape(separator.group()) + r"\s*(?:" + word + r"\s+){0,6}"
            distance = 13
        next_positions = {}
        for index, token in enumerate(tokens):
            if (token.group() if protected else token.group().casefold()) != key:
                continue
            if not number:
                next_positions[index] = token.start()
                continue
            starts = [positions[previous] for previous in range(max(0, index - distance), index)
                      if previous in positions and re.fullmatch(join, text[tokens[previous].end():token.start()], re.IGNORECASE)]
            if starts:
                next_positions[index] = min(starts)
        positions = next_positions
        if not positions:
            return []
    return [(start, tokens[index].end()) for index, start in positions.items()]


def _term_present(text, term, expand):
    if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text):
        return True
    if not expand:
        return False
    return bool(_expanded_term_spans(text, term))


def trigger_contract_error(prompt, trigger, target, *, connected=True, at_start=False, expand=False):
    """Return a placement/grouping preference issue, or None when satisfied."""
    text = trigger_text_target(prompt, target)
    terms = trigger_terms(trigger, False)
    if not terms:
        return "No trigger text or terms are configured."
    if error := trigger_presence_error(prompt, trigger, target, expand=expand):
        return error
    configured = str(trigger or "").strip()
    if connected and not _term_present(text, configured, expand):
        return "The trigger terms are present, but the requested connected trigger phrase was not preserved."
    first = configured if connected else terms[0]
    beginning = (any(re.fullmatch(r"(?:(?:a|an|the)\s+)?", text[:start], re.IGNORECASE)
                     for start, _end in _expanded_term_spans(text, first))
                 if expand else text.startswith(first))
    if at_start and not beginning:
        return "The trigger terms are present, but the requested beginning placement was not followed."
    if not connected and _terms_are_adjacent(text, terms):
        return (
            "The trigger terms are present, but they remained adjacent instead of being distributed "
            "through meaningful prompt positions."
        )
    return None


def trigger_presence_error(prompt, trigger, target, *, expand=False):
    """Return an error only when required trigger content is actually absent."""
    text = trigger_text_target(prompt, target)
    terms = trigger_terms(trigger, False)
    if not terms:
        return "No trigger text or terms are configured."
    missing = [term for term in terms if not _term_present(text, term, expand)]
    if not missing:
        return None
    quoted = ", ".join(json.dumps(term, ensure_ascii=False) for term in missing)
    if expand:
        return f"Could not find the required trigger subject/attribute word(s): {quoted}. Expansion allows descriptive wording, not subject omission; check paraphrases manually."
    return f"The result is missing the exact required trigger term(s): {quoted}."
