"""Transparent lexical diagnostics plus explicit semantic review, never word-count fidelity."""

from collections import defaultdict
import re

from goated_prompter.planning.rule_compiler import compile_rules
from goated_prompter.workflow_output import normalize_workflow_output
from goated_prompter.planning.constraint_validation import output_constraint_issues
from goated_prompter.dataset_triggers import trigger_presence_error

FIDELITY = ("scene", "action", "pose", "constraint")
REVIEW_FIELDS = ("semantic_repetition", "domain_action_relevance", "generic_pose", "pose_simplified",
                 "temporal_fidelity", "dialogue_reference_fidelity", "target_usability")


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def annotation_template(records):
    return [{"sample_id": row["sample_id"], "reviewer": "", "review_kind": "", "anchors": {
        kind: {anchor: None for anchor in row.get("anchors", {}).get(kind, [])} for kind in FIDELITY},
        "useful_details": {}, "semantic_idea_ids": [], "coverage_saturated": None, **{key: None for key in REVIEW_FIELDS}, "notes": ""}
        for row in records]


def measure(row, review=None):
    prompt = row.get("prompt", "")
    words = len(prompt.split())
    completion = row.get("completion_state", "unknown")
    calls = row.get("calls", [])
    writer_calls = [call for call in calls if not str(call.get("stage", "")).startswith("semantic:review:")]
    transport_retries = sum("transport_retry" in str(call.get("stage", "")) for call in writer_calls)
    repairs = sum(bool(re.search(r"repair|retry|correction", str(call.get("stage", ""))))
                  and "transport_retry" not in str(call.get("stage", "")) for call in writer_calls)
    events = [event for call in calls for event in call.get("validation_events", [])]
    validations = [event for event in events if event.get("type") == "validation" and event.get("workflow") == row["workflow"]]
    semantic = [event for event in events if event.get("type") == "semantic_review"]
    try:
        if row.get("output_kind") == "ideas":
            from goated_prompter.scene_planner import validate_saved_scene_plan
            validate_saved_scene_plan(row.get("scene_plan", []))
            valid = bool(row.get("scene_plan"))
        else:
            normalize_workflow_output(prompt, row.get("target", "Generic"), mode="Video" if row["workflow"] == "minimax" else "Enhance")
            valid = bool(prompt)
    except (ValueError, TypeError, KeyError):
        valid = False
    try:
        issues = output_constraint_issues(prompt, row.get("target", "Generic"), compile_rules(row.get("rules", "")))
    except (ValueError, TypeError, KeyError):
        issues = []
    accepted = valid and not row.get("error") and completion == "completed"
    completed = row.get("completed_results", int(accepted))
    trigger_fidelity = None
    if row.get("trigger") and row.get("output_kind") != "ideas":
        trigger_fidelity = trigger_presence_error(prompt, row["trigger"], row.get("target", "Generic"),
                                                 expand=row.get("expand_trigger", False)) is None
    # Rejected semantic candidates can still have valid target formatting.
    measured_formats = [event["format_valid"] for event in validations if type(event.get("format_valid")) is bool]
    format_valid = measured_formats[-1] if measured_formats else valid
    result = {"sample_id": row["sample_id"], "workflow": row["workflow"], "format_valid": format_valid, "accepted": accepted,
              "completion_state": completion, "completion_reason": row.get("finish_reason"),
              "truncation": completion == "token_limit", "prompt_words": words, "prompt_characters": len(prompt),
               "repair_calls": repairs if calls else None, "repair_frequency": repairs / len(writer_calls) if writer_calls else None,
               "repair_rate": bool(repairs) if writer_calls else None,
               "transport_retry_calls": transport_retries if calls else None,
               "model_calls": len(calls) if calls else None,
               "calls_per_result": len(calls) / completed if calls and completed else None,
               "trigger_fidelity": trigger_fidelity,
               "first_pass_valid": accepted and not (repairs or transport_retries) if writer_calls and completion != "unknown" else None,
               "latency_seconds": row.get("latency_seconds"),
              "forbidden_content_violations": sum(issue["code"] == "forbidden_content" and issue["severity"] == "error" for issue in issues),
              "forbidden_content_warnings": sum(issue["code"] == "forbidden_content" and issue["severity"] == "warning" for issue in issues),
              "negative_language_leakage": sum(issue["code"] == "constraint_negative_leakage" for issue in issues),
                "constraint_diagnostics": issues, "reviewed": False, "independent_review": False}
    outcomes = {event["attempt"]: event for event in validations}
    result.update(transport_success=(all(call.get("finish_reason") == "stop" for call in calls) if calls else None),
        semantic_checks=[event.get("checks", {}) for event in semantic],
        semantic_review_measured=bool(semantic),
        repair_status=("repaired_successfully" if accepted and repairs else "first_pass_valid" if accepted else
                       "repair_exhausted" if repairs else "rejected") if validations else "unknown",
        repair_introduced_regression=(any(event.get("attempt", 0) > 0 and any(issue.get("category") == "repair_preservation"
            for issue in event.get("issues", [])) for event in validations) if validations else None))
    result["semantic_forbidden_content_violations"] = sum(issue.get("kind") == "forbidden_content"
        for event in semantic for issue in event.get("issues", [])) if semantic else None
    result["semantic_exclusion_language_leakage"] = sum(issue.get("kind") == "exclusion_leakage"
        for event in semantic for issue in event.get("issues", [])) if semantic else None
    result["reviewer_format_failures"] = sum(bool(event.get("error")) for event in semantic)
    if repairs and result["repair_introduced_regression"] is False and not any(
            "repair_preservation" in event.get("checks", {}) for event in semantic):
        result["repair_introduced_regression"] = None
    if calls and any(call.get("finish_reason") is None for call in calls) and not any(call.get("error") for call in calls):
        result["transport_success"] = None
    if 0 in outcomes:
        result["first_pass_valid"] = outcomes[0]["accepted"] and not (repairs or transport_retries)
    for category in ("action_fidelity", "scene_fidelity", "constraint_validity", "domain_relevance", "temporal_fidelity"):
        statuses = [event.get("checks", {}).get(category) for event in semantic if category in event.get("checks", {})]
        result["model_review_" + category] = statuses[-1] if statuses else None
    result["known_failure"] = row.get("known_failure")
    if row.get("scene_plan"):
        from goated_prompter.scene_eligibility import scene_eligibility
        scenes = row["scene_plan"]
        result["scene_validity"] = sum(scene_eligibility(scene, {"trigger_type": row.get("dataset_type", "Character")}).usable for scene in scenes) / len(scenes)
    if review is None:
        return result
    if not review.get("reviewer"):
        raise ValueError("Semantic review needs named provenance (including agent/exploratory reviews).")
    review_kind = review.get("review_kind", "unspecified")
    if review_kind not in {"", "unspecified", "human", "independent", "self_review", "exploratory"}:
        raise ValueError("Unknown semantic review kind.")
    result.update(review_kind=review_kind, independent_review=review_kind in {"human", "independent"})
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
    if review.get("coverage_saturated") is not None and type(review["coverage_saturated"]) is not bool:
        raise ValueError("coverage_saturated needs true/false or null; never infer saturation from length.")
    unique = {fact.casefold().strip() for values in facts.values() for fact in values}
    result.update(reviewed=True, reviewer=review["reviewer"], useful_detail_facts=len(unique),
                   useful_fact_ids=sorted(unique),
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


def useful_fact_coverage(smaller, larger):
    """Compare explicit reviewed fact IDs, never adjectives or raw token count."""
    def facts(label):
        return {fact.strip().casefold() for values in label.get("useful_details", {}).values() for fact in values}
    low, high = facts(smaller), facts(larger)
    return {"new_useful_facts": sorted(high - low), "retained_useful_facts": sorted(high & low),
            "lost_useful_facts": sorted(low - high), "net_useful_fact_gain": len(high) - len(low)}


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
        fields = ("format_valid", "first_pass_valid", "repair_frequency", "repair_rate", "calls_per_result", "model_calls",
                  "trigger_fidelity", "transport_retry_calls", "transport_success", "repair_introduced_regression", "prompt_words", "latency_seconds",
                  "useful_detail_density", "semantic_repetition", "domain_action_relevance", "generic_pose",
                  "pose_simplified", "temporal_fidelity", "dialogue_reference_fidelity", "target_usability", "scene_validity",
                  *(kind + "_fidelity" for kind in FIDELITY))
        def average(field):
            values = [row[field] for row in rows if row.get(field) is not None]
            return sum(values) / len(values) if values else None
        workflows[workflow] = {"samples": len(rows), "reviewed": sum(row["reviewed"] for row in rows),
            "repair_outcomes": {status: sum(row["repair_status"] == status for row in rows)
                for status in ("first_pass_valid", "repaired_successfully", "repair_exhausted", "rejected", "unknown")},
            "model_semantic_statuses": {category: {status:sum(row.get("model_review_" + category) == status for row in rows)
                for status in ("pass", "fail", "unknown", None)}
                for category in ("action_fidelity", "scene_fidelity", "constraint_validity", "domain_relevance", "temporal_fidelity")},
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
    length_groups = defaultdict(dict)
    for row, sample in zip(records, samples):
        if row.get("length") not in {"Detailed", "Maximum", "Maximum Detail"} or row.get("output_kind") == "ideas":
            continue
        key = tuple(row.get(field) for field in ("workflow", "case_id", "target", "director", "style", "creativity", "planning", "run", "request", "rules"))
        if all(value is not None for value in key):
            length_groups[key]["Detailed" if row["length"] == "Detailed" else "Maximum Detail"] = (row, sample)
    coverage_pairs = []
    for key, pair in length_groups.items():
        if set(pair) != {"Detailed", "Maximum Detail"}:
            continue
        low, high = pair["Detailed"], pair["Maximum Detail"]
        if not low[1]["reviewed"] or not high[1]["reviewed"]:
            continue
        delta = useful_fact_coverage(labels[low[0]["sample_id"]], labels[high[0]["sample_id"]])
        fidelity_valid = all(sample["accepted"] and sample.get("review_complete") and not any(sample.get(kind + "_fidelity") not in (None, 1) for kind in FIDELITY)
                             and sample.get("target_usability") is not False and sample.get("temporal_fidelity") is not False
                             and sample.get("dialogue_reference_fidelity") is not False and sample.get("domain_action_relevance") is not False
                             and sample.get("pose_simplified") is not True
                             for _, sample in (low, high))
        coverage_pairs.append({"settings":list(key), "detailed":low[0]["sample_id"], "maximum":high[0]["sample_id"],
            **delta, "fidelity_valid":fidelity_valid,
            "source_saturated":labels[low[0]["sample_id"]].get("coverage_saturated"),
            "useful_coverage_increased": bool(delta["new_useful_facts"]) and delta["net_useful_fact_gain"] > 0 and fidelity_valid})
    latency = sorted(row["latency_seconds"] for row in records if isinstance(row.get("latency_seconds"), (int, float)))
    return {"workflows": workflows, "samples": samples, "parity_pairs": parity, "length_coverage_pairs":coverage_pairs,
            "latency": {"measured": len(latency), "p50_seconds": latency[len(latency) // 2] if latency else None,
                        "p95_seconds": latency[min(len(latency) - 1, int(len(latency) * .95))] if latency else None},
            "novelty": {"within_run_exact_duplicate_rates": {str(key): duplicate_rate(values) for key, values in groups.items()},
                        "cross_run_exact_duplicate_rates": {str(key): duplicate_rate(values) for key, values in cross.items()},
                        "cross_run_prompt_duplicate_rates": {str(key): duplicate_rate(values) if len(values) > 1 else None for key, values in prompt_groups.items()},
                        "reviewed_semantic_duplicate_rates": {str(key): duplicate_rate(values) for key, values in semantic_groups.items()}},
            "semantic_review_complete": bool(samples) and all(row.get("review_complete") and row["independent_review"] for row in samples)}
