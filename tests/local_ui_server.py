"""Real local API with a delayed mock service for browser integration tests only."""

from pathlib import Path
import os
import sys
import tempfile
import time
import json
import re
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from local_app import create_app
from goated_prompter.core import GoatedPrompterService
from goated_prompter.backends.mock import MockBackend


class DatasetUIMock(MockBackend):
    """Schema-aware Dataset fixture; automatic planning cannot rely on fallback."""
    def generate(self, instruction):
        stage = instruction.diagnostic_stage
        if stage.startswith(("dataset:idea_planner", "dataset:scene_planner", "dataset:scene_composer")):
            context = json.loads(instruction.user_message)
            rows = []
            for assignment in context["assignments"]:
                index = assignment["index"]
                idea = assignment.get("idea") or assignment["input"] or f"Mock activity{index}"
                if stage.startswith("dataset:idea_planner"):
                    # A replacement must differ from both the batch and prior idea.
                    idea = f"Replacement activity{index}" if context.get("existing_ideas") else idea
                    rows.append({"index": index, "idea": idea})
                else:
                    text = assignment["input"] or context["subject"]
                    if stage.startswith("dataset:scene_composer"):
                        text = idea
                    rows.append({"index": index, "idea": idea, "scene": f"{text}; mock scene {index}.",
                                 "geometry": {"camera_view": "front", "framing": "full body"}})
            result = json.dumps(rows)
        elif re.match(r"dataset:\d+", stage):
            text = re.search(r"<scene>\n(.*?)\n</scene>", instruction.user_message, re.S).group(1)
            trigger = re.search(r"<trigger>\n(.*?)\n</trigger>", instruction.user_message, re.S).group(1)
            result = f"{trigger}: {text}"
        else:
            return super().generate(instruction)
        self.emit_activity("request", model="dataset-ui-mock", messages=instruction.to_messages(), parameters={})
        self.emit_activity("response_delta", text=result)
        self.emit_activity("response_complete", finish_reason="stop")
        return result


def dataset_ui_backend(config):
    backend = DatasetUIMock()
    backend.activity_callback = config.get("_activity_callback")
    return backend


class DelayedMockService(GoatedPrompterService):
    def _generate(self, request, text_only=False):
        time.sleep(1)
        return super()._generate(request, text_only=text_only)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as data:
        os.environ["GOATED_PROMPTER_USER_DIR"] = str(Path(data) / "directors")
        port = int(os.environ.get("GOATED_UI_TEST_PORT", "8190"))
        with patch("goated_prompter.dataset.create_backend", side_effect=dataset_ui_backend):
            web.run_app(create_app(port=port, config_loader=lambda: {"backend": "mock"}, settings_path=Path(data) / "settings.json",
                                   service_factory=DelayedMockService), host="127.0.0.1",
                        port=port)
