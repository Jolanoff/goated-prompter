"""Repository hygiene: private/generated files stay out; source fixtures stay in."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "Requires a Git checkout")
class GitIgnoreTests(unittest.TestCase):
    def ignored(self, path):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path], cwd=ROOT,
            capture_output=True, text=True,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode == 0

    def test_private_and_generated_paths_are_ignored(self):
        for path in (
            "config/config.json", "data/workspace.json", "data/directors/private.json",
            ".env", ".env.local", "node_modules/pkg/index.js",
            "frontend/node_modules/pkg/index.js", "frontend/dist/index.html",
            "frontend/test-results/run.png", "frontend/playwright-report/index.html",
            ".venv/pyvenv.cfg", "goated_prompter/__pycache__/core.pyc",
            ".ruff_cache/results", "build/lib/core.py", "dist/app.whl",
            "app.egg-info/PKG-INFO", "quality-artifacts/run.json",
            "models/weights.bin", "LLM/model.gguf", "runtime/llama-server.exe",
            "weights.safetensors", "model.onnx", "server.log", "settings.json.tmp",
            "tests/eval/LIVE_RESULTS.json", "tests/eval/LIVE_RESULTS.md",
            "tests/eval/STATUS.md", "tests/eval/SEMANTIC_INVESTIGATION.md",
            "tests/evaluation/RESULTS.md", "tests/evaluation/DATASET_WRITER_RESULTS.md",
        ):
            with self.subTest(path=path):
                self.assertTrue(self.ignored(path))

    def test_templates_source_lockfiles_and_frozen_fixtures_remain_trackable(self):
        for path in (
            "config/config.example.json", ".env.example", ".env.local.example",
            "frontend/package-lock.json", "frontend/src/App.jsx",
            "tests/eval/fixtures/model_outputs/real_builder.json",
            "tests/eval/README.md", "tests/evaluation/README.md",
            "tests/fixtures/scene_planner_eval.md", ".github/workflows/checks.yml",
        ):
            with self.subTest(path=path):
                self.assertFalse(self.ignored(path))

    def test_public_evaluation_metadata_has_no_absolute_machine_paths(self):
        paths = list((ROOT / "tests/eval/fixtures/model_outputs").glob("*.json"))
        paths += [ROOT / "tests/eval/README.md", ROOT / "tests/evaluation/README.md",
                  ROOT / "tests/eval/fixtures/FAILURE_COVERAGE.md"]
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"(?<!\w)[A-Za-z]:[\\/]", text))
                self.assertNotIn('"engine_launch"', text)
