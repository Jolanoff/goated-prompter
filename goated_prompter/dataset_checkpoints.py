"""Backend-owned atomic Dataset progress, separate from editable workflow drafts."""

from copy import deepcopy
import hashlib
import json
import re
import threading
import time

from .dataset import validate_dataset_draft, saved_dataset_draft

CHECKPOINT_LIMIT = 20
CHECKPOINT_BYTE_BUDGET = 14 * 1024 * 1024
GENERATED_FIELDS = {"results", "result_job_id"}
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _checkpoint_input(data):
    """Validate an archived input projection without changing its signature or record."""
    return saved_dataset_draft(data)


def _result_fields(result, data):
    """Project supported fields without modifying the original historical snapshot."""
    fields = {key: result[key] for key in ("scene_plan", "scene_plan_signature") if key in result}
    if "prompts" in result:
        fields["results"] = result["prompts"]
    projected = saved_dataset_draft({**data, **fields})
    return {key: projected[key] for key in fields}


def generation_signature(data):
    # Scene prose/self-check and guided input are authoritative generation inputs.
    value = {key: item for key, item in validate_dataset_draft(data).items() if key not in GENERATED_FIELDS}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def validate_checkpoints(value):
    if not isinstance(value, dict) or set(value) != {"jobs"} or not isinstance(value["jobs"], list):
        raise ValueError("Invalid Dataset checkpoint store.")
    ids = set()
    for row in value["jobs"]:
        if (not isinstance(row, dict) or not isinstance(row.get("job_id"), str) or row["job_id"] in ids
                or type(row.get("workflow_revision")) is not int or row["workflow_revision"] < 0
                or not isinstance(row.get("input_signature"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["input_signature"])
                or not isinstance(row.get("snapshot"), dict) or not isinstance(row.get("input"), dict)):
            raise ValueError("Invalid Dataset checkpoint record.")
        data = _checkpoint_input(row["input"])
        snapshot = row["snapshot"]
        if (snapshot.get("id") != row["job_id"] or not isinstance(snapshot.get("kind"), str)
                or snapshot.get("status") not in TERMINAL | {"running", "paused", "pause_requested", "cancelling"}
                or type(snapshot.get("revision")) is not int
                or snapshot.get("result") is not None and not isinstance(snapshot["result"], dict)):
            raise ValueError("Invalid Dataset checkpoint snapshot.")
        if snapshot.get("result") is not None:
            result = snapshot["result"]
            validate_dataset_draft({**data, **_result_fields(result, data)})
        ids.add(row["job_id"])
    return value


class DatasetCheckpointStore:
    def __init__(self, path, read, write):
        self.path, self.read, self.write = path, read, write
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return self.read(self.path, {"jobs": []}, validate_checkpoints)

    def _write(self, store, current_job_id=None):
        # The shared atomic JSON store has a 16 MiB safety ceiling. Bound older
        # terminal jobs by bytes as well as count; never prune active work or the
        # current cumulative checkpoint's valid siblings to fit that ceiling.
        while (len(store["jobs"]) > CHECKPOINT_LIMIT or
               len(json.dumps(store, ensure_ascii=True, indent=2).encode()) > CHECKPOINT_BYTE_BUDGET):
            old = next((row for row in store["jobs"] if row["job_id"] != current_job_id and row["snapshot"]["status"] in TERMINAL), None)
            if old is None:
                break
            store["jobs"].remove(old)
        self.write(self.path, validate_checkpoints(store))

    def begin(self, job, data, revision):
        signature = generation_signature(data)
        job.workflow_revision = revision
        job.input_signature = signature
        record = {"job_id": job.id, "workflow_revision": revision,
                  "input_signature": signature, "input": deepcopy(data),
                  "snapshot": job.snapshot(), "stale": False, "updated_at": time.time()}
        with self.lock:
            store = self.snapshot()
            store["jobs"].append(record)
            self._write(store, job.id)
        return record

    def save(self, job, current, *, snapshot=None):
        snapshot = job.snapshot() if snapshot is None else snapshot
        with self.lock:
            store = self.snapshot()
            row = next((row for row in store["jobs"] if row["job_id"] == job.id), None)
            if row is None:
                return
            row["stale"] = (current["revision"] != row["workflow_revision"] or
                            generation_signature(current["draft"]) != row["input_signature"])
            # Live transport messages/reasoning remain RAM-only, not checkpoint data.
            snapshot["llm_trace"] = None
            snapshot["partial_responses"] = []
            snapshot.update(workflow_revision=row["workflow_revision"], input_signature=row["input_signature"], stale=row["stale"])
            row.update(snapshot=snapshot, updated_at=time.time())
            self._write(store, job.id)

    def recover(self):
        """A restarted backend cannot resume a socket; keep the last completed chunk."""
        with self.lock:
            store = self.snapshot()
            changed = False
            for row in store["jobs"]:
                snapshot = row["snapshot"]
                if snapshot["status"] not in TERMINAL:
                    snapshot.update(status="interrupted", completion_state="interrupted", error="Backend restarted. Completed Dataset checkpoints were recovered; resume by generating from the saved plan.",
                                    finished_at=time.time())
                    snapshot["status_reason"] = snapshot["error"]
                    changed = True
            if changed:
                self.write(self.path, validate_checkpoints(store))

    def find(self, job_id):
        return next((row["snapshot"] for row in self.snapshot()["jobs"] if row["job_id"] == job_id and not row.get("released")), None)

    def release(self, job_ids):
        # Releasing RAM diagnostics does not erase durable generated scenes/prompts.
        with self.lock:
            store = self.snapshot()
            changed = False
            for row in store["jobs"]:
                if row["job_id"] in job_ids and row["snapshot"]["status"] in TERMINAL:
                    row["released"] = True
                    changed = True
            if changed:
                self.write(self.path, validate_checkpoints(store))

    def project(self, record):
        """Only matching input revisions can overlay generated fields on a draft."""
        signature = generation_signature(record["draft"])
        matching = [row for row in self.snapshot()["jobs"] if row["workflow_revision"] == record["revision"]
                    and row["input_signature"] == signature and not row["stale"]]
        if not matching:
            return record
        row = matching[-1]
        result = row["snapshot"].get("result") or {}
        fields = _result_fields(result, _checkpoint_input(row["input"]))
        draft = deepcopy(record["draft"])
        for key in ("scene_plan", "scene_plan_signature"):
            if key in fields:
                draft[key] = deepcopy(fields[key])
        if "prompts" in result:
            draft.update(results=deepcopy(fields["results"]), result_job_id=row["job_id"])
        return {**record, "draft": draft, "checkpoint": {key: row[key] for key in
                ("job_id", "workflow_revision", "input_signature", "updated_at")},
                "checkpoint_status": row["snapshot"]["status"]}
