"""Dataset job execution: Understanding, then the confirmed V2 run (scenes, then final prompts)."""

import logging

from ...backends.factory import create_backend
from ...director_profiles import resolve_director_config
from ...local_jobs import JobCancelled
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


def no_scenes(result):
    """Why a run wrote no scene at all, per distinct reason with the images it stopped."""
    reasons = {}
    for item in result["missing"]:
        for reason in item["reasons"] or ["no reason recorded"]:
            reasons.setdefault(reason, []).append(item["slot"])
    detail = "; ".join(f"{reason} (image{'s' if len(slots) > 1 else ''} {', '.join(map(str, slots))})"
                       for reason, slots in list(reasons.items())[:4])
    return f"No scene could be written ({result['requested']} requested). {detail}"


def incomplete(value):
    """The job's final message when only some images were written; None when all were."""
    if value.get("complete", True):
        return None
    missing = [item["slot"] for item in value.get("missing", [])]
    return (f"Generation finished incomplete: {value['written']} of {value['requested']} scenes written; "
            f"not written: image{'s' if len(missing) > 1 else ''} {', '.join(map(str, missing))}.")


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
        job.commit(lambda: {"ok": True, "kind": "dataset_v2_scenes", **run, **value}, finish=True, reason=incomplete(value))
        _close(recorder, "succeeded")
    try:
        # One session held for the whole run: the scene steps and every Builder call share the loaded
        # model instead of each releasing it (a release with no other holder unloads the model).
        effective, _ = resolve_director_config(config, request)
        with create_backend(effective).generation_session():
            result = write_scenes(config, request, workflow["brief"], checkpoint=job.checkpoint, progress=job.set_progress,
                                  on_slot=on_slot, vocabulary=workflow.get("vocabulary_packs"),
                                  visual=workflow.get("visual_direction"))
            if recorder:
                recorder.scenes_finished(result)
            if not result["written"]:
                # Nothing to write prompts for: the job fails (its result keeps every image's reasons), never succeeds.
                publish({**result, "stage": "scenes", "prompts": []}, "No scene could be written.")
                raise RuntimeError(no_scenes(result))
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
