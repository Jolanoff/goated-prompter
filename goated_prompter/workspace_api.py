"""Dedicated HTTP workflows; uses the application's shared job admission/cancellation."""

import asyncio
from aiohttp import web

from .backends.factory import canonical_backend_name
from .core import GoatedPrompterRequest, _as_bool
from .prompting.details import PROMPT_LENGTH_NAMES
from .prompting.target_models import TARGET_MODEL_NAMES, canonical_target
from .refinement import RefineService
from .workspace_store import WorkspaceConflict, locks, text
from .minimax import MiniMaxService, validate_minimax_draft
from .dataset import DatasetService, validate_dataset_draft
from .dataset_assignments import dataset_assignments
from .dataset_intent import intent_signature
from .dataset_understanding import DatasetUnderstandingService
from .presets import get_director_preset
from .scene_planner import reusable_scene_plan, scene_is_usable, scene_unusable_reason


def register_workspace_routes(app, state_key, job_factory, json_object):
    async def dataset_endpoint(request):
        state = request.app[state_key]
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
            active = state.active_job()
            if active:
                return web.json_response({"error": "Wait for the active generation before generating again.",
                                          "active_job": active}, status=409)
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
            configured = canonical_backend_name(config.get("backend")) in {"mock", "openai_compatible"}
            director_request = GoatedPrompterRequest(
                idea=data["subject"], mode="Custom", target_model=data["target"],
                creativity=data["creativity"],
                prompt_length=data["length"], prompt_model="Custom",
                director_preset=director.id if director else "general_director",
                director_profile="" if configured else text(
                    settings.get("director_profile", state.saved_settings.get("selected_profile", "")),
                    "Prompt engine", 512, optional=True),
                director_keep_model_loaded=_as_bool(
                    config.get("local_llama_cpp", {}).get("keep_model_loaded", False)),
            )
            kind = "dataset_understanding" if understanding else "dataset_scenes" if scenes_only else "dataset"
            return web.json_response(state.start_job(kind, director_request, config, True,
                {"operation": kind, "input": data, "intent": intent, "scene_action": scene_action, "valid_only": valid_only, "resume": resume,
                 "workflow_revision": payload.get("workflow_revision")},
                job_factory=job_factory), status=202)

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
            active = state.active_job()
            if active:
                return web.json_response({"error": "Wait for the active generation before generating again.", "active_job": active}, status=409)
            config = state.config()
            configured = canonical_backend_name(config.get("backend")) in {"mock", "openai_compatible"}
            director_request = GoatedPrompterRequest(
                idea=data["user_request"], prompt_model="Custom",
                director_profile="" if configured else text(settings.get("director_profile", state.saved_settings.get("selected_profile", "")), "Prompt engine", 512, optional=True),
                director_keep_model_loaded=_as_bool(config.get("local_llama_cpp", {}).get("keep_model_loaded", False)),
            )
            return web.json_response(state.start_job("minimax", director_request, config, True,
                {"operation": "minimax", "input": data}, job_factory=job_factory), status=202)

    async def endpoint(request):
        state = request.app[state_key]
        store = state.workspace
        if request.method == "GET":
            return web.json_response(await asyncio.to_thread(store.snapshot))
        payload = await json_object(request)
        async with state.admission:
            active = state.active_job()
            if active:
                return web.json_response({"error": "Wait for the active generation before changing the workspace.", "active_job": active}, status=409)
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
                configured = canonical_backend_name(config.get("backend")) in {"mock", "openai_compatible"}
                director_request = GoatedPrompterRequest(
                    idea=workflow["base"], target_model=target, prompt_length=length, prompt_model="Custom",
                    director_profile="" if configured else text(settings.get("director_profile", state.saved_settings.get("selected_profile", "")), "Prompt engine", 512, optional=True),
                    director_keep_model_loaded=_as_bool(config.get("local_llama_cpp", {}).get("keep_model_loaded", False)),
                )
                return web.json_response(state.start_job("refine", director_request, config, True,
                    workflow, job_factory=job_factory), status=202)
            except WorkspaceConflict as exc:
                return web.json_response({"error": str(exc)}, status=409)

    async def settings_endpoint(request):
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
                    if state.active_job():
                        return web.json_response({"error": "End generation before changing saved instructions.", "active_job": state.active_job()}, status=409)
                    action = payload.get("action")
                    if action not in ("save", "reset") or (action == "save" and not isinstance(payload.get("instructions"), dict)):
                        raise ValueError("Choose save with instructions, or reset.")
                    result = await asyncio.to_thread(state.workflow_settings.update, operation, payload.get("revision"),
                                                     instructions=payload.get("instructions"), reset=action == "reset")
            return response(result)
        except WorkspaceConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)

    app.add_routes([web.post("/api/workspace/minimax", minimax_endpoint),
                    web.post("/api/workspace/dataset", dataset_endpoint),
                    web.post("/api/workspace/dataset/understand", dataset_endpoint),
                    web.post("/api/workspace/dataset/scenes", dataset_endpoint),
                    web.post("/api/workspace/dataset/scene", dataset_endpoint),
                    web.get("/api/workspace/settings/{operation:refine|minimax|dataset}", settings_endpoint),
                    web.put("/api/workspace/settings/{operation:refine|minimax|dataset}", settings_endpoint),
                    web.post("/api/workspace/settings/{operation:refine}/instructions", settings_endpoint),
                    web.get("/api/workspace", endpoint), web.post("/api/workspace", endpoint),
                    web.post("/api/workspace/{operation:refine}", endpoint)])


