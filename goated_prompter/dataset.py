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
from .prompting.target_models import TARGET_MODEL_NAMES, canonical_target
from .workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text, requested_visible_text
from .dataset_assignments import dataset_assignments
from .dataset_quality import analyze_dataset_quality, analyze_idea_diversity, idea_action_error
from .dataset_triggers import trigger_text_target
from .dataset_triggers import trigger_presence_error, trigger_terms
from .dataset_visible_content import PositiveContentError, positive_prompt_error, sanitize_positive_prompt
from .scene_planner import (ScenePlanner, MAX_STORED_SCENE_CHARACTERS, MAX_STORED_IDEA_CHARACTERS,
                            reusable_scene_plan, scene_plan_signature, validate_saved_scene_plan, validate_plan_metadata,
                            failure_reason, failed_scene, scene_is_usable, FAILURE_METADATA)
from .dataset_staging import geometry_errors, migrate_saved_geometry, resolve_framing_conflicts


DATASET_MAX_RETRIES = 3


class SceneFidelityError(ValueError):
    """The writer dropped a high-confidence fixed action, not the target schema."""


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "trigger_at_start": False, "trigger_connected": True, "expand_trigger": False,
        "amount": 12, "visual_style": "Photorealistic", "custom_style": "",
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "variety": "Balanced", "constraints": "",
        "quality_report": {}, "results": [], "result_job_id": "",
        "scene_plan": [], "scene_plan_signature": "",
        "planning_mode": "Fast",
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
    result["scene_plan_signature"] = _text(result["scene_plan_signature"], "Scene plan signature", 128).strip()
    if not isinstance(result["planning_mode"], str) or result["planning_mode"] not in {"Fast", "Quality"}:
        raise ValueError("Dataset planning mode must be Fast or Quality.")
    if result["trigger_type"] not in DATASET_TYPES:
        raise ValueError("Invalid trigger subject kind.")
    result["scene_plan"] = validate_saved_scene_plan(result["scene_plan"], dataset_type=result["trigger_type"])
    if result["visual_style"] not in DATASET_STYLES:
        raise ValueError("Invalid dataset visual style.")
    if result["source_mode"] not in DATASET_SOURCES:
        raise ValueError("Invalid dataset source mode.")
    if result["variety"] not in DATASET_VARIETY:
        raise ValueError("Invalid dataset variety.")
    result["target"] = canonical_target(result["target"])
    if result["target"] not in TARGET_MODEL_NAMES or result["length"] not in PROMPT_LENGTH_NAMES:
        raise ValueError("Invalid target model or prompt length.")
    if not isinstance(result["director_preset"], str) or len(result["director_preset"]) > 256:
        raise ValueError("Director preset must be a string of at most 256 characters.")
    if type(result["amount"]) is not int or not 1 <= result["amount"] <= 25:
        raise ValueError("Dataset prompt amount must be between 1 and 25.")
    for key, label in (("trigger_at_start", "Trigger starting placement"),
                       ("trigger_connected", "Connected trigger text"),
                       ("expand_trigger", "Trigger expansion")):
        if type(result[key]) is not bool:
            raise ValueError(f"{label} must be enabled or disabled.")
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
        if isinstance(item, dict):
            item = {key: value for key, value in item.items() if key != "coverage_conflicts"}
        if (not isinstance(item, dict) or not {"index", "prompt", "input"} <= set(item)
                or set(item) - {"index", "prompt", "input", "idea", "scene", "geometry"}):
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
        if "geometry" in item:
            record["geometry"], _ = migrate_saved_geometry(item["geometry"], dataset_type=result["trigger_type"])
        validate_plan_metadata(item)
        cleaned.append(record)
    result["results"] = cleaned
    if not isinstance(result["quality_report"], dict):
        raise ValueError("Dataset quality report must be an object.")
    if len(json.dumps(result["quality_report"], ensure_ascii=False)) > 500000:
        raise ValueError("Dataset quality report is too large.")
    metrics = result["quality_report"].get("metrics")
    if isinstance(metrics, dict) and metrics.keys() & {"coverage", "planned_coverage"}:
        # Recompute cached diagnostics from older builds without the removed metric.
        result["quality_report"] = {}
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

    def _generate(self, session, instruction, data, index, progress, plan_item=None, *, retries=DATASET_MAX_RETRIES):
        expected_text = requested_visible_text("\n".join((data["subject"], data["constraints"], (plan_item or {}).get("input", ""))))
        def check_fidelity(prompt):
            if data.get("planning_mode") == "Quality" and plan_item:
                text = trigger_text_target(prompt, data["target"])
                if data["target"] == "Ideogram4":
                    caption = json.loads(prompt)
                    text += " " + " ".join(element["desc"] for element in caption["compositional_deconstruction"]["elements"])
                if error := idea_action_error(plan_item["idea"], text):
                    raise SceneFidelityError(error)
            return prompt
        original = instruction
        for attempt in range(retries + 1):
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
                        prompt = normalize_workflow_output(recovered, data["target"], mode="Enhance",
                            expected_visible_text=expected_text)
                        prompt = validate_trigger_contract(prompt, data, progress)
                        prompt = validate_positive_content(prompt, data)
                        prompt = check_fidelity(prompt)
                    except PositiveContentError:
                        content_failure = True
                        progress("The pre-loop prefix still had invalid positive content after cleanup; retrying.")
                    except (WorkflowFormatError, ValueError, KeyError, TypeError):
                        progress("The pre-loop prefix was not a valid complete target prompt; retrying.")
                    else:
                        progress(f"Dataset prompt {index}/{data['amount']} recovered from the usable text before the repetition loop.")
                        return prompt
                if attempt >= retries:
                    raise BackendGenerationError(
                        f"Dataset prompt {index}/{data['amount']} produced runaway output after "
                        f"{retries} retries. {exc}"
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
            except BackendGenerationError as exc:
                self.checkpoint()
                if attempt >= retries:
                    raise BackendGenerationError(
                        f"Dataset prompt {index}/{data['amount']} could not be generated after {retries} retries. {exc}"
                    ) from exc
                progress(f"Dataset prompt {index}/{data['amount']} engine request failed: {exc} Retrying ({attempt + 1}/{retries}).")
                instruction = replace(original, diagnostic_stage=original.diagnostic_stage + f":transport_retry_{attempt + 1}")
                continue
            self.checkpoint()
            progress(f"Checking dataset prompt {index}/{data['amount']}")
            try:
                prompt = normalize_workflow_output(raw, data["target"], mode="Enhance",
                    expected_visible_text=expected_text)
                prompt = validate_trigger_contract(prompt, data, progress)
                return check_fidelity(validate_positive_content(prompt, data))
            except (WorkflowFormatError, ValueError, KeyError, TypeError) as exc:
                if attempt >= retries:
                    raise BackendGenerationError(
                        f"Dataset prompt {index}/{data['amount']} remained invalid after "
                        f"{retries} retries. {exc}"
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
                fidelity_failure = isinstance(exc, SceneFidelityError)
                instruction = replace(original,
                    system_message=(retry_system + "\n\nSCENE FIDELITY CORRECTION: Render the same fixed idea, primary action, props and geometry; do not replace the event with generic presentation."
                                    if fidelity_failure else dataset_content_repair(retry_system) if content_failure
                                    else dataset_format_repair(retry_system, exc)),
                    max_tokens=instruction.max_tokens,
                    hard_max_tokens=instruction.hard_max_tokens,
                    diagnostic_stage=original.diagnostic_stage
                    + f":{'scene' if fidelity_failure else 'content' if content_failure else 'format'}_retry_{attempt + 1}")

    def run(self, request, data, progress, partial, *, scenes_only=False, scene_action=None, valid_only=False):
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        assignments = dataset_assignments(data)
        results = list(data["results"]) if scene_action else []
        signature = scene_plan_signature(data, assignments)
        progress("Starting the prompt engine for the dataset…")
        with backend.generation_session() as session:
            planner = ScenePlanner(self.checkpoint)
            scenes = reusable_scene_plan(data, assignments, require_scenes=False, allow_pending=valid_only or scene_action is not None)
            if valid_only and (scenes is None or not any(scene_is_usable(row, data) for row in scenes)):
                raise ValueError("No valid scenes are available in the current saved plan.")
            if scenes_only and scenes and all(scene_is_usable(row, data) for row in scenes):
                scenes = None  # Explicit replanning of a completed plan still creates new ideas.
            if scene_action and scenes is None:
                raise ValueError("Per-scene actions need a current saved idea plan. Plan scenes first.")
            def save_planning_stage(rows):
                nonlocal scenes
                scenes = [{**row, "input": assignment["input"], "idea_status": row.get("idea_status", "valid"),
                           "scene_status": row.get("scene_status", "valid"), "prompt_status": row.get("prompt_status", "not_generated")}
                          for row, assignment in zip(rows, assignments)]
                partial({"ok": True, "kind": "dataset_scenes" if scenes_only else "dataset",
                         "prompts": list(results), "completed": len(results), "total": data["amount"],
                         "target": data["target"],
                         "scene_plan": [dict(row) for row in scenes], "scene_plan_signature": signature})
            if scenes is None:
                planned = planner.plan_batch(
                    session=session, data=data, assignments=assignments, family=family, progress=progress,
                    plan_update=save_planning_stage)
                scenes = [{**row, "input": assignment["input"], "idea_status": row.get("idea_status", "valid"),
                            "scene_status": row.get("scene_status", ("guided_fallback" if data["source_mode"] == "guided"
                                             and row["scene"] == assignment["input"] else "valid")),
                            "prompt_status": row.get("prompt_status", "not_generated")}
                          for row, assignment in zip(planned, assignments)]
            else:
                scenes = [dict(row) for row in scenes]
                progress("Reusing saved Scene Planner ideas for the selected target.")
            def publish():
                partial({"ok": True, "kind": "dataset", "prompts": list(results), "completed": len(results),
                         "total": data["amount"], "target": data["target"],
                         "scene_plan": [dict(row) for row in scenes], "scene_plan_signature": signature})
            selected = [row["index"] for row in scenes if scene_is_usable(row, data)] if valid_only else list(range(1, data["amount"] + 1))
            if scene_action:
                action, index = scene_action
                selected = [index]
                original = scenes[index - 1]
                if action != "regenerate_prompt":
                    original = {key: value for key, value in original.items() if key not in FAILURE_METADATA}
                results = [row for row in results if row["index"] != index]
                scenes[index - 1] = {**original, "prompt_status": "not_generated"}
                if action == "regenerate_idea":
                    try:
                        idea = planner.plan_ideas(session=session, data=data, assignments=assignments, family=family,
                            progress=progress, indexes=[index], existing=scenes)[0]
                    except BackendGenerationError as exc:
                        self.checkpoint()
                        scenes[index - 1] = failed_scene({**original, "replacement_attempted": True},
                            "Requested new idea failed: " + failure_reason(exc), stage="idea", dataset_type=data["trigger_type"])
                    else:
                        scenes[index - 1] = {**idea, "input": original["input"], "scene": "", "geometry": {},
                             "idea_status": "valid", "scene_status": "not_generated", "prompt_status": "not_generated"}
                    publish()
                elif action == "repair_scene":
                    scenes[index - 1] = {**original, "scene_status": "not_generated", "prompt_status": "not_generated"}
                    publish()
                    repaired = planner.recover_scene(session=session, data=data, assignments=assignments,
                        row=original, family=family, progress=progress,
                        existing_rows=[row for row in scenes if row["index"] != index])
                    scenes[index - 1] = {**repaired, "input": original["input"], "idea_status": repaired.get("idea_status", "valid"),
                                        "scene_status": repaired.get("scene_status", "valid"), "prompt_status": repaired.get("prompt_status", "not_generated")}
                elif action != "regenerate_prompt":
                    raise ValueError("Unknown per-scene action.")
            # Saved/manual idea edits invalidate only their downstream scene.
            pending = [scenes[index - 1] for index in selected if not scenes[index - 1]["scene"].strip()
                       and scenes[index - 1].get("scene_status") != "failed"]
            if pending:
                if scene_action and scene_action[0] == "regenerate_prompt":
                    raise ValueError("Compose or repair this scene before regenerating its prompt.")
                def save_composed(rows):
                    for composed in rows:
                        original = scenes[composed["index"] - 1]
                        scenes[composed["index"] - 1] = {**original, **composed,
                             "idea_status": composed.get("idea_status", "valid"), "prompt_status": composed.get("prompt_status", "not_generated")}
                    publish()
                composed = planner.compose(session=session, data=data, assignments=assignments, ideas=pending,
                    family=family, progress=progress, plan_update=save_composed)
                save_composed([{**row, "scene_status": row.get("scene_status", "valid")} for row in composed])
            for index in selected:
                row = scenes[index - 1]
                if row.get("scene_status") == "failed":
                    continue
                try:
                    row = scenes[index - 1] = resolve_framing_conflicts(row, dataset_type=data["trigger_type"])
                except ValueError:
                    pass  # Unknown staging facts still need a scene-local repair.
                # Saved/manual scenes may intentionally have no structured
                # staging. Validate their prose without rewriting it merely to
                # fill metadata. New model output and supplied staging still
                # enforce the same complete type profile in both modes.
                errors = [] if row.get("scene_status") == "guided_fallback" else geometry_errors(
                    row, dataset_type=data["trigger_type"], require_fields=bool(row.get("geometry")))
                if errors or row.get("scene_status") in {"not_generated", "geometry_warning"}:
                    if scene_action and scene_action[0] == "regenerate_prompt":
                        raise ValueError("Repair this scene's geometry before regenerating its prompt.")
                    scenes[index - 1] = {**row, "scene_status": "geometry_warning", "prompt_status": "not_generated"}
                    publish()
                    repaired = planner.recover_scene(session=session, data=data, assignments=assignments,
                        row=row, family=family, progress=progress, errors=errors,
                        existing_rows=[item for item in scenes if item["index"] != index])
                    scenes[index - 1] = {**row, **repaired, "scene_status": repaired.get("scene_status", "valid"),
                        "prompt_status": repaired.get("prompt_status", "not_generated")}
            duplicates = {row["index"] for row in analyze_idea_diversity(data, scenes)["ideas"] if row["issues"]}
            for index in selected:
                if scenes[index - 1].get("scene_status") == "failed":
                    continue
                if "idea_status" in scenes[index - 1]:
                    scenes[index - 1] = {**scenes[index - 1],
                        "idea_status": "duplicate_warning" if index in duplicates else "valid"}
                if "prompt_status" in scenes[index - 1]:
                    scenes[index - 1] = {**scenes[index - 1], "prompt_status": "not_generated"}
            scene_state = {"scene_plan": scenes, "scene_plan_signature": signature}
            if scenes_only:
                return {"ok": True, "kind": "dataset_scenes", **scene_state,
                        "backend": backend.name}
            # Publish the full plan before any final prompt, retaining it even if
            # the writer subsequently fails or the user ends generation.
            publish()
            for index in selected:
                self.checkpoint()
                if scenes[index - 1].get("scene_status") == "failed":
                    continue
                plan_item = {**assignments[index - 1], **scenes[index - 1]}
                instruction = dataset_instruction(request, data, index, (), family, plan_item)
                try:
                    prompt = self._generate(session, instruction, data, index, progress, plan_item)
                except BackendGenerationError as exc:
                    self.checkpoint()
                    original_reason = failure_reason(exc)
                    scenes[index - 1].update(prompt_status="failed", failure_stage="prompt",
                        failure_reason=original_reason)
                    progress(f"Skipping prompt {index}: {original_reason}")
                    publish()
                    continue
                seed = plan_item["input"]
                results.append({"index": index, "prompt": prompt, "input": seed,
                                "idea": plan_item["idea"], "scene": plan_item["scene"],
                                **{key: plan_item[key] for key in ("geometry",) if key in plan_item}})
                results.sort(key=lambda row: row["index"])
                if "prompt_status" in scenes[index - 1]:
                    scenes[index - 1] = {**scenes[index - 1], "prompt_status": "valid"}
                scenes[index - 1] = {key: value for key, value in scenes[index - 1].items()
                                    if key not in {"failure_reason", "failure_stage"}}
                publish()
            scene_state = {"scene_plan": scenes, "scene_plan_signature": signature}
        report = analyze_dataset_quality(data, results, assignments)
        return {"ok": True, "kind": "dataset", "prompts": results,
                "failed": sum(row.get("prompt_status") == "failed" for row in scenes),
                "completed": len(results), "total": data["amount"], "target": data["target"],
                **scene_state, "quality_report": report, "backend": backend.name}


def _parse_deep_review(raw, chunk):
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
    cleaned = []
    for position, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"index", "issues"} or item["index"] != expected[position] or not isinstance(item["issues"], list) or len(item["issues"]) > 5:
            raise WorkflowFormatError("Deep review records or prompt indexes are invalid.")
        issues = []
        for issue in item["issues"]:
            if (not isinstance(issue, dict) or set(issue) != {"category", "severity", "message"}
                    or issue["category"] not in DEEP_CATEGORIES or issue["severity"] not in {"warning", "error"}
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
                        reviewed.extend(_parse_deep_review(raw, chunk))
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
        report = analyze_dataset_quality(data, data["results"])
        merge_deep_review(report, reviewed)
        return {"ok": True, "kind": "dataset_review", "report": report,
                "reviewed": len(data["results"]), "backend": backend.name}
