"""Standalone local API and built Vite asset server. Run: python local_app.py."""

import argparse
import asyncio
from contextlib import closing
from collections import OrderedDict
import logging
import json
import hashlib
from pathlib import Path

from aiohttp import web

from goated_prompter.api import workflow_settings_routes
from goated_prompter.api.common import STATE
from goated_prompter.backends.base import GoatedPrompterError
from goated_prompter.backends.llama_cpp_process import get_process_manager, _resolve_server_executable
from goated_prompter.config import load_config
from goated_prompter.contracts import as_bool
from goated_prompter.director_profiles import discover_director_profiles, resolve_director_config
from goated_prompter.features.builder import routes as builder_routes
from goated_prompter.features.builder.input_schema import builder_input_schema
from goated_prompter.options.references import REFERENCE_SOURCES
from goated_prompter.features.builder.service import GoatedPrompterService
from goated_prompter.features.dataset import routes as dataset_routes
from goated_prompter.features.dataset.checkpoints import DatasetCheckpointStore
from goated_prompter.features.dataset.idea_history import RecentIdeaHistory
from goated_prompter.features.dataset.intent import DatasetIntentTickets
from goated_prompter.features.minimax import routes as minimax_routes
from goated_prompter.features.presets import routes as presets_routes
from goated_prompter.features.presets.routes import presets_payload
from goated_prompter.features.refine import routes as refine_routes
from goated_prompter.features.saved_prompts import routes as saved_prompts_routes
from goated_prompter.features.saved_prompts.store import validate_prompts
from goated_prompter.features.settings import routes as settings_routes
from goated_prompter.features.settings.routes import models_payload
from goated_prompter.features.settings.validation import validate_local_paths, validate_settings
from goated_prompter.job_lifecycle import DATASET_CHECKPOINT_KINDS, release_completed_checkpoints, daemon_work
from goated_prompter.json_store import atomic_json, read_store
from goated_prompter.local_jobs import Job, JobCancelled, TERMINAL
from goated_prompter.presets import (
    DEFAULT_DIRECTOR_PRESET, DirectorLibraryError, get_director_preset, recommended_director_for_mode,
    save_user_director,
)
from goated_prompter.options.references import REFERENCE_ATTRIBUTES
from goated_prompter.workflow_runners import execute_workflow
from goated_prompter.workflow_settings import WorkflowSettingsStore
from goated_prompter.workspace_store import WorkspaceStore, WorkspaceConflict

COMPLETED_LIMIT = 32


