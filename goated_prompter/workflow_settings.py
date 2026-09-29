"""Independent saved drafts and instruction overrides for prompt workflows."""

from copy import deepcopy
import threading

from .prompting.refine import builtin_refine_instructions
from .prompting.target_models import TARGET_MODEL_NAMES
from .workspace_store import WorkspaceConflict, locks, text
from .minimax import default_minimax_draft, validate_minimax_draft
from .dataset import default_dataset_draft, validate_dataset_draft


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
        validate_draft(operation, record["draft"])
        validate_instructions(operation, record["overrides"])
    # Older stores gain an independent workflow without altering their drafts/revisions.
    return {**empty_settings(), **value}


class WorkflowSettingsStore:
    def __init__(self, path, read, write):
        self.path, self.read, self.write = path, read, write
        self.lock = threading.RLock()

    def _read(self):
        return self.read(self.path, empty_settings(), validate_settings_store)

    def _public(self, operation, record):
        defaults = builtin_refine_instructions() if operation == "refine" else {}
        return {**record, "draft": validate_draft(operation, record["draft"]), "defaults": defaults,
                "instructions": {**defaults, **record["overrides"]}}

    def snapshot(self, operation):
        with self.lock:
            return self._public(operation, self._read()[operation])

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
