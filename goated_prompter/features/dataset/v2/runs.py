"""Durable Dataset V2 runs: one versioned JSON record per run, saved as work completes.

Each run is its own file, <directory>/<run_id>.json, written atomically (temporary file, fsync,
replace) through json_store.atomic_json. A damaged or unknown-version file is skipped and reported,
never rewritten, reset or deleted; the other runs stay readable. Legacy Dataset checkpoints are a
separate store and are not touched.

Record (schema 2; schema 1 is read as it is, see below):
  schema        2
  run_id        32 lowercase hex characters; the file name
  job_id        the job that owns the run; only that job's recorder may write generation results
  revision      increases by one on every saved change (compare-and-set: update(expected_revision=))
  created_at, updated_at   seconds since the epoch
  status        running | succeeded | failed | cancelled | interrupted
  stage         concepts | staging | description | prompts | done  (where the run is or stopped)
  scenes_only   the owner chose scenes without final prompts
  error         text or null
  brief         the confirmed Understanding brief (request, rules, settings, seed, amount, guided inputs)
  seed, requested   copies of brief.input.seed and brief.input.amount, checked against the brief
  vocabulary    {"enabled", "provided", ...} once scenes are written, else null: also the export-safe diagnostics of
                vocabulary_packs.diagnostics (selection, entries and ideas by image, exclusions, Visual Direction)
  packs         the run's vocabulary pack selection, recorded when the run is created, before any inference,
                and never changed afterwards (update() refuses): {version, enabled, selected, packs: [{id, role,
                origin, version, fingerprint}]} (vocabulary.packs.validate_selection), or null when the caller gave
                none. It is the run's own selection, never the global enabled state.
  slots         one per requested image, slot N = image N, never renumbered:
    slot, revision (this slot's own change counter), input (guided input or ""),
    concept, staging, scene     each null until completed, then never overwritten by generation
    scene_status  pending | written | failed
    failure       null or {"stage": "concepts" | "staging" | "description", "reasons": [...], "tries": n}
    prompt        null, or {"status": "written" | "failed", "text", "trigger_ok", "error", "stage", "attempts"}

Schema 1 runs (written before pack selection) are read and updated as schema 1: they have no packs field and
their selection reads as NOT RECORDED (recorded_packs()); nothing invents one from today's settings, and no file
is rewritten just because this reader also knows schema 2. Any other schema is reported as incompatible and never
changed. The stored brief is checked by understanding.validate_brief, so a later brief version only needs that
reader to accept both; run files need no migration.

A run is complete when it succeeded and every slot has a written scene and, unless scenes_only,
a written prompt. Everything else is incomplete; partial and complete runs are always told apart by
the slot fields, never by list position.

Runs are user work: this module never deletes a run. retention_candidates() only reports which
finished runs fall outside the newest RETAIN_COMPLETE complete and RETAIN_INCOMPLETE incomplete ones,
for a future, explicit storage-management action.

Size: one run file may not exceed json_store's 16 MiB limit. A save that would exceed it is
refused before anything is written, so the last saved version stays. A full 25-image run of real
scenes and prompts is about 115 KiB.

Final status: the recorder writes it once, after the job's own outcome is settled, with the
app's precedence (LocalState.execute): a requested cancellation wins, then a server stop
(interrupted), then any other error (failed); succeeded only once the job itself has succeeded.
Completed slots are saved before that and are kept whatever the final status is.
"""

from copy import deepcopy
import json
import logging
from pathlib import Path
import re
import threading
import time
import uuid

from ....json_store import MAX_STORE_BYTES, atomic_json
from ...vocabulary.packs import VocabularyError, validate_selection
from .understanding import validate_brief

