"""Opt-in real-engine evaluation. Fixtures/hints are NEVER imported by production.

Run from the root with --help. Outputs contain only aggregate metrics by default;
--artifacts explicitly opts into saving generated prompts for human annotation.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.dataset_idea_history import RecentIdeaHistory
from goated_prompter.dataset_quality import analyze_idea_diversity
from goated_prompter.dataset_constraints import compile_constraints, constraint_issues, positive_descriptions
from goated_prompter.backends.factory import create_backend
from goated_prompter.scene_planner import ScenePlanner
from goated_prompter.dataset_assignments import dataset_assignments


def rate(values):
    return round(sum(values) / len(values), 4) if values else None


def summarize(records, annotations=()):
    labels = {row["id"]: row for row in annotations}
    exact_within, exact_cross, lexical = [], [], []
    seen = {}
    for run in records:
        previous = seen.setdefault(run["concept"], set())
        ideas = [" ".join(row.get("idea", "").casefold().split()) for row in run["rows"] if row.get("idea")]
        if ideas:
            exact_within.extend([len(ideas) - len(set(ideas))] + [0] * (len(ideas) - 1))
        if previous:
            exact_cross.extend(idea in previous for idea in ideas)
        previous.update(ideas)
        diversity = analyze_idea_diversity({"subject": run["concept"], "source_mode": "random"}, run["rows"])
        lexical.extend(bool(row["issues"]) for row in diversity["ideas"])
    all_rows = [row for run in records for row in run["rows"]]
    judged = [labels[row["evaluation_id"]] for row in all_rows if row["evaluation_id"] in labels]
    repeats, event_history = [], {}
    within_semantic = []
    for run in records:
        previous = event_history.setdefault(run["concept"], set())
        events = [labels[row["evaluation_id"]].get("event_id") for row in run["rows"] if row["evaluation_id"] in labels]
        events = [event for event in events if event]
        if previous:
            repeats.extend(event in previous for event in events)
        if events:
            within_semantic.extend([len(events) - len(set(events))] + [0] * (len(events) - 1))
        previous.update(events)
    metrics = {
        "evaluated_items": len(all_rows),
        "generated_prompt_count": sum(bool(row.get("prompt")) for row in all_rows),
        "idea_duplicate_rate_exact": rate(exact_within),
        "cross_run_repeated_idea_rate_exact": rate(exact_cross),
        "within_run_repeat_hint_rate_lexical": rate(lexical),
        "idea_duplicate_rate_semantic": rate(within_semantic),
        "cross_run_repeated_idea_rate_semantic": rate(repeats),
        "scene_failure_rate": rate([row.get("scene_status") == "failed" for row in all_rows if "scene" in row]),
        "scene_repair_calls": sum(run["scene_repair_calls"] for run in records),
        "scene_repair_frequency": sum(run["scene_repair_calls"] for run in records) / max(1, sum("scene" in row for row in all_rows)),
        "forbidden_content_violation_rate_lexical": rate([row["forbidden_violation"] for row in all_rows if row.get("prompt")]),
        "negative_language_leakage_rate_lexical": rate([row["negative_leakage"] for row in all_rows if row.get("prompt")]),
        "domain_action_relevance_hint": rate([row["domain_hint"] for row in all_rows if "domain_hint" in row]),
        "generic_pose_rate_hint": rate([row["generic_hint"] for row in all_rows if "generic_hint" in row]),
        "pose_mechanics_hint": rate([row["mechanics_hint"] for row in all_rows if "mechanics_hint" in row]),
        "annotation_coverage": len(judged) / max(1, len(all_rows)),
    }
    for key in ("domain_action_relevance", "advanced_pose_fidelity", "final_prompt_scene_fidelity",
                "required_fact_fidelity", "forbidden_content", "negative_language_leakage"):
        metrics[key] = rate([label[key] for label in judged if isinstance(label.get(key), (int, float))])
    metrics["generic_pose_rate"] = rate([label["generic_pose"] for label in judged if "generic_pose" in label])
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.json")
    parser.add_argument("--group", choices=["all", "novelty", "domains", "poses", "constraints", "interactions"], default="all")
    parser.add_argument("--mode", choices=["Fast", "Quality"], default="Quality")
    parser.add_argument("--case", action="append", help="Run selected corpus case IDs (repeatable)")
    parser.add_argument("--amount", type=int, help="Probe batch size for non-novelty cases; novelty always uses 5 x 10")
    parser.add_argument("--artifacts", type=Path, help="Explicitly save content-bearing JSON for human annotation")
    parser.add_argument("--annotations", type=Path, help="JSON array of {id,event_id,rubric scores...}")
    parser.add_argument("--score", type=Path, help="Score saved artifacts instead of generating")
    parser.add_argument("--without-history", action="store_true", help="Same-engine control for cross-run novelty")
    parser.add_argument("--dry-run", action="store_true", help="List cases/call budget without loading a model")
    args = parser.parse_args()
    annotations = json.loads(args.annotations.read_text(encoding="utf-8")) if args.annotations else []
    if args.score:
        print(json.dumps(summarize(json.loads(args.score.read_text(encoding="utf-8")), annotations), indent=2))
        return
    corpus = json.loads(Path(__file__).with_name("dataset_semantics.json").read_text(encoding="utf-8"))
    groups = ["novelty", "domains", "poses", "constraints", "interactions"] if args.group == "all" else [args.group]
    if args.amount is not None and not 1 <= args.amount <= 25:
        parser.error("--amount must be between 1 and 25.")
    available = {case["id"] for group in groups for case in corpus[group]}
    if args.case and set(args.case) - available:
        parser.error("Unknown case IDs for selected group: " + ", ".join(sorted(set(args.case) - available)))
    if args.dry_run:
        print(json.dumps({group: {"cases": len(corpus[group]), "runs": sum(row.get("runs", 1) for row in corpus[group])} for group in groups}, indent=2))
        return
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("backend") in {"mock", "debug"}:
        parser.error("Real evaluation refuses mock backends. Use --dry-run for corpus inspection.")
    history = None if args.without_history else RecentIdeaHistory()
    records = []
    for group in groups:
        for case in corpus[group]:
            if args.case and case["id"] not in args.case:
                continue
            concept = case.get("concept", "A performer demonstrating the supplied physical arrangement" if group == "poses" else
                               "People performing the specified shared interaction" if group == "interactions" else
                               "A recurring woman carrying out meaningful everyday activities")
            for number in range(case.get("runs", 1)):
                data = {**default_dataset_draft(), "subject": concept, "amount": case.get("amount", args.amount or (10 if group == "domains" else 3)),
                        "planning_mode": args.mode, "trigger_type": case.get("type", "Multiple characters" if group == "interactions" else "Character"),
                        "trigger": "eval_subject", "constraints": case.get("rules", "")}
                if case.get("input"):
                    data.update(source_mode="guided", inputs=case["input"])
                counts = Counter()
                def activity(event):
                    if event.get("type") == "request":
                        counts[event.get("stage", "")] += 1
                # Observe the actual instruction stages, not progress wording.
                config_run = {**config, "_activity_callback": activity}
                if group == "novelty":
                    backend = create_backend(config_run)
                    with backend.generation_session() as session:
                        planner = ScenePlanner(lambda: None, history)
                        if args.mode == "Quality":
                            rows = planner.plan_ideas(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _message: None)
                        else:
                            rows = planner.plan_batch(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _message: None)
                    prompts = []
                else:
                    local = config.get("local_llama_cpp", {})
                    result = DatasetService(config_run, lambda: None, history).run(
                        GoatedPrompterRequest(idea=concept, prompt_model="Custom", director_keep_model_loaded=True,
                            director_llama_server=local.get("llama_server", ""),
                            director_context_size=local.get("context_size", 32768),
                            director_model_path=local.get("model_path", ""), director_mmproj_path=local.get("mmproj_path", "")),
                        data, lambda _message: None, lambda _result: None)
                    rows, prompts = result["scene_plan"], result["prompts"]
                by_index = {row["index"]: row for row in prompts}
                scored = []
                compiled = compile_constraints(data["constraints"])
                for row in rows:
                    row = {**row, **by_index.get(row["index"], {})}
                    row["evaluation_id"] = f"{args.mode}:{group}:{case['id']}:{number + 1}:{row['index']}"
                    text = row.get("idea", "").casefold()
                    if case.get("hints"):
                        row["domain_hint"] = any(word in text for word in case["hints"])
                        row["generic_hint"] = not row["domain_hint"] and bool(re.search(r"\b(?:stand\w*|sit\w*|walk\w*|smil\w*|portrait|pos\w*)\b", text))
                    if case.get("mechanics"):
                        detail = (row.get("scene", "") + " " + row.get("geometry", {}).get("pose_detail", "")).casefold()
                        row["mechanics_hint"] = sum(word in detail for word in case["mechanics"]) / len(case["mechanics"])
                    problems = [issue for text in positive_descriptions(row["prompt"], data["target"])
                                for issue in constraint_issues(text, compiled)] if row.get("prompt") else []
                    row["forbidden_violation"] = any(issue["code"] == "forbidden_content" for issue in problems)
                    row["negative_leakage"] = any(issue["code"] == "constraint_negative_leakage" for issue in problems)
                    scored.append(row)
                records.append({"concept": concept, "case": case["id"], "run": number + 1, "rows": scored,
                                "scene_repair_calls": sum(value for stage, value in counts.items() if "scene_composer:repair" in stage)})
                print(f"Completed {args.mode}/{group}/{case['id']}/{number + 1}", file=sys.stderr)
                if args.artifacts:
                    args.artifacts.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"aggregate": summarize(records, annotations), "by_group": {
        group: summarize([run for run in records if run["rows"] and run["rows"][0]["evaluation_id"].split(":")[1] == group], annotations)
        for group in groups if any(run["rows"] and run["rows"][0]["evaluation_id"].split(":")[1] == group for run in records)}}, indent=2))
    if args.artifacts:
        args.artifacts.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    finally:
        # The evaluation owns its local process; never leave it loaded on failure.
        from goated_prompter.backends.llama_cpp_process import get_process_manager
        get_process_manager().request_unload()
