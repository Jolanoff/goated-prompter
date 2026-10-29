"""The vocabulary the writer is offered: the selected vocabulary's entries, the groups a category's owner searches,
and dealing suggestions and frames."""

import math
import re

from ....vocabulary.retrieval import base_word, content_words, groups_of, said_entries, word_stem
from ....vocabulary.selection import deal_spread

from ..consistency import kept_words
from .checks import _words, named_frame
from .settings import ACTIONS_CATEGORY, AT_LEAST_HIPS, ENTRY_CAP, HAND


def offered_groups(catalog, category, selection, groups):
    """One category's groups for the vocabulary engine (retrieval.groups_of) with only the entries the run offers: the
    selected vocabulary's (groups) after its cast and slot checks (fit_cast, slots.only_fillable)."""
    return offered(groups_of(catalog, category, selection), category, groups)


def offered(rows, category, groups):
    """The retrieved groups of one category (rows, retrieval.groups_of) with only the entries the run offers (see
    offered_groups)."""
    keep = {entry for group in groups if group["category"] == category for pack in group["packs"]
            for entry in pack["entries"]}
    rows = [{**row, "entries": [entry for entry in row["entries"] if entry in keep]} for row in rows]
    return [row for row in rows if row["entries"]]


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


# How many of something there are never names a thing: a request about "two men" was read as asking for a prop whose
# name also says "two" (like "two matching candles"), and that one prop was then suggested for every image.
COUNT_WORDS = frozenset("one two three four five six seven eight nine ten both pair couple several few many".split())


def requested_words(brief):
    """The words of the request and of what it fixes or requires, without counts (words and digits)."""
    words = _words(" ".join((brief["input"]["request"], brief.get("fixed", ""), *brief.get("must", ()))))
    return frozenset(word for word in words if word not in COUNT_WORDS and not word.isdigit())


def requested_entries(entries, words):
    """The entries about something the request itself names: those that say its distinctive words, in any form
    (retrieval.said_entries: a word every entry repeats never counts, and "a reading room" names the reading room
    entries, not every entry that is some other room, while "a lantern and an oil lamp" keeps both)."""
    found = said_entries([{"name": "", "words": [], "entries": list(dict.fromkeys(entries))}], " ".join(sorted(words)))
    return [entry for group in found for entry in group["entries"]]


def named_entries(entries, words):
    """Of the entries about the request, the ones whose name (the text before ": ", else the whole entry) the request
    says in full: "lantern" over "double lantern" when only "lantern" was asked for. All of them when none is named in
    full."""
    named = [entry for entry in entries if _words(entry.split(": ", 1)[0]) <= words]
    return named or entries


def named_in(entries, words):
    """The entries whose whole name (the text before ": ", else the entry) the words say, every content word in any
    form."""
    said = {word_stem(word) for word in words}
    name = lambda entry: {word_stem(word) for word in content_words(entry.split(": ", 1)[0])}
    return [entry for entry in entries if name(entry) and name(entry) <= said]


PHRASES = re.compile(r"[;,]|\b(?:and|while|with)\b")


def named_things(groups, kept="", acts=(), place=""):
    """[[entries]]: the things the request asks for that the built-in packs (groups) name, each as the entries of one
    name. A thing is named by its whole name, in any form and order (named_in: "a red lantern" names the lantern; "a
    small paper kite" names no paper lantern), within one phrase of Understanding's kept words (kept) or of one act
    (acts: an act names the things it is done with even when the kept objects leave them out, "plays guitar"), so
    words of two phrases never make a name together. An act's thing the place's own words name too (place) is where
    the act happens, not a thing in it ("hiking a snowy mountain trail"); the kept words always count. [] when nothing
    is named: the request's own words stay as they are."""
    entries = list(dict.fromkeys(entry for group in groups for entry in group["entries"]))
    placed = {word_stem(word) for word in content_words(place)}
    name = lambda entry: " ".join(entry.split(": ", 1)[0].casefold().split())
    found, seen = {}, set()
    phrases = [(phrase, False) for phrase in PHRASES.split(str(kept or ""))] + [
        (phrase, True) for act in acts for phrase in PHRASES.split(str(act or ""))]
    for phrase, in_act in phrases:
        for entry in named_in(entries, content_words(phrase)):
            stems = {word_stem(word) for word in content_words(name(entry))}
            if entry not in seen and not (in_act and stems <= placed):
                seen.add(entry)
                found.setdefault(name(entry), []).append(entry)
    return list(found.values())


