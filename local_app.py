"""Standalone local API and built Vite asset server. Run: python local_app.py."""

import argparse
import asyncio
import base64
import binascii
from contextlib import closing
from collections import OrderedDict
from dataclasses import replace
from io import BytesIO
import logging
import json
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from aiohttp import web
from PIL import Image, UnidentifiedImageError

from goated_prompter.backends.base import GoatedPrompterError
from goated_prompter.backends.llama_cpp_process import get_process_manager, _resolve_server_executable
from goated_prompter.config import load_config
from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService, _as_bool
from goated_prompter.director_profiles import discover_director_profiles, resolve_director_config
from goated_prompter.image_utils import EncodedImage
from goated_prompter.comfy_node import GoatedPrompter
from goated_prompter.reference_map import REFERENCE_ATTRIBUTES
from goated_prompter.presets import (
    DEFAULT_DIRECTOR_PRESET, MODE_DIRECTOR_RECOMMENDATIONS, DirectorLibraryError, delete_user_director,
    list_director_presets, resolve_user_director_directory, save_user_director,
    get_director_preset, recommended_director_for_mode, update_director, reset_director,
)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
COMPLETED_LIMIT = 32
TERMINAL = {"succeeded", "failed"}
STATE = web.AppKey("local_state", object)
MAX_STORE_BYTES = 16 * 1024 * 1024
MAX_PROMPTS = 10000
REFERENCE_SOURCES = ("Off", "Image 1", "Image 2", "Image 3", "Image 4", "Blend")


