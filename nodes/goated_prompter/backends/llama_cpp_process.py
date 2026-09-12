"""Owned llama.cpp server lifecycle management for Goated Prompter."""

import atexit
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .base import BackendConfigurationError, BackendGenerationError
from ..director_profiles import resolve_models_directory

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _log(message):
    print(f"[Goated Prompter] {message}", flush=True)


def _path_text(path):
    return str(path) if path is not None else "NONE"


def _model_identity(config):
    return f"{config.requested_model} | model={config.model_path} | mmproj={_path_text(config.mmproj_path)}"


def _command_text(command):
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def _bounded_int(value, name, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise BackendConfigurationError(f"local_llama_cpp {name} must be an integer.") from exc
    if not minimum <= number <= maximum:
        raise BackendConfigurationError(
            f"local_llama_cpp {name} must be between {minimum} and {maximum}."
        )
    return number


def _bounded_float(value, name, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BackendConfigurationError(f"local_llama_cpp {name} must be numeric.") from exc
    if not minimum <= number <= maximum:
        raise BackendConfigurationError(
            f"local_llama_cpp {name} must be between {minimum} and {maximum}."
        )
    return number


def _resolve_model_file(value, models_dir, label):
    text = str(value or "").strip()
    if not text:
        raise BackendConfigurationError(f"local_llama_cpp {label} is not configured.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        if models_dir is None:
            raise BackendConfigurationError(
                f"Cannot resolve relative {label}; configure models_dir or GOATED_PROMPTER_MODELS_DIR."
            )
        path = models_dir / path
    path = path.resolve()
    if not path.is_file():
        raise BackendConfigurationError(f"local_llama_cpp {label} does not exist: {path}")
    if path.suffix.lower() != ".gguf":
        raise BackendConfigurationError(f"local_llama_cpp {label} must be a GGUF file.")
    return path


def _resolve_comfyui_root():
    try:
        import folder_paths

        value = getattr(folder_paths, "base_path", None)
        if value:
            return Path(value).resolve()
    except (ImportError, AttributeError, OSError):
        pass
    return None


def _resolve_server_executable(value, runtime_root=None):
    text = str(value or "").strip()
    candidates = [text] if text else ["llama-server.exe", "llama-server"]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
        if not path.is_absolute():
            base = Path(runtime_root).expanduser().resolve() if runtime_root else _resolve_comfyui_root()
            if base is not None:
                portable = base / path
                if portable.is_file():
                    return portable.resolve()
        discovered = shutil.which(candidate)
        if discovered:
            return Path(discovered).resolve()
    raise BackendConfigurationError(
        "local_llama_cpp llama_server executable was not found. Configure llama_server or add llama-server to PATH."
    )


@dataclass(frozen=True)
class LlamaCppLaunchConfig:
    executable: Path
    model_path: Path
    mmproj_path: Path
    host: str
    port: int
    context_size: int
    image_min_tokens: int
    gpu_layers: str
    reasoning: str
    keep_model_loaded: bool
    max_tokens: int
    timeout: float
    startup_timeout: float
    temperature: float
    alias: str
    requested_model: str

    @classmethod
    def from_mapping(cls, settings):
        if not isinstance(settings, dict):
            raise BackendConfigurationError("local_llama_cpp configuration must be an object.")
        models_dir = resolve_models_directory(settings)
        model_path = _resolve_model_file(settings.get("model_path"), models_dir, "model_path")
        mmproj_path = _resolve_model_file(settings.get("mmproj_path"), models_dir, "mmproj_path")
        if model_path == mmproj_path:
            raise BackendConfigurationError("local_llama_cpp model_path and mmproj_path must be different files.")
        if "mmproj" not in mmproj_path.name.lower():
            raise BackendConfigurationError("local_llama_cpp mmproj filename must contain 'mmproj'.")
        if model_path.parent != mmproj_path.parent:
            raise BackendConfigurationError(
                "local_llama_cpp model and mmproj must be stored in the same model folder to prevent accidental pairing."
            )

        host = str(settings.get("host") or "127.0.0.1").strip().lower()
        if host not in _LOOPBACK_HOSTS:
            raise BackendConfigurationError("local_llama_cpp host must be localhost/loopback in v0.2.")
        gpu_layers = str(settings.get("gpu_layers", "auto")).strip().lower()
        if gpu_layers not in {"auto", "all"}:
            gpu_layers = str(_bounded_int(gpu_layers, "gpu_layers", 0, 999))
        reasoning = str(settings.get("reasoning", "off")).strip().lower()
        if reasoning not in {"on", "off", "auto"}:
            raise BackendConfigurationError("local_llama_cpp reasoning must be on, off, or auto.")

        return cls(
            executable=_resolve_server_executable(settings.get("llama_server"), settings.get("runtime_root")),
            model_path=model_path,
            mmproj_path=mmproj_path,
            host=host,
            port=_bounded_int(settings.get("port", 8189), "port", 1024, 65535),
            context_size=_bounded_int(settings.get("context_size", 8192), "context_size", 512, 1048576),
            image_min_tokens=_bounded_int(settings.get("image_min_tokens", 1024), "image_min_tokens", 1, 1048576),
            gpu_layers=gpu_layers,
            reasoning=reasoning,
            keep_model_loaded=bool(settings.get("keep_model_loaded", False)),
            max_tokens=_bounded_int(settings.get("max_tokens", 768), "max_tokens", 1, 1048576),
            timeout=_bounded_float(settings.get("timeout", 180), "timeout", 1, 3600),
            startup_timeout=_bounded_float(settings.get("startup_timeout", 180), "startup_timeout", 1, 3600),
            temperature=_bounded_float(settings.get("temperature", 0.3), "temperature", 0, 2),
            alias=str(settings.get("alias") or "goated-prompter-vlm").strip(),
            requested_model=str(settings.get("requested_model") or model_path.name).strip(),
        )

    @property
    def key(self):
        return (
            str(self.executable), str(self.model_path), str(self.mmproj_path), self.host,
            self.port, self.context_size, self.image_min_tokens, self.gpu_layers,
            self.reasoning, self.alias,
        )

    @property
    def compatibility_key(self):
        """Restart-critical identity, excluding the manager-selected runtime port."""
        return (
            str(self.executable), str(self.model_path), str(self.mmproj_path), self.host,
            self.context_size, self.image_min_tokens, self.gpu_layers,
            self.reasoning, self.alias,
        )

    @property
    def base_url(self):
        host = "127.0.0.1" if self.host == "localhost" else self.host
        bracketed = f"[{host}]" if ":" in host else host
        return f"http://{bracketed}:{self.port}"

    def command(self):
        return [
            str(self.executable),
            "--model", str(self.model_path),
            "--mmproj", str(self.mmproj_path),
            "--ctx-size", str(self.context_size),
            "--image-min-tokens", str(self.image_min_tokens),
            "--n-gpu-layers", self.gpu_layers,
            "--reasoning", self.reasoning,
            "--host", self.host,
            "--port", str(self.port),
            "--alias", self.alias,
        ]


@dataclass
class OwnedLlamaServer:
    config: LlamaCppLaunchConfig
    process: object
    requested_config: LlamaCppLaunchConfig = None
    references: int = 1
    pending_unload: bool = False
    keep_model_loaded: bool = field(init=False)

    def __post_init__(self):
        if self.requested_config is None:
            self.requested_config = self.config
        self.keep_model_loaded = self.requested_config.keep_model_loaded


class LlamaCppProcessManager:
    """Authoritative owner of the single llama-server child used by Goated Prompter."""

    def __init__(self):
        self._owned = None
        self._lock = threading.RLock()

    @property
    def owned_process_count(self):
        with self._lock:
            return 1 if self._live_owned() is not None else 0

    def acquire(self, config, include_state=False):
        with self._lock:
            restarted = False
            _log(f"Requested model: {config.requested_model}")
            _log(f"Requested GGUF: {config.model_path}")
            _log(f"Requested mmproj: {_path_text(config.mmproj_path)}")
            active = self._live_owned()
            if active is not None:
                _log(f"Existing llama-server PID: {getattr(active.process, 'pid', 'UNKNOWN')}")
                _log(f"Existing model: {_model_identity(active.config)}")
                if self._compatible(active, config):
                    active.references += 1
                    active.keep_model_loaded = config.keep_model_loaded
                    _log("Reusing existing llama-server")
                    _log(
                        "Reusing owned llama-server "
                        f"PID={getattr(active.process, 'pid', 'UNKNOWN')} port={active.config.port}"
                    )
                    _log(f"Active model: {_model_identity(active.config)}")
                    state = {"reused": True, "restarted": False}
                    return (active, state) if include_state else active

                if self._model_changed(active.requested_config, config):
                    _log("MODEL CHANGE DETECTED")
                    _log(f"Old model: {_model_identity(active.requested_config)}")
                    _log(f"New model: {_model_identity(config)}")
                if active.references > 0:
                    raise BackendConfigurationError(
                        "A different Goated Prompter model/configuration is still generating. "
                        "Wait for it to finish before switching Prompt Model."
                    )
                _log("Restarting owned llama-server: model/config changed")
                self._terminate(active)
                self._owned = None
                restarted = True
                _log(f"Starting new model: {_model_identity(config)}")

            runtime_config = self._runtime_config(config)
            process = self._start_process(runtime_config)
            owned = OwnedLlamaServer(
                config=runtime_config,
                process=process,
                requested_config=config,
            )
            self._owned = owned
            _log(
                "Starting owned llama-server "
                f"PID={getattr(process, 'pid', 'UNKNOWN')} port={runtime_config.port}"
            )
            try:
                self._wait_until_ready(owned)
            except Exception:
                owned.references = 0
                self._terminate(owned)
                if self._owned is owned:
                    self._owned = None
                raise
            state = {"reused": False, "restarted": restarted}
            return (owned, state) if include_state else owned

    def _live_owned(self):
        owned = self._owned
        if owned is None:
            return None
        if owned.process.poll() is None:
            return owned
        _log("Owned process died; clearing stale state")
        self._owned = None
        return None

    @staticmethod
    def _compatible(owned, requested):
        return (
            owned.requested_config.compatibility_key == requested.compatibility_key
            and owned.requested_config.port == requested.port
        )

    @staticmethod
    def _model_changed(active, requested):
        return (
            active.model_path != requested.model_path
            or active.mmproj_path != requested.mmproj_path
        )

    def _runtime_config(self, requested):
        if self._port_available(requested.host, requested.port):
            return requested
        fallback = self._find_fallback_port(requested.host, requested.port)
        _log(
            f"Preferred port {requested.port} occupied by unrelated process; using port {fallback}"
        )
        return replace(requested, port=fallback)

    def _find_fallback_port(self, host, preferred):
        span = 65535 - 1024 + 1
        for offset in range(1, 257):
            candidate = 1024 + ((preferred - 1024 + offset) % span)
            if self._port_available(host, candidate):
                return candidate
        raise BackendConfigurationError(
            "Goated Prompter could not find a free loopback port for its owned llama.cpp server."
        )

    def release(self, owned):
        with self._lock:
            if self._owned is not owned:
                return
            owned.references = max(0, owned.references - 1)
            if owned.references == 0 and (owned.pending_unload or not owned.keep_model_loaded):
                if owned.pending_unload:
                    _log("Active Goated Prompter operation finished; completing pending unload")
                self._terminate(owned)
                self._owned = None

    def request_unload(self):
        """Unload idle owned servers, deferring safely while generation is active."""
        with self._lock:
            _log("Unload requested")
            owned = self._live_owned()
            if owned is None:
                _log("Unload Model requested; no managed llama-server is loaded")
                return "idle"
            if owned.references > 0:
                owned.pending_unload = True
                _log("Unload deferred: inference active")
                return "pending"
            self._terminate(owned)
            self._owned = None
            return "unloaded"

    def cleanup_all(self):
        with self._lock:
            owned = self._live_owned()
            if owned is not None:
                self._terminate(owned)
            self._owned = None

    def _start_process(self, config):
        command = config.command()
        _log("Starting llama-server")
        _log(f"Model: {config.model_path}")
        _log(f"mmproj: {_path_text(config.mmproj_path)}")
        _log(f"Command: {_command_text(command)}")
        kwargs = {
            "cwd": str(config.executable.parent),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            return subprocess.Popen(command, **kwargs)
        except OSError as exc:
            raise BackendGenerationError(f"Could not start local llama.cpp server: {exc}") from exc

    def _wait_until_ready(self, owned):
        deadline = time.monotonic() + owned.config.startup_timeout
        health_url = f"{owned.config.base_url}/health"
        while time.monotonic() < deadline:
            code = owned.process.poll()
            if code is not None:
                raise BackendGenerationError(f"Owned llama.cpp server exited during startup with code {code}.")
            try:
                with urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        return
            except HTTPError as exc:
                if exc.code != 503:
                    time.sleep(0.25)
            except (URLError, TimeoutError, OSError):
                pass
            time.sleep(0.25)
        raise BackendGenerationError(
            f"Owned llama.cpp server did not become ready within {owned.config.startup_timeout:g} seconds."
        )

    @staticmethod
    def _port_available(host, port):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        bind_host = "127.0.0.1" if host == "localhost" else host
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.bind((bind_host, port))
            return True
        except OSError:
            return False

    @staticmethod
    def _terminate(owned):
        process = owned.process
        pid = getattr(process, "pid", "UNKNOWN")
        owned.pending_unload = True
        try:
            if process.poll() is not None:
                return
            _log(f"Stopping llama-server PID {pid}")
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
        if process.poll() is None:
            raise BackendGenerationError(f"Could not stop owned llama.cpp server PID {pid}; retry unloading it.")
        _log(f"Owned llama-server stopped PID={pid}")


_RUNTIME_REGISTRY_KEY = "_goated_prompter_llama_runtime_registry"
_runtime_registry = sys.modules.setdefault(_RUNTIME_REGISTRY_KEY, ModuleType(_RUNTIME_REGISTRY_KEY))
_runtime_registry_lock = _runtime_registry.__dict__.setdefault("lock", threading.RLock())
with _runtime_registry_lock:
    _PROCESS_MANAGER = getattr(_runtime_registry, "process_manager", None)
    if _PROCESS_MANAGER is None:
        _PROCESS_MANAGER = LlamaCppProcessManager()
        _runtime_registry.process_manager = _PROCESS_MANAGER
        atexit.register(_PROCESS_MANAGER.cleanup_all)


def get_process_manager():
    return _PROCESS_MANAGER
