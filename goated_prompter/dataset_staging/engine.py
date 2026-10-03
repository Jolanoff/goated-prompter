"""Field validation and profile-selected modular staging rules."""

from ..dataset_visible_content import visible_content_error
from .normalize import normalize_geometry
from .profiles import get_profile
from .schema import GEOMETRY_FIELDS
from .rules import COMMON_RULES, GeometryContext, rules_for, issue
from .rules.framing import widen_framing


class GeometryValidationError(ValueError):
    def __init__(self, message, correction=None):
        super().__init__(message)
        self.correction = correction or message


def _short_text(value, spec):
    if not isinstance(value, str) or not value.strip() or len(value) > spec.max_length or "\n" in value or "\r" in value or "```" in value:
        raise GeometryValidationError(f"Geometry {spec.name} must contain short single-line descriptions.")
    if error := visible_content_error(value):
        raise GeometryValidationError(error)
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
        raise GeometryValidationError(message, correction)
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
                raise GeometryValidationError(message, correction)
        elif spec.count:
            if type(content) is not int or content < spec.minimum:
                raise GeometryValidationError(f"Invalid {name}; expected an integer >= {spec.minimum}.")
        elif spec.text_array:
            if not isinstance(content, list) or len(content) > spec.max_items:
                raise GeometryValidationError(f"Geometry {name} must be a short array of visible details.")
            cleaned[name] = [_short_text(text, spec) for text in content]
        elif spec.free_text:
            cleaned[name] = _short_text(content, spec)
    return cleaned


def geometry_issues(row, dataset_type=None, *, require_fields=True):
    profile = get_profile(dataset_type)
    try:
        geometry = validate_geometry(row.get("geometry", {}), dataset_type=dataset_type, require_fields=require_fields, scene=row.get("scene", ""))
    except ValueError as exc:
        return [issue("staging_schema", ("geometry",), getattr(exc, "correction", str(exc)))]
    context = GeometryContext(row, geometry, dataset_type, profile.rule_groups)
    issues = [problem for rule in (*COMMON_RULES, *rules_for(profile.rule_groups)) for problem in rule.check(context)]
    return list(dict.fromkeys(issues))


def geometry_errors(row, *, dataset_type=None, require_fields=True):
    return list(dict.fromkeys(problem.message for problem in geometry_issues(row, dataset_type, require_fields=require_fields)))


def resolve_framing_conflicts(row, *, dataset_type=None):
    geometry = validate_geometry(row.get("geometry", {}), dataset_type=dataset_type, scene=row.get("scene", ""))
    profile = get_profile(dataset_type)
    return widen_framing(GeometryContext(row, geometry, dataset_type, profile.rule_groups))
