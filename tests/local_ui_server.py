"""Compatible browser-test server command; implementation lives with integration."""

from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    runpy.run_module("tests.integration.browser.local_ui_server", run_name="__main__")
