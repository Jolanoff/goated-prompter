"""Scene Planner service. Dataset owns the session; this skill owns scene ideation."""

import json
import hashlib
import logging
from dataclasses import replace
from .dataset_visible_content import visible_content_error
from .dataset_geometry import validate_geometry, geometry_errors, migrate_saved_geometry
from .dataset_coverage import analyze_idea_diversity, idea_action_error, AXES

from .backends.base import BackendGenerationError
from .prompting.scene_planner import (
    MAX_SCENE_CHARACTERS, MAX_SCENE_WORDS, MAX_IDEA_CHARACTERS, MAX_IDEA_WORDS, scene_planner_instruction,
    idea_planner_instruction, scene_composer_instruction,
    SCENE_FORMAT_CORRECTION,
)


SCENE_PLAN_VERSION = 4
SCENE_COMPOSER_CHUNK_SIZE = 4
logger = logging.getLogger(__name__)
PLAN_STATUS_VALUES = {
    "idea_status": {"valid", "not_generated", "duplicate_warning"},
    "scene_status": {"valid", "not_generated", "geometry_warning", "guided_fallback"},
    "prompt_status": {"valid", "not_generated"},
}
# Saved scenes can include original long guided inputs used as graceful fallbacks
# or plans from older builds. New LLM output uses the stricter shared limits.
MAX_STORED_SCENE_CHARACTERS = 10000
MAX_STORED_IDEA_CHARACTERS = 10000


def scene_plan_signature(data, coverage):
    semantic = {key: data.get(key) for key in (
        "subject", "amount", "source_mode", "inputs", "trigger_type", "custom_type",
        "variety", "constraints", "visual_style", "custom_style")}
    semantic["planning_mode"] = data.get("planning_mode", "Fast")
    semantic.update(version=SCENE_PLAN_VERSION, coverage_enabled=coverage["enabled"],
                    assignments=coverage["plan"])
    return hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def validate_saved_scene_plan(rows):
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError("Scene plan must contain at most 25 scenes.")
    cleaned = []
    for index, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or not {"index", "input", "scene"} <= row.keys()
                or row.keys() - {"index", "input", "idea", "scene", "geometry", "coverage_conflicts", *PLAN_STATUS_VALUES}
                or type(row["index"]) is not int or row["index"] != index
                or not isinstance(row["input"], str) or len(row["input"]) > 10000
                or not isinstance(row["scene"], str) or len(row["scene"]) > MAX_STORED_SCENE_CHARACTERS):
            raise ValueError("Saved scenes require sequential indexes, input and scene text; idea is optional for legacy plans.")
        if "idea" in row and (not isinstance(row["idea"], str) or len(row["idea"]) > MAX_STORED_IDEA_CHARACTERS):
            raise ValueError("Saved idea must be text within the stored-input limit.")
        validate_plan_metadata(row)
        row = dict(row)
        if "geometry" in row:
            row["geometry"], migrated = migrate_saved_geometry(row["geometry"])
            if migrated:
                row.update(scene_status="geometry_warning", prompt_status="not_generated")
        cleaned.append(row)
    return cleaned


def reusable_scene_plan(data, coverage, *, require_scenes=True):
    rows = validate_saved_scene_plan(data.get("scene_plan", []))
    if (data.get("scene_plan_signature") != scene_plan_signature(data, coverage)
            or len(rows) != data["amount"] or any(not row.get("idea", "").strip() for row in rows)
            or (require_scenes and any(not row["scene"].strip() or row.get("scene_status") in {"not_generated", "geometry_warning"} for row in rows))
            or any(visible_content_error(row.get("idea", "")) or visible_content_error(row["scene"]) for row in rows)
            or any(row["input"] != assignment["input"] for row, assignment in zip(rows, coverage["plan"]))):
        return None
    return rows


