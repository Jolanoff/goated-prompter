"""Approved Dataset batches: compact ideas, frozen scenes, Builder enhancement."""

from dataclasses import replace

from ...backends.factory import create_backend
from ...backends.base import BackendGenerationError, BackendRunawayError
from ...contracts import effective_model_family
from ...director_profiles import resolve_director_config
from .prompting import dataset_instruction
from ...options.dataset import DATASET_SOURCES, DATASET_TYPES, LIBRARY_EXTRAS
from ...prompt_library import library_file_name, load_library
from ...options.lengths import PROMPT_LENGTH_NAMES
from ...options.creativity import CREATIVITY_NAMES
from ...options.styles import STYLE_NAMES
from ...options.targets import TARGET_MODEL_NAMES, canonical_target
from ...workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text, requested_visible_text
from .assignments import dataset_assignments
from .quality import analyze_idea_diversity
from .triggers import trigger_presence_error, trigger_terms, fixed_anima_prefix, restore_numeric_trigger_spelling
from ...prompt_library import copied_reference
from ...output_repetition import MAX_ANIMA_TAGS, anima_tag_count, anima_tag_key, anima_tags, drop_supplied_tags
from .visible_content import PositiveContentError, positive_prompt_error, sanitize_positive_prompt
from .plan import (ScenePlanner, MAX_STORED_SCENE_CHARACTERS, MAX_STORED_IDEA_CHARACTERS,
                           reusable_scene_plan, scene_plan_signature, validate_saved_scene_plan,
                           failure_reason, failed_scene, scene_is_usable, FAILURE_METADATA, PLAN_FIELDS)


DATASET_MAX_RETRIES = 3


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "trigger_at_start": False, "trigger_connected": True, "expand_trigger": False,
        "amount": 12,
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "constraints": "",
        "creativity": "Balanced", "style": "Auto", "library_extras": "drop", "results": [], "result_job_id": "",
        "scene_plan": [], "scene_plan_signature": "", "plan_scenes_first": False,
    }


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{label} must be a {'nonempty ' if required else ''}string of at most {limit} characters.")
    return value


