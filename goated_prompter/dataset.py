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
    dataset_format_repair, dataset_content_repair, dataset_loop_repair, deep_review_correction,
)
from .prompting.details import PROMPT_LENGTH_NAMES
from .prompting.target_models import TARGET_MODEL_NAMES
from .workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text
from .dataset_coverage import AXES, analyze_dataset_quality, effective_coverage_plan
from .dataset_triggers import trigger_presence_error, trigger_terms
from .dataset_visible_content import PositiveContentError, positive_prompt_error, sanitize_positive_prompt
from .scene_planner import (ScenePlanner, MAX_STORED_SCENE_CHARACTERS, MAX_STORED_IDEA_CHARACTERS,
                            reusable_scene_plan, scene_plan_signature, validate_saved_scene_plan)


DATASET_MAX_RETRIES = 3


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "trigger_at_start": False, "trigger_connected": True, "expand_trigger": False,
        "amount": 12, "visual_style": "Photorealistic", "custom_style": "",
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "variety": "Balanced", "constraints": "",
        "coverage_enabled": False, "coverage_axes": [], "coverage_plan": [], "plan_seed": 0, "plan_signature": "",
        "quality_report": {}, "results": [], "result_job_id": "",
        "scene_plan": [], "scene_plan_signature": "",
    }


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        qualifier = "nonempty " if required else ""
        raise ValueError(f"{label} must be a {qualifier}string of at most {limit} characters.")
    return value


def validate_dataset_draft(value, *, generation=False, planning=False):
    defaults = default_dataset_draft()
    if not isinstance(value, dict):
        raise ValueError("Invalid Dataset settings fields.")
    # Discard obsolete controls from older builds instead of blocking the entire
    # draft. Supported fields still receive the value validation below.
    value = {key: item for key, item in value.items() if key in defaults}
    result = {**defaults, **value}
    result["trigger"] = _text(result["trigger"], "Trigger / prepend", 200, required=generation and not planning).strip()
    result["subject"] = _text(result["subject"], "Dataset concept", 10000, required=generation).strip()
    result["custom_type"] = _text(result["custom_type"], "Custom subject kind", 120).strip()
    result["custom_style"] = _text(result["custom_style"], "Custom visual style", 500).strip()
    result["inputs"] = _text(result["inputs"], "Guided inputs", 50000)
    result["constraints"] = _text(result["constraints"], "Dataset constraints", 10000)
    result["result_job_id"] = _text(result["result_job_id"], "Result job id", 128).strip()
    result["plan_signature"] = _text(result["plan_signature"], "Coverage plan signature", 128).strip()
    result["scene_plan_signature"] = _text(result["scene_plan_signature"], "Scene plan signature", 128).strip()
    result["scene_plan"] = validate_saved_scene_plan(result["scene_plan"])
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
    for key, label in (("trigger_at_start", "Trigger starting placement"),
                       ("trigger_connected", "Connected trigger text"),
                       ("expand_trigger", "Trigger expansion")):
        if type(result[key]) is not bool:
            raise ValueError(f"{label} must be enabled or disabled.")
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
        if (not isinstance(item, dict) or not {"index", "prompt", "input"} <= set(item)
                or set(item) - {"index", "prompt", "input", "idea", "scene"}):
            raise ValueError("Each Dataset result requires index, prompt and input, with optional idea and scene text.")
        if type(item["index"]) is not int or item["index"] < 1 or item["index"] > 25:
            raise ValueError("Invalid Dataset result index.")
        record = {"index": item["index"],
                  "prompt": _text(item["prompt"], f"Dataset prompt {index + 1}", 100000),
                  "input": _text(item["input"], f"Dataset input {index + 1}", 10000)}
        if "scene" in item:
            record["scene"] = _text(item["scene"], f"Dataset scene {index + 1}", MAX_STORED_SCENE_CHARACTERS)
        if "idea" in item:
            record["idea"] = _text(item["idea"], f"Dataset idea {index + 1}", MAX_STORED_IDEA_CHARACTERS)
        cleaned.append(record)
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


def validate_trigger_contract(prompt, data, progress=None):
    cleaned = prompt if data["target"] == "Ideogram4" else sanitize_prompt_text(prompt)
    error = trigger_presence_error(cleaned, data["trigger"], data["target"])
    if error and progress:
        progress(f"Trigger warning: {error} Keeping the finished prompt without rewriting it.")
    return cleaned


def validate_positive_content(prompt, data):
    terms = trigger_terms(data["trigger"], data["trigger_connected"])
    prompt = sanitize_positive_prompt(prompt, data["target"], terms)
    error = positive_prompt_error(prompt, data["target"], terms)
    if not prompt.strip():
        error = "Positive content cleanup left no visible image description."
    if error:
        raise PositiveContentError(error)
    return prompt


