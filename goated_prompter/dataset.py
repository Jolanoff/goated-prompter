"""Validated, target-aware prompt batches for training datasets."""

from dataclasses import replace
import json

from .backends.factory import create_backend
from .backends.base import BackendGenerationError, BackendRunawayError
from .core import _effective_model_family
from .director_profiles import resolve_director_config
from .prompting.dataset import (
    DATASET_SOURCES, DATASET_STYLES, DATASET_TYPES, DATASET_VARIETY,
    DEEP_CATEGORIES, dataset_instruction, deep_review_instruction,
    dataset_format_repair, dataset_loop_repair, deep_review_correction,
)
from .prompting.details import PROMPT_LENGTH_NAMES
from .prompting.target_models import TARGET_MODEL_NAMES
from .workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text
from .dataset_coverage import AXES, analyze_dataset_quality, effective_coverage_plan


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "amount": 12, "visual_style": "Photorealistic", "custom_style": "",
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "variety": "Balanced", "constraints": "",
        "coverage_enabled": False, "coverage_axes": [], "coverage_plan": [], "plan_seed": 0, "plan_signature": "",
        "quality_report": {}, "results": [], "result_job_id": "",
    }


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        qualifier = "nonempty " if required else ""
        raise ValueError(f"{label} must be a {qualifier}string of at most {limit} characters.")
    return value


def validate_dataset_draft(value, *, generation=False):
    defaults = default_dataset_draft()
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise ValueError("Invalid Dataset settings fields.")
    result = {**defaults, **value}
    result["trigger"] = _text(result["trigger"], "Trigger / prepend", 200, required=generation).strip()
    result["subject"] = _text(result["subject"], "Trigger description", 10000, required=generation).strip()
    result["custom_type"] = _text(result["custom_type"], "Custom subject kind", 120).strip()
    result["custom_style"] = _text(result["custom_style"], "Custom visual style", 500).strip()
    result["inputs"] = _text(result["inputs"], "Guided inputs", 50000)
    result["constraints"] = _text(result["constraints"], "Dataset constraints", 10000)
    result["result_job_id"] = _text(result["result_job_id"], "Result job id", 128).strip()
    result["plan_signature"] = _text(result["plan_signature"], "Coverage plan signature", 128).strip()
    if result["trigger_type"] not in DATASET_TYPES:
        raise ValueError("Invalid trigger subject kind.")
    if result["visual_style"] not in DATASET_STYLES:
        raise ValueError("Invalid dataset visual style.")
    if result["source_mode"] not in DATASET_SOURCES:
        raise ValueError("Invalid dataset source mode.")
    if result["variety"] not in DATASET_VARIETY:
        raise ValueError("Invalid dataset variety.")
    if result["target"] not in TARGET_MODEL_NAMES or result["length"] not in PROMPT_LENGTH_NAMES:
        raise ValueError("Invalid target model or prompt length.")
    if not isinstance(result["director_preset"], str) or len(result["director_preset"]) > 256:
        raise ValueError("Director preset must be a string of at most 256 characters.")
    if type(result["amount"]) is not int or not 1 <= result["amount"] <= 25:
        raise ValueError("Dataset prompt amount must be between 1 and 25.")
    if type(result["coverage_enabled"]) is not bool:
        raise ValueError("Coverage planning must be enabled or disabled.")
    if type(result["plan_seed"]) is not int or not 0 <= result["plan_seed"] <= 2147483647:
        raise ValueError("Coverage plan seed must be between 0 and 2147483647.")
    if (not isinstance(result["coverage_axes"], list) or len(result["coverage_axes"]) > len(AXES)
            or any(not isinstance(key, str) or key not in AXES for key in result["coverage_axes"])
            or len(set(result["coverage_axes"])) != len(result["coverage_axes"])):
        raise ValueError("Invalid Dataset coverage axes.")
    if result["trigger_type"] == "Custom" and generation and not result["custom_type"]:
        raise ValueError("Describe the custom subject kind before generating.")
    if result["visual_style"] == "Custom" and generation and not result["custom_style"]:
        raise ValueError("Describe the custom visual style before generating.")
    if result["source_mode"] == "guided" and generation and not any(line.strip() for line in result["inputs"].splitlines()):
        raise ValueError("Add at least one guided input, one per line.")
    if not isinstance(result["results"], list) or len(result["results"]) > 25:
        raise ValueError("Dataset results must be an array of at most 25 prompts.")
    cleaned = []
    for index, item in enumerate(result["results"]):
        if not isinstance(item, dict) or set(item) != {"index", "prompt", "input"}:
            raise ValueError("Each Dataset result requires index, prompt and input only.")
        if type(item["index"]) is not int or item["index"] < 1 or item["index"] > 25:
            raise ValueError("Invalid Dataset result index.")
        cleaned.append({"index": item["index"],
                        "prompt": _text(item["prompt"], f"Dataset prompt {index + 1}", 100000),
                        "input": _text(item["input"], f"Dataset input {index + 1}", 10000)})
    result["results"] = cleaned
    if not isinstance(result["coverage_plan"], list) or len(result["coverage_plan"]) > 25:
        raise ValueError("Coverage plan must contain at most 25 rows.")
    plan = []
    for item in result["coverage_plan"]:
        if not isinstance(item, dict) or set(item) != {"index", "input", "facets"}:
            raise ValueError("Each coverage row requires index, input and facets only.")
        if type(item["index"]) is not int or not 1 <= item["index"] <= 25:
            raise ValueError("Invalid coverage row index.")
        if not isinstance(item["facets"], dict) or len(item["facets"]) > len(AXES):
            raise ValueError("Invalid coverage row facets.")
        facets = {}
        for key, value in item["facets"].items():
            if key not in AXES or not isinstance(value, str) or value not in AXES[key][1]:
                raise ValueError("Invalid coverage facet value.")
            facets[key] = value
        plan.append({"index": item["index"], "input": _text(item["input"], "Coverage input", 10000),
                     "facets": facets})
    result["coverage_plan"] = plan
    if not isinstance(result["quality_report"], dict):
        raise ValueError("Dataset quality report must be an object.")
    if len(json.dumps(result["quality_report"], ensure_ascii=False)) > 500000:
        raise ValueError("Dataset quality report is too large.")
    return result


