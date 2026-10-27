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

from ....vocabulary.retrieval import content_words, exact_search, groups_of, requested_parts, telling_words, word_stem
from ....vocabulary.selection import deal_composed
from ..consistency import kept_words
from ..understanding import is_human, stated_gender
from .request import varied_labels

SUBJECTS = "Subjects"
FIELDS = ("skin", "hair", "eyes")


def look_groups(catalog):
    """The built-in looks: the always-on Subjects groups."""
    return groups_of(catalog, SUBJECTS, {"packs": []})


def _looks_for(groups, person):
    return exact_search(groups, stated_gender(person)) or groups


def _own_words(brief, person):
    """A person's words about how they look: their label and appearance; a brief before version 17 has no appearance,
    so the subject's words count for its only person."""
    if "appearance" in person:
        return f'{person["label"]}, {person["appearance"]}'
    alone = len(brief["characters"]) == 1
    return f'{person["label"]}, {kept_words(brief).get("subject", "") if alone else ""}'


def _looked(brief, groups):
    """The people dealt a look: every human whose looks vary, when there are looks."""
    return [person for person in brief["characters"]
            if groups and person["label"] in varied_labels(brief) and is_human(person)]


def _wanted(brief, groups):
    """{label: (their looks, the parts their words fix, their details no part holds)} for every character; a detail that
    only repeats their label ("dancer") is not one."""
    looked = {person["label"] for person in _looked(brief, groups)}
    wanted = {}
    for person in brief["characters"]:
        pool = _looks_for(groups, person) if person["label"] in looked else []
        fixed, rest = requested_parts(pool, _own_words(brief, person))
        label = {word_stem(word) for word in content_words(person["label"])}
        wanted[person["label"]] = (pool, fixed, [detail for detail in rest
                                                 if not {word_stem(word) for word in content_words(detail)} <= label])
    return wanted


def deal_looks(brief, groups, total, rng):
    """{slot: {label: look}} for every human whose looks vary; {} when none is dealt (see the module docstring)."""
    wanted = _wanted(brief, groups)
    pools = {}
    for person in _looked(brief, groups):
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


def requested_details(brief, groups):
    """{label: the request's own details about that person that no dealt look holds}, for everyone who has any."""
    return {label: details for label, (_, _, details) in _wanted(brief, groups).items() if details}


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
    """Why a scene does not give a person their dealt look, as reasons to ask again ([] when it does): their skin, hair
    and eyes say at least one of the look's words (look_words)."""
    person = (scene.get("subjects") or {}).get(label) or {}
    own = ((words or {}).get(look) or frozenset(content_words(look))) - set(FIELDS)  # every look names the fields
    said = set(content_words(" ".join(str(person.get(field, "")) for field in FIELDS)))
    if not person or own & said:
        return []
    return [f'{label} does not have their dealt look: give {label} {look} (skin, hair and eyes)']
