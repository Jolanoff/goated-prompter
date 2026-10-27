"""Measures the built-in cameras (v2/scenes/camera.py) on labelled requests (tests/eval/cases/camera.json) against
dealing a camera's parts on their own: a shot, an angle and a view each drawn from all the built-in cameras' parts.
Per request and in total:

  pose fit    share of the images whose camera is one of the groups that show the request well (expect)
  coherent    share of the images whose camera is a whole built-in camera, not parts put together at random
  shape fit   share of the images that do not show a lying body from the side at full length in a tall image
  visible     share of the images whose shot shows what the request asks to show and a known character at least
              head to hips
  kept        share of the images whose camera keeps what the request's camera words ask of a part
  distinct    share of the images with a camera no earlier image has; shots: distinct shot sizes
  ms          retrieval and selection time per request (no model: cameras are found by words)

  python -m tests.eval.camera [--cases tests/eval/cases/camera_heldout.json] [--images 10] [--seed 7]
The held-out cases (camera_heldout.json) were labelled before any run and never used to write the built-in cameras.
"""

import argparse
import json
import random
import time
from pathlib import Path

from goated_prompter.features.dataset.v2.aspect import aspect_shape
from goated_prompter.features.dataset.v2.scenes import camera
from goated_prompter.features.dataset.v2.scenes.settings import AT_LEAST_HIPS, SHOWS
from goated_prompter.features.vocabulary import retrieval
from goated_prompter.features.vocabulary.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases" / "camera.json"
OUT = ROOT / "quality-artifacts" / "camera-eval"
KEYS = ("pose_fit", "coherent", "shape_fit", "visible", "kept", "distinct", "shots")


def brief(case):
    words = {key: case[key] for key in ("action", "subject", "camera") if case.get(key)}
    return {"input": {"request": case["request"]}, "must": [], "avoid": [], "kept_words": words,
            "consistency": {"camera": case.get("level", "free")}, "settings": {"aspect": case.get("aspect", "Auto")},
            "characters": [{"label": f"person {n}", "known": bool(case.get("known")) and n == 1}
                           for n in range(1, case.get("cast", 1) + 1)]}


def new_way(case, groups, total, seed):
    return camera.deal_cameras(brief(case), groups, total, random.Random(seed))


def parts_way(groups, total, seed):
    rng = random.Random(seed)
    facets = {}
    for group in groups:
        for entry in group["entries"]:
            for facet, part in retrieval.entry_parts(entry):
                facets.setdefault(facet, set()).add(part)
    pick = lambda facet: rng.choice(sorted(facets[facet]))
    return {n: f'{pick("shot")} with {pick("angl")} and {pick("view")}' for n in range(1, total + 1)}


def measure(case, dealt, groups):
    kind = {entry: group["name"] for group in groups for entry in group["entries"]}
    images = list(dealt.values())
    if not images:
        return {"images": 0}
    parts = [dict(retrieval.entry_parts(entry)) for entry in images]
    tall = (aspect_shape(case.get("aspect", "Auto")) or ("",))[0] == "tall"
    widest = SHOWS.index(case["needs"]) if case.get("needs") else len(SHOWS) - 1
    if case.get("known"):
        widest = min(widest, len(AT_LEAST_HIPS) - 1)
    frames = [camera.shot_frame(entry) for entry in images]
    row = {"images": len(images),
           "pose_fit": sum(kind.get(entry) in case["expect"] for entry in images) / len(images),
           "coherent": sum(entry in kind for entry in images) / len(images),
           "shape_fit": (sum(not (frame == "full body" and part["view"] == "side view")
                             for frame, part in zip(frames, parts)) / len(images)) if tall and case.get("lies") else None,
           "visible": sum(frame is not None and SHOWS.index(frame) <= widest for frame in frames) / len(images),
           "kept": (sum(all(word in part.get(facet, "") for facet, word in case["parts"].items()) for part in parts)
                    / len(images)) if case.get("parts") else None,
           "distinct": len(set(images)) / len(images), "shots": len(set(frames))}
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--images", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    groups = camera.camera_groups(load_catalog(user_root=False))
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"new": [], "parts": []}
    for case in cases:
        started = time.perf_counter()
        dealt = new_way(case, groups, args.images, args.seed)
        ms = (time.perf_counter() - started) * 1000
        new = {"request": case["request"], **measure(case, dealt, groups), "ms": round(ms, 1),
               "dealt": [dealt.get(n) for n in range(1, args.images + 1)]}
        old = {"request": case["request"], **measure(case, parts_way(groups, args.images, args.seed), groups)}
        report["new"].append(new)
        report["parts"].append(old)
        show = lambda row, key: "-" if row.get(key) is None else f"{row[key]:.2f}"
        print(f'{case["request"][:40]:40} ' + " ".join(f"{key[:5]} {show(old, key)}>{show(new, key)}" for key in KEYS)
              + f' ms {new["ms"]}', flush=True)
    summary = {side: {key: round(sum(r[key] for r in rows if r.get(key) is not None)
                                 / max(1, sum(r.get(key) is not None for r in rows)), 3) for key in KEYS}
               for side, rows in report.items()}
    summary["new"]["ms"] = round(sum(r["ms"] for r in report["new"]) / len(report["new"]), 1)
    print(json.dumps(summary, indent=1))
    (OUT / f"report-{Path(args.cases).stem}.json").write_text(json.dumps({**report, "summary": summary}, indent=1),
                                                              encoding="utf-8")


if __name__ == "__main__":
    main()
