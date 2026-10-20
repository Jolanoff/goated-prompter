"""Caption admission and a native folder chooser on the app's computer."""

import asyncio

from aiohttp import web

from ...api.common import STATE, active_job_conflict, engine_request, json_object
from .contract import caption_images, validate_caption_input


def choose_folder():
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        raise ValueError("Folder chooser is unavailable. Paste the folder path instead.") from exc
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        raise ValueError("Folder chooser is unavailable. Paste the folder path instead.") from exc
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        return filedialog.askdirectory(parent=root, title="Choose images to caption", mustexist=True)
    finally:
        root.destroy()


async def folder_endpoint(request):
    return web.json_response({"folder": await asyncio.to_thread(choose_folder)})


async def caption_endpoint(request):
    state = request.app[STATE]
    payload = await json_object(request)
    if set(payload) - {"input", "settings"}:
        raise ValueError("Expected Caption input and engine settings.")
    data = validate_caption_input(payload.get("input"))
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - {"director_profile"}:
        raise ValueError("Invalid Caption engine settings.")
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before captioning.")) is not None:
            return conflict
        await asyncio.to_thread(caption_images, data["folder"])
        config = state.config()
        director_request = engine_request(state, config, settings, idea=data["description"])
        return web.json_response(state.start_job("caption", director_request, config, False,
            {"operation": "caption", "input": data}), status=202)


def register(app):
    app.add_routes([web.post("/api/workspace/caption", caption_endpoint),
                    web.post("/api/caption/folder", folder_endpoint)])
