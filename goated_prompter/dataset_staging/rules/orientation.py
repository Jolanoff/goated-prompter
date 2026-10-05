"""Camera-relative presentation tables, distinct from pose mechanics."""

from . import Rule, issue

ORIENTATION_SIDES = {
    "front": "front", "front_three_quarter": "front",
    "front_three_quarter_left": "front", "front_three_quarter_right": "front",
    "direct_rear": "rear", "rear_three_quarter_left": "rear", "rear_three_quarter_right": "rear",
}
OPPOSED_PROFILES = {("profile_left", "profile_right"), ("profile_right", "profile_left")}


def presentation_issues(context, field):
    view, orientation = context.geometry.get("camera_azimuth"), context.geometry.get(field)
    sides = ORIENTATION_SIDES.get(view), ORIENTATION_SIDES.get(orientation)
    if all(sides) and sides[0] != sides[1]:
        return [issue("opposed_presentation", ("camera_azimuth", field),
            "Camera view and subject orientation describe opposing sides relative to camera. Keep one coherent front/rear relationship.")]
    if (view, orientation) in OPPOSED_PROFILES:
        return [issue("opposed_profiles", ("camera_azimuth", field),
            "Camera and subject specify opposite profile sides relative to camera.")]
    return []


def subject_presentation(context):
    return presentation_issues(context, "subject_orientation")


def body_presentation(context):
    problems = presentation_issues(context, "body_orientation")
    if (context.geometry.get("pose_type") != "custom"
            and {context.geometry.get("torso_orientation"), context.geometry.get("hip_orientation")} == {"front", "direct_rear"}):
        problems.append(issue("opposed_torso_hips", ("torso_orientation", "hip_orientation"),
            "Torso and hips require an impossible opposing front/rear twist."))
    return problems


SUBJECT_ORIENTATION_RULES = (Rule("subject_presentation", subject_presentation),)
BODY_ORIENTATION_RULES = (Rule("body_presentation", body_presentation),)
