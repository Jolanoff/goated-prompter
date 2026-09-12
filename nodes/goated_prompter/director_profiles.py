"""Local Director AI profile discovery and selection resolution."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import threading

from .backends.base import BackendConfigurationError

PROMPT_MODEL_QWEN = "Qwen 3.5 9B"
PROMPT_MODEL_QWEN_UNCENSORED = "Qwen 3.5 9B — Uncensored"
PROMPT_MODEL_QWEN_AGGRESSIVE = "Qwen 3.5 9B — HauhauCS Aggressive"
PROMPT_MODEL_GEMMA = "Gemma 3 12B"
PROMPT_MODEL_NAMES = (
    PROMPT_MODEL_QWEN,
    PROMPT_MODEL_QWEN_UNCENSORED,
    PROMPT_MODEL_QWEN_AGGRESSIVE,
    PROMPT_MODEL_GEMMA,
    "Custom",
)

# Kept for third-party callers that still validate legacy payload values.
DIRECTOR_AI_NAMES = ("Default", "Uncensored", "Gemma", "Custom")

QWEN_RUNTIME_DEFAULTS = {
    "reasoning": "off",
    "image_min_tokens": 1024,
    "max_tokens": 768,
    "context_size": 8192,
    "gpu_layers": "auto",
    "host": "127.0.0.1",
}

GEMMA_RUNTIME_DEFAULTS = {
    "reasoning": "off",
    "image_min_tokens": 1024,
    "max_tokens": 768,
    "context_size": 8192,
    "gpu_layers": "auto",
    "host": "127.0.0.1",
}


@dataclass(frozen=True)
class KnownProfileRule:
    key: str
    label: str
    slot: str
    prompt_model: str
    model_family: str
    required_terms: tuple
    excluded_terms: tuple = ()
    runtime_defaults: dict = field(default_factory=dict)

    def matches(self, text):
        compact = re.sub(r"[^a-z0-9]+", "", str(text).casefold())
        return all(re.sub(r"[^a-z0-9]+", "", term.casefold()) in compact for term in self.required_terms) and not any(
            re.sub(r"[^a-z0-9]+", "", term.casefold()) in compact for term in self.excluded_terms
        )


KNOWN_PROFILE_RULES = (
    KnownProfileRule(
        key="qwen35_9b_uncensored_hauhaucs_aggressive",
        label=PROMPT_MODEL_QWEN_AGGRESSIVE,
        slot="Uncensored",
        prompt_model=PROMPT_MODEL_QWEN_AGGRESSIVE,
        model_family="qwen",
        required_terms=("qwen3.5", "9b", "uncensored", "hauhaucs", "aggressive"),
        runtime_defaults=QWEN_RUNTIME_DEFAULTS,
    ),
    KnownProfileRule(
        key="qwen35_9b_uncensored",
        label=PROMPT_MODEL_QWEN_UNCENSORED,
        slot="Uncensored",
        prompt_model=PROMPT_MODEL_QWEN_UNCENSORED,
        model_family="qwen",
        required_terms=("qwen3.5", "9b", "uncensored"),
        runtime_defaults=QWEN_RUNTIME_DEFAULTS,
    ),
    KnownProfileRule(
        key="qwen35_9b_standard",
        label=PROMPT_MODEL_QWEN,
        slot="Default",
        prompt_model=PROMPT_MODEL_QWEN,
        model_family="qwen",
        required_terms=("qwen3.5", "9b"),
        excluded_terms=("uncensored", "hauhaucs", "aggressive"),
        runtime_defaults=QWEN_RUNTIME_DEFAULTS,
    ),
    KnownProfileRule(
        key="gemma3_12b",
        label=PROMPT_MODEL_GEMMA,
        slot="Gemma",
        prompt_model=PROMPT_MODEL_GEMMA,
        model_family="gemma",
        required_terms=("gemma3", "12b"),
        runtime_defaults=GEMMA_RUNTIME_DEFAULTS,
    ),
)


@dataclass(frozen=True)
class DirectorProfile:
    profile_id: str
    label: str
    slot: str
    folder: Path
    prompt_model: str = "Custom"
    model_family: str = "generic"
    model_path: Path = None
    mmproj_path: Path = None
    runtime_defaults: dict = field(default_factory=dict)
    warning: str = ""

    @property
    def vision_ready(self):
        return self.model_path is not None and self.mmproj_path is not None

    def to_public_mapping(self):
        return {
            "id": self.profile_id,
            "label": self.label,
            "slot": self.slot,
            "prompt_model": self.prompt_model,
            "model_family": self.model_family,
            "folder": self.folder.name,
            "vision_ready": self.vision_ready,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    models_dir: Path
    llm_root: Path
    profiles: tuple
    warnings: tuple = ()

    def preferred(self, slot):
        return next(
            (profile for profile in self.profiles if profile.slot == slot and profile.vision_ready),
            None,
        )

    def preferred_prompt_model(self, prompt_model):
        return next(
            (
                profile
                for profile in self.profiles
                if profile.prompt_model == prompt_model and profile.vision_ready
            ),
            None,
        )

    def by_id(self, profile_id):
        value = str(profile_id or "").strip().casefold()
        return next((profile for profile in self.profiles if profile.profile_id.casefold() == value), None)

    def to_public_mapping(self):
        assignments = {}
        for prompt_model in PROMPT_MODEL_NAMES[:-1]:
            profile = self.preferred_prompt_model(prompt_model)
            assignments[prompt_model] = profile.to_public_mapping() if profile else None
        # Compatibility keys for older frontends and serialized workflows.
        assignments["Default"] = assignments[PROMPT_MODEL_QWEN]
        assignments["Uncensored"] = assignments[PROMPT_MODEL_QWEN_UNCENSORED]
        assignments["Gemma"] = assignments[PROMPT_MODEL_GEMMA]
        return {
            "root": str(self.llm_root),
            "profiles": [profile.to_public_mapping() for profile in self.profiles],
            "assignments": assignments,
            "warnings": list(self.warnings),
        }


def resolve_models_directory(settings=None):
    settings = settings if isinstance(settings, dict) else {}
    configured = str(settings.get("models_dir") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    env_value = os.environ.get("GOATED_PROMPTER_MODELS_DIR", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    try:
        import folder_paths

        return Path(folder_paths.models_dir).resolve()
    except (ImportError, AttributeError):
        candidate = Path.cwd() / "models"
        return candidate.resolve()


def _normal_name(*parts):
    return " ".join(str(part).casefold().replace("_", "-") for part in parts)


def _compact_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def canonical_prompt_model(value):
    """Map legacy/generic labels to one stable friendly Prompt Model name."""
    compact = _compact_name(value)
    aliases = {
        "default": PROMPT_MODEL_QWEN,
        "qwen359b": PROMPT_MODEL_QWEN,
        "qwen359bstandard": PROMPT_MODEL_QWEN,
        "uncensored": PROMPT_MODEL_QWEN_UNCENSORED,
        "qwen359buncensored": PROMPT_MODEL_QWEN_UNCENSORED,
        "qwen359buncensoredhauhaucsaggressive": PROMPT_MODEL_QWEN_AGGRESSIVE,
        "qwen359bhauhaucsaggressive": PROMPT_MODEL_QWEN_AGGRESSIVE,
        "gemma": PROMPT_MODEL_GEMMA,
        "gemma312b": PROMPT_MODEL_GEMMA,
        "custom": "Custom",
    }
    return aliases.get(compact, PROMPT_MODEL_QWEN)


def infer_prompt_model_family(value):
    selection = canonical_prompt_model(value)
    if selection == PROMPT_MODEL_GEMMA:
        return "gemma"
    if selection.startswith("Qwen "):
        return "qwen"
    return "generic"


def _known_rule(folder, model_path):
    text = _normal_name(folder.name, model_path.name if model_path else "")
    return next((rule for rule in KNOWN_PROFILE_RULES if rule.matches(text)), None)


def _quant_rank(path):
    name = path.name.casefold()
    preferences = ("q4_k_m", "q5_k_m", "q6_k", "q8_0", "q4_k_s", "q3_k_m", "f16", "bf16")
    normalized = name.replace("-", "_").replace(".", "_")
    rank = next((index for index, quant in enumerate(preferences) if quant in normalized), len(preferences))
    return rank, len(name), name


def _projector_rank(path, model_path):
    name = path.name.casefold()
    model_terms = set(re.findall(r"[a-z0-9]+", model_path.stem.casefold())) if model_path else set()
    projector_terms = set(re.findall(r"[a-z0-9]+", path.stem.casefold()))
    shared = len(model_terms & projector_terms)
    precision = 0 if "bf16" in name else 1 if "f16" in name else 2 if "q8" in name else 3
    return -shared, precision, len(name), name


def _folder_profile(folder, llm_root):
    files = sorted((path for path in folder.glob("*.gguf") if path.is_file()), key=lambda path: path.name.casefold())
    models = [path for path in files if "mmproj" not in path.name.casefold()]
    projectors = [path for path in files if "mmproj" in path.name.casefold()]
    if not models and not projectors:
        return None

    model_path = min(models, key=_quant_rank) if models else None
    mmproj_path = min(projectors, key=lambda path: _projector_rank(path, model_path)) if projectors else None
    rule = _known_rule(folder, model_path)
    compact_identity = _compact_name(f"{folder.name} {model_path.name if model_path else ''}")
    inferred_family = "gemma" if "gemma" in compact_identity else "qwen" if "qwen" in compact_identity else "generic"
    warning_parts = []
    if len(models) > 1:
        warning_parts.append(f"Multiple model GGUF files found; selected {model_path.name} deterministically.")
    if len(projectors) > 1:
        warning_parts.append(f"Multiple mmproj files found; selected {mmproj_path.name} deterministically.")
    if model_path is None:
        warning_parts.append("Missing main model GGUF; this folder is incomplete.")
    if mmproj_path is None:
        warning_parts.append("Missing mmproj GGUF; text-only model file detected but vision is unavailable.")

    relative = folder.relative_to(llm_root).as_posix()
    return DirectorProfile(
        profile_id=relative,
        label=rule.label if rule else folder.name,
        slot=rule.slot if rule else "Custom",
        folder=folder,
        prompt_model=rule.prompt_model if rule else "Custom",
        model_family=rule.model_family if rule else inferred_family,
        model_path=model_path,
        mmproj_path=mmproj_path,
        runtime_defaults=dict(rule.runtime_defaults) if rule else {},
        warning=" ".join(warning_parts),
    )


_CACHE = {}
_CACHE_LOCK = threading.RLock()


def discover_director_profiles(settings=None, refresh=False):
    models_dir = resolve_models_directory(settings)
    llm_root = models_dir if models_dir.name.casefold() == "llm" else models_dir / "LLM"
    if isinstance(settings, dict) and settings.get("discovery_root"):
        llm_root = Path(settings["discovery_root"]).expanduser().resolve()
    cache_key = str(llm_root).casefold()
    with _CACHE_LOCK:
        if not refresh and cache_key in _CACHE:
            return _CACHE[cache_key]

    warnings = []
    profiles = []
    if not llm_root.is_dir():
        warnings.append(f"Director AI model folder does not exist: {llm_root}")
    else:
        folders = sorted(
            {path.parent for path in llm_root.rglob("*.gguf") if path.is_file()},
            key=lambda path: path.relative_to(llm_root).as_posix().casefold(),
        )
        for folder in folders:
            profile = _folder_profile(folder, llm_root)
            if profile is not None:
                profiles.append(profile)
                if profile.warning:
                    warnings.append(f"{profile.label}: {profile.warning}")

    prompt_model_order = {name: index for index, name in enumerate(PROMPT_MODEL_NAMES)}
    profiles.sort(key=lambda profile: (prompt_model_order.get(profile.prompt_model, 99), profile.label.casefold(), profile.profile_id.casefold()))
    result = DiscoveryResult(models_dir=models_dir, llm_root=llm_root, profiles=tuple(profiles), warnings=tuple(warnings))
    with _CACHE_LOCK:
        _CACHE[cache_key] = result
    return result


def _custom_runtime_settings(request):
    return {
        "context_size": request.director_context_size,
        "image_min_tokens": request.director_image_min_tokens,
        "max_tokens": request.director_max_tokens,
        "gpu_layers": request.director_gpu_layers,
        "reasoning": "off",
        "host": "127.0.0.1",
        "keep_model_loaded": request.director_keep_model_loaded,
    }


def resolve_director_config(config, request, refresh=False):
    """Return an effective backend config without mutating the user config."""
    config = dict(config or {})
    backend_name = str(config.get("backend") or "").strip().lower().replace("-", "_")
    if backend_name in {"mock", "debug", "openai", "openai_compatible"}:
        return config, None

    legacy_selection = str(getattr(request, "director_ai", "") or "").strip()
    requested_selection = legacy_selection or str(getattr(request, "prompt_model", "") or "")
    selection = canonical_prompt_model(requested_selection)
    local_settings = dict(config.get("local_llama_cpp") or {})
    discovery = discover_director_profiles(local_settings, refresh=refresh)
    profile = None

    if selection != "Custom":
        profile = discovery.preferred_prompt_model(selection)
        if profile is None and legacy_selection.casefold() == "uncensored":
            profile = discovery.preferred("Uncensored")
        if profile is None:
            raise BackendConfigurationError(
                f"Prompt Model {selection} is unavailable. Add a complete matching model + mmproj folder under {discovery.llm_root}."
            )
    else:
        if request.director_profile:
            profile = discovery.by_id(request.director_profile)
            if profile is None:
                raise BackendConfigurationError("The selected Custom Prompt Model profile was not found. Refresh Models and select it again.")
            if not profile.vision_ready:
                raise BackendConfigurationError(
                    f"Custom Prompt Model profile '{profile.label}' is incomplete: {profile.warning or 'matching model and mmproj are required.'}"
                )
        elif request.director_model_path or request.director_mmproj_path:
            if not request.director_model_path or not request.director_mmproj_path:
                raise BackendConfigurationError("Custom Prompt Model requires both model and mmproj paths.")
            local_settings.update(_custom_runtime_settings(request))
            local_settings["model_path"] = request.director_model_path
            local_settings["mmproj_path"] = request.director_mmproj_path
            local_settings["requested_model"] = selection
            if request.director_llama_server:
                local_settings["llama_server"] = request.director_llama_server
            effective = dict(config)
            effective["backend"] = "local_llama_cpp"
            effective["local_llama_cpp"] = local_settings
            return effective, None
        else:
            raise BackendConfigurationError(
                "Custom Prompt Model selected, but no custom model is configured. Choose a discovered profile or provide both model and mmproj paths in Advanced."
            )

    local_settings.update(profile.runtime_defaults)
    if selection == "Custom":
        local_settings.update(_custom_runtime_settings(request))
        if request.director_llama_server:
            local_settings["llama_server"] = request.director_llama_server
    local_settings["model_path"] = str(profile.model_path)
    local_settings["mmproj_path"] = str(profile.mmproj_path)
    local_settings["requested_model"] = selection
    local_settings["keep_model_loaded"] = request.director_keep_model_loaded
    effective = dict(config)
    effective["backend"] = "local_llama_cpp"
    effective["local_llama_cpp"] = local_settings
    return effective, profile