def ensure_trigger(prompt, trigger, target):
    if target == "Ideogram4":
        decoded = json.loads(prompt)
        description = decoded["high_level_description"].lstrip()
        if not description.startswith(trigger):
            separator = " " if trigger.endswith((",", ".", ":", ";")) else ", "
            decoded["high_level_description"] = trigger + separator + description
        return json.dumps(decoded, ensure_ascii=False, indent=2)
    prompt = sanitize_prompt_text(prompt)
    if prompt.startswith(trigger):
        return prompt
    separator = " " if trigger.endswith((",", ".", ":", ";")) else ", "
    return trigger + separator + prompt


class DatasetService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _generate(self, session, instruction, data, index, progress):
        for attempt in range(2):
            self.checkpoint()
            progress(
                f"{'Repairing' if attempt else 'Waiting for'} prompt engine · "
                f"dataset prompt {index}/{data['amount']}"
            )
            session.validate_instruction(instruction)
            try:
                raw = session.generate(instruction)
            except BackendRunawayError as exc:
                if attempt:
                    raise BackendGenerationError(
                        f"The prompt engine produced runaway dataset output twice. {exc}"
                    ) from exc
                progress(
                    f"Dataset prompt {index}/{data['amount']} entered a repetition/output-limit loop: "
                    f"{exc} Retrying once with stricter finite-output instructions."
                )
                instruction = replace(
                    instruction,
                    system_message=dataset_loop_repair(instruction.system_message, exc),
                    diagnostic_stage=instruction.diagnostic_stage + ":loop_retry",
                )
                continue
            self.checkpoint()
            progress(f"Checking dataset prompt {index}/{data['amount']}")
            try:
                prompt = normalize_workflow_output(raw, data["target"])
                return ensure_trigger(prompt, data["trigger"], data["target"])
            except (WorkflowFormatError, ValueError, KeyError, TypeError) as exc:
                if attempt:
                    raise BackendGenerationError(f"The prompt engine returned an invalid dataset prompt twice. {exc}") from exc
                progress(
                    f"Dataset prompt {index}/{data['amount']} failed output validation: {exc} Retrying once."
                )
                instruction = replace(instruction,
                    system_message=dataset_format_repair(instruction.system_message, exc),
                    diagnostic_stage=instruction.diagnostic_stage + ":format_retry")

    def run(self, request, data, progress, partial):
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        coverage = effective_coverage_plan(data)
        plan = coverage["plan"]
        results = []
        progress("Starting the prompt engine for the dataset…")
        with backend.generation_session() as session:
            for index in range(1, data["amount"] + 1):
                self.checkpoint()
                plan_item = plan[index - 1]
                instruction = dataset_instruction(request, data, index, results, family, plan_item)
                prompt = self._generate(session, instruction, data, index, progress)
                seed = plan_item["input"]
                results.append({"index": index, "prompt": prompt, "input": seed})
                partial({"ok": True, "kind": "dataset", "prompts": list(results),
                         "completed": len(results), "total": data["amount"], "target": data["target"],
                         "coverage": coverage})
        report = analyze_dataset_quality(data, results, plan)
        return {"ok": True, "kind": "dataset", "prompts": results,
                "completed": len(results), "total": data["amount"], "target": data["target"],
                "coverage": coverage, "quality_report": report, "backend": backend.name}


