"""Serve the production UI and real Understanding API with one synthetic replay."""

import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from tests.support.paths import ROOT
from tests.support.artifacts import task_paths
from tests.support.safety import private_storage_guard, synthetic_storage


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    from aiohttp import web
    from local_app import create_app
    from goated_prompter.backends.mock import MockBackend

    fixture = Path(os.environ.get("GOATED_UNDERSTANDING_REPLAY", ROOT / "tests/fixtures/understanding_review.json")).resolve()
    quality = ROOT / "quality-artifacts"
    parts = fixture.relative_to(quality).parts if fixture.is_relative_to(quality) else ()
    scoped = len(parts) >= 4 and parts[0] in {"tasks", "temp"} and parts[2] == "browser"
    if not scoped and not any(fixture.is_relative_to(root) for root in (ROOT / "tests/fixtures", quality / "test")):
        raise ValueError("Replay input must be a synthetic fixture or evaluation artifact.")
    captured = json.loads(fixture.read_text(encoding="utf-8"))

    class ReplayBackend(MockBackend):
        def generate(self, instruction):
            if instruction.diagnostic_stage != "dataset:understanding":
                raise AssertionError("UI replay must not generate ideas, scenes or prompts.")
            source = json.loads(instruction.user_message)["source"]
            assert source["subject"] == captured["input"]["subject"]
            assert source["constraints"] == captured["input"]["constraints"]
            result = captured.get("raw_response") or json.dumps(captured["brief"])
            self.emit_activity("request", model="synthetic-replay", messages=instruction.to_messages(), parameters={})
            self.emit_activity("response_delta", text=result)
            self.emit_activity("response_complete", finish_reason="stop")
            return result

    def backend(config):
        result = ReplayBackend()
        result.activity_callback = config.get("_activity_callback")
        return result

    _, scratch = task_paths(os.environ.get("GOATED_TEST_TASK_KEY", "browser-tests"), "browser")
    with synthetic_storage(scratch) as storage:
        with patch("goated_prompter.features.dataset.understanding.create_backend", side_effect=backend), \
                patch("goated_prompter.features.dataset.service.create_backend", side_effect=backend), \
                patch("goated_prompter.features.builder.service.create_backend", side_effect=backend), \
                patch("local_app.get_process_manager"):
            web.run_app(create_app(port=8192, config_loader=lambda: {"backend": "mock"},
                                   settings_path=Path(storage) / "settings.json"),
                        host="127.0.0.1", port=8192)