def said_of(brief, part):
    """{label: [phrases]}: the request's words for one part (Understanding's kept words, phrases joined with ";"),
    each with the character it belongs to. A phrase belongs to the character the request names right after it ("a
    smiling woman"), else the one it names last before it ("a man in a black suit beside a woman in a red dress": the
    suit is the man's, the dress the woman's). Characters of one name ("friend 1", "friend 2") are told apart by order:
    the name said once more ("a friend in a suit with a friend in a jacket") is the next of them, and the name said in
    the plural ("two friends in hoodies") is all of them. A phrase belongs to the only character when there is one, and
    to nobody when the request does not show whose it is."""
    request = " ".join(str(brief["input"]["request"]).casefold().split())
    people = [person["label"] for person in brief["characters"]]
    names = {label: {word for word in content_words(label) if not word.isdigit()} for label in people}
    named = lambda word: [label for label in people if base_word(word) in names[label]]
    words = lambda text: re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", text))
    found = {}
    for phrase in PHRASES.split(str(kept_words(brief).get(part, "") or "")):
        phrase = " ".join(phrase.split())
        if not content_words(phrase):
            continue
        start = request.find(phrase.casefold())
        said = words(request[:start]) if start >= 0 else []
        after = words(request[start + len(phrase):])[:1] if start >= 0 else []
        index = len(said) if after and named(after[0]) else next(
            (index for index in range(len(said) - 1, -1, -1) if named(said[index])), None)
        said += after
        owners = set()
        if index is not None:
            word, labels = said[index], named(said[index])
            plural = word != base_word(word)
            times = sum(base_word(other) == base_word(word) for other in said[:index + 1])
            owners = set(labels) if plural or len(labels) == 1 else set(labels[times - 1:times])
        owners = owners or ({people[0]} if len(people) == 1 else set())
        for label in people:
            if label in owners:
                found.setdefault(label, []).append(phrase)
    return found


def deal_per_person(pools, total, rng, fixed=False):
    """{slot: {label: entry}}: one entry per person per image ({label: pool}). The people who share a pool share one
    seeded deal without repeats until it is spent; image by image, each person takes the next entry of their deal
    that nobody in that image has yet, so the people of one image never get the same entry while their pools have
    enough. fixed: each person's first entry in every image."""
    shared = {}
    for label, pool in pools.items():
        if pool:
            shared.setdefault(tuple(pool), []).append(label)
    rows = 1 if fixed else total
    decks = {}
    for pool, labels in shared.items():
        cards = deal_spread([{"name": "people", "entries": list(pool)}], rows * len(labels), rng)
        decks[pool] = [cards[index] for index in sorted(cards)]
    dealt = {}
    for number in range(1, rows + 1):
        row = {}
        for label, pool in pools.items():
            if deck := decks.get(tuple(pool)):
                index = next((index for index, entry in enumerate(deck) if entry not in row.values()), None)
                # The deal's last cards may all be taken in this image already: then another of the pool's entries.
                row[label] = deck.pop(index) if index is not None else next(
                    (entry for entry in pool if entry not in row.values()), deck.pop(0))
        dealt[number] = row
    return {number: dict(dealt[1 if fixed else number]) for number in range(1, total + 1) if dealt.get(1 if fixed else number)}


def deal_named(things, total):
    """{slot: [entries]}: every named thing in every image, the entries of one name taken in turn (no random call)."""
    return {number: [entries[(number - 1) % len(entries)] for entries in things]
            for number in range(1, total + 1)} if things else {}


