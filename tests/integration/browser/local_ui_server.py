"""Real local API with a delayed mock service for browser integration tests only."""

from pathlib import Path
import os
import sys
import time
import json
from unittest.mock import patch

from tests.support.artifacts import task_paths
from tests.support.safety import private_storage_guard, synthetic_storage

from aiohttp import web
from local_app import create_app
from goated_prompter.features.builder.service import GoatedPrompterService
from goated_prompter.backends.mock import MockBackend
from goated_prompter.features.vocabulary.packs import PackManager


class UIMock(MockBackend):
    """Builder scene planning answered at once; every other stage falls back to the plain mock."""
    def generate(self, instruction):
        if instruction.diagnostic_stage == "builder:scene_planning":
            context = json.loads(instruction.user_message)
            return json.dumps({"primary_action": context["user_request"],
                               "staging": "Keep the requested subjects and relationships."})
        return super().generate(instruction)


def ui_backend(config):
    backend = UIMock()
    backend.activity_callback = config.get("_activity_callback")
    return backend


class DelayedMockService(GoatedPrompterService):
    def _generate(self, request, text_only=False):
        time.sleep(1)
        return super()._generate(request, text_only=text_only)


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    _, scratch = task_paths(os.environ.get("GOATED_TEST_TASK_KEY", "browser-tests"), "browser")
    with synthetic_storage(scratch) as data:
        port = int(os.environ.get("GOATED_UI_TEST_PORT", "8190"))
        packs = PackManager(Path(data) / "vocabulary" / "packs", Path(data) / "vocabulary" / "state.json")
        with patch("goated_prompter.features.builder.service.create_backend", side_effect=ui_backend), \
                patch("local_app.get_process_manager"), \
                patch("goated_prompter.features.vocabulary.routes.PackManager", return_value=packs), \
                patch("goated_prompter.features.dataset.v2.vocabulary_packs.PackManager", return_value=packs):
            # Exercise accepted aliases through the real API, not only factory tests.
            web.run_app(create_app(port=port, config_loader=lambda: {"backend": " DeBuG "}, settings_path=Path(data) / "settings.json",
                                   service_factory=DelayedMockService), host="127.0.0.1",
                        port=port)
