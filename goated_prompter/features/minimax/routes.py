"""MiniMax H3 prompt admission."""

from aiohttp import web

from .contract import validate_minimax_draft
from ...api.common import STATE, active_job_conflict, engine_request, json_object


async def minimax_endpoint(request):
    state = request.app[STATE]
    payload = await json_object(request)
    if set(payload) - {"input", "settings"}:
        raise ValueError("Expected MiniMax input and prompt-engine settings.")
    data = validate_minimax_draft(payload.get("input"), generation=True)
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - {"director_profile"}:
        raise ValueError("Invalid MiniMax prompt-engine settings.")
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before generating again.")) is not None:
            return conflict
        config = state.config()
        director_request = engine_request(state, config, settings, idea=data["user_request"])
        return web.json_response(state.start_job("minimax", director_request, config, True,
            {"operation": "minimax", "input": data}), status=202)


def register(app):
    app.add_routes([web.post("/api/workspace/minimax", minimax_endpoint)])
