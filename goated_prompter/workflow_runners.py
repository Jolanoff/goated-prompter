"""One execution entry point per workflow, run on the job worker thread.

Each runner receives the application state, the job, the engine request, the
effective config and the admitted workflow payload. Runners own workflow
orchestration and result persistence; HTTP admission stays in the route modules
and job outcome handling stays in ``LocalState.execute``.
"""

from .dataset import DatasetService
from .dataset_understanding import DatasetUnderstandingService
from .minimax import MiniMaxService
from .refinement import RefineService


def _progress(job):
    def progress(message):
        job.set_progress(message)
    return progress


def run_builder(state, job, request, config, workflow):
    job.set_progress(
        "Running the Builder model workflow. The engine may be loading, analyzing references, or writing the final prompt."
    )
    service = state.service_factory(config=config, checkpoint=job.checkpoint)
    generated = (service.generate_text_only if workflow.get("text_only") else service.generate)(request)
    result = {"ok": True, "prompt": generated.prompt, "backend": generated.backend_name,
              "director_profile": generated.director_profile,
              "prompt_model": generated.prompt_model, "director_preset": generated.director_preset}
    result["planning_status"] = getattr(generated, "planning_status", "direct")
    def save_result():
        try:
            snapshot = state.workspace.add_version(generated.prompt, request.target_model, "Builder generation")
            result["version_id"] = snapshot["current_id"]
        except (ValueError, OSError) as exc:
            result["history_error"] = f"Prompt generated, but version history could not be saved: {exc}"
        return result
    job.commit(save_result, finish=True)


def run_minimax(state, job, request, config, workflow):
    result = MiniMaxService(config, job.checkpoint).run(request, workflow["input"], _progress(job))
    job.commit(lambda: result, finish=True)


def run_dataset_understanding(state, job, request, config, workflow):
    brief = DatasetUnderstandingService(config, job.checkpoint).run(request, workflow["input"], _progress(job))
    job.commit(lambda: {"ok": True, "kind": "dataset_understanding",
                       **state.dataset_intents.register(workflow["input"], brief)}, finish=True)


def run_dataset(state, job, request, config, workflow):
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
                )
        job.commit(publish)
    result = DatasetService(config, job.checkpoint, idea_history=state.idea_history).run(
        request, {**workflow["input"], "_confirmed_intent": workflow.get("intent")}, _progress(job), partial,
        scenes_only=workflow["operation"] == "dataset_scenes", scene_action=workflow.get("scene_action"),
        valid_only=workflow.get("valid_only", False), resume=workflow.get("resume", False))
    job.commit(lambda: durable_result(result), finish=True)


def run_refine(state, job, request, config, workflow):
    def persist(prompt, operation):
        try:
            return operation()
        except (ValueError, OSError) as exc:
            # Preserve expensive model output even when the disk cannot accept it.
            with job.lock:
                job.result = {"recovery_prompt": prompt, "target": request.target_model}
            raise ValueError(f"The prompt was generated, but saving failed. Copy the recovered result before leaving this page. {exc}") from exc

    result = RefineService(config, job.checkpoint).run(request, workflow, _progress(job))
    def finish():
        snapshot = persist(result["prompt"], lambda: state.workspace.add_version(
            result["prompt"], request.target_model, "Refinement", parent_id=workflow["parent_id"],
            instruction=workflow["changes"], detail_locks=workflow["locks"]))
        result["version_id"] = snapshot["current_id"]
        return result
    job.commit(finish, finish=True)


WORKFLOW_RUNNERS = {
    "builder": run_builder,
    "minimax": run_minimax,
    "dataset_understanding": run_dataset_understanding,
    "dataset": run_dataset,
    "dataset_scenes": run_dataset,
    "refine": run_refine,
}


def execute_workflow(state, job, request, config, workflow):
    try:
        runner = WORKFLOW_RUNNERS[workflow["operation"]]
    except KeyError:
        raise ValueError(f"Unknown workflow operation: {workflow['operation']}") from None
    runner(state, job, request, config, workflow)
