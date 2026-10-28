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

These objects are optional and never add a second one of what the image already has: when the image's act, pose or
place already names an object of a group (a brush in a painter's hand, a bench someone sits on), that group offers
only that object, described more closely (the_same_things: a fine sable brush, a weathered park bench), never another
of its kind next to it (a second brush, another seat). A group's objects can be far apart (tools of one trade and of
another world), so only its entries at least as close to the image as the group's average are dealt (closest).
"""

from ....vocabulary.retrieval import content_words, entry_name, fit_scores, relevance, word_stem, zscores
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


def the_same_things(groups, text):
    """Each group with only the objects the image's text already names when it names one of them: an object is named
    by its own noun (the last word of its name, retrieval.entry_name), in any form. A group whose objects the text
    names none of is unchanged."""
    said = {word_stem(word) for word in content_words(text)}
    noun = lambda entry: (words := content_words(entry_name(entry))) and word_stem(words[-1])
    kept = []
    for group in groups:
        named = [entry for entry in group["entries"] if noun(entry) in said]
        kept.append({**group, "entries": named} if named else group)
    return kept


CLOSEST_GROUP = 3  # a group with at least this many objects keeps only those at least as close as its average


def closest(groups, text, embeddings=None):
    """Each group with only its objects at least as close to the image's text as the group's average (unchanged
    without embeddings, or for a group of fewer than CLOSEST_GROUP objects)."""
    if embeddings is None:
        return list(groups)
    kept = []
    for group in groups:
        entries = group["entries"]
        if len(entries) >= CLOSEST_GROUP:
            entries = [entry for entry, score in zip(entries, zscores(fit_scores(text, entries, embeddings)))
                       if score >= 0] or entries
        kept.append({**group, "entries": entries})
    return kept


def with_needed(scene, needed):
    """The scene with every needed thing (the request's own, in the vocabulary's words) it leaves out added to its
    extras: a thing is there when its own noun (entry_name's last word), in any form, is anywhere in the scene. Code
    adds it rather than asking the image again (a live writer kept every needed thing; this keeps it so)."""
    said = {word_stem(word) for word in content_words(" ".join(str(scene.get(key) or "") for key in
                                                              ("actions", "position", "space", "camera", "extras")))}
    noun = lambda entry: (words := content_words(entry_name(entry))) and word_stem(words[-1])
    missing = [entry_name(entry) for entry in needed if noun(entry) and noun(entry) not in said]
    if not missing:
        return scene
    return {**scene, "extras": "; ".join([str(scene.get("extras") or "").rstrip("; ."), *missing]).strip("; ")}


def deal_props(groups, total, rng, partners=None, embeddings=None):
    """{slot: entry}: each image's object from the groups that suit its pose and place (partners: {slot: text}), the
    images that share a pose and place spread over their groups in a seeded order; with no partners at all, every
    group for every image. An image nothing suits gets none."""
    images = {}
    for number in range(1, total + 1):
        images.setdefault((partners or {}).get(number), []).append(number)
    dealt = {}
    for text, numbers in images.items():
        pool = (closest(the_same_things(suiting(groups, text, embeddings), text), text, embeddings) if text
                else ([] if partners else list(groups)))
        rng.shuffle(pool)
        hand = deal_spread(pool, len(numbers), rng)
        dealt.update({number: hand[index] for index, number in enumerate(numbers, 1) if index in hand})
    return dealt
