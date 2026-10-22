"""Reading the Dataset scene writer's user message back in scripted tests (v2/scenes/request.py compose_message)."""

import json


def composer_user(message):
    """{"request", "rules", "understanding", "style", "vocabulary" (the SELECTED VOCABULARY text or ""), "images",
    "earlier"} from one scene-writer user message."""
    head, rest = message.split("EXISTING APPROVED REQUIREMENTS:\n", 1)
    rest, images = rest.split("\n\nIMAGES:\n", 1)
    requirements, _, vocabulary = rest.partition("\n\nSELECTED VOCABULARY:")
    vocabulary = "SELECTED VOCABULARY:" + vocabulary if vocabulary else ""
    return {"request": head[len("USER REQUEST:\n"):].rstrip("\n"), **json.loads(requirements),
            "vocabulary": vocabulary.strip(), **json.loads(images)}
