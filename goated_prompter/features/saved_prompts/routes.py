"""Saved prompt collection endpoints."""

from aiohttp import web

from ...api.common import STATE, json_object
from ...json_store import atomic_json, read_store
from .store import validate_prompts


async def prompts_endpoint(request):
    state = request.app[STATE]
    incoming = None
    if request.method == "POST":
        payload = await json_object(request)
        if request.path != "/api/prompts/import":
            payload = {"prompts": [payload]}
        # Conflicting IDs within an import are conflicts, not partial successes.
        try:
            incoming = validate_prompts(payload)["prompts"]
        except ValueError as exc:
            if str(exc).startswith("Conflicting saved prompt id:"):
                raise web.HTTPConflict(reason=str(exc)) from exc
            raise
    async with state.storage_lock:
        current = read_store(state.prompts_path, {"prompts": []}, validate_prompts)
        records = {record["id"]: record for record in current["prompts"]}
        if incoming is not None:
            for record in incoming:
                if record["id"] in records and records[record["id"]] != record:
                    raise web.HTTPConflict(reason=f"Conflicting saved prompt id: {record['id']}")
                records[record["id"]] = record
        elif request.method == "DELETE":
            records.pop(request.match_info["id"], None)
        snapshot = validate_prompts({"prompts": list(records.values())})
        if snapshot != current:
            atomic_json(state.prompts_path, snapshot)
        return web.json_response(snapshot)



def register(app):
    app.add_routes([web.get("/api/prompts", prompts_endpoint), web.post("/api/prompts", prompts_endpoint),
                    web.post("/api/prompts/import", prompts_endpoint), web.delete("/api/prompts/{id}", prompts_endpoint)])
