"""Places: every image is dealt one place, and its scene is built there (the writer never chooses one itself).

Responsibilities: Understanding says what the request asks (brief version 16 "places": the place words it keeps, the
setting around them, its world and, when it names no place, ideas of where it can happen; version 19 also its spatial
relations, each subject, relation and anchor in the request's own words and whether the anchor holds the subject); vocabulary retrieval finds
the Spaces groups each of those names (vocabulary/retrieval.py match, which finds nothing rather than a weak match);
vocabulary selection orders, deals and pairs them (vocabulary/selection.py). This module only says which texts are
searched, in which groups:
  named   the request's place words without the setting ("his room in space": "his room", setting "in space") among
          the groups of the request's world, or of every world when a setting carries the world (the room in space is a
          room). Words that point to some of a group's places (a white background, a rainy street) stay that
          specific; a place named broadly is widened by the ideas' groups that are close in meaning to it (retrieval.related:
          an idea that leaves the named place, a bedroom for a bathroom fixture, adds nothing; without embeddings
          nothing is added). The user's words are authoritative: when no group answers them, the setting's group is used, then the
          ideas, which for a named place are only that place or its kinds (so words that were never a place, a time of
          day kept as one, still find places, and a place missing from the catalog still finds none); with nothing,
          nothing is dealt and the writer follows the request's words. The setting goes to every image.
  related the request places its subjects relative to anchors (Understanding's relations): an anchor that holds them
          (in a park, inside a castle, on a cliff) and is held by none itself is where the image happens ("under an
          oak tree in a meadow": the meadow): searched like named place words (a thing of places, "the kitchen table",
          keeps every place of its groups, so the set still varies), else the request's own place words
          without the anchors they are outside of, never widened by other places, so variety comes from that place's
          own entries;
          an anchor they are outside of (in front of a castle, beside a lake, under a table) never is: the groups its
          own words name whole (the castle's own halls, the lake's shores) are left out of every search and its own
          words are taken out of every text searched ("a sidewalk near a bakery" is searched as "a sidewalk near"), so
          the environment comes from the anchors that hold them, else from the ideas, which for such an anchor are
          places it is seen from. An anchor that only names a thing of a place ("the kitchen table") leaves that place in.
          Nothing compatible found: nothing is dealt, and the writer follows the request's words; a relation is never
          given up for variety. Every image also carries the whole arrangement in the request's words (arrangement)
          for the writer to keep.
  free    the request names no place: the user's selected Spaces packs when there are any; else the groups that
          Understanding's ideas name among the groups of the request's world (and, for an adult request, the
          adult_default groups first). An idea no group answers adds nothing; with no idea answered nothing is dealt.
          Retrieval never adds a place on its own: what a request allows is Understanding's judgement.
A place the request needs is never traded for variety. A named place stays in every dealt place: when the search
finds places that say the place's own noun (the last word of its first phrase: "a library", "the beach at sunset"),
only those places, or the places of groups whose words say it, are dealt (the_place_named): a reading room, not a
cafe the ideas widened to. An idea or a name finds a whole group ("old town", "in space"), so the dealt
places then keep only the entries that suit what the request does there (fitting): close to one of Understanding's
ideas, which say where the act can happen (IDEA_Z; for a named place, its kinds), and not far from the act itself
(ACT_Z: the kept action's words). A shop interior when every idea is an open yard, or a gym for a rooftop repair, is
left out; the places that only differ in look stay, so the set still varies.
An idea can place the act outside a thing, as a relation does ("near a space station", "above the earth": OUTSIDE):
that thing's own places (its groups, _anchor_groups) are never what the idea finds, since it happens outside them, and
a group the request's place words found is left out when an idea puts the act outside it and no idea inside it
(outside_of_ideas): words that find a building's rooms, while every idea places the act outside the building, deal
none of its rooms; with nothing left, nothing is, and the writer follows the request's words.
The groups go in a varied order (selection.diverse_order) and the set is dealt across them (selection.deal_spread); a
locked place is one for every image. The places are then paired with the dealt Actions & Poses entries
(selection.pair with retrieval.fit_scores). No model call: code finds, deals and pairs.
"""

import re

from ....vocabulary.embeddings import dot
from ....vocabulary.retrieval import (FUNCTION_WORDS, content_words, entry_name, exact_search, group_vectors, in_world,
                                      match, related, word_sequence, word_stem, zscores)
from ....vocabulary.selection import diverse_order
from ..consistency import kept_words, levels

