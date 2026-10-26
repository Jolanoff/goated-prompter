"""Dataset types, consistency, idea sources and seed modes."""

# What the dataset trains: each type decides by default which parts of the image stay the same (TYPE_CONSISTENCY).
DATASET_TYPES = (
    "Character", "Multiple characters", "Animal", "Act variety", "Pose / action", "Outfit / clothing", "Expression",
    "Object / product", "Brand / logo", "Typography / text", "Location / environment", "Lighting",
    "Camera / composition", "Visual style", "Concept", "Custom",
)
# The parts of an image a dataset can hold the same. Each gets one level: locked (identical in every image), themed
# (every image follows the request's words for it, the rest of that part varies) or free (chosen anew for each image).
CONSISTENCY_PARTS = ("subject", "clothing", "action", "expression", "place", "objects", "camera", "light", "mood")
CONSISTENCY_LEVELS = ("locked", "themed", "free")
# Each type's default levels; a part not listed is free. The request and the draft's own choices override them.
# subject themed: the people the request names, triggers or knows keep their look and everyone else varies.
TYPE_CONSISTENCY = {
    "Character": {"subject": "themed"},
    "Multiple characters": {"subject": "themed"},
    "Animal": {"subject": "themed"},
    "Act variety": {"action": "themed"},
    "Pose / action": {"action": "locked"},
    "Outfit / clothing": {"clothing": "locked"},
    "Expression": {"expression": "locked"},
    "Object / product": {"objects": "locked"},
    "Brand / logo": {"objects": "locked"},
    "Typography / text": {"objects": "locked"},
    "Location / environment": {"place": "themed"},
    "Lighting": {"light": "locked"},
    "Camera / composition": {"camera": "locked"},
    "Visual style": {},
    "Concept": {},
    "Custom": {},
}
DATASET_SOURCES = ("random", "guided")
# The world a request belongs to (Understanding names it); a vocabulary group may list the worlds its entries fit
# ("worlds"), and a run deals only from groups that fit the request's world.
WORLDS = ("everyday", "historical", "fantasy", "sci-fi")
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
