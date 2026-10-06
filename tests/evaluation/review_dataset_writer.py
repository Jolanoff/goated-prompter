"""Score independently annotated writer artifacts, never infer fidelity from length."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

DETAIL_CATEGORIES = ("action", "composition", "environment", "materials", "lighting", "depth", "treatment")
WRITING_CHECKS = ("descriptive_usefulness", "coherence", "target_suitability")


def sample_id(record):
    return f"{record['id']}|{record['condition']}|{record.get('trial', 1)}"


def annotation_template(records):
    return [{"id": sample_id(row), "anchors": {anchor: None for anchor in row["anchors"]},
              "pose_fidelity": None, "constraint_fidelity": None, "identity_drift": None, "filler_or_repetition": None,
              "reviewer": "", "review_kind": "", "writing_review": {key: None for key in WRITING_CHECKS},
              "render_review": {"quality": None, "artifact": "", "settings": {}},
              "useful_details": {category: [] for category in DETAIL_CATEGORIES}, "notes": ""}
            for row in records]


def review_status(values, *, independent):
    if not independent or any(type(value) is not bool for value in values):
        return "unverified"
    return "pass" if all(values) else "fail"


def aggregate_status(statuses):
    if "fail" in statuses:
        return "fail"
    return "pass" if statuses and all(status == "pass" for status in statuses) else "unverified"


def score(records, annotations):
    labels = {row["id"]: row for row in annotations}
    if len(labels) != len(annotations):
        raise ValueError("Duplicate annotation IDs.")
    records_by_id = {sample_id(row): row for row in records}
    if len(records_by_id) != len(records):
        raise ValueError("Duplicate sample IDs.")
    failures, results, lengths, directors = [], [], defaultdict(dict), defaultdict(dict)
    for row in records:
        key = sample_id(row)
        label = labels.get(key)
        if label is None:
            failures.append(f"{key}: missing independent annotation")
            continue
        anchors = label.get("anchors", {})
        if set(anchors) != set(row["anchors"]) or any(type(value) is not bool for value in anchors.values()):
            failures.append(f"{key}: all supplied anchors require explicit true/false review")
            continue
        if any(type(label.get(field)) is not bool for field in ("pose_fidelity", "constraint_fidelity", "identity_drift", "filler_or_repetition")):
            failures.append(f"{key}: incomplete constraint/identity/filler review")
            continue
        details = label.get("useful_details", {})
        if set(details) != set(DETAIL_CATEGORIES) or any(not isinstance(values, list) or
            any(not isinstance(value, str) or not value.strip() for value in values) for values in details.values()):
            failures.append(f"{key}: useful detail facts must be grouped in the documented categories")
            continue
        facts = {value.strip().casefold() for values in details.values() for value in values}
        failed_anchors = [anchor for anchor, valid in anchors.items() if not valid]
        result = {"id": key, "scene_fidelity": not failed_anchors, "failed_anchors": failed_anchors,
                  "pose_fidelity": label["pose_fidelity"], "constraint_fidelity": label["constraint_fidelity"], "identity_drift": label["identity_drift"],
                  "target_valid": row.get("target_valid", False), "filler_or_repetition": label["filler_or_repetition"],
                  "useful_detail_facts": len(facts), "useful_facts_per_100_words": round(100 * len(facts) / max(1, row.get("word_count", 0)), 2),
                  "category_counts": {category: len(set(values)) for category, values in details.items()},
                   "final_text_tokens": row.get("final_text_tokens"), "repair_calls": row.get("repair_calls")}
        independent = (isinstance(label.get("reviewer"), str) and bool(label["reviewer"].strip())
                       and label.get("review_kind") in {"human", "independent"})
        writing = label.get("writing_review", {})
        render = label.get("render_review", {})
        if not isinstance(writing, dict) or any(writing.get(field) is not None and type(writing[field]) is not bool
                                               for field in WRITING_CHECKS):
            raise ValueError("Writing review checks need true, false or null.")
        if not isinstance(render, dict) or (render.get("quality") is not None and type(render["quality"]) is not bool):
            raise ValueError("Render quality review needs true, false or null.")
        render_evidence = (isinstance(render.get("artifact"), str) and bool(render["artifact"].strip())
                           and isinstance(render.get("settings"), dict) and bool(render["settings"]))
        result.update(reviewer=label.get("reviewer", ""), review_kind=label.get("review_kind", ""),
            semantic_correctness_status=review_status((not failed_anchors, label["pose_fidelity"],
                label["constraint_fidelity"], not label["identity_drift"], row.get("target_valid", False)), independent=independent),
            writing_quality_status=review_status((*[writing.get(field) for field in WRITING_CHECKS],
                not label["filler_or_repetition"]), independent=independent),
            image_quality_status=review_status((render.get("quality"),), independent=independent and render_evidence),
            writing_review=writing, render_review=render)
        results.append(result)
        if row["condition"] not in {"dataset", "sampling"}:
            continue  # Controls remain visible but do not define new-writer regression gates.
        if failed_anchors or not label["pose_fidelity"] or not label["constraint_fidelity"] or label["identity_drift"] or not row.get("target_valid"):
            failures.append(f"{key}: fidelity/identity/constraint/format regression")
        if label["filler_or_repetition"]:
            failures.append(f"{key}: richness relies on filler/repetition")
        group = tuple(row.get(field) for field in ("case", "target", "creativity", "director", "condition", "trial"))
        lengths[group][row["length"]] = (facts, details)
        treatment_group = tuple(row.get(field) for field in ("case", "target", "length", "creativity", "condition", "trial"))
        directors[treatment_group][row["director"]] = frozenset(value for category in ("lighting", "composition", "treatment") for value in details[category])
    for group, by_length in lengths.items():
        order = [length for length in ("Short", "Medium", "Detailed", "Maximum Detail") if length in by_length]
        for smaller, larger in zip(order, order[1:]):
            low, high = by_length[smaller][0], by_length[larger][0]
            if len(high) <= len(low) or not high - low:
                failures.append(f"{group}: {larger} is not usefully richer than {smaller} (paraphrases do not count)")
        if "Medium" in by_length and "Maximum Detail" in by_length:
            medium, maximum = by_length["Medium"][0], by_length["Maximum Detail"][0]
            new_categories = sum(bool(set(values) - medium) for values in by_length["Maximum Detail"][1].values())
            if len(maximum - medium) < 2 or new_categories < 2:
                failures.append(f"{group}: Maximum needs new scene-specific information in at least two categories beyond Medium")
    for group, treatments in directors.items():
        if len(treatments) > 1 and len(set(treatments.values())) == 1:
            failures.append(f"{group}: selected Directors had no reviewed lighting/composition/treatment effect")
    reviewed = {row["id"]: row for row in results}
    parity = []
    for row in records:
        if row["condition"] != "dataset":
            continue
        new = reviewed.get(sample_id(row))
        if new is None:
            continue
        for control in ("before", "builder", "sampling"):
            other = reviewed.get(sample_id({**row, "condition": control}))
            if other is not None:
                control_row = records_by_id[sample_id({**row, "condition": control})]
                parity.append({"id": row["id"], "trial": row.get("trial", 1), "control": control,
                               "matched_context": bool(row.get("context_id") and row.get("context_id") == control_row.get("context_id")),
                               "matched_controls": row.get("controls_matched") is True and control_row.get("controls_matched") is True,
                               "dataset_useful_facts": new["useful_detail_facts"], "control_useful_facts": other["useful_detail_facts"],
                               "dataset_category_counts": new["category_counts"], "control_category_counts": other["category_counts"],
                               "dataset_density": new["useful_facts_per_100_words"], "control_density": other["useful_facts_per_100_words"],
                               "dataset_scene_fidelity": new["scene_fidelity"], "control_scene_fidelity": other["scene_fidelity"],
                               "dataset_pose_fidelity": new["pose_fidelity"], "control_pose_fidelity": other["pose_fidelity"],
                               "dataset_identity_drift": new["identity_drift"], "control_identity_drift": other["identity_drift"],
                                "dataset_target_valid": new["target_valid"], "control_target_valid": other["target_valid"],
                                "dataset_writing_quality_status": new["writing_quality_status"],
                                "control_writing_quality_status": other["writing_quality_status"],
                                "dataset_image_quality_status": new["image_quality_status"],
                                "control_image_quality_status": other["image_quality_status"],
                                "matched_render_settings": bool(new["render_review"].get("settings") and
                                    new["render_review"].get("settings") == other["render_review"].get("settings"))})
    candidate_ids = [sample_id(row) for row in records if row["condition"] in {"dataset", "sampling"}]
    statuses = {field: aggregate_status([reviewed.get(key, {}).get(field, "unverified") for key in candidate_ids])
                for field in ("semantic_correctness_status", "writing_quality_status", "image_quality_status")}
    regression_passed = not failures and len(results) == len(records) and bool(records)
    text_quality_passed = regression_passed and statuses["semantic_correctness_status"] == statuses["writing_quality_status"] == "pass"
    return {"reviewed": len(results), "total": len(records), "samples": results, "regression_failures": failures,
             "parity_pairs": parity,
             **statuses, "assessment_conditions": ["dataset", "sampling"],
             "regression_passed": regression_passed, "text_quality_passed": text_quality_passed,
             "passed": text_quality_passed and statuses["image_quality_status"] == "pass"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = json.loads(args.artifacts.read_text(encoding="utf-8"))
    if args.template:
        args.template.write_text(json.dumps(annotation_template(records), indent=2), encoding="utf-8")
        return
    if args.annotations is None:
        parser.error("Supply --annotations or --template; missing review never counts as semantic success.")
    result = score(records, json.loads(args.annotations.read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
