"""Canonical, machine-checkable staging values. No rules or migrations live here."""

FRAMING_VALUES = frozenset("""
extreme_close_up detail_close_up face_close_up head_and_shoulders
upper_body waist_up three_quarter_body full_body
full_body_with_environment full_subject full_subject_with_environment
wide extreme_wide
""".split())

FRAMING_ALIASES = {
    "upper_body": "waist_up",
    "medium": "waist_up", "medium_shot": "waist_up",
    "medium_full": "three_quarter_body", "cowboy_shot": "three_quarter_body",
    "close_up": "face_close_up", "closeup": "face_close_up", "face_closeup": "face_close_up",
    "medium_close_up": "waist_up", "long_shot": "full_body_with_environment", "wide_shot": "wide",
}

CHARACTER_FRAMING_VALUES = FRAMING_VALUES - {"detail_close_up", "full_subject", "full_subject_with_environment"}
PRODUCT_FRAMING_VALUES = frozenset("detail_close_up full_subject full_subject_with_environment wide extreme_wide".split())

# The unsided three-quarter fact is intentionally retained: never guess a side
# when loading a saved plan that specified only front_three_quarter.
CAMERA_AZIMUTH_VALUES = frozenset("""
front front_three_quarter front_three_quarter_left front_three_quarter_right
profile_left profile_right
rear_three_quarter_left rear_three_quarter_right direct_rear
""".split())

CAMERA_ELEVATION_VALUES = frozenset("""
overhead high slightly_above eye_level slightly_below low ground_level
crotch_level hip_level between_legs
""".split())

CAMERA_DISTANCE_VALUES = frozenset("""
extreme_close close medium_close medium medium_full full long very_long
""".split())

ORIENTATION_VALUES = CAMERA_AZIMUTH_VALUES
BODY_ORIENTATION_VALUES = ORIENTATION_VALUES
TORSO_ORIENTATION_VALUES = ORIENTATION_VALUES
HIP_ORIENTATION_VALUES = ORIENTATION_VALUES
SUBJECT_ORIENTATION_VALUES = ORIENTATION_VALUES

HEAD_DIRECTION_VALUES = frozenset("""
toward_camera away_from_camera left right up down
up_left up_right down_left down_right
toward_action toward_held_object toward_secondary_subject
over_left_shoulder over_right_shoulder
looking_at_partner looking_at_genital looking_down_at_self
eyes_rolled head_thrown_back chin_to_chest
""".split())

GAZE_DIRECTION_VALUES = frozenset("""
toward_camera away_from_camera left right up down
up_left up_right down_left down_right
toward_action toward_held_object toward_secondary_subject
toward_ground toward_reflection toward_background_object
eyes_closed unfocused
looking_at_partner looking_at_genital looking_down_at_self
""".split())

EXPRESSION_VALUES = frozenset("""
neutral relaxed focused concentrating curious confused
surprised shocked amused submissive dominant
smiling laughing playful mischievous embarrassed awkward
deadpan serious determined frustrated annoyed angry
worried nervous fearful excited joyful ecstatic
sad disappointed disgusted skeptical confident proud
sleepy exhausted strained
aroused pleasured orgasmic pained vulnerable
ahegao tongue_out biting_lip moaning teary crying
custom
""".split())

POSE_TYPE_VALUES = frozenset("""
standing_neutral standing_relaxed standing_dynamic standing_balancing standing_leaning
walking running jumping landing crouching squatting kneeling
sitting_upright sitting_relaxed sitting_leaning sitting_on_floor
lying_face_up lying_face_down lying_on_side
reaching bending twisting dancing falling slipping climbing hanging
lifting carrying throwing catching pushing pulling holding gesturing
selfie_pose posed_portrait balancing custom
missionary missionary_legs_up missionary_legs_on_shoulders missionary_legs_spread
doggy doggy_arched doggy_face_down prone_bone
cowgirl cowgirl_leaning reverse_cowgirl reverse_cowgirl_leaning
spooning side_lying standing_sex standing_bent_over standing_doggy standing_missionary standing_lifted
sitting_sex lap_sitting straddle seated_cowgirl
against_wall against_wall_lifted
oral_giving oral_receiving oral_69 face_sitting
handjob fingering fellatio cunnilingus motorboat
on_all_fours presenting kneeling_presenting
legs_spread_sitting legs_spread_lying legs_up_lying
bent_over_table bent_over_furniture
arching_back thrusting grinding riding being_ridden
restrained bound spread_eagle froggy
pile_driver full_nelson mating_press
amazon reverse_amazon
""".split())

MOVEMENT_VALUES = frozenset("still subtle active fast explosive falling airborne".split())

FACE_VISIBILITY_VALUES = frozenset("full three_quarter profile partial mostly_hidden hidden".split())
BODY_VISIBILITY_VALUES = frozenset("face_only head_and_shoulders upper_body waist_up three_quarter_body full_body partial_body custom".split())
BODY_PART_VALUES = frozenset("face head neck shoulders torso arms hands hips legs thighs knees lower_legs ankles feet".split())
BODY_PART_ALIASES = {"foot": "feet", "both_feet": "feet", "feet_visible": "feet",
                     "hand": "hands", "both_hands": "hands"}
HAND_VISIBILITY_VALUES = frozenset("none_visible left_visible right_visible both_visible partially_visible".split())
FEET_VISIBILITY_VALUES = HAND_VISIBILITY_VALUES

SUBJECT_POSITION_VALUES = frozenset("center left right upper_left upper_right lower_left lower_right foreground midground background".split())
SUBJECT_SCALE_VALUES = frozenset("dominant large medium small environmental".split())
ACTION_VISIBILITY_VALUES = frozenset("clear partially_occluded subtle".split())

CONTACT_STATE_VALUES = frozenset("""
none holding touching supporting leaning_on sitting_on standing_on lying_on
pushing pulling carrying wearing
penetrating being_penetrated oral_contact genital_contact grinding straddling
""".split())

OCCLUSION_VALUES = frozenset("none minor moderate major".split())
DEPTH_POSITION_VALUES = frozenset("foreground same_plane midground background".split())
COMPOSITION_VALUES = frozenset("centered rule_of_thirds symmetrical asymmetrical diagonal layered environmental action_centered portrait_centered".split())
TURN_AMOUNT_VALUES = frozenset("none slight moderate strong".split())

LEG_POSITION_VALUES = frozenset("""
closed slightly_open open wide_open spread_eagle
legs_together one_leg_raised both_legs_raised
legs_on_shoulders legs_bent legs_straight
knees_bent ankles_crossed
""".split())

PELVIS_TILT_VALUES = frozenset("neutral tilted_up tilted_down arched thrust_forward thrust_back".split())
BACK_ARCH_VALUES = frozenset("flat slight moderate strong extreme".split())
