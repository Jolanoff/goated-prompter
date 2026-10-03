"""Dataset-type applicability and rule selection, independent of planning mode."""

from dataclasses import dataclass
from .schema import GEOMETRY_FIELDS


@dataclass(frozen=True)
class StagingProfile:
    required: frozenset[str]
    recommended: frozenset[str]
    allowed: frozenset[str]
    rule_groups: tuple[str, ...]


COMMON_FIELDS = frozenset("""
framing camera_azimuth camera_elevation camera_distance view_detail
subject_position subject_scale composition depth_position occlusion
visibility_focus action_focus action_visibility
primary_subject_count secondary_subject_count
""".split())

CHARACTER_REQUIRED_FIELDS = frozenset("""
framing camera_azimuth body_orientation head_direction gaze_direction face_visibility
""".split())


def _profile(required="", recommended="", extra="", groups=(), *, allowed=None):
    return StagingProfile(
        frozenset(required.split()),
        frozenset(recommended.split()),
        COMMON_FIELDS | frozenset(extra.split()) if allowed is None else frozenset(allowed),
        groups,
    )


STAGING_PROFILES = {
    "Character": _profile(
        " ".join(sorted(CHARACTER_REQUIRED_FIELDS)),
        """
        camera_elevation camera_distance
        torso_orientation hip_orientation
        pose_type pose_detail
        leg_position pelvis_tilt back_arch
        expression movement
        body_visibility hand_visibility feet_visibility
        contact_state
        action_focus visibility_focus
        composition occlusion
        """,
        groups=("character",),
        allowed=GEOMETRY_FIELDS,
    ),
    "Multiple characters": _profile(
        "framing camera_azimuth composition primary_subject_count action_visibility",
        """
        camera_elevation camera_distance
        subject_scale occlusion
        visibility_focus action_focus
        contact_state
        """,
        extra="contact_state",
        groups=("multiple_characters",),
    ),
    "Animal": _profile(
        recommended="""
        framing camera_azimuth camera_elevation camera_distance
        subject_orientation subject_scale movement
        action_visibility occlusion composition
        visibility_focus action_focus pose_detail
        """,
        extra="subject_orientation movement pose_detail contact_state",
        groups=("animal",),
    ),
    "Object / product": _profile(
        recommended="""
        framing camera_azimuth camera_elevation camera_distance
        subject_orientation subject_position subject_scale
        composition depth_position occlusion contact_state visibility_focus
        """,
        extra="subject_orientation contact_state",
        groups=("product",),
    ),
    "Visual style": _profile(
        recommended="""
        framing camera_azimuth camera_elevation camera_distance
        composition subject_position subject_scale depth_position visibility_focus
        """,
    ),
    "Location / environment": _profile(
        recommended="""
        framing camera_elevation camera_distance
        composition depth_position occlusion visibility_focus
        """,
        groups=("environment",),
    ),
    "Brand / logo": _profile(
        recommended="""
        framing camera_azimuth camera_elevation
        subject_position subject_scale composition depth_position occlusion visibility_focus
        """,
        groups=("brand_text",),
    ),
    "Typography / text": _profile(
        recommended="""
        framing subject_position subject_scale composition depth_position occlusion visibility_focus
        """,
        groups=("brand_text",),
    ),
    "Concept": _profile(
        recommended="framing composition visibility_focus",
    ),
    "Custom": _profile(
        recommended="framing composition action_focus visibility_focus",
        extra="subject_orientation movement pose_detail contact_state leg_position pelvis_tilt back_arch",
    ),
}


def get_profile(dataset_type):
    # None is only for field-wise validation of saved/pending geometry. Live
    # planning always supplies the selected type, never infers a Character.
    if dataset_type is None:
        return StagingProfile(frozenset(), frozenset(), frozenset(GEOMETRY_FIELDS), ())
    try:
        return STAGING_PROFILES[dataset_type]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unsupported Dataset staging type: {dataset_type!r}.") from exc


for _name, _profile_spec in STAGING_PROFILES.items():
    if not _profile_spec.required <= _profile_spec.allowed <= GEOMETRY_FIELDS.keys() or not _profile_spec.recommended <= _profile_spec.allowed:
        raise RuntimeError(f"Invalid staging profile {_name}.")
