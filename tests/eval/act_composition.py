"""Measures composing Actions & Poses for requests with several acts, the same person's acts included
(v2/scenes/actions.py: act_plans, deal_assignments, posed), on labelled cases with the small test vocabulary
tests/eval/fixtures/act_composition_pack.json (groups of actions with their poses, and one group of entries without
poses). No model and no embeddings: the acts' words find their groups. Per request and in total:

  acts kept     share of the images that keep every requested act as its own assignment, in order
  right         share of the acts whose kept entry is from the expected group, or none when none is expected
  roles         share of the kept entries whose letters are bound to their act's people, who does it first
  one pose      share of the people in several acts, among images that keep their entries, with one pose for all
  fallback      share of the acts expected to keep no entry that keep none
  distinct      share of an act's images with an entry no earlier image of that act has
  ms            planning, dealing and posing time per request

  python -m tests.eval.act_composition [--cases tests/eval/cases/act_composition_heldout.json] [--images 10]
The held-out cases (act_composition_heldout.json) were labelled before any run and are run once.
"""

import argparse
import json
import random
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.scenes import actions
from goated_prompter.features.vocabulary import retrieval
from goated_prompter.features.vocabulary.catalog import read_pack

PACK = Path(__file__).parent / "fixtures" / "act_composition_pack.json"
CASES = Path(__file__).parent / "cases" / "act_composition.json"


def vocabulary():
    pack = read_pack(PACK, "Actions & Poses", "Actions & Poses", "test/")
    catalog = {"packs": [{**pack, "always": False}]}
    return retrieval.groups_of(catalog, "Actions & Poses", {"packs": [pack["id"]]})


def brief(case):
    return {"characters": [{"label": label, "kind": kind, "count": 1} for label, kind in case["cast"]],
            "kept_words": {"action": case["request"]}, "avoid": [], "acts": case["acts"]}


def measure(case, groups, images, seed):
    started = time.perf_counter()
    plans = actions.act_plans(brief(case), groups)
    assigned = actions.posed(actions.deal_assignments(plans, images, random.Random(seed)), plans, random.Random(seed))
    ms = (time.perf_counter() - started) * 1000
    group_of = {entry: group["name"] for group in groups for entry in group["entries"]}
    acts = [act["act"] for act in case["acts"]]
    rows = list(assigned.values())
    expect = case["expect"]
    row = {"request": case["request"], "ms": round(ms, 2)}
    row["acts_kept"] = sum([item["act"] for item in items] == acts for items in rows) / len(rows)
    row["right"] = sum((group_of.get(item["entry"]) if item["entry"] else None) == expect[index]
                       for items in rows for index, item in enumerate(items)) / (len(rows) * len(acts))
    kept = [item for items in rows for item in items if item["entry"]]
    people = lambda item: [*item["who"], *[label for label in item["to"] if label not in item["who"]]]
    row["roles"] = (sum(all(item["roles"].get(letter) == label for letter, label in zip("ABCDEFGH", people(item))
                            if letter in item["roles"]) for item in kept) / len(kept)) if kept else None
    shared = []
    for items in rows:
        poses = {}
        for item in items:
            if item["entry"]:
                for label, pose in item["poses"].items():
                    poses.setdefault(label, set()).add(pose)
        shared += [len(found) == 1 for label, found in poses.items()
                   if sum(label in people(item) for item in items) > 1]
    row["one_pose"] = sum(shared) / len(shared) if shared else None
    none = [(index, items) for items in rows for index in range(len(acts)) if expect[index] is None]
    row["fallback"] = sum(not items[index]["entry"] for index, items in none) / len(none) if none else None
    per_act = [[items[index]["entry"] for items in rows if items[index]["entry"]] for index in range(len(acts))]
    rates = [len(set(found)) / len(found) for found in per_act if found]
    row["distinct"] = sum(rates) / len(rates) if rates else None
    row["images"] = [[(item["act"], item["entry"], item["roles"], item["poses"]) for item in items] for items in rows[:3]]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--images", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    groups = vocabulary()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    rows = [measure(case, groups, args.images, args.seed) for case in cases]
    keys = ("acts_kept", "right", "roles", "one_pose", "fallback", "distinct", "ms")
    for row in rows:
        show = lambda key: "-" if row.get(key) is None else f"{row[key]:.2f}"
        print(f'{row["request"][:56]:56} ' + " ".join(f"{key[:8]} {show(key)}" for key in keys))
    summary = {key: round(sum(row[key] for row in rows if row.get(key) is not None)
                          / max(1, sum(row.get(key) is not None for row in rows)), 3) for key in keys}
    print(json.dumps(summary, indent=1))
    out = Path("quality-artifacts") / "act-composition-eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"report-{Path(args.cases).stem}.json").write_text(json.dumps({"rows": rows, "summary": summary}, indent=1),
                                                             encoding="utf-8")


if __name__ == "__main__":
    main()