class DatasetService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _generate(self, session, instruction, data, index, progress):
        original = instruction
        for attempt in range(DATASET_MAX_RETRIES + 1):
            self.checkpoint()
            progress(
                f"{'Retrying' if attempt else 'Waiting for'} prompt engine · "
                f"dataset prompt {index}/{data['amount']}"
                + (f" · retry {attempt}/{DATASET_MAX_RETRIES}" if attempt else "")
            )
            session.validate_instruction(instruction)
            try:
                raw = session.generate(instruction)
            except BackendRunawayError as exc:
                self.checkpoint()
                recovered = getattr(exc, "recoverable_text", "")
                content_failure = False
                if recovered and len(recovered.split()) >= 30 and recovered.rstrip().endswith((".", "!", "?", "}")):
                    try:
                        prompt = normalize_workflow_output(recovered, data["target"])
                        prompt = validate_trigger_contract(prompt, data, progress)
                        prompt = validate_positive_content(prompt, data)
                    except PositiveContentError:
                        content_failure = True
                        progress("The pre-loop prefix still had invalid positive content after cleanup; retrying.")
                    except (WorkflowFormatError, ValueError, KeyError, TypeError):
                        progress("The pre-loop prefix was not a valid complete target prompt; retrying.")
                    else:
                        progress(f"Dataset prompt {index}/{data['amount']} recovered from the usable text before the repetition loop.")
                        return prompt
                if attempt >= DATASET_MAX_RETRIES:
                    raise BackendGenerationError(
                        f"Dataset prompt {index}/{data['amount']} produced runaway output after "
                        f"{DATASET_MAX_RETRIES} retries. {exc}"
                    ) from exc
                progress(
                    f"Dataset prompt {index}/{data['amount']} entered a repetition/output-limit loop: "
                    f"{exc} Retrying with stricter finite-output instructions "
                    f"({attempt + 1}/{DATASET_MAX_RETRIES})."
                )
                retry_system = dataset_loop_repair(original.system_message, exc, attempt + 1)
                if content_failure:
                    retry_system = dataset_content_repair(retry_system)
                instruction = replace(
                    original,
                    system_message=retry_system,
                    max_tokens=max(384, int(original.max_tokens * (0.8 ** (attempt + 1)))),
                    hard_max_tokens=max(384, int(original.hard_max_tokens * (0.8 ** (attempt + 1)))),
                    diagnostic_stage=original.diagnostic_stage + f":loop_retry_{attempt + 1}",
                )
                continue
            self.checkpoint()
            progress(f"Checking dataset prompt {index}/{data['amount']}")
            try:
                prompt = normalize_workflow_output(raw, data["target"])
                prompt = validate_trigger_contract(prompt, data, progress)
                return validate_positive_content(prompt, data)
            except (WorkflowFormatError, ValueError, KeyError, TypeError) as exc:
                if attempt >= DATASET_MAX_RETRIES:
                    raise BackendGenerationError(
                        f"Dataset prompt {index}/{data['amount']} remained invalid after "
                        f"{DATASET_MAX_RETRIES} retries. {exc}"
                    ) from exc
                progress(
                    f"Dataset prompt {index}/{data['amount']} failed output validation: {exc} "
                    f"Retrying ({attempt + 1}/{DATASET_MAX_RETRIES})."
                )
                # Repair from clean instructions without raising the detail or
                # token budget lowered by an earlier loop recovery attempt.
                retry_system = original.system_message
                if instruction.hard_max_tokens < original.hard_max_tokens:
                    retry_system = dataset_loop_repair(retry_system, exc, attempt + 1)
                content_failure = isinstance(exc, PositiveContentError)
                instruction = replace(original,
                    system_message=(dataset_content_repair(retry_system) if content_failure
                                    else dataset_format_repair(retry_system, exc)),
                    max_tokens=instruction.max_tokens,
                    hard_max_tokens=instruction.hard_max_tokens,
                    diagnostic_stage=original.diagnostic_stage
                    + f":{'content' if content_failure else 'format'}_retry_{attempt + 1}")

    def run(self, request, data, progress, partial, *, scenes_only=False):
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        coverage = effective_coverage_plan(data)
        plan = coverage["plan"]
        results = []
        signature = scene_plan_signature(data, coverage)
        progress("Starting the prompt engine for the dataset…")
        with backend.generation_session() as session:
            scenes = None if scenes_only else reusable_scene_plan(data, coverage)
            if scenes is None:
                planned = ScenePlanner(self.checkpoint).plan_batch(
                    session=session, data=data, coverage=coverage, family=family, progress=progress)
                scenes = [{**row, "input": assignment["input"]}
                          for row, assignment in zip(planned, plan)]
            else:
                progress("Reusing saved Scene Planner ideas for the selected target.")
            scene_state = {"scene_plan": scenes, "scene_plan_signature": signature}
            if scenes_only:
                return {"ok": True, "kind": "dataset_scenes", **scene_state,
                        "coverage": coverage, "backend": backend.name}
            # Publish the full plan before any final prompt, retaining it even if
            # the writer subsequently fails or the user ends generation.
            partial({"ok": True, "kind": "dataset", "prompts": [], "completed": 0,
                     "total": data["amount"], "target": data["target"],
                     "coverage": coverage, **scene_state})
            for index in range(1, data["amount"] + 1):
                self.checkpoint()
                plan_item = {**plan[index - 1], "idea": scenes[index - 1]["idea"], "scene": scenes[index - 1]["scene"]}
                instruction = dataset_instruction(request, data, index, (), family, plan_item)
                prompt = self._generate(session, instruction, data, index, progress)
                seed = plan_item["input"]
                results.append({"index": index, "prompt": prompt, "input": seed,
                                "idea": plan_item["idea"], "scene": plan_item["scene"]})
                partial({"ok": True, "kind": "dataset", "prompts": list(results),
                         "completed": len(results), "total": data["amount"], "target": data["target"],
                         "coverage": coverage, **scene_state})
        report = analyze_dataset_quality(data, results, plan)
        return {"ok": True, "kind": "dataset", "prompts": results,
                "completed": len(results), "total": data["amount"], "target": data["target"],
                "coverage": coverage, **scene_state, "quality_report": report, "backend": backend.name}


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
