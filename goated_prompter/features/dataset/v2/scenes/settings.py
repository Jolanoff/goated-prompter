"""Limits and field lists of the scene writer."""


BATCH = 10  # one answer holds up to ten images: a model spreads a set out best within one answer; in batches of
# five, a live second batch copied the first one image for image from its already_used list


ROUNDS = 3


# Only what decides the picture: the visible clothing and light source go in extras, never as fields of their own.
# The signs (extras) are written right after the people and their pose, before the place and camera: written last, a
# model fills them with leftover atmosphere.
SECTIONS = ("subjects", "actions", "position", "extras", "space", "camera")
# A cast with known characters (exact-text character triggers) also has "frame": how much of each person the camera
# shows ("shows", widest first) and whether their face is visible ("face"), data the writer fills for every person so a
# known character never drops out of the image while the action stays (checks.framing_problems). Each image is dealt
# the frame its known characters get, its dealt camera's shot (camera.camera_frames) or else entries.deal_frames, so
# the set spreads over full body, head to knees and head to hips instead of the tight crops a writer picks on its own,
# unless the request keeps the camera in its own words (request.deals_frames).
SHOWS = ("full body", "head to knees", "head to hips", "head and shoulders")
FACES = ("visible", "hidden")
AT_LEAST_HIPS = SHOWS[:3]


SUBJECT_FIELDS = ("skin", "build", "hair", "eyes", "expression")


# Adult datasets also describe each person's genitals, so the final prompt has them as data for every person whose
# genitals the camera sees (a rule alone left most of them undescribed) and never draws one without its owner.
ADULT_SUBJECT_FIELDS = ("genitals",)
KNOWN_SUBJECT_FIELDS = ("expression",)  # a known character's look comes from its name, never the writer


VOCABULARY_SAMPLE = 40  # entries per category in one batch's prompt: enough choice without drowning the request



FIELDS = SECTIONS


MAX_FIELD = 2000


EARLIER = 25  # every earlier image of a run (25 is the largest amount)


ACTIONS_CATEGORY = "Actions & Poses"


ENTRY_CAP = 2


HAND = 1  # suggested entries per category for each image (every category but Actions & Poses): one each, so a pack
# never piles several of its entries into one image