SCHEMA = 2
READABLE = (1, 2)  # schemas this module reads and keeps; anything else is incompatible
NOT_RECORDED = {"recorded": False}
STATUSES = ("running", "succeeded", "failed", "cancelled", "interrupted")
TERMINAL = frozenset(STATUSES[1:])
STAGES = ("concepts", "staging", "description", "prompts", "done")
SCENE_STATUSES = ("pending", "written", "failed")
FAILED_STAGES = ("concepts", "staging", "description")
RETAIN_COMPLETE = 20
RETAIN_INCOMPLETE = 20
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
INTERRUPTED = "The backend stopped before this run finished. Completed scenes and prompts are kept; nothing was restarted."
RECORD_KEYS_1 = {"schema", "run_id", "job_id", "revision", "created_at", "updated_at", "status", "stage", "scenes_only",
                 "error", "brief", "seed", "requested", "vocabulary", "slots"}
RECORD_KEYS = RECORD_KEYS_1 | {"packs"}
SLOT_KEYS = {"slot", "revision", "input", "concept", "staging", "scene", "scene_status", "failure", "prompt"}
PROMPT_KEYS = {"status", "text", "trigger_ok", "error", "stage", "attempts"}


class RunStoreError(ValueError):
    """A run could not be read or saved. Nothing was overwritten."""


class RunConflict(RunStoreError):
    """The run changed since the caller read it, or the caller does not own it."""


class IncompatibleRun(RunStoreError):
    """The file is a run of another schema version; it is left untouched."""


# ---------------------------------------------------------------- the schema

def _number(value, name):
    if type(value) not in (int, float) or value < 0:
        raise RunStoreError(f"{name} must be a non-negative number.")


def _validate_slot(slot, number):
    if not isinstance(slot, dict) or set(slot) != SLOT_KEYS:
        raise RunStoreError(f"slot {number} needs exactly: {', '.join(sorted(SLOT_KEYS))}.")
    if slot["slot"] != number:
        raise RunStoreError(f"slot {number} is stored as slot {slot['slot']}; slots are never renumbered.")
    if type(slot["revision"]) is not int or slot["revision"] < 0 or not isinstance(slot["input"], str):
        raise RunStoreError(f"slot {number} has an invalid revision or input.")
    for key in ("concept", "staging", "scene"):
        if slot[key] is not None and not isinstance(slot[key], dict):
            raise RunStoreError(f"slot {number} {key} must be an object or null.")
    if slot["scene_status"] not in SCENE_STATUSES:
        raise RunStoreError(f"slot {number} has an unknown scene status.")
    if (slot["scene_status"] == "written") != (slot["scene"] is not None):
        raise RunStoreError(f"slot {number}: a scene is written exactly when it is stored.")
    if slot["scene"] is not None and slot["scene"].get("slot") != number:
        raise RunStoreError(f"slot {number} holds the scene of another slot.")
    failure = slot["failure"]
    if (slot["scene_status"] == "failed") != (failure is not None):
        raise RunStoreError(f"slot {number}: a failed scene needs its failure, and only a failed scene has one.")
    if failure is not None and (not isinstance(failure, dict) or set(failure) != {"stage", "reasons", "tries"}
                                or failure["stage"] not in FAILED_STAGES or not isinstance(failure["reasons"], list)
                                or type(failure["tries"]) is not int):
        raise RunStoreError(f"slot {number} has an invalid failure.")
    prompt = slot["prompt"]
    if prompt is not None:
        if (not isinstance(prompt, dict) or set(prompt) != PROMPT_KEYS or prompt["status"] not in ("written", "failed")
                or not isinstance(prompt["text"], str) or type(prompt["trigger_ok"]) is not bool):
            raise RunStoreError(f"slot {number} has an invalid prompt.")
        if slot["scene_status"] != "written":
            raise RunStoreError(f"slot {number} has a prompt without a written scene.")
        if (prompt["status"] == "written") != bool(prompt["text"].strip()) or (prompt["status"] == "failed") != bool(prompt["error"]):
            raise RunStoreError(f"slot {number}: a written prompt has text, a failed prompt has an error.")


