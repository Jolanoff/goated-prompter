"""Serve the production UI and real Understanding API with one synthetic replay."""

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.support.safety import private_storage_guard


if __name__ == "__main__":
    sys.addaudithook(private_storage_guard)
    from aiohttp import web
    from local_app import create_app
    from goated_prompter.backends.mock import MockBackend

    fixture = Path(os.environ.get("GOATED_UNDERSTANDING_REPLAY", ROOT / "tests/fixtures/understanding_review.json")).resolve()
    if not any(fixture.is_relative_to(root) for root in (ROOT / "tests/fixtures", ROOT / "quality-artifacts/test")):
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

    with tempfile.TemporaryDirectory(prefix="understanding-ui-") as storage:
        os.environ["GOATED_PROMPTER_USER_DIR"] = str(Path(storage) / "directors")
        with patch("goated_prompter.dataset_understanding.create_backend", side_effect=backend), \
                patch("goated_prompter.dataset.create_backend", side_effect=backend), \
                patch("goated_prompter.core.create_backend", side_effect=backend), \
                patch("local_app.get_process_manager"):
            web.run_app(create_app(port=8192, config_loader=lambda: {"backend": "mock"},
                                   settings_path=Path(storage) / "settings.json"),
                        host="127.0.0.1", port=8192)
