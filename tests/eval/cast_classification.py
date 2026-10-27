"""Measures how Understanding classifies the cast (tests/eval/cases/cast_classification.json) and what the owners that
read it receive: runs Understanding live once per request (one model call each, as in the app), then reports per
request and in total:

  size       the number of individuals is the labelled one (objects on display are no characters)
  human      each individual is a human or not as labelled (comparable with briefs before kinds)
  kind       each individual's kind is the labelled one (briefs that have kinds)
  gender     each individual's gender is the labelled one; invented: genders the request does not state for anyone of
             that kind; missed: stated genders left out
  neutral    a human of unstated gender has a label that states none ("person 1", "chef", never "man")
  looks      no more people are dealt a human look than the labelled cast has humans (the real looks deal on the
             built-in looks), so no animal, creature, robot or object gets one
  tags       the count tags (1boy, 1girl, 1other) match the labelled cast

  python -m tests.eval.cast_classification --label baseline|new [--settings <quality settings file>] [--seed 173]
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from goated_prompter.features.dataset.v2 import prompts, understanding
from goated_prompter.features.dataset.v2.scenes import looks
from goated_prompter.features.vocabulary.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases" / "cast_classification.json"
OUT = ROOT / "quality-artifacts" / "cast-eval"
GENDERED = {"man", "men", "woman", "women", "boy", "girl", "male", "female", "lady", "guy", "husband", "wife",
            "father", "mother", "son", "daughter", "brother", "sister", "king", "queen", "bride", "groom"}


def human(person):
    return person["kind"] == "human" if "kind" in person else person.get("gender") != "custom"


def kind(person):
    return person.get("kind") or ("human" if human(person) else "other")


def gender(person):
    return person.get("gender") if person.get("gender") in ("male", "female") else ""


def score(case, brief):
    cast, want = brief["characters"], [tuple(row) for row in case["cast"]]
    got_human = Counter(human(person) for person in cast)
    want_human = Counter(row[0] == "human" for row in want)
    got = Counter((human(person), gender(person)) for person in cast)
    expected = Counter((row[0] == "human", row[1]) for row in want)
    stated = lambda counter: Counter({key: value for key, value in counter.items() if key[1]})
    invented = sum((stated(got) - stated(expected)).values())
    missed = sum((stated(expected) - stated(got)).values())
    kinds = Counter(kind(person) for person in cast) == Counter(row[0] for row in want) if all(
        "kind" in person for person in cast) else None
    neutral = all(not ({word.casefold() for word in person["label"].split()} & GENDERED)
                  for person in cast if human(person) and not gender(person) and not person.get("known"))
    groups = looks.look_groups(load_catalog(user_root=False))
    dealt = looks.deal_looks(brief, groups, 1, random.Random(1)) if cast else {}
    looked = set((dealt.get(1) or {}))
    humans = max(0, sum(row[0] == "human" for row in want) - len(case.get("known", ())))  # known ones keep their own look
    tag = {("human", "male"): "boy", ("human", "female"): "girl"}
    want_tags = Counter(tag.get(row if row[0] == "human" else ("", ""), "other") for row in want)
    tags = prompts.count_tags(cast) if cast else []
    expect_tags = [f"{number}{name}{'s' if number > 1 else ''}" for name in ("boy", "girl", "other")
                   if (number := want_tags.get(name))] + (["solo"] if len(want) == 1 else [])
    return {"request": case["request"], "cast": [(person["label"], kind(person), gender(person)) for person in cast],
            "size": len(cast) == len(want), "human": got_human == want_human, "kind": kinds,
            "gender": got == expected, "invented": invented, "missed": missed, "neutral": neutral,
            "looks": len(looked) <= humans, "looked": sorted(looked), "tags": tags == expect_tags, "count_tags": tags}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--settings", default=str(ROOT / "quality.json"))
    parser.add_argument("--seed", type=int, default=173)
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--rescore", action="store_true", help="score the saved briefs again without running the model")
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    saved = OUT / f"briefs-{args.label}.json"
    OUT.mkdir(parents=True, exist_ok=True)
    if args.rescore:
        briefs = json.loads(saved.read_text(encoding="utf-8"))
    else:
        from goated_prompter.backends.llama_cpp_process import get_process_manager
        from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
        from tests.quality.worker import _engine, _request
        config, profile = _engine(json.loads(Path(args.settings).read_text(encoding="utf-8")), ROOT)
        config["local_llama_cpp"] = {**config.get("local_llama_cpp", {}), "keep_model_loaded": True}
        briefs = {}
        try:
            for case in cases:
                data = validate_dataset_draft({**default_dataset_draft(), "subject": case["request"], "amount": 3,
                                               "nsfw": False, "seed": args.seed, "seed_mode": "fixed"}, generation=True)
                request = _request(profile, config, idea=data["subject"], mode="Custom", target_model=data["target"],
                                   creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
                                   director_preset="general_director")
                briefs[case["request"]] = understanding.understand(config, request, data, progress=lambda _: None)
        finally:
            get_process_manager().cleanup_all()
        saved.write_text(json.dumps(briefs, indent=1), encoding="utf-8")
    rows = [score(case, briefs[case["request"]]) for case in cases]
    for row in rows:
        marks = " ".join(f"{key}={'ok' if row[key] else ('-' if row[key] is None else 'NO')}"
                         for key in ("size", "human", "kind", "gender", "neutral", "looks", "tags"))
        print(f'{row["request"][:40]:40} {marks} inv={row["invented"]} miss={row["missed"]} | {row["cast"]}', flush=True)
    rate = lambda key: round(sum(bool(row[key]) for row in rows if row[key] is not None)
                             / max(1, sum(row[key] is not None for row in rows)), 3)
    summary = {**{key: rate(key) for key in ("size", "human", "kind", "gender", "neutral", "looks", "tags")},
               "invented": sum(row["invented"] for row in rows), "missed": sum(row["missed"] for row in rows)}
    print(json.dumps(summary))
    (OUT / f"report-{args.label}.json").write_text(json.dumps({"rows": rows, "summary": summary}, indent=1),
                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
