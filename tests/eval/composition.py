"""Measures composing Actions & Poses entries for requests with several separate acts (v2/scenes/actions.py:
act_plans, deal_assignments, suited_to_place) on labelled requests (tests/eval/cases/composition.json), with every
built-in Actions & Poses pack and the built-in places, against the earlier way (several acts: no entry at all).
Per request and in total:

  acts kept     share of the requested acts every image keeps as its own assignment (with an entry or none)
  covered       share of the acts an entry should show that get one (cases that expect a group)
  wrong         share of the dealt entries outside the groups that show their act
  assigned      share of the dealt entries made for their act's people: their number of humans, and an entry that
                gives someone their own part when the act is done to another character
  clashes       images where one person is in two entries (must be 0)
  dropped       share of the images whose entries no single place suits together and lose one (cases marked clash)
  fallback      share of the requests whose acts share a person that keep no entry (groups without poses)
  distinct      share of an act's images with an entry no earlier image of that act has
  ms            planning, dealing and place check time per request (the embedding index built beforehand)

  python -m tests.eval.composition --embedding-model <gguf> [--llama-server <exe>] [--images 10] [--seed 7]
"""

import argparse
import json
import random
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.scenes import actions
from goated_prompter.features.dataset.v2.scenes.entries import offered_groups
from goated_prompter.features.dataset.v2.scenes.places import SPACES, place_plan
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval
from goated_prompter.features.vocabulary.catalog import load_catalog, selected_vocabulary
from goated_prompter.features.vocabulary.selection import deal_spread, pair

CASES = Path(__file__).parent / "cases" / "composition.json"
OUT = Path("quality-artifacts") / "composition-eval"


def brief(case):
    characters = [{"label": label, "kind": kind, "count": 1} for label, kind in case["cast"]]
    return {"characters": characters, "kept_words": {"action": case["request"]}, "avoid": [], "acts": case["acts"],
            "consistency": {"place": "free"}, "path": "sfw_character", "input": {"request": case["request"]},
            "places": {"setting": "", "world": "everyday", "ideas": case.get("ideas", []), "relations": []}}


def run(case, poses, spaces, total, seed, embeddings):
    rng = random.Random(seed)
    request = brief(case)
    plans = actions.act_plans(request, poses, embeddings)
    if plans is None or not any(found for _, found in plans):
        return plans, None, {}
    assigned = actions.posed(actions.deal_assignments(plans, total, rng), plans, rng)
    found, _ = place_plan(request, spaces, embeddings)
    places = deal_spread(found, total, rng) if found else {}
    text = {number: "; ".join(item["entry"] for item in items if item["entry"]) for number, items in assigned.items()}
    text = {number: words for number, words in text.items() if words}
    if places and text:
        places = pair(places, text, lambda pose, entries: retrieval.fit_scores(pose, entries, embeddings))
    checked = actions.suited_to_place(assigned, places, [entry for group in found for entry in group["entries"]],
                                      embeddings)
    return plans, (assigned, checked), places


