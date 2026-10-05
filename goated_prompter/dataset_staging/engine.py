"""Field validation and profile-selected modular staging rules."""

import json

from ..dataset_visible_content import visible_content_error
from .normalize import normalize_geometry
from .profiles import get_profile
from .schema import GEOMETRY_FIELDS
from .rules import COMMON_RULES, GeometryContext, rules_for, issue
from .rules.framing import widen_framing


class GeometryValidationError(ValueError):
    def __init__(self, message, correction=None, fields=()):
        super().__init__(message)
        self.correction = correction or message
        self.fields = tuple(fields)


def _short_text(value, spec):
    if not isinstance(value, str) or not value.strip() or len(value) > spec.max_length or "\n" in value or "\r" in value or "```" in value:
        raise GeometryValidationError(f"Geometry {spec.name} must contain a single-line description of at most {spec.max_length} characters.", fields=(spec.name,))
    if error := visible_content_error(value):
        raise GeometryValidationError(error, fields=(spec.name,))
    return value.strip()


def normalize_staging(value, *, dataset_type=None, scene=""):
    if not isinstance(value, dict):
        return value
    return normalize_geometry(value, profile=get_profile(dataset_type), scene=scene)


def validate_geometry(value, *, dataset_type=None, require_fields=True, scene=""):
    profile = get_profile(dataset_type)
    if not isinstance(value, dict) or value.keys() - GEOMETRY_FIELDS.keys():
        raise GeometryValidationError("Geometry must be an object of supported staging fields.",
            "Use supported geometry keys; camera_view/camera_height are legacy fields. Use camera_azimuth/camera_elevation and keep unusual staging in view_detail or pose_detail.")
    if inapplicable := value.keys() - profile.allowed:
        raise GeometryValidationError(f"Fields are not applicable to {dataset_type}: {', '.join(sorted(inapplicable))}.")
    cleaned = normalize_staging(value, dataset_type=dataset_type, scene=scene)
    if require_fields and (missing := profile.required - cleaned.keys()):
        message = f"{dataset_type} geometry is missing: {', '.join(sorted(missing))}."
        correction = (message + " The gaze_direction field must describe where the eyes are directed, not an emotion or facial expression. "
                      "Keep the same scene and action. Move emotional state into expression if applicable and choose an allowed gaze_direction matching the existing scene."
                      if "gaze_direction" in missing else message)
        raise GeometryValidationError(message, correction, fields=sorted(missing))
    for name, content in cleaned.items():
        spec = GEOMETRY_FIELDS[name]
        values = profile.values_for(name)
        if values is not None:
            if not isinstance(content, str) or content not in values:
                message = f"Invalid {name} {content!r}. Expected one of: {', '.join(sorted(values))}."
                correction = ("The gaze_direction field must describe where the eyes are directed, not an emotion or facial expression. Keep the same scene and action. Move emotional state into expression if applicable and choose an allowed gaze_direction matching the existing scene."
                              if name == "gaze_direction" else f"Invalid {name} {content!r}. Choose an allowed value from the supplied staging schema, or use the applicable detail field for unusual staging.")
                if name == "framing":
                    correction = message + " Do not put camera-distance terminology in framing. Keep the same idea and scene; correct only the staging metadata."
                raise GeometryValidationError(message, correction, fields=(name,))
        elif spec.item_values is not None:
            if (not isinstance(content, list) or len(content) > spec.max_items
                    or any(not isinstance(part, str) or part not in spec.item_values for part in content)):
                raise GeometryValidationError(f"Invalid {name}; expected an array of known anatomical parts.",
                    f"Correct only {name}. Use an array drawn from: {', '.join(sorted(spec.item_values))}. Preserve framing, pose_detail and the required anatomy's meaning; never replace the pose to fix this list.", fields=(name,))
        elif spec.count:
            if type(content) is not int or content < spec.minimum:
                raise GeometryValidationError(f"Invalid {name}; expected an integer >= {spec.minimum}.", fields=(name,))
        elif spec.text_array:
            if not isinstance(content, list) or len(content) > spec.max_items:
                raise GeometryValidationError(f"Geometry {name} must be a short array of visible details.", fields=(name,))
            cleaned[name] = [_short_text(text, spec) for text in content]
        elif spec.free_text:
            cleaned[name] = _short_text(content, spec)
    if require_fields:
        if cleaned.get("pose_type") == "custom" and len(cleaned.get("pose_detail", "").split()) < 4:
            raise GeometryValidationError("Custom pose requires specific pose_detail with physical relationships, not a generic pose label.", fields=("pose_detail",))
        if cleaned.get("body_visibility") == "custom" and not cleaned.get("required_visible_parts"):
            raise GeometryValidationError("Custom body visibility requires nonempty required_visible_parts.", fields=("required_visible_parts",))
    return cleaned


