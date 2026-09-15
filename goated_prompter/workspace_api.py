"""Dedicated HTTP workflows; uses the application's shared job admission/cancellation."""

import asyncio
import uuid

from aiohttp import web

from .core import GoatedPrompterRequest, _as_bool
from .prompt_catalog import PROMPT_LENGTH_NAMES, TARGET_MODEL_NAMES
from .prompt_workflows import PromptWorkflowService
from .workspace_store import WorkspaceConflict, locks, now, text


def register_workspace_routes(app, state_key, job_factory, json_object):
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
                        target = payload.get("target", "Generic")
                        if target not in TARGET_MODEL_NAMES:
                            raise ValueError("Invalid target model.")
                        parent = current["current_id"] if payload.get("edit") is True else None
                        original = next((item for item in current["versions"] if item["id"] == parent), None)
                        result = await asyncio.to_thread(store.add_version, text(payload.get("prompt"), "Prompt"), target,
                                                         "Manual edit" if parent else "Starting prompt", parent_id=parent,
                                                         detail_locks=original["locks"] if original else locks(payload.get("locks", ["identity"])),
                                                         revision=current["revision"])
                    elif action == "delete_comparison":
                        result = await asyncio.to_thread(store.delete_comparison, text(payload.get("id"), "Comparison id", 128), current["revision"])
                    else:
                        result = await asyncio.to_thread(store.navigate, action, current["revision"], payload.get("id"))
                    return web.json_response(result)
                operation = request.match_info["operation"]
                settings = payload.get("settings", {})
                if not isinstance(settings, dict):
                    raise ValueError("settings must be an object.")
                target, length = settings.get("target_model", "Generic"), settings.get("prompt_length", "Medium")
                if target not in TARGET_MODEL_NAMES or length not in PROMPT_LENGTH_NAMES:
                    raise ValueError("Invalid target model or prompt length.")
                workflow = {"operation": operation, "locks": locks(payload.get("locks", []))}
                if operation == "refine":
                    version = next((item for item in current["versions"] if item["id"] == current["current_id"]), None)
                    if version is None:
                        raise ValueError("Add a starting prompt before refining.")
                    workflow.update(base=version["prompt"], parent_id=version["id"], changes=text(payload.get("changes"), "Requested changes", 10000))
                    target = version["target"]
                else:
                    if len(current["comparisons"]) >= 100:
                        raise ValueError("Remove an older comparison before exploring again (100 comparison limit).")
                    workflow["base"] = text(payload.get("base"), "Starting idea or prompt")
                    workflow["batch"] = {"id": uuid.uuid4().hex, "base": workflow["base"], "target": target,
                                         "locks": workflow["locks"], "created_at": now(), "results": []}
                if operation == "refine" and len(current["versions"]) >= 1000:
                    raise ValueError("Version history is full. Back it up and clear history before refining again.")
                config = state.config()
                configured = config.get("backend") in {"mock", "openai_compatible"}
                director_request = GoatedPrompterRequest(
                    idea=workflow["base"], target_model=target, prompt_length=length, prompt_model="Custom",
                    director_profile="" if configured else text(settings.get("director_profile", state.saved_settings.get("selected_profile", "")), "Prompt engine", 512, optional=True),
                    director_keep_model_loaded=_as_bool(config.get("local_llama_cpp", {}).get("keep_model_loaded", False)),
                )
                job = job_factory()
                job.kind = operation
                state.jobs[job.id] = job
                task = asyncio.create_task(state.run(job, director_request, config, True, workflow))
                state.tasks.add(task)
                task.add_done_callback(state.tasks.discard)
                return web.json_response(job.snapshot(), status=202)
            except WorkspaceConflict as exc:
                return web.json_response({"error": str(exc)}, status=409)

    app.add_routes([web.get("/api/workspace", endpoint), web.post("/api/workspace", endpoint),
                    web.post("/api/workspace/{operation:refine|explore}", endpoint)])


def execute_workflow(state, job, request, config, workflow):
    def persist(prompt, operation):
        try:
            return operation()
        except (ValueError, OSError) as exc:
            # Preserve expensive model output even when the disk cannot accept it.
            job.result = {"recovery_prompt": prompt, "target": request.target_model}
            raise ValueError(f"The prompt was generated, but saving failed. Copy the recovered result before leaving this page. {exc}") from exc

    def progress(message):
        with job.lock:
            job.progress = message
            job.revision += 1

    def save_direction(direction, prompt):
        job.commit(lambda: persist(prompt, lambda: state.workspace.save_direction(workflow["batch"], direction, prompt)))

    service = PromptWorkflowService(config, job.checkpoint)
    result = service.run(request, workflow, progress, save_direction)
    def finish():
        if workflow["operation"] == "refine":
            snapshot = persist(result["prompt"], lambda: state.workspace.add_version(
                result["prompt"], request.target_model, "Refinement", parent_id=workflow["parent_id"],
                instruction=workflow["changes"], detail_locks=workflow["locks"]))
            result["version_id"] = snapshot["current_id"]
        else:
            result["comparison_id"] = workflow["batch"]["id"]
        return result
    job.commit(finish, finish=True)
