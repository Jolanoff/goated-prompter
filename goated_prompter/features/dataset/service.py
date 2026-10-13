"""Approved Dataset batches: compact ideas, frozen scenes, Builder enhancement."""

from dataclasses import replace

from ...backends.factory import create_backend
from ...backends.base import BackendGenerationError, BackendRunawayError
from ...contracts import effective_model_family
from ...director_profiles import resolve_director_config
from .prompting import dataset_instruction, drop_wrong_count_tags, geometry_error, instruction_leak_error
from ...options.dataset import DATASET_SOURCES, DATASET_TYPES, MAX_SEED, SEED_MODES
from ...options.lengths import PROMPT_LENGTH_NAMES
from ...options.creativity import CREATIVITY_NAMES
from ...options.styles import STYLE_NAMES
from ...options.targets import TARGET_MODEL_NAMES, canonical_target
from ...workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text, requested_visible_text
from .assignments import dataset_assignments
from .quality import (ADULTS_ONLY, BROKEN_ANATOMY, adults_only_error, analyze_idea_diversity, broken_anatomy,
                      minor_reference)
from .triggers import (trigger_presence_error, trigger_terms, fixed_anima_prefix, restore_numeric_trigger_spelling,
                       tidy_expanded_trigger)
from .understanding import label_replacements, replace_labels
from . import private_vocabulary
from .validation import batch_requirements, text_signature, validation_strategies, verify_batch_requirements, verify_scenes
from .scene_spec import SceneSpec
from .routing import assignment_scope, image_hard_requirements, resolve_routes, scoped_request
from ...prompt_library import copied_reference
from ...output_repetition import (MAX_ANIMA_TAGS, anima_tag_count, anima_tag_key, anima_tags, drop_repeated_tags,
                                 drop_supplied_tags, remove_contradictory_solo)
from .visible_content import PositiveContentError, positive_prompt_error, sanitize_positive_prompt
from .plan import (ScenePlanner, MAX_STORED_SCENE_CHARACTERS, MAX_STORED_IDEA_CHARACTERS,
                           reusable_scene_plan, scene_plan_signature, validate_saved_scene_plan,
                           failure_reason, failed_scene, scene_is_usable, FAILURE_METADATA, PLAN_FIELDS)


DATASET_MAX_RETRIES = 1
FINAL_BATCH_FAILURE = ("Final prompts did not satisfy the approved dataset-wide requirements. "
                       "Review coverage and retry the affected prompts.")


class SeededSession:
    """A generation session that sends the batch seed with every request that has none."""

    def __init__(self, session, seed, *, private_content=False):
        self._session, self._seed = session, seed
        self._private_content = private_content

    def generate(self, instruction):
        if instruction.seed is None and self._seed is not None:
            instruction = replace(instruction, seed=self._seed)
        if self._private_content:
            instruction = replace(instruction, diagnostic_context={**(instruction.diagnostic_context or {}), "private_content": True})
        return self._session.generate(instruction)

    def __getattr__(self, name):
        return getattr(self._session, name)


