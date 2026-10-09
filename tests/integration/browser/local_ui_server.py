"""Real local API with a delayed mock service for browser integration tests only."""

from pathlib import Path
import os
import sys
import time
import json
import re
from unittest.mock import patch

from tests.support.artifacts import task_paths
from tests.support.safety import private_storage_guard, synthetic_storage

from aiohttp import web
from local_app import create_app
from goated_prompter.core import GoatedPrompterService
from goated_prompter.backends.mock import MockBackend


class DatasetUIMock(MockBackend):
    """Schema-aware Dataset fixture; automatic planning cannot rely on fallback."""
    def generate(self, instruction):
        stage = instruction.diagnostic_stage
        if stage == "dataset:build_scene":
            context = json.loads(instruction.user_message)
            row = context["assignments"][0]
            result = json.dumps({"scene": context.get("current_scene") or
                f"mock scene {row['index']}: " + " ".join(row.get(field, "") for field in ("idea", "placement", "visibility", "camera", "framing", "context")),
                "self_check": "PASS"})
        elif stage == "dataset:ideas":
            from tests.helpers import dataset_idea_fixture
            context = json.loads(instruction.user_message)
            used = {" ".join(idea.casefold().split()) for idea in context["recently_used_ideas"]}
            used.update(" ".join(row["idea"].casefold().split()) for row in context["existing_ideas"])
            rows = []
            for row in context["assignments"]:
                idea = row["input"] or f"Mock activity{row['index']}"
                if not row["input"]:
                    while " ".join(idea.casefold().split()) in used:
                        idea += " revised"
                used.add(" ".join(idea.casefold().split()))
                rows.append(dataset_idea_fixture(row["index"], idea=idea))
            result = json.dumps(rows)
        elif stage == "builder:scene_planning":
            context = json.loads(instruction.user_message)
            return json.dumps({"primary_action": context["user_request"],
                               "staging": "Keep the requested subjects and relationships."})
        elif stage.startswith("dataset:understanding"):
            from tests.helpers import dataset_understanding_fixture
            source = json.loads(instruction.user_message)["source"]
            self.dataset_trigger = source.get("trigger", "")
            result = json.dumps(dataset_understanding_fixture(requested_generation=source["subject"],
                hard=[{"scope": "all_outputs", "text": rule} for rule in source["constraints"].splitlines() if rule.strip()],
                rules=[{"scope": "all_outputs", "text": rule} for rule in source["constraints"].splitlines() if rule.strip()],
                clarifications=["Breaking what?"] if "unclear breaking" in source["subject"] and "breaking a board" not in source["constraints"] else []))
        elif re.match(r"dataset:\d+", stage):
            if "The application inserts the locked trigger" in instruction.system_message:
                result = instruction.user_message
            else:
                supplied = instruction.system_message.split("Include exact case-sensitive trigger wording: ", 1)[1]
                terms, _ = json.JSONDecoder().raw_decode(supplied)
                result = f"{', '.join(terms)}: {instruction.user_message}"
        else:
            return super().generate(instruction)
        time.sleep(.02)  # Leaves a real disconnect window without using inference.
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
    sys.addaudithook(private_storage_guard)
    _, scratch = task_paths(os.environ.get("GOATED_TEST_TASK_KEY", "browser-tests"), "browser")
    with synthetic_storage(scratch) as data:
        port = int(os.environ.get("GOATED_UI_TEST_PORT", "8190"))
        with patch("goated_prompter.dataset.create_backend", side_effect=dataset_ui_backend), \
                patch("goated_prompter.dataset_understanding.create_backend", side_effect=dataset_ui_backend), \
                patch("goated_prompter.core.create_backend", side_effect=dataset_ui_backend), \
                patch("local_app.get_process_manager"):
            # Exercise accepted aliases through the real API, not only factory tests.
            web.run_app(create_app(port=port, config_loader=lambda: {"backend": " DeBuG "}, settings_path=Path(data) / "settings.json",
                                   service_factory=DelayedMockService), host="127.0.0.1",
                        port=port)
