"""Pack management admission; all storage and validation belong to PackManager."""

import asyncio
import json

from aiohttp import web

from ...api.common import json_object
from ...options.vocabulary import CATALOGUE_SORTS
from .packs import MAX_ARCHIVE_BYTES, RATINGS, PackManager, VocabularyError, validate_pack_id
from .explorer import catalogue, entry_detail, inspect_retrieval, inspection_sample
from .creator import PackCreator

MANAGER = web.AppKey("vocabulary_pack_manager", PackManager)
CREATOR = web.AppKey("vocabulary_pack_creator", PackCreator)


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
            result = await asyncio.to_thread(inspect_retrieval, manager, **inspection_sample(await json_object(request)))
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


async def creator_endpoint(request):
    creator = request.app[CREATOR]
    action = request.match_info["action"]
    try:
        if request.method == "GET":
            if action == "schemas":
                result = await asyncio.to_thread(creator.schemas)
            elif action == "references":
                result = await asyncio.to_thread(creator.references)
            elif action == "drafts":
                result = await asyncio.to_thread(creator.open, request.match_info["id"]) if "id" in request.match_info else {"drafts": await asyncio.to_thread(creator.drafts)}
            elif action == "source":
                result = await asyncio.to_thread(creator.installed_document, request.match_info["id"], request.query.get("origin"))
            else:
                raise web.HTTPNotFound()
        elif action == "import":
            result = await asyncio.to_thread(creator.import_archive, await archive_bytes(request))
        else:
            try:
                payload = json.loads(await archive_bytes(request))
            except (ValueError, UnicodeError, RecursionError):
                raise ValueError("Expected valid draft JSON.") from None
            if not isinstance(payload, dict) or "document" not in payload:
                raise ValueError("Expected a draft document.")
            if action == "drafts":
                if set(payload) - {"document", "revision"}:
                    raise ValueError("Unknown draft save field.")
                result = await asyncio.to_thread(creator.save, payload["document"], request.match_info.get("id"), payload.get("revision"))
            elif action in ("validate", "preview"):
                if set(payload) - {"document", "sample"}:
                    raise ValueError("Unknown draft validation field.")
                sample = inspection_sample(payload.get("sample")) if action == "preview" else None
                if sample and ({"packs", "recorded"} & set(sample)):
                    raise ValueError("A draft preview always uses the draft and the packs it requires.")
                result = await asyncio.to_thread(creator.validate, payload["document"], sample)
            elif action == "export":
                data = await asyncio.to_thread(creator.export, payload["document"])
                return web.Response(body=data, content_type="application/zip", headers={"Content-Disposition": 'attachment; filename="vocabulary-pack.zip"'})
            elif action == "install":
                if set(payload) - {"document", "update_id", "confirmed"} or payload.get("confirmed") is not True:
                    raise ValueError("Explicit confirmation is required to install or update a pack.")
                update_id = payload.get("update_id")
                if update_id is not None:
                    validate_pack_id(update_id)
                pack = await asyncio.to_thread(creator.install, payload["document"], update_id)
                result = {"pack": pack}
            else:
                raise web.HTTPNotFound()
    except VocabularyError as error:
        return web.json_response({"ok": False, "error": str(error), "problems": error.problems}, status=400)
    except OSError:
        return web.json_response({"ok": False, "error": "Cannot access draft storage or pack files. Check permissions and retry."}, status=400)
    return web.json_response({"ok": True, **result})


def register(app):
    app[MANAGER] = PackManager()
    app[CREATOR] = PackCreator(app[MANAGER])
    app.add_routes([web.get("/api/vocabulary/creator/{action:schemas|references|drafts}", creator_endpoint),
                    web.get("/api/vocabulary/creator/{action:drafts|source}/{id}", creator_endpoint),
                    web.post("/api/vocabulary/creator/{action:drafts|import|validate|preview|export|install}", creator_endpoint),
                    web.put("/api/vocabulary/creator/{action:drafts}/{id}", creator_endpoint)])
    app.add_routes([web.get("/api/vocabulary/packs", packs_endpoint), web.post("/api/vocabulary/packs", packs_endpoint),
                    web.get("/api/vocabulary/packs/{id}/entries", explorer_endpoint),
                    web.get("/api/vocabulary/entries/{entry}", explorer_endpoint),
                    web.post("/api/vocabulary/retrieve", explorer_endpoint),
                    *[web.route(method, "/api/vocabulary/packs/{id}", packs_endpoint)
                      for method in ("PATCH", "PUT", "DELETE")]])