SPACES = "Spaces"
# An entry this many deviations farther from every idea than the pool's entries are is no place for the request, nor
# one this far from its act; only a pool large enough for that is judged (FIT_POOL). With the built-in places these left
# out shop interiors for an act the ideas put in a yard and indoor rooms for an act outside, and no place of a forest
# for an act any forest suits.
IDEA_Z, ACT_Z, FIT_POOL = -1.0, -1.5, 5
# The words that place what follows them outside the subjects ("near a station", "beside a lake"), as a relation whose
# within is false does; "along a beach" or "in a park" are on or in it.
OUTSIDE = frozenset("near beside behind above below under beneath over around outside before by across beyond opposite "
                    "between against".split())
_PREPOSITIONS = FUNCTION_WORDS - frozenset("a an the his her their its my your our this that these those".split())


def _facts(brief):
    """The brief's places ({setting, world, ideas, relations}); a brief before version 16 has no setting, no world and
    no ideas, one before version 19 no relations."""
    return {"setting": "", "world": None, "ideas": [], "relations": [], **(brief.get("places") or {})}


def _without(words, setting):
    """The place words without the setting's words ("in his room in space" without "in space" is "in his room")."""
    if not setting:
        return words
    start = " ".join(words.casefold().split()).find(" ".join(setting.casefold().split()))
    flat = " ".join(words.split())
    return (flat[:start] + flat[start + len(" ".join(setting.split())):]).strip(" ,;") if start >= 0 else words


def _merged(groups):
    """The groups once each, in order; a group found twice keeps every entry either finding kept."""
    merged = {}
    for group in groups:
        if group["name"] in merged:
            merged[group["name"]] = {**merged[group["name"]], "entries": list(dict.fromkeys(
                merged[group["name"]]["entries"] + group["entries"]))}
        else:
            merged[group["name"]] = group
    return list(merged.values())


def arrangement(brief):
    """The request's spatial relations as the writer keeps them, each in the request's own words ("a dragon in front of
    a castle"); [] for none."""
    return [" ".join(" ".join(filter(None, (item["subject"], item["relation"], item["anchor"]))).split())
            for item in _facts(brief).get("relations") or ()]


def _anchor_groups(groups, anchor):
    """The groups that are an anchor itself: those its words name whole, every content word of it among the group's
    own words ("a castle" is the castle; "the kitchen table" is a thing of the kitchen, not the kitchen)."""
    said = {word_stem(word) for word in content_words(anchor)}
    return [group for group in exact_search(groups, anchor)
            if said <= {word_stem(word) for phrase in group["words"] for word in content_words(phrase)}]


def _holding(pool, anchor, embeddings):
    """The groups an anchor that holds the subjects puts the image in. Its last word says what it is: a place ("a rainy
    street", "a park") is found and narrowed by its other words like named place words (retrieval.match); a thing of
    places ("the kitchen table", "a fireplace") keeps every place of the groups its words name, so the set still
    varies ("the kitchen table" is in any kitchen)."""
    words = content_words(anchor)
    hits = exact_search(pool, anchor) if words else []
    own = lambda group: {word_stem(word) for phrase in group["words"] for word in content_words(phrase)}
    if hits and not any(word_stem(words[-1]) in own(group) for group in hits):
        return hits
    return match(pool, anchor, embeddings)


def _without_anchors(text, anchors):
    """The text without every anchor's own words as a phrase ("a sidewalk near a bakery" without "a bakery" is "a
    sidewalk near"), so an anchor never pulls its own places into a search; words of an anchor said apart stay."""
    said = word_sequence(text)
    for anchor in anchors:
        own = tuple(word for word in word_sequence(anchor) if word in set(content_words(anchor))) or word_sequence(anchor)
        for start in range(len(said) - len(own), -1, -1):
            if own and said[start:start + len(own)] == own:
                said = said[:start] + said[start + len(own):]
    return " ".join(said)


