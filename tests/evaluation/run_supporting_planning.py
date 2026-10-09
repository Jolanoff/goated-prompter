"""Opt-in same-engine Direct/Auto probe. Human review, not semantic guarantees."""

import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService
from goated_prompter.minimax import MiniMaxService
from goated_prompter.backends.llama_cpp_process import get_process_manager
from tests.eval.runner import capture, run_metadata
from tests.support.artifacts import new_output, task_paths
from tests.support.safety import synthetic_storage
from tests.support.scenarios import select_cases


CASES = [
    {"id": "hoop", "workflow": "builder", "request": "a performer suspended sideways from a hoop, one knee hooked over the top, opposite leg extended downward, torso twisted toward the viewer, no hat",
     "review": ["sideways suspension", "hooked knee/equipment contact", "opposite leg extended downward", "torso twist toward viewer", "no forbidden hat or exclusion prose"]},
    {"id": "counterbalance", "workflow": "builder", "request": 'two people counterbalancing each other, holding one hand while leaning in opposite directions. A placard reads "BALANCE".',
     "review": ["exactly two people", "single shared hand contact", "opposing lean and reciprocal balance", "literal BALANCE"]},
    {"id": "motion", "workflow": "minimax", "request": "Two dancers exchange positions while rotating around each other, then one lifts the other as the camera circles them.",
     "review": ["two dancers", "rotation/exchange precedes lift", "shared lift support", "camera circles pair", "continuous action, no unrequested cuts"]},
    {"id": "shots-dialogue", "workflow": "minimax", "request": '<shot1> 0-4s Two people hold one hand and counterbalance while leaning apart. Person A says "No, don’t stop—go!" <shot2> 4-10s They release hands and recover their balance.',
     "review": ["two shots, order and exact 0-4s/4-10s boundaries", "exact dialogue", "shared contact then release/recovery"]},
    {"id": "symbolic-motion", "workflow": "minimax", "references": ["image1", "video1"], "request": "Use only identity from <image1> and movement characteristics from <video1>. Two dancers exchange positions while rotating around each other, then one lifts the other. Place them in a plain rehearsal room. Do not use source wardrobe, source environment or source audio.",
     "review": ["identity from image; movement from video", "symbolic/unseen media, no invented observed facts", "no source wardrobe/environment/audio transfer", "rotation/exchange then lift", "requested rehearsal room"]},
]


def main(argv=None, gpu=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--artifacts", "--output", type=Path, help="Explicitly save generated content for human review")
    parser.add_argument("--case", action="append", choices=[row["id"] for row in CASES])
    parser.add_argument("--target", default="Generic", help="Builder target; MiniMax uses its existing H3 writer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workflow", choices=("builder", "minimax"))
    parser.add_argument("--seed", type=int, help="Seed fixed-case selection/order, not model output")
    parser.add_argument("--limit", type=int, default=1 if gpu else None)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--task-key")
    parser.add_argument("--max-runs", type=int, help="Approved workflow-run ceiling; Direct and Auto each count")
    args = parser.parse_args(argv)
    if gpu and not args.workflow:
        parser.error("Real-engine execution requires one explicit --workflow.")
    try:
        cases = select_cases(CASES, args.case, args.workflow, args.seed, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({"cases": cases, "conditions": ["Direct", "Auto"],
                          "scenario_seed": args.seed, "inference": False,
                          "note": "Auto adds one planning pass; existing reference analysis and repairs remain."}, indent=2))
        return
    scratch = None
    if gpu:
        if not args.allow_live or not args.config or not args.task_key or args.max_runs is None:
            parser.error("Real-engine execution requires --allow-live, --config, --task-key and --max-runs after owner approval.")
        if args.max_runs < 1 or len(cases) * 2 > args.max_runs:
            parser.error("Direct/Auto workflow runs exceed --max-runs; narrow --case/--limit.")
        try:
            results, scratch = task_paths(args.task_key, "gpu")
            args.artifacts = new_output(args.artifacts or results / "results.json", args.task_key, "gpu")
        except ValueError as exc:
            parser.error(str(exc))
    if args.config is None:
        parser.error("--config is required for opt-in real generation.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if gpu and config.get("backend") != "openai_compatible":
        parser.error("Use an explicitly configured existing OpenAI-compatible endpoint; no process ownership changes.")
    if config.get("backend") in {"mock", "debug"}:
        parser.error("Live evaluation refuses mock backends.")
    local = config.get("local_llama_cpp", {})
    records = []
    if gpu:
        result = {**run_metadata(config, hashlib.sha256(json.dumps(CASES, sort_keys=True).encode()).hexdigest()),
                   "scenario_seed": args.seed, "selected_case_ids": [case["id"] for case in cases], "records": records}
        args.artifacts.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.artifacts.open("x", encoding="utf-8") as output:
                output.write(json.dumps(result, ensure_ascii=False, indent=2))
        except FileExistsError:
            parser.error("Output appeared during setup; retained evidence was not overwritten.")
    try:
        with synthetic_storage(scratch) if gpu else nullcontext():
            for case in cases:
                for mode in ("Direct", "Auto"):
                    calls = []
                    request = GoatedPrompterRequest(idea=case["request"], target_model=args.target,
                        creativity="Strict", prompt_length="Medium", planning_mode=mode, prompt_model="Custom",
                        director_keep_model_loaded=True, director_llama_server=local.get("llama_server", ""),
                        director_context_size=local.get("context_size", 32768), director_model_path=local.get("model_path", ""),
                        director_mmproj_path=local.get("mmproj_path", ""))
                    run_config = {**config, "_activity_callback": lambda event: capture(calls, event)}
                    record = {"id": case["id"], "workflow": case["workflow"], "mode": mode,
                        "target": args.target if case["workflow"] == "builder" else "MiniMax H3",
                        "request": case["request"], "review": case["review"]}
                    try:
                        if case["workflow"] == "builder":
                            generated = GoatedPrompterService(config=run_config).generate(request)
                            record.update(prompt=generated.prompt, planning_status=generated.planning_status)
                        else:
                            generated = MiniMaxService(run_config, lambda: None).run(request,
                                {"planning_mode": mode, "user_request": case["request"], "duration_seconds": 10,
                                 "references": case.get("references", [])}, lambda _message: None)
                            record.update(prompt=generated["prompt"], planning_status=generated["planning_status"])
                    except Exception as exc:
                        record["error"] = str(exc)
                        if gpu:
                            record["completion_state"] = getattr(exc, "completion_state", "provider_error")
                    record["calls"] = [{**call, "output": call["raw"]} for call in calls]
                    if gpu:
                        record.update(sample_id=f"supporting:{case['id']}|{case['workflow']}|{mode}|{record['target']}",
                                      planning=mode, anchors={})
                        record.setdefault("completion_state", "completed")
                    records.append(record)
                    if args.artifacts:
                        args.artifacts.write_text(json.dumps(result if gpu else records, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(record if gpu else {"id": record["id"], "mode": mode,
                        "planning_status": record.get("planning_status"), "calls": len(calls), "error": record.get("error")}), flush=True)
                    if gpu:
                        if record.get("error"):
                            return 1
                        if len(records) < len(cases) * 2:
                            if input("Inspect this result before continuing. Type yes: ").strip() != "yes":
                                return
    finally:
        # This evaluator owns its process manager, not the app's engine settings.
        if not gpu:
            get_process_manager().request_unload()


if __name__ == "__main__":
    raise SystemExit(main())
