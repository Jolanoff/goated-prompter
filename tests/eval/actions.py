"""Measures Actions & Poses and Objects & Props retrieval and selection (v2/scenes/actions.py, props.py) on labelled
requests (tests/eval/cases/actions.json), with every built-in pose and object pack selected, against the earlier way:
every entry for at most the cast's number of people dealt in a shuffle, and objects dealt in a shuffle (without the
model fitting call it had then). Per request and in total:

  action precision  share of the images whose pose shows the requested act (cases that name one)
  cast fit          share of the images whose pose is made for the cast's number of people
  ruled out         share of the images whose pose says what the request rules out
  distinct          share of the images with a pose no earlier image has; kinds: distinct kinds of pose (groups)
  object precision  share of the images whose object suits the request (cases that judge it)
  object fit        mean closeness in meaning of each image's object to its pose and place
  ms                retrieval and selection time per request (the embedding index built beforehand)

  python -m tests.eval.actions --embedding-model <gguf> [--llama-server <exe>] [--images 10] [--seed 7]
"""

import argparse
import json
import random
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.scenes import actions, props
from goated_prompter.features.dataset.v2.scenes.entries import offered_groups
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval
from goated_prompter.features.vocabulary.catalog import load_catalog, selected_vocabulary
from goated_prompter.features.vocabulary.selection import deal_spread

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases" / "actions.json"
OUT = ROOT / "quality-artifacts" / "actions-eval"


def brief(case):
    return {"characters": [{"label": f"person {n}", "count": 1} for n in range(1, case["cast"] + 1)],
            "kept_words": {key: case[key] for key in ("action", "objects") if case.get(key)},
            "avoid": case.get("avoid", [])}


def new_way(case, poses, objects, total, seed, embeddings):
    rng = random.Random(seed)
    found = actions.action_plan(brief(case), poses, embeddings)
    dealt = actions.deal_actions(found, total, rng) if found else {}
    partners = {n: " ".join(filter(None, (dealt.get(n), case.get("place")))) for n in range(1, total + 1)}
    partners = {n: text for n, text in partners.items() if text}
    things = props.deal_props(objects, total, rng, partners, embeddings)
    return dealt, things, partners


def old_way(case, poses, objects, total, seed):
    rng = random.Random(seed)
    pool = [entry for group in poses for entry in group["entries"] if group["people"].get(entry, 0) <= case["cast"]]
    deck, dealt = [], {}
    for number in range(1, total + 1):
        if not deck:
            deck = list(pool)
            rng.shuffle(deck)
        dealt[number] = deck.pop()
    things = deal_spread([{"name": "all", "entries": [e for g in objects for e in g["entries"]]}], total, rng)
    partners = {n: " ".join(filter(None, (dealt.get(n), case.get("place")))) for n in range(1, total + 1)}
    return dealt, things, partners


def measure(case, dealt, things, partners, poses, objects, embeddings):
    kind = {entry: group["name"] for group in poses for entry in group["entries"]}
    people = {entry: count for group in poses for entry, count in group["people"].items()}
    thing_kind = {entry: group["name"] for group in objects for entry in group["entries"]}
    images = list(dealt.values())
    best = max((count for count in people.values() if count <= case["cast"]), default=None)
    row = {"images": len(images)}
    if "actions" in case:
        row["action_precision"] = (sum(kind[e] in case["actions"] for e in images) / len(images) if images
                                   else (1.0 if not case["actions"] else 0.0))
    row["cast_fit"] = sum(people.get(e) == best for e in images) / len(images) if images else None
    ruled = [{retrieval.word_stem(w) for w in retrieval.content_words(p)} for p in case.get("avoid", [])]
    row["ruled_out"] = (sum(any(r <= {retrieval.word_stem(w) for w in retrieval.content_words(e)} for r in ruled)
                            for e in images) / len(images)) if images and ruled else 0.0
    row["distinct"] = len(set(images)) / len(images) if images else None
    row["kinds"] = len({kind[e] for e in images}) if images else None
    if "objects" in case:
        row["object_precision"] = (sum(thing_kind[t] in case["objects"] for t in things.values()) / len(things)
                                   if things else None)
    row["objects_given"] = len(things) / len(images or dealt or things or [0]) if images else len(things) / 10
    fits = [retrieval.fit_scores(partners[n], [things[n]], embeddings)[0] for n in things if partners.get(n)]
    row["object_fit"] = sum(fits) / len(fits) if fits else None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--llama-server", default="C:/Tools/llama.cpp/llama-server.exe")
    parser.add_argument("--images", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    catalog = load_catalog(user_root=False)
    packs = [pack["id"] for pack in catalog["packs"] if pack["category"] in ("Actions & Poses", "Objects & Props")
             and not pack.get("always")]
    selection = {"packs": packs}
    selected = selected_vocabulary(catalog, selection)
    poses = offered_groups(catalog, "Actions & Poses", selection, selected)
    objects = offered_groups(catalog, "Objects & Props", selection, selected)
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    OUT.mkdir(parents=True, exist_ok=True)
    embeddings = vectors_module.embeddings_for(
        {"local_llama_cpp": {"llama_server": args.llama_server, "embedding_model_path": args.embedding_model}},
        cache_path=OUT / f"embeddings-cache-{Path(args.embedding_model).stem}.json")
    report = {"new": [], "old": []}
    try:
        embeddings.documents([retrieval.group_text(g) for g in poses + objects]
                             + [e for g in poses + objects for e in g["entries"]])
        for case in cases:
            started = time.perf_counter()
            dealt, things, partners = new_way(case, poses, objects, args.images, args.seed, embeddings)
            ms = (time.perf_counter() - started) * 1000
            new = {"request": case["request"], **measure(case, dealt, things, partners, poses, objects, embeddings),
                   "ms": round(ms, 1), "dealt": [[dealt.get(n), things.get(n)] for n in range(1, args.images + 1)]}
            dealt, things, partners = old_way(case, poses, objects, args.images, args.seed)
            old = {"request": case["request"], **measure(case, dealt, things, partners, poses, objects, embeddings)}
            report["new"].append(new)
            report["old"].append(old)
            show = lambda row, key: "-" if row.get(key) is None else f"{row[key]:.2f}"
            print(f'{case["request"][:38]:38} '
                  + " ".join(f"{key[:6]} {show(old, key)}>{show(new, key)}" for key in
                             ("action_precision", "cast_fit", "distinct", "kinds", "object_precision", "objects_given", "object_fit"))
                  + f' ms {new["ms"]}', flush=True)
    finally:
        embeddings.close()
    summary = {}
    for side in ("old", "new"):
        rows = report[side]
        summary[side] = {key: round(sum(r[key] for r in rows if r.get(key) is not None)
                                    / max(1, sum(r.get(key) is not None for r in rows)), 3)
                         for key in ("action_precision", "cast_fit", "ruled_out", "distinct", "kinds",
                                     "object_precision", "objects_given", "object_fit")}
    summary["new"]["ms"] = round(sum(r["ms"] for r in report["new"]) / len(report["new"]), 1)
    print(json.dumps(summary, indent=1))
    (OUT / "report.json").write_text(json.dumps({**report, "summary": summary}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