def _related_plan(brief, groups, facts, embeddings):
    """(groups, setting) for a request with spatial relations (the "related" rule above)."""
    relations, setting = facts["relations"], facts["setting"]
    flat = lambda text: " ".join(word_sequence(text))
    apart = [item["anchor"] for item in relations if not item["within"]]
    outside = {group["name"] for anchor in apart for group in _anchor_groups(groups, anchor)}
    away = [group for group in groups if group["name"] not in outside]  # an anchor they are outside of is never the place
    pool = in_world(away, None if setting else facts["world"])
    # The anchors that hold the subjects and are held by none themselves ("under an oak tree in a meadow": the meadow),
    # then the request's own place words without the anchors they are outside of.
    held = {flat(item["subject"]) for item in relations if item["within"]}
    outer = [item["anchor"] for item in relations if item["within"] and flat(item["anchor"]) not in held]
    found = _merged([group for anchor in outer for group in _holding(pool, anchor, embeddings)])
    # Relation words are never place words: "in front of a large window" leaves nothing to search.
    words = _without_anchors(_without(kept_words(brief).get("place") or "", setting),
                             apart + [item["relation"] for item in relations])
    found = found or (match(pool, words, embeddings) if content_words(words) else [])
    if found:
        return found, setting  # the place that holds them, never widened: "in a park" is no backyard
    if setting and (inside := match(in_world(away, facts["world"]), setting, embeddings)):
        return inside, setting
    selected = [group for group in away if group["selected"]]
    if selected:
        return selected, setting  # the user's own places come first, never inside an anchor they are outside of
    ideas = {**facts, "ideas": [text for idea in facts["ideas"] if content_words(text := _without_anchors(idea, apart))]}
    return _from_ideas(brief, away, ideas, embeddings, adult_first=brief.get("path") == "nsfw_character"), setting


def _outside_anchors(text):
    """The things a text places the act outside of: the words after each OUTSIDE word up to the next preposition
    ("near a space station": "a space station"; "a meadow before its walls": "its walls")."""
    words, anchors, current = word_sequence(text), [], None
    for word in words:
        if word in OUTSIDE:
            current = []
            anchors.append(current)
        elif current is not None and word in _PREPOSITIONS:
            current = None
        elif current is not None:
            current.append(word)
    return [" ".join(anchor) for anchor in anchors if content_words(" ".join(anchor))]


def _reading(idea):
    """(what an idea itself names, the things it places the act outside of): the idea without those things' words, and
    the things ("near a space station": "near", ["a space station"])."""
    anchors = _outside_anchors(idea)
    return _without_anchors(idea, anchors), anchors


def outside_of_ideas(pool, ideas, embeddings=None):
    """The names of the groups an idea places the act outside of (the groups that are such a thing, _anchor_groups)
    and that no idea finds itself."""
    outside, inside = set(), set()
    for idea in ideas:
        own, anchors = _reading(idea)
        outside |= {group["name"] for anchor in anchors for group in _anchor_groups(pool, anchor)}
        if content_words(own):
            inside |= {group["name"] for group in match(pool, own, embeddings)}
    return outside - inside


def _noun(words):
    """A place's own noun: the last content word of its first phrase ("the beach at sunset": beach), stemmed; "" when
    it has none."""
    phrases = [phrase for phrase in re.split(r"\b(?:" + "|".join(sorted(FUNCTION_WORDS - {"a", "an", "the"})) + r")\b",
                                             str(words or "").casefold()) if content_words(phrase)]
    return word_stem(content_words(phrases[0])[-1]) if phrases else ""


def the_place_named(found, words):
    """The found groups with only the places that are the named place: its noun (_noun) said by the place or by its
    group's own words, in any form. Unchanged when no found place says it: the words name the place differently ("a
    house of worship" found a church by meaning)."""
    noun = _noun(words)
    says = lambda *texts: noun in {word_stem(word) for text in texts for word in content_words(text)}
    kept = [{**group, "entries": [entry for entry in group["entries"] if says(entry, group["name"], *group["words"])]}
            for group in found] if noun else []
    return [group for group in kept if group["entries"]] or found


def _near(found, texts, embeddings, cut):
    """The groups with only the entries whose closeness to the nearest of texts, compared over the pool, is at least
    cut. Unchanged without embeddings or texts, or with fewer than FIT_POOL entries."""
    entries = [entry for group in found for entry in group["entries"]]
    queries = [vector for text in texts if text and (vector := embeddings.query(text)) is not None] if embeddings else []
    vectors = embeddings.documents(entries) if queries and len(entries) >= FIT_POOL else None
    if vectors is None:
        return found
    near = {entry for entry, score in zip(entries, zscores(max(dot(query, vector) for query in queries)
                                                          for vector in vectors)) if score >= cut}
    kept = [{**group, "entries": [entry for entry in group["entries"] if entry in near]} for group in found]
    return [group for group in kept if group["entries"]]


def fitting(found, brief, embeddings=None):
    """The dealt places that suit what the request does there: close to one of its ideas (IDEA_Z) and not far from its
    kept action (ACT_Z)."""
    return _near(_near(found, _facts(brief)["ideas"], embeddings, IDEA_Z), [kept_words(brief).get("action", "")],
                 embeddings, ACT_Z)


