"""Dataset understanding, scene planning, per-scene and batch prompt admission."""

from aiohttp import web

from .service import validate_dataset_draft
from .assignments import dataset_assignments
from .intent import intent_signature
from ...presets import get_director_preset
from .plan import reusable_scene_plan, scene_is_usable, scene_unusable_reason
from ...api.common import STATE, active_job_conflict, engine_request, json_object


async def dataset_endpoint(request):
    state = request.app[STATE]
    payload = await json_object(request)
    local_scene = request.path.endswith("/scene")
    understanding = request.path.endswith("/understand")
    if set(payload) - ({"input", "settings", "workflow_revision"} if understanding else
                       {"input", "settings", "action", "index", "workflow_revision", "confirmation_token"} if local_scene else
                        {"input", "settings", "valid_only", "resume", "workflow_revision", "confirmation_token"}):
        raise ValueError("Expected Dataset input and prompt-engine settings.")
    scenes_only = request.path.endswith("/scenes")
    valid_only = payload.get("valid_only", False)
    if type(valid_only) is not bool or (valid_only and scenes_only):
        raise ValueError("Valid-scenes-only generation must be a boolean for prompt generation.")
    resume = payload.get("resume", False)
    if type(resume) is not bool or (resume and (scenes_only or local_scene or understanding)):
        raise ValueError("Continue must be a boolean for batch prompt generation.")
    if resume and not valid_only:
        raise ValueError("Continue requires valid-scenes-only generation from the saved plan.")
    data = validate_dataset_draft(payload.get("input"), generation=True, planning=scenes_only or understanding)
    if valid_only:
        rows = reusable_scene_plan(data, dataset_assignments(data), require_scenes=False, allow_pending=True)
        if rows is None or not any(scene_is_usable(row, data) for row in rows):
            raise ValueError("No valid scenes are available in the current saved plan.")
    scene_action = None
    if local_scene:
        action, index = payload.get("action"), payload.get("index")
        if (not isinstance(action, str) or action not in {"regenerate_idea", "repair_scene", "regenerate_prompt"}
                or type(index) is not int or not 1 <= index <= data["amount"]):
            raise ValueError("Choose a valid scene index and regenerate_idea, repair_scene or regenerate_prompt.")
        rows = reusable_scene_plan(data, dataset_assignments(data), require_scenes=False, allow_pending=True)
        if rows is None:
            raise ValueError("Per-scene actions require a current saved idea plan.")
        if action == "repair_scene" and not rows[index - 1].get("idea", "").strip():
            raise ValueError("Generate an idea for this item before repairing its scene.")
        if action == "regenerate_prompt" and (reason := scene_unusable_reason(rows[index - 1], data)):
            raise ValueError(reason)
        scene_action = (action, index)
    settings = payload.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - {"director_profile"}:
        raise ValueError("Invalid Dataset prompt-engine settings.")
    director = None if scenes_only or understanding else get_director_preset(data["director_preset"], strict=True)
    async with state.admission:
        if (conflict := active_job_conflict(state, "Wait for the active generation before generating again.")) is not None:
            return conflict
        if understanding:
            intent = None
        elif resume:
            saved = state.workflow_settings.snapshot("dataset")["draft"]
            if intent_signature(data) != intent_signature(saved):
                raise ValueError("Continue requires the current saved scene plan. Save your changes before continuing.")
            retained = state.dataset_checkpoints.continuation_intent(data)
            if retained is None:
                raise ValueError("No matching saved scene checkpoint is available. Use Generate scenes in Configure to start a new plan.")
            intent = (state.dataset_intents.approve(payload["confirmation_token"], data)
                      if payload.get("confirmation_token") else retained or None)
        else:
            intent = state.dataset_intents.approve(payload.get("confirmation_token"), data)
        config = state.config()
        director_request = engine_request(
            state, config, settings,
            idea=data["subject"], mode="Custom", target_model=data["target"],
            creativity=data["creativity"], prompt_length=data["length"],
            director_preset=director.id if director else "general_director",
        )
        kind = "dataset_understanding" if understanding else "dataset_scenes" if scenes_only else "dataset"
        return web.json_response(state.start_job(kind, director_request, config, True,
            {"operation": kind, "input": data, "intent": intent, "scene_action": scene_action, "valid_only": valid_only, "resume": resume,
             "workflow_revision": payload.get("workflow_revision")}), status=202)


def register(app):
    app.add_routes([web.post("/api/workspace/dataset", dataset_endpoint),
                    web.post("/api/workspace/dataset/understand", dataset_endpoint),
                    web.post("/api/workspace/dataset/scenes", dataset_endpoint),
                    web.post("/api/workspace/dataset/scene", dataset_endpoint)])
