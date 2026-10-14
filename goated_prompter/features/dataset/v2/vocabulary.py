"""The NSFW vocabulary of the new Dataset path: data/vocabulary/sexual.json (private, never committed).

{"version": 1, "sections": {name: section}}

section  kind     "always" (every NSFW dataset), "act" (oral, anal...: on by default), "cast" (used by
                  people count: solo, threesome, group), "theme" (off unless the user asks: kink, toys...)
         note     optional text for the person editing the file; never read by code
         people   optional {"min": N, "max": N}: people per image ("max" left out = no upper limit)
         cues     themes and acts only: words or phrases that ask for it ("blowjob", "slutty clothes")
         parts    themes only, instead of entries: {part: {note, people, cues, entries}}; a part
                  without people uses the section's
         entries  plain strings, or {"text": ..., "acts": [act names]} for a scene that contains acts

Slots in entry text: [male1] only a man, [female1] only a woman, [person1] anyone (custom included).
Pronouns: [person2.he] / [person2.him] / [person2.his] become he/she/it, him/her/it, his/her/its.
A pronoun needs its slot in the same text, and numbers count up from 1 per slot type.

load() returns units: one per section, or one per part ("kink: mood"), each
{name, theme, part, kind, people: (min, max or None), cues, theme_cues, entries: [{text, acts, slots}]}.
"""

import json
import re

from ....config import PROJECT_ROOT
from ....strict_json import reject_duplicate_keys

VOCABULARY_FILE = PROJECT_ROOT / "data" / "vocabulary" / "sexual.json"
KINDS = ("always", "act", "cast", "theme")
SLOT_TYPES = ("male", "female", "person")
PRONOUNS = {"he": {"he": "he", "him": "him", "his": "his"},
            "she": {"he": "she", "him": "her", "his": "her"},
            "it": {"he": "it", "him": "it", "his": "its"}}
_PLACEHOLDER = re.compile(r"\[([^\[\]]*)\]")
_SLOT = re.compile(r"(male|female|person)([1-9][0-9]*)(?:\.(he|him|his))?")
_SECTION_KEYS = {"kind", "note", "people", "cues", "parts", "entries"}
_PART_KEYS = {"note", "people", "cues", "entries"}


class VocabularyError(ValueError):
    pass


def _people(value, where):
    if value is None:
        return None
    if (not isinstance(value, dict) or not value or set(value) - {"min", "max"}
            or any(type(number) is not int or number < 1 for number in value.values())
            or "max" in value and value["max"] < value.get("min", 1)):
        raise VocabularyError(f'{where}: people must be {{"min": N, "max": N}} with whole numbers from 1, max >= min.')
    return value.get("min", 1), value.get("max")


def _cues(value, where):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(cue, str) or not cue.strip() for cue in value):
        raise VocabularyError(f"{where}: cues must be a list of words or phrases.")
    return [cue.strip() for cue in value]


def _slots(text, where):
    """{"male": n, "female": n, "person": n} used by the text; checks every [placeholder]."""
    used, pronouns = {kind: set() for kind in SLOT_TYPES}, []
    for token in _PLACEHOLDER.findall(text):
        match = _SLOT.fullmatch(token.strip())
        if not match:
            raise VocabularyError(f'{where}: unknown placeholder "[{token}]" (use [male1], [female1], [person1], [person1.his]).')
        if match[3]:
            pronouns.append((match[1], int(match[2]), token))
        else:
            used[match[1]].add(int(match[2]))
    for kind, number, token in pronouns:
        if number not in used[kind]:
            raise VocabularyError(f'{where}: "[{token}]" has no [{kind}{number}] in the same text.')
    for kind, numbers in used.items():
        if numbers and numbers != set(range(1, max(numbers) + 1)):
            raise VocabularyError(f"{where}: {kind} slots must count up from 1 without gaps.")
    return {kind: len(numbers) for kind, numbers in used.items()}


