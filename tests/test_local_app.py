"""Standalone HTTP contract, upload, and cooperative job lifecycle tests."""

import asyncio
import base64
from contextlib import closing
import json
import os
import sqlite3
from io import BytesIO
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

import local_app as local
from tests.helpers import enter_context
from goated_prompter import json_store, uploaded_images


class LocalEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.calls = []
        self.configs = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        enter_context(self, patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp.name) / "directors")}))
        self.settings_path = Path(self.temp.name) / "data" / "settings.json"
        owner = self

        class Service:
            def __init__(self, config, checkpoint):
                self.checkpoint = checkpoint
                owner.configs.append(config)

            def generate(self, request):
                self.checkpoint()
                owner.calls.append((request, False))
                owner.entered.set()
                if not owner.release.wait(5):
                    raise ValueError("Test model timed out")
                self.checkpoint()
                return SimpleNamespace(prompt="fresh prompt", backend_name="test", director_profile="",
                                       prompt_model=request.selected_prompt_model, director_preset=request.director_preset)

            def generate_text_only(self, request):
                result = self.generate(request)
                owner.calls[-1] = (request, True)
                return result

        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, service_factory=Service,
                                    settings_path=self.settings_path)
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()

    async def start(self, **payload):
        response = await self.client.post("/api/generate", json={"settings": {"idea": "portrait"}, **payload})
        self.assertEqual(response.status, 202, await response.text())
        return await response.json()

    async def wait_status(self, job_id, status):
        for _ in range(200):
            response = await self.client.get(f"/api/jobs/{job_id}")
            job = await response.json()
            if job["status"] == status:
                return job
            await asyncio.sleep(.01)
        self.fail(f"Expected {status}: {job}")

    async def test_bootstrap_and_models(self):
        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(set(payload), {"inputs", "presets", "models", "backend", "migration_notices", "active_job", "settings",
                                    "reference_attributes", "reference_sources", "max_reference_images"})
        self.assertEqual(payload["reference_attributes"], [{"key": key, "label": label} for key, label in local.REFERENCE_ATTRIBUTES])
        self.assertEqual(payload["reference_sources"], ["Off", "Image 1", "Image 2", "Image 3", "Image 4", "Blend"])
        self.assertEqual(payload["max_reference_images"], 4)
        self.assertEqual(payload["settings"]["builder"], {"director_preset": "general_director"})
        self.assertEqual(self.app._client_max_size, 112 * 1024 * 1024)
        self.assertEqual(payload["settings"]["models_directory"], payload["models"]["root"])
        self.assertIsNone(payload["active_job"])
        self.assertIn("mode", payload["inputs"])
        self.assertNotIn("system_prompt_override", payload["inputs"])
        self.assertEqual(len([key for key in payload["inputs"] if key.startswith("reference_")]), 11)
        self.assertNotIn("lock_generated_prompt", payload["inputs"])
        self.assertEqual(set(payload["presets"]), {"ok", "default", "presets", "mode_directors", "warnings", "storage"})
        self.assertEqual(set(payload["presets"]["mode_directors"]), set(payload["inputs"]["mode"][0]))
        self.assertEqual(payload["presets"]["mode_directors"]["Photography"], "photography_director")
        self.assertEqual(set(payload["models"]), {"ok", "backend", "root", "profiles", "assignments", "warnings"})
        with patch.object(local, "discover_director_profiles", wraps=local.discover_director_profiles) as discover:
            response = await self.client.get("/api/models?refresh=true")
            self.assertEqual(response.status, 200)
            self.assertTrue(discover.call_args.args[1])

    async def test_job_live_llm_trace_keeps_exact_exposed_text(self):
        job = local.Job()
        job.record_llm_activity({
            "type": "request", "model": "test-model",
            "messages": [{"role": "system", "content": "Read this exactly."},
                         {"role": "user", "content": "Write this exactly."}],
            "parameters": {"temperature": 0.3},
            "timeout_seconds": 45,
        })
        job.record_llm_activity({"type": "reasoning_delta", "text": "exposed reason"})
        job.record_llm_activity({"type": "response_delta", "text": "partial "})
        job.record_llm_activity({"type": "response_delta", "text": "answer"})
        job.record_llm_activity({"type": "response_complete", "finish_reason": "stop"})
        trace = job.snapshot()["llm_trace"]
        self.assertEqual(trace["messages"][0]["content"], "Read this exactly.")
        self.assertEqual(trace["reasoning"], "exposed reason")
        self.assertEqual(trace["output"], "partial answer")
        self.assertEqual(trace["timeout_seconds"], 45)
        self.assertEqual(trace["status"], "complete")

    async def test_job_snapshots_isolate_mutable_result_and_trace(self):
        job = local.Job()
        messages = [{"role": "user", "content": "original"}]
        job.record_llm_activity({"type": "request", "messages": messages})
        messages[0]["content"] = "changed by caller"
        job.deliver({"prompts": ["original result"]})
        snapshot = job.snapshot()
        snapshot["result"]["prompts"].append("changed by reader")
        snapshot["llm_trace"]["messages"][0]["content"] = "changed by reader"
        self.assertEqual(job.snapshot()["result"], {"prompts": ["original result"]})
        self.assertEqual(job.snapshot()["llm_trace"]["messages"],
                         [{"role": "user", "content": "original"}])

    async def test_job_events_are_bounded_and_release_ignores_late_activity(self):
        job = local.Job()
        for index in range(250):
            job.record_event(f"Event {index}")
        self.assertEqual(len(job.snapshot()["events"]), 200)
        self.assertEqual(job.snapshot()["events"][0]["message"], "Event 50")
        job.clear_private_data()
        revision = job.revision
        job.record_llm_activity({"type": "request", "messages": [{"content": "late private text"}]})
        self.assertEqual(job.revision, revision)
        self.assertIsNone(job.snapshot()["llm_trace"])
        self.assertEqual(job.snapshot()["events"], [])

    async def test_http_errors_keep_security_headers_and_no_store(self):
        for url in ("/api/settings", "/api/jobs/missing", "/api/no-such-route"):
            response = await self.client.get(url)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        for body in ("not json", "[]"):
            response = await self.client.post("/api/generate", data=body,
                                              headers={"Content-Type": "application/json"})
            self.assertEqual(response.status, 400)
            self.assertFalse((await response.json())["ok"])

    async def test_director_updates_reset_and_generation_authority(self):
        from goated_prompter import presets as library
        source = Path(library.__file__).read_bytes()
        created = await self.client.post("/api/presets", json={"name": "My Director", "instructions": "Original"})
        original = await created.json()
        self.assertEqual(original["director"]["recommended_mode"], "Custom")
        updated = await self.client.put("/api/presets", json={"id": original["director"]["id"], "name": "Renamed", "instructions": "New"})
        result = await updated.json()
        self.assertEqual(result["file"], original["file"])
        self.assertEqual(result["director"]["id"], original["director"]["id"])
        self.assertEqual(result["director"]["recommended_mode"], "Custom")
        response = await self.client.put("/api/presets", json={"id": "photography_director", "name": "Photography Director", "instructions": "Saved authority"})
        builtin = (await response.json())["director"]
        self.assertTrue(builtin["modified"])
        self.assertTrue(builtin["protected"])
        self.assertEqual(builtin["recommended_mode"], "Photography")
        self.assertEqual(library.get_director_preset("Photography Director").instructions, "Saved authority")
        self.assertEqual(Path(library.__file__).read_bytes(), source)
        for text_only in (False, True):
            for selected in ("photography_director", "reverse_engineer", result["director"]["id"]):
                job = await self.start(settings={"idea": "test", "director_preset": selected, "mode": "Video", "system_prompt_override": "Ignored"}, text_only=text_only)
                await self.wait_status(job["id"], "succeeded")
                request, actual_text = self.calls[-1]
                self.assertEqual(actual_text, text_only)
                self.assertEqual(request.mode, "Video")
                self.assertEqual(request.system_prompt_override, "")
        response = await self.client.post("/api/generate", json={"settings": {"director_preset": "user:missing"}})
        self.assertEqual(response.status, 400)
        response = await self.client.delete("/api/presets", json={"id": "photography_director"})
        self.assertEqual(response.status, 400)
        response = await self.client.post("/api/presets/reset", json={"id": "photography_director"})
        self.assertFalse((await response.json())["director"]["modified"])
        self.assertEqual(Path(library.__file__).read_bytes(), source)

    async def test_all_director_mutations_reject_paused_jobs(self):
        job = local.Job()
        job.status = "paused"
        self.app[local.STATE].jobs[job.id] = job
        for method, path in (("post", "/api/presets"), ("put", "/api/presets"), ("delete", "/api/presets"), ("post", "/api/presets/reset")):
            response = await getattr(self.client, method)(path, json={"id": "general_director", "name": "Test", "instructions": "Test"})
            self.assertEqual(response.status, 409)

    async def test_legacy_builder_recovery_retry_and_canonical_runtime_save(self):
        legacy = {"builder": {"mode": "Video", "director_preset": "Photography Director", "system_prompt_override": "Legacy draft", "generated_prompt": " exact output ", "lock_generated_prompt": True}}
        local.atomic_json(self.settings_path, legacy)
        with patch.object(local, "atomic_json", side_effect=PermissionError("read only")):
            with self.assertRaisesRegex(ValueError, "original settings remain intact"):
                local.LocalState(lambda: {}, None, self.settings_path)
        self.assertEqual(json.loads(self.settings_path.read_text()), legacy)
        state = local.LocalState(lambda: {}, None, self.settings_path)
        builder = state.settings()["builder"]
        self.assertEqual(builder["mode"], "Video")
        self.assertNotIn("system_prompt_override", builder)
        self.assertNotIn("lock_generated_prompt", builder)
        self.assertEqual(builder["generated_prompt"], " exact output ")
        recovered = local.get_director_preset(builder["director_preset"], strict=True)
        self.assertEqual(recovered.instructions, "Legacy draft")
        self.assertEqual(recovered.recommended_mode, "Video")
        self.assertTrue(state.migration_notices)
        again = local.LocalState(lambda: {}, None, self.settings_path)
        self.assertEqual(again.settings()["builder"], builder)
        self.assertEqual(len(list(local.resolve_user_director_directory().glob("*.json"))), 1)
        with self.assertRaisesRegex(ValueError, "Invalid builder mode"):
            state.save_settings({"builder": {"director_preset": "Photography Director", "mode": "invalid stale", "system_prompt_override": "stale"}})

    async def test_legacy_missing_selection_uses_mode_and_notifies(self):
        local.atomic_json(self.settings_path, {"builder": {"director_preset": "user:deleted", "mode": "Video"}})
        state = local.LocalState(lambda: {}, None, self.settings_path)
        self.assertEqual(state.settings()["builder"], {"director_preset": "video_director", "mode": "Video"})
        self.assertTrue(state.migration_notices)

    async def test_inflight_pause_conflict_resume_and_delivery(self):
        self.release.clear()
        job = await self.start()
        self.assertEqual(job["revision"], 0)
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 2))
        response = await self.client.get("/api/bootstrap")
        active = (await response.json())["active_job"]
        self.assertEqual(active["id"], job["id"])
        self.assertIn("Builder model workflow", active["progress"])
        response = await self.client.post(f"/api/jobs/{job['id']}/pause")
        requested = await response.json()
        self.assertEqual(requested["status"], "pause_requested")
        self.assertEqual(requested["revision"], 2)
        self.assertIn("safe checkpoint", requested["status_reason"])
        self.assertEqual(requested["events"][-1]["type"], "pause")
        response = await self.client.post("/api/generate", json={})
        self.assertEqual(response.status, 409)
        conflict = await response.json()
        self.assertEqual(set(conflict), {"ok", "error", "active_job"})
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["active_job"], requested)
        self.release.set()
        paused = await self.wait_status(job["id"], "paused")
        self.assertIsNone(paused["result"])
        self.assertEqual(paused["revision"], 3)
        self.assertIn("safe checkpoint", paused["status_reason"])
        response = await self.client.get("/api/bootstrap")
        self.assertEqual((await response.json())["active_job"], paused)
        response = await self.client.post(f"/api/jobs/{job['id']}/pause")
        self.assertEqual((await response.json())["revision"], 4)
        response = await self.client.post(f"/api/jobs/{job['id']}/resume")
        resumed = await response.json()
        self.assertEqual(resumed["revision"], 5)
        self.assertEqual(resumed["status"], "running")
        self.assertIn("resumed", resumed["status_reason"])
        completed = await self.wait_status(job["id"], "succeeded")
        self.assertEqual(completed["revision"], 6)
        self.assertEqual(completed["result"]["prompt"], "fresh prompt")
        response = await self.client.get("/api/bootstrap")
        self.assertIsNone((await response.json())["active_job"])
        response = await self.client.post(f"/api/jobs/{job['id']}/pause")
        self.assertEqual(response.status, 409)
        response = await self.client.get(f"/api/jobs/{job['id']}")
        self.assertEqual(await response.json(), completed)

    async def test_end_generation_cancels_without_delivering_and_releases_admission(self):
        self.release.clear()
        job = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 2))
        response = await self.client.post(f"/api/jobs/{job['id']}/cancel")
        ending = await response.json()
        self.assertEqual(ending["status"], "cancelling")
        self.assertEqual(ending["revision"], 2)
        response = await self.client.post("/api/generate", json={})
        self.assertEqual(response.status, 409)
        self.release.set()
        ended = await self.wait_status(job["id"], "cancelled")
        self.assertIsNone(ended["result"])
        self.assertEqual(ended["revision"], 3)
        self.assertIsNone((await (await self.client.get("/api/bootstrap")).json())["active_job"])
        next_job = await self.start()
        await self.wait_status(next_job["id"], "succeeded")

    async def test_settings_defaults_are_read_only_and_do_not_override_config(self):
        config = {"backend": "mock", "local_llama_cpp": {"models_dir": self.temp.name, "keep_model_loaded": True}}
        state = self.app[local.STATE]
        state.config_loader = lambda: config
        response = await self.client.get("/api/settings")
        self.assertEqual(await response.json(), {"models_directory": str(Path(self.temp.name) / "LLM"),
                                                 "keep_model_loaded": True, "selected_profile": "", "builder": {"director_preset": "general_director"}})
        self.assertEqual(state.config(), config)
        self.assertIsNot(state.config()["local_llama_cpp"], config["local_llama_cpp"])
        self.assertFalse(self.settings_path.parent.exists())
        job = await self.start(settings={"director_keep_model_loaded": False})
        await self.wait_status(job["id"], "succeeded")
        self.assertFalse(self.calls[-1][0].director_keep_model_loaded)

    async def test_settings_persist_discover_exact_root_and_resolve_custom(self):
        root = Path(self.temp.name) / "arbitrary models"
        nested = root / "nested" / "engine"
        nested.mkdir(parents=True)
        for folder in (root, nested):
            (folder / "model.gguf").touch()
            (folder / "mmproj.gguf").touch()
        expected = {"models_directory": str(root), "keep_model_loaded": True, "selected_profile": "nested/engine", "builder": {"director_preset": "general_director"}}
        response = await self.client.put("/api/settings", json=expected)
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(await response.json(), expected)
        app = local.create_app(settings_path=self.settings_path, config_loader=lambda: {})
        self.assertEqual(app[local.STATE].settings(), expected)
        response = await self.client.get("/api/bootstrap")
        bootstrap = await response.json()
        self.assertEqual(bootstrap["settings"], expected)
        self.assertEqual(bootstrap["models"]["root"], str(root))
        self.assertEqual({p["id"] for p in bootstrap["models"]["profiles"]}, {".", "nested/engine"})
        request = local.GoatedPrompterRequest.from_mapping({"prompt_model": "Custom", "director_profile": "nested/engine"})
        effective, profile = local.resolve_director_config(app[local.STATE].config(), request)
        self.assertEqual(profile.profile_id, "nested/engine")
        self.assertEqual(effective["local_llama_cpp"]["model_path"], str(nested / "model.gguf"))
        # With no standalone override, node discovery still appends LLM.
        self.assertEqual(local.discover_director_profiles({"models_dir": str(root)}).llm_root, root / "LLM")
        for saved in (True, False):
            response = await self.client.put("/api/settings", json={"keep_model_loaded": saved})
            self.assertEqual((await response.json())["selected_profile"], "nested/engine")
            job = await self.start(settings={"prompt_model": "Custom", "director_profile": "nested/engine",
                                             "director_keep_model_loaded": not saved})
            await self.wait_status(job["id"], "succeeded")
            self.assertEqual(self.calls[-1][0].director_keep_model_loaded, saved)
            self.assertEqual(self.configs[-1]["local_llama_cpp"]["keep_model_loaded"], saved)
            effective, _ = local.resolve_director_config({**self.configs[-1], "backend": "auto"}, self.calls[-1][0])
            self.assertEqual(effective["local_llama_cpp"]["keep_model_loaded"], saved)

    async def test_settings_validation_security_and_active_job_conflict(self):
        file = Path(self.temp.name) / "not-directory"
        file.touch()
        for payload in ([], {"models_directory": ""}, {"models_directory": 12},
                        {"models_directory": str(file)}, {"models_directory": str(file / "missing")},
                        {"models_directory": "https://example.com/models"}, {"models_directory": "//server/share"},
                        {"models_directory": "\\\\server\\share"}, {"keep_model_loaded": "false"},
                        {"keep_model_loaded": 1}, {"selected_profile": None}, {"unexpected": True}):
            response = await self.client.put("/api/settings", json=payload)
            self.assertEqual(response.status, 400, await response.text())
        for headers in ({"Host": "evil.example:8190"}, {"Origin": "https://evil.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            response = await self.client.put("/api/settings", json={"keep_model_loaded": True}, headers=headers)
            self.assertEqual(response.status, 403)
        self.assertFalse(self.settings_path.exists())
        self.release.clear()
        job = await self.start()
        response = await self.client.put("/api/settings", json={"keep_model_loaded": True})
        self.assertEqual(response.status, 409)
        await self.client.post(f"/api/jobs/{job['id']}/pause")
        self.release.set()
        await self.wait_status(job["id"], "paused")
        response = await self.client.put("/api/settings", json={"keep_model_loaded": True})
        self.assertEqual(response.status, 409)
        self.assertFalse(self.settings_path.exists())
        await self.client.post(f"/api/jobs/{job['id']}/resume")
        await self.wait_status(job["id"], "succeeded")

    async def test_builder_snapshot_persistence_validation_and_active_job(self):
        schema = local.GoatedPrompter.INPUT_TYPES()["required"]
        builder = {key: schema[key][0][0] for key in ("mode", "target_model", "creativity", "prompt_length")}
        builder.update(idea="  exact\n", custom_instructions="instructions", system_prompt_override="system",
                       generated_prompt="output", lock_generated_prompt=True, director_preset="general_director")
        builder.update({f"reference_{key}_source": local.REFERENCE_SOURCES[i % 6]
                        for i, (key, _) in enumerate(local.REFERENCE_ATTRIBUTES)})
        response = await self.client.put("/api/settings", json={"keep_model_loaded": True,
                                          "selected_profile": "custom", "builder": builder})
        self.assertEqual(response.status, 200, await response.text())
        builder.pop("system_prompt_override")
        builder.pop("lock_generated_prompt")
        self.assertEqual((await response.json())["builder"], builder)
        restarted = local.create_app(settings_path=self.settings_path, config_loader=lambda: {})
        self.assertEqual(restarted[local.STATE].settings()["builder"], builder)
        original = self.settings_path.read_bytes()
        invalid = [None, [], {"unknown": True}, {"idea": None}, {"idea": "x" * 100001}]
        invalid += [{key: "invalid"} for key in ("director_preset", "mode", "target_model", "creativity", "prompt_length")]
        invalid += [{"reference_face_source": value} for value in ("Auto", "Image 5", "image 1", "", None)]
        invalid += [{key: "data:image/png;base64,AAAA"} for key in
                    ("images", "image", "image_2", "image_3", "image_4", "model_path", "prompt_model",
                     "director_profile", "director_keep_model_loaded", "linked_references", "reference_unknown_source")]
        for value in invalid:
            response = await self.client.put("/api/settings", json={"builder": value})
            self.assertEqual(response.status, 400, await response.text())
            self.assertEqual(self.settings_path.read_bytes(), original)
        job = local.Job()
        self.app[local.STATE].jobs[job.id] = job
        response = await self.client.put("/api/settings", json={"builder": {"prompt_length": "Maximum"}})
        self.assertEqual(response.status, 200, await response.text())
        saved = await response.json()
        self.assertEqual(saved["builder"], {"prompt_length": "Maximum Detail", "director_preset": "general_director"})
        self.assertTrue(saved["keep_model_loaded"])
        self.assertEqual(saved["selected_profile"], "custom")
        response = await self.client.put("/api/settings", json={"builder": {}, "keep_model_loaded": False})
        self.assertEqual(response.status, 409)
        job.deliver({})
        response = await self.client.put("/api/settings", json={"keep_model_loaded": False})
        self.assertEqual((await response.json())["builder"], {"prompt_length": "Maximum Detail", "director_preset": "general_director"})
        response = await self.client.put("/api/settings", json={"builder": {}})
        self.assertEqual((await response.json())["builder"], {"director_preset": "general_director"})
        self.assertEqual(json.loads(self.settings_path.read_text()),
                         {"keep_model_loaded": False, "selected_profile": "custom", "builder": {"director_preset": "general_director"}})

    async def test_prompt_save_import_delete_restart_and_conflicts(self):
        record = {"id": "browser-1", "title": "Portrait", "prompt": "  exact\ntext  ",
                  "createdAt": "2026-09-09T12:00:00.000Z", "target": "Flux"}
        other = {**record, "id": "browser-2"}
        path = self.settings_path.parent / "prompts.json"
        response = await self.client.get("/api/prompts")
        self.assertEqual(await response.json(), {"prompts": []})
        self.assertFalse(path.exists())
        for _ in range(2):
            response = await self.client.post("/api/prompts", json=record)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {"prompts": [record]})
        original = path.read_bytes()
        for url, payload in (("/api/prompts", {**record, "title": "Changed"}),
                             ("/api/prompts/import", {"prompts": [other, {**record, "prompt": "Changed"}]}),
                             ("/api/prompts/import", {"prompts": [other, {**other, "title": "Changed"}]})):
            response = await self.client.post(url, json=payload)
            self.assertEqual(response.status, 409, await response.text())
            self.assertEqual(path.read_bytes(), original)
        for _ in range(2):
            response = await self.client.post("/api/prompts/import", json={"prompts": [record, other, other]})
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {"prompts": [record, other]})
        restarted = local.create_app(settings_path=self.settings_path, config_loader=lambda: {})
        async with TestClient(TestServer(restarted), headers={"Host": "localhost:8190"}) as client:
            response = await client.get("/api/prompts")
            self.assertEqual(await response.json(), {"prompts": [record, other]})
            for _ in range(2):
                response = await client.delete("/api/prompts/browser-1")
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.json(), {"prompts": [other]})
        self.assertEqual(json.loads(path.read_text()), {"prompts": [other]})

    async def test_prompt_validation_security_corruption_and_atomic_failure(self):
        record = {"id": "one", "title": "Title", "prompt": "Prompt", "createdAt": "2026-09-09"}
        for payload in ({}, [], {**record, "title": "x" * 81}, {**record, "target": None},
                        {**record, "createdAt": 123}, {**record, "id": "../bad"},
                        {**record, "prompt": " "}, {**record, "extra": True}):
            response = await self.client.post("/api/prompts", json=payload)
            self.assertEqual(response.status, 400, await response.text())
        for payload in ({}, {"prompts": {}}, {"prompts": [record, {}]}):
            response = await self.client.post("/api/prompts/import", json=payload)
            self.assertEqual(response.status, 400)
        for method, url, payload in (("get", "/api/prompts", None), ("post", "/api/prompts", record),
                                     ("post", "/api/prompts/import", {"prompts": [record]}),
                                     ("delete", "/api/prompts/one", None)):
            for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                            {"Sec-Fetch-Site": "cross-site"}):
                response = await self.client.request(method, url, json=payload, headers=headers)
                self.assertEqual(response.status, 403)
        await self.client.post("/api/prompts", json=record)
        path = self.settings_path.parent / "prompts.json"
        original = path.read_bytes()
        with patch.object(json_store.os, "replace", side_effect=OSError("disk failure")):
            response = await self.client.delete("/api/prompts/one")
            self.assertEqual(response.status, 500)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])
        response = await self.client.get("/api/prompts")
        self.assertEqual(await response.json(), {"prompts": [record]})
        path.write_text('{"prompts": [')
        for method, url in (("get", "/api/prompts"), ("post", "/api/prompts"), ("delete", "/api/prompts/one")):
            response = await self.client.request(method, url, json=record)
            self.assertEqual(response.status, 400)
            self.assertIn("Restore or repair", (await response.json())["error"])
        self.assertEqual(path.read_text(), '{"prompts": [')
        with self.assertRaisesRegex(ValueError, "Restore or repair"):
            local.create_app(settings_path=self.settings_path)

    async def test_concurrent_prompt_writes_preserve_all_records(self):
        records = [{"id": str(i), "title": "Title", "prompt": "Prompt", "createdAt": "today"} for i in range(20)]
        responses = await asyncio.gather(*(self.client.post("/api/prompts", json=record) for record in records))
        self.assertTrue(all(response.status == 200 for response in responses))
        response = await self.client.get("/api/prompts")
        self.assertEqual({item["id"] for item in (await response.json())["prompts"]}, {item["id"] for item in records})

    async def test_settings_atomic_failure_and_corruption_do_not_overwrite(self):
        await self.client.put("/api/settings", json={"keep_model_loaded": True})
        original = self.settings_path.read_bytes()
        self.assertEqual(json.loads(original), {"keep_model_loaded": True})
        with patch.object(json_store.os, "replace", side_effect=OSError("disk failure")):
            response = await self.client.put("/api/settings", json={"keep_model_loaded": False})
            self.assertEqual(response.status, 500)
        self.assertEqual(self.settings_path.read_bytes(), original)
        self.assertTrue(self.app[local.STATE].saved_settings["keep_model_loaded"])
        self.assertEqual(list(self.settings_path.parent.glob("*.tmp")), [])
        self.settings_path.write_text('{"keep_model_loaded": "false"}')
        response = await self.client.put("/api/settings", json={"keep_model_loaded": False})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.settings_path.read_text(), '{"keep_model_loaded": "false"}')

    async def test_existing_output_and_obsolete_lock_do_not_bypass_generation(self):
        for extra in ({}, {"lock_generated_prompt": True}):
            job = await self.start(settings={"idea": "portrait", "generated_prompt": "not a cache", **extra})
            self.assertEqual((await self.wait_status(job["id"], "succeeded"))["result"]["prompt"], "fresh prompt")
        self.assertEqual(len(self.calls), 2)

    async def test_delivery_gate_without_service_checkpoint(self):
        entered = threading.Event()
        release = threading.Event()
        original = local.Job.deliver

        def delayed_delivery(job, result):
            entered.set()
            release.wait(3)
            original(job, result)

        with patch.object(local.Job, "deliver", delayed_delivery):
            job = await self.start()
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                await self.client.post(f"/api/jobs/{job['id']}/pause")
            finally:
                release.set()
            paused = await self.wait_status(job["id"], "paused")
            self.assertIsNone(paused["result"])
            await self.client.post(f"/api/jobs/{job['id']}/resume")
            await self.wait_status(job["id"], "succeeded")

    async def test_generation_keeps_payload_bounds_and_security(self):
        for text_only in (False, True):
            payload = {"settings": {"idea": "portrait"}, "text_only": text_only}
            for images in ([None] * 5, "not an array"):
                response = await self.client.post("/api/generate", json={**payload, "images": images})
                self.assertEqual(response.status, 400)
            response = await self.client.post("/api/generate", json=payload, headers={"Origin": "https://evil.example"})
            self.assertEqual(response.status, 403)
            with patch.object(self.app, "_client_max_size", 64):
                response = await self.client.post("/api/generate", json={**payload, "images": ["x" * 1000]})
                self.assertEqual(response.status, 413)

    async def test_images_slots_mapping(self):
        buffer = BytesIO()
        Image.new("RGBA", (1600, 800)).save(buffer, "PNG")
        data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        job = await self.start(settings={"idea": "portrait", "reference_face_source": "Image 2"}, images=[None, data])
        await self.wait_status(job["id"], "succeeded")
        request, text_only = self.calls[0]
        self.assertIsNone(request.image)
        self.assertEqual((request.image_2.width, request.image_2.height), (1344, 672))
        self.assertEqual(request.reference_map["face"], "Image 2")
        self.assertFalse(text_only)
        self.assertIsNone(request.image_3)
        self.assertIsNone(request.image_4)
        self.assertFalse(request.linked_references)
        for slots in ([data] * 4, [None, None, None, data]):
            job = await self.start(settings={"idea": "portrait", "linked_references": True,
                                             "reference_face_source": "Image 4"}, images=slots)
            await self.wait_status(job["id"], "succeeded")
            request = self.calls[-1][0]
            self.assertTrue(request.linked_references)
            self.assertEqual(request.reference_map["face"], "Image 4")
            for value, encoded in zip(slots, (request.image, request.image_2, request.image_3, request.image_4)):
                self.assertEqual(encoded is None, value is None)
        self.assertFalse(self.settings_path.exists())

    async def test_text_only_skips_image_decoding(self):
        with patch.object(local, "decode_image", side_effect=AssertionError("Must not decode images")):
            job = await self.start(images=["invalid image", "data:image/png;base64,!!!!", "bad", "bad"], text_only=True)
            await self.wait_status(job["id"], "succeeded")
        request, text_only = self.calls[0]
        self.assertIsNone(request.image)
        self.assertIsNone(request.image_2)
        self.assertIsNone(request.image_3)
        self.assertIsNone(request.image_4)
        self.assertTrue(text_only)

    async def test_invalid_inputs_and_security(self):
        for payload in ([], {"images": [None] * 5}, {"images": ["bad"]}, {"settings": []},
                        {"text_only": "false"},
                        {"settings": {"director_llama_server": "\\\\server\\share\\run.exe"}}):
            response = await self.client.post("/api/generate", json=payload)
            self.assertEqual(response.status, 400, await response.text())
        for headers in ({"Host": "evil.example:8190"}, {"Origin": "https://evil.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            response = await self.client.get("/api/bootstrap", headers=headers)
            self.assertEqual(response.status, 403)
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = await self.client.get("/api/bootstrap", headers={"Origin": origin})
            self.assertEqual(response.status, 200)
        response = await self.client.get("/api/jobs/missing")
        self.assertEqual(response.status, 404)
        response = await self.client.get("/api/no-such-route")
        self.assertEqual(response.status, 404)

    async def test_failure_and_bounded_history(self):
        with patch.object(local, "COMPLETED_LIMIT", 2):
            ids = []
            for _ in range(3):
                job = await self.start()
                ids.append(job["id"])
                await self.wait_status(job["id"], "succeeded")
            response = await self.client.get(f"/api/jobs/{ids[0]}")
            self.assertEqual(response.status, 404)
        with patch.object(local, "resolve_director_config", side_effect=ValueError("Choose a valid model.")):
            job = await self.start()
            failed = await self.wait_status(job["id"], "failed")
            self.assertEqual(failed["error"], "Choose a valid model.")
            self.assertEqual(failed["revision"], job["revision"] + 1)

    async def test_shutdown_releases_paused_job(self):
        self.release.clear()
        job = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 2))
        await self.client.post(f"/api/jobs/{job['id']}/pause")
        self.release.set()
        await self.wait_status(job["id"], "paused")
        retained = self.app[local.STATE].jobs[job["id"]]
        await asyncio.wait_for(self.client.close(), 3)
        self.assertEqual(retained.status, "interrupted")
        self.assertEqual(self.app[local.STATE].jobs, {})
        self.assertIsNone(retained.result)
        self.assertIsNone(retained.llm_trace)
        self.assertEqual(retained.events, [])

    async def test_shutdown_is_bounded_when_provider_and_interrupt_do_not_cooperate(self):
        self.release.clear()
        accepted = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 2))
        retained = self.app[local.STATE].jobs[accepted["id"]]
        retained.set_interrupt(lambda: self.release.wait(30))
        try:
            await asyncio.wait_for(self.client.close(), 4.5)
            self.assertEqual(retained.status, "interrupted")
            self.assertTrue(retained.released)
            self.assertIsNone(retained.result)
        finally:
            self.release.set()

    async def test_cancel_response_is_bounded_when_transport_does_not_cooperate(self):
        self.release.clear()
        accepted = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 2))
        retained = self.app[local.STATE].jobs[accepted["id"]]
        retained.set_interrupt(lambda: self.release.wait(30))
        try:
            response = await asyncio.wait_for(self.client.post(f"/api/jobs/{accepted['id']}/cancel"), 3)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["status"], "cancelling")
            self.assertTrue(retained.cancel_requested)
        finally:
            self.release.set()
        await self.wait_status(accepted["id"], "cancelled")

    async def test_checkpoint_cleanup_is_scoped_memory_only_and_preserves_saved_content(self):
        state = self.app[local.STATE]
        completed = local.Job()
        completed.kind = "dataset"
        completed.deliver({"prompts": ["private checkpoint"]})
        completed.record_llm_activity({"type": "request", "messages": [{"content": "private request"}]})
        active = local.Job()
        active.kind = "dataset_scenes"
        other = local.Job()
        other.kind = "minimax"
        other.deliver({"prompt": "other workflow"})
        for job in (completed, active, other):
            state.jobs[job.id] = job
        before = {path: path.read_bytes() for path in Path(self.temp.name).rglob("*.json")}
        response = await self.client.delete("/api/jobs?kind=dataset")
        self.assertEqual(await response.json(), {"ok": True, "released": [completed.id]})
        self.assertIsNone(completed.result)
        self.assertIsNone(completed.llm_trace)
        self.assertEqual(completed.events, [])
        self.assertEqual((await self.client.get(f"/api/jobs/{completed.id}")).status, 404)
        self.assertIn(active.id, state.jobs)
        self.assertIn(other.id, state.jobs)
        self.assertEqual(before, {path: path.read_bytes() for path in Path(self.temp.name).rglob("*.json")})
        self.assertEqual((await self.client.delete("/api/jobs?kind=unknown")).status, 400)
        self.assertEqual((await self.client.delete("/api/jobs")).status, 400)
        self.assertEqual((await self.client.delete("/api/jobs?kind=dataset", headers={"Origin": "https://evil.example"})).status, 403)
        active.deliver({"scene_plan": []})

    async def test_recent_idea_reset_is_private_scoped_and_preserves_drafts(self):
        from goated_prompter.dataset import default_dataset_draft
        state = self.app[local.STATE]
        data = {**default_dataset_draft(), "subject": "A performer at a rehearsal"}
        other = {**data, "subject": "A different concept"}
        state.idea_history.remember(data, [{"idea": "Private recent activity"}])
        state.idea_history.remember(other, [{"idea": "Another private activity"}])
        before = {path: path.read_bytes() for path in Path(self.temp.name).rglob("*.json")}
        response = await self.client.post("/api/workspace/dataset/novelty/reset", json={"input": data})
        self.assertEqual(await response.json(), {"ok": True})
        self.assertEqual(state.idea_history.recent(data), [])
        self.assertEqual(state.idea_history.recent(other), ["Another private activity"])
        self.assertEqual(before, {path: path.read_bytes() for path in Path(self.temp.name).rglob("*.json")})
        response = await self.client.post("/api/workspace/dataset/novelty/reset", json={"input": data}, headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)
        active = local.Job()
        state.jobs[active.id] = active
        state.idea_history.remember(data, [{"idea": "An active run's recent idea"}])
        response = await self.client.post("/api/workspace/dataset/novelty/reset", json={"input": data})
        self.assertEqual(response.status, 409)
        self.assertEqual(state.idea_history.recent(data), ["An active run's recent idea"])
        active.deliver({"ok": True})

    async def test_local_prompt_regeneration_accepts_manual_scene_without_geometry(self):
        from goated_prompter.dataset import default_dataset_draft
        from goated_prompter.dataset_assignments import dataset_assignments
        from goated_prompter.scene_planner import scene_plan_signature
        data = {**default_dataset_draft(), "amount": 1, "subject": "A traveler", "trigger": "person_token"}
        data["scene_plan"] = [{"index": 1, "input": "", "idea": "Reading on a bench",
                               "scene": "She reads a book on a park bench.", "geometry": {},
                               "idea_status": "valid", "scene_status": "valid", "prompt_status": "not_generated"}]
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        response = await self.client.post("/api/workspace/dataset/scene", json={"input": data, "index": 1, "action": "regenerate_prompt"})
        self.assertEqual(response.status, 202, await response.text())
        finished = await self.wait_status((await response.json())["id"], "succeeded")
        self.assertEqual(finished["result"]["scene_plan"][0]["scene"], data["scene_plan"][0]["scene"])
        self.assertEqual(finished["result"]["scene_plan"][0]["geometry"], {})

    async def test_preset_crud_and_unload_shapes(self):
        director = SimpleNamespace(to_public_mapping=lambda: {"id": "user:test", "label": "Test"})
        for method, function, payload in (("post", "save_user_director", {"name": "Test", "instructions": "test"}),
                                          ("delete", "delete_user_director", {"id": "user:test"})):
            with patch.object(local, function, return_value=(director, Path("test.json"))):
                response = await getattr(self.client, method)("/api/presets", json=payload)
                self.assertEqual(await response.json(), {"ok": True, "director": director.to_public_mapping(), "file": "test.json"})
        response = await self.client.post("/api/unload")
        self.assertEqual(set(await response.json()), {"ok", "status", "message"})


