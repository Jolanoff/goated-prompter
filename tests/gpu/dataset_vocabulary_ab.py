"""Dataset vocabulary A/B: the same confirmed brief through Section 2 with vocabulary off and on.

Each case in fixtures/dataset_vocabulary_ab.json is a fixed confirmed brief, so Understanding never
varies between arms. Both arms use the same config, model, settings and sampling seed; the only
difference is "dataset_vocabulary" (false / true). The seed is set on each Section 2 request by
wrapping the backend here; the pipeline itself is unchanged.

A case whose vocabulary block is empty is not comparable: both arms would send identical requests.
It is reported as such and costs no run.

  python -m tests.gpu.dataset_vocabulary_ab --dry-run [--installed-packs]
      No inference. Shows, per case, what the vocabulary gives the Director and whether the case
      is comparable.
  python -m tests.gpu.dataset_vocabulary_ab --allow-live --config CONFIG.json --task-key KEY --max-runs N
                                            [--seed 1234] [--case ID] [--control] [--installed-packs]
      Real engine, after owner approval: an existing OpenAI-compatible endpoint only (no process
      changes). One run = one Section 2 call of write_scenes for one arm. --control repeats the
      off arm to show whether the seed makes this engine repeatable. Writes results.json (with the
      blind key) and review.json (blind A/B sheet) under quality-artifacts/tasks/KEY/gpu/.

Packs: the core only, unless --packs-dir DIR loads every pack folder in DIR as installed, or
--installed-packs uses the app's packs as the Dataset Builder does: core, the official packs in
vocabulary/packs (unless disabled) and the packs installed in data/vocabulary/packs.
Quality is judged by a reviewer with review.json; this script reports counts, never a score.
"""

import argparse
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
from unittest import mock

from tests.eval.metrics import normalized
from tests.support.artifacts import new_output, task_paths
from tests.support.paths import ROOT
from tests.support.safety import private_storage_guard, synthetic_storage

CASES = Path(__file__).resolve().parent / "fixtures" / "dataset_vocabulary_ab.json"
CRITERIA = ("request_preservation", "identities_and_roles", "physical_and_spatial_coherence", "scene_diversity",
            "unwanted_or_repetitive_details")


def briefs(fixture, selected=None):
    settings, amount = fixture["settings"], fixture["amount"]
    result = []
    for case in fixture["cases"]:
        if selected and case["id"] not in selected:
            continue
        result.append((case["id"], {
            "version": 9, "path": "sfw_character" if case["characters"] else "non_character", "summary": case["request"],
            "people": len(case["characters"]), "characters": case["characters"], "fixed": case["fixed"],
            "randomized": case["randomized"], "must": case["must"], "avoid": case["avoid"],
            "input": {"request": case["request"], "trigger": "", "trigger_at_start": False, "rules": [], "amount": amount, "nsfw": False},
            "settings": dict(settings)}))
    if selected and len(result) != len(set(selected)):
        raise ValueError("Unknown case id; see " + CASES.name)
    return result


def pack_manager(installed, scratch, packs_dir=None):
    from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, PackManager
    if installed:
        return PackManager()
    if packs_dir:
        return PackManager(install_dir=packs_dir, state_file=scratch / "packs-dir-state.json", bundled_dirs=BUNDLED_DIRS,
                           official_dir=None)
    return PackManager(install_dir=scratch / "no-installed-packs", state_file=scratch / "no-state.json", bundled_dirs=BUNDLED_DIRS,
                       official_dir=None)


def reference(brief, packs):
    """What the on arm gives the Director (vocabulary_reference with the brief's own director)."""
    from goated_prompter.features.dataset.director import active_director
    from goated_prompter.features.dataset.v2.vocabulary_packs import vocabulary_reference
    preset = active_director({"director_preset": brief["settings"]["director"], "target": brief["settings"]["target"]})
    return vocabulary_reference({}, brief, director=preset.instructions.strip() if preset else "", manager=packs)


class _SeededSession:
    def __init__(self, session, seed):
        self.session, self.seed = session, seed

    def generate(self, instruction):
        return self.session.generate(replace(instruction, seed=self.seed))

    def __getattr__(self, name):
        return getattr(self.session, name)


