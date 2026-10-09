"""Refine job execution: edit the current version and save the result."""

from .service import RefineService


def run_refine(state, job, request, config, workflow):
    def persist(prompt, operation):
        try:
            return operation()
        except (ValueError, OSError) as exc:
            # Preserve expensive model output even when the disk cannot accept it.
            with job.lock:
                job.result = {"recovery_prompt": prompt, "target": request.target_model}
            raise ValueError(f"The prompt was generated, but saving failed. Copy the recovered result before leaving this page. {exc}") from exc

    result = RefineService(config, job.checkpoint).run(request, workflow, job.set_progress)
    def finish():
        snapshot = persist(result["prompt"], lambda: state.workspace.add_version(
            result["prompt"], request.target_model, "Refinement", parent_id=workflow["parent_id"],
            instruction=workflow["changes"], detail_locks=workflow["locks"]))
        result["version_id"] = snapshot["current_id"]
        return result
    job.commit(finish, finish=True)
