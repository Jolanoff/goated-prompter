"""Saved workflow drafts and Advanced instructions."""

import asyncio
from aiohttp import web

from ..workspace_store import WorkspaceConflict
from .common import active_job_conflict


def register(app, state_key, job_factory, json_object):
    async def workflow_settings_endpoint(request):
        state = request.app[state_key]
        operation = request.match_info["operation"]

        def response(record):
            if operation == "dataset":
                data = record["draft"]
                token = state.dataset_intents.continuation_token(data)
                if not token and data["scene_plan"]:
                    retained = state.dataset_checkpoints.continuation_intent(data)
                    if retained:
                        state.dataset_intents.remember_generated(data, retained)
                        token = state.dataset_intents.continuation_token(data)
                record = {**record, "continuation_token": token}
            return web.json_response(record)

        if request.method == "GET":
            return response(await asyncio.to_thread(state.workflow_settings.snapshot, operation))
        payload = await json_object(request)
        try:
            if request.method == "PUT":
                if set(payload) != {"revision", "draft"} or not isinstance(payload["draft"], dict):
                    raise ValueError("Expected revision and workflow draft.")
                result = await asyncio.to_thread(state.workflow_settings.update, operation, payload["revision"], draft=payload["draft"])
            else:
                async with state.admission:
                    if conflict := active_job_conflict(state, "End generation before changing saved instructions."):
                        return conflict
                    action = payload.get("action")
                    if action not in ("save", "reset") or (action == "save" and not isinstance(payload.get("instructions"), dict)):
                        raise ValueError("Choose save with instructions, or reset.")
                    result = await asyncio.to_thread(state.workflow_settings.update, operation, payload.get("revision"),
                                                     instructions=payload.get("instructions"), reset=action == "reset")
            return response(result)
        except WorkspaceConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)

    app.add_routes([web.get("/api/workspace/settings/{operation:refine|minimax|dataset}", workflow_settings_endpoint),
                    web.put("/api/workspace/settings/{operation:refine|minimax|dataset}", workflow_settings_endpoint),
                    web.post("/api/workspace/settings/{operation:refine}/instructions", workflow_settings_endpoint)])