class _Seeded:
    def __init__(self, backend, seed):
        self.backend, self.seed = backend, seed

    @contextmanager
    def generation_session(self):
        with self.backend.generation_session() as session:
            yield _SeededSession(session, self.seed)


def run_arm(config, brief, packs, seed, vocabulary):
    """One Section 2 run; returns the result, its concepts and every model call."""
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.features.dataset.v2 import scenes
    from tests.gpu.common import capture
    calls, traces = [], []

    class KeptTrace(scenes.DebugTrace):
        def finish(self, output=None, error=None):
            traces.append(self.record)
            return super().finish(output=output, error=error)

    settings = brief["settings"]
    request = GoatedPrompterRequest(idea=brief["input"]["request"], mode="Custom", target_model=settings["target"],
                                    creativity=settings["creativity"], style=settings["style"],
                                    prompt_length=settings["length"], director_preset=settings["director"])
    arm_config = {**config, "dataset_vocabulary": vocabulary, "_activity_callback": lambda event: capture(calls, event)}
    row = {"vocabulary": vocabulary, "seed": seed}
    with mock.patch.object(scenes, "create_backend", lambda effective: _Seeded(create_backend(effective), seed)), \
            mock.patch.object(scenes, "DebugTrace", KeptTrace):
        try:
            row["result"] = scenes.write_scenes(arm_config, request, json.loads(json.dumps(brief)), packs=packs,
                                                progress=lambda message: print(f"  {message}", flush=True))
        except Exception as error:  # the row keeps the failure for the reviewer
            row["error"] = f"{type(error).__name__}: {error}"
    decisions = traces[-1]["decisions"] if traces else []
    row["concepts"] = next((item["detail"] for item in decisions if item["rule"] == "concepts"), [])
    row["calls"] = [{key: call.get(key) for key in ("stage", "finish_reason", "completion_state", "latency_seconds", "usage")}
                    for call in calls]
    scenes_written = row.get("result", {}).get("scenes", [])
    row["counts"] = {"requested": brief["input"]["amount"], "written": len(scenes_written),
                     "complete": row.get("result", {}).get("complete", False), "model_calls": len(calls),
                     "distinct_places": len({normalized(concept["place"]) for concept in row["concepts"]}),
                     "distinct_position_names": len({normalized(concept["position_name"]) for concept in row["concepts"]})}
    return row


