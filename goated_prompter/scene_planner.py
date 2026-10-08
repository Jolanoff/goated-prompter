"""Dataset compact idea/scene orchestration and saved-plan boundaries."""

import hashlib
import json

from .dataset_ideas import DatasetIdeasService, IDEA_DETAIL_FIELDS, MAX_FIELD_CHARACTERS
from .dataset_scene import DatasetSceneService, validate_self_check
from .scene_eligibility import scene_eligibility


SCENE_PLAN_VERSION = 7
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000
FAILURE_METADATA = {"failure_reason", "failure_stage"}
PLAN_STATUS_VALUES = {
    "idea_status": {"valid", "not_generated", "duplicate_warning", "failed"},
    "scene_status": {"valid", "not_generated", "repair_required", "failed"},
    "prompt_status": {"valid", "not_generated", "failed"},
}
PLAN_FIELDS = {"index", "input", "idea", "scene", "self_check",
               *IDEA_DETAIL_FIELDS, *PLAN_STATUS_VALUES, *FAILURE_METADATA}


def scene_plan_signature(data, assignments):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "variety", "constraints", "visual_style", "custom_style")}
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
        details = set(row) & set(IDEA_DETAIL_FIELDS)
        if details and (details != set(IDEA_DETAIL_FIELDS) or not row["idea"].strip()
                or any(not isinstance(row[field], str) or not row[field].strip()
                       or len(row[field]) > MAX_FIELD_CHARACTERS for field in IDEA_DETAIL_FIELDS)):
            raise ValueError("Saved compact ideas require all five concise description fields alongside the idea.")
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
        rows = [{**row, "scene": "", "self_check": "", "scene_status": row.get("scene_status", "not_generated"),
            "prompt_status": row.get("prompt_status", "not_generated")} for row in ideas]
        def update(composed):
            for row in composed:
                rows[row["index"] - 1] = row
            if plan_update:
                plan_update([dict(row) for row in rows])
        update([])
        self.compose(session=session, data=data, assignments=assignments,
            ideas=[row for row in ideas if row.get("idea_status") != "failed"],
            family=family, progress=progress, plan_update=update)
        return rows

    def plan_ideas(self, *, session, data, assignments, family="qwen", progress, indexes=None, existing=(), allow_partial=False):
        if self.idea_history is not None:
            data = {**data, "_recent_ideas": self.idea_history.recent(data)}
        rows = DatasetIdeasService(self.checkpoint).run(session=session, data=data,
            assignments=assignments, family=family, progress=progress, indexes=indexes, existing=existing, allow_partial=allow_partial)
        if self.idea_history is not None:
            self.idea_history.remember(data, rows)
        return rows

    def compose(self, *, session, data, assignments, ideas, family="qwen", progress, plan_update=None):
        rows = [{**idea, "self_check": "", "scene": idea.get("scene", ""),
                 "scene_status": "not_generated", "prompt_status": "not_generated"} for idea in ideas]
        for position, idea in enumerate(ideas):
            rows[position] = DatasetSceneService(self.checkpoint).run(session=session, data=data,
                assignment=assignments[idea["index"] - 1], idea=idea, family=family, progress=progress)
            if plan_update:
                plan_update([dict(item) for item in rows])
        return rows

    def repair_scene(self, *, session, data, assignments, row, family="qwen", progress):
        return DatasetSceneService(self.checkpoint).run(session=session, data=data,
            assignment=assignments[row["index"] - 1], idea=row, family=family, progress=progress, repair=True)
