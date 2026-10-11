"""Generic Dataset direction and look lists, shared by every batch."""

# Spread the batch in code instead of asking one call to invent and police variety.
# Values are generic so they fit any subject; the prompt lets HARD, guided input,
# expansion limits and batch-shared choices override any part of a direction.
DIRECTION_AXES = {
    "moment": ("the build-up just before the main action", "the peak of the action",
               "the aftermath or reaction", "a small mishap in the middle of it", "an unguarded candid moment",
               "a playful or unexpected twist on the subject"),
    "mood": ("joyful", "tense", "calm", "mischievous", "determined", "flustered", "tender", "chaotic"),
    "framing": ("close-up", "medium shot", "full-body shot", "wide shot where the place tells the story",
                "three-quarter view at eye level", "slightly raised eye-level view", "over-the-shoulder view"),
    "setting": ("the most familiar spot in the subject's world", "a less obvious corner of the subject's world",
                "a busy place full of other people", "a small shop, stall, workshop or kitchen",
                "a home, room or other private space", "a vehicle, station or other place in transit",
                "an outdoor spot shaped by the weather"),
    "light": ("soft morning light", "harsh midday sun", "golden hour", "dusk or blue hour",
              "night lit by practical lights", "dramatic single-source light", "overcast diffuse light",
              "warm lamplight from windows or lanterns"),
    # Only images with several characters get one; it decides how they relate in this moment.
    "interaction": ("one teaches or shows the other something", "a playful disagreement", "a shared mishap",
                    "one surprises the other", "working together on a fiddly task", "one helps the other out of a problem",
                    "a small competition between them", "one teases the other"),
}
# A required action must be visible in every image. Manual runs showed moment,
# mood and setting directions (rest, water break, climbing a ladder) replacing it,
# so those items only vary how the image is shot.
ACTION_SAFE_AXES = ("framing", "light")
# In a sexual batch the act is the required action; its mood, dynamic, place, clothing and prop support it.
SEXUAL_ACTION_SAFE_AXES = ("framing", "light", "mood", "interaction", "setting", "clothing", "prop", "position")
# Steep top-down and worm's-eye angles foreshorten full bodies into broken anatomy,
# so no direction asks for them; the user can still request one explicitly.
# Close-ups and over-the-shoulder views crop or hide a participant, so datasets
# with several characters draw framing from shots that keep everyone in frame.
GROUP_FRAMING = ("medium shot with everyone in frame", "full-body shot", "wide shot where the place tells the story",
                 "three-quarter view at eye level with everyone in frame", "slightly raised eye-level view with everyone in frame")
# Random characters otherwise collapse to the model's default person, so the app draws
# each image's look for them (AttrPrompt: random attribute combinations beat fixed ones).
# Looks are built from independent parts, so a batch of ten draws ten of hundreds of
# combinations instead of walking through one short list that every batch repeats.
AGES = ("early twenties", "mid twenties", "late twenties", "early thirties", "late thirties", "forties")
# Hair and build are drawn per sex, so a man does not get a pixie cut or a woman a crew cut by chance;
# people whose sex is open draw from both.
LOOK_PARTS = {
    "woman": {"length": ("pixie-length", "chin-length", "shoulder-length", "mid-back-length", "waist-length"),
              "style": ("straight", "wavy", "curly", "braided", "tied-up", "messy", "sleek"),
              "color": ("black", "dark brown", "chestnut", "auburn", "copper-red", "honey-blonde", "platinum-blonde",
                        "ash-brown", "silver-grey", "dark blonde"),
              "build": ("slim", "athletic", "curvy", "petite", "tall and slender", "full-figured", "toned",
                        "soft and round", "heavyset", "willowy")},
    "man": {"length": ("buzzed", "short", "cropped", "medium-length", "shoulder-length"),
            "style": ("straight", "wavy", "curly", "slicked-back", "tousled", "faded at the sides"),
            "color": ("black", "dark brown", "light brown", "sandy-blond", "ginger", "grey", "salt-and-pepper"),
            "build": ("slim", "athletic", "stocky", "broad-shouldered", "tall and lean", "heavyset", "muscular",
                      "wiry", "soft-bellied", "barrel-chested")},
}
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
SHORT_HAIR = {"pixie-length", "chin-length", "buzzed", "short", "cropped"}
LONG_HAIR_STYLES = {"braided", "tied-up", "slicked-back"}
SKIN_TONES = ("fair", "freckled fair", "light", "olive", "tan", "golden-brown", "brown", "deep brown")
LOOK_KINDS = {"human", "humanoid"}
SEX_LOOKS = ("woman", "man")
