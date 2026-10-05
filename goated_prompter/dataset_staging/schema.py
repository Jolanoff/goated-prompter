"""Single field registry shared by normalization, validation and planner schemas."""

from dataclasses import dataclass
from . import vocabulary as v


@dataclass(frozen=True)
class FieldSpec:
    name: str
    values: frozenset[str] | None = None
    free_text: bool = False
    count: bool = False
    text_array: bool = False
    description: str = ""
    minimum: int = 0
    max_length: int = 160
    max_items: int = 12
    item_values: frozenset[str] | None = None


GEOMETRY_FIELDS = {
    spec.name: spec for spec in (
        FieldSpec("framing", v.FRAMING_VALUES,
                  description="Camera crop, composition and visual emphasis, independent of anatomical visibility and pose. Required feet, knees or hands never automatically widen framing; pose_detail places them inside the composition."),
        FieldSpec("camera_azimuth", v.CAMERA_AZIMUTH_VALUES,
                  description="Which side is presented to the camera, not world-space direction. Unsided front_three_quarter does not imply left or right."),
        FieldSpec("camera_elevation", v.CAMERA_ELEVATION_VALUES,
                  description="Camera elevation relative to the viewed scene/subject, independent of azimuth."),
        FieldSpec("camera_distance", v.CAMERA_DISTANCE_VALUES,
                  description="How physically near or far the camera is from the subject, independent of framing, viewing side and elevation."),
        FieldSpec("view_detail", free_text=True,
                  description="Unusual viewpoint, roll, perspective or exact camera staging not captured by the axes."),
        FieldSpec("body_orientation", v.BODY_ORIENTATION_VALUES,
                  description="Side of the body presented to camera, never pose/body state."),
        FieldSpec("torso_orientation", v.TORSO_ORIENTATION_VALUES,
                  description="Camera-relative side of torso, not bending or twisting mechanics."),
        FieldSpec("hip_orientation", v.HIP_ORIENTATION_VALUES,
                  description="Camera-relative side of hips, not pose."),
        FieldSpec("subject_orientation", v.SUBJECT_ORIENTATION_VALUES,
                  description="Camera-relative side of a non-human subject/object."),
        FieldSpec("head_direction", v.HEAD_DIRECTION_VALUES,
                  description="Where the head points, independently of gaze. Supported head/eye-position states such as eyes_rolled belong here, never in gaze_direction."),
        FieldSpec("gaze_direction", v.GAZE_DIRECTION_VALUES,
                  description="GAZE_DIRECTION describes where the eyes are directed, never emotion, facial expression or head position."),
        FieldSpec("expression", v.EXPRESSION_VALUES,
                  description="EXPRESSION describes visible emotion/facial state, separate from eye direction. Never place emotional language inside gaze_direction."),
        FieldSpec("expression_detail", free_text=True,
                  description="Optional unusual expression description."),
        FieldSpec("pose_type", v.POSE_TYPE_VALUES,
                  description="Broad body mechanics. Use custom for long-tail poses; custom requires specific pose_detail, not a generic pose label."),
        FieldSpec("pose_detail", free_text=True, max_length=1600,
                  description="Physical staging: support/contact, torso and hip/shoulder relationship, limb directions, joint bends, self/object contact, overlap/depth and unusual visible extremities as applicable. Simple poses may be concise; complex poses need several short clauses. No new pose enum is needed."),
        FieldSpec("movement", v.MOVEMENT_VALUES,
                  description="Visible motion/body state."),
        FieldSpec("leg_position", v.LEG_POSITION_VALUES,
                  description="Position and openness of the legs."),
        FieldSpec("pelvis_tilt", v.PELVIS_TILT_VALUES,
                  description="Pelvis / hip tilt relative to neutral."),
        FieldSpec("back_arch", v.BACK_ARCH_VALUES,
                  description="Degree of lumbar / back arch."),
        FieldSpec("face_visibility", v.FACE_VISIBILITY_VALUES,
                  description="Face visibility in the selected view."),
        FieldSpec("body_visibility", v.BODY_VISIBILITY_VALUES,
                  description="Anatomical visibility, independent of framing. Use custom plus required_visible_parts for non-contiguous anatomy such as face, torso and feet."),
        FieldSpec("required_visible_parts", item_values=v.BODY_PART_VALUES, max_items=len(v.BODY_PART_VALUES),
                  description="Array of anatomical parts that must remain visible. Controls anatomical visibility only; must never automatically widen or change framing. Required and nonempty when body_visibility=custom; optional otherwise."),
        FieldSpec("hand_visibility", v.HAND_VISIBILITY_VALUES,
                  description="Visibility of human hands."),
        FieldSpec("feet_visibility", v.FEET_VISIBILITY_VALUES,
                  description="Visibility of human feet, independent of crop. Folded, inverted or foreshortened feet may appear within tight framing."),
        FieldSpec("subject_position", v.SUBJECT_POSITION_VALUES,
                  description="Position within the image."),
        FieldSpec("subject_scale", v.SUBJECT_SCALE_VALUES,
                  description="Subject scale within the image."),
        FieldSpec("action_visibility", v.ACTION_VISIBILITY_VALUES,
                  description="Readability of the main action/interaction."),
        FieldSpec("contact_state", v.CONTACT_STATE_VALUES,
                  description="Subject/object relationship to an interacting object or support. For unusual load-bearing contacts not accurately described by ordinary standing/sitting labels, use supporting and establish the actual external contact in pose_detail. This enum is not a substitute for a load path."),
        FieldSpec("occlusion", v.OCCLUSION_VALUES,
                  description="Extent of relevant subject/feature occlusion."),
        FieldSpec("depth_position", v.DEPTH_POSITION_VALUES,
                  description="Depth placement in the scene."),
        FieldSpec("composition", v.COMPOSITION_VALUES,
                  description="Scene-level arrangement."),
        FieldSpec("head_turn", v.TURN_AMOUNT_VALUES,
                  description="Head turn magnitude, not gaze."),
        FieldSpec("action_focus", free_text=True,
                  description="Concise activity/interaction; scene prose remains authoritative."),
        FieldSpec("visibility_focus", text_array=True,
                  description="Short array of important visible regions/objects/features, not an exhaustive inventory."),
        FieldSpec("primary_subject_count", count=True, minimum=1,
                  description="Explicit primary subject count, a positive integer."),
        FieldSpec("secondary_subject_count", count=True,
                  description="Explicit secondary subject count, a nonnegative integer."),
    )
}

# Derived compatibility views, never separately maintained field definitions.
GEOMETRY_ENUMS = {name: spec.values for name, spec in GEOMETRY_FIELDS.items() if spec.values is not None}
FREE_TEXT_FIELDS = frozenset(name for name, spec in GEOMETRY_FIELDS.items() if spec.free_text)
COUNT_FIELDS = frozenset(name for name, spec in GEOMETRY_FIELDS.items() if spec.count)
CUSTOM_DETAIL_FIELDS = {"pose_type": "pose_detail", "expression": "expression_detail"}
