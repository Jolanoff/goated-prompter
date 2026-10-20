"""Creativity: the one owner of how much is invented around the request's facts.

No other guide (Mode, target, Length, Director, planner or validator) decides how much is invented; each keeps only
its own job. The facts every level keeps are the request's own: who appears, what they do, quoted text, rules, locks
and references.
"""

# What every level keeps, said once.
CREATIVITY_FACTS = ("At every level the request's facts stay true and visible: who appears and how many, what each "
                    "one does, how they relate, any quoted text, and every rule, lock and reference. Never add or "
                    "replace a subject or an act.")
# Words to be read or heard: only when asked, or (Creative and Dice) written on something from the request's own words.
_TEXT_ASKED = "Add words to be read or heard (signs, captions, dialogue) only when the request asks for them."
_TEXT_OWN = ("A word written on a prop, garment or body may come from the request's own words or meaning; otherwise "
             "add words to be read or heard (signs, captions, dialogue) only when the request asks for them.")

CREATIVITY_ADAPTERS = {
    "Strict": "Creativity — Strict: write the request as given and show each abstract word through its most direct "
              "sign. Add only what the image needs to be coherent and choose nothing new. "
              + CREATIVITY_FACTS + " " + _TEXT_ASKED,
    "Balanced": "Creativity — Balanced: show the request in its most fitting way, with the signs that best fit the "
                "scene, and fill what it leaves open (setting details, light, materials, clothing) to suit it. "
                + CREATIVITY_FACTS + " " + _TEXT_ASKED,
    "Creative": "Creativity — Creative: find an unexpected but faithful angle on the request, built only from what it "
                "already contains: the moment just before or after, an unusual viewpoint or scale, an action or "
                "attitude that shows a subject's character, or a visual play on the request's own words. Show its "
                "abstract words through unexpected signs, never only the obvious ones. Avoid the most obvious way to "
                "show it. Props, clothing, setting and atmosphere follow that angle. " + CREATIVITY_FACTS + " " + _TEXT_OWN,
    "Dice": "Creativity — Dice: as Creative, and decide boldly: symbolic signs, and everything the request leaves "
            "open: the setting, the situation, props, clothing and atmosphere. " + CREATIVITY_FACTS + " " + _TEXT_OWN,
}

# Sampling follows the same setting: the final prompt writer and the Dataset scene writer (which writes several
# scenes in one answer and needs more spread) each have their own scale.
CREATIVITY_TEMPERATURE = {"Strict": .3, "Balanced": .55, "Creative": .8, "Dice": 1.0}
SCENE_TEMPERATURE = {"Strict": .55, "Balanced": .8, "Creative": .95, "Dice": 1.05}


def creativity_adapter(name):
    return CREATIVITY_ADAPTERS.get(name, CREATIVITY_ADAPTERS["Balanced"])


def creativity_temperature(name, *, scene=False):
    table = SCENE_TEMPERATURE if scene else CREATIVITY_TEMPERATURE
    return table.get(name, table["Balanced"])
