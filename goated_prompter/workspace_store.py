"""Revision-checked, atomic storage for prompt versions and direction comparisons."""

from copy import deepcopy
from datetime import datetime, timezone
import threading
import uuid


LOCKS = ("identity", "outfit", "pose", "scene", "composition", "camera", "lighting", "colors", "materials", "style")
DIRECTIONS = ("faithful", "creative", "experimental")


def text(value, name, limit=100000, optional=False):
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise ValueError(f"{name} must be {'a' if optional else 'a nonempty'} string of at most {limit} characters.")
    return value


def locks(value):
    if not isinstance(value, list) or len(value) > len(LOCKS) or any(item not in LOCKS for item in value):
        raise ValueError("Invalid detail locks.")
    return list(dict.fromkeys(value))


def empty_workspace():
    return {"revision": 0, "versions": [], "current_id": None, "redo": [], "comparisons": []}


def validate_workspace(value):
    if not isinstance(value, dict) or set(value) != set(empty_workspace()):
        raise ValueError("Invalid creative workspace store.")
    if type(value["revision"]) is not int or value["revision"] < 0:
        raise ValueError("Invalid workspace revision.")
    versions, comparisons = value["versions"], value["comparisons"]
    if not isinstance(versions, list) or len(versions) > 1000 or not isinstance(comparisons, list) or len(comparisons) > 100:
        raise ValueError("Workspace supports 1000 versions and 100 comparisons. Remove older comparisons or clear history first.")
    ids = set()
    for record in versions:
        if not isinstance(record, dict) or set(record) != {"id", "parent_id", "prompt", "target", "label", "created_at", "locks", "instruction"}:
            raise ValueError("Invalid prompt version.")
        for key, limit in (("id", 128), ("prompt", 100000), ("target", 256), ("label", 100), ("created_at", 64), ("instruction", 10000)):
            text(record[key], key, limit, optional=key == "instruction")
        locks(record["locks"])
        if record["id"] in ids or (record["parent_id"] is not None and record["parent_id"] not in ids):
            raise ValueError("Invalid version ancestry.")
        ids.add(record["id"])
    if value["current_id"] is not None and value["current_id"] not in ids:
        raise ValueError("Current version is missing.")
    if not isinstance(value["redo"], list) or len(value["redo"]) > 1000 or any(item not in ids for item in value["redo"]):
        raise ValueError("Invalid redo history.")
    batch_ids = set()
    for batch in comparisons:
        if not isinstance(batch, dict) or set(batch) != {"id", "base", "target", "locks", "created_at", "results"}:
            raise ValueError("Invalid comparison.")
        for key, limit in (("id", 128), ("base", 100000), ("target", 256), ("created_at", 64)):
            text(batch[key], key, limit)
        locks(batch["locks"])
        if batch["id"] in batch_ids or not isinstance(batch["results"], list) or len(batch["results"]) > 3:
            raise ValueError("Invalid comparison results.")
        batch_ids.add(batch["id"])
        for index, result in enumerate(batch["results"]):
            if not isinstance(result, dict) or set(result) != {"direction", "prompt"} or result["direction"] != DIRECTIONS[index]:
                raise ValueError("Invalid comparison direction.")
            text(result["prompt"], "Direction prompt")
    return value


class WorkspaceConflict(ValueError):
    """The caller is editing an outdated snapshot."""


class WorkspaceStore:
    def __init__(self, path, read, write):
        self.path, self.read, self.write = path, read, write
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return self.read(self.path, empty_workspace(), validate_workspace)

    def check(self, revision):
        current = self.snapshot()
        if type(revision) is not int or revision != current["revision"]:
            raise WorkspaceConflict("Workspace changed in another tab. Refresh it before trying again.")
        return current

    def mutate(self, operation, revision=None):
        with self.lock:
            current = self.snapshot() if revision is None else self.check(revision)
            updated = deepcopy(current)
            operation(updated)
            updated["revision"] += 1
            self.write(self.path, validate_workspace(updated))
            return updated

    def add_version(self, prompt, target, label, *, parent_id=None, instruction="", detail_locks=("identity",), revision=None):
        record = {"id": uuid.uuid4().hex, "parent_id": parent_id, "prompt": prompt, "target": target,
                  "label": label, "instruction": instruction, "locks": list(detail_locks), "created_at": now()}

        def add(state):
            state["versions"].append(record)
            state["current_id"] = record["id"]
            state["redo"] = []

        return self.mutate(add, revision)

    def navigate(self, action, revision, version_id=None):
        def move(state):
            records = {item["id"]: item for item in state["versions"]}
            current = records.get(state["current_id"])
            if action == "undo":
                if not current or not current["parent_id"]:
                    raise ValueError("No earlier version to undo to.")
                state["redo"].append(current["id"])
                state["current_id"] = current["parent_id"]
            elif action == "redo":
                if not state["redo"]:
                    raise ValueError("No version to redo.")
                state["current_id"] = state["redo"].pop()
            elif action == "restore":
                if version_id not in records:
                    raise ValueError("Version no longer exists.")
                state["current_id"] = version_id
                state["redo"] = []
            elif action == "clear_history":
                state.update(versions=[], current_id=None, redo=[])
            else:
                raise ValueError("Unknown history action.")

        return self.mutate(move, revision)

    def save_direction(self, batch, direction, prompt):
        def save(state):
            existing = next((item for item in state["comparisons"] if item["id"] == batch["id"]), None)
            if existing is None:
                existing = deepcopy(batch)
                state["comparisons"].append(existing)
            existing["results"].append({"direction": direction, "prompt": prompt})

        return self.mutate(save)

    def delete_comparison(self, batch_id, revision):
        return self.mutate(lambda state: state.update(comparisons=[item for item in state["comparisons"] if item["id"] != batch_id]), revision)


def now():
    return datetime.now(timezone.utc).isoformat()
