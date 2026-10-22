"""Limits and field lists of the scene writer."""


BATCH = 10  # one answer holds up to ten images: a model spreads a set out best within one answer


ROUNDS = 3


# Only what decides the picture's people and arrangement: clothing, light and mood are chosen by the final writer.
# The signs (extras) are written right after the people and their pose, before the place and camera: written last, a
# model fills them with leftover atmosphere.
SECTIONS = ("subjects", "actions", "position", "extras", "space", "camera")


SUBJECT_FIELDS = ("skin", "build", "hair", "detail", "expression")


KNOWN_SUBJECT_FIELDS = ("expression",)  # a known character's look comes from its name, never the writer


VOCABULARY_SAMPLE = 40  # entries per category in one batch's prompt: enough choice without drowning the request


FIT_CHUNK = 80  # Actions & Poses entries judged in one fitting call


FIELDS = SECTIONS


MAX_FIELD = 2000


EARLIER = 25  # every earlier image of a run (25 is the largest amount)


ACTIONS_CATEGORY = "Actions & Poses"


ENTRY_CAP = 2


HAND = 1  # suggested entries per category for each image (every category but Actions & Poses): one each, so a pack
# never piles several of its entries into one image
