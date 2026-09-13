"""Compatibility helpers for prompt-task adapters in prompt_catalog."""

from ..prompt_catalog import DEFAULT_VISION_ADAPTER, MODE_ADAPTERS, MODE_NAMES, VISION_MODE_ADAPTERS


def get_mode_adapter(name):
    """Return the selected adapter, falling back conservatively to Enhance."""
    return MODE_ADAPTERS.get(name, MODE_ADAPTERS["Enhance"])


def get_vision_mode_adapter(name):
    """Return general visual grounding plus any mode-specific constraints."""
    specific = VISION_MODE_ADAPTERS.get(name)
    return f"{DEFAULT_VISION_ADAPTER}\n\n{specific}" if specific else DEFAULT_VISION_ADAPTER
