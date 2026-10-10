"""Dataset idea orchestration and saved-plan boundaries; ideas arrive as finished scenes."""

import hashlib
import json
import secrets

import random

from .brainstorm import brainstorm_events, uses_event_seeds
from .ideas import DatasetIdeasService
from .eligibility import scene_eligibility, validate_self_check


SCENE_PLAN_VERSION = 8
# Small local models write better ideas a few at a time than as one long list.
IDEAS_PER_CALL = 5
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000
FAILURE_METADATA = {"failure_reason", "failure_stage"}
PLAN_STATUS_VALUES = {
    "idea_status": {"valid", "not_generated", "duplicate_warning", "failed"},
    "scene_status": {"valid", "not_generated", "repair_required", "failed"},
    "prompt_status": {"valid", "not_generated", "failed"},
}
PLAN_FIELDS = {"index", "input", "idea", "scene", "self_check", *PLAN_STATUS_VALUES, *FAILURE_METADATA}


def scene_plan_signature(data, assignments):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "constraints")}
    semantic.update(version=SCENE_PLAN_VERSION, assignments=assignments)
    return hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def validate_plan_metadata(row):
    if "failure_reason" in row and (not isinstance(row["failure_reason"], str) or len(row["failure_reason"]) > 2000):
        raise ValueError("Failure reason must be text of at most 2000 characters.")
    if "failure_stage" in row and (not isinstance(row["failure_stage"], str) or row["failure_stage"] not in {"idea", "scene", "prompt"}):
        raise ValueError("Invalid failure stage.")
    for key, allowed in PLAN_STATUS_VALUES.items():
        if key in row and (not isinstance(row[key], str) or row[key] not in allowed):
            raise ValueError(f"Invalid {key}.")


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
        cleaned.append(row)
    return cleaned


def reusable_scene_plan(data, assignments, *, require_scenes=True, allow_pending=False):
    rows = validate_saved_scene_plan(data.get("scene_plan", []))
    if (data.get("scene_plan_signature") != scene_plan_signature(data, assignments)
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

    def plan_batch(self, *, session, data, assignments, family="qwen", progress, plan_update=None):
        ideas = self.plan_ideas(session=session, data=data, assignments=assignments, family=family,
            progress=progress, allow_partial=True)
        rows = [{**row, "scene": row.get("scene", ""), "self_check": "", "scene_status": row.get("scene_status", "not_generated"),
            "prompt_status": row.get("prompt_status", "not_generated")} for row in ideas]
        def update(composed):
            for row in composed:
                rows[row["index"] - 1] = row
            if plan_update:
                plan_update([dict(row) for row in rows])
        update([])
        self.compose([row for row in ideas if row.get("idea_status") != "failed"], plan_update=update)
        return rows

    def plan_ideas(self, *, session, data, assignments, family="qwen", progress, indexes=None, existing=(), allow_partial=False):
        """Create ideas in chunks; each chunk sees the earlier ones so the batch keeps varying."""
        indexes = list(range(1, data["amount"] + 1)) if indexes is None else list(indexes)
        service = DatasetIdeasService(self.checkpoint, self.idea_history)
        salt, seed = secrets.randbits(32), secrets.randbits(32)
        known = [row for row in existing if row["index"] not in indexes]
        seeds = {}
        if uses_event_seeds(data):
            # Seed each image's event from a wider pool so repeated runs do not converge
            # on the model's favourite ideas; recent and current ideas are avoided.
            avoid = [*(self.idea_history.recent(data) if self.idea_history is not None else []),
                     *(row["idea"] for row in existing if row.get("idea"))]
            events = brainstorm_events(session, data, len(indexes), random.Random(seed), avoid=avoid,
                                       family=family, progress=progress, checkpoint=self.checkpoint)
            seeds = dict(zip(indexes, events))
        rows = []
        for start in range(0, len(indexes), IDEAS_PER_CALL):
            chunk = indexes[start:start + IDEAS_PER_CALL]
            if len(indexes) > IDEAS_PER_CALL:
                progress(f"Creating ideas {start + 1}-{start + len(chunk)} of {len(indexes)}…")
            created = service.run(session=session, data=data, assignments=assignments, family=family, progress=progress,
                indexes=chunk, existing=[*known, *[row for row in existing if row["index"] in chunk]],
                allow_partial=allow_partial, direction_salt=salt, event_seeds=seeds)
            rows.extend(created)
            known.extend(row for row in created if row.get("idea_status") != "failed")
        return rows

    @staticmethod
    def compose(ideas, plan_update=None):
        """Accept each idea's own scene, or the user's edit of it, for the writer; no model call."""
        rows = [{**idea, "scene": " ".join(idea.get("scene", "").split()), "self_check": "PASS",
                 "scene_status": "valid", "prompt_status": "not_generated"} for idea in ideas]
        if plan_update and rows:
            plan_update([dict(row) for row in rows])
        return rows
