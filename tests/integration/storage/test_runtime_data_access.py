"""Runtime storage remains available; all files here are synthetic temporary data."""

from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import local_app as local
from goated_prompter import presets
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import GoatedPrompterService
from goated_prompter.json_store import atomic_json
from tests.helpers import enter_context


class RuntimeDataAccessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(enter_context(self, tempfile.TemporaryDirectory()))
        enter_context(self, patch.object(local, "__file__", str(self.root / "local_app.py")))
        enter_context(self, patch.object(presets, "PROJECT_ROOT", self.root))
        enter_context(self, patch.dict(os.environ))
        os.environ.pop(presets.USER_DIRECTOR_DIR_ENV, None)
        enter_context(self, patch.object(local, "get_process_manager"))

    def app_state(self):
        return local.create_app(config_loader=lambda: {"backend": "mock"})[local.STATE]

    def test_default_data_settings_and_saved_director_reach_model_instruction(self):
        behavior = "Use warm amber lighting and visible ceramic surface texture."
        director, path = presets.save_user_director("Synthetic runtime Director", behavior)
        self.assertEqual(path.parent, self.root / "data" / "directors")
        idea = "A red ceramic cup stands on a wooden table."
        atomic_json(self.root / "data" / "settings.json", {"builder": {
            "idea": idea, "director_preset": director.id, "planning_mode": "Direct"}})
        state = self.app_state()
        self.assertEqual(state.settings_path, self.root / "data" / "settings.json")
        request = GoatedPrompterRequest.from_mapping(state.saved_settings["builder"])
        backend, session = Mock(), Mock()
        backend.name = "mock"
        backend.generation_session.return_value = nullcontext(session)
        session.generate.return_value = "A red ceramic cup on a wooden table in warm amber light."
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
            result = GoatedPrompterService(config={"backend": "mock"}).generate(request)
        session.generate.assert_called_once()
        instruction = session.generate.call_args.args[0]
        self.assertEqual(instruction.user_message, idea)
        self.assertIn(behavior, instruction.system_message)
        self.assertEqual(result.director_preset, director.label)
