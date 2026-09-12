"""Goated Prompter node package."""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

try:
    from .routes import register_routes

    if not register_routes():
        print(
            "[Goated Prompter] PromptServer or aiohttp unavailable at import time; "
            "Goated Prompter routes (/goated-prompter/*) were not registered."
        )
except Exception as exc:  # pragma: no cover - ComfyUI startup safety net
    print(f"[Goated Prompter] Goated Prompter route registration failed: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
