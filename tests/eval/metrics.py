"""Transparent lexical diagnostics plus explicit semantic review, never word-count fidelity."""

from collections import defaultdict
import re

from goated_prompter.dataset_constraints import compile_constraints
from goated_prompter.workflow_output import normalize_workflow_output
from goated_prompter.planning.constraint_validation import output_constraint_issues

FIDELITY = ("scene", "action", "pose", "constraint")
REVIEW_FIELDS = ("semantic_repetition", "domain_action_relevance", "generic_pose", "pose_simplified",
                 "temporal_fidelity", "dialogue_reference_fidelity", "target_usability")


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def annotation_template(records):
    return [{"sample_id": row["sample_id"], "reviewer": "", "anchors": {
        kind: {anchor: None for anchor in row.get("anchors", {}).get(kind, [])} for kind in FIDELITY},
        "useful_details": {}, "semantic_idea_ids": [], **{key: None for key in REVIEW_FIELDS}, "notes": ""}
        for row in records]


def measure(row, review=None):
    prompt = row.get("prompt", "")
    words = len(prompt.split())
    completion = row.get("completion_state", "unknown")
    calls = row.get("calls", [])
    repairs = sum(bool(re.search(r"repair|retry|correction", str(call.get("stage", "")))) for call in calls)
    try:
        if row.get("output_kind") == "ideas":
            from goated_prompter.scene_planner import validate_saved_scene_plan
            validate_saved_scene_plan(row.get("scene_plan", []), dataset_type=row.get("dataset_type", "Character"))
            valid = bool(row.get("scene_plan"))
        else:
            normalize_workflow_output(prompt, row.get("target", "Generic"), mode="Video" if row["workflow"] == "minimax" else "Enhance")
            valid = bool(prompt)
    except (ValueError, TypeError, KeyError):
        valid = False
    try:
        issues = output_constraint_issues(prompt, row.get("target", "Generic"), compile_constraints(row.get("rules", "")))
    except (ValueError, TypeError, KeyError):
        issues = []
    accepted = valid and not row.get("error") and completion == "completed"
    result = {"sample_id": row["sample_id"], "workflow": row["workflow"], "format_valid": valid, "accepted": accepted,
              "completion_state": completion, "completion_reason": row.get("finish_reason"),
              "truncation": completion == "token_limit", "prompt_words": words, "prompt_characters": len(prompt),
              "repair_calls": repairs if calls else None, "repair_frequency": repairs / len(calls) if calls else None,
              "first_pass_valid": accepted and not repairs if completion != "unknown" else None, "latency_seconds": row.get("latency_seconds"),
              "forbidden_content_violations": sum(issue["code"] == "forbidden_content" and issue["severity"] == "error" for issue in issues),
              "forbidden_content_warnings": sum(issue["code"] == "forbidden_content" and issue["severity"] == "warning" for issue in issues),
              "negative_language_leakage": sum(issue["code"] == "constraint_negative_leakage" for issue in issues),
              "constraint_diagnostics": issues, "reviewed": False}
    result["known_failure"] = row.get("known_failure")
    if row.get("scene_plan"):
        from goated_prompter.scene_eligibility import scene_eligibility
        scenes = row["scene_plan"]
        result["scene_validity"] = sum(scene_eligibility(scene, {"trigger_type": row.get("dataset_type", "Character")}).usable for scene in scenes) / len(scenes)
    if review is None:
        return result
    if not review.get("reviewer"):
        raise ValueError("Semantic review needs named provenance (including agent/exploratory reviews).")
    for kind in FIDELITY:
        anchors = review.get("anchors", {}).get(kind, {})
        expected = set(row.get("anchors", {}).get(kind, []))
        if set(anchors) != expected or any(type(value) is not bool for value in anchors.values()):
            raise ValueError(f"Incomplete {kind} anchor review for {row['sample_id']}")
        result[kind + "_fidelity"] = sum(anchors.values()) / len(anchors) if anchors else None
    facts = review.get("useful_details", {})
    if not isinstance(facts, dict) or any(not isinstance(values, list) or
            any(not isinstance(value, str) or not value.strip() for value in values) for values in facts.values()):
        raise ValueError("Useful detail IDs must be nonempty facts grouped by category; paraphrases reuse IDs.")
    for field in REVIEW_FIELDS:
        value = review.get(field)
        if value is not None and type(value) is not bool:
            raise ValueError(f"{field} needs true/false or null (not applicable).")
        result[field] = value
    unique = {fact.casefold().strip() for values in facts.values() for fact in values}
    result.update(reviewed=True, reviewer=review["reviewer"], useful_detail_facts=len(unique),
                  useful_detail_density=100 * len(unique) / max(1, words),
                  detail_categories={key: len(set(values)) for key, values in facts.items()})
    required = ["semantic_repetition", "target_usability"]
    if row["workflow"] == "minimax":
        required.append("temporal_fidelity")
        if row.get("references") or re.search(r'<(?:image|video|audio)\d+>|<d>|\bsays\b', row.get("request", ""), re.I):
            required.append("dialogue_reference_fidelity")
    elif row.get("anchors", {}).get("action"):
        required.extend(("domain_action_relevance", "generic_pose", "pose_simplified"))
    result["review_complete"] = all(type(review.get(field)) is bool for field in required)
    if row.get("output_kind") == "ideas":
        semantic_ids = review.get("semantic_idea_ids", [])
        result["review_complete"] &= len(semantic_ids) == len(row.get("ideas", [])) and all(
            isinstance(value, str) and value.strip() for value in semantic_ids)
    return result


