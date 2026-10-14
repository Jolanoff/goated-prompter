"""TEMPORARY debug trace for verifying one rebuilt section. Removed once that section is verified.

Each run writes one readable JSON file: what went in, every model attempt, every rule the code
applied and what came out. The console prints the output JSON, or one line on failure.
"""

from datetime import datetime
import json
from pathlib import Path
import time

DEBUG_DIR = Path(__file__).resolve().parents[4] / "quality-artifacts" / "temp" / "issue-106" / "debug"


class DebugTrace:
    def __init__(self, stage, **inputs):
        self.started = time.perf_counter()
        self.record = {"stage": stage, "input": inputs, "attempts": [], "decisions": [], "output": None, "error": None}

    def log(self, message):
        print(f"[debug:{self.record['stage']}] {message}", flush=True)

    def attempt(self, **details):
        self.record["attempts"].append(details)

    def decide(self, rule, detail):
        """A rule the code applied to the model's answer, so the reviewer sees every change."""
        self.record["decisions"].append({"rule": rule, "detail": detail})

    def finish(self, output=None, error=None):
        self.record.update(output=output, error=error, seconds=round(time.perf_counter() - self.started, 2))
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"{self.record['stage']}-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        path.write_text(json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8")
        if error:
            self.log(f"FAILED: {error} -> {path.name}")
        elif output is not None:
            self.log(f"{path.name}\n{json.dumps(output, ensure_ascii=False, indent=2)}")
        return path