def validate_plan_metadata(row):
    for key, allowed in PLAN_STATUS_VALUES.items():
        if key in row and (not isinstance(row[key], str) or row[key] not in allowed):
            raise ValueError(f"Invalid {key}.")
    if "coverage_conflicts" in row and (not isinstance(row["coverage_conflicts"], list)
            or len(row["coverage_conflicts"]) > len(AXES)
            or any(not isinstance(key, str) or key not in AXES for key in row["coverage_conflicts"])):
        raise ValueError("Coverage conflicts must be supported axis names.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Scene Planner returned duplicate JSON keys.")
        result[key] = value
    return result


def validate_scene_plan(raw, amount, *, guided_inputs=None, indexes=None, require_geometry=False, validate_geometry_fields=True):
    """Accept only the minimal JSON schema; never salvage fenced/broken output."""
    if guided_inputs is not None and (not isinstance(guided_inputs, list) or len(guided_inputs) != amount
                                     or any(not isinstance(value, str) for value in guided_inputs)):
        raise ValueError("Guided validation requires one source input per requested scene.")
    if not isinstance(raw, str):
        raise ValueError("Scene Planner must return a valid JSON array.")
    rows = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or len(rows) != amount:
        raise ValueError("Scene Planner must return exactly one scene per requested image.")
    cleaned, seen = [], {}
    indexes = indexes or list(range(1, amount + 1))
    for position, (index, row) in enumerate(zip(indexes, rows)):
        if (not isinstance(row, dict) or not {"index", "idea", "scene"} <= row.keys()
                or row.keys() - {"index", "idea", "scene", "geometry", "coverage_conflicts"}
                or (require_geometry and "geometry" not in row)
                or type(row["index"]) is not int or row["index"] != index):
            raise ValueError("Scene Planner rows require requested integer indexes, idea, scene and optional geometry/coverage conflicts.")
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
        guided_input = " ".join(guided_inputs[position].split()) if guided_inputs is not None else ""
        if signature in seen:
            # Cycling/repeated authoritative guided lines may deliberately ask
            # for the same scene. Never exempt random or different guided inputs.
            if not guided_input or guided_input != seen[signature]:
                raise ValueError("Scene Planner returned identical scenes for different assignments; diversify while preserving each input. Exact repeats are allowed only for the same nonempty guided input.")
        seen[signature] = guided_input
        record = {"index": index, "idea": idea, "scene": scene}
        if "geometry" in row:
            record["geometry"] = validate_geometry(row["geometry"]) if validate_geometry_fields else row["geometry"]
        validate_plan_metadata(row)
        if "coverage_conflicts" in row:
            record["coverage_conflicts"] = row["coverage_conflicts"]
        cleaned.append(record)
    return cleaned


def validate_idea_plan(raw, indexes):
    rows = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or len(rows) != len(indexes):
        raise ValueError("Idea Planner must return exactly the requested ideas.")
    for row, index in zip(rows, indexes):
        if (not isinstance(row, dict) or set(row) != {"index", "idea"}
                or type(row["index"]) is not int or row["index"] != index):
            raise ValueError("Idea Planner requires requested integer indexes and idea only.")
        idea = row["idea"]
        if (not isinstance(idea, str) or not idea.strip() or len(idea) > MAX_IDEA_CHARACTERS
                or len(idea.split()) > MAX_IDEA_WORDS or "\n" in idea or "\r" in idea or "```" in idea):
            raise ValueError("Idea Planner ideas must be short single-line concepts.")
        if error := visible_content_error(idea):
            raise ValueError(error)
        row["idea"] = idea.strip()
    return rows


