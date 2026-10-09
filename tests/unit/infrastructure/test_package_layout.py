"""Regression checks for standalone layout, input metadata, and data paths."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter import config, presets
from goated_prompter.director_profiles import resolve_models_directory
from goated_prompter.features.builder.input_schema import builder_input_schema


from tests.support.paths import ROOT


class PackageLayoutTests(unittest.TestCase):
    def test_standalone_layout_has_no_node_integration(self):
        for path in ("nodes", "comfyui_web", "__init__.py", ".comfyignore",
                     "goated_prompter/comfy_node.py", "goated_prompter/comfy_routes.py"):
            self.assertFalse((ROOT / path).exists(), path)
        self.assertTrue((ROOT / "config/config.example.json").is_file())

    def test_package_import_is_lazy_and_does_not_load_host_modules(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; import goated_prompter; "
                "assert not any(name.startswith('goated_prompter.') for name in sys.modules); "
                "from goated_prompter import config; "
                "assert 'folder_paths' not in sys.modules; "
                "assert 'server' not in sys.modules"
            )],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_standalone_data_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.resolve_config_path(), ROOT / "config/config.json")
            self.assertEqual(presets.resolve_user_director_directory(), ROOT / "data/directors")
            self.assertEqual(resolve_models_directory(), (Path.cwd() / "models").resolve())

    def test_environment_path_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "GOATED_PROMPTER_CONFIG": str(root / "custom.json"),
                "GOATED_PROMPTER_USER_DIR": str(root / "custom-directors"),
                "GOATED_PROMPTER_MODELS_DIR": str(root / "custom-models"),
            }, clear=True):
                self.assertEqual(config.resolve_config_path(), root / "custom.json")
                self.assertEqual(presets.resolve_user_director_directory(), root / "custom-directors")
                self.assertEqual(resolve_models_directory(), root / "custom-models")
                self.assertEqual(resolve_models_directory({"models_dir": str(root / "explicit")}), root / "explicit")

    def test_website_schema_keeps_defaults_and_fresh_metadata(self):
        schema = builder_input_schema()
        self.assertEqual(len(schema), 39)
        for key, default in (("mode", "Enhance"), ("target_model", "Generic"),
                             ("creativity", "Balanced"), ("prompt_length", "Medium"),
                             ("prompt_model", "Qwen 3.5 9B"), ("director_context_size", 32768)):
            self.assertEqual(schema[key][1]["default"], default)
        self.assertEqual(len([key for key in schema if key.startswith("reference_")]), 11)
        self.assertEqual(schema["reference_subject_source"][1]["default"], "Auto")
        schema["mode"][1]["default"] = "Custom"
        self.assertEqual(builder_input_schema()["mode"][1]["default"], "Enhance")
