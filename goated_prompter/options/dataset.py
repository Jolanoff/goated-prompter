"""Dataset types, idea sources and seed modes."""

DATASET_TYPES = (
    "Character", "Multiple characters", "Animal", "Object / product", "Visual style",
    "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom",
)
DATASET_SOURCES = ("random", "guided")
# Like ComfyUI's control: a new seed each run, the same seed, or the last seed plus one.
SEED_MODES = ("randomize", "fixed", "increment")
MAX_SEED = 2**32 - 1
