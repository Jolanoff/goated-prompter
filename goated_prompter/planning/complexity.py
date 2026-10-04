"""Conservative structural signals, not domain-to-action recommendations."""

import re


def needs_planning(text, *, video=False):
    # Literal text/dialogue is not evidence of bodily or temporal complexity.
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|(?<!\w)\'[^\'\n]*\'(?!\w)', "", text).casefold()
    text = re.sub(r"<d>.*?</d>", "", text, flags=re.S)
    mechanics = r"\b(?:suspended|inverted|counterbalanc\w*|weight[- ]bearing|cartwheel|backbend|mid[- ]throw|grappl\w*|acrobat\w*|choreograph\w*)\b"
    if re.search(mechanics, text):
        return True
    if re.search(r"\b(?:one|left|right)\s+(?:hand|foot|arm|leg)\b[^.;\n]{0,140}\b(?:other|opposite|left|right)\s+(?:hand|foot|arm|leg)\b", text):
        return True
    if re.search(r"\b(?:each|another|partner)\b[^.;\n]{0,60}\b(?:supports?|grips?|contacts?|bears?\s+weight)\b", text):
        return True
    if re.search(r"\b(?:torso|pelvis|knee|limb|leg|arm)\b[^.;\n]{0,60}\b(?:twist\w*|hook\w*|opposite|extend\w*|lean\w*)\b", text):
        return True
    if re.search(r"\b(?:two|three|four|2|3|4)\s+(?:\w+\s+){0,2}(?:people|persons|performers|dancers|wrestlers|subjects|characters)\b", text):
        return True
    if re.search(r"\b(?:each other|one another|opposite directions|supporting .{1,30}weight|between .{1,40}while)\b", text):
        return True
    if re.search(r"\b(?:only|both|all)\b[^.;\n]{0,40}\b(?:hands?|feet|limbs?)\b[^.;\n]{0,35}\b(?:visible|frame|cropped)\b", text):
        return True
    if video and (re.search(r"<shot\d+>", text) or re.search(r"\b(?:then|followed by|before .{1,45}after|transforms? into)\b", text)):
        return True
    if re.search(r"\bwhile\b", text) and (re.search(r"\b(?:holding|gripping|carrying|balancing|rotating|lifting|reaching|passing)\b", text)):
        return True
    return False