def default_dataset_draft():
    return {
        "trigger": "", "trigger_type": "Character", "custom_type": "", "subject": "",
        "trigger_at_start": False, "trigger_connected": True, "expand_trigger": True,
        "amount": 12,
        "source_mode": "random", "inputs": "", "target": "Generic", "length": "Medium",
        "director_preset": "general_director", "constraints": "",
        "creativity": "Balanced", "style": "Auto", "results": [], "result_job_id": "",
        "scene_plan": [], "scene_plan_signature": "", "plan_scenes_first": False,
        "seed": 0, "seed_mode": "randomize",
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
    if result["source_mode"] == "library":
        result["source_mode"] = "random"  # "From my library" was removed; ideas never come from the library.
    result["trigger"] = _text(result["trigger"], "Trigger / prepend", 1000, required=generation and not planning).strip()
    result["subject"] = _text(result["subject"], "Dataset concept", 10000, required=generation).strip()
    for key, label, limit in (("custom_type", "Custom subject kind", 120),
                              ("inputs", "Guided inputs", 50000), ("constraints", "Dataset constraints", 10000),
                              ("result_job_id", "Result job id", 128), ("scene_plan_signature", "Scene plan signature", 128)):
        result[key] = _text(result[key], label, limit)
    for key, allowed in (("trigger_type", DATASET_TYPES), ("source_mode", DATASET_SOURCES),
                         ("creativity", CREATIVITY_NAMES), ("style", STYLE_NAMES), ("length", PROMPT_LENGTH_NAMES)):
        if not isinstance(result[key], str) or result[key] not in allowed:
            raise ValueError(f"Invalid Dataset {key}.")
    result["target"] = canonical_target(result["target"])
    if result["target"] not in TARGET_MODEL_NAMES:
        raise ValueError("Invalid target model.")
    if generation and result["target"] == "Anima" and anima_tag_count(result["trigger"], tag_only=True) > MAX_ANIMA_TAGS:
        raise ValueError("Anima allows at most 100 tags. Your supplied trigger already exceeds this limit; edit it before generating.")
    _text(result["director_preset"], "Director preset", 256)
    if type(result["seed"]) is not int or not 0 <= result["seed"] <= MAX_SEED:
        raise ValueError(f"Seed must be a whole number from 0 to {MAX_SEED}.")
    if result["seed_mode"] not in SEED_MODES:
        raise ValueError("Invalid seed mode.")
    if type(result["amount"]) is not int or not 1 <= result["amount"] <= 25:
        raise ValueError("Dataset prompt amount must be between 1 and 25.")
    for key in ("trigger_at_start", "trigger_connected", "expand_trigger", "plan_scenes_first"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be enabled or disabled.")
    if result["trigger_type"] == "Custom" and generation and not result["custom_type"].strip():
        raise ValueError("Describe the custom subject kind before generating.")
    if result["source_mode"] == "guided" and generation and not any(line.strip() for line in result["inputs"].splitlines()):
        raise ValueError("Add at least one guided input, one per line.")
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
        if (data.get("_confirmed_intent") or {}).get("subjects"):
            route = resolve_routes(data, [{"index": index}])[assignment_scope(data, index)]
            data = {**data, "_confirmed_intent": {**data["_confirmed_intent"], "characters": list(route.subjects)}}
        expected_text = requested_visible_text(plan_item["scene"])
        spec = SceneSpec.from_dict(plan_item["scene_spec"])
        strategies = validation_strategies(spec)
        original = instruction
        rejected_texts = {}
        def validate(raw, attempt):
            warnings = []
            prompt = normalize_workflow_output(raw, data["target"], mode="Enhance", expected_visible_text=expected_text)
            if data["target"] == "Anima":
                prompt = drop_wrong_count_tags(drop_repeated_tags(remove_contradictory_solo(prompt)), data)
            if data["expand_trigger"]:
                prompt = tidy_expanded_trigger(prompt, data["trigger"], data["target"], plan_item["scene"])
            if labels := label_replacements((data.get("_confirmed_intent") or {}).get("characters")):
                prompt = replace_labels(prompt, labels)
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
            if conflicting_view := geometry_error(prompt):
                raise WorkflowFormatError(conflicting_view)
            if optional_view := geometry_error(prompt, plan_item["scene"]):
                warnings.append(optional_view)
            if leak := instruction_leak_error(prompt, plan_item["scene"]):
                raise WorkflowFormatError(leak)
            if spec.route == "adult" and strategies["anatomy_subjects"] and (word := minor_reference(prompt)):
                raise WorkflowFormatError(f'{ADULTS_ONLY} ("{word}")')
            if strategies["anatomy_subjects"] and (word := broken_anatomy(prompt)):
                raise WorkflowFormatError(f'{BROKEN_ANATOMY} ("{word}")')

            if original.reference_prompts and copied_reference(prompt, original.reference_prompts):
                raise WorkflowFormatError("The prompt copied wording from a library reference prompt. Write new wording "
                                          "for this scene; use the references only for style and quality.")
            prompt = validate_positive_content(validate_trigger_contract(prompt, data, progress), data)
            if plan_item.get("scene_spec"):
                verified = verify_scenes(session, [{**plan_item, "scene": prompt}], self.checkpoint,
                                         family=original.model_family, kind="prompt")[0]
                status = verified["scene_status"]
                signature = text_signature(prompt)
                if status == "failed":
                    rejected_texts[signature] = verified["failure_reason"]
                elif status != "valid" and signature in rejected_texts:
                    raise WorkflowFormatError(rejected_texts[signature])
                if status == "failed" or status == "repair_required" and attempt < retries:
                    raise WorkflowFormatError("Repair only these final-prompt fidelity problems, preserving the other details: "
                        + verified.get("failure_reason", "Essential fidelity conflict."))
                warnings.extend(verified.get("quality_warnings", []))
                if status == "repair_required":
                    warnings.append("Unresolved after the bounded repair: " + verified["failure_reason"])
                plan_item.update(prompt_status="valid" if status == "valid" and not warnings else "unverified", quality_warnings=warnings)
                for warning in warnings:
                    progress(f"Dataset prompt {index} unverified: {warning}")
            return prompt
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
                        prompt = validate(recovered, attempt)
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
                prompt = validate(raw, attempt)
            except (WorkflowFormatError, ValueError, KeyError, TypeError) as exc:
                session.emit_activity("validation", workflow="dataset", attempt=attempt, accepted=False, error=str(exc))
                if attempt >= retries:
                    label = "retry" if retries == 1 else "retries"
                    raise BackendGenerationError(f"Dataset prompt {index} remained invalid after {retries} {label}. {exc}") from exc
                instruction = replace(instruction,
                    system_message=original.system_message + "\nFINAL OUTPUT CORRECTION: " + str(exc),
                    diagnostic_stage=original.diagnostic_stage + f":output_retry_{attempt + 1}", temperature=.25, top_p=.85)
            else:
                session.emit_activity("validation", workflow="dataset", attempt=attempt, accepted=True)
                return prompt

    def run(self, request, data, progress, partial, *, scenes_only=False, scene_action=None, valid_only=False, resume=False):
        if resume and (scenes_only or scene_action):
            raise ValueError("Continue is only available for batch prompt generation.")
        if scene_action and scene_action[0] not in {"regenerate_idea", "regenerate_prompt", "validate_scene"}:
            raise ValueError("Unknown per-scene action.")
        routes = resolve_routes(data, dataset_assignments(data))
        for scope, route in routes.items():
            scoped = scoped_request(data, scope)
            scoped["_confirmed_intent"] = {**(data.get("_confirmed_intent") or {}), "characters": list(route.subjects)}
            if route.profile == "adult" and (blocked := adults_only_error(scoped, include_director=False)):
                raise ValueError(blocked)
        private_content = any((row.get("scene_spec") or {}).get("private_vocabulary") for row in data["scene_plan"])
        if not private_content and any(route.vocabulary_applicable for route in routes.values()):
            private_content = bool(private_vocabulary.load_vocabulary())
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = effective_model_family(request, profile, effective)
        assignments = dataset_assignments(data)
        results = list(data["results"]) if scene_action else []
        signature = scene_plan_signature(data, assignments)
        progress("Starting the prompt engine for the dataset…")
        # Batch runs use the draft's seed for the app's picks and the model's sampling; regenerating
        # one idea or prompt stays random. A fixed seed repeats a batch, so history must not reject it.
        seed = None if scene_action else data["seed"]
        history = None if seed is not None and data["seed_mode"] == "fixed" else self.idea_history
        with backend.generation_session() as engine:
            session = SeededSession(engine, seed, private_content=private_content)
            planner = ScenePlanner(self.checkpoint, idea_history=history)
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
                    scenes[composed["index"] - 1] = {**composed, "input": original["input"]}
                publish()
            def repair_pending_ideas():
                indexes = [row["index"] for row in scenes if row.get("failure_stage") in {"idea", "scene"}
                           and not row.get("edited_stage")]
                if not indexes or scene_action or valid_only or resume:
                    return []
                self.checkpoint()
                progress(f"Repairing {len(indexes)} failed/repeated ideas after the valid batch work…")
                try:
                    repaired = planner.plan_ideas(session=session, data=data, assignments=assignments, family=family,
                        progress=progress, indexes=indexes, existing=scenes, allow_partial=True, seed=seed)
                except BackendGenerationError as error:
                    self.checkpoint()
                    for index in indexes:
                        scenes[index - 1] = {**scenes[index - 1], "failure_reason": "Idea repair failed: " + failure_reason(error)}
                    publish()
                    return []
                for row in repaired:
                    scenes[row["index"] - 1] = {**row, "input": assignments[row["index"] - 1]["input"],
                        "scene": row.get("scene", ""), "self_check": "", "scene_status": row.get("scene_status", "not_generated"),
                        "prompt_status": row.get("prompt_status", "not_generated"), "idea_status": row.get("idea_status", "valid")}
                valid = [row for row in repaired if row.get("idea_status") != "failed"]
                planner.compose(valid, plan_update=save_composed, session=session,
                                checkpoint=self.checkpoint, family=family, verify=scenes_only)
                publish()
                return [row["index"] for row in valid if scene_is_usable(scenes[row["index"] - 1], data)]
            if scenes is None:
                planned = planner.plan_batch(session=session, data=data, assignments=assignments, family=family,
                    progress=progress, plan_update=save_planning_stage, seed=seed, verify=scenes_only)
                save_planning_stage(planned)
            else:
                scenes = [dict(row) for row in scenes]
                progress("Reusing saved Dataset ideas and scenes for the selected target.")
            available_indexes = [row["index"] for row in scenes if scene_is_usable(row, data)]
            if data.get("_confirmed_intent"):
                for slot, row in enumerate(scenes):
                    spec = SceneSpec.from_dict(row["scene_spec"])
                    hard = image_hard_requirements(data, assignment_scope(data, row["index"]))
                    candidate = SceneSpec.from_dict(replace(spec, hard=hard).to_dict())
                    if spec.signature != candidate.signature:
                        updated = {**row, "scene_spec": candidate.to_dict(), "self_check": "",
                            "scene_status": "unverified", "prompt_status": "not_generated"}
                        updated.pop("scene_validation", None)
                        scenes[slot] = updated
            completed = {}
            if resume:
                by_index = {row["index"]: row for row in scenes}
                for item in data["results"]:
                    row = by_index.get(item["index"])
                    if (row and scene_is_usable(row, data) and row.get("prompt_status") in {"valid", "unverified"}
                            and item["prompt"].strip()
                            and all(item.get(field) == row.get(field, "") for field in ("input", "idea", "scene"))):
                        completed[item["index"]] = dict(item)
                results = sorted(completed.values(), key=lambda item: item["index"])
            selected = available_indexes if valid_only else list(range(1, data["amount"] + 1))
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
                        scenes[index - 1] = {**idea, "input": original["input"], "self_check": "",
                            "idea_status": "valid", "scene_status": "not_generated", "prompt_status": "not_generated"}
                    publish()
                elif action not in {"regenerate_prompt", "validate_scene"}:
                    raise ValueError("Unknown per-scene action.")
            pending = [scenes[index - 1] for index in selected if scenes[index - 1].get("scene_status") != "failed"
                       and scenes[index - 1].get("failure_stage") != "idea"
                       and scenes[index - 1]["scene"].strip() and (scenes[index - 1].get("edited_stage")
                            or not scenes[index - 1].get("scene_validation") and scenes[index - 1].get("scene_status") != "unverified"
                            or scene_action and scene_action[0] == "validate_scene")]
            if pending:
                planner.compose(pending, plan_update=save_composed, session=session,
                                checkpoint=self.checkpoint, family=family)
            duplicates = {row["index"] for row in analyze_idea_diversity(data, scenes)["ideas"] if row["issues"]}
            for index in selected:
                if scenes[index - 1].get("scene_status") != "failed":
                    scenes[index - 1].update(idea_status="duplicate_warning" if index in duplicates else "valid", prompt_status="not_generated")
            def check_batch(rows, field="scene"):
                proof = verify_batch_requirements(session, data, rows, self.checkpoint, family=family, field=field)
                if batch_requirements(data):
                    for row in scenes:
                        row["batch_validation"] = proof
                return proof["valid"]
            if scenes_only:
                repair_pending_ideas()
                usable = check_batch(scenes) and any(scene_is_usable(row, data) for row in scenes)
                return {"ok": usable, "kind": "dataset_scenes", "prompts": [], "scene_plan": scenes,
                          "scene_plan_signature": signature, "backend": backend.name,
                          **({} if usable else {"error": "No usable Dataset scenes were generated. Review the failed or unresolved scene slots and retry."})}
            batch_valid = True
            if scene_action and scene_action[0] == "validate_scene":
                publish()
                return {"ok": True, "kind": "dataset_scenes", "prompts": results, "scene_plan": scenes,
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
                    scenes[index - 1].update(prompt_status=plan_item["prompt_status"], quality_warnings=plan_item["quality_warnings"])
                    publish()
            write_prompts(selected)
            write_prompts(repair_pending_ideas())
            if results and batch_requirements(data):
                batch_valid = check_batch(results, field="prompt")
            publish()
        return {"ok": bool(results) and batch_valid, "kind": "dataset", "prompts": results,
                "failed": sum(not scene_is_usable(row, data) or row.get("prompt_status") == "failed" for row in scenes),
                "completed": len(results), "total": data["amount"], "target": data["target"],
                "scene_plan": scenes, "scene_plan_signature": signature, "backend": backend.name,
                **({} if results and batch_valid else {"error":
                    FINAL_BATCH_FAILURE
                    if results else "No usable Dataset prompts were generated. Review the failed or unresolved scene slots and retry."})}
