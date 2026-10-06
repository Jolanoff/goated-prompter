"""Runtime storage remains available; all files here are synthetic temporary data."""

from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import local_app as local
from goated_prompter import core, presets
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.json_store import atomic_json
from goated_prompter.prompting.dataset import dataset_instruction
from tests.helpers import dataset_idea_fixture, enter_context


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
        request = core.GoatedPrompterRequest.from_mapping(state.saved_settings["builder"])
        backend, session = Mock(), Mock()
        backend.name = "mock"
        backend.generation_session.return_value = nullcontext(session)
        session.generate.return_value = "A red ceramic cup on a wooden table in warm amber light."
        with patch.object(core, "create_backend", return_value=backend):
            result = core.GoatedPrompterService(config={"backend": "mock"}).generate(request)
        session.generate.assert_called_once()
        instruction = session.generate.call_args.args[0]
        self.assertEqual(instruction.user_message, idea)
        self.assertIn(behavior, instruction.system_message)
        self.assertEqual(result.director_preset, director.label)

    def test_saved_pass_scene_from_default_data_checkpoint_reaches_enhance(self):
        state = self.app_state()
        data = {**default_dataset_draft(), "subject": "A craftsperson", "trigger": "craft_token", "amount": 1}
        scene = {**dataset_idea_fixture(idea="Center clay"), "input": "",
            "scene": "A craftsperson centers clay with both palms on a spinning wheel.",
            "geometry": {}, "self_check": "PASS", "scene_status": "valid"}
        job = local.Job()
        job.kind = "dataset"
        state.workflow_settings.begin_dataset(job, data)
        job.result = {"scene_plan": [scene], "scene_plan_signature": "synthetic-runtime-plan", "prompts": []}
        job.status = "succeeded"
        state.workflow_settings.checkpoint_dataset(job)
        restarted = self.app_state()
        self.assertEqual(restarted.dataset_checkpoints.path, self.root / "data" / "dataset_checkpoints.json")
        draft = restarted.workflow_settings.snapshot("dataset")["draft"]
        self.assertEqual(draft["scene_plan"][0]["scene"], scene["scene"])
        instruction = dataset_instruction(core.GoatedPrompterRequest(idea=data["subject"]), draft, 1,
            plan_item=draft["scene_plan"][0])
        session = Mock()
        session.generate.return_value = "craft_token centers clay with both palms on a spinning wheel."
        DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, draft, 1,
            lambda _message: None, draft["scene_plan"][0])
        session.generate.assert_called_once()
        self.assertEqual(session.generate.call_args.args[0].user_message, scene["scene"])
