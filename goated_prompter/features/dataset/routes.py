"""Dataset routes: Understanding, the confirmed V2 run and its recorded vocabulary packs."""

import asyncio

from aiohttp import web

from .v2.draft import validate_dataset_draft
from ...presets import get_director_preset
from .v2.runs import RunStoreError, recorded_packs
from .v2.understanding import VERSIONS, confirm, copied_input, copied_settings, reviewed_brief
from .v2.vocabulary_packs import pack_status, select_packs
from ..vocabulary.visual import validate_settings as validate_visual_settings
from ...api.common import STATE, active_job_conflict, engine_request, json_object


def _settings(payload):
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - {"director_profile"}:
        raise ValueError("Invalid Dataset prompt-engine settings.")
    return settings


async def understand_endpoint(request):
    """Start Understanding for the current draft; the brief comes back with a confirmation ticket."""
    state = request.app[STATE]
    payload = await json_object(request)
    if set(payload) - {"input", "settings", "workflow_revision"}:
        raise ValueError("Expected Dataset input and prompt-engine settings.")
    data = validate_dataset_draft(payload.get("input"), generation=True, planning=True)
    settings = _settings(payload)
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before generating again.")) is not None:
            return conflict
        config = state.config()
        director_request = engine_request(
            state, config, settings,
            idea=data["subject"], mode="Custom", target_model=data["target"],
            creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
            director_preset="general_director",
        )
        return web.json_response(state.start_job("dataset_understanding", director_request, config, True,
            {"operation": "dataset_understanding", "input": data}), status=202)


async def confirm_endpoint(request):
    """Check and log the confirmed brief, then start the V2 run (scenes, then final prompts)."""
    state = request.app[STATE]
    payload = await json_object(request)
    required = {"brief", "settings", "input", "operation", "confirmation_token", "vocabulary_packs"}
    if not required <= set(payload) or set(payload) - required - {"visual_direction"}:
        raise ValueError("Expected the confirmed brief, prompt-engine settings and vocabulary packs. Rebuild the frontend if it is out of date.")
    # Per-dimension Visual Direction settings for this run (vocabulary/visual.py); absent: the defaults.
    visual = validate_visual_settings(payload.get("visual_direction"))
    if payload["operation"] not in ("dataset", "dataset/scenes"):
        raise ValueError("Choose Dataset generation or scenes only.")
    data = validate_dataset_draft(payload["input"], generation=True, planning=True)
    settings = _settings(payload)
    approved = state.dataset_intents.approve(payload["confirmation_token"], data)
    # Only the structured intent may differ from what was analyzed, and only by allowed corrections (v2/intent.py).
    brief = reviewed_brief(approved, payload["brief"])
    if brief.get("version") not in VERSIONS or brief["input"] != copied_input(data) or brief["settings"] != copied_settings(data):
        raise ValueError("Dataset input changed after analysis. Review the updated request before generating.")
    brief = confirm(brief, data)
    director = get_director_preset(brief["settings"]["director"], strict=True)
    # The run's own pack selection, resolved and fingerprinted now, before any inference (v2/vocabulary_packs.py).
    packs = await asyncio.to_thread(select_packs, state.config(), payload["vocabulary_packs"])
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before generating again.")) is not None:
            return conflict
        config = state.config()
        director_request = engine_request(
            state, config, settings,
            idea=brief["input"]["request"], mode="Custom", target_model=brief["settings"]["target"],
            creativity=brief["settings"]["creativity"], style=brief["settings"]["style"],
            prompt_length=brief["settings"]["length"], director_preset=director.id,
        )
        return web.json_response(state.start_job("dataset_v2_scenes", director_request, config, True,
            {"operation": "dataset_v2_scenes", "brief": brief, "vocabulary_packs": packs, "visual_direction": visual,
             "scenes_only": payload["operation"] == "dataset/scenes"}), status=202)


async def run_packs_endpoint(request):
    """A stored V2 run's recorded pack selection and how the packs on disk compare with it (read-only)."""
    state = request.app[STATE]
    try:
        record = await asyncio.to_thread(state.dataset_runs.get, request.match_info["run_id"])
    except RunStoreError as error:
        return web.json_response({"ok": False, "error": str(error)}, status=404)
    packs = recorded_packs(record)
    status = await asyncio.to_thread(pack_status, packs) if packs.get("recorded", True) else None
    return web.json_response({"ok": True, "run_id": record["run_id"], "schema": record["schema"], "packs": packs, "status": status})


def register(app):
    app.add_routes([web.get("/api/workspace/dataset/v2/runs/{run_id}/packs", run_packs_endpoint),
                    web.post("/api/workspace/dataset/understand", understand_endpoint),
                    web.post("/api/workspace/dataset/v2/confirm", confirm_endpoint)])
