"""Dataset job execution: understanding, and scene/prompt batches with durable checkpoints."""

from ...backends.base import BackendGenerationError
from .service import DatasetService
from .understanding import DatasetUnderstandingService
from .brainstorm import dataset_routing
from .vocabulary_conversion import VocabularyConversion
from ...backends.factory import canonical_backend_name, create_backend
from ...contracts import effective_model_family
from ...director_profiles import resolve_director_config


def run_vocabulary_preparation(state, job, request, config, workflow):
    effective, profile = resolve_director_config(config, request)
    if canonical_backend_name(effective.get("backend")) != "local_llama_cpp":
        raise ValueError("Private vocabulary preparation requires a configured local model, not a remote backend.")
    backend = create_backend(effective)
    job.set_progress("Preparing private vocabulary for review; no catalog is approved yet.")
    with backend.generation_session() as session:
        def generate(instruction):
            session.validate_instruction(instruction)
            return session.generate(instruction)
        result = VocabularyConversion().prepare(generate, job.checkpoint,
            family=effective_model_family(request, profile, effective))
    job.commit(lambda: {"ok": True, "kind": "dataset_vocabulary", **result}, finish=True)


def run_dataset_understanding(state, job, request, config, workflow):
    brief = DatasetUnderstandingService(config, job.checkpoint).run(request, workflow["input"], job.set_progress)
    routing = dataset_routing({**workflow["input"], "_confirmed_intent": brief})
    job.commit(lambda: {"ok": True, "kind": "dataset_understanding",
                       "routing": routing,
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
