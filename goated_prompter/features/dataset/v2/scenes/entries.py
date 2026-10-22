"""The vocabulary the writer is offered: fitting Actions & Poses entries and dealing entries and suggestions."""

import json
import math
import re

from .....backends.base import GoatedPrompterError
from .....contracts import PromptInstruction

from .checks import _words
from .settings import ACTIONS_CATEGORY, ENTRY_CAP, FIT_CHUNK, HAND
from .texts import ENTRY_FIT_SYSTEM


def fitting_instruction(brief, entries, notes=None):
    """One fitting call: which of these Actions & Poses entries (numbered from 1) fit the request and the cast.
    notes: {pack name: its author's note} of the selected packs that have one."""
    cast = [{key: person[key] for key in ("label", "gender", "count") if key in person} for person in brief["characters"]]
    data = {"request": brief["input"]["request"], "summary": brief["summary"], "fixed": brief["fixed"],
            "must": brief["must"], "avoid": brief["avoid"], "cast": cast,
            "entries": {str(number): entry for number, entry in enumerate(entries, 1)}, **({"notes": notes} if notes else {})}
    schema = {"type": "object", "additionalProperties": False, "required": ["fit"],
              "properties": {"fit": {"type": "array", "items": {"type": "integer"}}}}
    return PromptInstruction(system_message=ENTRY_FIT_SYSTEM, user_message=json.dumps(data, ensure_ascii=False, indent=1),
                             model_family=brief["_family"], diagnostic_stage="dataset_v2:entries",
                             max_tokens=8 * len(entries) + 64, hard_max_tokens=8 * len(entries) + 64,
                             temperature=0.0, top_p=1.0, json_output=True, json_schema=schema,
                             seed=brief["input"].get("seed"))


def fitting_entries(session, brief, entries, checkpoint=lambda: None, progress=print, notes=None):
    """The Actions & Poses entries that fit the request and the cast, in their order. The vocabulary only offers
    what the request asks for, so an unrelated entry never fills an image. When a fitting call fails, every entry
    stays (the writer still checks each dealt entry against the request)."""
    fit = []
    for start in range(0, len(entries), FIT_CHUNK):
        chunk = entries[start:start + FIT_CHUNK]
        checkpoint()
        try:
            raw = session.generate(fitting_instruction(brief, chunk, notes))
            numbers = json.loads(re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(raw or "")))["fit"]
            if not isinstance(numbers, list) or not all(type(number) is int for number in numbers):
                raise ValueError("fit must be a list of numbers")
        except (GoatedPrompterError, ValueError, KeyError, TypeError):
            progress("Could not sort the Actions & Poses entries by the request; all of them stay available.")
            return list(entries)
        checkpoint()
        fit.extend(chunk[number - 1] for number in sorted(set(numbers)) if 1 <= number <= len(chunk))
    return fit


def _only(groups, category, keep):
    """The groups with category's entries limited to keep (the category is left out when none remain)."""
    keep, result = set(keep), []
    for group in groups:
        if group["category"] == category:
            packs = [{**pack, "entries": [entry for entry in pack["entries"] if entry in keep]} for pack in group["packs"]]
            packs = [pack for pack in packs if pack["entries"]]
            if not packs:
                continue
            group = {**group, "packs": packs}
        result.append(group)
    return result


def _entry_key(text):
    return " ".join(str(text or "").split()).casefold()


def _shuffled(groups, rng, limit=None):
    """The selected vocabulary with each pack's entries shuffled (an entry in two packs counted once); with limit, at
    most limit entries per category, taken from its packs in turn (a different seeded sample every batch), so large
    packs never drown the request. Each pack keeps its name and description."""
    result = []
    for group in groups:
        seen, packs = set(), []
        for pack in group["packs"]:
            entries = [entry for entry in dict.fromkeys(pack["entries"]) if entry not in seen]
            seen.update(entries)
            rng.shuffle(entries)
            packs.append({**pack, "entries": entries})
        if limit:
            kept, queues = [[] for _ in packs], [list(pack["entries"]) for pack in packs]
            while sum(map(len, kept)) < limit and any(queues):
                for index, queue in enumerate(queues):
                    if queue and sum(map(len, kept)) < limit:
                        kept[index].append(queue.pop(0))
            packs = [{**pack, "entries": entries} for pack, entries in zip(packs, kept)]
        result.append({**group, "packs": [pack for pack in packs if pack["entries"]]})
    return result


