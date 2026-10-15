"""Read-only catalogue projections; resolution and retrieval stay with their existing owners."""

from ...options.vocabulary import CATALOGUE_SORTS
from .packs import RATINGS, VocabularyError, entry_references
from .retrieval import RetrievalRequest, retrieve


SAMPLE_KEYS = {"request", "nsfw", "characters", "randomized", "avoid", "seed", "scenes"}
MAX_SEED, MAX_SCENES = 2**31 - 1, 20


def inspection_sample(payload):
    if not isinstance(payload, dict) or set(payload) - SAMPLE_KEYS:
        raise ValueError("Expected a sample request, NSFW rating filter and optional character descriptions, "
                         "what may vary, what to avoid, a seed and a scene count.")
    text, nsfw, characters = payload.get("request", ""), payload.get("nsfw", False), payload.get("characters", [])
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or type(nsfw) is not bool:
        raise ValueError("Enter a sample request of 1–4000 characters and a boolean NSFW rating filter.")
    if not isinstance(characters, list) or len(characters) > 16 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 512 for item in characters):
        raise ValueError("Use up to 16 character descriptions of 1–512 characters each.")
    randomized, avoid = payload.get("randomized", ""), payload.get("avoid", [])
    seed, scenes = payload.get("seed", 0), payload.get("scenes", 5)
    if not isinstance(randomized, str) or len(randomized) > 1200:
        raise ValueError("What may vary must be text of at most 1200 characters.")
    if not isinstance(avoid, list) or len(avoid) > 20 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 200 for item in avoid):
        raise ValueError("Use up to 20 avoid phrases of 1–200 characters each.")
    if type(seed) is not int or not 0 <= seed <= MAX_SEED or type(scenes) is not int or not 1 <= scenes <= MAX_SCENES:
        raise ValueError(f"The seed must be a whole number from 0 to {MAX_SEED} and the scene count 1–{MAX_SCENES}.")
    return {"request": text, "nsfw": nsfw, "characters": characters, "randomized": randomized, "avoid": avoid,
            "seed": seed, "scenes": scenes}


def catalogue(manager, pack_id, *, origin=None, query="", category="", rating="", sort="name"):
    view = manager.inspect_pack(pack_id, origin)
    pack = view["loaded"].get(pack_id)
    registry = view["registry"]
    categories = {item["id"]: item for owner in view["loaded"].values() for item in owner.manifest.get("categories", [])}
    entries = []
    for _file, raw in pack.entries if pack else []:
        entry = registry.resolved(raw["id"]) if registry is not None else raw
        entries.append({"id": raw["id"], "name": raw["name"], "category": raw["category"],
                        "description": entry.get("description", ""), "aliases": entry.get("aliases", []),
                        "tags": entry.get("tags", []), "rating": entry.get("rating", pack.manifest["rating"])})
    counts = {key: sum(entry["category"] == key for entry in entries) for key in sorted({entry["category"] for entry in entries})}
    needle = query.strip().casefold()
    filtered = [entry for entry in entries if (not category or entry["category"] == category)
                and (not rating or entry["rating"] == rating)
                and (not needle or any(needle in text.casefold() for text in
                     [entry["id"], entry["name"], *entry["aliases"], *entry["tags"]]))]
    filtered.sort(key=lambda entry: (entry[sort].casefold(), entry["id"]))
    return {"pack": view["pack"], "entries": filtered, "total": len(entries), "matched": len(filtered),
            "categories": [{"id": key, "name": categories.get(key, {}).get("name", key), "count": count}
                           for key, count in counts.items()], "ratings": list(RATINGS), "sorts": CATALOGUE_SORTS,
            "problems": view["problems"]}


def entry_detail(manager, entry_id, *, origin=None):
    pack_id, separator, _name = entry_id.partition(":")
    if not separator:
        raise VocabularyError("An entry id must include its pack prefix.")
    view = manager.inspect_pack(pack_id, origin)
    owner = view["loaded"].get(pack_id)
    raw = next((entry for _file, entry in owner.entries if entry["id"] == entry_id), None) if owner else None
    if raw is None:
        raise VocabularyError(f"{entry_id}: entry is missing or its pack could not be validated.")
    registry = view["registry"]
    resolved = registry.resolved(entry_id) if registry is not None else None
    known = {entry["id"]: (entry, pack) for pack in view["loaded"].values() for _file, entry in pack.entries}
    direct = {(kind, ident) for kind, ids in entry_references(raw).items() for ident in ids}
    all_refs = direct | {(kind, ident) for kind, ids in entry_references(resolved or raw).items() for ident in ids}
    references = []
    for kind, ident in sorted(all_refs):
        target, pack = known.get(ident, (None, None))
        references.append({"id": ident, "kind": kind, "declared": (kind, ident) in direct,
                           "exists": target is not None, "name": target["name"] if target else ident,
                           "pack": pack.id if pack else ident.split(":", 1)[0],
                           "origin": pack.summary()["origin"] if pack else None})
    return {"pack": view["pack"], "declared": raw, "resolved": resolved,
            "references": references, "problems": view["problems"]}


def inspect_retrieval(manager, request, **sample):
    # No Understanding, model call or scene generation: only the existing deterministic engine.
    return inspect_registry(manager.registry(), request, **sample)


def inspect_registry(registry, request, *, nsfw=False, characters=(), randomized="", avoid=(), seed=0, scenes=5):
    """The same inspection projection for enabled packs and isolated draft registries.

    The same retrieve() the Dataset Builder runs on a confirmed brief: the sample request stands for its request,
    randomized and avoid for the brief's, and scenes previews the ideas each image would be offered."""
    cast = tuple({"label": f"Character {number}", "gender": "custom", "custom": text}
                 for number, text in enumerate(characters, 1))
    found = retrieve(registry, RetrievalRequest(request=request, nsfw=nsfw, characters=cast, randomized=randomized,
                                                avoid=tuple(avoid), seed=seed))
    result = found.to_dict()
    for kind in ("excluded", "suppressed"):
        result[kind] = [{**item, "pack": registry.owner(item["id"])} for item in result[kind]]
    return {"nsfw": nsfw, **result, "seed": seed, "scenes": found.scenes(scenes)}
