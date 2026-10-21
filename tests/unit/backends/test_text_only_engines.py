"""Text-only engines: local models without an mmproj and endpoints without vision."""

from pathlib import Path
import tempfile
import unittest

from goated_prompter.backends.base import BackendCapabilityError, BackendConfigurationError
from goated_prompter.backends.llama_cpp_process import LlamaCppLaunchConfig
from goated_prompter.backends.local_llama_cpp import LocalLlamaCppBackend
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.director_profiles import discover_director_profiles, resolve_director_config
from goated_prompter.image_utils import EncodedImage


IMAGE = EncodedImage(data="AAAA", media_type="image/png", width=1, height=1)


class LocalTextOnlyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.server = self.root / "llama-server"
        self.server.touch()
        for folder, files in (("writer", ("writer-Q4_K_M.gguf",)),
                              ("seer", ("seer-Q4_K_M.gguf", "mmproj-seer-BF16.gguf"))):
            (self.root / folder).mkdir()
            for name in files:
                (self.root / folder / name).touch()
        self.settings = {"discovery_root": str(self.root), "llama_server": str(self.server)}

    def launch(self, **settings):
        return LlamaCppLaunchConfig.from_mapping({"llama_server": str(self.server), **settings})

    def test_model_without_projector_is_a_ready_text_only_profile(self):
        discovery = discover_director_profiles(self.settings, refresh=True)
        profiles = {profile.profile_id: profile for profile in discovery.profiles}
        self.assertTrue(profiles["writer"].ready)
        self.assertFalse(profiles["writer"].vision_ready)
        self.assertEqual(profiles["writer"].warning, "")
        self.assertTrue(profiles["seer"].vision_ready)
        public = {item["id"]: item for item in discovery.to_public_mapping()["profiles"]}
        self.assertEqual((public["writer"]["ready"], public["writer"]["vision_ready"]), (True, False))
        self.assertEqual((public["seer"]["ready"], public["seer"]["vision_ready"]), (True, True))

    def test_folder_with_only_a_projector_stays_incomplete(self):
        (self.root / "orphan").mkdir()
        (self.root / "orphan" / "mmproj-orphan.gguf").touch()
        discovery = discover_director_profiles(self.settings, refresh=True)
        orphan = discovery.by_id("orphan")
        self.assertFalse(orphan.ready)
        request = GoatedPrompterRequest(idea="a cup", prompt_model="Custom", director_profile="orphan")
        with self.assertRaisesRegex(BackendConfigurationError, "incomplete"):
            resolve_director_config({"local_llama_cpp": self.settings}, request, refresh=True)

    def test_text_only_profile_clears_a_configured_projector(self):
        # A projector from config must never be paired with another folder's model.
        config = {"local_llama_cpp": {**self.settings,
                                      "mmproj_path": str(self.root / "seer" / "mmproj-seer-BF16.gguf")}}
        request = GoatedPrompterRequest(idea="a cup", prompt_model="Custom", director_profile="writer")
        effective, profile = resolve_director_config(config, request, refresh=True)
        local = effective["local_llama_cpp"]
        self.assertEqual(profile.profile_id, "writer")
        self.assertEqual(local["mmproj_path"], "")
        backend = LocalLlamaCppBackend(local, process_manager=object())
        self.assertFalse(backend.supports_vision)
        with self.assertRaises(BackendCapabilityError):
            backend.validate_vision_input(IMAGE)
        backend.validate_vision_input(None)

    def test_vision_profile_keeps_its_projector(self):
        request = GoatedPrompterRequest(idea="a cup", prompt_model="Custom", director_profile="seer")
        effective, _profile = resolve_director_config({"local_llama_cpp": self.settings}, request, refresh=True)
        backend = LocalLlamaCppBackend(effective["local_llama_cpp"], process_manager=object())
        self.assertTrue(backend.supports_vision)
        backend.validate_vision_input(IMAGE)

    def test_custom_model_path_no_longer_requires_a_projector(self):
        request = GoatedPrompterRequest(idea="a cup", prompt_model="Custom",
                                        director_model_path=str(self.root / "writer" / "writer-Q4_K_M.gguf"))
        effective, profile = resolve_director_config({"local_llama_cpp": self.settings}, request)
        self.assertIsNone(profile)
        self.assertEqual(effective["local_llama_cpp"]["mmproj_path"], "")
        projector_only = GoatedPrompterRequest(idea="a cup", prompt_model="Custom",
                                               director_mmproj_path=str(self.root / "seer" / "mmproj-seer-BF16.gguf"))
        with self.assertRaisesRegex(BackendConfigurationError, "requires a model path"):
            resolve_director_config({"local_llama_cpp": self.settings}, projector_only)

    def test_launch_omits_projector_flags_without_mmproj(self):
        text_only = self.launch(model_path=str(self.root / "writer" / "writer-Q4_K_M.gguf"), mmproj_path="")
        self.assertIsNone(text_only.mmproj_path)
        self.assertFalse(text_only.supports_vision)
        command = text_only.command()
        self.assertNotIn("--mmproj", command)
        self.assertNotIn("--image-min-tokens", command)
        self.assertIn("--model", command)

        vision = self.launch(model_path=str(self.root / "seer" / "seer-Q4_K_M.gguf"),
                             mmproj_path=str(self.root / "seer" / "mmproj-seer-BF16.gguf"))
        self.assertTrue(vision.supports_vision)
        command = vision.command()
        self.assertEqual(command[command.index("--mmproj") + 1], str(vision.mmproj_path))
        self.assertIn("--image-min-tokens", command)
        self.assertNotEqual(text_only.compatibility_key, vision.compatibility_key)

    def test_configured_projector_is_still_validated(self):
        with self.assertRaisesRegex(BackendConfigurationError, "same model folder"):
            self.launch(model_path=str(self.root / "writer" / "writer-Q4_K_M.gguf"),
                        mmproj_path=str(self.root / "seer" / "mmproj-seer-BF16.gguf"))


class OpenAICompatibleVisionTests(unittest.TestCase):
    def backend(self, **settings):
        return OpenAICompatibleBackend({"base_url": "http://127.0.0.1:1234/v1", "model": "m", **settings})

    def test_vision_defaults_on_for_existing_configs(self):
        backend = self.backend()
        self.assertTrue(backend.supports_vision)
        backend.validate_vision_input(IMAGE)

    def test_text_only_endpoint_rejects_images_but_accepts_text(self):
        backend = self.backend(vision=False)
        self.assertFalse(backend.supports_vision)
        backend.validate_vision_input(None)
        with self.assertRaisesRegex(BackendCapabilityError, "does not support vision"):
            backend.validate_vision_input(IMAGE)

    def test_vision_flag_must_be_boolean(self):
        for value in ("false", 0, None):
            with self.subTest(value=value), self.assertRaisesRegex(BackendConfigurationError, "vision must be true or false"):
                self.backend(vision=value)


if __name__ == "__main__":
    unittest.main()
