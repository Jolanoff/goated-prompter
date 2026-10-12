"""Dataset types, idea sources and seed modes."""

DATASET_TYPES = (
    "Character", "Multiple characters", "Animal", "Object / product", "Visual style",
    "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom",
)
DATASET_SOURCES = ("random", "guided")
# Like ComfyUI's control: a new seed each run, the same seed, or the last seed plus one.
SEED_MODES = ("randomize", "fixed", "increment")
MAX_SEED = 2**32 - 1

CHARACTER_KINDS = ("human", "humanoid", "anthro", "animal", "monster", "alien", "robot", "creature", "other")
SUBJECT_KINDS = (*CHARACTER_KINDS, "object", "product", "environment", "style", "text", "concept")
BODIED_KINDS = frozenset(CHARACTER_KINDS) - {"other"}
ANATOMY_KINDS = BODIED_KINDS - {"robot"}
DATASET_SUBJECT_KINDS = {
    "Character": "human", "Multiple characters": "human", "Animal": "animal", "Object / product": "product",
    "Visual style": "style", "Location / environment": "environment", "Brand / logo": "object",
    "Typography / text": "text", "Concept": "concept", "Custom": "other",
}