class ScenePlanner:
    """Fast batch or Quality ideas/composition, with bounded local repairs."""

    def __init__(self, checkpoint):
        self.checkpoint = checkpoint

    def plan_batch(self, *, session, data, coverage, family="qwen", progress, plan_update=None):
        if data.get("planning_mode", "Fast") == "Quality":
            try:
                ideas = self.plan_ideas(session=session, data=data, coverage=coverage, family=family, progress=progress)
            except BackendGenerationError:
                return self._fallback(data, coverage, progress)
            if plan_update:
                plan_update([{**row, "scene": "", "geometry": {}, "scene_status": "not_generated"} for row in ideas])
            return self.compose(session=session, data=data, coverage=coverage, ideas=ideas, family=family,
                                progress=progress, plan_update=plan_update)
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
                guided_inputs = ([row["input"] for row in coverage["plan"]]
                                 if data["source_mode"] == "guided" else None)
                rows = validate_scene_plan(raw, data["amount"], guided_inputs=guided_inputs, validate_geometry_fields=False)
            except (ValueError, TypeError, RecursionError, BackendGenerationError) as exc:
                # A checkpoint outside the handler preserves pause/cancellation
                # even when the model call itself fails.
                self.checkpoint()
                progress(f"Scene Planner failed validation: {exc}")
                correction = str(exc) + ' Return only the requested JSON array with index, idea, scene and geometry.'
            else:
                return self._check_scenes(session, data, coverage, rows, family, progress, plan_update=plan_update)
        return self._fallback(data, coverage, progress)

    def _fallback(self, data, coverage, progress):
        if data["source_mode"] != "guided":
            raise BackendGenerationError("Dataset planning failed after retries. No useful automatic ideas were produced; revise the concept or retry planning.")
        progress("Scene Planner unavailable; using each supplied guided input directly.")
        # Do not guess whether a coverage facet conflicts with natural-language
        # constraints. Keep the original input intact; coverage remains separately
        # available to the writer as subordinate, compatible formatting context.
        return [{"index": row["index"], "idea": row["input"] or data["subject"], "scene": row["input"] or data["subject"]}
                for row in coverage["plan"]]

    def _call(self, session, build, validate, progress, label, *, scene_output=False):
        correction = ""
        previous_output = ""
        last_error = None
        for attempt in range(2):
            self.checkpoint()
            progress(f"{label} · {'repairing output' if attempt else 'planning'}…")
            try:
                instruction = build(correction)
                if scene_output and previous_output:
                    context = json.loads(instruction.user_message)
                    context["previous_response"] = previous_output[:instruction.stream_character_limit]
                    instruction = replace(instruction, user_message=json.dumps(context, ensure_ascii=False))
                session.validate_instruction(instruction)
                raw = session.generate(instruction)
                previous_output = raw if isinstance(raw, str) else ""
                self.checkpoint()
                return validate(raw)
            except json.JSONDecodeError as exc:
                self.checkpoint()
                last_error = exc
                logger.warning("%s JSON parse failure: %s", label, exc, exc_info=True)
                correction = SCENE_FORMAT_CORRECTION if scene_output else "Return only one valid JSON array of the requested ideas. No YAML, Markdown or commentary."
                progress(f"{label} returned invalid JSON; repairing output format only.")
            except (ValueError, TypeError, RecursionError, BackendGenerationError) as exc:
                self.checkpoint()
                last_error = exc
                correction = getattr(exc, "correction", str(exc))
                logger.warning("%s validation failure: %s", label, exc)
                progress(f"{label} failed validation: {correction}")
        raise BackendGenerationError(f"Dataset {label} failed after retries. {correction}") from last_error

    def plan_ideas(self, *, session, data, coverage, family="qwen", progress, indexes=None, existing=()):
        indexes = indexes or list(range(1, data["amount"] + 1))
        previous = {row["index"]: row["idea"] for row in existing if row["index"] in indexes}
        def validate_initial(raw):
            result = validate_idea_plan(raw, indexes)
            for row in result:
                if row["index"] in previous:
                    comparison = [{"index": 0, "idea": previous[row["index"]]}, row]
                    if analyze_idea_diversity(data, comparison)["uniqueness"] < 100:
                        raise ValueError("Create a genuinely new idea rather than repeating the replaced idea.")
            return result
        rows = self._call(session,
            lambda correction: idea_planner_instruction(data, coverage, family, correction, indexes=indexes, existing=existing),
            validate_initial, progress, "Idea Planner")
        # Audit locally, then replace only later members of duplicate groups.
        # Guided/Focused scope exemptions live in the diversity checker.
        accepted = [dict(row) for row in existing if row["index"] not in indexes]
        for position, row in enumerate(rows):
            audit = analyze_idea_diversity(data, accepted + [row])
            if any(record["issues"] for record in audit["ideas"] if record["index"] == row["index"]):
                exclusions = accepted + rows[position + 1:]
                def validate_new(raw):
                    new = validate_idea_plan(raw, [row["index"]])
                    audit = analyze_idea_diversity(data, exclusions + new)
                    if any(record["issues"] for record in audit["ideas"] if record["index"] == row["index"]):
                        raise ValueError("Replacement idea still repeats an existing idea's meaning.")
                    return new
                rows[position] = self._call(session,
                    lambda correction: idea_planner_instruction(data, coverage, family, correction,
                        indexes=[row["index"]], existing=exclusions),
                    validate_new, progress, f"Idea Planner · replace idea {row['index']}")[0]
            accepted.append(rows[position])
        return rows

    def compose(self, *, session, data, coverage, ideas, family="qwen", progress, plan_update=None):
        # Always publish a loadable state with every fixed idea, including pending
        # chunks. A retry/reload can compose only unfinished rows, never re-ideate.
        state = [{**row, "scene": "", "geometry": {}, "scene_status": "not_generated"} for row in ideas]
        def publish_chunk(rows):
            by_index = {row["index"]: row for row in rows}
            for position, item in enumerate(state):
                if item["index"] in by_index:
                    state[position] = dict(by_index[item["index"]])
            if plan_update:
                plan_update([dict(item) for item in state])
        for start in range(0, len(ideas), SCENE_COMPOSER_CHUNK_SIZE):
            chunk = ideas[start:start + SCENE_COMPOSER_CHUNK_SIZE]
            indexes = [row["index"] for row in chunk]
            inputs = [coverage["plan"][index - 1]["input"] for index in indexes] if data["source_mode"] == "guided" else None
            rows = self._call(session,
                lambda correction: scene_composer_instruction(data, coverage, chunk, family, correction),
                lambda raw: validate_scene_plan(raw, len(chunk), indexes=indexes, guided_inputs=inputs,
                                                validate_geometry_fields=False),
                progress, f"Scene Composer · chunk {indexes[0]}–{indexes[-1]}", scene_output=True)
            existing = {row["index"]: row for row in [*data.get("scene_plan", []), *state[:start]]
                        if row["index"] not in indexes and row.get("scene", "").strip()
                        and row.get("scene_status", "valid") == "valid"}
            rows = self._check_scenes(session, data, coverage, rows, family, progress, chunk, publish_chunk,
                                      existing_rows=list(existing.values()))
            publish_chunk([{**row, "scene_status": "valid"} for row in rows])
        return [{key: value for key, value in row.items() if key != "scene_status"} for row in state]

    def _check_scenes(self, session, data, coverage, rows, family, progress, ideas=None, plan_update=None, existing_rows=()):
        fixed = {row["index"]: row["idea"] for row in (ideas or rows)}
        checked = list(existing_rows)
        for position, row in enumerate(rows):
            try:
                if "geometry" in row:
                    row["geometry"] = validate_geometry(row["geometry"], character=ideas is not None and data["trigger_type"] == "Character")
                elif ideas is not None:
                    raise ValueError("Scene Composer must include a structured geometry object.")
                errors = geometry_errors(row)
            except ValueError as exc:
                logger.warning("Scene %s geometry validation failure: %s", row["index"], exc)
                errors = [getattr(exc, "correction", str(exc))]
            if data.get("planning_mode") == "Quality":
                if error := idea_action_error(fixed[row["index"]], row["scene"]):
                    errors.append(error)
            if row["idea"] != fixed[row["index"]]:
                errors.append("Echo the fixed idea unchanged; compose it instead of replacing it.")
            if error := duplicate_scene_error(row, checked, data, coverage):
                errors.append(error)
            if errors:
                if plan_update:
                    # Publish loadable stage state even if a local repair later fails.
                    pending = [{**item, "idea": fixed[item["index"]]} for item in rows]
                    for item in pending:
                        try:
                            item["geometry"] = validate_geometry(item.get("geometry", {}))
                        except ValueError:
                            item["geometry"] = {}
                            item["scene_status"] = "geometry_warning"
                        if geometry_errors(item, character=ideas is not None and data["trigger_type"] == "Character"):
                            item["scene_status"] = "geometry_warning"
                    pending[position]["scene_status"] = "geometry_warning"
                    plan_update(pending)
                rows[position] = self.repair_scene(session=session, data=data, coverage=coverage,
                    row={**row, "idea": fixed[row["index"]]}, family=family, progress=progress, errors=errors,
                    existing_rows=checked)
            rows[position] = reconcile_scene_coverage(rows[position], coverage["plan"][row["index"] - 1])
            checked.append(rows[position])
        return rows

    def repair_scene(self, *, session, data, coverage, row, family="qwen", progress, errors=(), existing_rows=()):
        def validate(raw):
            result = validate_scene_plan(raw, 1, indexes=[row["index"]], require_geometry=True)[0]
            result["geometry"] = validate_geometry(result["geometry"], character=data["trigger_type"] == "Character")
            if result["idea"] != row["idea"]:
                raise ValueError("Repair must preserve the fixed idea exactly.")
            if problems := geometry_errors(result):
                raise ValueError(" ".join(problems))
            if error := duplicate_scene_error(result, existing_rows, data, coverage):
                raise ValueError(error)
            if data.get("planning_mode") == "Quality" and (error := idea_action_error(row["idea"], result["scene"])):
                raise ValueError(error)
            return result
        result = self._call(session,
            lambda correction: scene_composer_instruction(data, coverage, [row], family,
                (correction + "\n" + " ".join(errors) if correction.startswith("SCENE OUTPUT FORMAT CORRECTION")
                 else " ".join(errors) + " " + correction)
                + " Preserve the fixed idea, important action and required props.", previous=row),
            validate, progress, f"Scene Composer · repair scene {row['index']}", scene_output=True)
        return reconcile_scene_coverage(result, coverage["plan"][row["index"] - 1])


