"""Prompt content is organized by concern under the prompting package."""

import unittest

from goated_prompter import director_profiles, reference_map
from goated_prompter.features.builder import service as builder
from goated_prompter.options import prompt_models, references
from goated_prompter.prompting import base, creativity, details, directors, modes, output, target_models


class PromptingPackageTests(unittest.TestCase):
    def test_runtime_modules_share_the_split_catalog_values(self):
        self.assertIs(builder._CREATIVITY_ADAPTERS, creativity.CREATIVITY_ADAPTERS)
        self.assertIs(builder._LENGTH_ADAPTERS, details.LENGTH_ADAPTERS)
        self.assertIs(builder._PRESERVATION_ADAPTERS, details.PRESERVATION_ADAPTERS)
        self.assertIs(builder.CORE_SYSTEM_PROMPT, base.CORE_SYSTEM_PROMPT)
        self.assertIs(builder.OUTPUT_CONTRACT, output.OUTPUT_CONTRACT)
        self.assertIs(director_profiles.PROMPT_MODEL_NAMES, prompt_models.PROMPT_MODEL_NAMES)
        self.assertIs(reference_map.REFERENCE_ATTRIBUTES, references.REFERENCE_ATTRIBUTES)
        self.assertIs(reference_map._MANUAL_CONSTRAINTS, details.REFERENCE_MANUAL_CONSTRAINTS)

    def test_adapters_keep_existing_fallbacks(self):
        self.assertEqual(modes.get_mode_adapter("missing"), modes.MODE_ADAPTERS["Enhance"])
        self.assertEqual(target_models.get_model_adapter("missing"), target_models.MODEL_ADAPTERS["Generic"])
        self.assertEqual(builder._LENGTH_ADAPTERS["Maximum"], details.MAXIMUM_DETAIL_GUIDANCE)


if __name__ == "__main__":
    unittest.main()
