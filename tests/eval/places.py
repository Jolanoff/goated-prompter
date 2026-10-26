"""Places retrieval evaluation: runs the app's place search, deal, validation and pose matching on the labelled cases in
tests/eval/cases/places.json with the real embedding model on the CPU (no generation model), and reports relevance,
variety, correctness and speed.

  python -m tests.eval.places --llama-server PATH --embedding-model PATH [--output quality-artifacts/places-eval/run.json]
  python -m tests.eval.places --no-embeddings     (exact words only)
  --cases tests/eval/cases/places_heldout.json    held-out cases, never used to tune a setting

Results and the embedding cache go under quality-artifacts/places-eval/, never into the app's data folder.
"""

import argparse
import csv
import io
import itertools
import json
import random
import statistics
import subprocess
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.scenes import places
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval, selection
from goated_prompter.features.vocabulary.catalog import load_catalog

CASES = Path(__file__).parent / "cases" / "places.json"
OUT = Path("quality-artifacts") / "places-eval"
IMAGES = 10


IDEAS = {}  # {request: Understanding's ideas}, from --ideas (a file of captured briefs)


def _brief(request, level="free", words=None, setting="", world="everyday", path="sfw_character"):
    return {"input": {"request": request, "seed": 1}, "summary": request, "path": path,
            "consistency": {"place": level}, "kept_words": {"place": words} if words else {},
            "places": {"setting": setting, "world": world, "ideas": list(IDEAS.get(request, ()))}}


def _kind_of(kinds):
    return {group: kind for kind, names in kinds.items() for group in names}


def free_cases(cases, groups, embeddings, kinds):
    owner = {entry: group["name"] for group in groups for entry in group["entries"]}
    rows = []
    for case in cases:
        brief = _brief(case["request"], world=case.get("world", "everyday"), path=case.get("path", "sfw_character"))
        began = time.perf_counter()
        found, _ = places.place_plan(brief, groups, embeddings)
        seconds = time.perf_counter() - began
        dealt = list(selection.deal_spread(found, IMAGES, random.Random(1)).values())
        names = [owner[place] for place in dealt]
        rows.append({"request": case["request"], "groups": [group["name"] for group in found], "dealt": names,
                     "relevant": sum(name in case["acceptable"] for name in names),
                     "forbidden": sum(name in case["forbidden"] for name in names),
                     "distinct": len(set(names)), "kinds": len({kinds.get(name) for name in names}),
                     "empty": not names, "ms": round(1000 * seconds, 1)})
    dealt = sum(len(row["dealt"]) for row in rows) or 1
    return rows, {"precision": round(sum(row["relevant"] for row in rows) / dealt, 3),
                  "forbidden_rate": round(sum(row["forbidden"] for row in rows) / dealt, 3),
                  "empty_cases": sum(row["empty"] for row in rows),
                  "distinct_groups": round(statistics.mean(row["distinct"] for row in rows), 2),
                  "distinct_kinds": round(statistics.mean(row["kinds"] for row in rows), 2),
                  "ms": round(statistics.mean(row["ms"] for row in rows), 1)}


def named_cases(cases, groups, embeddings):
    rows = []
    for case in cases:
        brief = _brief(case["words"], "themed", case["words"], case.get("setting", ""), case.get("world", "everyday"))
        began = time.perf_counter()
        found, setting = places.place_plan(brief, groups, embeddings)
        names = [group["name"] for group in found]
        wanted, banned = case["acceptable"], case.get("forbidden", [])
        correct = (bool(names) and all(name in wanted for name in names)) if wanted else not names
        rows.append({"words": case["words"], "found": names, "setting": setting, "correct": correct,
                     "forbidden": any(name in banned for name in names),
                     "setting_lost": bool(case.get("setting_kept")) and setting != case.get("setting"),
                     "ms": round(1000 * (time.perf_counter() - began), 1)})
    return rows, {"accuracy": round(sum(row["correct"] for row in rows) / len(rows), 3),
                  "found_when_none": sum(bool(row["found"]) for row, case in zip(rows, cases) if not case["acceptable"]),
                  "missed": sum(not row["found"] for row, case in zip(rows, cases) if case["acceptable"]),
                  "forbidden": sum(row["forbidden"] for row in rows),
                  "settings_lost": sum(row["setting_lost"] for row in rows)}


def validation_cases(cases, groups, embeddings):
    rows = []
    words = retrieval.telling_words(groups)
    for case in cases:
        scene = {"space": case["space"]}
        problems = (places.place_problems(scene, case["place"], words) if words is not None
                    else places.place_problems(scene, case["place"]))
        rows.append({"place": case["place"], "space": case["space"], "expected_pass": case["pass"],
                     "passed": not problems})
    wrong = [row for row in rows if row["passed"] != row["expected_pass"]]
    return rows, {"accuracy": round(1 - len(wrong) / len(rows), 3),
                  "needless_redos": sum(row["expected_pass"] and not row["passed"] for row in rows),
                  "missed_wrong_places": sum(not row["expected_pass"] and row["passed"] for row in rows)}


