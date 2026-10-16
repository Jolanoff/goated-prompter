"""Dataset vocabulary integration: retrieval, Director preferences, composition and Visual Direction.

After Understanding is confirmed, the run's selected packs are searched with its brief and Director.
Core composes images and binds roles before any scene inference. Named entries are requirements;
ideas remain optional and unknown data is never treated as incompatibility. Composed images receive
checked facts in a lightweight finisher. Unsupported images retain the freeform concept, staging and
description path, with retrieval suggestions in the first two calls. Validated v10 intent supplies
grounded search hints and performer/target links; unusable intent retains v9 retrieval. Ratings follow
the brief's path: only nsfw_character allows adult entries. The user's requirements always win.

Pack selection (Phase 2): each run uses the packs its owner selected for it, plus the core and every pack those
require (select_packs, PackManager.resolve_selection), never the global enabled state. The selection is resolved and
recorded with each pack's version and content fingerprint when the run is confirmed, before any inference; retrieval
then reads exactly those packs (PackManager.registry_for) and stops the run, before the first concept, when one of
them changed since: there is no silent fallback to another version or to the global packs.

Visual Direction (vocabulary/visual.py): with visual settings, the same packs' visual directions are chosen per
image; while it is active, the brief's camera and light wording is masked out of content retrieval only.

Composition (vocabulary/composer.py, SPEC.md section 13): after retrieval, Core composes each image in code from the
same packs: the arrangement, interactions with their items, and the place, checked together with the resolver while
choosing, with each person's role assigned. What a composed image must show narrows its Visual Direction. An image no
entry fits is freeform (the concept, staging and description requests, with the inspiration block above).

The Director (preferences.py): its instructions are a retrieval source, and every sentence of them that states an
obligation and names entries makes those entries required in every image (composer.SceneContract); its structured
vocabulary block, when the preset has one, requires the entries it lists, adds the names it prefers to that source,
weights the ideas it prefers, drops the ones it avoids (never what the request names), orders the roles the composer
fills and steers Visual Direction. The target model's vocabulary block (target_models.target_vocabulary) adds its
requirements the same way. All of them take part in the same joint search as the user's requirements.

Comparison: "dataset_vocabulary": false in config.json turns retrieval off (default on). It is read
for each run, changes nothing else, and every scenes debug trace and result records the state.
"""

from dataclasses import replace

from ...vocabulary.packs import PackDrift, PackManager, VocabularyError
from ...vocabulary.retrieval import RATINGS, RetrievalConfig, RetrievalRequest, retrieve
from ...vocabulary import visual as visual_direction
from ...vocabulary.composer import Composer, SceneContract
from ...vocabulary.preferences import PREFER_WEIGHT, Preferences
from ....prompting.target_models import target_vocabulary
from .intent import search_hints

CONFIG_KEY = "dataset_vocabulary"
STEPS = ("concept", "staging")  # the Section 2 requests that receive the reference block
LIST_LIMIT = 200  # excluded/suppressed rows kept in a run's diagnostics; the full lists stay in the debug trace
ENTRY_FIELDS = ("id", "name", "pack", "category", "rating", "status", "source", "scopes")


def _selection_summary(selection):
    """The recorded selection without anything but ids, roles, origins, versions and fingerprints."""
    if selection is None:
        return None
    return {"enabled": selection["enabled"], "selected": list(selection["selected"]),
            "packs": [{key: item[key] for key in ("id", "role", "origin", "version", "fingerprint")} for item in selection["packs"]]}


def diagnostics(log):
    """What a run keeps (and the generation log exports) about its vocabulary: the pack selection with versions and
    fingerprints, the entries named and the ideas offered with ids, names, packs and categories, what each image was
    offered, and why entries were excluded or suppressed. Never an entry's description, notes or the block text, so a
    private pack's wording stays in the debug trace only."""
    out = {"enabled": log.get("enabled", False), "selection": _selection_summary(log.get("selection"))}
    for key in ("reason", "error", "allowed_ratings", "seed", "warnings", "stats", "provided", "provided_to", "visual",
                "composer"):
        if key in log:
            out[key] = log[key]
    if "entries" in log:
        out["entries"] = [{key: entry.get(key) for key in ENTRY_FIELDS} for entry in log["entries"]]
        out["ideas"] = [{key: entry.get(key) for key in ENTRY_FIELDS} for entry in log.get("inspiration", [])]
        out["images"] = [{"slot": scene["scene"], "entries": scene["entries"], "ideas": scene["ideas"]}
                         for scene in log.get("scenes", [])]
        for key in ("excluded", "suppressed"):
            rows = log.get(key, [])
            out[key] = [{field: row[field] for field in ("id", "reason", "because", "source") if field in row}
                        for row in rows[:LIST_LIMIT]]
            if len(rows) > LIST_LIMIT:
                out[f"{key}_total"] = len(rows)
        if log.get("intent"):
            out["intent"] = log["intent"]
    return out


def enabled(config):
    value = (config or {}).get(CONFIG_KEY, True)
    if type(value) is not bool:
        raise ValueError(f'config.json "{CONFIG_KEY}" must be true or false.')
    return value


def _nothing(numbers=()):
    return ""


def _without(log, visual=None):
    """No vocabulary for this run, with the reason logged and kept in its diagnostics."""
    plan = visual_direction.off("no vocabulary packs are read for this run", visual)
    log = {**log, "visual": plan.record(0)}
    return {"enabled": log["enabled"], "offer": _nothing, "block": "", "provided": [], "log": log,
            "diagnostics": diagnostics(log), "visual": plan, "composer": None, "per_image": False}


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


