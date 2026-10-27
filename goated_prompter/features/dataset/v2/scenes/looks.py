"""Looks and requested details of the people in a set.

Details: every character's appearance (understanding: the request's own words about how that person looks, "a short
beard", "sleeve tattoos", "22 year old") holds in every image, whatever the vocabulary: what no dealt look holds goes
with every image as that person's details (requested_details, DETAILS_RULE), and code adds one a scene leaves out to
its extras in the request's own words (with_details; a live writer asked three times still gave no beard). Nothing is
added to a person that the request and their look do not give.

Looks: every human whose looks vary from image to image (request.varied_labels) is dealt a look in every image: a hair
style and colour, eyes and skin tone from the built-in looks (the always-on Subjects packs,
vocabulary/Subjects/Female.json and Male.json, one group each), so the people of a set differ. The writer keeps the
look's skin tone, hair colour, hairstyle and eye colour and describes the person as before; build follows the request
or is chosen anew (LOOK_RULE). A person's stated sex finds their group by the group's words ("female", "male"); a
person whose sex the request does not state gets looks of either, never a sex of its own, and a character that is not
a human (understanding.is_human: an animal, a creature, a robot, an object, whatever its sex) none: its own
description is its look. A look is made of parts (retrieval.entry_parts): what the person's words ask of a part fixes
that part in every image ("ginger": the hair, "green eyes": the eyes) and every other part varies with the dealt look
(retrieval.requested_parts, selection.deal_composed); a live set that kept whole looks gave a ginger man with green
eyes the same hairstyle and skin in every image. Looks are not searched by meaning: their words are too much alike for
it ("a tall woman" ranks a blonde look first). With the user's own Subjects packs selected, they are suggestions as
before and no built-in look is dealt. No model call: code finds and deals the looks.
"""

from ....vocabulary.retrieval import (content_words, exact_search, groups_of, match, requested_parts, telling_words,
                                      word_stem)
from ....vocabulary.selection import deal_composed
from ..consistency import kept_words
from ..understanding import is_human, stated_gender
from .request import varied_labels

SUBJECTS = "Subjects"
FIELDS = ("skin", "hair", "eyes")
NONHUMAN_FIELDS = ("covering", "features", "build")  # where a look that is not a human's shows (settings)


def look_groups(catalog):
    """The built-in looks: the always-on Subjects groups."""
    return groups_of(catalog, SUBJECTS, {"packs": []})


def _looks_for(groups, person, embeddings=None):
    """The groups a character's looks come from. A human's are the groups made for humans (no kinds), found by their
    stated sex, looks of either when it is unstated. Any other character's are the groups made for its kind whose
    words its own words say ("a black cat": fur), else the one meaning picks out (retrieval.match), else the only one
    of its kind; none when no group fits it, and then nothing is dealt. A brief before kinds deals none to it."""
    if is_human(person):
        human = [group for group in groups if not group.get("kinds") or "human" in group["kinds"]]
        return exact_search(human, stated_gender(person)) or human
    pool = [group for group in groups if person.get("kind") in (group.get("kinds") or ())]
    text = f'{person["label"]}, {person.get("custom", "")}'
    named = {group["name"] for group in match(pool, text, embeddings)} if pool and embeddings else set()
    return exact_search(pool, text) or [group for group in pool if group["name"] in named] or (
        pool if len(pool) == 1 else [])


def _own_words(brief, person):
    """A character's words about how it looks: its label, its description when it is not a human ("black cat") and its
    appearance; a brief before version 17 has no appearance, so the subject's words count for its only person."""
    if "appearance" in person:
        return ", ".join(filter(None, (person["label"], person.get("custom", ""), person["appearance"])))
    alone = len(brief["characters"]) == 1
    return f'{person["label"]}, {kept_words(brief).get("subject", "") if alone else ""}'


def _pools(brief, groups, embeddings=None):
    """{label: the groups its looks come from} for every character whose looks vary and that some group fits."""
    varied = varied_labels(brief) if groups else ()
    return {person["label"]: pool for person in brief["characters"]
            if person["label"] in varied and (pool := _looks_for(groups, person, embeddings))}


