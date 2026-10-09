"""Prompt version history and Refine admission."""

import asyncio
from aiohttp import web

from ..prompting.details import PROMPT_LENGTH_NAMES
from ..prompting.target_models import TARGET_MODEL_NAMES, canonical_target
from ..workspace_store import WorkspaceConflict, locks, text
from .common import active_job_conflict, engine_request


def register(app, state_key, job_factory, json_object):
    async def workspace_endpoint(request):
        state = request.app[state_key]
        store = state.workspace
        if request.method == "GET":
            return web.json_response(await asyncio.to_thread(store.snapshot))
        payload = await json_object(request)
        async with state.admission:
            if (conflict := active_job_conflict(state, "Wait for the active generation before changing the workspace.")) is not None:
                return conflict
            try:
                current = await asyncio.to_thread(store.check, payload.get("revision"))
                action = payload.get("action")
                if request.path == "/api/workspace":
                    if action == "add":
                        target = canonical_target(payload.get("target", "Generic"))
                        if target not in TARGET_MODEL_NAMES:
                            raise ValueError("Invalid target model.")
                        parent = current["current_id"] if payload.get("edit") is True else None
                        original = next((item for item in current["versions"] if item["id"] == parent), None)
                        result = await asyncio.to_thread(store.add_version, text(payload.get("prompt"), "Prompt"), target,
                                                         "Manual edit" if parent else "Starting prompt", parent_id=parent,
                                                         detail_locks=original["locks"] if original else locks(payload.get("locks", ["identity"])),
                                                         revision=current["revision"])
                    else:
                        result = await asyncio.to_thread(store.navigate, action, current["revision"], payload.get("id"))
                    return web.json_response(result)
                operation = request.match_info["operation"]
                settings = payload.get("settings", {})
                if not isinstance(settings, dict):
                    raise ValueError("settings must be an object.")
                target, length = canonical_target(settings.get("target_model", "Generic")), settings.get("prompt_length", "Medium")
                if target not in TARGET_MODEL_NAMES or length not in PROMPT_LENGTH_NAMES:
                    raise ValueError("Invalid target model or prompt length.")
                workflow = {"operation": "refine", "locks": locks(payload.get("locks", []))}
                saved_workflow = await asyncio.to_thread(state.workflow_settings.snapshot, operation)
                workflow["instructions"] = saved_workflow["instructions"]
                version = next((item for item in current["versions"] if item["id"] == current["current_id"]), None)
                if version is None:
                    raise ValueError("Add a starting prompt before refining.")
                workflow.update(base=version["prompt"], parent_id=version["id"], changes=text(payload.get("changes"), "Requested changes", 10000))
                target = version["target"]
                if len(current["versions"]) >= 1000:
                    raise ValueError("Version history is full. Back it up and clear history before refining again.")
                config = state.config()
                director_request = engine_request(state, config, settings,
                                                  idea=workflow["base"], target_model=target, prompt_length=length)
                return web.json_response(state.start_job("refine", director_request, config, True,
                    workflow, job_factory=job_factory), status=202)
            except WorkspaceConflict as exc:
                return web.json_response({"error": str(exc)}, status=409)

    app.add_routes([web.get("/api/workspace", workspace_endpoint), web.post("/api/workspace", workspace_endpoint),
                    web.post("/api/workspace/{operation:refine}", workspace_endpoint)])
