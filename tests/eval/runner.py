"""Reusable frozen/live workflow evaluation. Live inference is explicit and opt-in."""

import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import time
from contextlib import nullcontext

from .metrics import annotation_template
from tests.support.artifacts import new_output, task_paths
from tests.support.paths import ROOT
from tests.support.safety import synthetic_storage
from tests.support.scenarios import select_cases

CORPUS = Path(__file__).parent / "cases" / "corpus.json"


def capture(calls, event):
    kind = event.get("type")
    if kind == "request":
        calls.append({"stage": event.get("stage"), "parameters": event.get("parameters"),
                      "messages": event.get("messages"), "raw": "", "finish_reason": None,
                      "started_at": time.perf_counter()})
    elif calls and kind == "response_delta":
        calls[-1]["raw"] += str(event.get("text") or "")
    elif calls and kind == "response_complete":
        calls[-1].update(finish_reason=event.get("finish_reason"), completion_state=event.get("completion_state", "completed"))
        calls[-1]["latency_seconds"] = time.perf_counter() - calls[-1]["started_at"]
    elif calls and kind == "error":
        calls[-1].update(error=event.get("message"), completion_state=event.get("completion_state", "provider_error"))
        calls[-1]["latency_seconds"] = time.perf_counter() - calls[-1]["started_at"]
    elif calls and kind in {"semantic_review", "validation"}:
        calls[-1].setdefault("validation_events", []).append(event)


def live_case(case, workflow, config, args, run=1):
    from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService
    from goated_prompter.dataset import DatasetService, default_dataset_draft
    from goated_prompter.prompting.dataset import STYLE_RULES
    from goated_prompter.minimax import MiniMaxService
    from goated_prompter.planning.constraints import compile_request
    calls = []
    config = {**config, "_activity_callback": lambda event: capture(calls, event)}
    length = case.get("length", args.length)
    compiled_source = compile_request(case["request"])
    rules = case.get("rules", "")
    if compiled_source.forbidden:
        rules += "\n" + "; ".join("no " + fact for fact in compiled_source.forbidden)
    # Match Dataset's explicit trigger/identity restriction in Builder parity;
    # it is evaluation scaffolding, not a new production planning step.
    source = case["request"] if workflow == "minimax" else "eval_subject represents " + case["request"]
    common_rules = STYLE_RULES[args.style] + "\n" + rules
    identity_rules = ""
    if workflow != "minimax":
        identity_rules = "Include the exact subject identifier eval_subject. Do not invent stable identity traits or gender; compatible temporary clothing and scene detail are allowed."
        common_rules += "\n" + identity_rules
    request = GoatedPrompterRequest(idea=source, target_model=args.target, prompt_length=length,
        director_preset=args.director, creativity=args.creativity, planning_mode=args.planning,
        custom_instructions=common_rules)
    sample_id = "|".join(str(value) for value in (case["id"], workflow, args.target, length, args.director,
                                               args.style, args.creativity, args.planning, run))
    if workflow == "dataset":
        sample_id += "|pipeline"
    row = {"sample_id": sample_id, "case_id": case["id"], "workflow": workflow,
           "run": run, "request": case["request"], "anchors": case["anchors"], "rules": rules,
           "target": "MiniMax H3" if workflow == "minimax" else args.target, "length": length, "director": args.director,
           "style": args.style, "creativity": args.creativity, "planning": args.planning,
            "effective_request": source, "calls": calls}
    if workflow != "minimax":
        row.update(trigger="eval_subject", expand_trigger=False)
    start = time.perf_counter()
    try:
        if workflow == "builder":
            row["prompt"] = GoatedPrompterService(config=config).generate(request).prompt
        elif workflow == "minimax":
            result = MiniMaxService(config, lambda: None).run(request,
                {"user_request": case["request"], "planning_mode": args.planning,
                 "duration_seconds": 10, "references": case.get("references", []), "director_preset": args.director}, lambda _message: None)
            row["prompt"] = result["prompt"]
        else:
            row["evaluation_scope"] = "pipeline"
            data = {**default_dataset_draft(), "subject": case["request"], "trigger": "eval_subject",
                    "trigger_type": case.get("dataset_type", "Character"),
                    "amount": 1, "target": args.target, "length": length, "director_preset": args.director,
                     "visual_style": args.style, "creativity": args.creativity,
                     "constraints": rules + "\n" + identity_rules}
            data.update(source_mode="guided", inputs=case["request"].replace("\n", " "))
            data = approve_dataset(config, request, data)
            result = DatasetService(config, lambda: None).run(request, data, lambda _message: None, lambda _partial: None)
            row.update(scene_plan=result["scene_plan"], dataset_type=data["trigger_type"],
                       completed_results=result["completed"], prompts=result["prompts"],
                       prompt=result["prompts"][0]["prompt"] if result["prompts"] else "")
            if not result["completed"]:
                row.update(error="Dataset pipeline produced no valid prompt.", completion_state="validation_failed")
        row.setdefault("completion_state", "completed")
    except Exception as exc:
        row.update(error=str(exc), completion_state=getattr(exc, "completion_state", "provider_error"),
                   partial_text=getattr(exc, "partial_text", ""))
    row.update(latency_seconds=time.perf_counter() - start,
               finish_reason=calls[-1].get("finish_reason") if calls else None)
    return row


