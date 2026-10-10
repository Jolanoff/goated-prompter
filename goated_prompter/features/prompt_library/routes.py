"""Edit the target-specific text libraries without changing their format."""

import asyncio

from aiohttp import web

from ...api.common import json_object
from ...prompt_library import LibraryConflict, library_snapshot, update_library


async def library(request):
    target = request.query.get("target", "Generic")
    if request.method == "GET":
        result = await asyncio.to_thread(library_snapshot, target)
    else:
        payload = await json_object(request)
        try:
            result = await asyncio.to_thread(
                update_library, target, payload.get("revision"),
                {"POST": "add", "PUT": "edit", "DELETE": "delete"}[request.method],
                prompt=payload.get("prompt"), index=payload.get("index"),
            )
        except LibraryConflict as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
    return web.json_response({"ok": True, **result})


def register(app):
    app.add_routes([web.route(method, "/api/prompt-library", library)
                    for method in ("GET", "POST", "PUT", "DELETE")])
