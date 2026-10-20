"""Dataset routes: Understanding, then the confirmed V2 run with the vocabulary the user enabled for it."""

import asyncio

from aiohttp import web

from .v2.draft import validate_dataset_draft
from .v2.tickets import USED
from ...presets import get_director_preset
from .v2.understanding import VERSIONS, confirm, copied_input, copied_settings, reviewed_brief
from ..vocabulary.catalog import CatalogError, catalog_for, validate_selection
from ...options.dataset import dataset_director_allowed
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


def _vocabulary(packs):
    """The run's vocabulary packs (the draft's vocabulary_packs) checked against the packs on disk now."""
    catalog = catalog_for(packs)
    try:
        return validate_selection(catalog, packs)
    except CatalogError as error:
        raise ValueError(str(error)) from None


async def confirm_endpoint(request):
    """Check and log the confirmed brief, then start the V2 run (scenes, then final prompts)."""
    state = request.app[STATE]
    payload = await json_object(request)
    required = {"brief", "settings", "input", "operation", "confirmation_token"}
    if set(payload) != required:
        raise ValueError("Expected the confirmed brief and prompt-engine settings. Rebuild the frontend if it is out of date.")
    if payload["operation"] not in ("dataset", "dataset/scenes"):
        raise ValueError("Choose Dataset generation or scenes only.")
    data = validate_dataset_draft(payload["input"], generation=True, planning=True)
    settings = _settings(payload)
    approved = state.dataset_intents.approve(payload["confirmation_token"], data)
    brief = reviewed_brief(approved, payload["brief"])
    if brief.get("version") not in VERSIONS or brief["input"] != copied_input(data) or brief["settings"] != copied_settings(data):
        raise ValueError("Dataset input changed after analysis. Review the updated request before generating.")
    brief = confirm(brief, data)
    director = get_director_preset(brief["settings"]["director"], strict=True)
    if not dataset_director_allowed(director.id):
        raise ValueError(f"{director.name} does not work in Dataset. Choose another Director preset.")
    # The user's own scene ideas (guided) use no vocabulary.
    packs = [] if data["source_mode"] == "guided" else data["vocabulary_packs"]
    vocabulary = await asyncio.to_thread(_vocabulary, packs)
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before generating again.")) is not None:
            return conflict
        # One approval starts one run: a repeated Confirm (double click, second tab) cannot start a second one.
        if not state.dataset_intents.consume(payload["confirmation_token"]):
            raise ValueError(USED)
        config = state.config()
        director_request = engine_request(
            state, config, settings,
            idea=brief["input"]["request"], mode="Custom", target_model=brief["settings"]["target"],
            creativity=brief["settings"]["creativity"], style=brief["settings"]["style"],
            capture=brief["settings"].get("capture") or "Auto",
            prompt_length=brief["settings"]["length"], director_preset=director.id,
        )
        return web.json_response(state.start_job("dataset_v2_scenes", director_request, config, True,
            {"operation": "dataset_v2_scenes", "brief": brief, "vocabulary": vocabulary,
             "scenes_only": payload["operation"] == "dataset/scenes"}), status=202)


def register(app):
    app.add_routes([web.post("/api/workspace/dataset/understand", understand_endpoint),
                    web.post("/api/workspace/dataset/v2/confirm", confirm_endpoint)])
