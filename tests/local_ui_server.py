"""Real local API with a delayed mock service for browser integration tests only."""

from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from local_app import create_app
from nodes.goated_prompter.core import GoatedPrompterService


class DelayedMockService(GoatedPrompterService):
    def _generate(self, request, text_only=False):
        time.sleep(1)
        return super()._generate(request, text_only=text_only)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as data:
        web.run_app(create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(data) / "settings.json",
                               service_factory=DelayedMockService), host="127.0.0.1", port=8190)
