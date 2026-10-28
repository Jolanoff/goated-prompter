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
done to or for (the brief's acts). An entry is one interaction of its people. A request with one act is planned as a
whole (action_plan). A request with several separate acts whose people do not overlap (one reads while another
paints) is planned act by act (act_plans): each act on its own people and words, by every rule below, so each image
is dealt one assignment per act (deal_assignments: the act, who does it, to whom, and its entry or none), every act
kept in order whether or not an entry fits it. Each assignment binds its entry's letters to its own people, the ones
who do the act first and then those it is done to, the same in every image (roles). A person in several acts keeps
one body: their acts' entries stay only when every one of their groups names its poses and some pose is in all of
them, with an entry for every one of their acts (posed: the image's pose for that person is dealt from those);
otherwise those entries are dropped, never their acts, and the writer builds the person's acts from the request. A group of entries never says its poses, so a person
in several acts gets none of its entries. Entries that suit opposite places (a beach and an office) cannot share one image: the one
its image's place suits less is dropped there, never its act (suited_to_place); the writer builds an act without an
entry from the request.
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

from ....vocabulary.retrieval import content_words, fit_scores, for_cast, match, without_said, word_stem, zscores
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
    """Whether a group's entries can place a character: a human always, another kind when the group lists it, anyone
    in a group of actions (people of any kind, each with its own body)."""
    return is_human(person) or person.get("kind") in (group.get("kinds") or ()) or bool(group.get("actions"))


def _act_cast(brief, groups):
    """The pool with each group's entries made for the characters it can place (retrieval.for_cast, groups that hold
    the same kinds counted together); without the groups that cannot place someone the request's act involves."""
    people = brief["characters"]
    involved = {label for act in brief.get("acts") or () for label in (*act["who"], *act["to"])}
    pool = []
    kinds_of = lambda group: (tuple(group.get("kinds") or ()), bool(group.get("actions")))
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


def several_acts(brief):
    """The brief's acts when there are several and each has someone in it (who or to); None otherwise."""
    acts = brief.get("acts") or []
    return acts if len(acts) >= 2 and all(act["who"] or act["to"] for act in acts) else None


def _people(act):
    return [*act["who"], *(label for label in act["to"] if label not in act["who"])]


def act_plans(brief, groups, embeddings=None):
    """[(act, groups)] for several acts (several_acts): each act planned on its own (action_plan) with only its own
    people and its own words as the kept action, so every rule holds per act; groups is [] when no entry fits it. An
    act whose person also takes part in another act keeps only the groups that name their poses (posed needs them).
    None for one act or none."""
    acts = several_acts(brief)
    if acts is None:
        return None
    shared = {label for index, act in enumerate(acts) for other in acts[index + 1:]
              for label in set(_people(act)) & set(_people(other))}
    plans = []
    for act in acts:
        people = set(_people(act))
        own = {**brief, "characters": [person for person in brief["characters"] if person["label"] in people],
               "kept_words": {**kept_words(brief), "action": act["act"]}, "acts": [act]}
        found = action_plan(own, groups, embeddings)
        plans.append((act, [group for group in found if group.get("poses")] if people & shared else found))
    return plans


_LETTER = re.compile(r"\b([A-Z])\b(?! group\b)")


def roles(entry, act):
    """{letter: label}: an entry's letters (A, B, C, in order) bound to the act's own people, who does it first, then
    those it is done to; people beyond its letters are "others" (the rest of a group the entry names so)."""
    letters = sorted(dict.fromkeys(_LETTER.findall(_NAME.sub("", str(entry)))))
    people = _people(act)
    bound = dict(zip(letters, people))
    rest = people[len(letters):]
    return {**bound, **({"others": rest} if rest else {})}


def posed(assigned, plans, rng):
    """The assignments with each entry's roles, and every person's pose for the image from their entries' groups. A
    person in several acts keeps their acts' entries only when every one of those acts has an entry whose group names
    its poses and one pose is in all of them (an act without one, or of unknown poses, is unknown, never compatible);
    otherwise those entries are dropped (their acts stay, for the writer to build from the request), never one act
    favoured over another. A person in one act gets a pose of that act's group when it names
    them."""
    poses_of = {entry: group.get("poses") for _, found in plans for group in found for entry in group["entries"]}
    result = {}
    for number, items in assigned.items():
        acts_of = {}
        for index, item in enumerate(items):
            for label in _people(item):
                acts_of.setdefault(label, []).append(index)
        dropped, pose = set(), {}
        for label, indexes in acts_of.items():
            dealt = [index for index in indexes if items[index]["entry"]]
            known = [poses_of.get(items[index]["entry"]) if items[index]["entry"] else None for index in indexes]
            if not dealt:
                continue
            if len(indexes) > 1 and (not all(known) or not set.intersection(*map(set, known))):
                dropped.update(dealt)  # an act of unknown pose, or no pose they all share: one body, no entries
            elif all(known):
                common = sorted(set.intersection(*map(set, known)))
                pose[label] = common[rng.randrange(len(common))] if len(common) > 1 else common[0]
        result[number] = []
        for index, item in enumerate(items):
            entry = None if index in dropped else item["entry"]
            result[number].append({**item, "entry": entry, "roles": roles(entry, item) if entry else {},
                                   "poses": {label: pose[label] for label in _people(item) if label in pose}})
    return result


def deal_assignments(plans, total, rng, locked=False):
    """{slot: [assignment]}: every image's acts in order, each {"act", "who", "to", "entry"}: the act with its own
    people and roles and the entry dealt to it from its own deck (deal_actions), or None when none fits it."""
    decks = [deal_actions(groups, total, rng, locked) if groups else {} for _, groups in plans]
    return {number: [{"act": act["act"], "who": list(act["who"]), "to": list(act["to"]), "entry": deck.get(number)}
                     for (act, _), deck in zip(plans, decks)] for number in range(1, total + 1)}


# Two entries cannot share a place when they rank the pool's places this oppositely (an outdoor and an indoor act: -0.6 to
# -1.0 with the built-in places, while acts that share a room or a path stayed above -0.1), judged over at least
# PLACE_POOL places (fewer ranked by chance).
PLACE_AGREE, PLACE_POOL = -0.5, 4


def _agree(left, right):
    """How alike two entries rank the same places: the correlation of their fits over the pool (-1 to 1)."""
    places = list(left)
    a, b = [left[place] for place in places], [right[place] for place in places]
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    top = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    low = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
    return top / low if low > 1e-12 else 1.0


def suited_to_place(assigned, places, pool, embeddings=None):
    """The assignments with the entries that cannot share their image's place dropped (their acts kept). Two entries
    of one image cannot share a place when they rank the pool's places in opposite order (_agree below PLACE_AGREE:
    one suits the places the other does not, a beach and an office); of such a pair, the one its image's dealt place suits less
    than its average place is dropped, never both. Entries that rank places alike share any of them, however noisy
    the scores of a pool of alike places. Unchanged without embeddings, places, or a pool of fewer than PLACE_POOL
    places."""
    if embeddings is None or not places or len(pool) < PLACE_POOL:
        return assigned
    fits = {}
    fit = lambda entry: fits.setdefault(entry, dict(zip(pool, zscores(fit_scores(entry, pool, embeddings)))))
    kept = {}
    for number, items in assigned.items():
        place, entries = places.get(number), [item["entry"] for item in items if item["entry"]]
        dropped = set()
        if place in pool:
            for index, left in enumerate(entries):
                for right in entries[index + 1:]:
                    if left in dropped or right in dropped or _agree(fit(left), fit(right)) >= PLACE_AGREE:
                        continue
                    worse = min((left, right), key=lambda entry: fit(entry)[place])
                    if fit(worse)[place] < 0:
                        dropped.add(worse)
        kept[number] = [{**item, "entry": None} if item["entry"] in dropped else item for item in items]
    return kept