class JsonStorageTests(unittest.TestCase):
    def test_settings_sqlite_migration_and_json_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            legacy = path.with_suffix(".sqlite3")
            expected = {"models_directory": folder, "keep_model_loaded": True, "selected_profile": "custom"}
            with closing(sqlite3.connect(legacy)) as db, db:
                db.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, payload TEXT)")
                db.execute("INSERT INTO settings VALUES (1, ?)", (json.dumps(expected),))
            original = legacy.read_bytes()
            state = local.create_app(settings_path=path)[local.STATE]
            self.assertEqual(state.saved_settings, expected)
            self.assertEqual(json.loads(path.read_text()), expected)
            self.assertEqual(legacy.read_bytes(), original)
            path.write_text('{"keep_model_loaded": false}')
            self.assertEqual(local.create_app(settings_path=path)[local.STATE].saved_settings, {"keep_model_loaded": False})
            path.write_text("not json")
            with self.assertRaisesRegex(ValueError, "Restore or repair"):
                local.create_app(settings_path=path)
            self.assertEqual(path.read_text(), "not json")
            self.assertEqual(legacy.read_bytes(), original)

    def test_invalid_migration_and_atomic_migration_failure(self):
        for payload in ('{"keep_model_loaded": "false"}', '[]', 'not json', '{"keep_model_loaded": true}'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "settings.json"
                legacy = path.with_suffix(".sqlite3")
                with closing(sqlite3.connect(legacy)) as db, db:
                    db.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, payload TEXT)")
                    db.execute("INSERT INTO settings VALUES (1, ?)", (payload,))
                original = legacy.read_bytes()
                with patch.object(json_store.os, "replace", side_effect=OSError("disk failure")):
                    with self.assertRaises((ValueError, OSError)):
                        local.create_app(settings_path=path)
                self.assertFalse(path.exists())
                self.assertEqual(legacy.read_bytes(), original)

    def test_explicit_prompt_path_load_validation_and_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "custom.json"
            settings = Path(folder) / "settings.json"
            record = {"id": "one", "title": "Title", "prompt": "Exact", "createdAt": "today"}
            for payload in ({"prompts": [record]}, {"prompts": [{}]}, [],
                            {"prompts": [record, {**record, "title": "Conflict"}]}):
                path.write_text(json.dumps(payload))
                if payload == {"prompts": [record]}:
                    self.assertEqual(local.create_app(settings_path=settings, prompts_path=path)[local.STATE].prompts_path, path)
                else:
                    with self.assertRaisesRegex(ValueError, "Restore or repair"):
                        local.create_app(settings_path=settings, prompts_path=path)
                self.assertEqual(json.loads(path.read_text()), payload)
            with patch.object(local, "MAX_PROMPTS", 1):
                with self.assertRaises(ValueError):
                    local.validate_prompts({"prompts": [record, {**record, "id": "two"}]})
            original = path.read_bytes()
            with patch.object(json_store, "MAX_STORE_BYTES", 2):
                with self.assertRaises(ValueError):
                    local.atomic_json(path, {"prompts": [record]})
            self.assertEqual(path.read_bytes(), original)