def atomic_json(path, payload):
    data = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_STORE_BYTES:
        raise ValueError("JSON store exceeds the 16 MiB limit. Export or remove records first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_store(path, default, validate):
    try:
        try:
            with path.open("rb") as file:
                data = file.read(MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            return default
        if len(data) > MAX_STORE_BYTES:
            raise ValueError("Store exceeds the 16 MiB limit.")
        return validate(json.loads(data))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc} Restore or repair this file; it has not been overwritten.") from exc


def validate_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("Settings must be an object.")
    unknown = payload.keys() - {"models_directory", "keep_model_loaded", "selected_profile", "builder"}
    if unknown:
        raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
    if "models_directory" in payload:
        value = payload["models_directory"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("models_directory must be a nonempty local directory path.")
        validate_local_paths({"models_dir": value})
    if "keep_model_loaded" in payload and not isinstance(payload["keep_model_loaded"], bool):
        raise ValueError("keep_model_loaded must be a boolean.")
    if "selected_profile" in payload and not isinstance(payload["selected_profile"], str):
        raise ValueError("selected_profile must be a string.")
    result = dict(payload)
    if "builder" in payload:
        builder = payload["builder"]
        strings = {"idea", "system_prompt_override", "custom_instructions", "generated_prompt", "director_preset"}
        combos = {"mode", "target_model", "creativity", "prompt_length"}
        sources = {f"reference_{key}_source" for key, _ in REFERENCE_ATTRIBUTES}
        if not isinstance(builder, dict):
            raise ValueError("builder must be an object.")
        unknown = builder.keys() - strings - combos - sources - {"lock_generated_prompt"}
        if unknown:
            raise ValueError("Unknown builder settings: " + ", ".join(sorted(unknown)))
        builder = dict(builder)
        schema = GoatedPrompter.INPUT_TYPES()["required"]
        for key, value in builder.items():
            if key == "lock_generated_prompt":
                if not isinstance(value, bool):
                    raise ValueError("lock_generated_prompt must be a boolean.")
            elif not isinstance(value, str) or len(value) > 100000:
                raise ValueError(f"builder {key} must be a string of at most 100000 characters.")
            elif key in sources and value not in REFERENCE_SOURCES:
                raise ValueError(f"Invalid reference source for {key}.")
            elif key in combos:
                if key == "prompt_length" and value == "Maximum":
                    value = builder[key] = "Maximum Detail"
                if value not in schema[key][0]:
                    raise ValueError(f"Invalid builder {key}.")
        result["builder"] = builder
    return result


def validate_prompts(payload):
    if not isinstance(payload, dict) or set(payload) != {"prompts"} or not isinstance(payload["prompts"], list):
        raise ValueError("Expected an object containing only a prompts array.")
    if len(payload["prompts"]) > MAX_PROMPTS:
        raise ValueError("At most 10000 saved prompts are supported.")
    records = {}
    for record in payload["prompts"]:
        required = {"id", "title", "prompt", "createdAt"}
        if not isinstance(record, dict) or not required <= record.keys() or record.keys() - required - {"target"}:
            raise ValueError("Each prompt requires id, title, prompt, createdAt, and optionally target only.")
        for key, limit in (("id", 128), ("title", 80), ("prompt", 100000), ("createdAt", 64), ("target", 256)):
            if key not in record:
                continue
            value = record[key]
            if not isinstance(value, str) or len(value) > limit or (key != "target" and not value.strip()):
                raise ValueError(f"Prompt {key} must be a {'nonempty ' if key != 'target' else ''}string of at most {limit} characters.")
        if any(ord(char) < 33 or char in '/\\?#' for char in record["id"]):
            raise ValueError("Prompt id must not contain whitespace, controls, or URL path separators.")
        if record["id"] in records and records[record["id"]] != record:
            raise ValueError(f"Conflicting saved prompt id: {record['id']}")
        records[record["id"]] = dict(record)
    return {"prompts": list(records.values())}


def decode_image(value, max_dimension=1344):
    if value is None:
        return None
    formats = {"data:image/png;base64": "PNG", "data:image/jpeg;base64": "JPEG",
               "data:image/webp;base64": "WEBP"}
    if not isinstance(value, str) or "," not in value:
        raise ValueError("Images must be PNG, JPEG, or WEBP base64 data URLs, or null.")
    header, data = value.split(",", 1)
    if header not in formats or len(data) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Each image must be PNG, JPEG, or WEBP and at most 20 MiB.")
    try:
        raw = base64.b64decode(data, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Each image must be at most 20 MiB.")
        with Image.open(BytesIO(raw)) as image:
            if image.format != formats[header]:
                raise ValueError("Image content does not match its data URL type.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Each image must be at most 40 million pixels.")
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            prepared = image.convert("RGB")
        try:
            limit = max(256, min(4096, int(max_dimension)))
        except (TypeError, ValueError):
            limit = 1344
        if max(prepared.size) > limit:
            prepared.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        prepared.save(buffer, format="PNG", optimize=True)
        return EncodedImage(base64.b64encode(buffer.getvalue()).decode("ascii"),
                            "image/png", prepared.width, prepared.height)
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Image could not be decoded. Upload a valid PNG, JPEG, or WEBP.") from exc


def validate_local_paths(values):
    for key in ("model_path", "mmproj_path", "llama_server", "models_dir", "discovery_root", "runtime_root",
                "director_model_path", "director_mmproj_path", "director_llama_server"):
        value = str(values.get(key) or "").strip()
        if value and (value.startswith(("\\\\", "//")) or "://" in value):
            raise ValueError(f"{key} must be a local filesystem path, not a URL or network share.")
        if value and str(Path(value).expanduser().resolve()).startswith(("\\\\", "//")):
            raise ValueError(f"{key} must resolve to a local filesystem path.")


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.status = "running"
        self.revision = 0
        self.created_at = time.time()
        self.finished_at = None
        self.result = None
        self.error = None
        self.lock = threading.RLock()
        self.gate = threading.Event()
        self.gate.set()
        self.stopping = False

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "status": self.status, "revision": self.revision, "created_at": self.created_at,
                    "finished_at": self.finished_at, "result": self.result, "error": self.error}

    def checkpoint(self):
        while True:
            with self.lock:
                if self.stopping:
                    raise ValueError("Server is shutting down. Restart it and generate again.")
                if self.gate.is_set():
                    return
                if self.status != "paused":
                    self.status = "paused"
                    self.revision += 1
            self.gate.wait()

    def deliver(self, result):
        while True:
            self.checkpoint()
            with self.lock:
                if not self.gate.is_set():
                    continue
                self.result = result
                self.status = "succeeded"
                self.finished_at = time.time()
                self.revision += 1
                return


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
        self.jobs = OrderedDict()
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
                "keep_model_loaded": _as_bool(local.get("keep_model_loaded", False)),
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

    def execute(self, job, director_request, config, text_only, locked):
        try:
            job.checkpoint()
            if locked is not None:
                result = {"ok": True, "prompt": locked, "backend": "locked",
                          "director_profile": director_request.director_profile,
                          "prompt_model": director_request.selected_prompt_model,
                          "director_preset": director_request.director_preset}
            else:
                effective, _ = resolve_director_config(config, director_request)
                local_settings = effective.get("local_llama_cpp", {})
                validate_local_paths(local_settings)
                if effective.get("backend") == "local_llama_cpp":
                    executable = _resolve_server_executable(local_settings.get("llama_server"), local_settings.get("runtime_root"))
                    validate_local_paths({"llama_server": executable})
                service = self.service_factory(config=config, checkpoint=job.checkpoint)
                generated = (service.generate_text_only if text_only else service.generate)(director_request)
                result = {"ok": True, "prompt": generated.prompt, "backend": generated.backend_name,
                          "director_profile": generated.director_profile,
                          "prompt_model": generated.prompt_model, "director_preset": generated.director_preset}
            job.deliver(result)
        except Exception as exc:
            logging.exception("Local generation failed")
            with job.lock:
                job.error = str(exc) if isinstance(exc, (ValueError, GoatedPrompterError)) else (
                    "Generation failed unexpectedly. Check the server console and model configuration, then retry.")
                job.status = "failed"
                job.finished_at = time.time()
                job.revision += 1

    async def run(self, job, *args):
        await asyncio.to_thread(self.execute, job, *args)
        completed = [key for key, record in self.jobs.items() if record.status in TERMINAL]
        for key in completed[:-COMPLETED_LIMIT]:
            del self.jobs[key]


async def json_object(request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


async def models_payload(state, refresh=False):
    config = state.config()
    discovered = await asyncio.to_thread(discover_director_profiles, config.get("local_llama_cpp", {}), refresh)
    return {**discovered.to_public_mapping(), "ok": True, "backend": str(config.get("backend") or "auto")}


async def presets_payload():
    presets, warnings = await asyncio.to_thread(list_director_presets)
    return {"ok": True, "default": DEFAULT_DIRECTOR_PRESET, "presets": presets,
            "warnings": warnings, "storage": str(resolve_user_director_directory())}


async def bootstrap(request):
    state = request.app[STATE]
    models = await models_payload(state)
    presets = await presets_payload()
    inputs = {key: value for key, value in GoatedPrompter.INPUT_TYPES()["required"].items()
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


async def generate(request):
    state = request.app[STATE]
    payload = await json_object(request)
    settings = payload.get("settings", {})
    images = payload.get("images", [])
    text_only = payload.get("text_only", False)
    if not isinstance(settings, dict) or not isinstance(images, list) or len(images) > 4:
        raise ValueError("settings must be an object; images must be an array with at most four entries.")
    if not isinstance(text_only, bool):
        raise ValueError("text_only must be a boolean.")
    locked = None
    if _as_bool(settings.get("lock_generated_prompt", False)):
        locked = str(settings.get("generated_prompt") or "")
        if not locked.strip():
            raise ValueError("Generated Prompt is locked but empty. Generate or enter a prompt first.")
    async with state.admission:
        active_job = state.active_job()
        if active_job is not None:
            return web.json_response({"ok": False,
                                      "error": "A job is active. Resume it or wait for completion before generating again.",
                                      "active_job": active_job}, status=409)
        if locked is not None:
            config = {}
            director_request = GoatedPrompterRequest(idea="")
        else:
            director = get_director_preset(settings.get("director_preset", DEFAULT_DIRECTOR_PRESET), strict=True)
            settings = {**settings, "director_preset": director.id,
                        "mode": settings.get("mode") or director.recommended_mode or "Custom",
                        "system_prompt_override": ""}
            validate_local_paths(settings)
            config = state.config()
            director_request = replace(GoatedPrompterRequest.from_mapping(settings),
                                       linked_references=_as_bool(settings.get("linked_references", False)))
            if "keep_model_loaded" in state.saved_settings:
                director_request = replace(director_request,
                                           director_keep_model_loaded=state.saved_settings["keep_model_loaded"])
            if not text_only:
                vision = config.get("vision", {})
                dimension = vision.get("max_image_dimension", 1344) if isinstance(vision, dict) else 1344
                slots = images + [None] * (4 - len(images))
                encoded = await asyncio.to_thread(lambda: [decode_image(value, dimension) for value in slots])
                director_request = replace(director_request, image=encoded[0], image_2=encoded[1],
                                           image_3=encoded[2], image_4=encoded[3])
        job = Job()
        state.jobs[job.id] = job
        task = asyncio.create_task(state.run(job, director_request, config, text_only, locked))
        state.tasks.add(task)
        task.add_done_callback(state.tasks.discard)
        return web.json_response(job.snapshot(), status=202)


async def job_endpoint(request):
    job = request.app[STATE].jobs.get(request.match_info["id"])
    if job is None:
        raise web.HTTPNotFound(reason="Job not found or expired. Generate again.")
    with job.lock:
        if request.method == "POST":
            if job.status in TERMINAL:
                raise web.HTTPConflict(reason="This job has already finished.")
            if request.match_info["action"] == "pause":
                job.gate.clear()
                if job.status != "paused":
                    job.status = "pause_requested"
            else:
                job.status = "running"
                job.gate.set()
            job.revision += 1
        return web.json_response(job.snapshot())


async def models(request):
    refresh = request.query.get("refresh", "").strip().lower() in {"1", "true", "yes"}
    return web.json_response(await models_payload(request.app[STATE], refresh))


async def settings_endpoint(request):
    state = request.app[STATE]
    if request.method == "PUT":
        payload = await json_object(request)
        async with state.admission:
            active = state.active_job()
            if active is not None and set(payload) != {"builder"}:
                return web.json_response({"ok": False, "error": "Settings cannot change while a job is active.",
                                          "active_job": active}, status=409)
            async with state.storage_lock:
                state.save_settings(payload)
    return web.json_response(await asyncio.to_thread(state.settings))


async def prompts_endpoint(request):
    state = request.app[STATE]
    incoming = None
    if request.method == "POST":
        payload = await json_object(request)
        if request.path != "/api/prompts/import":
            payload = {"prompts": [payload]}
        # Conflicting IDs within an import are conflicts, not partial successes.
        try:
            incoming = validate_prompts(payload)["prompts"]
        except ValueError as exc:
            if str(exc).startswith("Conflicting saved prompt id:"):
                raise web.HTTPConflict(reason=str(exc)) from exc
            raise
    async with state.storage_lock:
        current = read_store(state.prompts_path, {"prompts": []}, validate_prompts)
        records = {record["id"]: record for record in current["prompts"]}
        if incoming is not None:
            for record in incoming:
                if record["id"] in records and records[record["id"]] != record:
                    raise web.HTTPConflict(reason=f"Conflicting saved prompt id: {record['id']}")
                records[record["id"]] = record
        elif request.method == "DELETE":
            records.pop(request.match_info["id"], None)
        snapshot = validate_prompts({"prompts": list(records.values())})
        if snapshot != current:
            atomic_json(state.prompts_path, snapshot)
        return web.json_response(snapshot)


async def presets(request):
    if request.method == "GET":
        return web.json_response(await presets_payload())
    payload = await json_object(request)
    state = request.app[STATE]
    async with state.admission:
        active = state.active_job()
        if active is not None:
            return web.json_response({"ok": False, "error": "Directors cannot change while a job is active.",
                                      "active_job": active}, status=409)
        async with state.storage_lock:
            if request.path == "/api/presets/reset":
                director, path = reset_director(payload.get("id"))
            elif request.method == "PUT":
                director, path = update_director(payload.get("id"), payload.get("name"), payload.get("instructions"))
            elif request.method == "POST":
                director, path = save_user_director(payload.get("name"), payload.get("instructions"),
                                                    payload.get("recommended_mode", "Custom"))
            else:
                director, path = delete_user_director(payload.get("id") or payload.get("name"))
    return web.json_response({"ok": True, "director": director.to_public_mapping(), "file": path.name})


async def unload(request):
    status = await asyncio.to_thread(get_process_manager().request_unload)
    messages = {"idle": "No Goated Prompter model is currently loaded.",
                "pending": "Unload queued until the active Goated Prompter operation finishes.",
                "unloaded": "Goated Prompter model unloaded."}
    return web.json_response({"ok": True, "status": status, "message": messages[status]})


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
    app.add_routes([web.get("/api/bootstrap", bootstrap), web.post("/api/generate", generate),
                    web.get("/api/jobs/{id}", job_endpoint),
                    web.post("/api/jobs/{id}/{action:pause|resume}", job_endpoint),
                    web.get("/api/models", models), web.get("/api/presets", presets),
                    web.get("/api/settings", settings_endpoint), web.put("/api/settings", settings_endpoint),
                    web.get("/api/prompts", prompts_endpoint), web.post("/api/prompts", prompts_endpoint),
                    web.post("/api/prompts/import", prompts_endpoint), web.delete("/api/prompts/{id}", prompts_endpoint),
                    web.post("/api/presets", presets), web.delete("/api/presets", presets),
                    web.put("/api/presets", presets), web.post("/api/presets/reset", presets),
                    web.post("/api/unload", unload)])
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
        for job in state.jobs.values():
            with job.lock:
                job.stopping = True
                job.gate.set()
        if state.tasks:
            await asyncio.gather(*state.tasks)
        await asyncio.to_thread(get_process_manager().request_unload)

    app.on_shutdown.append(shutdown)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8190)
    args = parser.parse_args()
    web.run_app(create_app(port=args.port), host=args.host, port=args.port)
