"""Repository paths independent of a test module's directory depth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
