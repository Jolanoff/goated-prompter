"""Pack management admission; all storage and validation belong to PackManager."""

import asyncio

from aiohttp import web

from ...api.common import json_object
from ...options.vocabulary import CATALOGUE_SORTS
from .packs import MAX_ARCHIVE_BYTES, RATINGS, PackManager, VocabularyError, validate_pack_id
from .explorer import catalogue, entry_detail, inspect_retrieval

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


async def explorer_endpoint(request):
    manager = request.app[MANAGER]
    try:
        if request.method == "POST":
            payload = await json_object(request)
            if set(payload) - {"request", "nsfw", "characters"}:
                raise ValueError("Expected a sample request, NSFW rating filter and optional character descriptions.")
            text, nsfw, characters = payload.get("request", ""), payload.get("nsfw", False), payload.get("characters", [])
            if not isinstance(text, str) or not text.strip() or len(text) > 4000 or type(nsfw) is not bool:
                raise ValueError("Enter a sample request of 1–4000 characters and a boolean NSFW rating filter.")
            if not isinstance(characters, list) or len(characters) > 16 or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 512 for item in characters):
                raise ValueError("Use up to 16 character descriptions of 1–512 characters each.")
            result = await asyncio.to_thread(inspect_retrieval, manager, text, nsfw=nsfw, characters=characters)
        else:
            params = request.query
            if "entry" in request.match_info:
                if set(params) - {"origin"}:
                    raise ValueError("Unknown entry inspection parameter.")
                result = await asyncio.to_thread(entry_detail, manager, request.match_info["entry"], origin=params.get("origin"))
            else:
                if set(params) - {"origin", "q", "category", "rating", "sort"} or len(params.get("q", "")) > 200:
                    raise ValueError("Invalid catalogue filter.")
                if params.get("sort", "name") not in CATALOGUE_SORTS or params.get("rating", "") not in ("", *RATINGS):
                    raise ValueError("Unknown sort order or rating.")
                result = await asyncio.to_thread(catalogue, manager, request.match_info["id"], origin=params.get("origin"),
                    query=params.get("q", ""), category=params.get("category", ""), rating=params.get("rating", ""), sort=params.get("sort", "name"))
    except VocabularyError as error:
        return web.json_response({"ok": False, "error": str(error), "problems": error.problems}, status=400)
    except OSError:
        return web.json_response({"ok": False, "error": "Cannot read vocabulary packs. Check folder permissions and retry."}, status=400)
    return web.json_response({"ok": True, **result})


def register(app):
    app[MANAGER] = PackManager()
    app.add_routes([web.get("/api/vocabulary/packs", packs_endpoint), web.post("/api/vocabulary/packs", packs_endpoint),
                    web.get("/api/vocabulary/packs/{id}/entries", explorer_endpoint),
                    web.get("/api/vocabulary/entries/{entry}", explorer_endpoint),
                    web.post("/api/vocabulary/retrieve", explorer_endpoint),
                    *[web.route(method, "/api/vocabulary/packs/{id}", packs_endpoint)
                      for method in ("PATCH", "PUT", "DELETE")]])
