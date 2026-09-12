"""Regression checks for the website-first layout and retained data paths."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from goated_prompter import config, presets


ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    def test_shared_import_does_not_load_comfy_adapters_or_server(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; import goated_prompter; "
                "assert not any(name.startswith('goated_prompter.') for name in sys.modules); "
                "from goated_prompter import config; "
                "assert 'goated_prompter.comfy_node' not in sys.modules; "
                "assert 'goated_prompter.comfy_routes' not in sys.modules; "
                "assert 'server' not in sys.modules"
            )],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_legacy_data_defaults_without_comfyui(self):
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"folder_paths": None}):
            self.assertEqual(config.resolve_config_path(), ROOT / "nodes/goated_prompter/config.json")
            self.assertEqual(
                presets.resolve_user_director_directory(),
                ROOT / "nodes/goated_prompter/user_data/directors",
            )

    def test_comfyui_and_environment_path_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            user_root = Path(directory)
            comfy_config = user_root / "GoatedPrompter/config.json"
            folder_paths = types.SimpleNamespace(get_user_directory=lambda: directory)
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"folder_paths": folder_paths}):
                with patch.object(Path, "is_file", return_value=True):
                    self.assertEqual(config.resolve_config_path(), comfy_config)
                with patch.object(Path, "is_file", return_value=False):
                    self.assertEqual(config.resolve_config_path(), config.DEFAULT_CONFIG_PATH)
                self.assertEqual(presets.resolve_user_director_directory(), user_root / "GoatedPrompter/directors")
                with patch.dict(os.environ, {
                    "GOATED_PROMPTER_CONFIG": str(user_root / "custom.json"),
                    "GOATED_PROMPTER_USER_DIR": str(user_root / "custom-directors"),
                }):
                    self.assertEqual(config.resolve_config_path(), user_root / "custom.json")
                    self.assertEqual(presets.resolve_user_director_directory(), user_root / "custom-directors")

    def test_comfy_entry_point_registers_routes_and_exports_existing_node(self):
        name = "_goated_comfy_layout_test"
        spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
        entry = importlib.util.module_from_spec(spec)
        routes = types.ModuleType(f"{name}.goated_prompter.comfy_routes")
        with patch.object(routes, "register_routes", return_value=True, create=True) as register:
            with patch.dict(sys.modules, {name: entry, routes.__name__: routes}):
                spec.loader.exec_module(entry)
                register.assert_called_once_with()
                self.assertEqual(set(entry.NODE_CLASS_MAPPINGS), {"GoatedPrompter"})
                self.assertEqual(entry.NODE_DISPLAY_NAME_MAPPINGS, {"GoatedPrompter": "Goated Prompter"})
                self.assertEqual(entry.WEB_DIRECTORY, "./comfyui_web")
                self.assertTrue((ROOT / entry.WEB_DIRECTORY / "goated_prompter/goated_prompter.js").is_file())