class UploadTests(unittest.TestCase):
    def test_declared_format_must_match_content_and_invalid_dimension_uses_default(self):
        buffer = BytesIO()
        Image.new("RGB", (1600, 800)).save(buffer, "PNG")
        raw = base64.b64encode(buffer.getvalue()).decode()
        with self.assertRaisesRegex(ValueError, "does not match"):
            local.decode_image("data:image/jpeg;base64," + raw)
        encoded = local.decode_image("data:image/png;base64," + raw, "invalid")
        self.assertEqual((encoded.width, encoded.height), (1344, 672))
        self.assertIsNone(local.decode_image(None))

    def test_formats_and_limits(self):
        for fmt, mime in (("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")):
            buffer = BytesIO()
            Image.new("RGB", (500, 300)).save(buffer, fmt)
            data = f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode()
            encoded = local.decode_image(data, 256)
            self.assertEqual((encoded.width, encoded.height, encoded.media_type), (256, 154, "image/png"))
            with patch.object(uploaded_images, "MAX_IMAGE_PIXELS", 100):
                with self.assertRaisesRegex(ValueError, "pixels"):
                    local.decode_image(data)
            with patch.object(uploaded_images, "MAX_IMAGE_BYTES", 1):
                with self.assertRaises(ValueError):
                    local.decode_image(data)
        with self.assertRaises(ValueError):
            local.decode_image("data:image/png;base64,!!!!")


class AssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_assets_and_traversal(self):
        # The test's own directory supplies an existing asset without creating build files.
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        app = local.create_app(dist=Path(__file__).parent, config_loader=lambda: {},
                               settings_path=Path(temp.name) / "settings.json")
        async with TestClient(TestServer(app), headers={"Host": "localhost:8190"}) as client:
            response = await client.get("/test_local_app.py")
            self.assertEqual(response.status, 200)
            response = await client.get("/%2e%2e%5clocal_app.py")
            self.assertEqual(response.status, 403)
            response = await client.get("/missing.js")
            self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