def pose_cases(cases, groups, embeddings):
    by_name = {group["name"]: group for group in groups}
    rows, wins, pairs = [], 0, 0
    for case in cases:
        fits = [entry for name in case["fits"] for entry in by_name[name]["entries"]]
        clashes = [entry for name in case["clashes"] for entry in by_name[name]["entries"]]
        scores = retrieval.fit_scores(case["pose"], fits + clashes, embeddings)
        good, bad = scores[:len(fits)], scores[len(fits):]
        won = sum((g > b) + .5 * (g == b) for g, b in itertools.product(good, bad))
        wins, pairs = wins + won, pairs + len(good) * len(bad)
        rows.append({"pose": case["pose"][:60], "auc": round(won / (len(good) * len(bad)), 3)})
    # A set of images: each pose with one place of one of its fitting groups, dealt in a shuffled order.
    rng = random.Random(1)
    poses = [case["pose"] for case in cases]
    dealt_places = [by_name[case["fits"][0]]["entries"][0] for case in cases]
    clash = lambda pose_list, place_list: sum(
        any(place in by_name[name]["entries"] for name in case["clashes"])
        for case, place in zip([next(c for c in cases if c["pose"] == pose) for pose in pose_list], place_list))
    before = after = 0
    for _ in range(20):
        shuffled = rng.sample(dealt_places, len(dealt_places))
        before += clash(poses, shuffled)
        result = selection.pair(dict(enumerate(shuffled, 1)), dict(enumerate(poses, 1)),
                                lambda pose, entries: retrieval.fit_scores(pose, entries, embeddings))
        after += clash(poses, [result[number] for number in range(1, len(poses) + 1)])
    return rows, {"auc": round(wins / pairs, 3) if pairs else None, "clashes_dealt": before / 20,
                  "clashes_matched": after / 20}


def _memory_mb(pid):
    """The working set of a process in MB (Windows tasklist; None elsewhere or when it cannot be read)."""
    try:
        row = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=10).stdout
        return round(int(next(csv.reader(io.StringIO(row)))[4].replace(",", "").replace(".", "").split()[0]) / 1024)
    except (OSError, ValueError, IndexError, StopIteration, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llama-server", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--no-embeddings", action="store_true")
    parser.add_argument("--cold", action="store_true", help="embed the catalog again, to time a first run")
    parser.add_argument("--output", default=str(OUT / "run.json"))
    parser.add_argument("--label", default="")
    parser.add_argument("--cases", default=str(CASES), help="a labelled corpus (places.json or places_heldout.json)")
    parser.add_argument("--ideas", default="", help="{request: [ideas]} captured from Understanding for the cases")
    args = parser.parse_args()
    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    IDEAS.update(json.loads(Path(args.ideas).read_text(encoding="utf-8")) if args.ideas else {})
    groups = retrieval.groups_of(load_catalog(user_root=False), places.SPACES, {"packs": []})
    cache = OUT / f"embeddings-cache-{Path(args.embedding_model).stem or 'none'}.json"  # one per model
    if args.cold and cache.exists():
        cache.unlink()
    embeddings = None if args.no_embeddings else vectors_module.embeddings_for(
        {"local_llama_cpp": {"llama_server": args.llama_server, "embedding_model_path": args.embedding_model}},
        cache_path=cache)
    began = time.perf_counter()
    report = {"label": args.label, "model": Path(args.embedding_model).name if embeddings else None}
    try:
        if embeddings is not None:  # build the index once, so the per-request timings show searching only
            embeddings.documents([retrieval.group_text(group) for group in groups]
                                 + [entry for group in groups for entry in group["entries"]])
        report["index_seconds"] = round(time.perf_counter() - began, 2)
        for name, run, cases in (("free", lambda c: free_cases(c, groups, embeddings, _kind_of(data["kinds"])), data["free"]),
                                 ("named", lambda c: named_cases(c, groups, embeddings), data["named"]),
                                 ("validation", lambda c: validation_cases(c, groups, embeddings), data["validation"]),
                                 ("poses", lambda c: pose_cases(c, groups, embeddings), data["poses"])):
            rows, summary = run(cases)
            report[name] = {"summary": summary, "cases": rows}
        process = getattr(getattr(embeddings, "embedder", None), "_process", None)
        report["server_memory_mb"] = _memory_mb(process.pid) if process else None
    finally:
        if embeddings is not None:
            embeddings.close()
    report["seconds"] = round(time.perf_counter() - began, 2)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    for name in ("free", "named", "validation", "poses"):
        print(f"{name:10} {report[name]['summary']}")
    print(f"index {report['index_seconds']} s, total {report['seconds']} s, server memory "
          f"{report['server_memory_mb']} MB -> {output}")


if __name__ == "__main__":
    main()
