"""Vocabulary routes: the catalog (Core categories and every pack, read fresh from disk on each request) and pack
import into data/vocabulary/<category folder>/."""

import asyncio

from aiohttp import web

from .catalog import import_pack, load_catalog


async def catalog_endpoint(request):
    try:
        catalog = await asyncio.to_thread(load_catalog)
    except (OSError, ValueError) as error:  # only Core itself can fail the whole catalog
        return web.json_response({"ok": False, "error": f"Vocabulary Core could not be read: {error}"}, status=500)
    return web.json_response({"ok": True, **catalog})


async def import_endpoint(request):
    """Body {"filename", "content"}: one pack file's name and text. Saves it in its category's data folder."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("content"), str):
        return web.json_response({"ok": False, "error": 'Send {"filename", "content"} with the pack file\'s text.'},
                                 status=400)
    try:
        pack = await asyncio.to_thread(import_pack, body.get("filename") or "", body["content"])
    except (OSError, ValueError) as error:
        return web.json_response({"ok": False, "error": f"Could not import {body.get('filename') or 'the pack'}: {error}"},
                                 status=400)
    return web.json_response({"ok": True, "pack": pack})


def register(app):
    app.add_routes([web.get("/api/vocabulary/catalog", catalog_endpoint),
                    web.post("/api/vocabulary/import", import_endpoint)])
