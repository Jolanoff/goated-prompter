"""Independent saved drafts and instruction overrides for prompt workflows."""

from copy import deepcopy
import threading

from .prompting.refine import builtin_refine_instructions
from .prompting.target_models import TARGET_MODEL_NAMES, canonical_target
from .workspace_store import WorkspaceConflict, locks, text
from .minimax import default_minimax_draft, validate_minimax_draft
from .dataset import default_dataset_draft, validate_dataset_draft, saved_dataset_draft
from .dataset_assignments import dataset_assignments
from .scene_planner import reusable_scene_plan
from .scene_eligibility import scene_eligibility
from .dataset_scene import MAX_SCENE_CHARACTERS
from .dataset_ideas import MAX_FIELD_CHARACTERS


def default_draft(operation):
    if operation == "minimax":
        return default_minimax_draft()
    if operation == "dataset":
        return default_dataset_draft()
    if operation == "refine":
        return {"target": "Generic", "locks": ["identity"], "changes": "", "source": "", "editing": None, "lock_version_id": None}
    raise ValueError("Unknown workflow settings operation.")


def validate_draft(operation, value):
    if operation == "minimax":
        return validate_minimax_draft(value)
    if operation == "dataset":
        return validate_dataset_draft(value)
    defaults = default_draft(operation)
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise ValueError(f"Invalid {operation} settings fields.")
    result = {**defaults, **value}
    result["target"] = canonical_target(result["target"])
    if result["target"] not in TARGET_MODEL_NAMES:
        raise ValueError("Invalid target model.")
    result["locks"] = locks(result["locks"])
    for key in ("changes", "source", "base", "selected_id"):
        if key in result:
            text(result[key], key, 10000 if key == "changes" else 128 if key == "selected_id" else 100000, optional=True)
    if operation == "refine":
        if result["lock_version_id"] is not None:
            text(result["lock_version_id"], "Version id", 128)
        edit = result["editing"]
        if edit is not None:
            if not isinstance(edit, dict) or set(edit) != {"id", "text"}:
                raise ValueError("Invalid manual edit draft.")
            text(edit["id"], "Edit version id", 128)
            text(edit["text"], "Manual edit", optional=True)
    return result


def validate_instructions(operation, value):
    defaults = builtin_refine_instructions() if operation == "refine" else {}
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise ValueError("Unknown workflow instruction section.")
    return {key: text(content, "System instructions", 20000) for key, content in value.items() if content != defaults[key]}


def empty_settings():
    return {operation: {"revision": 0, "draft": default_draft(operation), "overrides": {}}
            for operation in ("refine", "minimax", "dataset")}


def validate_settings_store(value):
    supported = {"refine", "minimax", "dataset"}
    if not isinstance(value, dict) or "refine" not in value:
        raise ValueError("Invalid workflow settings store.")
    value = {key: record for key, record in value.items() if key in supported}
    for operation, record in value.items():
        if not isinstance(record, dict) or set(record) != {"revision", "draft", "overrides"} or type(record["revision"]) is not int or record["revision"] < 0:
            raise ValueError("Invalid workflow settings record.")
        value[operation] = {**record, "draft": saved_dataset_draft(record["draft"]) if operation == "dataset"
                            else validate_draft(operation, record["draft"])}
        validate_instructions(operation, record["overrides"])
    # Older stores gain an independent workflow without altering their drafts/revisions.
    return {**empty_settings(), **value}


class WorkflowSettingsStore:
    def __init__(self, path, read, write):
        self.path, self.read, self.write = path, read, write
        self.lock = threading.RLock()
        self.dataset_checkpoints = None

    def _read(self):
        return self.read(self.path, empty_settings(), validate_settings_store)

    def _public(self, operation, record):
        defaults = builtin_refine_instructions() if operation == "refine" else {}
        draft = validate_draft(operation, record["draft"])
        scene_state = ({"scene_plan_current": reusable_scene_plan(draft, dataset_assignments(draft)) is not None,
                         "idea_plan_current": reusable_scene_plan(draft, dataset_assignments(draft), require_scenes=False) is not None,
                         "scene_plan_matches_settings": reusable_scene_plan(draft, dataset_assignments(draft), require_scenes=False, allow_pending=True) is not None,
                         "scene_limits": {"characters": MAX_SCENE_CHARACTERS},
                         "idea_limits": {"characters": MAX_FIELD_CHARACTERS},
                         "scene_eligibility": {str(row["index"]): scene_eligibility(row, draft).to_dict() for row in draft["scene_plan"]}}
                       if operation == "dataset" else {})
        return {**record, "draft": draft, "defaults": defaults, **scene_state,
                "instructions": {**defaults, **record["overrides"]}}

    def snapshot(self, operation):
        with self.lock:
            record = self._read()[operation]
            if operation == "dataset" and self.dataset_checkpoints is not None:
                record = self.dataset_checkpoints.project(record)
            return self._public(operation, record)

    def checkpoint_dataset(self, job):
        snapshot = job.snapshot()  # Never acquire a job lock while holding the settings lock.
        with self.lock:
            if self.dataset_checkpoints is not None:
                self.dataset_checkpoints.save(job, self._read()["dataset"], snapshot=snapshot)

    def begin_dataset(self, job, data, revision=None):
        with self.lock:
            current = self._read()["dataset"]
            if revision is not None and (type(revision) is not int or revision != current["revision"]):
                raise WorkspaceConflict("Dataset input changed before generation started. Reload and retry.")
            # Older API callers may supply an unsaved draft. Persist that exact
            # configuration at admission, never again from a running job.
            if current["draft"] != data:
                self.update("dataset", current["revision"], draft=data)
                current = self._read()["dataset"]
            record = self.dataset_checkpoints.begin(job, data, current["revision"])
            job.workflow_revision = record["workflow_revision"]
            job.input_signature = record["input_signature"]

    def update(self, operation, revision, *, draft=None, instructions=None, reset=False):
        with self.lock:
            store = deepcopy(self._read())
            record = store[operation]
            if type(revision) is not int or revision != record["revision"]:
                raise WorkspaceConflict("These workflow settings changed in another tab. Reload saved settings before saving again.")
            if draft is not None:
                record["draft"] = validate_draft(operation, draft)
            if instructions is not None or reset:
                record["overrides"] = {} if reset else validate_instructions(operation, instructions)
            record["revision"] += 1
            self.write(self.path, validate_settings_store(store))
            return self._public(operation, record)
