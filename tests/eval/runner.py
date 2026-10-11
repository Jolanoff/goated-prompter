"""Reusable frozen/live workflow evaluation. Live inference is explicit and opt-in."""

import argparse
import json
import hashlib
from pathlib import Path
import time
from contextlib import nullcontext

from .metrics import annotation_template
from tests.gpu.common import capture, run_case, run_metadata  # noqa: F401  (existing import path)
from tests.gpu.cases import fixture_digest, random_cases
from tests.gpu.workflows.dataset import approve_dataset
from tests.support.artifacts import new_output, task_paths
from tests.support.safety import synthetic_storage
from tests.support.scenarios import select_cases

CORPUS = Path(__file__).parent / "cases" / "corpus.json"


def live_case(case, workflow, config, args, run=1):
    # approve_dataset is resolved here so callers and tests can replace it.
    return run_case(case, workflow, config, args, run, approve=approve_dataset)


def novelty_cases(spec, config, args):
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.features.dataset.service import DatasetService, default_dataset_draft
    from goated_prompter.features.dataset.idea_history import RecentIdeaHistory
    history = RecentIdeaHistory() if args.history == "on" else None
    rows = []
    for run in range(1, spec["runs"] + 1):
        calls = []
        data = {**default_dataset_draft(), "subject": spec["concept"], "amount": spec["amount"],
                 "trigger": "eval_subject",
                "target": args.target, "length": args.length, "director_preset": args.director,
                 "creativity": args.creativity}
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
    parser.add_argument("--creativity", default="Balanced")
    parser.add_argument("--planning", choices=["Direct", "Auto", "Always"], default="Direct")
    parser.add_argument("--novelty", action="store_true")
    parser.add_argument("--history", choices=["on", "off"], default="on")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--seed", type=int, help="Seed fixed-case selection/order or random cases, not model output")
    parser.add_argument("--random", type=int, metavar="N",
                        help="Generate N seeded random cases for --workflow instead of fixed corpus cases")
    parser.add_argument("--limit", type=int, default=1 if gpu else None, help="Maximum selected cases")
    parser.add_argument("--task-key", help="Task key for isolated real-engine execution")
    parser.add_argument("--max-runs", type=int, help="Approved maximum workflow runs, not model calls")
    args = parser.parse_args(argv)
    if gpu and (args.replay or args.novelty):
        parser.error("Use tests.eval.runner for replay or novelty evaluation.")
    if gpu and not args.workflow:
        parser.error("Real-engine execution requires one explicit --workflow.")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    random_selection = None
    try:
        if args.random is not None:
            if not args.workflow or args.case or args.replay or args.novelty:
                raise ValueError("--random needs one --workflow and no --case, --replay or --novelty.")
            cases = random_cases(args.workflow, args.seed, args.random)
            random_selection = {"workflow": args.workflow, "seed": args.seed, "count": args.random,
                                "fixture_digest": fixture_digest(args.workflow)}
        else:
            cases = select_cases(corpus["cases"], args.case, args.workflow, args.seed, args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({"cases": cases, "novelty": [] if gpu or random_selection else corpus["novelty"],
                          "scenario_seed": args.seed, "random_cases": random_selection, "inference": False}, indent=2))
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
                   "scenario_seed": args.seed, "selected_case_ids": [case["id"] for case in cases],
                   **({"random_cases": {**random_selection, "cases": cases}} if random_selection else {}),
                   "records": []}
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