def vocabulary_reference(config, brief, *, director="", manager=None, selection=None, visual=None, preferences=None):
    """The vocabulary for this brief and what was logged about it.

    Returns {"enabled", "offer", "block", "provided", "log"}: offer(numbers) is the block for one request that
    writes those images (1-based, in order), "" when nothing is given; block is the block of image 1 alone;
    provided lists every id offered to any image; log is the full record for the debug trace; visual is the run's
    Visual Direction (vocabulary/visual.py Plan), from the same packs, when visual settings are given (None: off);
    composer is the run's Composer (compose(n): image n's composed scene, or why it is freeform or failed).
    preferences: the active Director's vocabulary block (preferences.py), or None.
    """
    if not enabled(config):
        return _without({"enabled": False, "reason": f'turned off in config.json ("{CONFIG_KEY}": false)'}, visual)
    if selection is not None and not selection["enabled"]:
        return _without({"enabled": False, "reason": "the run's pack selection uses no vocabulary", "selection": selection}, visual)
    try:
        # A recorded selection reads exactly its packs; without one (older callers) the enabled packs are read.
        registry = (manager or PackManager()).registry_for(selection) if selection is not None else (manager or PackManager()).registry()
    except PackDrift as drift:
        raise ValueError("The selected vocabulary packs changed since this run was confirmed; review and confirm again: "
                         + "; ".join(drift.problems)) from None
    except (VocabularyError, OSError) as error:
        problems = getattr(error, "problems", None) or [str(error)]
        return _without({"enabled": True, "error": f"vocabulary packs could not be loaded: {'; '.join(problems)}",
                         "selection": selection, "provided_to": []}, visual)
    # Ratings follow the path Section 2 writes for, so the vocabulary and the scene rules always agree.
    allowed = RATINGS if brief["path"] == "nsfw_character" else tuple(rating for rating in RATINGS if rating != "adult")
    try:
        prefs = Preferences(preferences, registry)
        preference_error = None
    except ValueError as error:  # a stored block is validated when saved; an unreadable one steers nothing
        prefs, preference_error = Preferences(None, registry), str(error)
    amount = brief["input"].get("amount")
    # The target model may add scene requirements of its own (prompting/target_models.py target_vocabulary): data, read
    # the way a Director's block is; it never decides the final prompt's format, which stays the target adapter's job.
    try:
        target = Preferences(target_vocabulary(brief.get("settings", {}).get("target", "")), registry)
    except ValueError:
        target = Preferences(None, registry)
    contract = SceneContract.build(registry, brief, prefs, director, target=target, allowed=allowed)
    images = range(1, (amount if type(amount) is int and amount > 0 else 1) + 1)
    # Visual Direction reads the same packs; what the brief says about camera and light is masked out of content
    # retrieval only while it is active, so "low camera angle" never finds a Camera prop. Off: the request is unchanged.
    plan = (visual_direction.plan(registry, brief, visual, allowed=allowed, preferences=prefs.visual) if visual is not None
            else visual_direction.off("Visual Direction was not requested for this run"))
    searched = visual_direction.masked_brief(brief, plan.mask) if plan.active else brief
    director_text = "\n".join(part for part in (director, prefs.text()) if part)
    request = replace(RetrievalRequest.from_brief(searched, director=director_text), hints=search_hints(brief))
    request = replace(request, must=(*request.must, *(row["text"] for row in contract.requirements if row["source"] == "user")),
                      director="\n".join([request.director, *(registry.resolved(ident)["name"]
                                           for row in contract.requirements if row["source"] == "director"
                                           for ident in row["entries"])]))
    found = retrieve(registry, request, RetrievalConfig(allowed_ratings=allowed))
    if prefs:
        found.steer(boost={entry.id: PREFER_WEIGHT for entry in found.inspiration if prefs.prefers(entry.id)},
                    drop={entry.id: "the Director avoids it" for entry in found.inspiration if prefs.avoids(entry.id)})
    # Core composes every image before anything is offered or recorded, so each image's Visual Direction already
    # knows what its scene must show.
    composer = Composer(registry, found, brief, preferences=prefs, plan=plan if plan.active else None, allowed=allowed,
                        contract=contract)
    composition = composer.summary()
    provided = list(dict.fromkeys(entry_id for number in images for entry_id in found.offer([number])[1]))
    block = found.offer([1])[0]

    def offer(numbers):
        return found.offer(list(numbers))[0]

    provided_to = ["composition"] if provided else []
    if provided and any(image["kind"] == "freeform" for image in composition["images"]):
        provided_to.extend(STEPS)
    log = {"enabled": True, "packs": sorted({registry.owner(entry_id) for entry_id in registry.ids()}), "selection": selection,
           "allowed_ratings": list(allowed), **found.to_dict(), "scenes": found.scenes(len(images)), "seed": found.seed,
           "provided": provided, "provided_to": provided_to, "block": block,
           "visual": plan.record(len(images)), "composer": composition}
    if preference_error:
        log["composer"]["director_error"] = preference_error
    return {"enabled": True, "offer": offer, "block": block, "provided": provided, "log": log, "diagnostics": diagnostics(log),
            "visual": plan, "composer": composer, "per_image": any(scene["ideas"] for scene in log["scenes"])}
