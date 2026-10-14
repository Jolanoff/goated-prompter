"""Dataset idea orchestration and saved-plan boundaries; ideas arrive as finished scenes."""

import hashlib
import json
import secrets

import random

from ...backends.base import BackendGenerationError
from .batch_planner import plan_scene_specs, propose_scene_specs
from .brainstorm import brainstorm_events, uses_event_seeds
from .routing import resolve_routes
from .ideas import DatasetIdeasService, creative_directions
from .eligibility import scene_eligibility, validate_self_check
from .private_vocabulary import load_vocabulary, Vocabulary
from .scene_spec import SceneSpec
from .validation import verify_scenes


SCENE_PLAN_VERSION = 18
# Small local models write better ideas a few at a time than as one long list.
IDEAS_PER_CALL = 5
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000
FAILURE_METADATA = {"failure_reason", "failure_stage"}
PLAN_STATUS_VALUES = {
    "idea_status": {"valid", "not_generated", "duplicate_warning", "failed"},
    "scene_status": {"valid", "unverified", "not_generated", "repair_required", "failed"},
    "prompt_status": {"valid", "unverified", "not_generated", "failed"},
}
PLAN_FIELDS = {"index", "input", "idea", "scene", "self_check", "selected_position", "selected_setting", "scene_spec", "scene_validation", "batch_validation", "quality_warnings", "edited_stage", *PLAN_STATUS_VALUES, *FAILURE_METADATA}


def scene_plan_signature(data, assignments):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "constraints")}
    semantic.update(version=SCENE_PLAN_VERSION, assignments=assignments)
    return hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def validate_plan_metadata(row):
    if "quality_warnings" in row and (not isinstance(row["quality_warnings"], list) or len(row["quality_warnings"]) > 100
            or any(not isinstance(warning, str) or len(warning) > 2000 for warning in row["quality_warnings"])):
        raise ValueError("Invalid Dataset quality warnings.")
    if "batch_validation" in row:
        proof = row["batch_validation"]
        if (not isinstance(proof, dict) or set(proof) != {"valid", "signature", "errors"}
                or type(proof["valid"]) is not bool or not isinstance(proof["signature"], str) or len(proof["signature"]) != 64
                or not isinstance(proof["errors"], list) or len(proof["errors"]) > 24
                or any(not isinstance(error, str) or len(error) > 2000 for error in proof["errors"])):
            raise ValueError("Invalid dataset-wide validation evidence.")
    if "scene_spec" in row:
        spec = SceneSpec.from_dict(row["scene_spec"])
        if spec.index != row["index"]:
            raise ValueError("SceneSpec index must match its saved slot.")
    if "edited_stage" in row and row["edited_stage"] not in {"idea", "scene"}:
        raise ValueError("Invalid edited Dataset stage.")
    if "scene_validation" in row:
        proof = row["scene_validation"]
        if (not isinstance(proof, dict) or set(proof) != {"text_signature", "spec_signature", "observation"}
                or any(not isinstance(proof[key], str) or len(proof[key]) != 64 for key in ("text_signature", "spec_signature"))
                or not isinstance(proof["observation"], dict) or len(json.dumps(proof)) > 100000):
            raise ValueError("Invalid saved scene validation evidence.")
    for key in ("selected_position", "selected_setting"):
        if key in row and (not isinstance(row[key], str)
                or not row[key].strip() or len(row[key]) > MAX_STORED_SCENE_CHARACTERS):
            raise ValueError(f"{key.replace('_', ' ').capitalize()} must be nonempty text of at most 10000 characters.")
    if "failure_reason" in row and (not isinstance(row["failure_reason"], str) or len(row["failure_reason"]) > 2000):
        raise ValueError("Failure reason must be text of at most 2000 characters.")
    if "failure_stage" in row and (not isinstance(row["failure_stage"], str) or row["failure_stage"] not in {"idea", "scene", "prompt"}):
        raise ValueError("Invalid failure stage.")
    for key, allowed in PLAN_STATUS_VALUES.items():
        if key in row and (not isinstance(row[key], str) or row[key] not in allowed):
            raise ValueError(f"Invalid {key}.")


def invalidate_scene_edit(row, stage, *, clear_failure=True):
    """An edited description needs fresh evidence; retain its text and approved specification."""
    stale = {"scene_validation", "selected_position", "selected_setting", "quality_warnings"}
    if clear_failure:
        stale.update(FAILURE_METADATA)
    return {**{key: value for key, value in row.items() if key not in stale},
        "edited_stage": stage, "self_check": "", "scene_status": "not_generated", "prompt_status": "not_generated"}