def approve_dataset(config, request, data):
    from goated_prompter.dataset_understanding import DatasetUnderstandingService
    from goated_prompter.dataset_intent import DatasetIntentTickets
    brief = DatasetUnderstandingService(config, lambda: None).run(request, data, print)
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    tickets = DatasetIntentTickets()
    ticket = tickets.register(data, brief)
    if not ticket["confirmation_token"] or input("Approve this interpretation? Type yes: ").strip() != "yes":
        raise ValueError("Dataset evaluation stopped before downstream generation.")
    return {**data, "_confirmed_intent": tickets.approve(ticket["confirmation_token"], data)}


def novelty_cases(spec, config, args):
    from goated_prompter.core import GoatedPrompterRequest
    from goated_prompter.dataset import DatasetService, default_dataset_draft
    from goated_prompter.dataset_idea_history import RecentIdeaHistory
    history = RecentIdeaHistory() if args.history == "on" else None
    rows = []
    for run in range(1, spec["runs"] + 1):
        calls = []
        data = {**default_dataset_draft(), "subject": spec["concept"], "amount": spec["amount"],
                 "variety": args.variety, "trigger": "eval_subject",
                "target": args.target, "length": args.length, "director_preset": args.director,
                "visual_style": args.style, "creativity": args.creativity}
        start = time.perf_counter()
        row = {"sample_id": f"novelty:{spec['id']}|dataset|{run}", "workflow": "dataset",
               "case_id": spec["id"], "concept": spec["concept"], "run": run,
               "anchors": {}, "calls": calls, "target": args.target, "output_kind": "ideas",
               "dataset_type": data["trigger_type"], "history": args.history}
        try:
            effective = {**config, "_activity_callback": lambda event: capture(calls, event)}
            request = GoatedPrompterRequest(idea=spec["concept"])
            data = approve_dataset(effective, request, data)
            result = DatasetService(effective, lambda: None, idea_history=history).run(request,
                    data, lambda _message: None, lambda _partial: None, scenes_only=True)
            row.update(ideas=[item["idea"] for item in result["scene_plan"]], scene_plan=result["scene_plan"],
                       completion_state="completed")
        except Exception as exc:
            row.update(error=str(exc), completion_state=getattr(exc, "completion_state", "provider_error"))
        row["latency_seconds"] = time.perf_counter() - start
        rows.append(row)
        if row.get("error"):
            break
    return rows


def load_replay(path):
    """Load evaluation runs, excluding raw supporting fixtures in directories."""
    directory = path.is_dir()
    paths = sorted(path.glob("*.json")) if directory else [path]
    runs, skipped = [], []
    for source in paths:
        run = json.loads(source.read_text(encoding="utf-8"))
        records = run.get("records") if isinstance(run, dict) else None
        # Historical raw supporting responses are not workflow runs;
        # they must not be reported as workflow samples or invented successes.
        if directory and isinstance(run, dict):
            if records is None and "run_id" not in run:
                skipped.append(source.name)
                continue
            if isinstance(records, list) and records and all(
                isinstance(row, dict) and "sample_id" not in row and "workflow" not in row
                for row in records
            ):
                skipped.append(source.name)
                continue
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or not run["run_id"]:
            raise ValueError(f"{source.name}: evaluation run requires a nonempty run_id")
        if not isinstance(records, list) or any(
            not isinstance(row, dict) or not row.get("sample_id") or
            row.get("workflow") not in {"builder", "dataset", "minimax"}
            for row in records
        ):
            raise ValueError(f"{source.name}: evaluation records require sample_id and workflow")
        runs.append(run)
    if not runs:
        raise ValueError("No evaluation runs found in replay input")
    if not directory:
        return runs[0]
    return {"run_id": "frozen-regression-replay", "sources": [run["run_id"] for run in runs],
            "skipped_supporting_fixtures": skipped,
            "records": [row for run in runs for row in run["records"]]}


