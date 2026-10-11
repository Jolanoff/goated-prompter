"""MiniMax job execution."""

from .service import MiniMaxService


def run_minimax(state, job, request, config, workflow):
    result = MiniMaxService(config, job.checkpoint).run(request, workflow["input"], job.set_progress)
    job.commit(lambda: result, finish=True)
