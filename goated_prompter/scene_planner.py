"""Scene Planner service. Dataset owns the session; this skill owns scene ideation."""

import json
import hashlib
import logging
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal
from .dataset_visible_content import visible_content_error
from .dataset_staging import validate_geometry, validate_planned_geometry, geometry_errors, migrate_saved_geometry, resolve_framing_conflicts, STAGING_PROFILES
from .dataset_staging.engine import geometry_repair_locks, geometry_issues, semantic_geometry_fields
from .dataset_staging.rules.framing import framing_intent
from .dataset_quality import analyze_idea_diversity, idea_action_error
from .dataset_ideas import DatasetIdeasService, IDEA_DETAIL_FIELDS, MAX_FIELD_CHARACTERS
from .dataset_scene import DatasetSceneService, validate_self_check
from .dataset_constraints import compile_constraints, constraint_issues
from .scene_eligibility import scene_eligibility, scene_geometry_errors
from .planning.result import PlanningResult

from .backends.base import BackendGenerationError
from .prompting.scene_planner import (
    MAX_SCENE_CHARACTERS, MAX_SCENE_WORDS, MAX_IDEA_CHARACTERS, MAX_IDEA_WORDS, scene_planner_instruction,
    idea_planner_instruction, scene_composer_instruction,
    SCENE_FORMAT_CORRECTION, IDEA_FORMAT_CORRECTION,
)


SCENE_PLAN_VERSION = 5
SCENE_COMPOSER_CHUNK_SIZE = 4
SCENE_REPAIR_ATTEMPTS = 3
FAILURE_METADATA = {"failure_reason", "failure_stage", "replacement_attempted"}
logger = logging.getLogger(__name__)
PLAN_STATUS_VALUES = {
    "idea_status": {"valid", "not_generated", "duplicate_warning", "failed"},
    "scene_status": {"valid", "not_generated", "geometry_warning", "repair_required", "guided_fallback", "failed"},
    "prompt_status": {"valid", "not_generated", "failed"},
}
# Saved scenes can include original long guided inputs used as graceful fallbacks
# or plans from older builds. New LLM output uses the stricter shared limits.
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000


class SceneFormatError(ValueError):
    def __init__(self, message, indexes):
        super().__init__(message)
        self.correction = (SCENE_FORMAT_CORRECTION + "\nSchema error: " + message
            + "\nEvery object must include its index. Requested indexes in order: " + json.dumps(indexes))


@dataclass
class PlannerCallState:
    phase: Literal["initial", "repair", "transport_retry"] = "initial"
    correction: str = ""
    previous_output: str = ""
    last_error: Exception | None = None


def scene_plan_signature(data, assignments):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "variety", "constraints", "visual_style", "custom_style")}
    semantic["planning_mode"] = data.get("planning_mode", "Fast")
    semantic.update(version=SCENE_PLAN_VERSION, assignments=assignments)
    return hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def validate_saved_scene_plan(rows, *, dataset_type=None, allow_legacy_metadata=False):
    """Keep live input strict; historical checkpoint projections may omit opaque metadata."""
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError("Scene plan must contain at most 25 scenes.")
    cleaned = []
    fields = {"index", "input", "idea", "scene", "geometry", "self_check", "coverage_conflicts",
              *IDEA_DETAIL_FIELDS, *PLAN_STATUS_VALUES, *FAILURE_METADATA}
    for index, row in enumerate(rows, 1):
        if isinstance(row, dict):
            if allow_legacy_metadata:
                row = {key: value for key, value in row.items() if key in fields}
            # Only new deterministic crop diagnostics survive obsolete coverage metadata.
            conflicts = row.get("coverage_conflicts")
            row = {key: value for key, value in row.items() if key != "coverage_conflicts"}
            if conflicts == ["framing"] and isinstance(row.get("geometry"), dict) and row["geometry"].get("framing") in {"full_body", "full_subject"}:
                row["coverage_conflicts"] = conflicts
        if (not isinstance(row, dict) or not {"index", "input", "scene"} <= row.keys()
                or row.keys() - fields
                or type(row["index"]) is not int or row["index"] != index
                or not isinstance(row["input"], str) or len(row["input"]) > 10000
                or not isinstance(row["scene"], str) or len(row["scene"]) > MAX_STORED_SCENE_CHARACTERS):
            raise ValueError("Saved scenes require sequential indexes, input and scene text; idea is optional for legacy plans.")
        if "idea" in row and (not isinstance(row["idea"], str) or len(row["idea"]) > MAX_STORED_IDEA_CHARACTERS):
            raise ValueError("Saved idea must be text within the stored-input limit.")
        details = set(row) & set(IDEA_DETAIL_FIELDS)
        if details and (details != set(IDEA_DETAIL_FIELDS) or not row.get("idea", "").strip()
                or any(not isinstance(row[field], str) or not row[field].strip()
                       or len(row[field]) > MAX_FIELD_CHARACTERS for field in IDEA_DETAIL_FIELDS)):
            raise ValueError("Saved compact ideas require all five concise description fields alongside the idea.")
        validate_plan_metadata(row)
        row = dict(row)
        row["scene"] = " ".join(row["scene"].split())
        if "self_check" in row:
            row["self_check"] = validate_self_check(row["self_check"], allow_pending=True)
            if row["self_check"].startswith("REPAIR:"):
                row.update(scene_status="repair_required", prompt_status="not_generated")
        if "geometry" in row:
            row["geometry"], migrated = migrate_saved_geometry(row["geometry"], dataset_type=dataset_type)
            if migrated and row["scene"] and row.get("scene_status") not in {"failed", "guided_fallback"}:
                row.update(scene_status="geometry_warning", prompt_status="not_generated")
        cleaned.append(row)
    return cleaned


