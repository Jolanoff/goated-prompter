"""Dataset job execution: understanding, and scene/prompt batches with durable checkpoints."""

import logging

from ...backends.base import BackendGenerationError
from ...backends.factory import create_backend
from ...director_profiles import resolve_director_config
from ...local_jobs import JobCancelled
from .service import DatasetService
from .v2.prompts import write_prompts
from .v2.runs import RunRecorder, RunStoreError
from .v2.scenes import slot_inputs, write_scenes
from .v2.understanding import understand


def run_dataset_understanding(state, job, request, config, workflow):
    # Rebuild (issue 106): the tab's Understand button runs only the new Understanding.
    brief = understand(config, request, workflow["input"], checkpoint=job.checkpoint, progress=job.set_progress)
    job.commit(lambda: {"ok": True, "kind": "dataset_understanding",
                        **state.dataset_intents.register(workflow["input"], brief)}, finish=True)


def _recorder(state, job, workflow):
    """The durable V2 run for this job (v2/runs.py), created before any inference; None without a store."""
    store = getattr(state, "dataset_runs", None)
    if store is None:
        return None
    brief = workflow["brief"]
    return RunRecorder.start(store, job.id, brief, scenes_only=bool(workflow.get("scenes_only")), inputs=slot_inputs(brief),
                             packs=workflow.get("vocabulary_packs"))


def _close(recorder, status, error=None):
    """Record how the run ended, once the job's outcome is settled. A failure here is logged, never raised."""
    if recorder is None:
        return
    try:
        recorder.finish(status, error)
    except RunStoreError:
        logging.exception("Could not record the end of Dataset run %s; it will be marked interrupted on restart", recorder.run_id)


def run_dataset_v2_scenes(state, job, request, config, workflow):
    # Confirm runs scenes, then final prompts unless the owner chose scenes only.
    # The scenes are published as soon as they exist, then each final prompt as it is written.
    # Every completed concept, staging, scene and prompt is also saved to the run store (v2/runs.py)
    # as it appears; a save that fails stops the job instead of being treated as saved.
    recorder = _recorder(state, job, workflow)
    run = {"run_id": recorder.run_id} if recorder else {}
    def publish(value, message):
        def apply():
            with job.lock:
                job.result = {"ok": True, "kind": "dataset_v2_scenes", **run, **value}
                job.record_event(message, "result")
        job.commit(apply)
    def on_slot(event, number, value):
        if recorder:
            recorder.slot_event(event, number, value)
    written = []
    def on_prompt(item):
        if recorder:
            recorder.prompt(item)
        written.append(item)
        publish({**result, "stage": "prompts", "prompts": list(written)},
                 f"Final prompt for image {item['slot']} ({len(written)} of {len(result['scenes'])}) "
                 + ("failed; continuing with the remaining scenes." if item.get("error") else "is ready."))
    def finish(value):
        # The run is marked succeeded only after the job itself has succeeded: a cancellation that
        # lands while the result is delivered makes both the job and the run cancelled.
        job.commit(lambda: {"ok": True, "kind": "dataset_v2_scenes", **run, **value}, finish=True)
        _close(recorder, "succeeded")
    try:
        # One session held for the whole run: the scene steps and every Builder call share the loaded
        # model instead of each releasing it (a release with no other holder unloads the model).
        effective, _ = resolve_director_config(config, request)
        with create_backend(effective).generation_session():
            result = write_scenes(config, request, workflow["brief"], checkpoint=job.checkpoint, progress=job.set_progress,
                                  on_slot=on_slot, vocabulary=workflow.get("vocabulary_packs"))
            if recorder:
                recorder.scenes_finished(result)
            if workflow.get("scenes_only"):
                finish({**result, "stage": "scenes", "prompts": []})
                return
            publish({**result, "stage": "prompts", "prompts": []}, f"{result['written']} scenes are ready; writing final prompts.")
            prompts = write_prompts(config, request, workflow["brief"], result["scenes"],
                                    checkpoint=job.checkpoint, progress=job.set_progress, on_prompt=on_prompt)
        finish({**result, "stage": "done", "prompts": prompts})
    except Exception as error:
        # The same precedence LocalState.execute uses for the job: cancellation, then a server stop, then failure.
        if isinstance(error, JobCancelled) or job.cancel_requested:
            _close(recorder, "cancelled", "Generation stopped because cancellation was requested.")
        elif job.stopping:
            _close(recorder, "interrupted", "Server stopped before this run finished.")
        else:
            _close(recorder, "failed", f"{type(error).__name__}: {error}")
        raise


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
