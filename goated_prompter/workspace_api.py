"""Workspace route registration; workflow execution lives in ``workflow_runners``."""

from .api import dataset_routes, minimax_routes, workflow_settings_routes, workspace_routes
from .workflow_runners import execute_workflow  # noqa: F401  (existing import path)


def register_workspace_routes(app, state_key, job_factory, json_object):
    for routes in (minimax_routes, dataset_routes, workflow_settings_routes, workspace_routes):
        routes.register(app, state_key, job_factory, json_object)