def validate_run(value):
    """The stored contract. Raises IncompatibleRun for another schema, RunStoreError for anything else."""
    if not isinstance(value, dict):
        raise RunStoreError("A run must be a JSON object.")
    if value.get("schema") not in READABLE:
        raise IncompatibleRun(f"Unsupported Dataset run schema {value.get('schema')!r}; this version reads schemas 1 and {SCHEMA}.")
    keys = RECORD_KEYS if value["schema"] == SCHEMA else RECORD_KEYS_1
    if set(value) != keys:
        raise RunStoreError(f"A schema {value['schema']} run needs exactly: {', '.join(sorted(keys))}.")
    if value["schema"] == SCHEMA and value["packs"] is not None:
        try:
            validate_selection(value["packs"])
        except VocabularyError as error:
            raise RunStoreError(f"The recorded pack selection is invalid: {error}") from None
    if not isinstance(value["run_id"], str) or not RUN_ID.match(value["run_id"]) or not isinstance(value["job_id"], str) or not value["job_id"]:
        raise RunStoreError("run_id must be 32 hex characters and job_id nonempty text.")
    if type(value["revision"]) is not int or value["revision"] < 0:
        raise RunStoreError("revision must be a non-negative integer.")
    _number(value["created_at"], "created_at")
    _number(value["updated_at"], "updated_at")
    if value["status"] not in STATUSES or value["stage"] not in STAGES or type(value["scenes_only"]) is not bool:
        raise RunStoreError("Unknown run status, stage or scenes_only.")
    if value["error"] is not None and not isinstance(value["error"], str):
        raise RunStoreError("error must be text or null.")
    try:
        brief = validate_brief(deepcopy(value["brief"]))
    except ValueError as error:
        raise RunStoreError(f"The stored brief is not a confirmed brief: {error}") from None
    if value["seed"] != brief["input"].get("seed") or value["requested"] != brief["input"]["amount"]:
        raise RunStoreError("seed and requested must match the confirmed brief.")
    if value["vocabulary"] is not None and not isinstance(value["vocabulary"], dict):
        raise RunStoreError("vocabulary must be an object or null.")
    slots = value["slots"]
    if not isinstance(slots, list) or len(slots) != value["requested"]:
        raise RunStoreError("A run has exactly one slot per requested image.")
    for number, slot in enumerate(slots, 1):
        _validate_slot(slot, number)
    return value


def recorded_packs(record):
    """A run's pack selection as recorded, or NOT_RECORDED (schema 1 runs, or runs started without one)."""
    return deepcopy(record.get("packs")) if record.get("packs") is not None else dict(NOT_RECORDED)


def is_complete(record):
    return record["status"] == "succeeded" and all(
        slot["scene_status"] == "written" and (record["scenes_only"] or (slot["prompt"] or {}).get("status") == "written")
        for slot in record["slots"])


# ---------------------------------------------------------------- the store

