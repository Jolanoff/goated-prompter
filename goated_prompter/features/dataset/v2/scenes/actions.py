"""Actions & Poses: the act and arrangement each image is built on, from the user's selected Actions & Poses packs,
found by the shared vocabulary engine (vocabulary/retrieval.py) and dealt by its selection (vocabulary/selection.py).
No model call chooses them.

An entry is a whole interaction with its people as letters (A, B, C), kept as written: the act and the physical
arrangement go together. action_plan keeps the entries made for the cast's number of people (retrieval.for_cast: a
pair gets entries for two, a group entries for a group; an entry for fewer people only when the packs have none for
the cast), without those that say what the request rules out (retrieval.without_said). When the request keeps an
action ("dancing close", "one riding the other"), only the entries that show it stay (retrieval.match: a group's
trigger words, then the entries that say the action's own words; closeness in meaning alone never finds one); when
none does, none is dealt and the writer builds the scene from the request, which is never replaced by an unrelated
entry. When the request leaves the action open, every fitting entry may be dealt.

The request's act comes before the vocabulary. Understanding gives each separate act with who does it and who it is
done to or for (the brief's acts). An entry is one interaction of the cast, so a request with several separate acts
(one reads while another paints) gets none: an entry would keep one act and drop the others.
Who an entry can place: a group made for people (one without "kinds") holds only humans, so its entries are made for
the cast's number of humans and an act with any other character in it (a person and an animal) gets none of them; a
group with kinds also holds characters of those kinds (understanding.is_human, the brief's kinds). When an act is done
to or for another character (one guides, feeds or holds another), only the entries that give someone their own part
stay (distinct_roles): an entry in which everyone does the group's own act together (both stretching a cloth, both
walking side by side) is a shared act, whatever detail one of them adds ("A turning their head toward B").
What the act is done with: the things the request names inside its own action words (kept objects that the action
also says, "with rackets") are part of the act. An entry stays only when it, or its group's words, says each of them
in any form; an entry with other gear or none would change the act.

deal_actions spreads the set over the groups (selection.deal_spread), so the images get different kinds of
interaction; a locked action is one entry for every image. Places and props are paired with the dealt entries
afterwards (places.py, props.py), so each image is one coherent scene.

A live run judged the fit with a separate model call; the request's own action words and the cast now decide it.
"""

import re

from ....vocabulary.retrieval import content_words, for_cast, match, without_said, word_stem
from ....vocabulary.selection import deal_spread
from ..consistency import kept_words
from ..understanding import is_human


_NAME = re.compile(r"^[^,.:]*:\s*")  # an entry's own name before its colon ("Slow dance: ")
# Who it opens with: everyone ("A and B", "A, B and C", "A group") or one person ("A").
_ROSTER = re.compile(r"^\s*(?:A group\b|[A-Z](?:(?:\s*,\s*|\s+and\s+)[A-Z])*\b)")
# A person named alone after that, or the rest of the group doing something of their own ("the other's hand" and "the
# others' paths" say whose, not who acts).
_OWN_PART = re.compile(r"\b[A-Z]\b|\bthe others\b(?!['’])")


def _stems(texts):
    return {word_stem(word) for text in texts for word in content_words(text)}


def distinct_roles(entry, group_words=()):
    """Whether an entry gives someone their own part: it opens with one person acting ("A smoothing B's collar", "B
    handing over a cup while A ..."), or, opening with everyone, it names one of them alone or the others ("A and B
    facing each other, B gripping A's wrist", "A group ..., A pointing while the others ..."). Everyone doing the
    group's own act together ("A and B walking side by side", for a group whose words say walking) is a shared act,
    whatever detail one of them adds after it."""
    body = _NAME.sub("", str(entry))
    roster = _ROSTER.match(body)
    if not roster:
        return bool(_OWN_PART.search(body))
    rest = body[roster.end():]
    if not re.search(r",|\band\b|group", roster.group()):
        return True
    first = content_words(rest)[:1]
    if first and word_stem(first[0]) in _stems(group_words):
        return False
    return bool(_OWN_PART.search(rest))


def _holds(group, person):
    """Whether a group's entries can place a character: a human always, another kind when the group lists it."""
    return is_human(person) or person.get("kind") in (group.get("kinds") or ())


def _act_cast(brief, groups):
    """The pool with each group's entries made for the characters it can place (retrieval.for_cast, groups that hold
    the same kinds counted together); without the groups that cannot place someone the request's act involves."""
    people = brief["characters"]
    involved = {label for act in brief.get("acts") or () for label in (*act["who"], *act["to"])}
    pool = []
    kinds_of = lambda group: tuple(group.get("kinds") or ())
    for kinds in dict.fromkeys(map(kinds_of, groups)):
        alike = [group for group in groups if kinds_of(group) == kinds]
        if all(_holds(alike[0], person) for person in people if person["label"] in involved):
            size = sum(person.get("count") if type(person.get("count")) is int else 1
                       for person in people if _holds(alike[0], person))
            pool += for_cast(alike, size) if size else []
    return pool


def _with_things(groups, brief):
    """The groups with only the entries that keep what the act is done with: each kept object the action also says
    must be said by the entry or its group's words, in any form (its last content word, the thing itself)."""
    words = kept_words(brief)
    action, objects = words.get("action", ""), words.get("objects", "")
    said = _stems([action])
    things = [stems[-1] for part in re.split(r"[,;]|\band\b", objects if isinstance(objects, str) else "")
              if (stems := [word_stem(word) for word in content_words(part)]) and stems[-1] in said]
    if not things:
        return groups
    kept = [{**group, "entries": [entry for entry in group["entries"]
                                  if set(things) <= _stems([entry, group["name"], *group["words"]])]} for group in groups]
    return [group for group in kept if group["entries"]]


def action_plan(brief, groups, embeddings=None):
    """The Actions & Poses groups the images may be dealt, each with only its fitting entries; [] when none fits (see
    the module docstring)."""
    acts = brief.get("acts") or []
    if len(acts) > 1:
        return []
    pool = without_said(_act_cast(brief, groups), brief.get("avoid") or ())
    if any(act["to"] for act in acts):
        pool = [kept for group in pool if (kept := {**group, "entries": [
            entry for entry in group["entries"] if distinct_roles(entry, [group["name"], *group["words"]])]})["entries"]]
    words = kept_words(brief).get("action", "")
    return _with_things(match(pool, words, embeddings, entry_words=True), brief) if words else pool


def deal_actions(groups, total, rng, locked=False):
    """{slot: entry}: the set spread over the groups in a seeded order; one entry for every image when locked."""
    order = list(groups)
    rng.shuffle(order)
    return deal_spread(order, total, rng, locked)
