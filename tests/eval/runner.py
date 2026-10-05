"""Reusable frozen/live workflow evaluation. Live inference is explicit and opt-in."""

import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import time

from .metrics import annotation_template

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
    elif calls and kind in {"semantic_review", "validation"}:
        calls[-1].setdefault("validation_events", []).append(event)


def live_case(case, workflow, config, args, run=1):
    from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.dataset import DatasetService, default_dataset_draft
    from goated_prompter.prompting.dataset import dataset_instruction, STYLE_RULES
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
    if workflow != "minimax":
        common_rules += "\nInclude the exact subject identifier eval_subject. Do not invent stable identity traits or gender; compatible temporary clothing and scene detail are allowed."
    request = GoatedPrompterRequest(idea=source, target_model=args.target, prompt_length=length,
        director_preset=args.director, creativity=args.creativity, planning_mode=args.planning,
        custom_instructions=common_rules)
    sample_id = "|".join(str(value) for value in (case["id"], workflow, args.target, length, args.director,
                                               args.style, args.creativity, args.planning, run))
    row = {"sample_id": sample_id, "case_id": case["id"], "workflow": workflow,
           "run": run, "request": case["request"], "anchors": case["anchors"], "rules": rules,
           "target": "MiniMax H3" if workflow == "minimax" else args.target, "length": length, "director": args.director,
           "style": args.style, "creativity": args.creativity, "planning": args.planning,
           "effective_request": source, "calls": calls}
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
            data = {**default_dataset_draft(), "subject": case["request"], "trigger": "eval_subject",
                    "trigger_type": case.get("dataset_type", "Character"),
                    "amount": 1, "target": args.target, "length": length, "director_preset": args.director,
                    "visual_style": args.style, "creativity": args.creativity, "constraints": rules}
            plan = {"index": 1, "input": case["request"], "idea": compiled_source.positive_request,
                    "scene": compiled_source.positive_request, "geometry": {}}
            backend = create_backend(config)
            with backend.generation_session() as session:
                instruction = dataset_instruction(request, data, 1, plan_item=plan)
                row["prompt"] = DatasetService(config, lambda: None)._generate(session, instruction, data, 1,
                    lambda _message: None, plan)
        row["completion_state"] = "completed"
    except Exception as exc:
        row.update(error=str(exc), completion_state=getattr(exc, "completion_state", "provider_error"),
                   partial_text=getattr(exc, "partial_text", ""))
    row.update(latency_seconds=time.perf_counter() - start,
               finish_reason=calls[-1].get("finish_reason") if calls else None)
    return row


def novelty_cases(spec, config, args):
    from goated_prompter.core import GoatedPrompterRequest
    from goated_prompter.dataset import DatasetService, default_dataset_draft
    from goated_prompter.dataset_idea_history import RecentIdeaHistory
    history = RecentIdeaHistory() if args.history == "on" else None
    rows = []
    for run in range(1, spec["runs"] + 1):
        calls = []
        data = {**default_dataset_draft(), "subject": spec["concept"], "amount": spec["amount"],
                "variety": args.variety, "trigger": "eval_subject", "planning_mode": "Quality",
                "target": args.target, "length": args.length, "director_preset": args.director,
                "visual_style": args.style, "creativity": args.creativity}
        start = time.perf_counter()
        row = {"sample_id": f"novelty:{spec['id']}|dataset|{run}", "workflow": "dataset",
               "case_id": spec["id"], "concept": spec["concept"], "run": run,
               "anchors": {}, "calls": calls, "target": args.target, "output_kind": "ideas",
               "dataset_type": data["trigger_type"], "history": args.history}
        try:
            result = DatasetService({**config, "_activity_callback": lambda event: capture(calls, event)},
                lambda: None, idea_history=history).run(GoatedPrompterRequest(idea=spec["concept"]),
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


def main():
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
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    cases = [case for case in corpus["cases"] if not args.case or case["id"] in args.case]
    if args.dry_run:
        print(json.dumps({"cases": cases, "novelty": corpus["novelty"], "inference": False}, indent=2))
        return
    if args.replay:
        if args.replay.is_dir():
            runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.replay.glob("*.json"))]
            result = {"run_id": "frozen-regression-replay", "sources": [run["run_id"] for run in runs],
                      "records": [row for run in runs for row in run["records"]]}
        else:
            result = json.loads(args.replay.read_text(encoding="utf-8"))
    else:
        if not args.allow_live or not args.config or not args.output:
            parser.error("Live evaluation requires --allow-live, --config and --output; notify the GPU owner first.")
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        if config.get("backend") != "openai_compatible":
            parser.error("Use an explicitly configured existing OpenAI-compatible endpoint; no process ownership changes.")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        source_root = Path(__file__).resolve().parents[2] / "goated_prompter"
        code = hashlib.sha256()
        for path in sorted(source_root.rglob("*.py")):
            code.update(str(path.relative_to(source_root)).replace("\\", "/").encode())
            code.update(path.read_bytes())
        result = {"run_id": datetime.now(timezone.utc).isoformat(), "revision": revision,
                  "code_digest": code.hexdigest(), "corpus_digest": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
                  "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
                  "engine": {key: config.get("openai_compatible", {}).get(key) for key in ("model", "context_size")}, "records": []}
        for trial in range(1, args.repeats + 1):
            for case in cases:
                for workflow in (case["workflows"] if trial % 2 else list(reversed(case["workflows"]))):
                    if args.workflow and args.workflow != workflow:
                        continue
                    row = live_case(case, workflow, config, args, run=trial)
                    result["records"].append(row)
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    if row.get("error") and "Could not reach" in row["error"]:
                        return
        if args.novelty:
            for spec in corpus["novelty"]:
                result["records"].extend(novelty_cases(spec, config, args))
    if args.template:
        args.template.write_text(json.dumps(annotation_template(result["records"]), indent=2), encoding="utf-8")
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{result['run_id']}: {len(result['records'])} samples")


if __name__ == "__main__":
    main()
