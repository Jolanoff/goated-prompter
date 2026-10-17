"""Dataset types, idea sources and seed modes."""

DATASET_TYPES = (
    "Character", "Multiple characters", "Animal", "Object / product", "Visual style",
    "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom",
)
DATASET_SOURCES = ("random", "guided")
# Like ComfyUI's control: a new seed each run, the same seed, or the last seed plus one.
SEED_MODES = ("randomize", "fixed", "increment")
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
