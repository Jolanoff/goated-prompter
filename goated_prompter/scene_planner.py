"""Scene Planner service. Dataset owns the session; this skill owns scene ideation."""

import json

from .backends.base import BackendGenerationError
from .prompting.scene_planner import (
    MAX_SCENE_CHARACTERS, MAX_SCENE_WORDS, scene_planner_instruction,
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Scene Planner returned duplicate JSON keys.")
        result[key] = value
    return result


def validate_scene_plan(raw, amount):
    """Accept only the minimal JSON schema; never salvage fenced/broken output."""
    if not isinstance(raw, str):
        raise ValueError("Scene Planner must return a valid JSON array.")
    rows = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or len(rows) != amount:
        raise ValueError("Scene Planner must return exactly one scene per requested image.")
    cleaned, seen = [], set()
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or set(row) != {"index", "scene"}
                or type(row["index"]) is not int or row["index"] != index):
            raise ValueError("Scene Planner rows require sequential integer indexes and scene only.")
        scene = row["scene"]
        if (not isinstance(scene, str) or not scene.strip()
                or len(scene) > MAX_SCENE_CHARACTERS or len(scene.split()) > MAX_SCENE_WORDS
                or "```" in scene or "\n" in scene.strip() or "\r" in scene.strip()):
            raise ValueError("Scene Planner scenes must be nonempty concise paragraphs without markdown fences.")
        scene = scene.strip()
        signature = " ".join(scene.casefold().split())
        if signature in seen:
            raise ValueError("Scene Planner returned identical scenes; use compatible distinct presentations.")
        seen.add(signature)
        cleaned.append({"index": index, "scene": scene})
    return cleaned


class ScenePlanner:
    """Plan a batch with one repair, then preserve user input on failure."""

    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    def plan_batch(self, *, session, data, coverage, family="qwen", progress):
        correction = ""
        for attempt in range(2):
            self.checkpoint()
            progress("Scene Planner · planning dataset scenes…" if not attempt
                     else "Scene Planner · repairing scene plan…")
            instruction = scene_planner_instruction(data, coverage, family, correction)
            try:
                session.validate_instruction(instruction)
                raw = session.generate(instruction)
                self.checkpoint()
                return validate_scene_plan(raw, data["amount"])
            except (ValueError, TypeError, RecursionError, BackendGenerationError) as exc:
                # A checkpoint outside the handler preserves pause/cancellation
                # even when the model call itself fails.
                self.checkpoint()
                progress(f"Scene Planner failed validation: {exc}")
                correction = str(exc) + " Return the exact JSON array schema, with concise distinct scenes and sequential indexes."
        progress("Scene Planner unavailable; using the supplied concept and guided inputs directly.")
        # Do not guess whether a coverage facet conflicts with natural-language
        # constraints. Keep the original input intact; coverage remains separately
        # available to the writer as subordinate, compatible formatting context.
        return [{"index": row["index"], "scene": row["input"] or data["subject"]}
                for row in coverage["plan"]]
