"""Objects & Props: the object suggested to each image, from the user's selected Objects & Props packs, found by the
shared vocabulary engine (vocabulary/retrieval.py) and dealt by its selection (vocabulary/selection.py). No model call
chooses them, and no action and object pair is listed anywhere: they are combined image by image.

Objects stay separate from Actions & Poses and stay suggestions: the writer uses the one that fits the image, or none,
and never adds a subject or object only to use one. When the request names an object ("a lantern"), every image is
suggested the entries that are it, as for every other category (entries.deal_hands, retrieval.said_entries).
Otherwise each image's object comes from the groups that suit its own dealt pose and place: clearly closer to them in
meaning than the other groups (suiting, SUIT_Z), so a game board goes with a pair seated at a table and a sword with
a sparring pair, and an image that nothing suits is suggested nothing. A group is judged by its name and words, which
say what its objects are for; a single object's name compared with a pose matched on shared words ("handle", "box")
and gave a cooking image a mace. deal_props spreads each image's objects over its suiting groups
(selection.deal_spread), so images with the same pose get different objects.
"""

from ....vocabulary.retrieval import relevance, zscores
from ....vocabulary.selection import deal_spread

OBJECTS = "Objects & Props"
# A group this many deviations closer to an image's pose and place than the other groups suits it: poses that use
# an object stood out at 2.9 to 3.7 (a book, a pan, a game board, swords), poses that use none at most 2.5.
SUIT_Z = 2.5


def suiting(groups, text, embeddings=None):
    """The groups that suit one image's pose and place (text): closer to it in meaning than the other groups by SUIT_Z
    (retrieval.relevance); [] when none stands out. Every group when that cannot be judged: without embeddings, or
    with too few groups for one to stand out that far."""
    if embeddings is None or len(groups) - 1 < SUIT_Z ** 2:
        return list(groups)
    return [group for group, score in zip(groups, zscores(relevance(groups, text, embeddings))) if score >= SUIT_Z]


def deal_props(groups, total, rng, partners=None, embeddings=None):
    """{slot: entry}: each image's object from the groups that suit its pose and place (partners: {slot: text}), the
    images that share a pose and place spread over their groups in a seeded order; with no partners at all, every
    group for every image. An image nothing suits gets none."""
    images = {}
    for number in range(1, total + 1):
        images.setdefault((partners or {}).get(number), []).append(number)
    dealt = {}
    for text, numbers in images.items():
        pool = suiting(groups, text, embeddings) if text else ([] if partners else list(groups))
        rng.shuffle(pool)
        hand = deal_spread(pool, len(numbers), rng)
        dealt.update({number: hand[index] for index, number in enumerate(numbers, 1) if index in hand})
    return dealt
