"""Measures how Places keeps the request's spatial relations (v2/scenes/places.py) on labelled requests
(tests/eval/cases/place_relations.json), with the built-in Spaces catalog, against the same briefs without their
relations (the earlier way). Two steps:

  python -m tests.eval.place_relations --capture --settings <quality settings file> [--cases <file>]
      runs Understanding once per request (one model call each, as in the app) and saves the briefs
  python -m tests.eval.place_relations [--cases <file>] [--embedding-model <gguf>] [--llama-server <exe>]
      deals 10 images per request from the saved briefs and reports, per request and in total:

  anchors     share of the labelled anchors Understanding kept as a relation (its anchor says the anchor's words)
  within      share of those whose within (the anchor holds the subject) is right
  kept        share of the dealt places that keep every relation (none in a group that breaks one: the inside of an
              anchor the subjects are outside of, or away from the one they are in)
  relevant    share of the dealt places in a group where the arrangement holds (cases that list some)
  groups      distinct groups among the dealt places; empty: requests dealt nothing
  ms          place search and deal time per request (the embedding index built beforehand)

The held-out cases (place_relations_heldout.json) were labelled before any run and never used to tune anything.
Briefs, reports and the embedding cache go under quality-artifacts/places-eval/.
"""

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.scenes import places
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval, selection
from goated_prompter.features.vocabulary.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases" / "place_relations.json"
OUT = ROOT / "quality-artifacts" / "places-eval"
IMAGES = 10


def capture(cases, settings, seed):
    """{request: brief} from Understanding run live on every request."""
    from goated_prompter.backends.llama_cpp_process import get_process_manager
    from goated_prompter.features.dataset.v2 import understanding
    from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
    from tests.quality.worker import _engine, _request
    config, profile = _engine(json.loads(Path(settings).read_text(encoding="utf-8")), ROOT)
    config["local_llama_cpp"] = {**config.get("local_llama_cpp", {}), "keep_model_loaded": True}
    briefs = {}
    try:
        for case in cases:
            data = validate_dataset_draft({**default_dataset_draft(), "subject": case["request"], "amount": 3,
                                           "nsfw": False, "seed": seed, "seed_mode": "fixed"}, generation=True)
            request = _request(profile, config, idea=data["subject"], mode="Custom", target_model=data["target"],
                               creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
                               director_preset="general_director")
            briefs[case["request"]] = understanding.understand(config, request, data, progress=lambda _: None)
            print(case["request"][:50], "->", briefs[case["request"]]["places"].get("relations"), flush=True)
    finally:
        get_process_manager().cleanup_all()
    return briefs


def measure(case, brief, groups, embeddings):
    owner = {entry: group["name"] for group in groups for entry in group["entries"]}
    began = time.perf_counter()
    found, _ = places.place_plan(brief, groups, embeddings)
    dealt = [owner[place] for place in selection.deal_spread(found, IMAGES, random.Random(1)).values()]
    seconds = time.perf_counter() - began
    kept = brief["places"].get("relations") or []
    said = lambda label, anchor: set(retrieval.content_words(label)) <= set(retrieval.content_words(anchor))
    matched = [(label, next((item for item in kept if said(label["anchor"], item["anchor"])), None))
               for label in case["relations"]]
    found_anchors = [(label, item) for label, item in matched if item]
    return {"request": case["request"], "dealt": dealt,
            "anchors": len(found_anchors) / len(matched) if matched else None,
            "within": (sum(label["within"] == item["within"] for label, item in found_anchors) / len(found_anchors)
                       if found_anchors else None),
            "kept": sum(name not in case["breaks"] for name in dealt) / len(dealt) if dealt else None,
            "relevant": (sum(name in case["acceptable"] for name in dealt) / len(dealt)
                         if dealt and case["acceptable"] else None),
            "groups": len(set(dealt)), "empty": not dealt, "ms": round(1000 * seconds, 1)}


def total(rows):
    mean = lambda key: round(statistics.mean(row[key] for row in rows if row[key] is not None), 3) if any(
        row[key] is not None for row in rows) else None
    return {"anchors": mean("anchors"), "within": mean("within"), "kept": mean("kept"), "relevant": mean("relevant"),
            "groups": round(statistics.mean(row["groups"] for row in rows), 2), "empty": sum(row["empty"] for row in rows),
            "ms": round(statistics.mean(row["ms"] for row in rows), 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--settings", default=str(ROOT / "quality.json"))
    parser.add_argument("--seed", type=int, default=173)
    parser.add_argument("--embedding-model", default="G:/AI/models/embedding-models/bge-small-en-v1.5-q8_0.gguf")
    parser.add_argument("--llama-server", default="C:/Tools/llama.cpp/llama-server.exe")
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    saved = OUT / f"briefs-{Path(args.cases).stem}.json"
    OUT.mkdir(parents=True, exist_ok=True)
    if args.capture:
        saved.write_text(json.dumps(capture(cases, args.settings, args.seed), indent=1), encoding="utf-8")
        print("saved", saved)
        return
    briefs = json.loads(saved.read_text(encoding="utf-8"))
    groups = retrieval.groups_of(load_catalog(user_root=False), places.SPACES, {"packs": []})
    embeddings = None if args.no_embeddings else vectors_module.embeddings_for(
        {"local_llama_cpp": {"llama_server": args.llama_server, "embedding_model_path": args.embedding_model}},
        cache_path=OUT / f"embeddings-cache-{Path(args.embedding_model).stem}.json")
    report = {"new": [], "old": []}
    try:
        if embeddings is not None:
            embeddings.documents([retrieval.group_text(group) for group in groups]
                                 + [entry for group in groups for entry in group["entries"]])
        for case in cases:
            brief = briefs[case["request"]]
            new = measure(case, brief, groups, embeddings)
            old = measure(case, {**brief, "places": {**brief["places"], "relations": []}}, groups, embeddings)
            report["new"].append(new)
            report["old"].append(old)
            show = lambda row, key: "-" if row[key] is None else f"{row[key]:.2f}" if isinstance(row[key], float) else str(row[key])
            print(f'{case["request"][:46]:46} ' + " ".join(f"{key[:5]} {show(old, key)}>{show(new, key)}"
                                                          for key in ("anchors", "within", "kept", "relevant", "groups"))
                  + f' | {sorted(set(new["dealt"]))}', flush=True)
    finally:
        if embeddings is not None:
            embeddings.close()
    summary = {side: total(rows) for side, rows in report.items()}
    print(json.dumps(summary, indent=1))
    (OUT / f"relations-report-{Path(args.cases).stem}.json").write_text(
        json.dumps({**report, "summary": summary}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
