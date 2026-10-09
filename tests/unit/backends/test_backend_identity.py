"""Backend identity stays consistent across construction and website contracts."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from goated_prompter.backends.base import BackendConfigurationError
from goated_prompter.backends.factory import canonical_backend_name, create_backend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.director_profiles import resolve_director_config
from tests.support.backends import CONFIGURED_BACKENDS, backend_config


class BackendIdentityTests(unittest.TestCase):
    def test_canonical_names_cover_local_aliases_and_preserve_unknown_names(self):
        for value, expected in ((" Local-Llama-CPP ", "local_llama_cpp"), ("LLAMA-CPP", "local_llama_cpp"),
                                ("llamacpp", "local_llama_cpp"), (None, ""), ("   ", ""),
                                ("Other-Backend", "other_backend"), ("auto", "auto")):
            with self.subTest(value=value):
                self.assertEqual(canonical_backend_name(value), expected)

    def test_factory_accepts_configured_aliases_without_local_models(self):
        for name, expected in CONFIGURED_BACKENDS:
            with self.subTest(name=name):
                config = backend_config(name)
                original = deepcopy(config)
                self.assertEqual(create_backend(config).name, expected)
                self.assertEqual(config, original)

    def test_resolver_returns_canonical_config_without_discovering_local_models(self):
        request = GoatedPrompterRequest(idea="a cup", prompt_model="Custom")
        for name, expected in CONFIGURED_BACKENDS:
            with self.subTest(name=name), patch("goated_prompter.director_profiles.discover_director_profiles") as discover:
                config = backend_config(name)
                original = deepcopy(config)
                effective, profile = resolve_director_config(config, request)
                self.assertEqual(effective["backend"], expected)
                self.assertIsNone(profile)
                discover.assert_not_called()
                self.assertEqual(config, original)
                self.assertEqual(effective["openai_compatible"], config["openai_compatible"])

    def test_factory_still_rejects_missing_and_unsupported_names(self):
        for name in (None, "", "   ", "not-a-backend"):
            with self.subTest(name=name), self.assertRaises(BackendConfigurationError):
                create_backend({"backend": name})