def measure(case, plans, dealt, poses):
    group_of = {entry: group["name"] for group in poses for entry in group["entries"]}
    people = {entry: count for group in poses for entry, count in group["people"].items()}
    words = {entry: [group["name"], *group["words"]] for group in poses for entry in group["entries"]}
    humans = {label for label, kind in case["cast"] if kind == "human"}
    row = {"overlap": bool(case.get("overlap"))}
    if case.get("overlap"):  # the acts share a person: no entry kept (built-in groups never say their poses)
        row["fallback"] = 1.0 if dealt is None or not any(item["entry"] for items in dealt[1].values() for item in items)             else 0.0
        return row
    if dealt is None:
        row.update(acts_kept=0.0, covered=0.0 if any(case["expect"]) else None)
        return row
    assigned, checked = dealt
    acts = [act["act"] for act in case["acts"]]
    row["acts_kept"] = sum([item["act"] for item in items] == acts for items in checked.values()) / len(checked)
    expect = case["expect"]
    should = [(number, index) for number in checked for index, groups in enumerate(expect) if groups]
    row["covered"] = (sum(bool(checked[number][index]["entry"]) for number, index in should) / len(should)
                      if should else None)
    entries = [(index, item) for items in checked.values() for index, item in enumerate(items) if item["entry"]]
    row["wrong"] = (sum(group_of[item["entry"]] not in expect[index] for index, item in entries) / len(entries)
                    if entries else None)

    def fits(item):
        cast = len([label for label in [*item["who"], *item["to"]] if label in humans])
        made = people.get(item["entry"], cast)
        roles = not item["to"] or actions.distinct_roles(item["entry"], words[item["entry"]])
        return made <= cast and roles

    row["assigned"] = sum(fits(item) for _, item in entries) / len(entries) if entries else None
    row["clashes"] = sum(any(len({*a["who"], *a["to"]} & {*b["who"], *b["to"]}) for i, a in enumerate(items)
                             for b in items[i + 1:] if a["entry"] and b["entry"]) for items in checked.values())
    row["dropped"] = sum(any(before["entry"] and not after["entry"] for before, after in zip(assigned[n], checked[n]))
                         for n in checked) / len(checked)
    per_act = [[items[index]["entry"] for number, items in sorted(checked.items()) if items[index]["entry"]]
               for index in range(len(acts))]
    rates = [len(set(entries_)) / len(entries_) for entries_ in per_act if entries_]
    row["distinct"] = sum(rates) / len(rates) if rates else None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--llama-server", default="C:/Tools/llama.cpp/llama-server.exe")
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--images", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    catalog = load_catalog(user_root=False)
    packs = [pack["id"] for pack in catalog["packs"] if pack["category"] == "Actions & Poses" and not pack.get("always")]
    selection = {"packs": packs}
    poses = offered_groups(catalog, "Actions & Poses", selection, selected_vocabulary(catalog, selection))
    spaces = retrieval.groups_of(catalog, SPACES, {"packs": []})
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    OUT.mkdir(parents=True, exist_ok=True)
    embeddings = vectors_module.embeddings_for(
        {"local_llama_cpp": {"llama_server": args.llama_server, "embedding_model_path": args.embedding_model}},
        cache_path=OUT / f"embeddings-cache-{Path(args.embedding_model).stem}.json")
    rows = []
    try:
        embeddings.documents([entry for group in poses + spaces for entry in group["entries"]])
        for case in cases:
            started = time.perf_counter()
            plans, dealt, places = run(case, poses, spaces, args.images, args.seed, embeddings)
            row = {"request": case["request"], **measure(case, plans, dealt, poses),
                   "ms": round((time.perf_counter() - started) * 1000, 1)}
            if dealt:
                row["images"] = [[places.get(number), [(item["act"], item["entry"]) for item in items]]
                                 for number, items in sorted(dealt[1].items())]
            rows.append(row)
            show = lambda key: "-" if row.get(key) is None else f"{row[key]:.2f}"
            print(f'{case["request"][:52]:52} ' + " ".join(f"{key[:7]} {show(key)}" for key in
                  ("acts_kept", "covered", "wrong", "assigned", "dropped", "fallback", "distinct")) +
                  f' clashes {row.get("clashes", 0)} ms {row["ms"]}', flush=True)
    finally:
        embeddings.close()
    keys = ("acts_kept", "covered", "wrong", "assigned", "dropped", "fallback", "distinct", "clashes", "ms")
    summary = {key: round(sum(row[key] for row in rows if row.get(key) is not None)
                          / max(1, sum(row.get(key) is not None for row in rows)), 3) for key in keys}
    summary["earlier way"] = "several acts: no entry at all (covered 0, acts kept as assignments 0)"
    print(json.dumps(summary, indent=1))
    (OUT / f"report-{Path(args.cases).stem}.json").write_text(json.dumps({"rows": rows, "summary": summary}, indent=1),
                                                             encoding="utf-8")


if __name__ == "__main__":
    main()
