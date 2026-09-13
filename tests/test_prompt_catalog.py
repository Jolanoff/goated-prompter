"""Static prompt content has one editable source of truth."""

import unittest

from goated_prompter import prompt_catalog
from goated_prompter import core, director_profiles, system_prompt
from goated_prompter.models import adapters as model_adapters
from goated_prompter.modes import adapters as mode_adapters
from goated_prompter import reference_map


class PromptCatalogTests(unittest.TestCase):
    def test_compatibility_modules_share_the_catalog_values(self):
        self.assertIs(core._CREATIVITY_ADAPTERS, prompt_catalog.CREATIVITY_ADAPTERS)
        self.assertIs(core._LENGTH_ADAPTERS, prompt_catalog.LENGTH_ADAPTERS)
        self.assertIs(core._PRESERVATION_ADAPTERS, prompt_catalog.PRESERVATION_ADAPTERS)
        self.assertIs(system_prompt.CORE_SYSTEM_PROMPT, prompt_catalog.CORE_SYSTEM_PROMPT)
        self.assertIs(mode_adapters.MODE_NAMES, prompt_catalog.MODE_NAMES)
        self.assertIs(model_adapters.TARGET_MODEL_NAMES, prompt_catalog.TARGET_MODEL_NAMES)
        self.assertIs(director_profiles.PROMPT_MODEL_NAMES, prompt_catalog.PROMPT_MODEL_NAMES)
        self.assertIs(reference_map.REFERENCE_ATTRIBUTES, prompt_catalog.REFERENCE_ATTRIBUTES)
        self.assertIs(reference_map.REFERENCE_SOURCE_NAMES, prompt_catalog.REFERENCE_SOURCE_NAMES)
        self.assertIs(reference_map._MANUAL_CONSTRAINTS, prompt_catalog.REFERENCE_MANUAL_CONSTRAINTS)

    def test_compatibility_adapters_keep_the_existing_fallbacks(self):
        self.assertEqual(mode_adapters.get_mode_adapter("missing"), prompt_catalog.MODE_ADAPTERS["Enhance"])
        self.assertEqual(model_adapters.get_model_adapter("missing"), prompt_catalog.MODEL_ADAPTERS["Generic"])
        self.assertEqual(core._LENGTH_ADAPTERS["Maximum"], prompt_catalog.MAXIMUM_DETAIL_GUIDANCE)