def summarize(records, annotations=()):
    labels = {row["sample_id"]: row for row in annotations}
    if len(labels) != len(annotations) or len({row["sample_id"] for row in records}) != len(records):
        raise ValueError("Duplicate sample or annotation IDs.")
    if labels.keys() - {row["sample_id"] for row in records}:
        raise ValueError("Annotations reference unknown samples.")
    samples = [measure(row, labels.get(row["sample_id"])) for row in records]
    workflows = {}
    for workflow in sorted({row["workflow"] for row in samples}):
        rows = [row for row in samples if row["workflow"] == workflow]
        fields = ("format_valid", "first_pass_valid", "repair_frequency", "prompt_words", "latency_seconds",
                  "useful_detail_density", "semantic_repetition", "domain_action_relevance", "generic_pose",
                  "pose_simplified", "temporal_fidelity", "dialogue_reference_fidelity", "target_usability", "scene_validity",
                  *(kind + "_fidelity" for kind in FIDELITY))
        def average(field):
            values = [row[field] for row in rows if row.get(field) is not None]
            return sum(values) / len(values) if values else None
        workflows[workflow] = {"samples": len(rows), "reviewed": sum(row["reviewed"] for row in rows),
            "averages": {field: average(field) for field in fields},
            "forbidden_content_violations": sum(row["forbidden_content_violations"] for row in rows),
            "negative_language_leakage": sum(row["negative_language_leakage"] for row in rows),
            "failures": [row["sample_id"] for row in rows if not row["accepted"] or row.get("known_failure") or
                row["forbidden_content_violations"] or row["negative_language_leakage"] or
                row.get("target_usability") is False or row.get("domain_action_relevance") is False or
                row.get("temporal_fidelity") is False or row.get("dialogue_reference_fidelity") is False or
                row.get("pose_simplified") is True or row.get("semantic_repetition") is True or
                any(row.get(kind + "_fidelity", 1) not in (None, 1) for kind in FIDELITY)]}
    groups = defaultdict(list)
    semantic_groups = defaultdict(list)
    for row in records:
        for idea in row.get("ideas", []):
            groups[(row.get("concept", row.get("case_id")), row.get("run", 1))].append(normalized(idea))
        if labels.get(row["sample_id"]):
            semantic_groups[row.get("concept", row.get("case_id"))].extend(labels[row["sample_id"]].get("semantic_idea_ids", []))
    def duplicate_rate(values):
        return (len(values) - len(set(values))) / len(values) if values else None
    cross = defaultdict(list)
    for (concept, _run), ideas in groups.items():
        cross[concept].extend(ideas)
    prompt_groups = defaultdict(list)
    for row in records:
        if row.get("prompt"):
            prompt_groups[(row["workflow"], row.get("concept", row.get("case_id")))].append(normalized(row["prompt"]))
    parity_groups = defaultdict(dict)
    for row, sample in zip(records, samples):
        if row["workflow"] in {"builder", "dataset"} and row.get("output_kind") != "ideas":
            key = tuple(row.get(field) for field in ("case_id", "target", "length", "director", "style", "creativity", "run"))
            if all(value is not None for value in key):
                parity_groups[key][row["workflow"]] = sample
    parity = [{"settings": list(key), "builder": values["builder"], "dataset": values["dataset"]}
              for key, values in parity_groups.items() if set(values) == {"builder", "dataset"}]
    latency = sorted(row["latency_seconds"] for row in records if isinstance(row.get("latency_seconds"), (int, float)))
    return {"workflows": workflows, "samples": samples, "parity_pairs": parity,
            "latency": {"measured": len(latency), "p50_seconds": latency[len(latency) // 2] if latency else None,
                        "p95_seconds": latency[min(len(latency) - 1, int(len(latency) * .95))] if latency else None},
            "novelty": {"within_run_exact_duplicate_rates": {str(key): duplicate_rate(values) for key, values in groups.items()},
                        "cross_run_exact_duplicate_rates": {str(key): duplicate_rate(values) for key, values in cross.items()},
                        "cross_run_prompt_duplicate_rates": {str(key): duplicate_rate(values) if len(values) > 1 else None for key, values in prompt_groups.items()},
                        "reviewed_semantic_duplicate_rates": {str(key): duplicate_rate(values) for key, values in semantic_groups.items()}},
            "semantic_review_complete": bool(samples) and all(row.get("review_complete") for row in samples)}
