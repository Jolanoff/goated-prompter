"""Section 2 input — installed vocabulary packs as optional knowledge for the Director (Phase 5).

After Understanding is confirmed and before the first scene concept, the enabled packs (the core, the
enabled official packs in vocabulary/packs and the enabled installed packs) are searched once with the
confirmed brief: its request, summary, fixed, randomized, must, avoid, rules and characters, the
creativity and style settings and the active Director's instructions (vocabulary/schemas/SPEC.md
section 10). Each concept and staging request of Section 2 gets the result as a field of the brief
data: the entries the request names, for every image, and the ideas for the images that request
writes, from the categories the brief opens, rotated across the images by the brief's seed. It is
knowledge, not a template:

- optional: entries the Director may use, adapt or ignore; the scene is never limited to them;
- the request, fixed, must, avoid and the user's rules outrank it (the Section 2 prompts already
  say so, retrieval drops what the request rules out and offers no idea against what it fixes);
- confirmed conflicts with this cast are never offered; unknown entries are offered with that status;
- ratings follow the brief's path: only nsfw_character allows adult-rated entries;
- it never assigns roles: no character label or slot binding reaches the Director.

With nothing relevant, the switch off or a pack that cannot be loaded, nothing is added: the
requests are byte-for-byte those of a run without vocabulary.

Comparison: "dataset_vocabulary": false in config.json turns retrieval off (default on). It is read
for each run, changes nothing else, and every scenes debug trace and result records the state.
"""

from ...vocabulary.packs import PackManager, VocabularyError
from ...vocabulary.retrieval import RATINGS, RetrievalConfig, RetrievalRequest, retrieve

CONFIG_KEY = "dataset_vocabulary"
STEPS = ("concept", "staging")  # the Section 2 requests that receive the reference block


def enabled(config):
    value = (config or {}).get(CONFIG_KEY, True)
    if type(value) is not bool:
        raise ValueError(f'config.json "{CONFIG_KEY}" must be true or false.')
    return value


def _nothing(numbers=()):
    return ""


def vocabulary_reference(config, brief, *, director="", manager=None):
    """The vocabulary for this brief and what was logged about it.

    Returns {"enabled", "offer", "block", "provided", "log"}: offer(numbers) is the block for one request that
    writes those images (1-based, in order), "" when nothing is given; block is the block of image 1 alone;
    provided lists every id offered to any image; log is the full record for the debug trace.
    """
    if not enabled(config):
        return {"enabled": False, "offer": _nothing, "block": "", "provided": [],
                "log": {"enabled": False, "reason": f'turned off in config.json ("{CONFIG_KEY}": false)'}}
    try:
        registry = (manager or PackManager()).registry()
    except (VocabularyError, OSError) as error:
        problems = getattr(error, "problems", None) or [str(error)]
        return {"enabled": True, "offer": _nothing, "block": "", "provided": [],
                "log": {"enabled": True, "error": f"vocabulary packs could not be loaded: {'; '.join(problems)}",
                        "provided_to": []}}
    # Ratings follow the path Section 2 writes for, so the vocabulary and the scene rules always agree.
    allowed = RATINGS if brief["path"] == "nsfw_character" else tuple(rating for rating in RATINGS if rating != "adult")
    found = retrieve(registry, RetrievalRequest.from_brief(brief, director=director), RetrievalConfig(allowed_ratings=allowed))
    amount = brief["input"].get("amount")
    images = range(1, (amount if type(amount) is int and amount > 0 else 1) + 1)
    provided = list(dict.fromkeys(entry_id for number in images for entry_id in found.offer([number])[1]))
    block = found.offer([1])[0]

    def offer(numbers):
        return found.offer(list(numbers))[0]

    log = {"enabled": True, "packs": sorted({registry.owner(entry_id) for entry_id in registry.ids()}),
           "allowed_ratings": list(allowed), **found.to_dict(), "scenes": found.scenes(len(images)), "seed": found.seed,
           "provided": provided, "provided_to": list(STEPS) if provided else [], "block": block}
    return {"enabled": True, "offer": offer, "block": block, "provided": provided, "log": log}