def _entries(value, where, acts):
    if not isinstance(value, list):
        raise VocabularyError(f"{where}: entries must be a list.")
    result = []
    for number, item in enumerate(value, 1):
        spot = f"{where} entry {number}"
        if isinstance(item, str):
            text, labels = item, []
        elif isinstance(item, dict) and set(item) <= {"text", "acts"} and "text" in item and isinstance(item["text"], str):
            text, labels = item["text"], item.get("acts", [])
            if not isinstance(labels, list) or any(label not in acts for label in labels):
                raise VocabularyError(f"{spot}: acts must name act sections ({', '.join(acts) or 'none'}).")
        else:
            raise VocabularyError(f'{spot}: an entry is text, or {{"text": ..., "acts": [...]}}.')
        if not text.strip():
            raise VocabularyError(f"{spot}: empty text.")
        result.append({"text": text.strip(), "acts": list(labels), "slots": _slots(text, spot)})
    return result


def parse(text, name="sexual.json"):
    try:
        data = json.loads(text, object_pairs_hook=reject_duplicate_keys(f"{name}: a key appears twice in one object."))
    except json.JSONDecodeError as error:
        raise VocabularyError(f"{name}: not valid JSON at line {error.lineno}, column {error.colno}: {error.msg}.") from None
    if not isinstance(data, dict) or set(data) != {"version", "sections"} or data["version"] != 1:
        raise VocabularyError(f'{name}: the file must be {{"version": 1, "sections": {{...}}}}.')
    sections = data["sections"]
    if not isinstance(sections, dict) or not sections:
        raise VocabularyError(f"{name}: sections must be an object with at least one section.")
    acts = [key for key, body in sections.items() if isinstance(body, dict) and body.get("kind") == "act"]
    units = []
    for section, body in sections.items():
        where = f'{name}: section "{section}"'
        if ":" in section or not section.strip():
            raise VocabularyError(f"{where}: a section name cannot be empty or contain a colon.")
        if not isinstance(body, dict) or set(body) - _SECTION_KEYS or body.get("kind") not in KINDS:
            raise VocabularyError(f"{where}: needs kind ({', '.join(KINDS)}) and only {', '.join(sorted(_SECTION_KEYS))}.")
        kind = body["kind"]
        if ("parts" in body) == ("entries" in body):
            raise VocabularyError(f"{where}: needs entries or parts (not both).")
        if "parts" in body and kind != "theme":
            raise VocabularyError(f"{where}: only a theme can have parts.")
        if "cues" in body and kind not in ("theme", "act"):
            raise VocabularyError(f"{where}: only themes and acts have cues.")
        people = _people(body.get("people"), where)
        cues = _cues(body.get("cues"), where)
        if "entries" in body:
            units.append({"name": section, "theme": section, "part": None, "kind": kind, "people": people,
                          "cues": cues, "theme_cues": cues, "entries": _entries(body["entries"], where, acts)})
            continue
        if not isinstance(body["parts"], dict) or not body["parts"]:
            raise VocabularyError(f"{where}: parts must be an object with at least one part.")
        for part, item in body["parts"].items():
            spot = f'{where} part "{part}"'
            if ":" in part or not part.strip():
                raise VocabularyError(f"{spot}: a part name cannot be empty or contain a colon.")
            if not isinstance(item, dict) or set(item) - _PART_KEYS or "entries" not in item:
                raise VocabularyError(f"{spot}: needs entries and only {', '.join(sorted(_PART_KEYS))}.")
            units.append({"name": f"{section}: {part}", "theme": section, "part": part, "kind": kind,
                          "people": _people(item.get("people"), spot) or people, "cues": _cues(item.get("cues"), spot),
                          "theme_cues": cues, "entries": _entries(item["entries"], spot, acts)})
    return units


def load(path=None):
    path = path or VOCABULARY_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise VocabularyError(f"Could not read {path.name}: {error}.") from None
    return parse(text, path.name)


def in_range(unit, people):
    low, high = unit["people"] or (1, None)
    return people >= low and (high is None or people <= high)


def fits(entry, cast):
    """The cast can fill the entry's slots: men for [male], women for [female], anyone left for [person]."""
    men = sum(item["gender"] == "male" for item in cast)
    women = sum(item["gender"] == "female" for item in cast)
    slots = entry["slots"]
    return slots["male"] <= men and slots["female"] <= women and sum(slots.values()) <= len(cast)


def usable(unit, cast):
    """In the unit's people range, and at least one entry fits the cast (when it has entries)."""
    return in_range(unit, len(cast)) and (not unit["entries"] or any(fits(entry, cast) for entry in unit["entries"]))
