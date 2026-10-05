"""Compact JSON and Markdown quality reports with review coverage made explicit."""

import argparse
import json
from pathlib import Path
from .metrics import summarize


def markdown(report):
    lines = [f"# Evaluation {report['run_id']}", "", "Unreviewed semantic metrics are unknown, not passes.", ""]
    for workflow, result in report["workflows"].items():
        lines += [f"## {workflow.title()}", f"Samples: {result['samples']}; reviewed: {result['reviewed']}"]
        def metrics(fields):
            return "; ".join(f"{field}: {result['averages'].get(field):.3f}" if result["averages"].get(field) is not None
                             else f"{field}: not reviewed/measured" for field in fields)
        lines += ["- " + metrics(("format_valid", "first_pass_valid", "repair_frequency")),
                  "- " + metrics(("transport_success", "repair_introduced_regression")),
                  "- " + metrics(("scene_fidelity", "action_fidelity", "pose_fidelity", "constraint_fidelity")),
                  "- " + metrics(("prompt_words", "useful_detail_density", "semantic_repetition", "latency_seconds")),
                  "- " + metrics(("temporal_fidelity", "dialogue_reference_fidelity") if workflow == "minimax" else
                                  ("domain_action_relevance", "generic_pose", "pose_simplified"))]
        lines += [f"- forbidden content: {result['forbidden_content_violations']}",
                  f"- exclusion-language leakage: {result['negative_language_leakage']}",
                   f"- failures: {', '.join(result['failures']) or 'none detected (review coverage above)'}", ""]
        lines += ["Repair outcomes: " + json.dumps(result.get("repair_outcomes", {})),
                  "Model semantic statuses (separate from explicit annotations): " + json.dumps(result.get("model_semantic_statuses", {})), ""]
    lines += ["## Novelty", "```json", json.dumps(report["novelty"], indent=2), "```"]
    pairs = report.get("length_coverage_pairs", [])
    lines += ["", "## Useful-detail length scaling", f"Matched explicitly reviewed pairs: {len(pairs)}"]
    for pair in pairs:
        lines.append(f"- {pair['detailed']} -> {pair['maximum']}: {len(pair['new_useful_facts'])} new facts, "
                     f"{len(pair['lost_useful_facts'])} lost facts, net gain {pair['net_useful_fact_gain']}; "
                     f"fidelity valid: {pair['fidelity_valid']}; useful coverage increased: {pair['useful_coverage_increased']}; "
                     f"Detailed coverage saturated: {pair['source_saturated']}")
    return "\n".join(lines) + "\n"


def regressions(report, baseline):
    """Comparable reviewed samples only; longer prose cannot offset lost fidelity."""
    previous = {row["sample_id"]: row for row in baseline["samples"]}
    failures = []
    missing = previous.keys() - {row["sample_id"] for row in report["samples"]}
    failures.extend(f"{sample_id}: baseline sample missing from current evaluation" for sample_id in sorted(missing))
    if report.get("engine") != baseline.get("engine"):
        failures.append("Engine metadata differs; do not pool this as a matched regression comparison.")
    higher = ("scene_fidelity", "action_fidelity", "pose_fidelity", "constraint_fidelity", "target_usability", "temporal_fidelity", "dialogue_reference_fidelity",
              "accepted", "format_valid", "first_pass_valid", "useful_detail_facts")
    lower = ("forbidden_content_violations", "negative_language_leakage", "semantic_repetition", "pose_simplified", "generic_pose")
    for row in report["samples"]:
        old = previous.get(row["sample_id"])
        if old is None or not row.get("review_complete") or not old.get("review_complete"):
            failures.append(f"{row['sample_id']}: missing comparable complete semantic review")
            continue
        for field in higher + lower:
            value, prior = row.get(field), old.get(field)
            if value is None or prior is None:
                continue
            if field in higher and value < prior or field in lower and value > prior:
                failures.append(f"{row['sample_id']}: {field} regressed ({prior} -> {value})")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--require-review", action="store_true")
    args = parser.parse_args()
    run = json.loads(args.artifacts.read_text(encoding="utf-8"))
    labels = json.loads(args.annotations.read_text(encoding="utf-8")) if args.annotations else []
    report = {"run_id": run["run_id"], **summarize(run["records"], labels)}
    for key in ("revision", "code_digest", "corpus_digest", "dirty", "engine", "sources"):
        if key in run:
            report[key] = run[key]
    report["regression_failures"] = regressions(report, json.loads(args.baseline.read_text(encoding="utf-8"))) if args.baseline else []
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    if report["regression_failures"] or args.require_review and not report["semantic_review_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
