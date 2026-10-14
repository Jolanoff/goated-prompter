"""Pack management admission; all storage and validation belong to PackManager."""

import asyncio

from aiohttp import web

from ...api.common import json_object
from .packs import MAX_ARCHIVE_BYTES, PackManager, VocabularyError, validate_pack_id

MANAGER = web.AppKey("vocabulary_pack_manager", PackManager)


def snapshot(manager):
    packs = manager.discover()
    try:
        manager.registry()
        problems = []
    except (VocabularyError, OSError) as error:
        problems = getattr(error, "problems", [str(error)])
    return {"ok": True, "packs": packs, "problems": problems, "max_archive_bytes": MAX_ARCHIVE_BYTES}


async def archive_bytes(request):
    if request.content_length is not None and request.content_length > MAX_ARCHIVE_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_ARCHIVE_BYTES, actual_size=request.content_length)
    data = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_ARCHIVE_BYTES, actual_size=len(data))
    return bytes(data)


async def packs_endpoint(request):
    manager = request.app[MANAGER]
    try:
        if request.method == "POST":
            await asyncio.to_thread(manager.install_archive, await archive_bytes(request))
        elif request.method != "GET":
            pack_id = validate_pack_id(request.match_info["id"])
            if request.method == "PATCH":
                payload = await json_object(request)
                if set(payload) != {"enabled"} or type(payload["enabled"]) is not bool:
                    raise ValueError("Expected enabled: true or false.")
                await asyncio.to_thread(manager.set_enabled, pack_id, payload["enabled"])
            elif request.method == "PUT":
                await asyncio.to_thread(manager.install_archive, await archive_bytes(request), replace=True, expected_id=pack_id)
            elif request.method == "DELETE":
                await asyncio.to_thread(manager.remove, pack_id)
        result = await asyncio.to_thread(snapshot, manager)
    except VocabularyError as error:
        return web.json_response({"ok": False, "error": str(error), "problems": error.problems}, status=400)
    except OSError:
        return web.json_response({"ok": False, "error": "Cannot access vocabulary packs. Check folder permissions and retry."}, status=400)
    return web.json_response(result)


def register(app):
    app[MANAGER] = PackManager()
    app.add_routes([web.get("/api/vocabulary/packs", packs_endpoint), web.post("/api/vocabulary/packs", packs_endpoint),
                    *[web.route(method, "/api/vocabulary/packs/{id}", packs_endpoint)
                      for method in ("PATCH", "PUT", "DELETE")]])