def reusable_scene_plan(data, assignments, *, require_scenes=True, allow_pending=False):
    rows = validate_saved_scene_plan(data.get("scene_plan", []), dataset_type=data["trigger_type"])
    if (data.get("scene_plan_signature") != scene_plan_signature(data, assignments)
            or len(rows) != data["amount"] or (not allow_pending and any("idea" in row and not row["idea"].strip()
                and row.get("scene_status") != "failed" for row in rows))
            or (require_scenes and any(not scene_eligibility(row, data).usable for row in rows))
             or any("self_check" not in row and (visible_content_error(row.get("idea", "")) or (row.get("scene_status") not in
                 {"not_generated", "geometry_warning", "repair_required", "failed"} and visible_content_error(row["scene"]))) for row in rows)
            or any(row["input"] != assignment["input"] for row, assignment in zip(rows, assignments))):
        return None
    return rows


def validate_plan_metadata(row):
    if "failure_reason" in row and (not isinstance(row["failure_reason"], str) or len(row["failure_reason"]) > 2000):
        raise ValueError("Failure reason must be text of at most 2000 characters.")
    if "failure_stage" in row and (not isinstance(row["failure_stage"], str) or row["failure_stage"] not in {"idea", "scene", "prompt"}):
        raise ValueError("Invalid failure stage.")
    if "replacement_attempted" in row and type(row["replacement_attempted"]) is not bool:
        raise ValueError("Replacement attempt must be enabled or disabled.")
    for key, allowed in PLAN_STATUS_VALUES.items():
        if key in row and (not isinstance(row[key], str) or row[key] not in allowed):
            raise ValueError(f"Invalid {key}.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Scene Planner returned duplicate JSON keys.")
        result[key] = value
    return result


def failure_reason(error):
    """Expose the last actionable validation error, not a traceback or full prompt."""
    cause = error.__cause__ or error
    if isinstance(cause, json.JSONDecodeError):
        return "The model did not return the required valid JSON array."
    return " ".join(getattr(cause, "correction", str(cause)).split())[:900] or "The model did not return a usable result."


def failed_scene(row, reason, *, stage="scene", dataset_type=None):
    result = {**row, "failure_reason": reason[:2000], "failure_stage": stage,
              "scene_status": "failed", "prompt_status": "failed"}
    result.setdefault("idea", "")
    result.setdefault("scene", "")
    result["idea_status"] = "valid" if result["idea"].strip() else "failed"
    try:
        result["geometry"] = validate_geometry(result.get("geometry", {}), dataset_type=dataset_type, require_fields=False)
    except ValueError:
        result["geometry"] = {}
    return result


def scene_unusable_reason(row, data):
    return scene_eligibility(row, data).reason


def scene_is_usable(row, data):
    return scene_eligibility(row, data).usable


def validate_scene_plan(raw, amount, *, guided_inputs=None, indexes=None, require_geometry=False, validate_geometry_fields=True,
                        allow_scene_errors=False, dataset_type=None):
    """Accept only the minimal JSON schema; never salvage fenced/broken output."""
    if guided_inputs is not None and (not isinstance(guided_inputs, list) or len(guided_inputs) != amount
                                     or any(not isinstance(value, str) for value in guided_inputs)):
        raise ValueError("Guided validation requires one source input per requested scene.")
    if not isinstance(raw, str):
        raise ValueError("Scene Planner must return a valid JSON array.")
    rows = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or len(rows) != amount:
        raise ValueError("Scene Planner must return exactly one scene per requested image.")
    cleaned, seen = [], {}
    indexes = indexes or list(range(1, amount + 1))
    for position, (index, row) in enumerate(zip(indexes, rows)):
        if (not isinstance(row, dict) or not {"index", "idea", "scene"} <= row.keys()
                or row.keys() - {"index", "idea", "scene", "geometry"}
                or (require_geometry and "geometry" not in row)
                or type(row["index"]) is not int or row["index"] != index):
            raise SceneFormatError("Scene Planner rows require requested integer indexes, idea, scene and optional geometry.", indexes)
        idea = row["idea"]
        if (not isinstance(idea, str) or not idea.strip()
                or len(idea) > MAX_IDEA_CHARACTERS or len(idea.split()) > MAX_IDEA_WORDS
                or "```" in idea or "\n" in idea.strip() or "\r" in idea.strip()):
            raise ValueError("Scene Planner ideas must be nonempty short concepts without markdown or multiple lines.")
        scene = row["scene"]
        scene_error = ""
        if isinstance(scene, str):
            scene = " ".join(scene.split())
        if (not isinstance(scene, str) or not scene.strip()
                or len(scene) > MAX_SCENE_CHARACTERS or len(scene.split()) > MAX_SCENE_WORDS
                or "```" in scene):
            scene_error = "Scene Planner scenes must be nonempty concise paragraphs without markdown fences."
            if not allow_scene_errors:
                raise ValueError(scene_error)
            scene = scene[:MAX_STORED_SCENE_CHARACTERS] if isinstance(scene, str) else ""
        scene = scene.strip()
        if error := visible_content_error(idea):
            raise ValueError(error)
        if error := visible_content_error(scene):
            if not allow_scene_errors:
                raise ValueError(error)
            scene_error = error
        signature = " ".join(scene.casefold().split())
        guided_input = " ".join(guided_inputs[position].split()) if guided_inputs is not None else ""
        if signature in seen:
            # Cycling/repeated authoritative guided lines may deliberately ask
            # for the same scene. Never exempt random or different guided inputs.
            if (not guided_input or guided_input != seen[signature]) and not allow_scene_errors:
                raise ValueError("Scene Planner returned identical scenes for different assignments; diversify while preserving each input. Exact repeats are allowed only for the same nonempty guided input.")
        seen[signature] = guided_input
        record = {"index": index, "idea": idea, "scene": scene}
        if scene_error:
            record["scene_error"] = scene_error
        if "geometry" in row:
            record["geometry"] = validate_geometry(row["geometry"], dataset_type=dataset_type) if validate_geometry_fields else row["geometry"]
        validate_plan_metadata(row)
        cleaned.append(record)
    return cleaned


