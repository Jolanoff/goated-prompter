"""Durable Dataset V2 runs (v2/runs.py): synthetic model, temporary storage, no inference."""

from collections import defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.service import default_dataset_draft
from goated_prompter.features.dataset.v2 import prompts, runs, scenes, understanding
from goated_prompter.json_store import atomic_json
from goated_prompter.local_jobs import Job, JobCancelled

PLACE = re.compile(r"location(\d+)")


class ProcessKilled(BaseException):
    """Stands in for the process dying: nothing in the runner may catch it."""


class RunStoreHarness(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.directory = self.root / "dataset_v2_runs"
        self.saved = []  # every record written, in order

        def write(path, payload):
            atomic_json(path, payload)
            self.saved.append(deepcopy(payload))
        self.write = write
        self.store = runs.DatasetRunStore(self.directory, write=self.write)
        self.config = {"backend": "mock", "dataset_vocabulary": False}
        self.request = GoatedPrompterRequest(idea="Adult reading", planning_mode="Direct", director_preset="general_director")
        self.failing = {"concepts": set(), "staging": set(), "description": set()}
        self.on_call = None  # hook(stage, instruction) before each model answer
        self.calls = []
        self.backend = MockBackend()
        self.enterContext(patch.object(self.backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            self.enterContext(patch.object(module, "create_backend", return_value=self.backend))
        for module in (understanding, scenes, prompts):
            self.enterContext(patch.object(module, "DebugTrace", return_value=Mock()))
        self.enterContext(patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.enterContext(patch.object(runner, "create_backend", return_value=self.backend))
        self.make_brief(3)

    def make_brief(self, amount, guided=()):
        data = {**default_dataset_draft(), "subject": "Alex reads", "amount": amount, "seed": 73, "seed_mode": "fixed"}
        if guided:
            data.update(source_mode="guided", inputs="\n".join(guided))
        value = {"path": "character", "summary": "Alex reads", "fixed": "Alex stays the same", "randomized": "Location",
                 "must": [], "avoid": [],
                 "characters": [{"label": "Alex", "gender": "custom", "custom": "adult human reader", "pronoun": "it", "count": 1}]}
        self.brief = understanding.apply_rules(value, data, Mock())
        return self.brief

    @staticmethod
    def image(text):
        return int(PLACE.search(json.dumps(text)).group(1))

    def generate(self, instruction):
        stage = instruction.diagnostic_stage
        self.calls.append(stage)
        if self.on_call:
            self.on_call(stage, instruction)
        user = json.loads(instruction.user_message) if (instruction.user_message or "").startswith("{") else None
        if stage == "dataset_v2:concepts":
            start = len(user["earlier_concepts"]) + 1
            concepts = []
            for number in range(start, start + user["concepts_needed"]):
                if number in self.failing["concepts"]:
                    break
                concepts.append({"place": f"location{number}", "position_name": "reading", "position": f"arrangement{number}",
                                 "looks": {"Alex": "short hair"}, "lighting": "daylight", "camera": "wide"})
            return json.dumps({"concepts": concepts})
        if stage == "dataset_v2:stagings":
            return json.dumps({"stagings": [
                {"reach": "The book is within reach", "actions": "Alex reads the book",
                 "position": {("Nobody" if self.image(concept) in self.failing["staging"] else "Alex"): f"Seated at {concept['place']}"}}
                for concept in user["concepts"]]})
        if stage == "dataset_v2:scenes":
            out = []
            for row in user["scenes"]:
                number = self.image(row["concept"])
                described = {"subjects": {("Nobody" if number in self.failing["description"] else "Alex"):
                                          {field: f"visible {field}" for field in scenes.SUBJECT_FIELDS}},
                             "space": f"location{number}", "lighting": "daylight", "mood": "calm", "camera": "wide", "extras": "books"}
                out.append(described)
            return json.dumps({"scenes": out})
        found = PLACE.search(instruction.user_message or "") or PLACE.search(instruction.system_message or "")
        return f"Alex reads a book at location{found.group(1)}." if found else "Alex reads a book."

    def run_job(self, *, scenes_only=False, job=None, state=None):
        job = job or Job()
        state = state or SimpleNamespace(dataset_runs=self.store)
        runner.run_dataset_v2_scenes(state, job, self.request, self.config, {"brief": self.brief, "scenes_only": scenes_only})
        return job

    def only_run(self, store=None):
        records, problems = (store or self.store).scan()
        self.assertEqual(len(records), 1, problems)
        return records[0]


class Persistence(RunStoreHarness):
    def test_full_generation_is_saved_and_complete(self):
        job = self.run_job()
        record = self.only_run()
        self.assertEqual(job.result["run_id"], record["run_id"])
        self.assertEqual((record["status"], record["stage"], record["job_id"]), ("succeeded", "done", job.id))
        self.assertEqual((record["schema"], record["requested"], record["seed"]), (2, 3, 73))
        self.assertEqual(record["brief"], self.brief)
        for slot in record["slots"]:
            number = slot["slot"]
            self.assertEqual(slot["concept"]["place"], f"location{number}")
            self.assertIn(f"location{number}", json.dumps(slot["staging"]))
            self.assertEqual((slot["scene_status"], slot["scene"]["slot"], slot["scene"]["space"]), ("written", number, f"location{number}"))
            self.assertEqual(slot["prompt"]["status"], "written")
            self.assertIn(f"location{number}", slot["prompt"]["text"])
        self.assertTrue(runs.is_complete(record))

    def test_partial_concept_staging_and_scene_completion(self):
        self.make_brief(5)
        self.failing["staging"], self.failing["description"], self.failing["concepts"] = {2}, {3}, {5}
        self.run_job()
        record = self.only_run()
        by = {slot["slot"]: slot for slot in record["slots"]}
        self.assertEqual({n: by[n]["scene_status"] for n in by}, {1: "written", 2: "failed", 3: "failed", 4: "written", 5: "failed"})
        self.assertEqual(by[2]["failure"]["stage"], "staging")
        self.assertIsNotNone(by[2]["concept"], "the concept that was completed is kept")
        self.assertIsNone(by[2]["staging"])
        self.assertEqual(by[3]["failure"]["stage"], "description")
        self.assertIsNotNone(by[3]["staging"], "the staging that was completed is kept")
        self.assertEqual(by[5]["failure"]["stage"], "concepts")
        self.assertIsNone(by[5]["concept"])
        self.assertEqual({n for n in by if by[n]["prompt"]}, {1, 4})
        self.assertFalse(runs.is_complete(record))
        self.assertEqual(record["status"], "succeeded")

    def test_each_completed_scene_is_saved_before_its_batch_finishes(self):
        self.run_job()
        written = [sum(slot["scene"] is not None for slot in saved["slots"]) for saved in self.saved]
        steps = sorted(set(written))
        self.assertEqual(steps, [0, 1, 2, 3], "scenes become durable one at a time")
        first_scene = written.index(1)
        self.assertEqual(written[first_scene - 1], 0)
        self.assertEqual(self.saved[first_scene]["slots"][1]["scene"], None, "slot 2 was not yet saved when slot 1 was")

    def test_prompts_are_saved_as_each_is_written(self):
        seen = []
        def on_call(stage, instruction):
            if not stage.startswith("dataset_v2:"):
                record = self.only_run()
                seen.append([slot["slot"] for slot in record["slots"] if slot["prompt"]])
        self.on_call = on_call
        self.run_job()
        self.assertEqual(seen, [[], [1], [1, 2]], "each prompt was durable before the next one was requested")

    def test_failed_first_middle_and_final_slots_keep_their_ids(self):
        for failed in ({1}, {2}, {3}, {1, 3}):
            with self.subTest(failed=failed):
                shutil.rmtree(self.directory, ignore_errors=True)
                self.failing["description"] = set(failed)
                job = self.run_job()
                record = self.only_run()
                self.assertEqual([slot["slot"] for slot in record["slots"]], [1, 2, 3])
                self.assertEqual({slot["slot"] for slot in record["slots"] if slot["scene_status"] == "failed"}, failed)
                for slot in record["slots"]:
                    if slot["scene"]:
                        self.assertEqual(slot["scene"]["space"], f"location{slot['slot']}")
                        self.assertIn(f"location{slot['slot']}", slot["prompt"]["text"])
                self.assertEqual(sorted(item["slot"] for item in job.result["prompts"]),
                                 sorted({1, 2, 3} - failed))

    def test_scenes_only_run_is_complete_without_prompts(self):
        self.run_job(scenes_only=True)
        record = self.only_run()
        self.assertEqual((record["status"], record["stage"], record["scenes_only"]), ("succeeded", "done", True))
        self.assertTrue(all(slot["prompt"] is None for slot in record["slots"]))
        self.assertTrue(runs.is_complete(record))

    def test_guided_inputs_are_saved_per_slot_from_the_start(self):
        self.make_brief(3, guided=("one", "two", "three"))
        self.failing["description"] = {2}
        first = []
        self.on_call = lambda stage, _instruction: first.append(self.only_run()) if not first else None
        self.run_job()
        self.assertEqual([slot["input"] for slot in first[0]["slots"]], ["one", "two", "three"], "saved before any inference")
        self.assertEqual([slot["input"] for slot in self.only_run()["slots"]], ["one", "two", "three"])

    def test_without_a_store_generation_is_unchanged(self):
        job = Job()
        runner.run_dataset_v2_scenes(None, job, self.request, self.config, {"brief": self.brief})
        self.assertEqual(job.status, "succeeded")
        self.assertNotIn("run_id", job.result)
        self.assertFalse(self.directory.exists())


class Interruption(RunStoreHarness):
    def cancel_on(self, job, stage, count=1):
        seen = defaultdict(int)
        def on_call(name, _instruction):
            seen[name] += 1
            if name == stage and seen[name] == count:
                job.cancel_requested = True
        self.on_call = on_call

    def test_cancellation_during_scene_generation_keeps_completed_concepts(self):
        job = Job()
        self.cancel_on(job, "dataset_v2:stagings")
        with self.assertRaises(JobCancelled):
            self.run_job(job=job)
        record = self.only_run()
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual([slot["concept"]["place"] for slot in record["slots"]], ["location1", "location2", "location3"])
        self.assertTrue(all(slot["scene_status"] == "pending" for slot in record["slots"]), "unfinished, not failed")

    def test_cancellation_during_prompt_generation_keeps_written_prompts(self):
        job = Job()
        builder = defaultdict(int)
        def on_call(stage, _instruction):
            if not stage.startswith("dataset_v2:"):
                builder["calls"] += 1
                if builder["calls"] == 2:
                    job.cancel_requested = True
        self.on_call = on_call
        with self.assertRaises(JobCancelled):
            self.run_job(job=job)
        record = self.only_run()
        self.assertEqual(record["status"], "cancelled")
        self.assertTrue(all(slot["scene_status"] == "written" for slot in record["slots"]))
        self.assertEqual(record["slots"][0]["prompt"]["status"], "written")
        self.assertIsNone(record["slots"][2]["prompt"])
        self.assertFalse(runs.is_complete(record))

    def test_server_stop_marks_the_run_interrupted(self):
        job = Job()
        def on_call(stage, _instruction):
            if stage == "dataset_v2:scenes":
                job.stopping = True
        self.on_call = on_call
        with self.assertRaises(ValueError):
            self.run_job(job=job)
        self.assertEqual(self.only_run()["status"], "interrupted")

    def test_restart_after_partial_completion_keeps_work_and_runs_nothing(self):
        def on_call(stage, _instruction):
            if stage == "dataset_v2:scenes":
                raise ProcessKilled()
        self.on_call = on_call
        with self.assertRaises(ProcessKilled):
            self.run_job()
        before = self.only_run()
        self.assertEqual(before["status"], "running", "a killed process could not record its end")
        calls = len(self.calls)
        restarted = runs.DatasetRunStore(self.directory)
        report = restarted.recover()
        after = self.only_run(restarted)
        self.assertEqual(report, {"interrupted": [before["run_id"]], "problems": {}})
        self.assertEqual((after["status"], after["error"]), ("interrupted", runs.INTERRUPTED))
        self.assertEqual([slot["staging"] for slot in after["slots"]], [slot["staging"] for slot in before["slots"]])
        self.assertTrue(all(slot["staging"] for slot in after["slots"]))
        self.assertEqual([slot["slot"] for slot in after["slots"]], [1, 2, 3])
        self.assertEqual(len(self.calls), calls, "recovery starts no inference")
        self.assertEqual(restarted.recover()["interrupted"], [], "recovery is idempotent")

    def test_restart_after_success_changes_nothing(self):
        self.run_job()
        path = next(self.directory.glob("*.json"))
        before = path.read_bytes()
        self.assertEqual(runs.DatasetRunStore(self.directory).recover(), {"interrupted": [], "problems": {}})
        self.assertEqual(path.read_bytes(), before)

    def test_a_failed_save_stops_the_job_and_keeps_the_last_good_version(self):
        failures = {"left": 4}
        def flaky(path, payload):
            failures["left"] -= 1
            if failures["left"] == 0:
                raise OSError("disk full")
            self.write(path, payload)
        self.store.write = flaky
        job = Job()
        with self.assertRaises(runs.RunStoreError):
            self.run_job(job=job)
        record = self.only_run()
        self.assertEqual(record, self.saved[-1], "the file is the last version that was saved")
        self.assertEqual(record["status"], "failed", "the end of the run was still recorded")

    def test_an_interrupted_atomic_write_leaves_the_previous_version(self):
        self.run_job()
        path = next(self.directory.glob("*.json"))
        before = path.read_bytes()
        record = json.loads(before)
        with patch("goated_prompter.json_store.os.replace", side_effect=OSError("power cut")):
            with self.assertRaises(runs.RunStoreError):
                self.store.update(record["run_id"], lambda working: working.update(error="never saved"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob("*.tmp")), [], "no temporary file is left behind")
        (self.directory / f"{path.name}.abc.tmp").write_text('{"half": ', encoding="utf-8")
        self.assertEqual(self.store.scan()[1], {}, "a stray temporary file is ignored")


class Integrity(RunStoreHarness):
    def test_corrupt_and_incompatible_files_are_reported_and_never_touched(self):
        self.run_job()
        good = self.only_run()
        self.directory.joinpath("0" * 32 + ".json").write_text("{not json", encoding="utf-8")
        future = {**good, "schema": 3, "run_id": "1" * 32}  # a schema this version does not know
        self.directory.joinpath("1" * 32 + ".json").write_text(json.dumps(future), encoding="utf-8")
        renumbered = deepcopy(good)
        renumbered["run_id"] = "2" * 32
        renumbered["slots"][0]["slot"] = 2
        self.directory.joinpath("2" * 32 + ".json").write_text(json.dumps(renumbered), encoding="utf-8")
        snapshot = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        records, problems = self.store.scan()
        self.assertEqual([record["run_id"] for record in records], [good["run_id"]])
        self.assertEqual(set(problems), {"0" * 32 + ".json", "1" * 32 + ".json", "2" * 32 + ".json"})
        self.assertIn("Unsupported Dataset run schema 3", problems["1" * 32 + ".json"])
        self.assertIn("never renumbered", problems["2" * 32 + ".json"])
        runs.DatasetRunStore(self.directory).recover()
        self.assertEqual(self.store.retention_candidates(keep_complete=0, keep_incomplete=0), [good["run_id"]])
        for name, data in snapshot.items():
            if name != f"{good['run_id']}.json":
                self.assertEqual(self.directory.joinpath(name).read_bytes(), data, name)
        with self.assertRaises(runs.IncompatibleRun):
            self.store.get("1" * 32)
        with self.assertRaises(runs.RunStoreError):
            self.store.update("0" * 32, lambda working: None)

    def test_revision_compare_and_set(self):
        record = self.store.create("job-a", self.brief)
        saved = self.store.update(record["run_id"], lambda working: working.update(error="edited"), expected_revision=0)
        self.assertEqual(saved["revision"], 1)
        with self.assertRaises(runs.RunConflict):
            self.store.update(record["run_id"], lambda working: working.update(error="stale"), expected_revision=0)
        self.assertEqual(self.store.get(record["run_id"])["error"], "edited")

    def test_another_job_cannot_write_into_a_run(self):
        record = self.store.create("job-a", self.brief)
        stranger = runs.RunRecorder(self.store, {**record, "job_id": "job-b"})
        with self.assertRaises(runs.RunConflict):
            stranger.slot_event("concept", 1, {"place": "location1"})
        self.assertIsNone(self.store.get(record["run_id"])["slots"][0]["concept"])

    def test_completed_results_are_never_replaced_and_repeats_change_nothing(self):
        recorder = runs.RunRecorder.start(self.store, "job-a", self.brief)
        concept = {"place": "location1"}
        first = recorder.slot_event("concept", 1, concept)
        again = recorder.slot_event("concept", 1, concept)
        self.assertEqual(again["revision"], first["revision"], "publishing the same result twice is not a new change")
        with self.assertRaises(runs.RunConflict):
            recorder.slot_event("concept", 1, {"place": "elsewhere"})
        recorder.finish("cancelled")
        with self.assertRaises(runs.RunConflict):
            recorder.slot_event("concept", 2, {"place": "late"})
        self.assertIsNone(self.store.get(recorder.run_id)["slots"][1]["concept"], "a finished run takes no late results")

    def test_concurrent_slot_updates_keep_every_slot(self):
        self.make_brief(8)
        recorder = runs.RunRecorder.start(self.store, "job-a", self.brief)
        errors = []
        def fill(number):
            try:
                for round_ in range(5):
                    self.store.update(recorder.run_id, lambda working, n=number, r=round_: working["slots"][n - 1].update(
                        concept={"place": f"location{n}", "round": r}, revision=working["slots"][n - 1]["revision"] + 1))
            except Exception as error:  # surfaced below
                errors.append(error)
        threads = [threading.Thread(target=fill, args=(number,)) for number in range(1, 9)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        record = self.store.get(recorder.run_id)
        self.assertEqual(record["revision"], 40)
        self.assertEqual([slot["concept"] for slot in record["slots"]], [{"place": f"location{n}", "round": 4} for n in range(1, 9)])
        self.assertEqual([slot["revision"] for slot in record["slots"]], [5] * 8)

    def test_unrelated_runs_are_preserved(self):
        self.run_job()
        first = next(self.directory.glob("*.json"))
        before = first.read_bytes()
        self.failing["description"] = {2}
        self.run_job()
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(len(self.store.scan()[0]), 2)

    def test_the_schema_rejects_inconsistent_records(self):
        record = self.store.create("job-a", self.brief)
        broken = [
            lambda r: r.update(seed=1),
            lambda r: r["slots"].pop(),
            lambda r: r["slots"][0].update(scene_status="written"),
            lambda r: r["slots"][0].update(scene_status="failed"),
            lambda r: r["slots"][0].update(prompt={"status": "written", "text": "x", "trigger_ok": True, "error": None,
                                                   "stage": None, "attempts": None}),
            lambda r: r.update(status="done"),
            lambda r: r.update(extra=True),
        ]
        for index, damage in enumerate(broken):
            with self.subTest(case=index):
                value = deepcopy(record)
                damage(value)
                with self.assertRaises(runs.RunStoreError):
                    runs.validate_run(value)


class Retention(RunStoreHarness):
    """Runs are user work: nothing is ever deleted automatically."""

    def finished(self, status, complete, when):
        with patch.object(self.store, "clock", return_value=when):
            record = self.store.create("job", self.brief)
        def change(working):
            working["status"], working["updated_at"] = status, when
            if complete:
                for slot in working["slots"]:
                    slot["scene"], slot["scene_status"] = {"slot": slot["slot"]}, "written"
                    slot["prompt"] = {"status": "written", "text": "p", "trigger_ok": True, "error": None,
                                      "stage": None, "attempts": None}
        with patch.object(self.store, "clock", return_value=when):
            return self.store.update(record["run_id"], change)["run_id"]

    def test_new_runs_never_delete_earlier_runs_of_any_status(self):
        earlier = {status: [self.finished(status, status == "succeeded", 100 + n) for n in range(25)]
                   for status in ("succeeded", "failed", "cancelled", "interrupted")}
        earlier["succeeded_partial"] = [self.finished("succeeded", False, 300 + n) for n in range(3)]
        files = {path.name: path.read_bytes() for path in self.directory.glob("*.json")}
        self.assertEqual(len(files), 103)
        for _ in range(5):
            self.store.create("new-job", self.brief)
        self.run_job()
        for name, data in files.items():
            self.assertEqual(self.directory.joinpath(name).read_bytes(), data, f"{name} was changed or removed")
        self.assertEqual(len(self.store.scan()[0]), 103 + 5 + 1)

    def test_the_store_has_no_deleting_operation(self):
        self.assertFalse([name for name in dir(runs.DatasetRunStore) if name in {"prune", "delete", "remove", "cleanup"}])
        removed, real_unlink, real_remove = [], Path.unlink, os.remove
        def unlink(path, *args, **kwargs):
            removed.append(str(path))
            return real_unlink(path, *args, **kwargs)
        def remove(path, *args, **kwargs):
            removed.append(str(path))
            return real_remove(path, *args, **kwargs)
        with patch("pathlib.Path.unlink", unlink), patch("os.remove", remove):
            for n in range(3):
                self.finished("succeeded", True, 10 + n)
            self.run_job()
            runs.DatasetRunStore(self.directory).recover()
            self.store.retention_candidates(keep_complete=0, keep_incomplete=0)
        self.assertEqual([path for path in removed if path.endswith(".json")], [],
                         "only atomic_json's own temporary files may be removed")

    def test_retention_candidates_are_reported_not_removed(self):
        complete = [self.finished("succeeded", True, 1000 + n) for n in range(22)]
        incomplete = [self.finished(status, False, 2000 + n) for n, status in enumerate(["failed", "cancelled", "interrupted"] * 7)]
        active = self.store.create("active-job", self.brief)["run_id"]
        self.directory.joinpath("f" * 32 + ".json").write_text("{damaged", encoding="utf-8")
        candidates = self.store.retention_candidates()
        self.assertEqual(set(candidates), set(complete[:2]) | set(incomplete[:1]), "the oldest beyond 20 of each kind")
        self.assertNotIn(active, candidates)
        self.assertEqual(len(self.store.scan()[0]), 22 + 21 + 1, "reporting candidates deletes nothing")
        self.assertTrue(self.directory.joinpath("f" * 32 + ".json").exists())


class Limits(RunStoreHarness):
    def over_the_limit(self, refuse, slack):
        """Run once to measure, then again with the limit just below the save chosen by refuse(saved)."""
        size = lambda record: len((json.dumps(record, ensure_ascii=True, indent=2) + "\n").encode())
        self.store.clock = lambda: 1000.0  # fixed timestamps: identical record sizes in both runs
        self.run_job()
        refused = next(index for index, saved in enumerate(self.saved) if refuse(saved))
        limit = size(self.saved[refused]) - slack
        shutil.rmtree(self.directory)
        self.saved.clear()
        with patch("goated_prompter.json_store.MAX_STORE_BYTES", limit):
            with self.assertRaises(runs.RunStoreError) as raised:
                self.run_job()
        self.assertIn("16 MiB limit", str(raised.exception))
        self.assertIn("the previous version is kept", str(raised.exception))
        self.assertEqual(list(self.directory.glob("*.tmp")), [], "nothing half-written is left")
        record = self.only_run()
        self.assertEqual(record, self.saved[-1], "the file is the last version that fit")
        return record

    def test_a_refused_prompt_keeps_every_scene_and_records_the_failure(self):
        record = self.over_the_limit(lambda saved: any(slot["prompt"] for slot in saved["slots"]), slack=1)
        self.assertEqual([slot["scene_status"] for slot in record["slots"]], ["written"] * 3, "all scenes are kept")
        self.assertEqual([slot["prompt"] for slot in record["slots"]], [None] * 3, "the refused prompt was not saved")
        self.assertEqual(record["status"], "failed", "the end-of-run record is smaller and still fits")
        self.assertIn("16 MiB limit", record["error"])
        self.assertEqual(runs.DatasetRunStore(self.directory).recover()["interrupted"], [])

    def test_when_even_the_failure_cannot_be_saved_restart_marks_the_run_interrupted(self):
        # The limit sits just above the new, empty run: the first concept and the failure record both exceed it.
        record = self.over_the_limit(lambda saved: True, slack=-8)
        self.assertEqual(record["revision"], 0, "only the newly created run fits")
        self.assertEqual(record["status"], "running", "the failure record does not fit either")
        restarted = runs.DatasetRunStore(self.directory)
        self.assertEqual(restarted.recover()["interrupted"], [record["run_id"]])
        self.assertEqual(restarted.get(record["run_id"])["status"], "interrupted")

    def test_a_full_25_image_run_is_far_below_the_limit(self):
        self.make_brief(25)
        self.run_job()
        path = next(self.directory.glob("*.json"))
        self.assertLess(path.stat().st_size, 1024 * 1024)


class FinalStatus(RunStoreHarness):
    """The stored status always matches the job's final status; completed work is always kept."""

    def test_a_cancellation_while_the_result_is_delivered_cancels_the_run_too(self):
        class RacingJob(Job):
            def deliver(self, result):
                def value():
                    produced = result() if callable(result) else result
                    self.cancel_requested = True  # lands after the result exists, before the job is marked done
                    return produced
                return super().deliver(value)
        job = RacingJob()
        with self.assertRaises(JobCancelled):
            self.run_job(job=job)
        job.mark_cancelled()  # what LocalState.execute does with JobCancelled
        record = self.only_run()
        self.assertEqual((job.status, record["status"]), ("cancelled", "cancelled"))
        self.assertTrue(all(slot["scene_status"] == "written" and slot["prompt"]["status"] == "written"
                            for slot in record["slots"]), "every completed result is kept")

    def test_a_cancellation_that_surfaces_as_another_error_is_still_cancelled(self):
        job = Job()
        def on_call(stage, _instruction):
            if stage == "dataset_v2:stagings":
                job.cancel_requested = True
                raise ConnectionError("transport closed by the cancellation")
        self.on_call = on_call
        with self.assertRaises(ConnectionError):
            self.run_job(job=job)
        record = self.only_run()
        self.assertEqual(record["status"], "cancelled")
        self.assertTrue(all(slot["concept"] for slot in record["slots"]))

    def test_succeeded_is_written_only_after_the_job_succeeded(self):
        statuses = []
        real = runs.RunRecorder.finish
        def observe(recorder, status, error=None):
            statuses.append((status, job.status))
            return real(recorder, status, error)
        job = Job()
        with patch.object(runs.RunRecorder, "finish", observe):
            self.run_job(job=job)
        self.assertEqual(statuses, [("succeeded", "succeeded")])
        self.assertEqual(self.only_run()["status"], "succeeded")

    def test_every_outcome_matches_between_job_and_run(self):
        cases = {
            "failed": lambda job: (_ for _ in ()).throw(RuntimeError("model error")),
            "cancelled": lambda job: setattr(job, "cancel_requested", True),
            "interrupted": lambda job: setattr(job, "stopping", True),
        }
        for expected, act in cases.items():
            with self.subTest(outcome=expected):
                shutil.rmtree(self.directory, ignore_errors=True)
                job = Job()
                def on_call(stage, _instruction, act=act, job=job):
                    if stage == "dataset_v2:scenes":
                        act(job)
                self.on_call = on_call
                with self.assertRaises(BaseException):
                    self.run_job(job=job)
                self.assertEqual(self.only_run()["status"], expected)


class PackSelection(RunStoreHarness):
    """Phase 2: the run's own vocabulary pack selection, recorded before inference and never changed."""

    def setUp(self):
        super().setUp()
        from goated_prompter.features.dataset.v2 import vocabulary_packs
        from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, OFFICIAL_DIR, PackManager
        self.vocabulary_packs = vocabulary_packs
        self.config = {"backend": "mock", "dataset_vocabulary": True}
        packs = self.root / "packs"
        (packs / "harbor").mkdir(parents=True)
        (packs / "harbor" / "manifest.json").write_text(json.dumps(
            {"spec": 1, "id": "harbor", "name": "Harbor", "version": "1.0.0", "rating": "general",
             "requires": {"core": ">=1.0.0 <2.0.0"}, "files": ["entries.json"]}), encoding="utf-8")
        (packs / "harbor" / "entries.json").write_text(json.dumps({"spec": 1, "entries": [
            {"id": "harbor:space.quay", "category": "space", "name": "Stone quay", "description": "A quay of old stone.",
             "components": {"environment": {"provides": ["core:surface.ground"]}}}]}), encoding="utf-8")
        self.manager = PackManager(packs, self.root / "state.json", bundled_dirs=BUNDLED_DIRS, official_dir=OFFICIAL_DIR)
        self.enterContext(patch.object(vocabulary_packs, "PackManager", return_value=self.manager))

    def select(self, packs):
        return self.vocabulary_packs.select_packs(self.config, packs)

    def run_with(self, selection, **options):
        job = Job()
        workflow = {"brief": self.brief, "scenes_only": options.get("scenes_only", False), "vocabulary_packs": selection}
        runner.run_dataset_v2_scenes(SimpleNamespace(dataset_runs=self.store), job, self.request, self.config, workflow)
        return job

    def test_the_selection_is_recorded_before_any_inference_and_used(self):
        selection = self.select(["harbor"])
        seen = []
        self.on_call = lambda stage, instruction: seen.append(self.only_run()["packs"])
        job = self.run_with(selection)
        self.assertEqual(job.status, "succeeded")
        self.assertTrue(seen and all(packs == selection for packs in seen), "saved before the first model call")
        record = self.only_run()
        self.assertEqual((record["schema"], record["packs"]), (2, selection))
        self.assertEqual(runs.recorded_packs(record), selection)
        self.assertEqual(record["vocabulary"]["enabled"], True)

    def test_a_run_reads_exactly_its_selection(self):
        concept_vocabulary = []
        self.on_call = lambda stage, instruction: concept_vocabulary.append(instruction.user_message) if stage == "dataset_v2:concepts" else None
        self.make_brief(2)
        self.brief["randomized"] = "location"
        self.run_with(self.select([]))
        self.assertFalse(any("Stone quay" in message for message in concept_vocabulary), "an unselected pack never takes part")

    def test_a_pack_changed_since_confirmation_stops_the_run_before_inference(self):
        selection = self.select(["harbor"])
        entries = self.root / "packs" / "harbor" / "entries.json"
        entries.write_text(entries.read_text(encoding="utf-8").replace("Stone quay", "Granite quay"), encoding="utf-8")
        job = Job()
        with self.assertRaises(ValueError) as caught:
            runner.run_dataset_v2_scenes(SimpleNamespace(dataset_runs=self.store), job, self.request, self.config,
                                         {"brief": self.brief, "scenes_only": False, "vocabulary_packs": selection})
        self.assertIn("changed since this run was confirmed", str(caught.exception))
        self.assertEqual(self.calls, [], "no model call: there is no fallback to other pack content")
        record = self.only_run()
        self.assertEqual((record["status"], record["packs"]), ("failed", selection))

    def test_a_global_disable_never_changes_a_recorded_selection(self):
        selection = self.select(["harbor"])
        self.manager.set_enabled("harbor", False)
        self.assertEqual(self.run_with(selection).status, "succeeded")
        self.assertEqual(self.only_run()["packs"], selection)

    def test_the_recorded_selection_and_schema_never_change(self):
        job = self.run_with(self.select(["harbor"]))
        record = self.only_run()
        path = self.directory / f"{record['run_id']}.json"
        before = path.read_bytes()
        for change in (lambda working: working.update(packs=self.select([])), lambda working: working.update(schema=1)):
            with self.assertRaises(runs.RunConflict):
                self.store.update(record["run_id"], change)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(job.status, "succeeded")

    def test_schema_1_runs_stay_readable_unchanged_and_not_recorded(self):
        self.run_with(self.select(["harbor"]))
        record = self.only_run()
        old = {key: value for key, value in record.items() if key != "packs"}
        old.update(schema=1, run_id="3" * 32, status="running")
        path = self.directory / f"{'3' * 32}.json"
        path.write_text(json.dumps(old), encoding="utf-8")
        loaded = self.store.get("3" * 32)
        self.assertEqual(loaded["schema"], 1)
        self.assertEqual(runs.recorded_packs(loaded), {"recorded": False}, "no selection is invented from today's settings")
        untouched = self.directory / f"{record['run_id']}.json"
        before = untouched.read_bytes()
        self.store.recover()
        recovered = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((recovered["schema"], recovered["status"], "packs" in recovered), (1, "interrupted", False),
                         "a schema 1 run is updated as schema 1")
        self.assertEqual(untouched.read_bytes(), before, "a finished schema 2 run is not rewritten")

    def test_a_disabled_vocabulary_is_recorded_as_such(self):
        self.config = {"backend": "mock", "dataset_vocabulary": False}
        selection = self.select(["harbor"])
        self.assertEqual(selection, {"version": 1, "enabled": False, "selected": [], "packs": []})
        self.run_with(selection)
        self.assertEqual(self.only_run()["packs"], selection)

    def test_slot_identity_and_cancellation_hold_with_a_selection(self):
        self.failing["description"] = {2}
        job = self.run_with(self.select(["harbor"]))
        record = self.only_run()
        self.assertEqual([slot["scene_status"] for slot in record["slots"]], ["written", "failed", "written"])
        self.assertEqual(job.status, "succeeded")
        cancelled = Job()
        def cancel(stage, instruction):
            if stage == "dataset_v2:stagings":
                cancelled.cancel_requested = True
                raise JobCancelled()
        self.on_call = cancel
        with self.assertRaises(JobCancelled):
            runner.run_dataset_v2_scenes(SimpleNamespace(dataset_runs=self.store), cancelled, self.request, self.config,
                                         {"brief": self.brief, "scenes_only": False, "vocabulary_packs": self.select(["harbor"])})
        newest = self.store.find_by_job(cancelled.id)
        self.assertEqual((newest["status"], newest["schema"]), ("cancelled", 2))
        self.assertEqual(newest["packs"]["selected"], ["harbor"])


if __name__ == "__main__":
    unittest.main()