def validate_planned_geometry(value, *, dataset_type=None, scene=""):
    """Canonicalize planner metadata without guessing anatomy from a crop."""
    return validate_geometry(value, dataset_type=dataset_type, scene=scene)


def geometry_issues(row, dataset_type=None, *, require_fields=True):
    profile = get_profile(dataset_type)
    try:
        geometry = validate_geometry(row.get("geometry", {}), dataset_type=dataset_type, require_fields=require_fields, scene=row.get("scene", ""))
    except ValueError as exc:
        return [issue("staging_schema", getattr(exc, "fields", ()) or ("geometry",), getattr(exc, "correction", str(exc)))]
    context = GeometryContext(row, geometry, dataset_type, profile.rule_groups)
    issues = [problem for rule in (*COMMON_RULES, *rules_for(profile.rule_groups)) for problem in rule.check(context)]
    return list(dict.fromkeys(issues))


def geometry_errors(row, *, dataset_type=None, require_fields=True):
    return list(dict.fromkeys(problem.message for problem in geometry_issues(row, dataset_type, require_fields=require_fields)))


def resolve_framing_conflicts(row, *, dataset_type=None, intent=None):
    geometry = validate_geometry(row.get("geometry", {}), dataset_type=dataset_type, scene=row.get("scene", ""))
    if intent is not None and intent.locked:
        return {**row, "geometry": geometry} if "geometry" in row else row
    profile = get_profile(dataset_type)
    return widen_framing(GeometryContext(row, geometry, dataset_type, profile.rule_groups))


POSE_SEMANTIC_FIELDS = ("framing", "camera_distance", "camera_azimuth", "camera_elevation", "view_detail",
    "pose_type", "pose_detail", "body_visibility", "required_visible_parts", "body_orientation",
    "torso_orientation", "hip_orientation", "head_direction", "contact_state", "leg_position",
    "pelvis_tilt", "back_arch", "depth_position", "feet_visibility", "hand_visibility")


def semantic_geometry_fields(row, issues):
    """Locate quoted defects, not infer mechanics from a diagnosis or pose name.

    Callers supply provenance-validated semantic issues. Empty omission evidence
    and uncertain judgments cannot identify a field to unlock.
    """
    geometry = row.get("geometry", {})
    if not isinstance(geometry, dict):
        return set()
    fields = set()
    for problem in issues:
        if "index" in row and problem.get("index", 0) not in (0, row["index"]):
            continue
        evidence = problem.get("evidence", "")
        if not evidence or problem.get("kind") == "uncertain":
            continue
        for name, content in geometry.items():
            spec = GEOMETRY_FIELDS.get(name)
            if not spec:
                continue
            if spec.free_text or spec.text_array:
                values = content if isinstance(content, list) else [content]
                matched = any(isinstance(text, str) and
                    (evidence in text or evidence in json.dumps(text, ensure_ascii=False)) for text in values)
            else:
                # A short enum/count/anatomical item is implicated only by an
                # exact value, not by a coincidental substring of another value.
                values = content if isinstance(content, list) else [content]
                matched = any(evidence == text or evidence == json.dumps(text, ensure_ascii=False) for text in values)
            if matched:
                fields.add(name)
    return fields


def geometry_repair_locks(row, *, dataset_type=None, defective_fields=()):
    """Protect valid semantic fields unrelated to field-specific staging defects."""
    profile = get_profile(dataset_type)
    raw = row.get("geometry", {})
    if not isinstance(raw, dict):
        return {}
    defective = set(defective_fields) | {field for problem in geometry_issues(row, dataset_type) for field in problem.fields}
    for related in (("camera_azimuth", "body_orientation"), ("torso_orientation", "hip_orientation")):
        if defective.intersection(related):
            defective.update(related)  # These corrections can require paired metadata.
    normalized = normalize_staging(raw, dataset_type=dataset_type, scene=row.get("scene", ""))
    if normalized.get("pose_type") == "custom" and (not isinstance(normalized.get("pose_detail"), str) or len(normalized["pose_detail"].split()) < 4):
        defective.add("pose_detail")
    if normalized.get("body_visibility") == "custom" and not normalized.get("required_visible_parts"):
        defective.add("required_visible_parts")
    locks = {}
    for field in POSE_SEMANTIC_FIELDS:
        if field not in normalized or field not in profile.allowed or field in defective:
            continue
        try:
            checked = validate_geometry({field: normalized[field]}, dataset_type=dataset_type, require_fields=False)
        except ValueError:
            continue
        locks.update(checked)
    return locks