def place_plan(brief, groups, embeddings=None):
    """(groups to deal from in order, setting): the places this run deals, by the rules above, only those that suit what
    the request does there (fitting); ([], "") for none."""
    found, setting = _place_plan(brief, groups, embeddings)
    return fitting(found, brief, embeddings), setting


def _place_plan(brief, groups, embeddings):
    level, words, facts = levels(brief)["place"], kept_words(brief).get("place"), _facts(brief)
    if facts["relations"]:
        return _related_plan(brief, groups, facts, embeddings)
    if level != "free" and not words:
        return [], ""  # a kept place without its words (a brief from before version 15): the writer keeps it
    if words:
        found, setting = _named_plan(brief, groups, facts, words, embeddings)
        away = outside_of_ideas(in_world(groups, None if setting else facts["world"]), facts["ideas"], embeddings)
        named = [group for group in the_place_named(found, _without(words, facts["setting"]))
                 if group["name"] not in away]
        return named, setting
    selected = [group for group in groups if group["selected"]]
    if selected:
        return selected, ""  # the user's own places come first
    return _from_ideas(brief, groups, facts, embeddings, adult_first=brief.get("path") == "nsfw_character"), ""


def _named_plan(brief, groups, facts, words, embeddings):
    """(groups, setting) for a request that names its place (the "named" rule above), before the_place_named."""
    setting = facts["setting"]
    pool, named = in_world(groups, None if setting else facts["world"]), _without(words, setting)
    found = match(pool, named, embeddings)
    if found and not exact_search(pool, named):
        # Found by meaning alone, so Understanding's ideas decide when they name other places: "on a marble table"
        # meant a kitchen by meaning, while the ideas of a perfume bottle on it were a vanity, a dressing room, a shop.
        ideas = _from_ideas(brief, groups, facts, embeddings, adult_first=False)
        if ideas and not {group["name"] for group in found} & {group["name"] for group in ideas}:
            return ideas, setting
    if found:
        sizes = {group["name"]: len(group["entries"]) for group in groups}
        if any(len(group["entries"]) < sizes.get(group["name"], 0) for group in found):
            return found, setting  # words that point to some of a group's places stay that specific
        # Named broadly ("his room"): the ideas widen it, only with groups close to the one it names (its kinds).
        ideas = _from_ideas(brief, groups, facts, embeddings, adult_first=False)
        return _merged(found + related(ideas, found, groups, embeddings)), setting
    found = match(in_world(groups, facts["world"]), setting, embeddings) if setting else []
    # The words name no catalog place (or were never a place: a time of day kept as one): the ideas, which for a
    # named place are that place or its kinds, so a place missing from the catalog still deals nothing.
    return found or _from_ideas(brief, groups, facts, embeddings, adult_first=False), ""


def _from_ideas(brief, groups, facts, embeddings, adult_first):
    """The groups Understanding's ideas name among the groups of the request's world, in the most varied order; the
    adult_default groups lead when adult_first."""
    pool = in_world(groups, facts["world"])
    if embeddings is not None:
        embeddings.prepare(facts["ideas"])  # every idea embedded in one call
    first = [group for group in pool if group["adult"]] if adult_first else []
    found = []
    for idea in facts["ideas"]:  # an idea never finds a thing it places the act outside of
        own, anchors = _reading(idea)
        apart = {group["name"] for anchor in anchors for group in _anchor_groups(pool, anchor)}
        found += match([group for group in pool if group["name"] not in apart], own, embeddings) if content_words(own) else []
    found = _merged(first + found)
    # The adult default leads; then the most varied order.
    scores = [2.0 if any(group["name"] == lead["name"] for lead in first) else 1.0 for group in found]
    return diverse_order(found, scores, group_vectors(found, embeddings))


def place_problems(scene, place, words=None):
    """Why a scene is not built in its dealt place, as reasons to ask again ([] when it is): its space says at least
    one of the words that tell the place apart (its name or one of its features: retrieval.telling_words), a plural
    ending aside. A space that names the place differently but keeps one of its features is that place."""
    own = (words or {}).get(place) or frozenset(content_words(place))
    if own & set(content_words(scene.get("space"))):
        return []
    # Asked again, a scene keeps its act and only moves (a live redo wrote another image's act instead).
    act = " ".join(str(scene.get("actions") or "").split())[:160]
    return [f'its space is not its dealt place: build it in "{entry_name(place)}"'
            + (f' and keep its act ("{act}")' if act else "")]