def deal_hands(groups, total, rng, size=HAND, words=frozenset(), owned=frozenset(), own_words=None):
    """{slot: {category: [entries]}}: suggested entries (size, one by default) of every selected category except Actions & Poses (dealt
    on its own) for every image, from a seeded shuffle, without repeats until every entry has been dealt, so the whole
    vocabulary spreads over the set instead of the same few favourites. Suggestions are optional: the writer uses the
    ones that fit the image, or none.

    words: the request's words (requested_words). In a category whose entries are about something the request names:
    - the request names only that thing (not the category or one of its packs): every image gets only the entry the
      request names (named_entries), so asking for one thing gives that one thing;
    - the request also names the category or a pack of it by its kind, the last word of its name ("tools" for a pack
      called Garden Tools), so it asks for the kind in general: every image gets one entry about what it names and one
      other, and the vocabulary adds variety. Another word of the name is not the kind: "reading in a quiet library"
      never asks for a pack called Reading Spaces in general, so every image stays in the library.
    A request word that names a selected pack of another category is that pack's theme, never one entry of this
    category: a live request about "public" places with a pack called Public Risk got the one prop entry that also
    said "public" in every image.
    owned: categories whose owner deals them when the request names none of their entries (Objects & Props:
    props.py), so they are dealt here only for what the request names.
    own_words: {category: words} for a category whose entries the request names only in those words (Objects & Props:
    the things Understanding kept, never any word of the request: a word of the act names no object), and only the
    entries whose whole name those words say (named_in: "a red lantern" names the lantern; "a small paper kite" names
    no paper lantern and "a bowl of soup" no mixing bowl)."""
    hands, asked = {number: {} for number in range(1, total + 1)}, words
    themes = {group["category"]: {word for pack in group["packs"] for word in _words(pack.get("name", ""))}
              for group in groups}
    for group in groups:
        if group["category"] == ACTIONS_CATEGORY:
            continue
        words = (own_words or {}).get(group["category"], asked)
        entries = list(dict.fromkeys(entry for pack in group["packs"] for entry in pack["entries"]))
        others = set().union(*(theme for category, theme in themes.items() if category != group["category"]))
        # A pack's whole name said in the request ("light sources") names its kind, never one of its entries.
        named = set().union(*(name for pack in group["packs"] if (name := _words(pack.get("name", ""))) <= words))
        loose = requested_entries(entries, words - others - named)
        if related := (named_in(entries, words) if group["category"] in (own_words or {}) else loose):
            kinds = (re.findall(r"[a-z0-9]+", name.casefold())[-1:] for name in
                     [group["category"], *(pack.get("name", "") for pack in group["packs"])])
            general = words & {word for kind in kinds for word in kind}
            if general:
                others = [entry for entry in entries if entry not in related and entry not in loose]
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
        if group["category"] in owned:
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


def deal_frames(total, rng, needed=None):
    """{slot: frame}: the frame each image's known characters get, from a seeded deck of the frames that keep them at
    least head to hips (full body, head to knees, head to hips), so a set spreads over all three. needed: the narrowest
    frame the request asks for (required_frame); no tighter frame is dealt, since the writer follows the deal over the
    request (a live request for the feet was dealt hips-up frames and lost them)."""
    frames = AT_LEAST_HIPS[:AT_LEAST_HIPS.index(needed) + 1] if needed in AT_LEAST_HIPS else AT_LEAST_HIPS
    deck, dealt = [], {}
    for number in range(1, total + 1):
        if not deck:
            deck = list(frames)
            rng.shuffle(deck)
        dealt[number] = deck.pop()
    return dealt


def kept_things(brief):
    """The words of the things the request keeps (Understanding's kept objects), without counts: the only words that
    name an Objects & Props entry for every image."""
    text = (brief.get("kept_words") or {}).get("objects", "")
    return frozenset(word for word in _words(text if isinstance(text, str) else "") if word not in COUNT_WORDS
                     and not word.isdigit())


def required_frame(brief):
    """The narrowest frame that holds the body parts the request asks to show, in its own words, its must or its
    camera words (checks.named_frame); None when it names none."""
    found = named_frame([brief["input"]["request"], *brief.get("must", ()), (brief.get("kept_words") or {}).get("camera")])
    return found[0] if found else None


def cast_size(brief):
    """How many people the run's cast has (a character with a count stands for that many)."""
    return sum(person.get("count") if type(person.get("count")) is int else 1 for person in brief["characters"])


def fit_cast(groups, size):
    """The selected vocabulary without the entries that need more people than the cast has (a pack's "people"); a
    pack or category left with no entry is left out. Entries that give no count always stay."""
    result = []
    for group in groups:
        packs = []
        for pack in group["packs"]:
            needs = pack.get("people") or {}
            entries = [entry for entry in pack["entries"] if needs.get(entry, 0) <= size]
            if entries:
                packs.append({**pack, "entries": entries})
        if packs:
            result.append({**group, "packs": packs})
    return result


def entry_cap(entries, total):
    """How many images may use one Actions & Poses entry: ENTRY_CAP, or more when there are fewer entries than
    images."""
    return max(ENTRY_CAP, math.ceil(total / len(entries))) if entries else None
