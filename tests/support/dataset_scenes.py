"""Reading the Dataset scene writer's user message back in scripted tests (v2/scenes/request.py compose_message)."""

import json
from unittest.mock import patch

from tests.helpers import enter_context


def without_places(test):
    """For scripted tests that are not about places: no place is dealt (v2/scenes/places.py), so the writer chooses
    the place as before. tests/unit/dataset/test_dataset_places.py tests the deal."""
    enter_context(test, patch("goated_prompter.features.dataset.v2.scenes.policies.place_plan", return_value=([], "")))


def without_looks(test):
    """For scripted tests that are not about looks: no look is dealt (v2/scenes/looks.py), so the writer chooses
    looks as before. tests/unit/dataset/test_dataset_looks.py tests the deal."""
    enter_context(test, patch("goated_prompter.features.dataset.v2.scenes.policies.deal_looks", return_value={}))


def composer_user(message):
    """{"request", "rules", "understanding", "style", "vocabulary" (the SELECTED VOCABULARY text or ""), "images",
    "earlier"} from one scene-writer user message."""
    head, rest = message.split("EXISTING APPROVED REQUIREMENTS:\n", 1)
    rest, images = rest.split("\n\nIMAGES:\n", 1)
    requirements, _, vocabulary = rest.partition("\n\nSELECTED VOCABULARY:")
    vocabulary = "SELECTED VOCABULARY:" + vocabulary if vocabulary else ""
    return {"request": head[len("USER REQUEST:\n"):].rstrip("\n"), **json.loads(requirements),
            "vocabulary": vocabulary.strip(), **json.loads(images)}
