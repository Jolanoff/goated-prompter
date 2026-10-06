"""Memory-only checkpoint cleanup, independent of saved drafts and history."""

import asyncio
import threading

TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
JOB_FAMILIES = {
    "builder": {"builder"}, "refine": {"refine"}, "minimax": {"minimax"},
    "dataset": {"dataset", "dataset_scenes", "dataset_understanding"},
}


async def daemon_work(operation, *args):
    """Cooperative workers with an exit fallback independent of executor shutdown."""
    loop = asyncio.get_running_loop()
    finished = loop.create_future()
    def complete(value, error):
        if not finished.done():
            if error is None:
                finished.set_result(value)
            else:
                finished.set_exception(error)
    def worker():
        value, error = None, None
        try:
            value = operation(*args)
        except Exception as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(complete, value, error)
        except RuntimeError:
            pass
    threading.Thread(target=worker, name="generation-worker", daemon=True).start()
    return await finished


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