class LocalState:
    def __init__(self, config_loader, service_factory, settings_path, prompts_path=None):
        self.config_loader = config_loader
        self.service_factory = service_factory
        self.settings_path = Path(settings_path).expanduser().resolve()
        self.prompts_path = (Path(prompts_path).expanduser().resolve() if prompts_path is not None
                             else self.settings_path.parent / "prompts.json")
        if self.prompts_path == self.settings_path:
            raise ValueError("Settings and prompts require separate JSON paths.")
        self.saved_settings = read_store(self.settings_path, {}, validate_settings)
        legacy = self.settings_path.parent / "settings.sqlite3"
        if not self.settings_path.exists() and legacy.exists():
            self.migrate_settings(legacy)
        read_store(self.prompts_path, {"prompts": []}, validate_prompts)
        workspace_path = self.settings_path.parent / "workspace.json"
        if workspace_path in {self.settings_path, self.prompts_path}:
            raise ValueError("Workspace, settings and prompts require separate JSON paths.")
        self.workspace = WorkspaceStore(workspace_path, read_store, atomic_json)
        workflow_settings_path = self.settings_path.parent / "workflow_settings.json"
        if workflow_settings_path in {self.settings_path, self.prompts_path}:
            raise ValueError("Workflow settings require a separate JSON path.")
        self.workflow_settings = WorkflowSettingsStore(workflow_settings_path, read_store, atomic_json)
        checkpoint_path = self.settings_path.parent / "dataset_checkpoints.json"
        if checkpoint_path in {self.settings_path, self.prompts_path}:
            raise ValueError("Dataset checkpoints require a separate JSON path.")
        self.dataset_checkpoints = DatasetCheckpointStore(checkpoint_path, read_store, atomic_json)
        self.dataset_checkpoints.recover()
        self.workflow_settings.dataset_checkpoints = self.dataset_checkpoints
        self.jobs = OrderedDict()
        self.idea_history = RecentIdeaHistory()
        self.dataset_intents = DatasetIntentTickets()
        self.tasks = set()
        self.admission = asyncio.Lock()
        self.storage_lock = asyncio.Lock()
        self.migration_notices = []
        # Initialization precedes request admission, so no job or settings writer can race recovery.
        if "builder" in self.saved_settings:
            saved = dict(self.saved_settings)
            saved["builder"] = self.canonical_builder(saved["builder"], recover=True)
            if saved != self.saved_settings:
                try:
                    atomic_json(self.settings_path, saved)
                except OSError as exc:
                    raise ValueError("Cannot migrate builder settings. Make the settings directory writable and retry; original settings remain intact.") from exc
                self.saved_settings = saved

    def canonical_builder(self, builder, recover=False):
        builder = dict(builder)
        selected = builder.get("director_preset")
        try:
            director = get_director_preset(selected or (recommended_director_for_mode(builder.get("mode")) if recover else DEFAULT_DIRECTOR_PRESET), strict=True)
        except DirectorLibraryError:
            if not recover:
                raise
            director = get_director_preset(recommended_director_for_mode(builder.get("mode")))
            self.migration_notices.append(f"Saved Director '{selected}' is unavailable; selected {director.label}.")
        override = builder.pop("system_prompt_override", "")
        old_mode = builder.get("mode")
        if recover and override.strip():
            mode = old_mode or director.recommended_mode or "Custom"
            digest = hashlib.sha256(json.dumps([director.id, override.strip(), mode]).encode()).hexdigest()[:20]
            name = f"Recovered Director {digest}"
            try:
                recovered = get_director_preset(name, strict=True)
            except DirectorLibraryError:
                recovered, _ = save_user_director(name, override, mode)
            if recovered.instructions != override.strip() or recovered.recommended_mode != mode:
                raise ValueError("Recovered Director conflicts with legacy draft. Rename that Director and retry; original settings remain intact.")
            director = recovered
            self.migration_notices.append(f"Recovered legacy Director Behavior as '{director.label}' ({director.id}).")
        builder["director_preset"] = director.id
        return builder

    def migrate_settings(self, legacy):
        import sqlite3

        try:
            with closing(sqlite3.connect(legacy.as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute("SELECT payload FROM settings WHERE id = 1").fetchone()
            saved = validate_settings(json.loads(row[0]) if row else {})
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ValueError(f"Cannot migrate {legacy}: {exc} Restore or repair the original database; it has not been modified.") from exc
        atomic_json(self.settings_path, saved)
        self.saved_settings = saved

    def config(self):
        config = dict(self.config_loader())
        settings = dict(config.get("local_llama_cpp") or {})
        if "models_directory" in self.saved_settings:
            settings["models_dir"] = self.saved_settings["models_directory"]
            settings["discovery_root"] = self.saved_settings["models_directory"]
        if "keep_model_loaded" in self.saved_settings:
            settings["keep_model_loaded"] = self.saved_settings["keep_model_loaded"]
        validate_local_paths(settings)
        config["local_llama_cpp"] = settings
        return config

    def settings(self):
        local = self.config().get("local_llama_cpp", {})
        return {"models_directory": str(discover_director_profiles(local).llm_root),
                "keep_model_loaded": as_bool(local.get("keep_model_loaded", False)),
                "selected_profile": self.saved_settings.get("selected_profile", ""),
                "builder": self.saved_settings.get("builder", {"director_preset": "general_director"})}

    def save_settings(self, payload):
        if isinstance(payload, dict) and isinstance(payload.get("builder"), dict):
            payload = {**payload, "builder": {key: value for key, value in payload["builder"].items()
                                               if key != "system_prompt_override"}}
        payload = validate_settings(payload)
        if "builder" in payload:
            payload["builder"] = self.canonical_builder(payload["builder"])
        if "models_directory" in payload:
            value = payload["models_directory"]
            directory = Path(value.strip()).expanduser().resolve()
            if not directory.is_dir():
                raise ValueError("models_directory must be an existing directory.")
            payload["models_directory"] = str(directory)
        saved = {**read_store(self.settings_path, {}, validate_settings), **payload}
        if "builder" in saved:
            saved["builder"] = self.canonical_builder(saved["builder"])
        atomic_json(self.settings_path, saved)
        self.saved_settings = saved

    def active_job(self):
        for job in self.jobs.values():
            snapshot = job.snapshot()
            if snapshot["status"] not in TERMINAL:
                return snapshot
        return None

    def start_job(self, kind, request, config, text_only, workflow=None, *, job_factory=Job):
        """Called under admission; all routes share task registration/lifecycle."""
        job = job_factory()
        job.kind = kind
        if kind in DATASET_CHECKPOINT_KINDS:
            self.workflow_settings.begin_dataset(job, workflow["input"], workflow.get("workflow_revision"))
        self.jobs[job.id] = job
        task = asyncio.create_task(self.run(job, request, config, text_only, workflow))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job.snapshot()

    def execute(self, job, director_request, config, text_only, workflow=None):
        try:
            job.checkpoint()
            config = {**config, "_activity_callback": job.record_llm_activity,
                      "_register_interrupt": job.register_interrupt,
                      "_unregister_interrupt": job.unregister_interrupt}
            effective, _ = resolve_director_config(config, director_request)
            local_settings = effective.get("local_llama_cpp", {})
            validate_local_paths(local_settings)
            if effective.get("backend") == "local_llama_cpp":
                executable = _resolve_server_executable(local_settings.get("llama_server"), local_settings.get("runtime_root"))
                validate_local_paths({"llama_server": executable})
                # This app owns the active llama.cpp process, so ending its
                # job can interrupt the blocking inference request.
                job.set_interrupt(get_process_manager().interrupt_active)
            execute_workflow(self, job, director_request, config,
                             workflow if workflow is not None else {"operation": "builder", "text_only": text_only})
        except JobCancelled:
            with job.lock:
                if job.released:
                    return
                job.mark_cancelled()
        except Exception as exc:
            with job.lock:
                if job.released:
                    return
                cancelled = job.cancel_requested
                if cancelled:
                    job.mark_cancelled()
                elif job.stopping:
                    job.mark_failed("Server stopped. Completed Dataset checkpoints remain recoverable.", "interrupted")
                else:
                    job.mark_failed(str(exc) if isinstance(exc, (ValueError, GoatedPrompterError)) else (
                        "Generation failed unexpectedly. Check the server console and model configuration, then retry."),
                        getattr(exc, "completion_state", "provider_error"))
            if not cancelled:
                logging.exception("Local generation failed")
        finally:
            if not job.released and job.kind in DATASET_CHECKPOINT_KINDS:
                try:
                    self.workflow_settings.checkpoint_dataset(job)
                except (ValueError, OSError):
                    logging.exception("Could not persist final Dataset job status; prior checkpoints remain intact")

    async def run(self, job, *args):
        await daemon_work(self.execute, job, *args)
        completed = [key for key, record in self.jobs.items() if record.status in TERMINAL]
        for key in completed[:-COMPLETED_LIMIT]:
            self.jobs.pop(key).clear_private_data()








async def bootstrap(request):
    state = request.app[STATE]
    models = await models_payload(state)
    presets = await presets_payload()
    inputs = {key: value for key, value in builder_input_schema().items()
              if key != "system_prompt_override"}
    return web.json_response({"inputs": inputs,
                              "presets": presets, "models": models,
                               "backend": models["backend"],
                              "reference_attributes": [{"key": key, "label": label} for key, label in REFERENCE_ATTRIBUTES],
                              "reference_sources": REFERENCE_SOURCES,
                               "max_reference_images": 4,
                              "settings": await asyncio.to_thread(state.settings),
                              "migration_notices": state.migration_notices,
                              "active_job": state.active_job()})




async def job_endpoint(request):
    job = request.app[STATE].jobs.get(request.match_info["id"])
    if job is None:
        recovered = await asyncio.to_thread(request.app[STATE].dataset_checkpoints.find, request.match_info["id"])
        if recovered is not None and request.method == "GET":
            return web.json_response(recovered)
        raise web.HTTPNotFound(reason="Job not found or expired. Generate again.")
    if request.method == "POST" and request.match_info["action"] == "cancel":
        with job.lock:
            if job.status in TERMINAL:
                raise web.HTTPConflict(reason="This job has already finished.")
        # Process termination can briefly wait; keep the HTTP event loop free.
        try:
            snapshot = await asyncio.wait_for(daemon_work(job.cancel), timeout=2)
        except asyncio.TimeoutError:
            # Admission stays occupied until the worker reaches its cancellable
            # checkpoint; a stalled transport must not stall the HTTP response.
            snapshot = job.snapshot()
        return web.json_response(snapshot)
    with job.lock:
        if request.method == "POST":
            if job.status in TERMINAL:
                raise web.HTTPConflict(reason="This job has already finished.")
            if request.match_info["action"] == "pause":
                job.request_pause()
            else:
                job.resume()
        return web.json_response(job.snapshot())


async def release_job_checkpoints(request):
    family = request.query.get("kind")
    if not family:
        raise ValueError("Choose the workflow whose completed checkpoints should be released.")
    released = release_completed_checkpoints(request.app[STATE].jobs, family=family)
    if family == "dataset":
        await asyncio.to_thread(request.app[STATE].dataset_checkpoints.release, released)
    return web.json_response({"ok": True, "released": released})












def create_app(*, port=8190, dist=None, config_loader=load_config, service_factory=GoatedPrompterService,
               settings_path=None, prompts_path=None):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts} | {"http://localhost:5173", "http://127.0.0.1:5173"}

    @web.middleware
    async def security(request, handler):
        origin = request.headers.get("Origin")
        if request.headers.get("Host", "").lower() not in hosts or (origin is not None and origin not in origins):
            return web.json_response({"ok": False, "error": "Untrusted Host or Origin. Open the app on localhost."}, status=403)
        if origin is None and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return web.json_response({"ok": False, "error": "Cross-site requests are forbidden."}, status=403)
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.json_response({"ok": False, "error": exc.reason}, status=exc.status)
        except WorkspaceConflict as exc:
            response = web.json_response({"ok": False, "error": str(exc)}, status=409)
        except (ValueError, TypeError, GoatedPrompterError, DirectorLibraryError) as exc:
            response = web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            logging.exception("Local API request failed")
            response = web.json_response({"ok": False, "error": "Request failed. Check the server console and configuration."}, status=500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app = web.Application(middlewares=[security], client_max_size=112 * 1024 * 1024)
    app[STATE] = LocalState(config_loader, service_factory,
                            settings_path if settings_path is not None else Path(__file__).parent / "data" / "settings.json",
                            prompts_path)
    app.add_routes([web.get("/api/bootstrap", bootstrap), web.delete("/api/jobs", release_job_checkpoints),
                    web.get("/api/jobs/{id}", job_endpoint),
                    web.post("/api/jobs/{id}/{action:pause|resume|cancel}", job_endpoint)])
    for routes in (builder_routes, settings_routes, presets_routes, saved_prompts_routes,
                   minimax_routes, dataset_routes, workflow_settings_routes, refine_routes):
        routes.register(app)
    root = Path(dist or Path(__file__).parent / "frontend" / "dist").resolve()

    async def assets(request):
        relative = request.match_info["path"] or "index.html"
        if relative == "api" or relative.startswith("api/"):
            raise web.HTTPNotFound(reason="Unknown API endpoint.")
        if "\\" in relative or ":" in relative or any(part.startswith(".") for part in relative.split("/")):
            raise web.HTTPForbidden(reason="Invalid asset path.")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise web.HTTPForbidden(reason="Invalid asset path.")
        if not path.is_file():
            raise web.HTTPNotFound(reason="Asset not found. Build frontend/dist or use the Vite dev server.")
        return web.FileResponse(path)

    app.router.add_get("/{path:.*}", assets)

    async def shutdown(app):
        state = app[STATE]
        interrupts = []
        for job in state.jobs.values():
            with job.lock:
                job.stopping = True
                job.gate.set()
            interrupts.append(asyncio.create_task(daemon_work(job.interrupt_requests)))
        waiting = set(state.tasks) | set(interrupts)
        if waiting:
            done, pending = await asyncio.wait(waiting, timeout=3)
            for task in pending:
                task.cancel()
            for task in done:
                if not task.cancelled() and task.exception():
                    logging.error("Shutdown cancellation failed: %s", task.exception())
            for job in state.jobs.values():
                job.mark_abandoned("Shutdown timeout. Completed checkpoints remain recoverable.")
                if job.kind in DATASET_CHECKPOINT_KINDS:
                    await asyncio.to_thread(state.workflow_settings.checkpoint_dataset, job)
        unload_task = asyncio.create_task(daemon_work(get_process_manager().request_unload))
        _done, pending = await asyncio.wait({unload_task}, timeout=1)
        for task in pending:
            task.cancel()
        release_completed_checkpoints(state.jobs)
        state.idea_history.clear()

    app.on_shutdown.append(shutdown)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8190)
    args = parser.parse_args()
    web.run_app(create_app(port=args.port), host=args.host, port=args.port)
