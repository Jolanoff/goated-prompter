"""Instruction preset library endpoints."""

import asyncio

from aiohttp import web

from ...api.common import STATE, json_object
from ...presets import (
    DEFAULT_DIRECTOR_PRESET, MODE_DIRECTOR_RECOMMENDATIONS, delete_user_director, list_director_presets,
    reset_director, resolve_user_director_directory, save_user_director, update_director,
)


async def presets_payload():
    presets, warnings = await asyncio.to_thread(list_director_presets)
    preset_ids = {preset["label"]: preset["id"] for preset in presets}
    return {"ok": True, "default": DEFAULT_DIRECTOR_PRESET, "presets": presets,
            "mode_directors": {mode: preset_ids[label]
                               for mode, label in MODE_DIRECTOR_RECOMMENDATIONS.items()},
            "warnings": warnings, "storage": str(resolve_user_director_directory())}


async def presets(request):
    if request.method == "GET":
        return web.json_response(await presets_payload())
    payload = await json_object(request)
    state = request.app[STATE]
    async with state.admission:
        active = state.active_job()
        if active is not None:
            return web.json_response({"ok": False, "error": "Directors cannot change while a job is active.",
                                      "active_job": active}, status=409)
        async with state.storage_lock:
            if request.path == "/api/presets/reset":
                director, path = reset_director(payload.get("id"))
            elif request.method == "PUT":
                director, path = update_director(payload.get("id"), payload.get("name"), payload.get("instructions"))
            elif request.method == "POST":
                director, path = save_user_director(payload.get("name"), payload.get("instructions"),
                                                    payload.get("recommended_mode", "Custom"))
            else:
                director, path = delete_user_director(payload.get("id") or payload.get("name"))
    return web.json_response({"ok": True, "director": director.to_public_mapping(), "file": path.name})



def register(app):
    app.add_routes([web.get("/api/presets", presets), web.post("/api/presets", presets),
                    web.delete("/api/presets", presets), web.put("/api/presets", presets),
                    web.post("/api/presets/reset", presets)])