class DatasetRunStore:
    """Thread-safe store of V2 runs in one directory. All writes are atomic and validated first."""

    def __init__(self, directory, *, write=atomic_json, clock=time.time):
        self.directory = Path(directory)
        self.write, self.clock = write, clock
        self.lock = threading.RLock()

    def path(self, run_id):
        if not isinstance(run_id, str) or not RUN_ID.match(run_id):
            raise RunStoreError("Unknown Dataset run.")
        return self.directory / f"{run_id}.json"

    def _read(self, path):
        try:
            with path.open("rb") as file:
                data = file.read(MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            raise RunStoreError(f"Dataset run {path.stem} does not exist.") from None
        except OSError as error:
            raise RunStoreError(f"Cannot read {path.name}: {error}") from None
        if len(data) > MAX_STORE_BYTES:
            raise RunStoreError(f"{path.name} exceeds the 16 MiB limit; it has not been changed.")
        try:
            value = json.loads(data)
        except ValueError as error:
            raise RunStoreError(f"{path.name} is not valid JSON ({error}); it has not been changed.") from None
        record = validate_run(value)
        if record["run_id"] != path.stem:
            raise RunStoreError(f"{path.name} holds run {record['run_id']}; it has not been changed.")
        return record

    def _save(self, record):
        validate_run(record)
        try:
            self.write(self.path(record["run_id"]), record)
        except (OSError, ValueError) as error:
            raise RunStoreError(f"Dataset run {record['run_id']} could not be saved; the previous version is kept. {error}") from error
        return deepcopy(record)

    # -- reading
    def get(self, run_id):
        with self.lock:
            return self._read(self.path(run_id))

    def scan(self):
        """(records, problems): every readable run, newest first, and {file name: reason} for the rest."""
        with self.lock:
            records, problems = [], {}
            if not self.directory.is_dir():
                return records, problems
            for path in sorted(self.directory.glob("*.json")):
                try:
                    records.append(self._read(path))
                except RunStoreError as error:
                    problems[path.name] = str(error)
            records.sort(key=lambda record: (record["updated_at"], record["run_id"]), reverse=True)
            return records, problems

    def find_by_job(self, job_id):
        return next((record for record in self.scan()[0] if record["job_id"] == job_id), None)

    # -- writing
    def create(self, job_id, brief, *, scenes_only=False, inputs=None, packs=None):
        """A new running run with one pending slot per requested image and its pack selection (packs, recorded now,
        before any inference; None when the caller has none). Never removes another run."""
        brief = validate_brief(deepcopy(brief))
        total = brief["input"]["amount"]
        inputs = inputs or {}
        now = self.clock()
        record = {"schema": SCHEMA, "run_id": uuid.uuid4().hex, "job_id": str(job_id), "revision": 0,
                  "created_at": now, "updated_at": now, "status": "running", "stage": "concepts",
                  "scenes_only": bool(scenes_only), "error": None, "brief": brief, "seed": brief["input"].get("seed"),
                  "requested": total, "vocabulary": None, "packs": deepcopy(packs),
                  "slots": [{"slot": number, "revision": 0, "input": inputs.get(number, ""), "concept": None, "staging": None,
                             "scene": None, "scene_status": "pending", "failure": None, "prompt": None}
                            for number in range(1, total + 1)]}
        with self.lock:
            return self._save(record)

    def update(self, run_id, change, *, expected_revision=None, owner=None):
        """Read, apply change(record) -> bool (False: nothing changed), validate, save atomically.

        expected_revision: compare-and-set; RunConflict if the run moved on. owner: only this job may write.
        Returns the saved record (or the unchanged one)."""
        with self.lock:
            record = self.get(run_id)
            if expected_revision is not None and record["revision"] != expected_revision:
                raise RunConflict(f"Dataset run {run_id} changed (revision {record['revision']}, expected {expected_revision}).")
            if owner is not None and record["job_id"] != owner:
                raise RunConflict(f"Dataset run {run_id} belongs to another job.")
            working = deepcopy(record)
            if change(working) is False:
                return record
            if working.get("schema") != record["schema"] or working.get("packs") != record.get("packs"):
                raise RunConflict(f"Dataset run {run_id}: its schema and recorded pack selection never change.")
            working["revision"] = record["revision"] + 1
            working["updated_at"] = max(self.clock(), record["updated_at"])
            return self._save(working)

    def recover(self):
        """At startup: running runs become interrupted (their work is kept). Nothing is generated.
        Returns {"interrupted": [run ids], "problems": {file: reason}}."""
        interrupted = []
        with self.lock:
            records, problems = self.scan()
            for record in records:
                if record["status"] == "running":
                    def mark(working):
                        working.update(status="interrupted", error=INTERRUPTED)
                    try:
                        self.update(record["run_id"], mark)
                        interrupted.append(record["run_id"])
                    except RunStoreError as error:
                        problems[f"{record['run_id']}.json"] = str(error)
        for name, reason in problems.items():
            logging.warning("Dataset run file %s was skipped: %s", name, reason)
        return {"interrupted": interrupted, "problems": problems}

    def retention_candidates(self, *, keep_complete=RETAIN_COMPLETE, keep_incomplete=RETAIN_INCOMPLETE):
        """Run ids of finished runs outside the newest keep_complete complete and keep_incomplete
        incomplete ones, oldest last. Read-only: nothing is deleted. Running runs and unreadable
        files are never candidates."""
        records, _problems = self.scan()
        finished = [record for record in records if record["status"] in TERMINAL]
        complete = [record for record in finished if is_complete(record)]
        incomplete = [record for record in finished if not is_complete(record)]
        return [record["run_id"] for record in complete[keep_complete:] + incomplete[keep_incomplete:]]


# ---------------------------------------------------------------- writing one job's progress

class RunRecorder:
    """Saves one job's V2 progress into its run as it happens.

    Generation results only fill empty fields: a completed concept, staging, scene or prompt is
    never overwritten, and publishing the same result again changes nothing. Every save is one
    slot-targeted read-modify-write, so other slots and later edits are kept. A failed save raises
    RunStoreError; it is never treated as saved."""

    def __init__(self, store, record):
        self.store, self.run_id, self.job_id = store, record["run_id"], record["job_id"]

    @classmethod
    def start(cls, store, job_id, brief, *, scenes_only=False, inputs=None, packs=None):
        return cls(store, store.create(job_id, brief, scenes_only=scenes_only, inputs=inputs, packs=packs))

    def _change(self, change):
        return self.store.update(self.run_id, change, owner=self.job_id)

    def _fill(self, number, field, value, *, stage=None):
        def change(record):
            if record["status"] != "running":
                raise RunConflict(f"Dataset run {self.run_id} is {record['status']}; late results are not saved.")
            slot = record["slots"][number - 1]
            changed = False
            if slot[field] is None:
                slot[field] = deepcopy(value)
                if field == "scene":
                    slot["scene_status"] = "written"
                slot["revision"] += 1
                changed = True
            elif slot[field] != value:
                raise RunConflict(f"Image {number} already has a different {field}; it is not replaced.")
            if stage is not None and STAGES.index(stage) > STAGES.index(record["stage"]):
                record["stage"] = stage
                changed = True
            return changed
        return self._change(change)

    def slot_event(self, event, number, value):
        """write_scenes progress: ("concept" | "staging" | "description", slot, value)."""
        if event == "concept":
            return self._fill(number, "concept", value, stage="concepts")
        if event == "staging":
            return self._fill(number, "staging", value, stage="staging")
        if event == "description":
            return self._fill(number, "scene", value, stage="description")
        raise ValueError(f"Unknown scene progress event {event}.")

    def scenes_finished(self, result):
        """Record each failed slot's stage and reasons, and move on to prompts (or finish scenes only)."""
        failed = {row["slot"]: row for row in result["slots"] if row["status"] == "failed"}
        def change(record):
            for slot in record["slots"]:
                row = failed.get(slot["slot"])
                if row and slot["scene_status"] != "failed":
                    slot["scene_status"] = "failed"
                    slot["failure"] = {"stage": row["stage"], "reasons": list(row["reasons"]), "tries": row["tries"]}
                    slot["revision"] += 1
            record["vocabulary"] = deepcopy(result.get("vocabulary"))
            record["stage"] = "done" if record["scenes_only"] else "prompts"
        return self._change(change)

    def prompt(self, item):
        """One Builder result, keyed by its slot."""
        value = {"status": "failed" if item.get("error") else "written", "text": item.get("prompt", ""),
                 "trigger_ok": bool(item.get("trigger_ok")), "error": item.get("error"),
                 "stage": item.get("stage"), "attempts": item.get("attempts")}
        return self._fill(item["slot"], "prompt", value, stage="prompts")

    def finish(self, status, error=None):
        def change(record):
            if record["status"] != "running":
                return False
            record["status"], record["error"] = status, error
            if status == "succeeded":
                record["stage"] = "done"
        return self._change(change)
