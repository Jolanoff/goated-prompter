"""Dataset types, idea sources and seed modes."""

DATASET_TYPES = (
    "Character", "Multiple characters", "Animal", "Object / product", "Visual style",
    "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom",
)
DATASET_SOURCES = ("random", "guided")
# The shape every image of a dataset is made in (ComfyUI sets it; Auto leaves the scenes free to choose).
ASPECT_RATIO_NAMES = ("Auto", "1:1", "4:5", "3:4", "2:3", "9:16", "5:4", "4:3", "3:2", "16:9")
# Like ComfyUI's control: a new seed each run, the same seed, or the last seed plus one.
SEED_MODES = ("randomize", "fixed", "increment")
# Dataset triggers: what each one stands for, and whether its exact text is placed by code ("off"), its meaning is
# written by the model in every prompt ("on"), or both.
TRIGGER_KINDS = ("character", "style", "outfit", "object", "other")
TRIGGER_EXPANSIONS = ("off", "on", "both")
MAX_TRIGGERS = 20
MAX_SEED = 2**32 - 1
# Directors that need reference images, edit a source image or write video do not fit Dataset, which writes
# text-to-image prompts from scenes. Every other Director, built-in or the user's own, is offered.
DATASET_EXCLUDED_DIRECTORS = (
    "reverse_engineer", "surgical_edit", "image_edit_director", "face_identity_analyst", "subject_appearance_analyst",
    "reference_composer", "krea_2_pose_lock", "krea_2_identity_edit", "style_transfer_director", "video_director",
    "minimax_director", "minimax_h3_director",
)


def dataset_director_allowed(director_id):
    return director_id not in DATASET_EXCLUDED_DIRECTORS
