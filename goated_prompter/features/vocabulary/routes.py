"""Vocabulary route: the Core categories and every pack in their folders, read fresh from disk on each request."""

import asyncio

from aiohttp import web

from .catalog import load_catalog


async def catalog_endpoint(request):
    try:
        catalog = await asyncio.to_thread(load_catalog)
    except (OSError, ValueError) as error:  # only Core itself can fail the whole catalog
        return web.json_response({"ok": False, "error": f"Vocabulary Core could not be read: {error}"}, status=500)
    return web.json_response({"ok": True, **catalog})


def register(app):
    app.add_routes([web.get("/api/vocabulary/catalog", catalog_endpoint)])
