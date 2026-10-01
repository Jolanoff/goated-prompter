"""Scene Planner service. Dataset owns the session; this skill owns scene ideation."""

import json
import hashlib
from .dataset_visible_content import visible_content_error

from .backends.base import BackendGenerationError
from .prompting.scene_planner import (
    MAX_SCENE_CHARACTERS, MAX_SCENE_WORDS, MAX_IDEA_CHARACTERS, MAX_IDEA_WORDS, scene_planner_instruction,
)


SCENE_PLAN_VERSION = 3
# Saved scenes can include original long guided inputs used as graceful fallbacks
# or plans from older builds. New LLM output uses the stricter shared limits.
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000


def scene_plan_signature(data, coverage):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "variety", "constraints", "visual_style", "custom_style")}
    semantic.update(version=SCENE_PLAN_VERSION, coverage_enabled=coverage["enabled"],
                    assignments=coverage["plan"])
    return hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def validate_saved_scene_plan(rows):
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError("Scene plan must contain at most 25 scenes.")
    cleaned = []
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or set(row) not in ({"index", "input", "scene"}, {"index", "input", "idea", "scene"})
                or type(row["index"]) is not int or row["index"] != index
                or not isinstance(row["input"], str) or len(row["input"]) > 10000
                or not isinstance(row["scene"], str) or len(row["scene"]) > MAX_STORED_SCENE_CHARACTERS):
            raise ValueError("Saved scenes require sequential indexes, input and scene text; idea is optional for legacy plans.")
        if "idea" in row and (not isinstance(row["idea"], str) or len(row["idea"]) > MAX_STORED_IDEA_CHARACTERS):
            raise ValueError("Saved idea must be text within the stored-input limit.")
        cleaned.append(dict(row))
    return cleaned


def reusable_scene_plan(data, coverage):
    rows = validate_saved_scene_plan(data.get("scene_plan", []))
    if (data.get("scene_plan_signature") != scene_plan_signature(data, coverage)
            or len(rows) != data["amount"] or any(not row["scene"].strip() or not row.get("idea", "").strip() for row in rows)
            or any(visible_content_error(row.get("idea", "")) or visible_content_error(row["scene"]) for row in rows)
            or any(row["input"] != assignment["input"] for row, assignment in zip(rows, coverage["plan"]))):
        return None
    return rows


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
        if (not isinstance(row, dict) or set(row) != {"index", "idea", "scene"}
                or type(row["index"]) is not int or row["index"] != index):
            raise ValueError("Scene Planner rows require sequential integer indexes, idea and scene only.")
        idea = row["idea"]
        if (not isinstance(idea, str) or not idea.strip()
                or len(idea) > MAX_IDEA_CHARACTERS or len(idea.split()) > MAX_IDEA_WORDS
                or "```" in idea or "\n" in idea.strip() or "\r" in idea.strip()):
            raise ValueError("Scene Planner ideas must be nonempty short concepts without markdown or multiple lines.")
        scene = row["scene"]
        if (not isinstance(scene, str) or not scene.strip()
                or len(scene) > MAX_SCENE_CHARACTERS or len(scene.split()) > MAX_SCENE_WORDS
                or "```" in scene or "\n" in scene.strip() or "\r" in scene.strip()):
            raise ValueError("Scene Planner scenes must be nonempty concise paragraphs without markdown fences.")
        scene = scene.strip()
        if error := visible_content_error(idea) or visible_content_error(scene):
            raise ValueError(error)
        signature = " ".join(scene.casefold().split())
        if signature in seen:
            raise ValueError("Scene Planner returned identical scenes; use distinct primary events unless guided actions are fixed.")
        seen.add(signature)
        cleaned.append({"index": index, "idea": idea.strip(), "scene": scene})
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
                correction = str(exc) + ' Return only the exact JSON array of {"index": integer, "idea": string, "scene": string}, with concise ideas/scenes and sequential indexes.'
        progress("Scene Planner unavailable; using the supplied concept and guided inputs directly.")
        # Do not guess whether a coverage facet conflicts with natural-language
        # constraints. Keep the original input intact; coverage remains separately
        # available to the writer as subordinate, compatible formatting context.
        return [{"index": row["index"], "idea": row["input"] or data["subject"], "scene": row["input"] or data["subject"]}
                for row in coverage["plan"]]
