"""MiniMax H3 prompt admission."""

from aiohttp import web

from ..minimax import validate_minimax_draft
from .common import active_job_conflict, engine_request


def register(app, state_key, job_factory, json_object):
    async def minimax_endpoint(request):
        state = request.app[state_key]
        payload = await json_object(request)
        if set(payload) - {"input", "settings"}:
            raise ValueError("Expected MiniMax input and prompt-engine settings.")
        data = validate_minimax_draft(payload.get("input"), generation=True)
        settings = payload.get("settings", {})
        if not isinstance(settings, dict) or set(settings) - {"director_profile"}:
            raise ValueError("Invalid MiniMax prompt-engine settings.")
        async with state.admission:
            if conflict := active_job_conflict(state, "Wait for the active generation before generating again."):
                return conflict
            config = state.config()
            director_request = engine_request(state, config, settings, idea=data["user_request"])
            return web.json_response(state.start_job("minimax", director_request, config, True,
                {"operation": "minimax", "input": data}, job_factory=job_factory), status=202)

    app.add_routes([web.post("/api/workspace/minimax", minimax_endpoint)])