def validate_saved_scene_plan(rows):
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError("Scene plan must contain at most 25 scenes.")
    cleaned = []
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or not {"index", "input", "idea", "scene", "self_check"} <= row.keys()
                or row.keys() - PLAN_FIELDS or type(row["index"]) is not int or row["index"] != index
                or not isinstance(row["input"], str) or len(row["input"]) > 10000
                or not isinstance(row["idea"], str) or len(row["idea"]) > MAX_STORED_IDEA_CHARACTERS
                or not isinstance(row["scene"], str) or len(row["scene"]) > MAX_STORED_SCENE_CHARACTERS):
            raise ValueError("Saved scenes require sequential indexes, input, idea, scene and self-check.")
        validate_plan_metadata(row)
        row = {**row, "scene": " ".join(row["scene"].split()),
               "self_check": validate_self_check(row["self_check"], allow_pending=True)}
        if row["self_check"].startswith("REPAIR:"):
            row.update(scene_status="repair_required", prompt_status="not_generated")
        if row.get("scene_spec") and row.get("edited_stage"):
            row = invalidate_scene_edit(row, row["edited_stage"], clear_failure=False)
        cleaned.append(row)
    if any(row.get("edited_stage") for row in cleaned):
        cleaned = [{**row, "batch_validation": {**row["batch_validation"], "valid": False,
            "errors": ["Dataset-wide validation is pending after a scene edit."]}}
            if row.get("batch_validation") else row for row in cleaned]
    return cleaned


def reusable_scene_plan(data, assignments, *, require_scenes=True, allow_pending=False):
    rows = validate_saved_scene_plan(data.get("scene_plan", []))
    if (data.get("scene_plan_signature") != scene_plan_signature(data, assignments)
            or any(not row.get("scene_spec") for row in rows)
            or len(rows) != data["amount"]
            or (not allow_pending and any(not row["idea"].strip() and row.get("scene_status") != "failed" for row in rows))
            or (require_scenes and any(not scene_is_usable(row, data) for row in rows))
            or any(row["input"] != assignment["input"] for row, assignment in zip(rows, assignments))):
        return None
    return rows


def failure_reason(error):
    cause = error.__cause__ or error
    if isinstance(cause, json.JSONDecodeError):
        return "The model did not return the required valid JSON."
    return " ".join(str(cause).split())[:900] or "The model did not return a usable result."


def failed_scene(row, reason, *, stage="scene"):
    result = {**row, "failure_reason": reason[:2000], "failure_stage": stage,
              "scene_status": "failed", "prompt_status": "failed", "self_check": ""}
    result.setdefault("idea", "")
    result.setdefault("scene", "")
    result["idea_status"] = "valid" if result["idea"].strip() else "failed"
    return result


def scene_unusable_reason(row, data):
    return scene_eligibility(row, data).reason


def scene_is_usable(row, data):
    return scene_eligibility(row, data).usable


