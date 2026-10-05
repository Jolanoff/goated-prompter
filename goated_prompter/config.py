"""Portable, feature-local configuration loading."""

import json
import os
from pathlib import Path

from .backends.base import BackendConfigurationError

CONFIG_ENV_VAR = "GOATED_PROMPTER_CONFIG"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"


def resolve_config_path():
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
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