def run_metadata(config, corpus_digest):
    code = hashlib.sha256()
    source_root = ROOT / "goated_prompter"
    for path in sorted(source_root.rglob("*.py")):
        code.update(str(path.relative_to(source_root)).replace("\\", "/").encode())
        code.update(path.read_bytes())
    return {"run_id": datetime.now(timezone.utc).isoformat(),
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "code_digest": code.hexdigest(), "corpus_digest": corpus_digest,
            "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
            "engine": {key: config.get("openai_compatible", {}).get(key) for key in ("model", "context_size")}}


def main(argv=None, gpu=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workflow", choices=["builder", "dataset", "minimax"])
    parser.add_argument("--case", action="append")
    parser.add_argument("--target", default="Generic")
    parser.add_argument("--length", default="Detailed")
    parser.add_argument("--director", default="general_director")
    parser.add_argument("--style", default="Photorealistic")
    parser.add_argument("--creativity", default="Balanced")
    parser.add_argument("--planning", choices=["Direct", "Auto", "Always"], default="Direct")
    parser.add_argument("--variety", choices=["Focused", "Balanced", "Wide"], default="Balanced")
    parser.add_argument("--novelty", action="store_true")
    parser.add_argument("--history", choices=["on", "off"], default="on")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--seed", type=int, help="Seed fixed-case selection/order, not model output")
    parser.add_argument("--limit", type=int, default=1 if gpu else None, help="Maximum selected cases")
    parser.add_argument("--task-key", help="Task key for isolated real-engine execution")
    parser.add_argument("--max-runs", type=int, help="Approved maximum workflow runs, not model calls")
    args = parser.parse_args(argv)
    if gpu and (args.replay or args.novelty):
        parser.error("Use tests.eval.runner for replay or novelty evaluation.")
    if gpu and not args.workflow:
        parser.error("Real-engine execution requires one explicit --workflow.")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    try:
        cases = select_cases(corpus["cases"], args.case, args.workflow, args.seed, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({"cases": cases, "novelty": [] if gpu else corpus["novelty"],
                          "scenario_seed": args.seed, "inference": False}, indent=2))
        return
    scratch = None
    if gpu:
        if not args.allow_live or not args.config or not args.task_key or args.max_runs is None:
            parser.error("Real-engine execution requires --allow-live, --config, --task-key and --max-runs after owner approval.")
        if args.max_runs < 1 or len(cases) * args.repeats > args.max_runs:
            parser.error("Selected workflow runs exceed --max-runs; narrow --case/--limit/--repeats.")
        try:
            results, scratch = task_paths(args.task_key, "gpu")
            args.output = new_output(args.output or results / "results.json", args.task_key, "gpu")
            if args.template:
                args.template = new_output(args.template, args.task_key, "gpu")
                if args.template == args.output:
                    raise ValueError("Result and annotation outputs must be different paths.")
        except ValueError as exc:
            parser.error(str(exc))
    if args.replay:
        try:
            result = load_replay(args.replay)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        if not args.allow_live or not args.config or not args.output:
            parser.error("Live evaluation requires --allow-live, --config and --output; notify the GPU owner first.")
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if config.get("backend") != "openai_compatible":
            parser.error("Use an explicitly configured existing OpenAI-compatible endpoint; no process ownership changes.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result = {**run_metadata(config, hashlib.sha256(args.corpus.read_bytes()).hexdigest()),
                   "scenario_seed": args.seed, "selected_case_ids": [case["id"] for case in cases], "records": []}
        if gpu:
            try:
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(json.dumps(result, ensure_ascii=False, indent=2))
            except FileExistsError:
                parser.error("Output appeared during setup; retained evidence was not overwritten.")
        with synthetic_storage(scratch) if gpu else nullcontext():
            for trial in range(1, args.repeats + 1):
                for case in cases:
                    workflows = [args.workflow] if args.workflow else case["workflows"]
                    for workflow in (workflows if trial % 2 else list(reversed(workflows))):
                        row = live_case(case, workflow, config, args, run=trial)
                        result["records"].append(row)
                        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        if gpu:
                            print(json.dumps(row, ensure_ascii=False, indent=2))
                            if row.get("error"):
                                return 1
                            if len(result["records"]) < len(cases) * args.repeats:
                                if input("Inspect this result before continuing. Type yes: ").strip() != "yes":
                                    return
                        elif row.get("error") and "Could not reach" in row["error"]:
                            return
            if args.novelty:
                for spec in corpus["novelty"]:
                    result["records"].extend(novelty_cases(spec, config, args))
    if args.template:
        args.template.parent.mkdir(parents=True, exist_ok=True)
        with args.template.open("x" if gpu else "w", encoding="utf-8") as template:
            template.write(json.dumps(annotation_template(result["records"]), indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{result['run_id']}: {len(result['records'])} samples")


if __name__ == "__main__":
    raise SystemExit(main())
