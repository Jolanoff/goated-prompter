"""Compare a baseline and a candidate real-engine result file.

Both runs must use the same engine, samples (case, workflow and settings encode
the sample ID) and random-case seed. Deterministic checks are compared per
sample. Semantic quality is reported only from independent reviews; otherwise it
is "not_evaluated". Length is reported as a description, never as quality.

  python -m tests.gpu.compare BASELINE.json CANDIDATE.json [--baseline-review R --candidate-review R]
                              [--task-key KEY --output quality-artifacts/tasks/KEY/gpu/comparison.json]
"""

import argparse
import json
from pathlib import Path
import sys

from tests.eval.metrics import measure
from tests.gpu.common import token_usage
from tests.support.artifacts import new_output

# Higher is better for these booleans; a True -> False change is a regression.
BOOLEAN_CHECKS = ("accepted", "format_valid", "trigger_fidelity")
# Lower is better for these counts.
COUNT_CHECKS = ("forbidden_content_violations", "negative_language_leakage", "repair_calls", "transport_retry_calls")
DESCRIPTIVE = ("completion_state", "model_calls", "latency_seconds", "prompt_words")
FIDELITY = ("scene_fidelity", "action_fidelity", "pose_fidelity", "constraint_fidelity")


class ComparisonError(ValueError):
    pass


def _records(run):
    rows = {}
    for row in run.get("records", []):
        if row["sample_id"] in rows:
            raise ComparisonError(f"Duplicate sample {row['sample_id']} in one run.")
        rows[row["sample_id"]] = row
    return rows


def _reviews(path):
    if path is None:
        return {}
    return {row["sample_id"]: row for row in json.loads(Path(path).read_text(encoding="utf-8"))}


def _random_key(run):
    selection = run.get("random_cases")
    return None if not selection else {key: selection.get(key) for key in ("workflow", "seed", "count", "fixture_digest")}


def matched(baseline, candidate):
    """Refuse comparisons that would not hold model, inputs and settings constant."""
    if baseline.get("engine") != candidate.get("engine"):
        raise ComparisonError("Engine metadata differs; rerun both sides on the same model and context.")
    if baseline.get("scenario_seed") != candidate.get("scenario_seed") or _random_key(baseline) != _random_key(candidate):
        raise ComparisonError("Case seed or random-case fixture differs; rerun with the same --seed and fixtures.")
    if baseline.get("corpus_digest") != candidate.get("corpus_digest") and not _random_key(baseline):
        raise ComparisonError("Fixed corpus differs between runs.")
    left, right = _records(baseline), _records(candidate)
    if set(left) != set(right):
        missing = sorted(set(left) ^ set(right))
        raise ComparisonError("Samples differ between runs: " + ", ".join(missing))
    for sample_id, row in left.items():
        if row.get("request") != right[sample_id].get("request"):
            raise ComparisonError(f"Input differs for {sample_id}.")
    return left, right


def _check_change(name, before, after):
    if before == after:
        return "unchanged"
    if before is None or after is None:
        return "not_comparable"
    if name in BOOLEAN_CHECKS:
        return "improved" if after else "regressed"
    return "improved" if after < before else "regressed"


def _semantic(measured):
    if not measured.get("independent_review") or not measured.get("review_complete"):
        return None
    return {key: measured.get(key) for key in FIDELITY}


def compare(baseline, candidate, baseline_reviews=None, candidate_reviews=None):
    left, right = matched(baseline, candidate)
    baseline_reviews, candidate_reviews = baseline_reviews or {}, candidate_reviews or {}
    samples, totals = [], {"regressed": 0, "improved": 0, "unchanged": 0, "not_comparable": 0}
    semantic_samples = 0
    for sample_id in sorted(left):
        before = measure(left[sample_id], baseline_reviews.get(sample_id))
        after = measure(right[sample_id], candidate_reviews.get(sample_id))
        checks = {}
        for name in (*BOOLEAN_CHECKS, *COUNT_CHECKS):
            change = _check_change(name, before.get(name), after.get(name))
            totals[change] += 1
            checks[name] = {"baseline": before.get(name), "candidate": after.get(name), "change": change}
        semantic_before, semantic_after = _semantic(before), _semantic(after)
        if semantic_before and semantic_after:
            semantic_samples += 1
            semantic = {"baseline": semantic_before, "candidate": semantic_after}
        else:
            semantic = "not_evaluated"
        samples.append({
            "sample_id": sample_id, "checks": checks, "semantic_quality": semantic,
            "descriptive": {name: {"baseline": before.get(name), "candidate": after.get(name)} for name in DESCRIPTIVE},
            "token_usage": {"baseline": token_usage(left[sample_id].get("calls")),
                            "candidate": token_usage(right[sample_id].get("calls"))},
            "errors": {"baseline": left[sample_id].get("error"), "candidate": right[sample_id].get("error")},
            "prompts": {"baseline": left[sample_id].get("prompt", ""), "candidate": right[sample_id].get("prompt", "")},
        })
    return {
        "baseline": {key: baseline.get(key) for key in ("run_id", "revision", "code_digest", "dirty")},
        "candidate": {key: candidate.get(key) for key in ("run_id", "revision", "code_digest", "dirty")},
        "engine": baseline.get("engine"), "scenario_seed": baseline.get("scenario_seed"),
        "random_cases": _random_key(baseline),
        "same_code": baseline.get("code_digest") == candidate.get("code_digest"),
        "deterministic_checks": totals,
        "semantic_quality": ("not_evaluated" if not semantic_samples else
                             f"independently reviewed for {semantic_samples}/{len(samples)} samples"),
        "samples": samples,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline-review", type=Path)
    parser.add_argument("--candidate-review", type=Path)
    parser.add_argument("--task-key")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if bool(args.output) != bool(args.task_key):
        parser.error("--output requires --task-key (and the reverse).")
    try:
        output = new_output(args.output, args.task_key, "gpu") if args.output else None
        report = compare(json.loads(args.baseline.read_text(encoding="utf-8")),
                         json.loads(args.candidate.read_text(encoding="utf-8")),
                         _reviews(args.baseline_review), _reviews(args.candidate_review))
    except ValueError as exc:
        parser.error(str(exc))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(text)
    print(json.dumps({key: report[key] for key in ("baseline", "candidate", "same_code", "deterministic_checks",
                                                   "semantic_quality")}, indent=2))
    return 1 if report["deterministic_checks"]["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main())
