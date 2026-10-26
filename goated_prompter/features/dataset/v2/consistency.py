"""Consistency: which parts of the image stay the same across a dataset (options.dataset.CONSISTENCY_PARTS).

Each part has one level: locked (identical in every image), themed (every image follows the request's words for it and
the rest of that part varies) or free (chosen anew for each image). Understanding resolves the levels once per brief
(resolve): a part the user set by hand in the draft keeps that level; otherwise the request decides (a mentioned part
it asks to differ between images is free, one it asks to be identical is locked, any other mentioned part is at least
themed); otherwise the dataset type's default (options.dataset.TYPE_CONSISTENCY); otherwise free. A brief stores the
levels ("consistency") and the user's own words for every part the request mentions ("kept_words"). Briefs from before
version 15 read their kept parts as themed and the rest as free (levels)."""

import re

from ....options.dataset import CONSISTENCY_PARTS, TYPE_CONSISTENCY

# Words that ask for a part to look identical. A request locks a part only when its own words for that part say so: a
# live model locked a named character, an object and "feet visible", which the request only required, and every image
# came out the same.
_SAME = re.compile(r"\b(?:same|identical|exact(?:ly)?|unchanged|consistent(?:ly)?)\b", re.IGNORECASE)


def asks_same(words):
    """Whether the user's words for a part ask for it to be identical in every image."""
    return bool(_SAME.search(str(words or "")))

# The vocabulary categories whose per-image suggestions would vary a part: a locked part gets none (the action has its
# own deal of Actions & Poses entries).
PART_CATEGORIES = {"subject": ("Subjects",), "clothing": ("Clothing",), "expression": ("Expressions",),
                   "place": ("Spaces",), "objects": ("Objects & Props",), "camera": ("Camera & Composition",),
                   "light": ("Lighting",), "mood": ("Mood & Tone", "Effects & Atmosphere")}


def resolve(dataset_type, chosen=None, mentioned=(), locked=(), varied=()):
    """{part: level} for every part. chosen: the draft's {part: level}; mentioned: the parts whose words are really in
    the request; locked and varied: the parts the request asks to be identical or to differ (they count only when
    mentioned, so a part nobody wrote about is never locked by a guess)."""
    chosen, defaults = chosen or {}, TYPE_CONSISTENCY.get(dataset_type, {})
    result = {}
    for part in CONSISTENCY_PARTS:
        if part in chosen:
            result[part] = chosen[part]
        elif part in mentioned and part in varied:
            result[part] = "free"
        elif part in mentioned:
            result[part] = "locked" if part in locked or defaults.get(part) == "locked" else "themed"
        else:
            result[part] = defaults.get(part, "free")
    return result


def levels(brief):
    """A brief's level for every part; a brief from before version 15 keeps its kept parts themed and frees the rest."""
    if isinstance(brief.get("consistency"), dict):
        return {part: brief["consistency"].get(part, "free") for part in CONSISTENCY_PARTS}
    kept = set(brief.get("kept") or ())
    return {part: "themed" if part in kept else "free" for part in CONSISTENCY_PARTS}


def parts_at(brief, level):
    """The parts at one level, in CONSISTENCY_PARTS order."""
    return [part for part, value in levels(brief).items() if value == level]


def kept_words(brief):
    """{part: the user's words for it} for every part the request mentions ({} before version 15)."""
    return dict(brief.get("kept_words") or {})


def locked_categories(brief):
    """The vocabulary categories that deal no per-image suggestion, because the part they vary is locked."""
    return frozenset(category for part in parts_at(brief, "locked") for category in PART_CATEGORIES.get(part, ()))
