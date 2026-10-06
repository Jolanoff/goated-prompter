from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

import local_app as local
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import default_dataset_draft
from goated_prompter.dataset_checkpoints import generation_signature
from goated_prompter.workspace_api import execute_workflow
from goated_prompter.workspace_store import WorkspaceConflict
from goated_prompter.json_store import atomic_json


class DatasetCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.json"
        self.state = self.make_state()
        self.data = {**default_dataset_draft(), "subject": "A craftsperson", "trigger": "token", "amount": 1}
        self.row = {"index": 1, "input": "", "idea": "Center clay", "scene": "Both palms center clay on a spinning wheel.", "geometry": {}}

    def make_state(self):
        return local.LocalState(lambda: {"backend": "mock"}, None, self.path)

    def begin(self):
        job = local.Job()
        job.kind = "dataset"
        self.state.workflow_settings.begin_dataset(job, self.data)
        return job

    def result(self):
        return {"kind": "dataset", "completed": 1, "total": 1, "scene_plan": [self.row],
                "scene_plan_signature": "test", "prompts": [{"index": 1, "input": "", "prompt": "token centers clay."}]}

    def test_backend_partial_persists_without_browser_or_autosave(self):
        job = self.begin()
        result = self.result()
        class Service:
            def __init__(self, *args, **kwargs):
                pass
            def run(self, request, data, progress, partial, **kwargs):
                partial(result)
                raise ValueError("writer unavailable")
        with patch("goated_prompter.workspace_api.DatasetService", Service):
            with self.assertRaisesRegex(ValueError, "writer unavailable"):
                execute_workflow(self.state, job, GoatedPrompterRequest(idea="craft"), {"backend": "mock"},
                                 {"operation": "dataset", "input": self.data})
        raw = self.state.workflow_settings._read()["dataset"]
        self.assertEqual(raw["draft"]["results"], [])
        saved = self.state.workflow_settings.snapshot("dataset")
        self.assertEqual(saved["draft"]["results"], result["prompts"])
        self.assertEqual(saved["revision"], raw["revision"])
        restarted = self.make_state()
        recovered = restarted.workflow_settings.snapshot("dataset")
        self.assertEqual(recovered["draft"]["scene_plan"], result["scene_plan"])
        self.assertEqual(recovered["checkpoint_status"], "interrupted")
        self.assertEqual(restarted.dataset_checkpoints.find(job.id)["result"], result)

    def test_old_checkpoint_metadata_does_not_block_startup_or_rewrite_archived_scenes(self):
        job = self.begin()
        job.result = self.result()
        job.status = "succeeded"
        self.state.workflow_settings.checkpoint_dataset(job)
        store = self.state.dataset_checkpoints.snapshot()
        archived = store["jobs"][0]["snapshot"]["result"]
        archived["scene_plan"][0]["legacy_scene_review"] = {"note": "Synthetic old-version metadata", "passed": True}
        original_result = deepcopy(archived)
        atomic_json(self.state.dataset_checkpoints.path, store)
        before = self.state.dataset_checkpoints.path.read_bytes()
        restarted = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=self.path)[local.STATE]
        self.assertEqual(restarted.dataset_checkpoints.find(job.id)["result"], original_result)
        self.assertEqual(restarted.dataset_checkpoints.path.read_bytes(), before)
        projected = restarted.workflow_settings.snapshot("dataset")["draft"]
        self.assertEqual(projected["scene_plan"], self.result()["scene_plan"])
        self.assertEqual(projected["results"], self.result()["prompts"])

    def test_legacy_scene_metadata_in_checkpoint_input_and_result_survives_startup_and_new_saves(self):
        job = local.Job()
        job.kind = "dataset"
        self.state.workflow_settings.begin_dataset(job, {**self.data, "scene_plan": [self.row]})
        job.result = self.result()
        self.state.workflow_settings.checkpoint_dataset(job)
        store = self.state.dataset_checkpoints.snapshot()
        archived = store["jobs"][0]
        for plan in (archived["input"]["scene_plan"], archived["snapshot"]["result"]["scene_plan"]):
            plan[0]["legacy_scene_review"] = {"note": "Synthetic archived input metadata", "passed": True}
        original = deepcopy(archived)
        atomic_json(self.state.dataset_checkpoints.path, store)
        restarted = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=self.path)[local.STATE]
        projected = restarted.workflow_settings.snapshot("dataset")["draft"]
        self.assertEqual(projected["scene_plan"], [self.row])
        self.assertEqual(projected["results"], job.result["prompts"])
        self.assertEqual(restarted.dataset_checkpoints.find(job.id)["status"], "interrupted")
        newer = local.Job()
        newer.kind = "dataset"
        restarted.workflow_settings.begin_dataset(newer, {**self.data, "subject": "Another synthetic craft"})
        saved = restarted.dataset_checkpoints.snapshot()["jobs"]
        self.assertEqual([row["job_id"] for row in saved], [job.id, newer.id])
        self.assertEqual(saved[0]["input"], original["input"])
        self.assertEqual(saved[0]["input_signature"], original["input_signature"])
        self.assertEqual(saved[0]["snapshot"]["result"], original["snapshot"]["result"])

    def test_legacy_checkpoint_input_still_rejects_invalid_scene_content_without_overwriting_it(self):
        job = self.begin()
        original = self.state.dataset_checkpoints.snapshot()
        for changes in ({"index": 2}, {"index": True}, {"input": None}, {"scene": []}):
            with self.subTest(changes=changes):
                store = deepcopy(original)
                store["jobs"][0]["input"]["scene_plan"] = [{**self.row, **changes,
                    "legacy_scene_review": {"passed": True}}]
                atomic_json(self.state.dataset_checkpoints.path, store)
                before = self.state.dataset_checkpoints.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "Saved scenes require"):
                    self.make_state()
                self.assertEqual(self.state.dataset_checkpoints.path.read_bytes(), before)

    def test_interrupted_legacy_checkpoint_keeps_its_scene_metadata_when_new_jobs_are_saved(self):
        job = self.begin()
        job.result = self.result()
        self.state.workflow_settings.checkpoint_dataset(job)
        store = self.state.dataset_checkpoints.snapshot()
        store["jobs"][0]["snapshot"]["result"]["scene_plan"][0]["legacy_scene_review"] = {"passed": True}
        archived = deepcopy(store["jobs"][0])
        atomic_json(self.state.dataset_checkpoints.path, store)
        restarted = self.make_state()
        recovered = restarted.dataset_checkpoints.find(job.id)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["result"], archived["snapshot"]["result"])
        newer = local.Job()
        newer.kind = "dataset"
        restarted.workflow_settings.begin_dataset(newer, {**self.data, "subject": "A different synthetic craft"})
        saved = restarted.dataset_checkpoints.snapshot()["jobs"]
        self.assertEqual([row["job_id"] for row in saved], [job.id, newer.id])
        self.assertEqual(saved[0]["snapshot"]["result"], archived["snapshot"]["result"])
        self.assertEqual(saved[0]["input"], archived["input"])

    def test_legacy_metadata_tolerance_does_not_hide_broken_indexes_or_scene_types(self):
        job = self.begin()
        job.result = self.result()
        job.status = "succeeded"
        self.state.workflow_settings.checkpoint_dataset(job)
        original = self.state.dataset_checkpoints.snapshot()
        for changes in ({"index": 2}, {"index": True}, {"input": None}, {"scene": []}, {"scene": "x" * 10001}):
            with self.subTest(changes=changes):
                store = deepcopy(original)
                scene = store["jobs"][0]["snapshot"]["result"]["scene_plan"][0]
                scene.update(changes, legacy_scene_review={"passed": True})
                atomic_json(self.state.dataset_checkpoints.path, store)
                before = self.state.dataset_checkpoints.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "Saved scenes require"):
                    self.make_state()
                self.assertEqual(self.state.dataset_checkpoints.path.read_bytes(), before)

    def test_current_generation_inputs_still_reject_unknown_scene_metadata(self):
        before = self.state.dataset_checkpoints.snapshot()
        with self.assertRaisesRegex(ValueError, "Saved scenes require"):
            self.state.workflow_settings.begin_dataset(local.Job(), {**self.data,
                "scene_plan": [{**self.row, "legacy_scene_review": {"passed": True}}]})
        self.assertEqual(self.state.dataset_checkpoints.snapshot(), before)

    def test_stale_job_never_overlays_newer_settings_or_manual_scene(self):
        job = self.begin()
        current = self.state.workflow_settings.snapshot("dataset")
        newer = {**current["draft"], "subject": "New user concept", "scene_plan": [self.row]}
        self.state.workflow_settings.update("dataset", current["revision"], draft=newer)
        job.result = self.result()
        self.state.workflow_settings.checkpoint_dataset(job)
        saved = self.state.workflow_settings.snapshot("dataset")
        self.assertEqual(saved["draft"], newer)
        self.assertNotIn("checkpoint", saved)
        historical = self.state.dataset_checkpoints.find(job.id)
        self.assertTrue(historical["stale"])
        self.assertEqual(historical["result"], job.result)

    def test_revision_rejects_stale_admission(self):
        self.begin()
        with self.assertRaises(WorkspaceConflict):
            self.state.workflow_settings.begin_dataset(local.Job(), self.data, 0)

    def test_signature_includes_manual_geometry_and_writer_controls(self):
        self.assertNotEqual(generation_signature(self.data), generation_signature({**self.data, "length": "Short"}))
        self.assertNotEqual(generation_signature(self.data), generation_signature({**self.data, "scene_plan": [self.row]}))

    def test_atomic_write_failure_retains_prior_checkpoint(self):
        job = self.begin()
        job.result = self.result()
        self.state.workflow_settings.checkpoint_dataset(job)
        before = self.state.dataset_checkpoints.snapshot()
        with patch.object(self.state.dataset_checkpoints, "write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.state.workflow_settings.checkpoint_dataset(job)
        self.assertEqual(self.state.dataset_checkpoints.snapshot(), before)

    def test_released_diagnostics_do_not_erase_generated_progress(self):
        job = self.begin()
        job.result = self.result()
        job.status = "succeeded"
        self.state.workflow_settings.checkpoint_dataset(job)
        self.state.dataset_checkpoints.release([job.id])
        self.assertIsNone(self.state.dataset_checkpoints.find(job.id))
        self.assertEqual(self.state.workflow_settings.snapshot("dataset")["draft"]["results"], job.result["prompts"])

    def test_checkpoint_store_rejects_corrupt_job_binding_before_projection(self):
        from goated_prompter.dataset_checkpoints import validate_checkpoints
        job = self.begin()
        store = self.state.dataset_checkpoints.snapshot()
        store["jobs"][0]["snapshot"]["id"] = "another-job"
        with self.assertRaisesRegex(ValueError, "snapshot"):
            validate_checkpoints(store)

    def test_byte_budget_prunes_old_terminal_records_not_current_valid_siblings(self):
        old = self.begin()
        old.result = self.result()
        old.status = "succeeded"
        self.state.workflow_settings.checkpoint_dataset(old)
        with patch("goated_prompter.dataset_checkpoints.CHECKPOINT_BYTE_BUDGET", 1):
            current = self.begin()
        records = self.state.dataset_checkpoints.snapshot()["jobs"]
        self.assertEqual([row["job_id"] for row in records], [current.id])
