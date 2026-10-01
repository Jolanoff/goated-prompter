"""Small Dataset staging guardrails, not an anatomy solver."""

import re

from .dataset_coverage import explicit_geometry_issues
from .dataset_visible_content import visible_content_error


GEOMETRY_FIELDS = {"framing", "camera_view", "body_orientation", "head_direction", "gaze",
                   "pose", "action_focus", "face_visibility", "visibility_focus"}


def validate_geometry(value):
    if not isinstance(value, dict) or value.keys() - GEOMETRY_FIELDS:
        raise ValueError("Geometry must be an object of supported staging fields.")
    cleaned = {}
    for key, content in value.items():
        values = content if key == "visibility_focus" else [content]
        if not isinstance(values, list) or len(values) > 12:
            raise ValueError("Geometry visibility_focus must be a short array of strings.")
        for text in values:
            if (not isinstance(text, str) or not text.strip() or len(text) > 160
                    or "\n" in text or "\r" in text or "```" in text):
                raise ValueError("Geometry fields must contain short single-line descriptions.")
            if error := visible_content_error(text):
                raise ValueError(error)
        cleaned[key] = [text.strip() for text in values] if key == "visibility_focus" else content.strip()
    return cleaned


def geometry_errors(row):
    """Reject only explicit contradictions; partial rear shoulder turns remain valid.

    Prose and structured fields are checked together so a valid geometry object
    cannot hide contradictory prose. Mirrors/multi-panel prose retains the existing
    conservative exemption, but never exempts contradictory structured fields.
    """
    geometry = row.get("geometry", {})
    text = row.get("scene", "").casefold().replace("–", "-").replace("—", "-")
    errors = [issue["message"] for issue in explicit_geometry_issues(text)]
    if re.search(r"\b(?:mirror|reflection|reflected|collage|inset|split.screen)\b", text):
        text = ""  # Do not confuse reflected/secondary views with the primary camera.
    def asserted(pattern):
        return any(not re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$",
                                 text[max(0, match.start() - 40):match.start()])
                   for match in re.finditer(pattern, text))
    g = {key: value.casefold().replace("-", " ") for key, value in geometry.items()
         if isinstance(value, str)}
    focus = " ".join(geometry.get("visibility_focus", [])).casefold()
    view = g.get("camera_view", "")
    body = g.get("body_orientation", "")
    head = g.get("head_direction", "")
    gaze = g.get("gaze", "")
    face = g.get("face_visibility", "") + " " + focus
    crop = g.get("framing", "")
    rear = bool(re.search(r"\b(?:direct|straight) rear\b|directly behind", view)) or asserted(r"\b(?:direct|straight) rear view\b|camera directly behind")
    frontal = bool(re.search(r"full(?:y)? frontal|full front(?:al)?", face)) or asserted(r"full(?:y)? frontal face|face (?:is )?(?:clearly )?fully frontal")
    turn = bool(re.search(r"over (?:\w+ )?shoulder|over.shoulder", head)) or asserted(r"head (?:is )?turned (?:back )?over (?:\w+ )?shoulder")
    toward_camera = bool(re.search(r"(?:toward|at|into|to) (?:the )?(?:camera|viewer)|^(?:camera|viewer)$", gaze)) or asserted(r"looking (?:straight |directly )?(?:at|into) (?:the )?(?:camera|viewer)")
    if rear and frontal:
        errors.append("Direct rear camera cannot show a fully frontal face; choose a compatible view/visibility.")
    if rear and toward_camera and not turn:
        errors.append("Direct rear view needs a plausible over-shoulder head turn for camera-directed gaze.")
    if re.search(r"fully (?:facing |turned )?away|facing away", body) and re.search(r"fully frontal|fully toward (?:the )?camera", head):
        errors.append("Fully away body and fully frontal head require incompatible rotation.")
    close = bool(re.search(r"close ?up|upper body|head and shoulders", crop))
    if close and re.search(r"\b(?:walking|running|walks?|runs?)\b", row.get("idea", "").casefold()) and re.search(r"\bshoes\b", row.get("idea", "").casefold()):
        errors.append("The fixed locomotion/shoe idea needs a wider crop to make its central interaction visible.")
    if close and re.search(r"\b(?:shoes|feet|foot|full body)\b", focus):
        errors.append("This close/upper-body crop cannot include required shoes, feet or full-body visibility.")
    if "profile" in view and re.search(r"both (?:sides|halves).*face|face.*both (?:sides|halves)|equally visible", face):
        errors.append("Profile view cannot expose both sides of the face equally.")
    if view in {"front", "front three quarter"} and asserted(r"camera directly behind|direct rear view"):
        errors.append("Scene prose contradicts the structured front camera view.")
    if view == "direct rear" and asserted(r"camera (?:is )?directly in front|front camera view"):
        errors.append("Scene prose contradicts the structured rear camera view.")
    return list(dict.fromkeys(errors))