def deal_entries(entries, total, rng):
    """{slot: entry}: a different Actions & Poses entry for every image, from a seeded shuffle, without repeats until
    every entry has been dealt ({} without entries). The writer keeps it unless it cannot fit the cast."""
    if not entries:
        return {}
    deck, dealt = [], {}
    for number in range(1, total + 1):
        if not deck:
            deck = list(entries)
            rng.shuffle(deck)
        dealt[number] = deck.pop()
    return dealt


def requested_words(brief):
    """The words of the request and of what it fixes or requires."""
    return frozenset(_words(" ".join((brief["input"]["request"], brief.get("fixed", ""), *brief.get("must", ())))))


def requested_entries(entries, words):
    """The entries about something the request itself names: they share a word with it that is rare in this category
    (in at most a quarter of its entries), so a word every entry repeats never counts."""
    found = {word: sum(word in _words(entry) for entry in entries) for word in words}
    rare = {word for word, count in found.items() if 0 < count <= max(1, len(entries) // 4)}
    return [entry for entry in entries if _words(entry) & rare]


def named_entries(entries, words):
    """Of the entries about the request, the ones whose name (the text before ": ", else the whole entry) the request
    says in full: "dildo" over "double dildo" when only "dildo" was asked for. All of them when none is named in full."""
    named = [entry for entry in entries if _words(entry.split(": ", 1)[0]) <= words]
    return named or entries


def deal_hands(groups, total, rng, size=HAND, words=frozenset()):
    """{slot: {category: [entries]}}: a few suggested entries of every selected category except Actions & Poses (dealt
    on its own) for every image, from a seeded shuffle, without repeats until every entry has been dealt, so the whole
    vocabulary spreads over the set instead of the same few favourites. Suggestions are optional: the writer uses the
    ones that fit the image, or none.

    words: the request's words (requested_words). In a category whose entries are about something the request names:
    - the request names only that thing (not the category or one of its packs): every image gets only the entry the
      request names (named_entries), so asking for one thing gives that one thing;
    - the request also names the category or a pack of it ("sex toys" for a pack called Sex Toys), so it asks for the
      kind in general: every image gets one entry about what it names and one other, and the vocabulary adds variety."""
    hands = {number: {} for number in range(1, total + 1)}
    for group in groups:
        if group["category"] == ACTIONS_CATEGORY:
            continue
        entries = list(dict.fromkeys(entry for pack in group["packs"] for entry in pack["entries"]))
        if related := requested_entries(entries, words):
            general = words & _words(" ".join([group["category"], *(pack.get("name", "") for pack in group["packs"])]))
            if general:
                others = [entry for entry in entries if entry not in related]
            else:
                related, others = named_entries(related, words), []
            decks = [[], []]
            for number in range(1, total + 1):
                for deck, pool in zip(decks, (related, others)):
                    if pool:
                        if not deck:
                            deck.extend(pool)
                            rng.shuffle(deck)
                        hands[number].setdefault(group["category"], []).append(deck.pop())
            continue
        deck = []
        for number in range(1, total + 1):
            hand = []
            while len(hand) < min(size, len(entries)):
                if not deck:
                    deck = [entry for entry in entries if entry not in hand]
                    rng.shuffle(deck)
                hand.append(deck.pop())
            if hand:
                hands[number][group["category"]] = hand
    return {number: hand for number, hand in hands.items() if hand}


def entry_cap(entries, total):
    """How many images may use one Actions & Poses entry: ENTRY_CAP, or more when there are fewer entries than
    images."""
    return max(ENTRY_CAP, math.ceil(total / len(entries))) if entries else None
