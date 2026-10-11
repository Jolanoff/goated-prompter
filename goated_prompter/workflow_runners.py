"""Dispatch each admitted job to its tab's runner on the job worker thread.

Runners receive the application state, the job, the engine request, the effective
config and the admitted workflow payload. They own orchestration and result
persistence; HTTP admission stays in each tab's routes and job outcome handling
stays in ``LocalState.execute``.
"""

from .features.builder.runner import run_builder
from .features.dataset.runner import run_dataset, run_dataset_understanding
from .features.minimax.runner import run_minimax
from .features.refine.runner import run_refine


WORKFLOW_RUNNERS = {
    "builder": run_builder,
    "minimax": run_minimax,
    "dataset_understanding": run_dataset_understanding,
    "dataset": run_dataset,
    "dataset_scenes": run_dataset,
    "refine": run_refine,
}


def execute_workflow(state, job, request, config, workflow):
    try:
        runner = WORKFLOW_RUNNERS[workflow["operation"]]
    except KeyError:
        raise ValueError(f"Unknown workflow operation: {workflow['operation']}") from None
    runner(state, job, request, config, workflow)
