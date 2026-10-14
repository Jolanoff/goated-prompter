"""Dataset job execution: understanding, and scene/prompt batches with durable checkpoints."""

from ...backends.base import BackendGenerationError
from ...backends.factory import create_backend
from ...director_profiles import resolve_director_config
from .service import DatasetService
from .v2.prompts import write_prompts
from .v2.scenes import write_scenes
from .v2.understanding import understand


def run_dataset_understanding(state, job, request, config, workflow):
    # Rebuild (issue 106): the tab's Understand button runs only the new Understanding.
    brief = understand(config, request, workflow["input"], checkpoint=job.checkpoint, progress=job.set_progress)
    job.commit(lambda: {"ok": True, "kind": "dataset_understanding", "brief": brief}, finish=True)


def run_dataset_v2_scenes(state, job, request, config, workflow):
    # Rebuild (issue 106): Confirm runs Section 2 (scenes) and Section 3 (final prompts through the Builder).
    # The scenes are published as soon as they exist, then each final prompt as it is written.
    def publish(value, message):
        def apply():
            with job.lock:
                job.result = {"ok": True, "kind": "dataset_v2_scenes", **value}
                job.record_event(message, "result")
        job.commit(apply)
    written = []
    def on_prompt(item):
        written.append(item)
        publish({**result, "stage": "prompts", "prompts": list(written)},
                f"Final prompt {item['index']} of {len(result['scenes'])} is ready.")
    # One session held for the whole run: the scene steps and every Builder call share the loaded
    # model instead of each releasing it (a release with no other holder unloads the model).
    effective, _ = resolve_director_config(config, request)
    with create_backend(effective).generation_session():
        result = write_scenes(config, request, workflow["brief"], checkpoint=job.checkpoint, progress=job.set_progress)
        publish({**result, "stage": "prompts", "prompts": []}, f"{result['written']} scenes are ready; writing final prompts.")
        prompts = write_prompts(config, request, workflow["brief"], result["scenes"],
                                checkpoint=job.checkpoint, progress=job.set_progress, on_prompt=on_prompt)
    job.commit(lambda: {"ok": True, "kind": "dataset_v2_scenes", **result, "stage": "done", "prompts": prompts}, finish=True)


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
                     else "Dataset scene plan is ready and available before prompt writing."
                     if any(row.get("scene_status") in {"valid", "unverified"} for row in result["scene_plan"])
                     else "Dataset planning failures saved; review the failed or unresolved scene slots."),
                    "result",
                )
        job.commit(publish)
    result = DatasetService(config, job.checkpoint, idea_history=state.idea_history).run(
        request, {**workflow["input"], "_confirmed_intent": workflow.get("intent")}, job.set_progress, partial,
        scenes_only=workflow["operation"] == "dataset_scenes", scene_action=workflow.get("scene_action"),
        valid_only=workflow.get("valid_only", False), resume=workflow.get("resume", False))
    if result.get("ok") is False:
        job.commit(lambda: durable_result(result))
        raise BackendGenerationError(result["error"])
    job.commit(lambda: durable_result(result), finish=True)
