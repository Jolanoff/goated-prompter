"""Places: every image is dealt one place, and its scene is built there (the writer never chooses one itself).

Responsibilities: Understanding says what the request asks (brief version 16 "places": the place words it keeps, the
setting around them, its world and, when it names no place, ideas of where it can happen); vocabulary retrieval finds
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
  free    the request names no place: the user's selected Spaces packs when there are any; else the groups that
          Understanding's ideas name among the groups of the request's world (and, for an adult request, the
          adult_default groups first). An idea no group answers adds nothing; with no idea answered nothing is dealt.
          Retrieval never adds a place on its own: what a request allows is Understanding's judgement.
The groups go in a varied order (selection.diverse_order) and the set is dealt across them (selection.deal_spread); a
locked place is one for every image. The places are then paired with the dealt Actions & Poses entries
(selection.pair with retrieval.fit_scores). No model call: code finds, deals and pairs.
"""

from ....vocabulary.retrieval import content_words, entry_name, group_vectors, in_world, match, related
from ....vocabulary.selection import diverse_order
from ..consistency import kept_words, levels

SPACES = "Spaces"


def _facts(brief):
    """The brief's places ({setting, world, ideas}); a brief before version 16 has no setting, no world and no ideas."""
    return {"setting": "", "world": None, "ideas": [], **(brief.get("places") or {})}


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


def place_plan(brief, groups, embeddings=None):
    """(groups to deal from in order, setting): the places this run deals, by the rules above; ([], "") for none."""
    level, words, facts = levels(brief)["place"], kept_words(brief).get("place"), _facts(brief)
    if level != "free" and not words:
        return [], ""  # a kept place without its words (a brief from before version 15): the writer keeps it
    if words:
        setting = facts["setting"]
        found = match(in_world(groups, None if setting else facts["world"]), _without(words, setting), embeddings)
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
    selected = [group for group in groups if group["selected"]]
    if selected:
        return selected, ""  # the user's own places come first
    return _from_ideas(brief, groups, facts, embeddings, adult_first=brief.get("path") == "nsfw_character"), ""


def _from_ideas(brief, groups, facts, embeddings, adult_first):
    """The groups Understanding's ideas name among the groups of the request's world, in the most varied order; the
    adult_default groups lead when adult_first."""
    pool = in_world(groups, facts["world"])
    if embeddings is not None:
        embeddings.prepare(facts["ideas"])  # every idea embedded in one call
    first = [group for group in pool if group["adult"]] if adult_first else []
    found = _merged(first + [group for idea in facts["ideas"] for group in match(pool, idea, embeddings)])
    scores = [2.0 if group in first else 1.0 for group in found]  # the adult default leads; then the most varied order
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
