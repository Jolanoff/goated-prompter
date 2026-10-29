"""Clothing from the user's selected Clothing packs: selecting one is the instruction to dress the people with it.

All the selected packs' entries are one pool. Every person who can be dressed (dressed: a human whose look is not a
known character's or a trigger's) wears one of them in every image, dealt in a seeded order without repeats until
the pool is spent, never the same entry as another person of that image (deal_outfits); a locked clothing part keeps
each person's first one. An entry is one garment, not a whole outfit: the writer completes the rest of the clothing.
Packs made for one sex (a group named "female" or "male", like the built-in *-Female and *-Male packs) dress only the
people of that sex, and everyone else from the other selected packs (for_sex): the pack says who it is for, so no
garment is judged by its meaning.

The request comes first (worn). Understanding keeps the request's clothing words as one text ("kept_words.clothing",
phrases joined with ";"), not per person. A phrase belongs to the character the request names last before it ("a man
in a black suit beside a woman in a red dress": the suit is the man's, the dress the woman's). Characters of one name
("friend 1", "friend 2") are told apart by order: the name said once more ("a friend in a suit with a friend in a
jacket") is the next of them, and the name said in the plural ("two friends in hoodies") is all of them. A phrase
belongs to the only character when there is one, and to nobody when the request does not show whose it is. A person
the request dresses wears the selected entries that name the garment whole, else the request's own words, and is
dealt nothing else.

No Clothing pack selected: nothing is dealt and the writer dresses everyone from the request. Adult sets keep their
rule (texts.NSFW_RULE): whoever takes part is bare unless the request, an entry or a selected Clothing entry names a
garment, so a selected pack stays a suggestion there and nothing is dealt.
"""

import re

from ....vocabulary.retrieval import base_word, content_words
from ....vocabulary.selection import deal_spread
from ..consistency import kept_words
from ..understanding import is_human, stated_gender
from .entries import PHRASES

CLOTHING = "Clothing"


def worn(brief):
    """{label: [phrases]}: the request's clothing phrases each character wears (see the module docstring)."""
    request = " ".join(str(brief["input"]["request"]).casefold().split())
    people = [person["label"] for person in brief["characters"]]
    names = {label: {word for word in content_words(label) if not word.isdigit()} for label in people}
    found = {}
    for phrase in PHRASES.split(str(kept_words(brief).get("clothing", "") or "")):
        phrase = " ".join(phrase.split())
        if not content_words(phrase):
            continue
        start = request.find(phrase.casefold())
        said = re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", request[:start])) if start >= 0 else []
        owners = set()
        for index in range(len(said) - 1, -1, -1):
            named = [label for label in people if base_word(said[index]) in names[label]]
            if named:
                plural = said[index] != base_word(said[index])
                times = sum(base_word(word) == base_word(said[index]) for word in said[:index + 1])
                owners = set(named) if plural or len(named) == 1 else set(named[times - 1:times])
                break
        owners = owners or ({people[0]} if len(people) == 1 else set())
        for label in people:
            if label in owners:
                found.setdefault(label, []).append(phrase)
    return found


def for_sex(packs, person):
    """The selected Clothing packs a person is dressed from: all but the ones made for the other sex (a pack whose
    group is named or worded "female" or "male": vocabulary/Clothing/*-Female.json and *-Male.json); all of them when
    the person's sex is unstated, or when only the other sex's packs are selected."""
    other = {"female": "male", "male": "female"}.get(stated_gender(person))
    says = lambda pack, word: any(word == group["name"].casefold() or word in group["words"]
                                  for group in pack.get("groups") or ())
    return [pack for pack in packs if not (other and says(pack, other))] or list(packs)


def dressed(person):
    """Whether a character is dealt clothing: a human whose look does not come from a name or trigger."""
    return is_human(person) and not person.get("known") and not person.get("triggers")


def deal_outfits(pools, total, rng, fixed=False):
    """{slot: {label: entry}}: one entry per person per image ({label: pool}). The people who share a pool share one
    seeded deal without repeats until it is spent; image by image, each person takes the next entry of their deal
    that nobody in that image wears yet, so the people of one image never wear the same entry while their pools have
    enough. fixed: each person's first entry in every image."""
    shared = {}
    for label, pool in pools.items():
        if pool:
            shared.setdefault(tuple(pool), []).append(label)
    rows = 1 if fixed else total
    decks = {}
    for pool, labels in shared.items():
        cards = deal_spread([{"name": CLOTHING, "entries": list(pool)}], rows * len(labels), rng)
        decks[pool] = [cards[index] for index in sorted(cards)]
    dealt = {}
    for number in range(1, rows + 1):
        row = {}
        for label, pool in pools.items():
            if deck := decks.get(tuple(pool)):
                index = next((index for index, entry in enumerate(deck) if entry not in row.values()), None)
                # The deal's last cards may all be worn in this image already: then another of the pool's entries.
                row[label] = deck.pop(index) if index is not None else next(
                    (entry for entry in pool if entry not in row.values()), deck.pop(0))
        dealt[number] = row
    return {number: dict(dealt[1 if fixed else number]) for number in range(1, total + 1) if dealt.get(1 if fixed else number)}
