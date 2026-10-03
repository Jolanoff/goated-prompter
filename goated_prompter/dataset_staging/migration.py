"""Conservative saved-plan migration, not an alternative live-output validator."""

from .engine import validate_geometry
from .normalize import normalize_field, normalize_geometry_value
from .profiles import get_profile
from .schema import GEOMETRY_FIELDS
from .vocabulary import CAMERA_AZIMUTH_VALUES, GAZE_DIRECTION_VALUES, EXPRESSION_VALUES, POSE_TYPE_VALUES, ORIENTATION_VALUES

# Only facts known from the old dimension are moved to a new axis. A high-angle
# view says nothing about front/rear, and an exact physical height need not imply
# an elevation relative to an unspecified subject.
LEGACY_VIEW_ELEVATIONS = {
    "overhead": "overhead", "birds_eye": "overhead", "high_angle": "high",
    "low_angle": "low", "ground_level": "ground_level", "worms_eye": "ground_level",
    "top_down": "overhead",
}
LEGACY_HEIGHT_ELEVATIONS = {
    "eye_level": "eye_level", "slightly_above_eye_level": "slightly_above",
    "high": "high", "overhead": "overhead", "ground_level": "ground_level",
}
LEGACY_POSES = {"bent_forward": "bending", "bent_over": "bending", "bent_over_deep": "bending",
                "lying_face_up": "lying_face_up", "lying_face_down": "lying_face_down",
                "lying_on_left_side": "lying_on_side", "lying_on_right_side": "lying_on_side",
                "kneeling_upright": "kneeling", "kneeling_forward": "kneeling"}
LEGACY_HEAD_DIRECTIONS = {"looking_at_partner": "toward_secondary_subject", "looking_at_genital": "toward_action", "looking_down_at_self": "down"}


def migrate_saved_geometry(value, *, dataset_type=None):
    """Return (canonical geometry, needs_local_repair), never guess missing facts.

    Safe field renames alone do not invalidate a saved scene. Unknown/ambiguous
    fields are omitted or preserved as detail, and flag this row rather than
    failing the entire draft. Inapplicable human fields are safely discarded.
    """
    profile = get_profile(dataset_type)
    if not isinstance(value, dict):
        return {}, True
    cleaned, needs_repair = {}, False

    def put(name, content):
        nonlocal needs_repair
        if name not in profile.allowed:
            return
        if name in cleaned and cleaned[name] != content:
            needs_repair = True
            return  # Explicit current fields win over a conflicting legacy field.
        cleaned[name] = content

    def detail(name, content):
        nonlocal needs_repair
        if name not in profile.allowed:
            return
        text = " ".join(str(content).replace("_", " ").split())
        if not text:
            needs_repair = True
            return
        joined = cleaned.get(name, "")
        joined = joined + ", " + text if joined and text not in joined else joined or text
        if len(joined) > GEOMETRY_FIELDS[name].max_length:
            needs_repair = True
            joined = joined[:GEOMETRY_FIELDS[name].max_length]
        cleaned[name] = joined

    # Current fields have priority. Old mixed dimensions are dealt with below.
    for name, content in value.items():
        if name not in GEOMETRY_FIELDS or name not in profile.allowed:
            continue
        canonical = normalize_field(name, content)
        if name in {"body_orientation", "torso_orientation", "hip_orientation"} and isinstance(canonical, str) and canonical not in ORIENTATION_VALUES:
            continue
        if name == "pose_type" and isinstance(canonical, str) and canonical not in POSE_TYPE_VALUES:
            continue
        if name == "camera_distance" and canonical in ("macro", "extreme_close_detail"):
            continue
        if name == "head_direction" and isinstance(canonical, str) and canonical not in GEOMETRY_FIELDS[name].values:
            continue
        try:
            cleaned.update(validate_geometry({name: content}, dataset_type=dataset_type, require_fields=False))
        except ValueError:
            needs_repair = True

    for name, content in value.items():
        canonical = normalize_geometry_value(content)
        if not isinstance(canonical, str):
            if name in {"camera_view", "camera_height", "gaze", "pose"} or name not in GEOMETRY_FIELDS:
                needs_repair = True
            continue
        if name == "camera_view":
            if canonical in CAMERA_AZIMUTH_VALUES:
                put("camera_azimuth", canonical)
            elif canonical in LEGACY_VIEW_ELEVATIONS:
                put("camera_elevation", LEGACY_VIEW_ELEVATIONS[canonical])
            else:
                detail("view_detail", content)
                needs_repair = True  # No inferred side for profile/side/intimate/compound views.
        elif name == "camera_height":
            if canonical in LEGACY_HEIGHT_ELEVATIONS:
                put("camera_elevation", LEGACY_HEIGHT_ELEVATIONS[canonical])
            else:
                detail("view_detail", "camera height " + content)
        elif name == "camera_distance" and canonical in {"macro", "extreme_close_detail"}:
            # Keep the exact older description; a magnification label alone does
            # not establish a camera distance.
            cleaned.pop(name, None)
            detail("view_detail", content)
        elif name == "gaze":
            needs_repair = True  # Preserve the historical legacy-gaze review behavior.
            if canonical in GAZE_DIRECTION_VALUES:
                put("gaze_direction", canonical)
            elif canonical.startswith("focused_on_"):
                put("gaze_direction", "toward_action")
                put("expression", "focused")
            elif canonical in EXPRESSION_VALUES - {"custom"}:
                put("expression", canonical)
        elif name in {"pose", "pose_type"} and isinstance(canonical, str):
            if "pose_type" in profile.allowed:
                put("pose_type", canonical if canonical in POSE_TYPE_VALUES else "custom")
            if canonical not in POSE_TYPE_VALUES:
                detail("pose_detail", content)
        elif name in {"body_orientation", "torso_orientation", "hip_orientation"} and isinstance(canonical, str) and canonical not in ORIENTATION_VALUES:
            put("pose_type", LEGACY_POSES.get(canonical, "custom"))
            detail("pose_detail", name.removesuffix("_orientation") + " " + content)
            needs_repair = True  # Pose does not reveal which side faces the camera.
        elif name == "body_orientation" and "body_orientation" not in profile.allowed and "subject_orientation" in profile.allowed and canonical in ORIENTATION_VALUES:
            put("subject_orientation", canonical)
        elif name == "head_direction" and canonical in LEGACY_HEAD_DIRECTIONS and canonical not in GEOMETRY_FIELDS[name].values:
            put(name, LEGACY_HEAD_DIRECTIONS[canonical])
        elif name == "head_direction" and isinstance(canonical, str) and canonical not in GEOMETRY_FIELDS[name].values:
            detail("pose_detail", "head " + content)
            needs_repair = True
        elif name not in GEOMETRY_FIELDS and name not in {"camera_view", "camera_height", "gaze", "pose"}:
            needs_repair = True

    # Validate each retained field separately: one unsupported fact cannot erase
    # its valid siblings or the saved idea/scene/prompt.
    result = {}
    for name, content in cleaned.items():
        try:
            result.update(validate_geometry({name: content}, dataset_type=dataset_type, require_fields=False))
        except ValueError:
            needs_repair = True
    if value and profile.required - result.keys():
        needs_repair = True
    return result, needs_repair
