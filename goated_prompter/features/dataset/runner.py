"""Dataset job execution: Understanding, then the confirmed V2 run (scenes, then final prompts)."""

from ...backends.factory import create_backend
from ...backends.base import GoatedPrompterError
from ...director_profiles import resolve_director_config
from .v2.prompts import write_prompts
from .v2.scenes import write_scenes
from .v2.understanding import understand


def run_dataset_understanding(state, job, request, config, workflow):
    # Rebuild (issue 106): the tab's Understand button runs only the new Understanding.
    brief = understand(config, request, workflow["input"], checkpoint=job.checkpoint, progress=job.set_progress)
    job.commit(lambda: {"ok": True, "kind": "dataset_understanding",
                        **state.dataset_intents.register(workflow["input"], brief)}, finish=True)


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
    if "prompt_summary" in value:
        summary = value["prompt_summary"]
        missing = summary["missing"]
        return (f"Generation finished incomplete: {summary['written']} of {value['requested']} final prompts written; "
                f"not written: image{'s' if len(missing) > 1 else ''} {', '.join(map(str, missing))}.")
    missing = [item["slot"] for item in value.get("missing", [])]
    return (f"Generation finished incomplete: {value['written']} of {value['requested']} scenes written; "
            f"not written: image{'s' if len(missing) > 1 else ''} {', '.join(map(str, missing))}.")


def prompt_result(result, prompts, stage):
    """Keep scene counts intact, but require usable final prompts for end-to-end completion."""
    ready = {item["slot"] for item in prompts if item.get("prompt", "").strip() and not item.get("error")
             and item.get("trigger_ok", True)}
    missing = [number for number in range(1, result["requested"] + 1) if number not in ready]
    return {**result, "stage": stage, "prompts": list(prompts), "complete": result["complete"] and not missing,
            "prompt_summary": {"written": result["requested"] - len(missing), "missing": missing}}


def run_dataset_v2_scenes(state, job, request, config, workflow):
    # Confirm runs scenes, then final prompts unless the owner chose scenes only.
    # Each scene is published as soon as it is written, then each final prompt as it is written.
    def publish(value, message):
        def apply():
            with job.lock:
                job.result = {"ok": True, "kind": "dataset_v2_scenes", **value}
                job.record_event(message, "result")
        job.commit(apply)
    requested = workflow["brief"]["input"]["amount"]
    composed = {}
    def on_slot(event, number, value):
        composed[number] = value
        publish({"complete": False, "requested": requested, "written": len(composed), "missing": [], "slots": [],
                 "scenes": [composed[slot] for slot in sorted(composed)], "stage": "writing_scenes", "prompts": []},
                f"Scene for image {number} ({len(composed)} of {requested}) is ready.")
    written = []
    def on_prompt(item):
        written.append(item)
        publish(prompt_result(result, written, "prompts"),
                 f"Final prompt for image {item['slot']} ({len(written)} of {len(result['scenes'])}) "
                 + ("failed; continuing with the remaining scenes." if item.get("error") else "is ready."))
    def finish(value):
        job.commit(lambda: {"ok": True, "kind": "dataset_v2_scenes", **value}, finish=True, reason=incomplete(value))
    # One session held for the whole run: the scene steps and every Builder call share the loaded
    # model instead of each releasing it (a release with no other holder unloads the model).
    effective, _ = resolve_director_config(config, request)
    with create_backend(effective).generation_session():
        result = write_scenes(config, request, workflow["brief"], checkpoint=job.checkpoint, progress=job.set_progress,
                              on_slot=on_slot, vocabulary=workflow.get("vocabulary"))
        if not result["written"]:
            # Nothing to write prompts for: the job fails (its result keeps every image's reasons), never succeeds.
            publish({**result, "stage": "scenes", "prompts": []}, "No scene could be written.")
            raise GoatedPrompterError(no_scenes(result))
        if workflow.get("scenes_only"):
            finish({**result, "stage": "scenes", "prompts": []})
            return
        publish(prompt_result(result, [], "prompts"), f"{result['written']} scenes are ready; writing final prompts.")
        prompts = write_prompts(config, request, workflow["brief"], result["scenes"],
                                checkpoint=job.checkpoint, progress=job.set_progress, on_prompt=on_prompt)
    value = prompt_result(result, prompts, "done")
    if not value["prompt_summary"]["written"]:
        publish(value, "No final prompt could be written.")
        raise GoatedPrompterError(f"No final prompt could be written ({result['requested']} requested). "
                                 "Scenes and per-image prompt errors have been kept.")
    finish(value)