def validate_idea_plan(raw, indexes):
    rows = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or len(rows) != len(indexes):
        raise ValueError("Idea Planner must return exactly the requested ideas.")
    for row, index in zip(rows, indexes):
        if (not isinstance(row, dict) or set(row) != {"index", "idea"}
                or type(row["index"]) is not int or row["index"] != index):
            raise ValueError("Idea Planner requires requested integer indexes and idea only.")
        idea = row["idea"]
        if (not isinstance(idea, str) or not idea.strip() or len(idea) > MAX_IDEA_CHARACTERS
                or len(idea.split()) > MAX_IDEA_WORDS or "\n" in idea or "\r" in idea or "```" in idea):
            raise ValueError("Idea Planner ideas must be short single-line concepts.")
        if error := visible_content_error(idea):
            raise ValueError(error)
        row["idea"] = idea.strip()
    return rows


class ScenePlanner:
    """Chunked Fast planning or Quality composition, with bounded local repairs."""

    def plan_result(self, **kwargs):
        rows = self.plan_batch(**kwargs)
        warnings = tuple(row.get("failure_reason", "Scene planning needs repair.") for row in rows if row.get("scene_status") == "failed")
        return PlanningResult(not warnings, rows, warnings=warnings, fallback_allowed=False,
                              status="partial" if warnings else "planned")

    def __init__(self, checkpoint, idea_history=None, semantic_validation=False, support_validation=False):
        self.checkpoint = checkpoint
        self.idea_history = idea_history
        self.semantic_validation = semantic_validation
        self.support_validation = support_validation
        self._accepted_scene_facts = {}
        self._scene_repair_contracts = {}

    def _audit_idea(self, session, data, assignments, row, family):
        from .planning.semantic_validation import invariant_contract, review_candidate
        local = assignments[row["index"] - 1].get("input", "")
        contract = invariant_contract(data["subject"] + "\n" + local,
            constraints=compile_constraints(data.get("constraints", "")), concept=data["subject"])
        contract["candidate_scope"] = "idea"
        return review_candidate(session, contract, json.dumps(row, ensure_ascii=False),
            stage=f"dataset:idea:{row['index']}", family=family, checkpoint=self.checkpoint,
            checks=("domain_relevance", "constraint_validity", *(["action_fidelity"] if local else [])))

    def _audit_scene(self, session, data, assignments, row, family):
        from .planning.semantic_validation import invariant_contract, review_candidate, SemanticValidationError
        from .planning.semantics import support_requirements
        source = "\n".join((data["subject"], assignments[row["index"] - 1].get("input", "")))
        support = (support_requirements(source) if self.support_validation
                   and isinstance(row.get("geometry"), dict) and row["geometry"].get("pose_type") == "custom" else [])
        if not self.semantic_validation and not support:
            return
        contract = invariant_contract(source, planned={"idea": row["idea"]}, constraints=compile_constraints(data.get("constraints", "")),
            concept=data["subject"], accepted_facts=self._accepted_scene_facts.get(row["index"], ()))
        if previous := self._scene_repair_contracts.get(row["index"]):
            if (previous["original_requirements"] == source
                    and previous["action_critical_facts"].get("idea") == row["idea"]):
                contract.update(previous)
                contract["accepted_facts"] = list(self._accepted_scene_facts.get(row["index"], ()))
            else:
                # A deliberate local idea replacement starts a new contract;
                # never leak the failed sibling's facts into its replacement.
                self._scene_repair_contracts.pop(row["index"], None)
                self._accepted_scene_facts.pop(row["index"], None)
                contract["accepted_facts"] = []
        try:
            preservation = ("repair_preservation",) if contract.get("previous_response") else ()
            reviews = []
            if support:
                reviews.append(("source_support", "support", ("action_fidelity", "scene_fidelity", *preservation)))
            if self.semantic_validation:
                reviews.append(("scene", "scene", ("action_fidelity", "scene_fidelity", "constraint_validity", "domain_relevance", *preservation)))
            for scope, stage, checks in reviews:
                facts = review_candidate(session, {**contract, "candidate_scope": scope,
                    "source_support_requirements": support}, json.dumps(row, ensure_ascii=False),
                    stage=f"dataset:{stage}:{row['index']}", family=family, checkpoint=self.checkpoint, checks=checks)
                contract["accepted_facts"] = list(facts)
        except SemanticValidationError as exc:
            facts = exc.accepted_facts or contract["accepted_facts"]
            evidence = [problem.get("evidence", "") for problem in exc.issues if problem.get("evidence")]
            self._accepted_scene_facts[row["index"]] = tuple(fact for fact in facts
                if not any(quote in fact or fact in quote for quote in evidence))
            raise
        self._accepted_scene_facts[row["index"]] = facts

    def plan_batch(self, *, session, data, assignments, family="qwen", progress, plan_update=None):
        if self.idea_history is not None:
            data = {**data, "_recent_ideas": self.idea_history.recent(data)}
        if data.get("planning_mode", "Fast") == "Quality" or data.get("_confirmed_intent"):
            if "requested_generation" in (data.get("_confirmed_intent") or {}):
                ideas = self.plan_ideas(session=session, data=data, assignments=assignments, family=family, progress=progress)
            else:
                try:
                    ideas = self.plan_ideas(session=session, data=data, assignments=assignments, family=family, progress=progress)
                except BackendGenerationError:
                    return self._fallback(data, assignments, progress)
            if plan_update:
                plan_update([{**row, "scene": "", "geometry": {}, "scene_status": "not_generated",
                    **({"self_check": ""} if "requested_generation" in (data.get("_confirmed_intent") or {}) else {})} for row in ideas])
            return self.compose(session=session, data=data, assignments=assignments, ideas=ideas, family=family,
                                progress=progress, plan_update=plan_update)
        state = [{"index": row["index"], "idea": "", "scene": "", "geometry": {},
                  "idea_status": "not_generated", "scene_status": "not_generated"} for row in assignments]
        if data.get("scene_plan_signature") == scene_plan_signature(data, assignments):
            saved = validate_saved_scene_plan(data.get("scene_plan", []), dataset_type=data["trigger_type"])
            incomplete = any(row.get("scene_status") == "failed" or not row.get("idea", "").strip() or not row["scene"].strip()
                or row.get("scene_status") in {"not_generated", "geometry_warning"} for row in saved)
            if incomplete and len(saved) == len(state) and all(row["input"] == assignment["input"]
                    for row, assignment in zip(saved, assignments)):
                state = [dict(row) for row in saved]
        def publish_chunk(rows):
            for row in rows:
                state[row["index"] - 1] = dict(row)
            if self.idea_history is not None:
                self.idea_history.remember(data, rows)
            if plan_update:
                plan_update([dict(row) for row in state])
        for start in range(0, len(state), SCENE_COMPOSER_CHUNK_SIZE):
            chunk = state[start:start + SCENE_COMPOSER_CHUNK_SIZE]
            # Fixed ideas from a partially checked chunk never go back through ideation.
            fixed = [row for row in chunk if row.get("scene_status") != "failed" and row.get("idea", "").strip() and
                     (not row["scene"].strip() or row.get("scene_status") in {"not_generated", "geometry_warning"})]
            for row in fixed:
                if not row["scene"].strip():
                    repaired = self.compose(session=session, data=data, assignments=assignments, ideas=[row],
                        family=family, progress=progress, plan_update=publish_chunk)[0]
                else:
                    repaired = self.recover_scene(session=session, data=data, assignments=assignments, row=row,
                        family=family, progress=progress, errors=geometry_errors(row, dataset_type=data["trigger_type"]),
                        existing_rows=[item for item in state if item.get("scene_status") == "valid"])
                publish_chunk([{**repaired, "idea_status": repaired.get("idea_status", "valid"),
                    "scene_status": repaired.get("scene_status", "valid")}])
            indexes = [row["index"] for row in chunk if row.get("scene_status") != "failed" and not row.get("idea", "").strip()]
            if not indexes:
                continue
            accepted = [row for row in state if row.get("idea", "").strip()]
            inputs = [assignments[index - 1]["input"] for index in indexes] if data["source_mode"] == "guided" else None
            try:
                rows = self._call(session,
                    lambda correction: scene_planner_instruction(data, assignments, family, correction,
                        indexes=indexes, existing=accepted),
                    lambda raw: validate_scene_plan(raw, len(indexes), indexes=indexes, guided_inputs=inputs,
                        validate_geometry_fields=False, allow_scene_errors=True, dataset_type=data["trigger_type"]),
                    progress, f"Scene Planner · chunk {indexes[0]}–{indexes[-1]}", scene_output=True)
            except BackendGenerationError as exc:
                # Isolate an unreadable chunk into bounded single-item requests.
                rows = []
                for index in indexes:
                    local_inputs = [assignments[index - 1]["input"]] if inputs is not None else None
                    try:
                        local = self._call(session,
                            lambda correction: scene_planner_instruction(data, assignments, family, correction,
                                indexes=[index], existing=accepted + rows),
                            lambda raw: validate_scene_plan(raw, 1, indexes=[index], guided_inputs=local_inputs,
                                validate_geometry_fields=False, allow_scene_errors=True, dataset_type=data["trigger_type"]),
                            progress, f"Scene Planner · scene {index}",
                            scene_output=True, attempts=SCENE_REPAIR_ATTEMPTS)
                        local = self._check_scenes(session, data, assignments, local, family, progress,
                            existing_rows=accepted + rows)
                        row = local[0]
                    except BackendGenerationError as local_error:
                        row = failed_scene(state[index - 1], failure_reason(local_error), dataset_type=data["trigger_type"])
                    rows.append(row)
                    publish_chunk([{**row, "scene_status": row.get("scene_status", "valid")}])
            else:
                rows = self._check_scenes(session, data, assignments, rows, family, progress,
                    plan_update=publish_chunk, existing_rows=[row for row in accepted if row.get("scene_status") == "valid"])
            publish_chunk([{**row, "idea_status": row.get("idea_status", "valid"), "scene_status": row.get("scene_status", (
                "guided_fallback" if data["source_mode"] == "guided" and row["scene"] == assignments[row["index"] - 1]["input"]
                else "valid"))} for row in rows])
        return [{key: value for key, value in row.items() if key != "input"
                 and (key not in PLAN_STATUS_VALUES or row.get("scene_status") == "failed")} for row in state]

    def _fallback(self, data, assignments, progress):
        if data["source_mode"] != "guided":
            raise BackendGenerationError("Dataset planning failed after retries. No useful automatic ideas were produced; revise the concept or retry planning.")
        progress("Scene Planner unavailable; using each supplied guided input directly.")
        return [{"index": row["index"], "idea": row["input"] or data["subject"], "scene": row["input"] or data["subject"]}
                for row in assignments]

    def _call(self, session, build, validate, progress, label, *, scene_output=False, attempts=2):
        state = PlannerCallState()
        for attempt in range(attempts):
            self.checkpoint()
            progress(f"{label} · {'retrying transport' if state.phase == 'transport_retry' else 'repairing output' if attempt else 'planning'}…")
            try:
                instruction = build(state.correction)
                if state.phase == "transport_retry":
                    instruction = replace(instruction, diagnostic_stage=instruction.diagnostic_stage + f":transport_retry_{attempt}")
                if state.previous_output:
                    context = json.loads(instruction.user_message)
                    context["previous_response"] = state.previous_output[:instruction.stream_character_limit]
                    instruction = replace(instruction, user_message=json.dumps(context, ensure_ascii=False))
                session.validate_instruction(instruction)
                raw = session.generate(instruction)
                state.previous_output = raw if isinstance(raw, str) else ""
                self.checkpoint()
                return validate(raw)
            except json.JSONDecodeError as exc:
                self.checkpoint()
                state.last_error = exc
                state.phase = "repair"
                logger.warning("%s JSON parse failure: %s", label, exc, exc_info=True)
                state.correction = SCENE_FORMAT_CORRECTION if scene_output else IDEA_FORMAT_CORRECTION
                progress(f"{label} returned invalid JSON; repairing output format only.")
            except BackendGenerationError as exc:
                self.checkpoint()
                state.last_error = exc
                state.phase = "transport_retry"
                progress(f"{label} engine request failed; retrying the same stage request.")
            except (ValueError, TypeError, RecursionError) as exc:
                self.checkpoint()
                state.last_error = exc
                state.phase = "repair"
                state.correction = getattr(exc, "correction", str(exc))
                logger.warning("%s validation failure: %s", label, exc)
                progress(f"{label} failed validation: {state.correction}")
        raise BackendGenerationError(f"Dataset {label} failed after retries. {state.correction or str(state.last_error)}",
            completion_state=getattr(state.last_error, "completion_state", "provider_error"),
            partial_text=getattr(state.last_error, "partial_text", ""), finish_reason=getattr(state.last_error, "finish_reason", None)) from state.last_error

    def plan_ideas(self, *, session, data, assignments, family="qwen", progress, indexes=None, existing=()):
        if self.idea_history is not None:
            data = {**data, "_recent_ideas": self.idea_history.recent(data)}
        if "requested_generation" in (data.get("_confirmed_intent") or {}):
            rows = DatasetIdeasService(self.checkpoint).run(session=session, data=data,
                assignments=assignments, family=family, progress=progress, indexes=indexes, existing=existing)
            if self.idea_history is not None:
                self.idea_history.remember(data, rows)
            return rows
        indexes = indexes or list(range(1, data["amount"] + 1))
        previous = {row["index"]: row["idea"] for row in existing if row["index"] in indexes}
        def validate_initial(raw):
            result = validate_idea_plan(raw, indexes)
            for row in result:
                if row["index"] in previous:
                    comparison = [{"index": 0, "idea": previous[row["index"]]}, row]
                    if any(issue["code"] == "exact_duplicate_idea" for record in analyze_idea_diversity(data, comparison)["ideas"] for issue in record["issues"]):
                        raise ValueError("Create a genuinely new idea rather than repeating the replaced idea.")
            return result
        rows = self._call(session,
            lambda correction: idea_planner_instruction(data, assignments, family, correction, indexes=indexes, existing=existing),
            validate_initial, progress, "Idea Planner")
        # Audit locally, then replace only later members of duplicate groups.
        # Guided/Focused scope exemptions live in the diversity checker.
        accepted = [dict(row) for row in existing if row["index"] not in indexes]
        for position, row in enumerate(rows):
            relevance_error = None
            if self.semantic_validation:
                from .planning.semantic_validation import SemanticValidationError
                try:
                    self._audit_idea(session, data, assignments, row, family)
                except SemanticValidationError as exc:
                    relevance_error = str(exc)
            audit = analyze_idea_diversity(data, accepted + [row])
            if relevance_error or any(issue["code"] == "exact_duplicate_idea" for record in audit["ideas"] if record["index"] == row["index"] for issue in record["issues"]):
                exclusions = accepted + rows[position + 1:]
                def validate_new(raw):
                    new = validate_idea_plan(raw, [row["index"]])
                    audit = analyze_idea_diversity(data, exclusions + new)
                    if any(issue["code"] == "exact_duplicate_idea" for record in audit["ideas"] if record["index"] == row["index"] for issue in record["issues"]):
                        raise ValueError("Replacement idea still repeats an existing idea's meaning.")
                    if self.semantic_validation:
                        self._audit_idea(session, data, assignments, new[0], family)
                    return new
                rows[position] = self._call(session,
                    lambda correction: idea_planner_instruction(data, assignments, family,
                        ("CONCEPT RELEVANCE CORRECTION: " + relevance_error + ". Keep a meaningful procedure inside the concept; novelty is subordinate to relevance. " if relevance_error else "") + correction,
                        indexes=[row["index"]], existing=exclusions),
                    validate_new, progress, f"Idea Planner · replace idea {row['index']}")[0]
            accepted.append(rows[position])
        if self.idea_history is not None:
            self.idea_history.remember(data, rows)
        return rows

    def compose(self, *, session, data, assignments, ideas, family="qwen", progress, plan_update=None):
        if "requested_generation" in (data.get("_confirmed_intent") or {}):
            rows = [{**idea, "self_check": "", "geometry": {}, "scene": idea.get("scene", ""),
                     "scene_status": "not_generated", "prompt_status": "not_generated"} for idea in ideas]
            for position, idea in enumerate(ideas):
                row = DatasetSceneService(self.checkpoint).run(session=session, data=data,
                    assignment=assignments[idea["index"] - 1], idea=idea, family=family, progress=progress)
                rows[position] = row
                if plan_update:
                    plan_update([dict(item) for item in rows])
            return rows
        # Always publish a loadable state with every fixed idea, including pending
        # chunks. A retry/reload can compose only unfinished rows, never re-ideate.
        state = [{**row, "scene": "", "geometry": {}, "scene_status": "not_generated"} for row in ideas]
        def publish_chunk(rows):
            by_index = {row["index"]: row for row in rows}
            for position, item in enumerate(state):
                if item["index"] in by_index:
                    state[position] = {**{field: item[field] for field in IDEA_DETAIL_FIELDS if field in item},
                                       **by_index[item["index"]]}
            if plan_update:
                plan_update([dict(item) for item in state])
        for start in range(0, len(ideas), SCENE_COMPOSER_CHUNK_SIZE):
            chunk = ideas[start:start + SCENE_COMPOSER_CHUNK_SIZE]
            indexes = [row["index"] for row in chunk]
            inputs = [assignments[index - 1]["input"] for index in indexes] if data["source_mode"] == "guided" else None
            existing = {row["index"]: row for row in [*data.get("scene_plan", []), *state[:start]]
                         if row["index"] not in indexes and row.get("scene", "").strip()
                         and row.get("scene_status", "valid") == "valid"}
            recovery_context = [*existing.values(), *[row for row in state if row["index"] not in indexes and not row["scene"].strip()]]
            try:
                rows = self._call(session,
                    lambda correction: scene_composer_instruction(data, assignments, chunk, family, correction),
                    lambda raw: validate_scene_plan(raw, len(chunk), indexes=indexes, guided_inputs=inputs,
                        validate_geometry_fields=False, allow_scene_errors=True, dataset_type=data["trigger_type"]),
                    progress, f"Scene Composer · chunk {indexes[0]}–{indexes[-1]}", scene_output=True)
            except BackendGenerationError as exc:
                rows = []
                for idea in chunk:
                    row = self.recover_scene(session=session, data=data, assignments=assignments,
                        row={**idea, "scene": "", "geometry": {}},
                        family=family, progress=progress, errors=[failure_reason(exc)],
                        existing_rows=[*recovery_context, *rows])
                    rows.append(row)
                    publish_chunk([{**row, "scene_status": row.get("scene_status", "valid")}])
            else:
                rows = self._check_scenes(session, data, assignments, rows, family, progress, chunk, publish_chunk,
                                          existing_rows=recovery_context)
            publish_chunk([{**row, "scene_status": row.get("scene_status", "valid")} for row in rows])
        return [{key: value for key, value in row.items() if key != "scene_status"
                 or row.get("scene_status") == "failed"} for row in state]

    def _check_scenes(self, session, data, assignments, rows, family, progress, ideas=None, plan_update=None, existing_rows=()):
        fixed = {row["index"]: row["idea"] for row in (ideas or rows)}
        details = {row["index"]: {field: row[field] for field in IDEA_DETAIL_FIELDS if field in row} for row in (ideas or rows)}
        rows = [{**details[row["index"]], **row} for row in rows]
        scene_errors = {row["index"]: row.pop("scene_error", "") for row in rows}
        replaced = {row["index"] for row in (ideas or rows) if row.get("replacement_attempted")}
        checked = list(existing_rows)
        for position, row in enumerate(rows):
            semantic_issues = ()
            scene_error = scene_errors[row["index"]]
            if row["index"] in replaced:
                row["replacement_attempted"] = True
            try:
                if "geometry" in row:
                    row["geometry"] = validate_planned_geometry(row["geometry"], dataset_type=data["trigger_type"], scene=row["scene"])
                    row = rows[position] = resolve_framing_conflicts(row, dataset_type=data["trigger_type"], intent=framing_intent(data, row))
                elif ideas is not None or STAGING_PROFILES[data["trigger_type"]].required:
                    raise ValueError("Scene Composer must include a structured geometry object.")
                errors = geometry_errors(row, dataset_type=data["trigger_type"])
            except ValueError as exc:
                logger.warning("Scene %s geometry validation failure: %s", row["index"], exc)
                errors = [getattr(exc, "correction", str(exc))]
            if scene_error:
                errors.append(scene_error)
            errors.extend(framing_intent(data, {**row, "input": assignments[row["index"] - 1]["input"]}).errors_for(row))
            compiled = compile_constraints(data.get("constraints", ""))
            errors.extend(issue["message"] for text in (row["idea"], row["scene"])
                          for issue in constraint_issues(text, compiled) if issue["severity"] == "error")
            if data.get("planning_mode") == "Quality":
                if error := idea_action_error(fixed[row["index"]], row["scene"]):
                    errors.append(error)
            if row["idea"] != fixed[row["index"]]:
                errors.append("Echo the fixed idea unchanged; compose it instead of replacing it.")
            if error := duplicate_scene_error(row, checked, data, assignments):
                errors.append(error)
            if not errors:
                try:
                    self._audit_scene(session, data, assignments, row, family)
                except ValueError as exc:
                    errors.append(str(exc))
                    semantic_issues = getattr(exc, "issues", ())
            if errors:
                if plan_update:
                    # Publish loadable stage state even if a local repair later fails.
                    pending = [{**item, "idea": fixed[item["index"]]} for item in rows]
                    for item in pending:
                        try:
                            item["geometry"] = validate_geometry(item.get("geometry", {}), dataset_type=data["trigger_type"], require_fields=False)
                        except ValueError:
                            item["geometry"] = {}
                            item["scene_status"] = "geometry_warning"
                        if geometry_errors(item, dataset_type=data["trigger_type"]):
                            item["scene_status"] = "geometry_warning"
                        if scene_errors[item["index"]]:
                            item["scene_status"] = "geometry_warning"
                    pending[position]["scene_status"] = "geometry_warning"
                    plan_update(pending)
                rows[position] = self.recover_scene(session=session, data=data, assignments=assignments,
                    row={**row, "idea": fixed[row["index"]]}, family=family, progress=progress, errors=errors,
                    existing_rows=[*checked, *rows[position + 1:]], semantic_issues=semantic_issues)
            if rows[position].get("scene_status") != "failed":
                checked.append(rows[position])
        return rows

    def recover_scene(self, *, session, data, assignments, row, family="qwen", progress, errors=(), existing_rows=(), semantic_issues=()):
        if "requested_generation" in (data.get("_confirmed_intent") or {}):
            return DatasetSceneService(self.checkpoint).run(session=session, data=data,
                assignment=assignments[row["index"] - 1], idea=row, family=family, progress=progress, repair=True)
        try:
            return self.repair_scene(session=session, data=data, assignments=assignments, row=row,
                family=family, progress=progress, errors=errors, existing_rows=existing_rows,
                attempts=SCENE_REPAIR_ATTEMPTS, semantic_issues=semantic_issues)
        except BackendGenerationError as exc:
            reason = failure_reason(exc)
            progress(f"Scene {row['index']} needs a local retry: {reason}")
            return failed_scene(row, reason, dataset_type=data["trigger_type"])

    def repair_scene(self, *, session, data, assignments, row, family="qwen", progress, errors=(), existing_rows=(), attempts=SCENE_REPAIR_ATTEMPTS, semantic_issues=()):
        semantic_defects = list(deepcopy(semantic_issues))
        defective_fields = semantic_geometry_fields(row, semantic_defects)
        locked_geometry = deepcopy(geometry_repair_locks(row, dataset_type=data["trigger_type"], defective_fields=defective_fields))
        intent = framing_intent(data, {**row, "input": assignments[row["index"] - 1]["input"]})
        local_crop = intent.crop if intent.locked else None
        if local_crop:
            locked_geometry["framing"] = local_crop  # Source outranks supporting plan.
        problems = geometry_issues(row, data["trigger_type"])
        defective_fields.update(field for problem in problems for field in problem.fields)
        # A malformed optional metadata field does not authorize rewriting valid
        # scene prose. Semantic/prose defects still use the existing scene repair.
        preserve_scene = (not semantic_defects and bool(problems) and all(problem.code in {"staging_schema", "support_contact_metadata"} for problem in problems)
            and bool(row.get("scene", "").strip()) and not visible_content_error(row["scene"])
            and len(row["scene"]) <= MAX_SCENE_CHARACTERS and len(row["scene"].split()) <= MAX_SCENE_WORDS
            and not any(problem.fields == ("pose_detail",) for problem in problems))
        compiled = compile_constraints(data.get("constraints", ""))
        if (any(problem["severity"] == "error" for problem in constraint_issues(row.get("scene", ""), compiled))
                or duplicate_scene_error(row, existing_rows, data, assignments)
                or (data.get("planning_mode") == "Quality" and idea_action_error(row["idea"], row.get("scene", "")))):
            preserve_scene = False  # Real content defects must remain repairable.
        if local_crop and (not isinstance(row.get("geometry"), dict) or row["geometry"].get("framing") != local_crop):
            preserve_scene = False
        from .planning.semantic_validation import invariant_contract
        source = "\n".join((data["subject"], assignments[row["index"] - 1].get("input", "")))
        def support_contract():
            supporting = deepcopy(row)
            if isinstance(supporting.get("geometry"), dict):
                for field in defective_fields:
                    supporting["geometry"].pop(field, None)
            evidence = [problem.get("evidence", "") for problem in semantic_defects if problem.get("evidence")]
            accepted = [fact for fact in self._accepted_scene_facts.get(row["index"], ())
                        if not any(quote in fact or fact in quote for quote in evidence)]
            return {**invariant_contract(source, planned=supporting, constraints=compiled, concept=data["subject"],
                        accepted_facts=accepted),
                    "previous_response": json.dumps(row, ensure_ascii=False), "listed_defect": " ".join(errors),
                    "known_semantic_defects": deepcopy(semantic_defects)}
        self._scene_repair_contracts[row["index"]] = support_contract()
        def validate(raw):
            nonlocal preserve_scene
            result = validate_scene_plan(raw, 1, indexes=[row["index"]], require_geometry=True, validate_geometry_fields=False)[0]
            if not isinstance(result["geometry"], dict):
                raise ValueError("Repair geometry must be an object.")
            result["geometry"] = {**result["geometry"], **deepcopy(locked_geometry)}
            if preserve_scene:
                result["scene"] = row["scene"]
            result["geometry"] = validate_planned_geometry(result["geometry"], dataset_type=data["trigger_type"], scene=result["scene"])
            result = resolve_framing_conflicts(result, dataset_type=data["trigger_type"], intent=intent)
            if result["idea"] != row["idea"]:
                raise ValueError("Repair must preserve the fixed idea exactly.")
            if framing_errors := intent.errors_for(result):
                raise ValueError(" ".join(framing_errors))
            if problems := geometry_errors(result, dataset_type=data["trigger_type"]):
                raise ValueError(" ".join(problems))
            if error := duplicate_scene_error(result, existing_rows, data, assignments):
                raise ValueError(error)
            compiled = compile_constraints(data.get("constraints", ""))
            for text in (result["idea"], result["scene"]):
                if problems := [issue for issue in constraint_issues(text, compiled) if issue["severity"] == "error"]:
                    raise ValueError(problems[0]["message"])
            if data.get("planning_mode") == "Quality" and (error := idea_action_error(row["idea"], result["scene"])):
                raise ValueError(error)
            try:
                self._audit_scene(session, data, assignments, result, family)
            except ValueError as exc:
                # A metadata-only retry can uncover a semantic defect. Carry its
                # exact field evidence into the next bounded attempt; otherwise
                # copying the original locks back makes correction impossible.
                if issues := getattr(exc, "issues", ()):
                    preserve_scene = False
                    semantic_defects.extend(deepcopy(problem) for problem in issues if problem not in semantic_defects)
                    defective_fields.update(semantic_geometry_fields(result, issues))
                    locked_geometry.clear()
                    locked_geometry.update(deepcopy(geometry_repair_locks(row, dataset_type=data["trigger_type"], defective_fields=defective_fields)))
                    if local_crop:
                        locked_geometry["framing"] = local_crop
                    self._scene_repair_contracts[row["index"]] = support_contract()
                raise
            return result
        def build(correction):
            from .planning.semantic_validation import repair_contract
            instruction = scene_composer_instruction(data, assignments, [row], family,
                (correction + "\n" + " ".join(errors) if correction.startswith("SCENE OUTPUT FORMAT CORRECTION")
                 else " ".join(errors) + " " + correction)
                + " Preserve the fixed idea, important action and required props.", previous=row)
            contract = support_contract()
            context = json.loads(instruction.user_message)
            context["repair_contract"] = repair_contract(contract, json.dumps(row, ensure_ascii=False), " ".join(errors) + " " + correction)
            context["locked_geometry"] = locked_geometry
            context["locked_scene_prose"] = row["scene"] if preserve_scene else None
            context["repair_policy"] = "Repair only diagnosed defects, not unrelated creative staging. locked_geometry fields are unchanged; echo them and keep scene prose consistent with them. Fields implicated by quoted known_semantic_defects are repairable, not accepted invariants. Source support/contact requirements outrank a defective supporting plan. Preserve unusual geometry, overlap and required visible anatomy. Never widen crop to expose an extremity or substitute a conventional pose."
            return replace(instruction, user_message=json.dumps(context, ensure_ascii=False))
        result = self._call(session,
            build,
            validate, progress, f"Scene Composer · repair scene {row['index']}", scene_output=True, attempts=attempts)
        result.update({field: row[field] for field in IDEA_DETAIL_FIELDS if field in row})
        if row.get("replacement_attempted"):
            result["replacement_attempted"] = True
        if row.get("coverage_conflicts"):
            result["coverage_conflicts"] = row["coverage_conflicts"]
        return result


def duplicate_scene_error(row, existing, data, assignments):
    """Retain the old batch duplicate guard across chunk boundaries."""
    signature = " ".join(row["scene"].casefold().split())
    for other in existing:
        if other.get("scene_status") == "failed":
            continue
        if other["index"] == row["index"] or " ".join(other["scene"].casefold().split()) != signature:
            continue
        source = assignments[row["index"] - 1]["input"]
        previous = assignments[other["index"] - 1]["input"]
        if data["source_mode"] == "guided" and source.strip() and " ".join(source.split()) == " ".join(previous.split()):
            continue
        return "This scene duplicates another assignment. Compose only this fixed idea as a distinct scene; do not change or brainstorm ideas."
    return ""