def review_sheet(cases, seed):
    """Blind A/B per comparable case; the arm behind A and B is only in results.json."""
    sheet, key = [], {}
    for number, case in enumerate(cases):
        if not case["comparable"] or any("error" in case["arms"].get(arm, {"error": 1}) for arm in ("off", "on")):
            continue
        order = ["off", "on"]
        random.Random(seed * 1000 + number).shuffle(order)
        key[case["id"]] = {"A": order[0], "B": order[1]}
        arms = {label: {"concepts": case["arms"][arm]["concepts"], "scenes": case["arms"][arm]["result"]["scenes"],
                        **{criterion: {"score_1_to_5": None, "notes": ""} for criterion in CRITERIA}}
                for label, arm in zip("AB", order)}
        sheet.append({"case": case["id"], "request": case["brief"]["input"]["request"], "fixed": case["brief"]["fixed"],
                      "characters": case["brief"]["characters"], "must": case["brief"]["must"], "avoid": case["brief"]["avoid"],
                      "arms": arms, "preferred": None,
                      "vocabulary_offered_to_one_arm": case["vocabulary"]["block"],
                      "vocabulary_relevance": {"score_1_to_5": None, "notes": ""}, "reviewer": "", "notes": ""})
    return sheet, key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--task-key")
    parser.add_argument("--max-runs", type=int, help="Approved maximum Section 2 runs (one arm of one case each)")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--case", action="append")
    parser.add_argument("--control", action="store_true", help="Repeat the off arm to check repeatability")
    parser.add_argument("--installed-packs", action="store_true", help="Include the packs installed in this app")
    parser.add_argument("--packs-dir", type=Path, help="Load every pack folder in this directory as installed")
    args = parser.parse_args(argv)
    if args.installed_packs and args.packs_dir:
        parser.error("Use --installed-packs or --packs-dir, not both.")
    if args.packs_dir:
        args.packs_dir = args.packs_dir.resolve()
        if not args.packs_dir.is_dir():
            parser.error(f"{args.packs_dir} is not a directory.")
    packs_label = ("core + official + installed" if args.installed_packs else
                   f"core + {args.packs_dir.name}/ ({', '.join(sorted(p.name for p in args.packs_dir.iterdir() if p.is_dir()))})"
                   if args.packs_dir else "core only")
    if not args.installed_packs:
        sys.addaudithook(private_storage_guard)  # core only: nothing under data/ is read
    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    try:
        selected = briefs(fixture, args.case)
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="vocabulary-ab-") as temporary, synthetic_storage(Path(temporary)):
            packs = pack_manager(args.installed_packs, Path(temporary), args.packs_dir)
            report = []
            for case_id, brief in selected:
                found = reference(brief, packs)
                report.append({"case": case_id, "comparable": bool(found["block"]), "provided": found["provided"],
                               "cast": found["log"].get("cast"), "warnings": found["log"].get("warnings", []),
                               "error": found["log"].get("error"), "block": found["block"]})
        print(json.dumps({"packs": packs_label, "inference": False,
                          "cases": report, "runs_needed": sum(item["comparable"] for item in report) * (3 if args.control else 2)},
                         ensure_ascii=False, indent=2))
        return 0

    if not (args.allow_live and args.config and args.task_key and args.max_runs is not None):
        parser.error("Real-engine runs require --allow-live, --config, --task-key and --max-runs after owner approval.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("backend") != "openai_compatible":
        parser.error("Use an explicitly configured existing OpenAI-compatible endpoint; no process ownership changes.")
    try:
        results_dir, scratch = task_paths(args.task_key, "gpu")
        output = new_output(results_dir / "vocabulary-ab-results.json", args.task_key, "gpu")
        review_output = new_output(results_dir / "vocabulary-ab-review.json", args.task_key, "gpu")
    except ValueError as exc:
        parser.error(str(exc))
    from tests.gpu.common import run_metadata
    run = {**run_metadata(config, hashlib.sha256(CASES.read_bytes()).hexdigest()), "seed": args.seed,
           "packs": packs_label, "cases": []}
    arms = ("off", "on", "control") if args.control else ("off", "on")
    with synthetic_storage(scratch):
        packs = pack_manager(args.installed_packs, scratch, args.packs_dir)
        plan = [(case_id, brief, reference(brief, packs)) for case_id, brief in selected]
        needed = sum(bool(found["block"]) for _, _, found in plan) * len(arms)
        if needed > args.max_runs:
            parser.error(f"{needed} runs are needed; --max-runs is {args.max_runs}. Narrow --case or drop --control.")
        output.parent.mkdir(parents=True, exist_ok=True)
        done = 0
        for case_id, brief, found in plan:
            case = {"id": case_id, "brief": brief, "comparable": bool(found["block"]), "vocabulary": found["log"], "arms": {}}
            run["cases"].append(case)
            if not case["comparable"]:
                case["not_comparable"] = "the vocabulary gives the Director nothing for this case, so both arms are identical"
                output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{case_id}: not comparable (no vocabulary provided); no run spent.")
                continue
            for arm in arms:
                print(f"{case_id}: vocabulary {'on' if arm == 'on' else 'off'}{' (control)' if arm == 'control' else ''}")
                case["arms"][arm] = run_arm(config, brief, packs, args.seed, arm == "on")
                done += 1
                output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"counts": case["arms"][arm]["counts"], "error": case["arms"][arm].get("error")}, indent=2))
                if case["arms"][arm].get("error"):
                    print("Stopped: this run failed. See the results file.")
                    return 1
                if done < needed and input("Inspect this result before continuing. Type yes: ").strip() != "yes":
                    return 0
            if args.control:
                off, control = case["arms"]["off"]["result"]["scenes"], case["arms"]["control"]["result"]["scenes"]
                case["repeatable"] = off == control
        sheet, key = review_sheet(run["cases"], args.seed)
        run["blind_key"] = key
        output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        review_output.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Results: {output.relative_to(ROOT)}\nReview sheet: {review_output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
