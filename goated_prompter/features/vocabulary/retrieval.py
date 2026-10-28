"""Vocabulary retrieval: which entries of a category a text names. Shared by every category: Spaces
(dataset/v2/scenes/places.py), Actions & Poses (actions.py), Objects & Props (props.py), the looks (looks.py) and the
cameras (camera.py).
Retrieval finds entries; it does not decide what a request allows (Understanding does) or choose a set (selection.py
does).

Index (groups_of): the groups of the run's selected packs of the category, then of its always-on packs. A grouped
pack gives its groups (catalog.py); a plain pack's entries are each a group named by the entry. An entry in two packs
is listed once, where it comes first.
Constraints: in_world (the request's world), in_shape (the image shape), for_cast (the entries made for the cast's
number of people) and without_said (no entry that says what the request rules out).
Exact words (exact_hits): a group's words said whole in the text, in order, a plural ending and a possessive "'s"
aside. A word said inside a longer word that another group says does not count ("water" inside "water aquarium").
Entry words (said_entries): the entries that say the text's own distinctive words in any form, for packs of plain
entries that have no group words ("one riding the other" finds the entries that say riding). With entry words, words
decide: a group whose words the text says in any form ("reads" says reading: said_groups), or an entry that says
them, and closeness in meaning alone finds nothing (an act is not shown by an entry that is only near it in
meaning).
Scoring (relevance): each group's closeness in meaning to the text (embeddings.py), compared with the other groups,
plus its share of the text's content words.
match: the groups a text names, or none. Exact words decide when they explain every content word of the text; a
word match that leaves words unexplained stays only when meaning also rates its group highly (MATCH_AGREE: "sports
hall" is not the corridor's "hall", "a cozy bedroom" is a bedroom); without exact words, the one group that stands
out from all the others (MATCH_Z, MATCH_LEAD). The found groups keep only the entries the text points to (narrowed:
their name, or the details the group's words do not explain). A text no group clearly answers finds nothing: a weak
match is never forced.
requested_parts: what a text asks of each part of entries made of parts ("ginger" of the hair, "green eyes" of the
eyes), word for word in any form, for entries too alike in meaning to tell apart by it, and the details no part holds
(dataset/v2/scenes/looks.py).
"""

import math
import re

from .catalog import always_on
from .embeddings import dot

MATCH_Z = 2.0     # a group found by meaning stands this far above the average group ...
MATCH_LEAD = .6   # ... and this far above the next one
MATCH_AGREE = 1.5  # a word match that leaves words unexplained is kept when meaning rates its group at least this high
WORD_WEIGHT = 1.5  # a group that has all of a text's content words gains this many deviations of meaning
COMMON_SHARE = .1  # a word in more than this share of the entries says too little to tell them apart

# Words that say nothing about what an entry is ("a", "with", "his"); everything else is a content word.
FUNCTION_WORDS = frozenset("""a an the and or but nor of in on at to for from by with without into onto over under
above below behind beside between near across along around through about against among off up down out his her
their its my your our him them it he she they we you i me is are was were be been being has have had do does did this
that these those there here one two some any each every all both other another while who whom which what where when
how as so than then just very too also only not no together""".split())


def base_word(word):
    """A word without a regular plural ending, so "rooms" and "room" read alike."""
    return word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 3 else word


