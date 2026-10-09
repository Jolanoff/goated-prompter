"""Saved settings and local path validation."""

from pathlib import Path

from ..builder.input_schema import builder_input_schema
from ...options.references import REFERENCE_SOURCES
from ...options.references import REFERENCE_ATTRIBUTES


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
        combos = {"mode", "target_model", "creativity", "prompt_length", "planning_mode"}
        sources = {f"reference_{key}_source" for key, _ in REFERENCE_ATTRIBUTES}
        if not isinstance(builder, dict):
            raise ValueError("builder must be an object.")
        builder = dict(builder)
        builder.pop("lock_generated_prompt", None)
        builder.pop("resolution", None)  # Remove legacy data from pre-removal settings.
        unknown = builder.keys() - strings - combos - sources
        if unknown:
            raise ValueError("Unknown builder settings: " + ", ".join(sorted(unknown)))
        schema = builder_input_schema()
        for key, value in builder.items():
            if not isinstance(value, str) or len(value) > 100000:
                raise ValueError(f"builder {key} must be a string of at most 100000 characters.")
            elif key in sources and value not in REFERENCE_SOURCES:
                raise ValueError(f"Invalid reference source for {key}.")
            elif key in combos:
                if key == "planning_mode":
                    from goated_prompter.planning import planning_mode
                    planning_mode(value)
                    continue
                if key == "prompt_length" and value == "Maximum":
                    value = builder[key] = "Maximum Detail"
                if value not in schema[key][0]:
                    raise ValueError(f"Invalid builder {key}.")
        result["builder"] = builder
    return result


def validate_local_paths(values):
    for key in ("model_path", "mmproj_path", "llama_server", "models_dir", "discovery_root", "runtime_root",
                "director_model_path", "director_mmproj_path", "director_llama_server"):
        value = str(values.get(key) or "").strip()
        if value and (value.startswith(("\\\\", "//")) or "://" in value):
            raise ValueError(f"{key} must be a local filesystem path, not a URL or network share.")
        if value and str(Path(value).expanduser().resolve()).startswith(("\\\\", "//")):
            raise ValueError(f"{key} must resolve to a local filesystem path.")