class ScenePlanner:
    def __init__(self, checkpoint, idea_history=None):
        self.checkpoint, self.idea_history = checkpoint, idea_history

    def plan_batch(self, *, session, data, assignments, family="qwen", progress, plan_update=None, seed=None, verify=True):
        rows = []
        def save_specs(specs):
            rows[:] = [{**assignment, "scene_spec": specs[assignment["index"]].to_dict(),
                         "idea": "", "scene": "", "self_check": "", "idea_status": "not_generated",
                         "scene_status": "not_generated", "prompt_status": "not_generated"}
                        for assignment in assignments]
            if plan_update:
                plan_update([dict(row) for row in rows])
        def update(composed):
            for row in composed:
                rows[row["index"] - 1] = {**row, "input": assignments[row["index"] - 1]["input"],
                    "self_check": row.get("self_check", ""), "scene_status": row.get("scene_status", "not_generated"),
                    "prompt_status": row.get("prompt_status", "not_generated")}
            if plan_update:
                plan_update([dict(row) for row in rows])
        ideas = self.plan_ideas(session=session, data=data, assignments=assignments, family=family,
            progress=progress, allow_partial=True, seed=seed, spec_update=save_specs, ideas_update=update)
        self.compose([row for row in ideas if row.get("idea_status") != "failed"], plan_update=update,
                      session=session, checkpoint=self.checkpoint, family=family, verify=verify)
        return rows

    def plan_ideas(self, *, session, data, assignments, family="qwen", progress, indexes=None, existing=(), allow_partial=False,
                   seed=None, spec_update=None, ideas_update=None):
        """Create ideas in chunks; each chunk sees the earlier ones so the batch keeps varying.

        A seed makes the app's random picks (directions, looks, brainstorm sampling) repeatable;
        without one every run draws fresh ones.
        """
        indexes = list(range(1, data["amount"] + 1)) if indexes is None else list(indexes)
        service = DatasetIdeasService(self.checkpoint, self.idea_history)
        picks = random.Random(f"{seed}|{','.join(map(str, indexes))}") if seed is not None else None
        salt, seed = (picks.getrandbits(32), picks.getrandbits(32)) if picks else (secrets.randbits(32), secrets.randbits(32))
        known = [row for row in existing if row["index"] not in indexes]
        # Plan the full batch once. Repairs keep the original specification, not a fresh direction draw.
        specs = {row["index"]: SceneSpec.from_dict(row["scene_spec"]) for row in existing if row.get("scene_spec")}
        if len(specs) != len(assignments):
            routes = resolve_routes(data, assignments)
            catalog = load_vocabulary() if any(route.vocabulary_applicable for route in routes.values()) else Vocabulary()
            planned = plan_scene_specs(data, assignments,
                directions=creative_directions(data, range(1, data["amount"] + 1), salt, vocabulary={}),
                seed=seed, catalog=catalog, routes=routes,
                used=[spec.catalog_id for spec in specs.values() if spec.catalog_id])
            specs = {**planned, **specs}
        if spec_update:
            spec_update(specs)
        candidates = [specs[index] for index in indexes if specs[index].state == "provisional"]
        seeds = {}
        if candidates and uses_event_seeds(data):
            history = self.idea_history
            avoid = [*(history.recent(data) if history is not None else []), *(row["idea"] for row in existing if row.get("idea"))]
            seeds = brainstorm_events(session, data, len(candidates), random.Random(seed), avoid=avoid,
                seen=(lambda text: history.seen_before(data, text)) if history is not None else None,
                family=family, progress=progress, checkpoint=self.checkpoint,
                scene_specs={spec.index: spec for spec in candidates})
        frozen, planning_errors = propose_scene_specs(session, data, candidates, self.checkpoint, family=family,
            existing=[spec for index, spec in specs.items() if index not in indexes or spec.state == "frozen"], event_seeds=seeds,
            corrections={row["index"]: row["failure_reason"] for row in existing
                if row["index"] in indexes and specs[row["index"]].state == "provisional" and row.get("failure_reason")})
        specs.update(frozen)
        if spec_update:
            spec_update(specs)
        rows = []
        for start in range(0, len(indexes), IDEAS_PER_CALL):
            selected = indexes[start:start + IDEAS_PER_CALL]
            chunk = [index for index in selected if index not in planning_errors]
            if chunk and len(indexes) > IDEAS_PER_CALL:
                progress(f"Creating {len(chunk)} ideas for image slots {', '.join(map(str, chunk))} of {data['amount']}…")
            try:
                created = service.run(session=session, data=data, assignments=assignments, family=family, progress=progress,
                    indexes=chunk, existing=[*known, *[row for row in existing if row["index"] in chunk]],
                    allow_partial=allow_partial, direction_salt=salt, scene_specs=specs) if chunk else []
            except BackendGenerationError as error:
                if not allow_partial:
                    raise
                self.checkpoint()
                created = [failed_scene({"index": index, "scene_spec": specs[index].to_dict()},
                                        failure_reason(error), stage="idea") for index in chunk]
            created.extend(failed_scene({"index": index, "scene_spec": specs[index].to_dict()},
                                        planning_errors[index], stage="idea") for index in selected if index in planning_errors)
            created.sort(key=lambda row: row["index"])
            rows.extend(created)
            known.extend(row for row in created if row.get("idea_status") != "failed")
            if ideas_update:
                ideas_update(created)
        return rows

    @staticmethod
    def compose(ideas, plan_update=None, *, session=None, checkpoint=lambda: None, family="qwen", verify=True):
        """Scene review is explicit; direct generation defers fidelity checks to the final output."""
        if session is not None and verify:
            rows = verify_scenes(session, ideas, checkpoint, family=family)
            if plan_update and rows:
                plan_update(rows)
            return rows
        rows = []
        for idea in ideas:
            row = {**idea, "scene": " ".join(idea.get("scene", "").split()), "prompt_status": "not_generated"}
            if not verify:
                row.update(self_check="", scene_status="unverified", quality_warnings=["Scene fidelity deferred to the final prompt check."])
            eligibility = scene_eligibility(row, {})
            if eligibility.usable:
                if verify and row.get("scene_status") != "unverified":
                    row.update(self_check="PASS", scene_status="valid")
            else:
                row.update(self_check="", scene_status="repair_required", failure_stage="scene",
                           failure_reason=eligibility.reason)
            rows.append(row)
        if plan_update and rows:
            plan_update([dict(row) for row in rows])
        return rows
