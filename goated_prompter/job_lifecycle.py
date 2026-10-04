"""Memory-only checkpoint cleanup, independent of saved drafts and history."""

TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
JOB_FAMILIES = {
    "builder": {"builder"}, "refine": {"refine"}, "minimax": {"minimax"},
    "dataset": {"dataset", "dataset_scenes", "dataset_review"},
}


def release_completed_checkpoints(jobs, *, family=None):
    if family is not None and family not in JOB_FAMILIES:
        raise ValueError("Choose a supported workflow checkpoint family.")
    kinds = JOB_FAMILIES.get(family)
    released = []
    for job_id, job in list(jobs.items()):
        with job.lock:
            if job.status not in TERMINAL_JOB_STATUSES or (kinds is not None and job.kind not in kinds):
                continue
            job.clear_private_data()
            del jobs[job_id]
            released.append(job_id)
    return released
