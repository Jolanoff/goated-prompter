"""Actions & Poses: the act and arrangement each image is built on, from the user's selected Actions & Poses packs,
found by the shared vocabulary engine (vocabulary/retrieval.py) and dealt by its selection (vocabulary/selection.py).
No model call chooses them.

An entry is a whole interaction with its people as letters (A, B, C), kept as written: the act and the physical
arrangement go together. action_plan keeps the entries made for the cast's number of people (retrieval.for_cast: a
pair gets entries for two, a group entries for a group; an entry for fewer people only when the packs have none for
the cast), without those that say what the request rules out (retrieval.without_said). When the request keeps an
action ("dancing close", "one riding the other"), only the entries that show it stay (retrieval.match: a group's
trigger words, then the entries that say the action's own words, then meaning); when none does, none is dealt and the
writer builds the scene from the request, which is never replaced by an unrelated entry. When the request leaves the
action open, every fitting entry may be dealt. deal_actions spreads the set over the groups (selection.deal_spread),
so the images get different kinds of interaction; a locked action is one entry for every image. Places and props are
paired with the dealt entries afterwards (places.py, props.py), so each image is one coherent scene.

A live run judged the fit with a separate model call; the request's own action words and the cast now decide it.
"""

from ....vocabulary.retrieval import for_cast, match, without_said
from ....vocabulary.selection import deal_spread
from ..consistency import kept_words
from .entries import cast_size


def action_plan(brief, groups, embeddings=None):
    """The Actions & Poses groups the images may be dealt, each with only its fitting entries; [] when none fits (see
    the module docstring)."""
    pool = without_said(for_cast(groups, cast_size(brief)), brief.get("avoid") or ())
    words = kept_words(brief).get("action", "")
    return match(pool, words, embeddings, entry_words=True) if words else pool


def deal_actions(groups, total, rng, locked=False):
    """{slot: entry}: the set spread over the groups in a seeded order; one entry for every image when locked."""
    order = list(groups)
    rng.shuffle(order)
    return deal_spread(order, total, rng, locked)
