"""Portable, feature-local configuration loading."""

import json
import os
from pathlib import Path

from .backends.base import BackendConfigurationError

CONFIG_ENV_VAR = "GOATED_PROMPTER_CONFIG"
# Keep persisted configuration and Directors in their original location.
LEGACY_DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "nodes" / "goated_prompter"
DEFAULT_CONFIG_PATH = LEGACY_DATA_DIRECTORY / "config.json"


def _user_config_path():
    """Return the Goated Prompter-owned ComfyUI user config location when available."""
    try:
        import folder_paths

        getter = getattr(folder_paths, "get_user_directory", None)
        if callable(getter):
            return Path(getter()).resolve() / "GoatedPrompter" / "config.json"
    except (ImportError, AttributeError, OSError):
        pass
    return None


def resolve_config_path():
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    user_path = _user_config_path()
    if user_path is not None and user_path.is_file():
        return user_path
    return DEFAULT_CONFIG_PATH


def load_config(path=None):
    config_path = Path(path).expanduser() if path is not None else resolve_config_path()
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackendConfigurationError(f"Goated Prompter config could not be read: {config_path.name}") from exc
    if not isinstance(data, dict):
        raise BackendConfigurationError("Goated Prompter config root must be a JSON object.")
    return data
