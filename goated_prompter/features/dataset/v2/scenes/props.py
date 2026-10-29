"""Objects & Props: the objects of every image, dealt by the Objects & Props policy (policies.py) with the shared
vocabulary engine (vocabulary/retrieval.py, vocabulary/selection.py). No model call chooses them.

The request comes first: the things it keeps are needed in every image, in the vocabulary's words (entries.deal_hands
with the kept objects). Otherwise a selected Objects & Props pack is the user's instruction to use it: all the
selected packs' entries are one pool, and every image needs one of them, dealt in a seeded spread without repeats
until every entry has been dealt; the writer places or uses it without changing the act (texts.PLACED_RULE). Without
a selected pack, the built-in packs only give the things the request itself asks for, by their whole name, as needed
in every image (entries.named_things, entries.deal_named): never another object, and a thing no built-in entry names
keeps the request's own words.
"""

from ....vocabulary.retrieval import content_words, entry_name, word_stem

OBJECTS = "Objects & Props"


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
