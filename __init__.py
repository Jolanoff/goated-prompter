"""Goated Prompter for ComfyUI."""

from .goated_prompter.comfy_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./comfyui_web"

try:
    from .goated_prompter.comfy_routes import register_routes

    if not register_routes():
        print(
            "[Goated Prompter] PromptServer or aiohttp unavailable at import time; "
            "Goated Prompter routes (/goated-prompter/*) were not registered."
        )
except Exception as exc:  # pragma: no cover - ComfyUI startup safety net
    print(f"[Goated Prompter] Goated Prompter route registration failed: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