def execute_workflow(state, job, request, config, workflow):
    def persist(prompt, operation):
        try:
            return operation()
        except (ValueError, OSError) as exc:
            # Preserve expensive model output even when the disk cannot accept it.
            with job.lock:
                job.result = {"recovery_prompt": prompt, "target": request.target_model}
            raise ValueError(f"The prompt was generated, but saving failed. Copy the recovered result before leaving this page. {exc}") from exc

    def progress(message):
        job.set_progress(message)

    if workflow["operation"] == "minimax":
        result = MiniMaxService(config, job.checkpoint).run(request, workflow["input"], progress)
        job.commit(lambda: result, finish=True)
        return

    if workflow["operation"] == "dataset_understanding":
        brief = DatasetUnderstandingService(config, job.checkpoint).run(request, workflow["input"], progress)
        job.commit(lambda: {"ok": True, "kind": "dataset_understanding",
                           **state.dataset_intents.register(workflow["input"], brief)}, finish=True)
        return

    if workflow["operation"] in {"dataset", "dataset_scenes"}:
        def checkpoint_result(snapshot=None):
            try:
                state.workflow_settings.checkpoint_dataset(job, snapshot=snapshot,
                                                            approved_intent=workflow.get("intent"))
            except (ValueError, OSError) as exc:
                raise ValueError(f"Dataset progress could not be saved. Earlier durable checkpoints remain intact; copy unsaved output from this job's diagnostics before leaving. {exc}") from exc
        def durable_result(result):
            snapshot = job.snapshot()
            snapshot["result"] = result
            try:
                checkpoint_result(snapshot)
                if workflow.get("intent") and result.get("scene_plan"):
                    generated = {**workflow["input"], "scene_plan": result["scene_plan"],
                                 "scene_plan_signature": result["scene_plan_signature"]}
                    state.dataset_intents.remember_generated(generated, workflow["intent"])
            finally:
                # Retain completed chunks for recovery even if persistence/cancellation fails.
                with job.lock:
                    job.result = result
            return result
        def partial(result):
            def publish():
                # Disk owns progress before it becomes available to a browser poll.
                durable_result(result)
                with job.lock:
                    job.record_event(
                        (f"Dataset prompt {result['completed']}/{result['total']} completed and is available."
                         if result["completed"] else "Dataset planning stages saved; final prompts have not started."
                         if any(row.get("scene_status") == "not_generated" for row in result["scene_plan"])
                         else "Dataset scene plan is ready and available before prompt writing."),
                        "result",
                        revise=False,
                    )
                    job.revision += 1
            job.commit(publish)
        result = DatasetService(config, job.checkpoint, idea_history=state.idea_history).run(
            request, {**workflow["input"], "_confirmed_intent": workflow.get("intent")}, progress, partial,
            scenes_only=workflow["operation"] == "dataset_scenes", scene_action=workflow.get("scene_action"),
            valid_only=workflow.get("valid_only", False), resume=workflow.get("resume", False))
        job.commit(lambda: durable_result(result), finish=True)
        return

    service = RefineService(config, job.checkpoint)
    result = service.run(request, workflow, progress)
    def finish():
        snapshot = persist(result["prompt"], lambda: state.workspace.add_version(
            result["prompt"], request.target_model, "Refinement", parent_id=workflow["parent_id"],
            instruction=workflow["changes"], detail_locks=workflow["locks"]))
        result["version_id"] = snapshot["current_id"]
        return result
    job.commit(finish, finish=True)
