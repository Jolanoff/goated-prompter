"""Prompt Builder generation admission."""

import asyncio
from dataclasses import replace

from aiohttp import web

from ...api.common import STATE, json_object
from ...contracts import GoatedPrompterRequest, as_bool
from ...presets import DEFAULT_DIRECTOR_PRESET, fold_replaced_director, get_director_preset
from ...uploaded_images import decode_image
from ..settings.validation import validate_local_paths


_SERVER_ONLY_SETTINGS = frozenset({"director_model_path", "director_mmproj_path", "director_llama_server"})


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
    # Executable and model locations come from config or model discovery, never from the request body.
    forbidden = sorted(_SERVER_ONLY_SETTINGS & settings.keys())
    if forbidden:
        raise ValueError("These settings can only be configured on the server: " + ", ".join(forbidden) + ".")
    async with state.admission:
        active_job = state.active_job()
        if active_job is not None:
            return web.json_response({"ok": False,
                                      "error": "A job is active. Resume it or wait for completion before generating again.",
                                      "active_job": active_job}, status=409)
        settings = fold_replaced_director(settings)
        director = get_director_preset(settings.get("director_preset", DEFAULT_DIRECTOR_PRESET), strict=True)
        settings = {**settings, "director_preset": director.id,
                    "mode": settings.get("mode") or director.recommended_mode or "Custom",
                    "system_prompt_override": ""}
        validate_local_paths(settings)
        config = state.config()
        director_request = replace(GoatedPrompterRequest.from_mapping(settings),
                                   linked_references=as_bool(settings.get("linked_references", False)))
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
        return web.json_response(state.start_job("builder", director_request, config, text_only), status=202)



def register(app):
    app.add_routes([web.post("/api/generate", generate)])
