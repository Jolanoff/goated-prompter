"""Frontend option lists that mirror backend catalogs stay identical."""

import json
import re
import unittest

from goated_prompter.options import dataset, detail_locks, minimax, styles
from tests.support.paths import ROOT

FRONTEND = ROOT / "frontend" / "src"


def exported(path, name):
    """Read one JSON-compatible exported literal from a frontend options module."""
    text = (FRONTEND / path).read_text(encoding="utf-8")
    match = re.search(rf"^export const {name} = (.*?);$", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"{path} does not export {name}")
    literal = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', match.group(1))
    literal = re.sub(r",\s*([\]}])", r"\1", literal)
    return json.loads(literal)


class OptionParityTests(unittest.TestCase):
    def test_minimax_options_match_backend(self):
        self.assertEqual(tuple(exported("features/minimax/options.js", "models")), minimax.MODELS)
        self.assertEqual(tuple(value for value, _label in exported("features/minimax/options.js", "modes")), minimax.MODES)
        self.assertEqual(tuple(exported("features/minimax/options.js", "ratios")), minimax.RATIOS)
        self.assertEqual(exported("features/minimax/options.js", "referenceLimits"), minimax.LIMITS)

    def test_dataset_types_match_backend(self):
        self.assertEqual(tuple(exported("features/dataset/options.js", "triggerTypes")), dataset.DATASET_TYPES)
        self.assertEqual(tuple(value for value, _label in exported("features/dataset/options.js", "consistencyParts")),
                         dataset.CONSISTENCY_PARTS)
        self.assertEqual(tuple(value for value, _label in exported("features/dataset/options.js", "consistencyLevels")),
                         dataset.CONSISTENCY_LEVELS)
        self.assertEqual(exported("features/dataset/options.js", "typeConsistency"), dataset.TYPE_CONSISTENCY)

    def test_dataset_seed_options_match_backend(self):
        self.assertEqual(tuple(value for value, _label in exported("features/dataset/options.js", "seedModes")),
                         dataset.SEED_MODES)
        self.assertEqual(exported("features/dataset/options.js", "maxSeed"), dataset.MAX_SEED)

    def test_dataset_trigger_options_match_backend(self):
        self.assertEqual(tuple(value for value, _label in exported("features/dataset/options.js", "triggerKinds")),
                         dataset.TRIGGER_KINDS)
        self.assertEqual(tuple(value for value, _label in exported("features/dataset/options.js", "triggerExpansions")),
                         dataset.TRIGGER_EXPANSIONS)
        self.assertEqual(exported("features/dataset/options.js", "maxTriggers"), dataset.MAX_TRIGGERS)

    def test_dataset_director_exclusions_match_backend(self):
        self.assertEqual(tuple(exported("features/dataset/options.js", "excludedDirectors")),
                         dataset.DATASET_EXCLUDED_DIRECTORS)

    def test_styles_match_backend(self):
        self.assertEqual(tuple(exported("shared/workflow/options.js", "styles")), styles.STYLE_NAMES)
        self.assertEqual(tuple(exported("shared/workflow/options.js", "captures")), styles.CAPTURE_NAMES)
        self.assertEqual(tuple(exported("shared/workflow/options.js", "aspectRatios")), dataset.ASPECT_RATIO_NAMES)
        self.assertEqual({key: tuple(value) for key, value in exported("shared/workflow/options.js", "unsupportedStyles").items()},
                         styles.UNSUPPORTED_STYLES)

    def test_detail_locks_match_backend(self):
        self.assertEqual(tuple(value for value, _label in exported("shared/workflow/options.js", "lockOptions")),
                         detail_locks.LOCKS)


if __name__ == "__main__":
    unittest.main()
