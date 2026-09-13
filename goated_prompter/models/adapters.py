"""Compatibility helpers for target-model adapters in prompt_catalog."""

from ..prompt_catalog import MODEL_ADAPTERS, TARGET_MODEL_NAMES


def get_model_adapter(name):
    """Return the selected adapter, falling back to Generic."""
    return MODEL_ADAPTERS.get(name, MODEL_ADAPTERS["Generic"])