def _looked(brief, groups, embeddings=None):
    """The characters dealt a look: every one whose looks vary and that a group of looks fits."""
    pools = _pools(brief, groups, embeddings)
    return [person for person in brief["characters"] if person["label"] in pools]


def _wanted(brief, groups, embeddings=None):
    """{label: (their looks, the parts their words fix, their details no part holds)} for every character; a detail that
    only repeats their label ("dancer") is not one."""
    pools = _pools(brief, groups, embeddings)
    wanted = {}
    for person in brief["characters"]:
        pool = pools.get(person["label"], [])
        fixed, rest = requested_parts(pool, _own_words(brief, person))
        label = {word_stem(word) for word in content_words(person["label"])}
        wanted[person["label"]] = (pool, fixed, [detail for detail in rest
                                                 if not {word_stem(word) for word in content_words(detail)} <= label])
    return wanted


def deal_looks(brief, groups, total, rng, embeddings=None):
    """{slot: {label: look}} for every character whose looks vary and that a group of looks fits; {} when none is dealt
    (see the module docstring)."""
    wanted = _wanted(brief, groups, embeddings)
    pools = {}
    for person in _looked(brief, groups, embeddings):
        pool, fixed, _ = wanted[person["label"]]
        key = (tuple(map(id, pool)), tuple((facet, tuple(parts)) for facet, parts in sorted(fixed.items())))
        pools.setdefault(key, (pool, fixed, []))[2].append(person["label"])
    if not pools:
        return {}
    dealt = {number: {} for number in range(1, total + 1)}
    for pool, fixed, labels in pools.values():
        # One deal for everyone who shares a pool, image by image: the people of one image get different looks.
        looks = deal_composed(pool, fixed, total * len(labels), rng)
        for number in range(1, total + 1):
            for index, label in enumerate(labels):
                dealt[number][label] = looks[(number - 1) * len(labels) + index + 1]
    return dealt


def requested_details(brief, groups, embeddings=None):
    """{label: the request's own details about that person that no dealt look holds}, for everyone who has any."""
    return {label: details for label, (_, _, details) in _wanted(brief, groups, embeddings).items() if details}


def with_details(scene, details):
    """The scene with every requested detail (requested_details) it leaves out added to its extras as "label: detail",
    in the request's own words; one is shown when any of its words, in any form, is on that person or in the extras."""
    added = []
    for label, wanted in (details or {}).items():
        person = (scene.get("subjects") or {}).get(label)
        if not person:
            continue
        said = {word_stem(word) for word in content_words(" ".join([*map(str, person.values()), str(scene.get("extras", ""))]))}
        added += [f"{label}: {detail}" for detail in wanted if not {word_stem(word) for word in content_words(detail)} & said]
    return {**scene, "extras": "; ".join([str(scene.get("extras") or "").rstrip("; ."), *added]).strip("; ")} if added else scene


def look_words(groups, brief, dealt):
    """{look: the words that show it was used} for every dealt look: its words that tell looks apart across the
    catalog (retrieval.telling_words), and the request's own words about the people, which replace a part of a look."""
    rare = set().union(*telling_words(groups).values()) if groups else set()
    said = set(content_words(" ".join([kept_words(brief).get("subject", ""),
                                       *(person.get("appearance", "") for person in brief["characters"])]))) - set(FIELDS)
    return {look: frozenset({word for word in content_words(look) if word in rare} | said)
            for looks in dealt.values() for look in looks.values()}


def look_problems(scene, label, look, words=None):
    """Why a scene does not give a character its dealt look, as reasons to ask again ([] when it does): the fields its
    look shows in (a person's skin, hair and eyes; any other character's covering, features and build) say at least
    one of the look's words (look_words)."""
    person = (scene.get("subjects") or {}).get(label) or {}
    fields = NONHUMAN_FIELDS if "covering" in person else FIELDS
    own = ((words or {}).get(look) or frozenset(content_words(look))) - set(FIELDS)  # every look names the fields
    said = set(content_words(" ".join(str(person.get(field, "")) for field in fields)))
    if not person or own & said:
        return []
    return [f'{label} does not have their dealt look: give {label} {look} ({", ".join(fields[:-1])} and {fields[-1]})']
