"""Compatible Understanding replay command; implementation lives with integration."""

from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    runpy.run_module("tests.integration.browser.understanding_ui_replay", run_name="__main__")
