"""Prompt Builder job execution: generate, then save the result as a history version."""


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