def validate_dataset_draft(value, *, generation=False, planning=False):
    defaults = default_dataset_draft()
    if not isinstance(value, dict):
        raise ValueError("Invalid Dataset settings fields.")
    result = {**defaults, **{key: item for key, item in value.items() if key in defaults}}
    result["trigger"] = _text(result["trigger"], "Trigger / prepend", 1000, required=generation and not planning).strip()
    result["subject"] = _text(result["subject"], "Dataset concept", 10000, required=generation).strip()
    for key, label, limit in (("custom_type", "Custom subject kind", 120),
                              ("inputs", "Guided inputs", 50000), ("constraints", "Dataset constraints", 10000),
                              ("result_job_id", "Result job id", 128), ("scene_plan_signature", "Scene plan signature", 128)):
        result[key] = _text(result[key], label, limit)
    for key, allowed in (("trigger_type", DATASET_TYPES), ("source_mode", DATASET_SOURCES),
                         ("creativity", CREATIVITY_NAMES), ("style", STYLE_NAMES),
                         ("library_extras", LIBRARY_EXTRAS), ("length", PROMPT_LENGTH_NAMES)):
        if not isinstance(result[key], str) or result[key] not in allowed:
            raise ValueError(f"Invalid Dataset {key}.")
    result["target"] = canonical_target(result["target"])
    if result["target"] not in TARGET_MODEL_NAMES:
        raise ValueError("Invalid target model.")
    if generation and result["target"] == "Anima" and anima_tag_count(result["trigger"], tag_only=True) > MAX_ANIMA_TAGS:
        raise ValueError("Anima allows at most 100 tags. Your supplied trigger already exceeds this limit; edit it before generating.")
    _text(result["director_preset"], "Director preset", 256)
    if type(result["amount"]) is not int or not 1 <= result["amount"] <= 25:
        raise ValueError("Dataset prompt amount must be between 1 and 25.")
    for key in ("trigger_at_start", "trigger_connected", "expand_trigger", "plan_scenes_first"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be enabled or disabled.")
    if result["trigger_type"] == "Custom" and generation and not result["custom_type"].strip():
        raise ValueError("Describe the custom subject kind before generating.")
    if result["source_mode"] == "guided" and generation and not any(line.strip() for line in result["inputs"].splitlines()):
        raise ValueError("Add at least one guided input, one per line.")
    if result["source_mode"] == "library" and generation and not load_library(result["target"]).prompts:
        raise ValueError(f"Add prompts to data/prompt_library/{library_file_name(result['target'])} "
                         f"to plan scenes from your library for {result['target']}.")
    result["scene_plan"] = validate_saved_scene_plan(result["scene_plan"])
    if not isinstance(result["results"], list) or len(result["results"]) > 25:
        raise ValueError("Dataset results must be an array of at most 25 prompts.")
    cleaned = []
    for item in result["results"]:
        if (not isinstance(item, dict) or not {"index", "prompt", "input"} <= item.keys()
                or item.keys() - {"index", "prompt", "input", "idea", "scene"}
                or type(item["index"]) is not int or not 1 <= item["index"] <= 25):
            raise ValueError("Each Dataset result requires index, prompt and input, with optional idea and scene text.")
        record = {"index": item["index"], "prompt": _text(item["prompt"], "Dataset prompt", 100000),
                  "input": _text(item["input"], "Dataset input", 10000)}
        for key, limit in (("scene", MAX_STORED_SCENE_CHARACTERS), ("idea", MAX_STORED_IDEA_CHARACTERS)):
            if key in item:
                record[key] = _text(item[key], f"Dataset {key}", limit)
        cleaned.append(record)
    result["results"] = cleaned
    return result


def saved_dataset_draft(value):
    """Read saved prompts without making obsolete plans executable or rewriting disk."""
    if not isinstance(value, dict):
        raise ValueError("Invalid saved Dataset draft.")
    result = {key: item for key, item in value.items() if key in default_dataset_draft()}
    result["results"] = [{key: item for key, item in row.items() if key in {"index", "input", "idea", "scene", "prompt"}}
                         if isinstance(row, dict) else row for row in result.get("results", [])]
    rows = result.get("scene_plan", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid saved scenes.")
    obsolete = any("self_check" not in row or row.keys() - PLAN_FIELDS for row in rows)
    if obsolete:
        # Check retained text/index types even when obsolete state is discarded.
        projected = [{**{key: item for key, item in row.items() if key in PLAN_FIELDS},
                      "idea": row.get("idea", ""), "self_check": row.get("self_check", ""),
                      "scene_status": "not_generated", "prompt_status": "not_generated"} for row in rows]
        validate_saved_scene_plan(projected)
        result.update(scene_plan=[], scene_plan_signature="")
    return validate_dataset_draft(result)


class TriggerContractError(ValueError):
    """Exact protected wording is a final-output invariant."""


def validate_trigger_contract(prompt, data, progress=None):
    cleaned = prompt if data["target"] == "Ideogram4" else sanitize_prompt_text(prompt)
    error = trigger_presence_error(cleaned, data["trigger"], data["target"], expand=data["expand_trigger"])
    if error and not data["expand_trigger"]:
        raise TriggerContractError(error)
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
    def __init__(self, config, checkpoint, idea_history=None):
        self.config, self.checkpoint, self.idea_history = config, checkpoint, idea_history

    def _generate(self, session, instruction, data, index, progress, plan_item, *, retries=DATASET_MAX_RETRIES):
        expected_text = requested_visible_text(plan_item["scene"])
        original = instruction
        def validate(raw):
            prompt = normalize_workflow_output(raw, data["target"], mode="Enhance", expected_visible_text=expected_text)
            if prefix := fixed_anima_prefix(data):
                tail = prompt[len(prefix):] if prompt.startswith(prefix) else None
                if tail is not None and (not tail or tail.lstrip(" \t")[:1] in ",;:\r\n"):
                    prompt = tail.lstrip(",;: \t\r\n")
                if not prompt:
                    raise WorkflowFormatError("The locked trigger is inserted by the app; return the accepted scene description as well.")
                supplied = {anima_tag_key(tag) for tag in anima_tags(prefix, tag_only=True)}
                generated = anima_tags(prompt)
                if any(anima_tag_key(tag) in supplied for tag in generated):
                    # The app inserts the inventory itself, so restated character tags
                    # (often respelled, e.g. "2boys" or unescaped "(series)") are dropped, not fatal.
                    cleaned = drop_supplied_tags(prompt, prefix)
                    if cleaned is None:
                        raise WorkflowFormatError("Generated scene tags repeat supplied tags. Return only useful new scene tags and scene prose; the app inserts the protected inventory once.")
                    prompt = cleaned
                    generated = anima_tags(prompt)
                if anima_tag_count(prefix, tag_only=True) + len(generated) > MAX_ANIMA_TAGS:
                    raise WorkflowFormatError("Anima allows at most 100 tags, including supplied tags. Reduce added scene tags, preserving the scene prose.")
                prompt = normalize_workflow_output(prefix + ("" if prompt[:1] in "\r\n" else ", ") + prompt,
                                                   data["target"], mode="Enhance")
            if not data["expand_trigger"]:
                corrected = restore_numeric_trigger_spelling(prompt, data["trigger"], data["target"])
                if corrected != prompt:
                    session.emit_activity("normalization", workflow="dataset", index=index, operation="numeric_trigger_spelling")
                    progress(f"Dataset prompt {index}: restored the supplied numeric trigger spelling.")
                    prompt = corrected
            if original.reference_prompts and copied_reference(prompt, original.reference_prompts):
                raise WorkflowFormatError("The prompt copied wording from a library reference prompt. Write new wording "
                                          "for this scene; use the references only for style and quality.")
            return validate_positive_content(validate_trigger_contract(prompt, data, progress), data)
        for attempt in range(retries + 1):
            self.checkpoint()
            progress(f"{'Retrying' if attempt else 'Waiting for'} prompt engine · dataset prompt {index}/{data['amount']}")
            session.validate_instruction(instruction)
            try:
                raw = session.generate(instruction)
            except BackendRunawayError as exc:
                self.checkpoint()
                recovered = getattr(exc, "recoverable_text", "")
                if recovered and len(recovered.split()) >= 30 and recovered.rstrip().endswith((".", "!", "?", "}")):
                    try:
                        prompt = validate(recovered)
                    except (ValueError, KeyError, TypeError):
                        pass
                    else:
                        progress(f"Dataset prompt {index} recovered from the complete pre-loop output.")
                        return prompt
                if attempt >= retries:
                    raise
                instruction = replace(original,
                    system_message=original.system_message + "\nOUTPUT CORRECTION: Write a shorter finite prompt for the accepted scene. Finish without repetition.",
                    max_tokens=max(384, int(original.max_tokens * (.8 ** (attempt + 1)))),
                    hard_max_tokens=max(384, int(original.hard_max_tokens * (.8 ** (attempt + 1)))),
                    diagnostic_stage=original.diagnostic_stage + f":loop_retry_{attempt + 1}", temperature=.25, top_p=.85)
                continue
            except BackendGenerationError:
                self.checkpoint()
                if attempt >= retries:
                    raise
                instruction = replace(instruction, diagnostic_stage=original.diagnostic_stage + f":transport_retry_{attempt + 1}")
                continue
            self.checkpoint()
            try:
                prompt = validate(raw)
            except (WorkflowFormatError, ValueError, KeyError, TypeError) as exc:
                session.emit_activity("validation", workflow="dataset", attempt=attempt, accepted=False, error=str(exc))
                if attempt >= retries:
                    raise BackendGenerationError(f"Dataset prompt {index} remained invalid after {retries} retries. {exc}") from exc
                instruction = replace(instruction,
                    system_message=original.system_message + "\nFINAL OUTPUT CORRECTION: " + str(exc),
                    diagnostic_stage=original.diagnostic_stage + f":output_retry_{attempt + 1}", temperature=.25, top_p=.85)
            else:
                session.emit_activity("validation", workflow="dataset", attempt=attempt, accepted=True)
                return prompt

    def run(self, request, data, progress, partial, *, scenes_only=False, scene_action=None, valid_only=False, resume=False):
        if resume and (scenes_only or scene_action):
            raise ValueError("Continue is only available for batch prompt generation.")
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = effective_model_family(request, profile, effective)
        assignments = dataset_assignments(data)
        results = list(data["results"]) if scene_action else []
        signature = scene_plan_signature(data, assignments)
        progress("Starting the prompt engine for the dataset…")
        with backend.generation_session() as session:
            planner = ScenePlanner(self.checkpoint, idea_history=self.idea_history)
            scenes = reusable_scene_plan(data, assignments, require_scenes=False, allow_pending=valid_only or scene_action is not None)
            if valid_only and (scenes is None or not any(scene_is_usable(row, data) for row in scenes)):
                raise ValueError("No valid scenes are available in the current saved plan.")
            if scenes_only and scenes and all(scene_is_usable(row, data) for row in scenes):
                scenes = None
            if scene_action and scenes is None:
                raise ValueError("Per-scene actions need a current saved idea plan. Plan scenes first.")
            def publish():
                partial({"ok": True, "kind": "dataset_scenes" if scenes_only else "dataset", "prompts": list(results),
                         "completed": len(results), "total": data["amount"], "target": data["target"],
                         "scene_plan": [dict(row) for row in scenes], "scene_plan_signature": signature})
            def save_planning_stage(rows):
                nonlocal scenes
                scenes = [{**row, "input": assignment["input"], "idea_status": row.get("idea_status", "valid"),
                           "scene_status": row.get("scene_status", "valid"), "prompt_status": row.get("prompt_status", "not_generated")}
                          for row, assignment in zip(rows, assignments)]
                publish()
            def save_composed(rows):
                for composed in rows:
                    original = scenes[composed["index"] - 1]
                    scenes[composed["index"] - 1] = {**original, **composed}
                publish()
            def repair_pending_ideas():
                indexes = [row["index"] for row in scenes if row.get("failure_stage") == "idea"]
                if not indexes or scene_action or valid_only or resume:
                    return []
                self.checkpoint()
                progress(f"Repairing {len(indexes)} failed/repeated ideas after the valid batch work…")
                try:
                    repaired = planner.plan_ideas(session=session, data=data, assignments=assignments, family=family,
                        progress=progress, indexes=indexes, existing=scenes, allow_partial=True)
                except BackendGenerationError as error:
                    self.checkpoint()
                    for index in indexes:
                        scenes[index - 1] = {**scenes[index - 1], "failure_reason": "Idea repair failed: " + failure_reason(error)}
                    publish()
                    return []
                for row in repaired:
                    scenes[row["index"] - 1] = {**row, "input": assignments[row["index"] - 1]["input"],
                        "scene": "", "self_check": "", "scene_status": row.get("scene_status", "not_generated"),
                        "prompt_status": row.get("prompt_status", "not_generated"), "idea_status": row.get("idea_status", "valid")}
                publish()
                valid = [row for row in repaired if row.get("idea_status") != "failed"]
                for row in valid:
                    try:
                        planner.compose(session=session, data=data, assignments=assignments, ideas=[row],
                            family=family, progress=progress, plan_update=save_composed)
                    except BackendGenerationError as error:
                        self.checkpoint()
                        index = row["index"]
                        scenes[index - 1] = failed_scene(scenes[index - 1], failure_reason(error), stage="scene")
                        publish()
                return [row["index"] for row in valid if scene_is_usable(scenes[row["index"] - 1], data)]
            if scenes is None:
                planned = planner.plan_batch(session=session, data=data, assignments=assignments, family=family,
                    progress=progress, plan_update=save_planning_stage)
                save_planning_stage(planned)
            else:
                scenes = [dict(row) for row in scenes]
                progress("Reusing saved Dataset ideas and scenes for the selected target.")
            completed = {}
            if resume:
                by_index = {row["index"]: row for row in scenes}
                for item in data["results"]:
                    row = by_index.get(item["index"])
                    if (row and scene_is_usable(row, data) and row.get("prompt_status") == "valid"
                            and item["prompt"].strip()
                            and all(item.get(field) == row.get(field, "") for field in ("input", "idea", "scene"))):
                        completed[item["index"]] = dict(item)
                results = sorted(completed.values(), key=lambda item: item["index"])
            selected = [row["index"] for row in scenes if scene_is_usable(row, data)] if valid_only else list(range(1, data["amount"] + 1))
            selected = [index for index in selected if index not in completed]
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
                        scenes[index - 1] = failed_scene(original, "Requested new idea failed: " + failure_reason(exc), stage="idea")
                    else:
                        scenes[index - 1] = {**idea, "input": original["input"], "scene": "", "self_check": "",
                            "idea_status": "valid", "scene_status": "not_generated", "prompt_status": "not_generated"}
                    publish()
                elif action == "repair_scene":
                    scenes[index - 1] = {**original, "self_check": "", "scene_status": "not_generated", "prompt_status": "not_generated"}
                    publish()
                    repaired = planner.repair_scene(session=session, data=data, assignments=assignments,
                        row=original, family=family, progress=progress)
                    scenes[index - 1] = {**repaired, "input": original["input"]}
                elif action != "regenerate_prompt":
                    raise ValueError("Unknown per-scene action.")
            pending = [scenes[index - 1] for index in selected if scenes[index - 1].get("scene_status") != "failed"
                       and (not scenes[index - 1]["scene"].strip() or not scenes[index - 1].get("self_check"))]
            if pending:
                if scene_action and scene_action[0] == "regenerate_prompt":
                    raise ValueError("Compose or repair this scene before regenerating its prompt.")
                composed = planner.compose(session=session, data=data, assignments=assignments, ideas=pending,
                    family=family, progress=progress, plan_update=save_composed)
                save_composed(composed)
            duplicates = {row["index"] for row in analyze_idea_diversity(data, scenes)["ideas"] if row["issues"]}
            for index in selected:
                if scenes[index - 1].get("scene_status") != "failed":
                    scenes[index - 1].update(idea_status="duplicate_warning" if index in duplicates else "valid", prompt_status="not_generated")
            if scenes_only:
                repair_pending_ideas()
                return {"ok": True, "kind": "dataset_scenes", "prompts": [], "scene_plan": scenes,
                        "scene_plan_signature": signature, "backend": backend.name}
            publish()
            def write_prompts(indexes):
                for index in indexes:
                    self.checkpoint()
                    if not scene_is_usable(scenes[index - 1], data):
                        continue
                    plan_item = {**assignments[index - 1], **scenes[index - 1]}
                    instruction = dataset_instruction(request, data, index, model_family=family, plan_item=plan_item)
                    try:
                        prompt = self._generate(session, instruction, data, index, progress, plan_item)
                    except BackendGenerationError as exc:
                        self.checkpoint()
                        scenes[index - 1].update(prompt_status="failed", failure_stage="prompt", failure_reason=failure_reason(exc))
                        publish()
                        continue
                    results.append({"index": index, "prompt": prompt, "input": plan_item["input"],
                                    "scene": plan_item["scene"], "idea": plan_item["idea"]})
                    results.sort(key=lambda row: row["index"])
                    scenes[index - 1] = {key: value for key, value in scenes[index - 1].items() if key not in FAILURE_METADATA}
                    scenes[index - 1]["prompt_status"] = "valid"
                    publish()
            write_prompts(selected)
            write_prompts(repair_pending_ideas())
        return {"ok": True, "kind": "dataset", "prompts": results,
                "failed": sum(row.get("prompt_status") == "failed" for row in scenes),
                "completed": len(results), "total": data["amount"], "target": data["target"],
                "scene_plan": scenes, "scene_plan_signature": signature, "backend": backend.name}
