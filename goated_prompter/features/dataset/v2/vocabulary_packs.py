"""Section 2 input — installed vocabulary packs as optional knowledge for the Director (Phase 5).

After Understanding is confirmed and before the first scene concept, the enabled packs (the core, the
enabled official packs in vocabulary/packs and the enabled installed packs) are searched once with the
confirmed brief: its request, summary, fixed, randomized, must, avoid, rules and characters, the
creativity and style settings and the active Director's instructions (vocabulary/schemas/SPEC.md
section 10). Each concept and staging request of Section 2 gets the result as a field of the brief
data: the entries the request names, for every image, and the ideas for the images that request
writes, from the categories the brief opens, rotated across the images by the brief's seed. It is
knowledge, not a template. Validated v10 intent contributes grounded wording and optional semantic
hints; these may find optional ideas but never name a fixed choice. Unusable intent keeps v9 retrieval:

- optional: entries the Director may use, adapt or ignore; the scene is never limited to them;
- the request, fixed, must, avoid and the user's rules outrank it (the Section 2 prompts already
  say so, retrieval drops what the request rules out and offers no idea against what it fixes);
- confirmed conflicts with this cast are never offered; unknown entries are offered with that status;
- ratings follow the brief's path: only nsfw_character allows adult-rated entries;
- it never assigns roles: no character label or slot binding reaches the Director.

With nothing relevant, the switch off or a pack that cannot be loaded, nothing is added: the
requests are byte-for-byte those of a run without vocabulary.

Pack selection (Phase 2): each run uses the packs its owner selected for it, plus the core and every pack those
require (select_packs, PackManager.resolve_selection), never the global enabled state. The selection is resolved and
recorded with each pack's version and content fingerprint when the run is confirmed, before any inference; retrieval
then reads exactly those packs (PackManager.registry_for) and stops the run, before the first concept, when one of
them changed since: there is no silent fallback to another version or to the global packs.

Comparison: "dataset_vocabulary": false in config.json turns retrieval off (default on). It is read
for each run, changes nothing else, and every scenes debug trace and result records the state.
"""

from dataclasses import replace

from ...vocabulary.packs import PackDrift, PackManager, VocabularyError
from ...vocabulary.retrieval import RATINGS, RetrievalConfig, RetrievalRequest, retrieve
from .intent import search_hints

CONFIG_KEY = "dataset_vocabulary"
STEPS = ("concept", "staging")  # the Section 2 requests that receive the reference block


def enabled(config):
    value = (config or {}).get(CONFIG_KEY, True)
    if type(value) is not bool:
        raise ValueError(f'config.json "{CONFIG_KEY}" must be true or false.')
    return value


def _nothing(numbers=()):
    return ""


def select_packs(config, selected, *, manager=None):
    """The pack selection to record for a new run: the user's selected pack ids resolved with the core and their
    dependencies (vocabulary off in config.json: an empty, disabled selection). Raises ValueError naming every
    unknown, invalid or dependency-blocked pack."""
    if not isinstance(selected, list) or any(not isinstance(pack_id, str) for pack_id in selected):
        raise ValueError("Select the Dataset vocabulary packs as a list of pack ids.")
    try:
        return (manager or PackManager()).resolve_selection(selected, enabled=enabled(config))
    except VocabularyError as error:
        raise ValueError("The selected vocabulary packs cannot be used: " + "; ".join(error.problems)) from None


def pack_status(selection, *, manager=None):
    """How the packs on disk compare with a recorded selection: {exact, drift, disabled_globally}. Read-only."""
    if not selection["enabled"]:
        return {"exact": True, "drift": [], "disabled_globally": []}
    return (manager or PackManager()).selection_status(selection)


def vocabulary_reference(config, brief, *, director="", manager=None, selection=None):
    """The vocabulary for this brief and what was logged about it.

    Returns {"enabled", "offer", "block", "provided", "log"}: offer(numbers) is the block for one request that
    writes those images (1-based, in order), "" when nothing is given; block is the block of image 1 alone;
    provided lists every id offered to any image; log is the full record for the debug trace.
    """
    if not enabled(config):
        return {"enabled": False, "offer": _nothing, "block": "", "provided": [],
                "log": {"enabled": False, "reason": f'turned off in config.json ("{CONFIG_KEY}": false)'}}
    if selection is not None and not selection["enabled"]:
        return {"enabled": False, "offer": _nothing, "block": "", "provided": [],
                "log": {"enabled": False, "reason": "the run's pack selection uses no vocabulary", "packs": selection}}
    try:
        # A recorded selection reads exactly its packs; without one (older callers) the enabled packs are read.
        registry = (manager or PackManager()).registry_for(selection) if selection is not None else (manager or PackManager()).registry()
    except PackDrift as drift:
        raise ValueError("The selected vocabulary packs changed since this run was confirmed; review and confirm again: "
                         + "; ".join(drift.problems)) from None
    except (VocabularyError, OSError) as error:
        problems = getattr(error, "problems", None) or [str(error)]
        return {"enabled": True, "offer": _nothing, "block": "", "provided": [],
                "log": {"enabled": True, "error": f"vocabulary packs could not be loaded: {'; '.join(problems)}",
                        "provided_to": []}}
    # Ratings follow the path Section 2 writes for, so the vocabulary and the scene rules always agree.
    allowed = RATINGS if brief["path"] == "nsfw_character" else tuple(rating for rating in RATINGS if rating != "adult")
    request = replace(RetrievalRequest.from_brief(brief, director=director), hints=search_hints(brief))
    found = retrieve(registry, request, RetrievalConfig(allowed_ratings=allowed))
    amount = brief["input"].get("amount")
    images = range(1, (amount if type(amount) is int and amount > 0 else 1) + 1)
    provided = list(dict.fromkeys(entry_id for number in images for entry_id in found.offer([number])[1]))
    block = found.offer([1])[0]

    def offer(numbers):
        return found.offer(list(numbers))[0]

    log = {"enabled": True, "packs": sorted({registry.owner(entry_id) for entry_id in registry.ids()}), "selection": selection,
           "allowed_ratings": list(allowed), **found.to_dict(), "scenes": found.scenes(len(images)), "seed": found.seed,
           "provided": provided, "provided_to": list(STEPS) if provided else [], "block": block}
    return {"enabled": True, "offer": offer, "block": block, "provided": provided, "log": log}