def _parse_deep_review(raw, chunk, coverage_enabled=False):
    text = str(raw or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise WorkflowFormatError("Deep review must return a valid JSON array.") from exc
    expected = [item["index"] for item in chunk]
    if not isinstance(value, list) or len(value) != len(expected):
        raise WorkflowFormatError("Deep review must return one record per supplied prompt.")
    allowed_categories = DEEP_CATEGORIES if coverage_enabled else DEEP_CATEGORIES - {"coverage_mismatch"}
    cleaned = []
    for position, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"index", "issues"} or item["index"] != expected[position] or not isinstance(item["issues"], list) or len(item["issues"]) > 5:
            raise WorkflowFormatError("Deep review records or prompt indexes are invalid.")
        issues = []
        for issue in item["issues"]:
            if (not isinstance(issue, dict) or set(issue) != {"category", "severity", "message"}
                    or issue["category"] not in allowed_categories or issue["severity"] not in {"warning", "error"}
                    or not isinstance(issue["message"], str) or not issue["message"].strip()
                    or len(issue["message"]) > 500):
                raise WorkflowFormatError("A deep review issue is invalid.")
            issues.append({"code": "deep_" + issue["category"], "severity": issue["severity"],
                           "message": issue["message"].strip()})
        cleaned.append({"index": item["index"], "issues": issues})
    return cleaned


def merge_deep_review(report, reviewed):
    by_index = {item["index"]: item for item in reviewed}
    errors = warnings = 0
    for record in report["prompts"]:
        issues = by_index.get(record["index"], {}).get("issues", [])
        record["issues"].extend(issues)
        errors += sum(issue["severity"] == "error" for issue in issues)
        warnings += sum(issue["severity"] == "warning" for issue in issues)
        severities = {issue["severity"] for issue in record["issues"]}
        record["status"] = "error" if "error" in severities else "warning" if severities else "pass"
    report["deep_review"] = {"completed": True, "errors": errors, "warnings": warnings}
    report["score"] = max(0, report["score"] - min(30, errors * 8 + warnings * 3))
    if errors:
        report["status"] = "issues"
    elif warnings and report["status"] == "strong":
        report["status"] = "review"
    return report


class DatasetReviewService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def run(self, request, data, progress):
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        reviewed = []
        chunks = [data["results"][index:index + 4] for index in range(0, len(data["results"]), 4)]
        progress("Starting the prompt engine for deep review…")
        with backend.generation_session() as session:
            for position, chunk in enumerate(chunks, start=1):
                instruction = deep_review_instruction(data, chunk, family)
                for attempt in range(2):
                    self.checkpoint()
                    progress(
                        f"{'Repairing review for' if attempt else 'Waiting for prompt engine · reviewing'} "
                        f"prompts {chunk[0]['index']}–{chunk[-1]['index']} ({position}/{len(chunks)})"
                    )
                    session.validate_instruction(instruction)
                    raw = session.generate(instruction)
                    self.checkpoint()
                    progress(f"Checking review for prompts {chunk[0]['index']}–{chunk[-1]['index']}")
                    try:
                        reviewed.extend(_parse_deep_review(raw, chunk, data["coverage_enabled"]))
                        break
                    except WorkflowFormatError as exc:
                        if attempt:
                            raise BackendGenerationError(f"The prompt engine returned an invalid deep-review format twice. {exc}") from exc
                        progress(
                            f"Deep review for prompts {chunk[0]['index']}–{chunk[-1]['index']} "
                            f"failed output validation: {exc} Retrying once."
                        )
                        instruction = deep_review_instruction(
                            data, chunk, family, deep_review_correction(exc)
                        )
        coverage = effective_coverage_plan(data)
        report = analyze_dataset_quality(data, data["results"], coverage["plan"])
        merge_deep_review(report, reviewed)
        return {"ok": True, "kind": "dataset_review", "report": report,
                "reviewed": len(data["results"]), "backend": backend.name}