def word_sequence(text):
    """Every word of a text in order, plural endings and a possessive "'s" aside."""
    return tuple(base_word(word) for word in re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", str(text or "").casefold())))


def word_stem(word):
    """A word without its regular ending, so the forms of a word read alike ("freckles", "freckled": "freckl";
    "tanned", "tan": "tan"; "eyed", "eyes": "ey"); a stem shorter than two letters keeps the word ("red")."""
    word = base_word(word)
    stem = re.sub(r"(ing|ed|e|y)$", "", word)
    stem = stem[:-1] if len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouls" else stem
    return stem if len(stem) >= 2 else word


def content_words(text):
    """The words of a text that say what it is about (FUNCTION_WORDS left out), plural endings aside."""
    return [word for word in word_sequence(text) if word not in FUNCTION_WORDS]


def entry_name(entry):
    """An entry's name: its text before "with", a colon or a comma ("attic bedroom with a round window" -> "attic
    bedroom")."""
    return re.split(r"\s+with\s+|[:,;]", str(entry), maxsplit=1)[0].strip()


def _spans(said, phrase):
    return [(start, start + len(phrase)) for start in range(len(said) - len(phrase) + 1)
            if phrase and said[start:start + len(phrase)] == phrase]


def groups_of(catalog, category, selection):
    """[{"name", "words", "entries", "worlds", "shapes", "kinds", "people", "adult", "selected"}]: the selected packs'
    groups, then the always-on ones'. A group's words include its name; worlds and shapes are None when the group fits
    every world or image shape, kinds when it is a human's; people is {entry: how many people it needs} for the
    entries that say so."""
    chosen = set(selection.get("packs") or ())
    packs = [pack for pack in catalog["packs"] if pack["category"] == category and pack["id"] in chosen]
    packs += [pack for pack in always_on(catalog, category) if pack["id"] not in chosen]
    rows, seen = [], set()
    key = lambda entry: " ".join(entry.split()).casefold()
    for pack in packs:
        for group in pack.get("groups") or [{"name": entry_name(entry), "words": [], "entries": [entry]}
                                            for entry in pack["entries"]]:
            own = [entry for entry in group["entries"] if key(entry) not in seen]
            seen.update(key(entry) for entry in own)
            if own:
                rows.append({"name": group["name"],
                             "words": list(dict.fromkeys([group["name"].casefold(), *group["words"]])),
                             "entries": own, "worlds": tuple(group["worlds"]) if group.get("worlds") else None,
                             "shapes": tuple(group["shapes"]) if group.get("shapes") else None,
                             "kinds": tuple(group["kinds"]) if group.get("kinds") else None,
                             "people": {entry: count for entry, count in (pack.get("people") or {}).items()
                                        if entry in own},
                             "adult": bool(group.get("adult_default")), "selected": pack["id"] in chosen})
    return rows


def in_world(groups, world):
    """The groups that fit a world (every group when world is None; a group without worlds fits every world)."""
    return [group for group in groups if not world or group["worlds"] is None or world in group["worlds"]]


def in_shape(groups, shape):
    """The groups that fit an image shape (every group when shape is None; a group without shapes fits every shape)."""
    return [group for group in groups if not shape or group.get("shapes") is None or shape in group["shapes"]]


def for_cast(groups, size):
    """The groups with only the entries that fit a cast of size people: those made for exactly that many, else for the
    most people below it (an entry for three is a group, so it serves a larger one too); an entry that gives no count
    fits every cast. A group left with no entry is left out."""
    counts = {count for group in groups for count in (group.get("people") or {}).values()}
    best = max((count for count in counts if count <= size), default=None)
    kept = [{**group, "entries": [entry for entry in group["entries"]
                                  if (group.get("people") or {}).get(entry, best) == best]} for group in groups]
    return [group for group in kept if group["entries"]]


def without_said(groups, phrases):
    """The groups without the entries that say what a phrase rules out: every content word of one of the phrases, in
    any form (word_stem), so "no kneeling" keeps no entry that says kneeling. A group left with no entry is left out."""
    ruled = [stems for phrase in phrases if (stems := {word_stem(word) for word in content_words(phrase)})]
    if not ruled:
        return groups
    says = lambda entry: {word_stem(word) for word in content_words(entry)}
    kept = [{**group, "entries": [entry for entry in group["entries"]
                                  if not any(stems <= says(entry) for stems in ruled)]} for group in groups]
    return [group for group in kept if group["entries"]]


ENTRY_WORD_SHARE = .25  # a text's word in more of the entries than this says too little to choose them


def said_entries(groups, text, share=ENTRY_WORD_SHARE):
    """The groups with only the entries that say the text's distinctive words: its content words, in any form
    (word_stem), that some but at most share of the entries say (1: any word an entry says, for a pack whose entries
    all show one act, where its word keeps them all); an entry whose words of the text are only
    part of another entry's is about less of it ("a reading room" names the reading room entries, not every other
    room, while "a lantern and an oil lamp" keeps both). [] when no entry says one."""
    entries = [entry for group in groups for entry in group["entries"]]
    says = {entry: {word_stem(word) for word in content_words(entry)} for entry in entries}
    asked = {word_stem(word) for word in content_words(text)}
    rare = {word for word in asked
            if 0 < sum(word in words for words in says.values()) <= max(1, share * len(entries))}
    shared = {entry: frozenset(says[entry] & rare) for entry in entries}
    kept = [{**group, "entries": [entry for entry in group["entries"]
                                  if shared[entry] and not any(shared[entry] < other for other in shared.values())]}
            for group in groups]
    return [group for group in kept if group["entries"]]


def group_text(group):
    """What a group means, for its embedding: its name and words."""
    return f'{group["name"]}: {", ".join(group["words"])}'


def exact_hits(groups, text):
    """{group index: how many of its words the text says}; a word inside a longer said word does not count."""
    said, matches = word_sequence(text), []
    for number, group in enumerate(groups):
        for word in group["words"]:
            matches += [(start, end, number, word) for start, end in _spans(said, word_sequence(word))]
    counted = {}
    for start, end, number, word in matches:
        if not any(other[0] <= start and end <= other[1] and other[1] - other[0] > end - start for other in matches):
            counted.setdefault(number, set()).add(word)
    return {number: len(words) for number, words in counted.items()}


def said_groups(groups, text):
    """The groups one of whose words the text says in any form (word_stem: "reads" says "reading", "cleans the house"
    says "cleaning"), every content word of it; [] when none."""
    said = {word_stem(word) for word in content_words(text)}
    return [group for group in groups
            if any((stems := {word_stem(word) for word in content_words(phrase)}) and stems <= said
                   for phrase in group["words"])]


def exact_search(groups, text):
    """The groups whose words the text says most often; [] when it says none."""
    hits = exact_hits(groups, text) if str(text or "").strip() else {}
    top = max(hits.values(), default=0)
    return [group for number, group in enumerate(groups) if top and hits.get(number) == top]


NARROW_Z = 1.5  # an entry this many deviations closer in meaning than the group's other entries is the one meant


def entry_parts(entry):
    """An entry's parts in order, as (facet, text): its phrases between " with ", " and " and commas ("long wavy black
    hair with green eyes and fair skin": hair, eyes, skin), each named by its last word's stem (word_stem), the thing
    it describes. Entries made of parts can be recombined part by part (selection.deal_composed)."""
    parts = [" ".join(part.split()) for part in re.split(r"\s+(?:with|and)\s+|\s*[,;:]\s*", str(entry))]
    return [(word_stem(words[-1]), part) for part in parts if (words := content_words(part))]


def requested_parts(groups, text):
    """({facet: the parts that say what the text asks of that facet}, the text's details no part can hold, in its own
    words). A detail is a run of the text's content words the groups' own words do not explain ("ginger", "green eyes"
    of "a ginger man with green eyes"): it fixes the facet whose parts say it, in order within one part, in any form of
    each word (word_stem: "freckles" says "freckled", "blue-eyed" says "blue eyes"), and every other facet stays free.
    It belongs to the facet its words name ("green eyes": eyes), else to the one whose parts say it nearest their own
    last word ("pale skin" over "pale blue eyes"). A word no part says that starts with one a part says reads as that
    word ("redhead": red); a run no part says whole is read word by word when its last word is one parts say
    ("freckled redhead"). A detail no part says ("sleeve tattoos", "22 year old"), one that contradicts a detail
    before it in the same facet, or one whose facet no entry has together with the facets already fixed (a beard
    beside hair) is returned in the text's own words: the text still asks for it."""
    explained = {word_stem(word) for group in groups for phrase in [group["name"], *group["words"]]
                 for word in content_words(phrase)}
    entries = [entry for group in groups for entry in group["entries"]]
    shapes = [{facet for facet, _ in entry_parts(entry)} for entry in entries]
    parts = {part: (facet, tuple(map(word_stem, word_sequence(part))))
             for entry in entries for facet, part in entry_parts(entry)}
    known = sorted({word for _, words in parts.values() for word in words}, key=len, reverse=True)

    def saying(detail):  # the parts with the detail's words in order, other words between them allowed
        return [part for part, (_, words) in parts.items()
                if all(word in rest for rest in [iter(words)] for word in detail)]

    def read(word):
        stem = word_stem(word)
        if stem in known:
            return stem
        return next((part for part in known if len(part) >= 3 and len(word) - len(part) >= 3 and word.startswith(part)),
                    stem)

    clean = re.sub(r"['’]s\b", "", str(text or "").casefold())
    runs, run = [], []
    for match in (*re.finditer(r"[a-z0-9]+", clean), None):
        word = base_word(match.group()) if match else ""
        if run and (not match or re.search(r"[^\s'’-]", clean[run[-1][2]:match.start()])):  # a comma ends a run
            runs, run = runs + [run], []
        if word and word not in FUNCTION_WORDS and word_stem(word) not in explained:
            run.append((read(word), match.start(), match.end()))
        elif run:
            runs, run = runs + [run], []
    details, rest = [], []
    for run in runs:
        words = tuple(word for word, _, _ in run)
        if saying(words):
            details.append((words, clean[run[0][1]:run[-1][2]]))
        elif words[-1] in known:
            details += [((word,), clean[start:end]) for word, start, end in run if word in known]
            rest += [clean[start:end] for word, start, end in run if word not in known]
        else:
            rest.append(clean[run[0][1]:run[-1][2]])
    fixed = {}
    for words, phrase in details:
        found = saying(words)
        facets = {parts[part][0] for part in found}
        named = facets & set(words)
        distance = lambda facet: min(len(parts[part][1]) - 1 - max(parts[part][1].index(word) for word in words)
                                     for part in found if parts[part][0] == facet)
        facet = min(named or facets, key=lambda facet: (distance(facet), -sum(parts[part][0] == facet for part in found)))
        kept = [part for part in found if parts[part][0] == facet and part in fixed.get(facet, [part])]
        if kept and any(set(fixed) | {facet} <= shape for shape in shapes):
            fixed[facet] = kept
        else:
            rest.append(phrase)
    return fixed, rest


def narrowed(groups, text, embeddings=None):
    """The groups with only the entries the text points to: those whose own name it says; else, when it has words the
    groups' own words do not explain ("rainy" of "a rainy street", "white" of "a white background"), those that
    stand out in meaning among all the groups' entries (NARROW_Z). Unchanged when it points to none: "his room" is
    every bedroom."""
    said = word_sequence(text)
    named = [{**group, "entries": [entry for entry in group["entries"] if _spans(said, word_sequence(entry_name(entry)))]}
             for group in groups]
    named = [group for group in named if group["entries"]]
    if named:
        return named
    explained = {word for group in groups for phrase in [group["name"], *group["words"]] for word in content_words(phrase)}
    entries = [entry for group in groups for entry in group["entries"]]
    query = embeddings.query(text) if embeddings is not None and set(content_words(text)) - explained else None
    vectors = embeddings.documents(entries) if query is not None else None
    if vectors is None:
        return groups
    close = {entry for entry, score in zip(entries, zscores(dot(query, vector) for vector in vectors)) if score >= NARROW_Z}
    picked = [{**group, "entries": [entry for entry in group["entries"] if entry in close]} for group in groups]
    return [group for group in picked if group["entries"]] or groups


def zscores(values):
    """Each value as standard deviations above the mean of all of them (0 for all when they do not differ)."""
    values = list(values)
    if len(values) < 2:
        return [0.0 for _ in values]
    mean = sum(values) / len(values)
    spread = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    return [(value - mean) / spread if spread > 1e-9 else 0.0 for value in values]


def word_scores(groups, text):
    """How much of the text's content each group's own text (its name, words and entries) has, from 0 to 1: the share
    of the text's content words it has, each weighted by how few groups have it, so a word every group has counts
    little. Bounded, so one shared word never outweighs everything else."""
    documents = [set(content_words(" ".join([group["name"], *group["words"], *group["entries"]]))) for group in groups]
    query = set(content_words(text))
    if not query or not documents:
        return [0.0 for _ in groups]
    rarity = {word: math.log((len(documents) + 1) / (sum(word in document for document in documents) + 1)) + 1
              for word in query}
    whole = sum(rarity.values())
    return [sum(rarity[word] for word in query & document) / whole for document in documents]


def meaning_scores(groups, text, embeddings):
    """How close each group is in meaning to the text: its own text or its closest entry, whichever is closer; None
    without embeddings or when they fail."""
    query = embeddings.query(text) if embeddings is not None and groups and str(text or "").strip() else None
    if query is None:
        return None
    texts = [group_text(group) for group in groups]
    entries = [entry for group in groups for entry in group["entries"]]
    vectors = embeddings.documents(texts + entries)
    if vectors is None:
        return None
    by_text = dict(zip(texts + entries, vectors))
    return [max(dot(query, by_text[text]), *(dot(query, by_text[entry]) for entry in group["entries"]))
            for text, group in zip(texts, groups)]


def relevance(groups, text, embeddings=None):
    """How well each group answers the text compared with the other groups: its closeness in meaning as a z-score over
    the groups, plus its share of the text's content words (word_scores, weighted by WORD_WEIGHT). Words alone without
    embeddings."""
    words = word_scores(groups, text)
    meaning = meaning_scores(groups, text, embeddings)
    if meaning is None:
        return words
    return [WORD_WEIGHT * w + m for w, m in zip(words, zscores(meaning))]


def _standout(groups, text, embeddings):
    """The one group that stands out from all the others for the text (MATCH_Z, MATCH_LEAD); [] when none does."""
    if len(groups) < 3:
        return []
    scores = sorted(zip(relevance(groups, text, embeddings), range(len(groups))), reverse=True)
    (top, index), (runner_up, _) = scores[0], scores[1]
    return [groups[index]] if top >= MATCH_Z and top - runner_up >= MATCH_LEAD else []


def match(groups, text, embeddings=None, entry_words=False):
    """The groups the text names (see the module docstring), the user's selected packs' groups first, each with only
    the entries the text points to (narrowed); [] when no group clearly answers it. With entry_words, the entries that
    say the text's words (said_entries, any share) take the place of meaning: meaning alone finds nothing."""
    if not groups or not str(text or "").strip():
        return []
    hits = exact_search([group for group in groups if group["selected"]], text) or exact_search(groups, text)
    explained = {word for group in hits for phrase in group["words"] for word in content_words(phrase)}
    if hits and not set(content_words(text)) <= explained:
        # Judged by meaning alone: the hit already is the words' evidence. A wrong word match ("sports hall" said the
        # corridor's "hall") is rated low by meaning, a right one with a detail ("a cozy bedroom") high, even when a
        # group the detail fits is rated higher. Without embeddings the words are all the evidence there is.
        meaning = meaning_scores(groups, text, embeddings)
        if meaning is not None:
            scores = dict(zip(map(id, groups), zscores(meaning)))
            hits = [group for group in hits if scores[id(group)] >= MATCH_AGREE]
    found = hits or ((said_entries(groups, text, share=1) or said_groups(groups, text)) if entry_words
                     else _standout(groups, text, embeddings))
    return narrowed(found, text, embeddings) if found else []


def group_vectors(groups, embeddings):
    """One unit vector per group: the mean of its own text's and its entries' vectors (None without embeddings)."""
    if embeddings is None or not groups:
        return None
    texts = [[group_text(group), *group["entries"]] for group in groups]
    vectors = embeddings.documents([text for row in texts for text in row])
    if vectors is None:
        return None
    by_text = dict(zip([text for row in texts for text in row], vectors))
    total = [[sum(values) for values in zip(*(by_text[text] for text in row))] for row in texts]
    return [[value / (math.sqrt(sum(part * part for part in vector)) or 1.0) for value in vector] for vector in total]


RELATED_Z = 1.5  # a group this many deviations closer to an anchor than the other groups are is related to it


def related(candidates, anchors, groups, embeddings=None):
    """The candidates that are one of the anchors or related to one: closer in meaning to it than the other groups
    are by RELATED_Z (each group's mean vector, compared over all the groups). Without embeddings only the anchors
    themselves, so nothing is added on a guess."""
    names = {group["name"] for group in anchors}
    vectors = group_vectors(groups, embeddings)
    if vectors is None:
        return [group for group in candidates if group["name"] in names]
    by_name = dict(zip((group["name"] for group in groups), vectors))
    close = set(names)
    for anchor in names & set(by_name):
        others = [name for name in by_name if name != anchor]
        scores = zscores(dot(by_name[anchor], by_name[name]) for name in others)
        close |= {name for name, score in zip(others, scores) if score >= RELATED_Z}
    return [group for group in candidates if group["name"] in close]


def fit_scores(text, entries, embeddings=None):
    """How well each entry goes with the text (an entry of another category): closeness in meaning with embeddings,
    else the content words they share."""
    vectors = embeddings.documents([text, *entries]) if embeddings is not None else None
    if vectors is None:
        said = set(content_words(text))
        return [float(len(said & set(content_words(entry)))) for entry in entries]
    return [dot(vectors[0], vector) for vector in vectors[1:]]


def telling_words(groups):
    """{entry: the words that tell it apart}: its content words that few of all the entries have (COMMON_SHARE; a word
    of one entry is never common), or all of its content words when every one is common."""
    entries = [entry for group in groups for entry in group["entries"]]
    holding = {}
    for entry in entries:
        for word in set(content_words(entry)):
            holding[word] = holding.get(word, 0) + 1
    common = {word for word, count in holding.items() if count > max(1, COMMON_SHARE * len(entries))}
    return {entry: frozenset(set(content_words(entry)) - common or content_words(entry)) for entry in entries}
