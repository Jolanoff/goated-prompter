"""Settings, model discovery and model unload endpoints."""

import asyncio

from aiohttp import web

from ...api.common import STATE, json_object
from ...backends.factory import canonical_backend_name
from ...backends.llama_cpp_process import get_process_manager
from ...director_profiles import discover_director_profiles
from ...prompt_library import library_status


async def models_payload(state, refresh=False):
    config = state.config()
    discovered = await asyncio.to_thread(discover_director_profiles, config.get("local_llama_cpp", {}), refresh)
    return {**discovered.to_public_mapping(), "ok": True,
            "backend": canonical_backend_name(config.get("backend")) or "auto"}


async def models(request):
    refresh = request.query.get("refresh", "").strip().lower() in {"1", "true", "yes"}
    return web.json_response(await models_payload(request.app[STATE], refresh))


async def settings_endpoint(request):
    state = request.app[STATE]
    if request.method == "PUT":
        payload = await json_object(request)
        async with state.admission:
            active = state.active_job()
            if active is not None and set(payload) != {"builder"}:
                return web.json_response({"ok": False, "error": "Settings cannot change while a job is active.",
                                          "active_job": active}, status=409)
            async with state.storage_lock:
                state.save_settings(payload)
    return web.json_response(await asyncio.to_thread(state.settings))


async def unload(request):
    status = await asyncio.to_thread(get_process_manager().request_unload)
    messages = {"idle": "No Goated Prompter model is currently loaded.",
                "pending": "Unload queued until the active Goated Prompter operation finishes.",
                "unloaded": "Goated Prompter model unloaded."}
    return web.json_response({"ok": True, "status": status, "message": messages[status]})



async def library(request):
    target = request.query.get("target", "Generic")
    return web.json_response({"ok": True, **await asyncio.to_thread(library_status, target)})


def register(app):
    app.add_routes([web.get("/api/library", library), web.get("/api/models", models), web.get("/api/settings", settings_endpoint),
                    web.put("/api/settings", settings_endpoint), web.post("/api/unload", unload)])