def duplicate_scene_error(row, existing, data, coverage):
    """Retain the old batch duplicate guard across chunk boundaries."""
    signature = " ".join(row["scene"].casefold().split())
    for other in existing:
        if other["index"] == row["index"] or " ".join(other["scene"].casefold().split()) != signature:
            continue
        source = coverage["plan"][row["index"] - 1]["input"]
        previous = coverage["plan"][other["index"] - 1]["input"]
        if data["source_mode"] == "guided" and source.strip() and " ".join(source.split()) == " ".join(previous.split()):
            continue
        return "This scene duplicates another assignment. Compose only this fixed idea as a distinct scene; do not change or brainstorm ideas."
    return ""


def reconcile_scene_coverage(row, assignment):
    """Record omitted framing rather than forcing it back into the writer."""
    conflicts = set(row.get("coverage_conflicts", []))
    requested = assignment.get("facets", {}).get("framing", "")
    actual = row.get("geometry", {}).get("framing", "").casefold()
    focus = " ".join(row.get("geometry", {}).get("visibility_focus", [])).casefold()
    if requested in {"face close-up", "head-and-shoulders"} and (
            actual in {"full_body", "full_body_with_environment", "three_quarter_body", "wide", "extreme_wide"}
            or any(word in focus.split() for word in ("feet", "shoes"))):
        conflicts.add("framing")
    if conflicts:
        row = {**row, "coverage_conflicts": sorted(conflicts)}
    return row
