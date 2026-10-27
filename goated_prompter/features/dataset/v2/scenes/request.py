"""What the scene writer is asked: the brief's cast and inputs, the system text and the user message."""

import json
import re

from .....contracts import PromptInstruction
from .....options.targets import canonical_target
from .....presets import get_director_preset
from .....options.styles import OFF_STYLE, without_color
from .....prompting.base import SHOW_DONT_TELL
from .....prompting.creativity import creativity_adapter, creativity_temperature
from ..aspect import brief_aspect, shape_rule
from ..assignments import dataset_assignments
from ..consistency import kept_words, levels, parts_at
from ..triggers import brief_triggers, owner, run_style

from .entries import entry_cap
from .settings import ADULT_SUBJECT_FIELDS, FACES, FIELDS, KNOWN_SUBJECT_FIELDS, MAX_FIELD, SHOWS, SUBJECT_FIELDS
from .texts import (ASPECT_RULE, CAMERA_RULE, COMPOSE_SYSTEM, CONSISTENCY_RULE, DEALT_FRAME_RULE, DETAILS_RULE,
                    ENTRY_RULE, FRAME_RULE, GUIDED_RULE, LABELS_RULE, LOOK_RULE, NO_COLOR_RULE, NO_PEOPLE_RULE,
                    NSFW_RULE, PLACE_RULE, SFW_RULE, VOCABULARY_RULES)

# Where an earlier image's summary (checks._summary) holds each part: a locked part's first version is copied from it,
# and already_used never lists a locked part as something to avoid.
SUMMARY_KEYS = {"place": "space", "action": "actions", "camera": "camera", "subject": "looks", "objects": "extras",
                "clothing": "extras", "light": "extras", "mood": "extras"}
USED_KEYS = {"space": "places", "actions": "arrangements", "camera": "cameras", "looks": "looks", "extras": "extras"}


def _labels(brief):
    return [item["label"] for item in brief["characters"]]


def trigger_notes(brief):
    """What the user's triggers mean for the scenes: a meaning trigger about a person, object or the whole image applies
    to every scene. Exact-text character triggers make their character known (no looks); outfits and style are the
    final prompt's concern."""
    notes = []
    for number, trigger in enumerate(brief_triggers(brief), 1):
        person = owner(brief, number)
        if trigger["kind"] not in ("style", "outfit") and trigger["expand"] != "off":
            about = f" ({person})" if person else ""
            notes.append(f'"{trigger["text"]}"{about} applies to every image: keep its meaning.')
    return notes


def known_labels(brief):
    """Labels of established characters (brief version 12), whose looks come from their name, never the writer."""
    return {item["label"] for item in brief["characters"] if item.get("known") is True}


def deals_frames(brief):
    """Whether each image is dealt a frame for its known characters (entries.deal_frames): only when the camera is
    free. A camera the request keeps (the framing, the shot or which body parts must show) decides how much of everyone
    the image shows; a live request that asked for the feet got dealt hips-up frames in a third of its images."""
    return bool(known_labels(brief)) and levels(brief)["camera"] == "free"


def consistency_items(brief):
    """{part: {"level", "words"?}} for every part that does not vary freely, as the scene writer reads it."""
    words = kept_words(brief)
    return {part: {"level": level, **({"words": words[part]} if part in words else {})}
            for part, level in levels(brief).items() if level != "free"}


def subject_fields(brief, label):
    """The subject fields one person's scene needs: a known character only its expression; in an adult dataset
    everyone else also their genitals."""
    if label in known_labels(brief):
        return KNOWN_SUBJECT_FIELDS
    return SUBJECT_FIELDS + (ADULT_SUBJECT_FIELDS if brief["path"] == "nsfw_character" else ())


def guided_assignments(brief):
    return dataset_assignments({"source_mode": "guided", "inputs": "\n".join(brief["input"]["guided_inputs"]),
                                "amount": brief["input"]["amount"]})


def slot_inputs(brief):
    """{slot: guided input}, fixed before generation; "" for every slot when the source is random."""
    total = brief["input"]["amount"]
    if brief["input"].get("source_mode") != "guided" or not brief["input"].get("guided_inputs"):
        return {number: "" for number in range(1, total + 1)}
    return {row["index"]: row["input"] for row in guided_assignments(brief)}


def director_emphasis(brief):
    """The run's Director as what each scene emphasizes, or "" when it says nothing for this target. The final prompt
    writes the decided scene without a Director, so its emphasis is decided once, here."""
    if not brief["settings"].get("director"):
        return ""
    preset = get_director_preset(brief["settings"]["director"])
    if not preset.instructions or (preset.supported_targets
                                   and canonical_target(brief["settings"]["target"]) not in preset.supported_targets):
        return ""
    return (f"DIRECTOR EMPHASIS — {preset.label}\nWritten for a final prompt; here it decides what each scene shows "
            f"and emphasizes, never what happens, how the act is worded or where everyone is:\n{preset.instructions}")


def _system(brief, errors, vocabulary="", entry_cap=None, places=False, looks=False, details=False, cameras=False,
            frames=False):
    content = NSFW_RULE if brief["path"] == "nsfw_character" else SFW_RULE
    if not brief["characters"]:
        content += "\n" + NO_PEOPLE_RULE
    if brief["input"].get("source_mode") == "guided":
        content += "\n" + GUIDED_RULE
    system = COMPOSE_SYSTEM.format(content_rule=content, show=SHOW_DONT_TELL)
    if vocabulary:
        system += "\n\n" + VOCABULARY_RULES
    if entry_cap:
        system += "\n\n" + ENTRY_RULE.format(cap=entry_cap)
    if places:
        system += "\n\n" + PLACE_RULE
    if looks:
        system += "\n\n" + LOOK_RULE
    if cameras:
        system += "\n\n" + CAMERA_RULE
    if details:
        system += "\n\n" + DETAILS_RULE
    if emphasis := director_emphasis(brief):
        system += "\n\n" + emphasis
    system += "\n\n" + creativity_adapter(brief["settings"]["creativity"] or "Balanced")
    if consistency_items(brief):
        system += "\n\n" + CONSISTENCY_RULE
    if known := known_labels(brief):
        system += "\n\n" + FRAME_RULE.format(known=", ".join(sorted(known)))
        if frames:
            system += " " + DEALT_FRAME_RULE
    if rule := shape_rule(brief_aspect(brief), ASPECT_RULE):
        system += "\n\n" + rule
    if without_color(*run_style(brief)):  # given only the capture's name, a live run wrote "redness" and "bruises"
        system += "\n\n" + NO_COLOR_RULE
    if len(labels := _labels(brief)) > 1:  # last, where the retries that fixed it put the labels
        system += "\n\n" + LABELS_RULE.format(labels=", ".join(labels[:-1]) + " and " + labels[-1])
    if errors:
        system += "\n\nYour previous answer broke these rules. Answer again correctly:\n- " + "\n- ".join(errors)
    return system


def _keyed(labels, value):
    return {"type": "object", "additionalProperties": False, "required": labels,
            "properties": {label: value for label in labels}}


def compose_message(brief, images, earlier=(), vocabulary="", entries_used=None):
    """The scene writer's user message: the request, the approved requirements, the selected vocabulary (only when
    some was selected) and the images to write. entries_used: {entry: images so far} when entries are tracked."""
    held = consistency_items(brief)
    requirements = {"rules": brief["input"]["rules"],
                    "understanding": {**{key: brief[key] for key in ("summary", "characters", "fixed", "randomized", "must", "avoid")},
                                      **({"consistency": held} if held else {})}}
    style, capture = run_style(brief)
    if style != OFF_STYLE:  # with a style trigger the trigger carries the style, so no Style is named
        requirements["style"] = style
    if capture != "Auto":
        requirements["capture"] = capture  # how the photograph was taken
    if notes := trigger_notes(brief):
        requirements["triggers"] = notes
    parts = [f"USER REQUEST:\n{brief['input']['request']}",
             "EXISTING APPROVED REQUIREMENTS:\n" + json.dumps(requirements, ensure_ascii=False, indent=1)]
    if vocabulary:
        parts.append(vocabulary)
    locked = {SUMMARY_KEYS[part] for part in parts_at(brief, "locked") if part in SUMMARY_KEYS}
    used = {USED_KEYS[key]: [item.get(key, "") for item in earlier] for key in USED_KEYS if key not in locked}
    if "looks" in locked and (held := locked_people(brief)):  # everyone the locked subject leaves free still varies
        free = [{label: look for label, look in item.get("looks", {}).items() if label not in held} for item in earlier]
        if any(free):
            used["looks"] = free
    if entries_used:
        used["entries"] = dict(entries_used)
    first = {key: earlier[0][key] for key in sorted(locked) if earlier and earlier[0].get(key)}
    if "looks" in first:  # only the people the locked subject holds keep image 1's looks
        held = locked_people(brief)
        first["looks"] = {label: look for label, look in first["looks"].items() if label in held}
        first = {key: value for key, value in first.items() if value}
    parts.append("IMAGES:\n" + json.dumps({"images": list(images), **({"already_used": used} if earlier or entries_used else {}),
                                           **({"same_as_image_1": first} if first else {})},
                                          ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


def compose_instruction(brief, images, earlier=(), errors=(), vocabulary="", entry_cap=None, entries_used=None):
    """One composition request. images: [{"image": n, "input"?: guided text}]; vocabulary:
    the SELECTED VOCABULARY section ("" for none); entry_cap: set when scenes name their Actions & Poses entry."""
    labels = _labels(brief)
    text = {"type": "string", "maxLength": MAX_FIELD}

    def person(label):
        fields = subject_fields(brief, label)
        return {"type": "object", "additionalProperties": False, "required": list(fields),
                "properties": {field: text for field in fields}}
    subjects = {"type": "object", "additionalProperties": False, "required": labels,
                "properties": {label: person(label) for label in labels}}
    framed = {"type": "object", "additionalProperties": False, "required": ["shows", "face"],
              "properties": {"shows": {"type": "string", "enum": list(SHOWS)}, "face": {"type": "string", "enum": list(FACES)}}}
    frame = {"type": "object", "additionalProperties": False, "required": labels,
             "properties": {label: framed for label in labels}}
    fields = [*FIELDS, *(["frame"] if known_labels(brief) else []), *(["entry"] if entry_cap else [])]
    item = {"type": "object", "additionalProperties": False, "required": fields,
            "properties": {field: subjects if field == "subjects" else frame if field == "frame" else _keyed(labels, text)
                           if field == "position" else text for field in fields}}
    count = len(images)
    schema = {"type": "object", "additionalProperties": False, "required": ["scenes"],
              "properties": {"scenes": {"type": "array", "minItems": count, "maxItems": count, "items": item}}}
    per_image = 700 + 300 * len(labels)
    creativity = brief["settings"]["creativity"] or "Balanced"
    return PromptInstruction(system_message=_system(brief, errors, vocabulary, entry_cap,
                                                    any("place" in image for image in images),
                                                    any("looks" in image for image in images),
                                                    any("details" in image for image in images),
                                                    any("camera" in image for image in images),
                                                    any("frame" in image for image in images)),
                             user_message=compose_message(brief, images, earlier, vocabulary, entries_used),
                             model_family=brief["_family"], diagnostic_stage="dataset_v2:scenes",
                             max_tokens=per_image * count, hard_max_tokens=per_image * count,
                             stream_character_limit=per_image * 4 * count,
                             repetition_protected_terms=tuple([*labels, *FIELDS, *SUBJECT_FIELDS, *ADULT_SUBJECT_FIELDS]),
                             temperature=creativity_temperature(creativity, scene=True), top_p=.95,
                             json_output=True, json_schema=schema, seed=brief["input"].get("seed"))


def locked_people(brief):
    """Labels whose looks a locked subject holds: the people the subject's words name, or everyone when they name
    nobody in particular ("the same man"); nobody when the subject is not locked. A live set that locked one named
    character also froze the looks of everyone around him."""
    if levels(brief)["subject"] != "locked":
        return frozenset()
    words, labels = kept_words(brief).get("subject", ""), [person["label"] for person in brief["characters"]]
    named = frozenset(label for label in labels
                      if re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", words, re.IGNORECASE))
    return named or frozenset(labels)


def varied_labels(brief):
    """Labels whose looks change from image to image: not a known character, not a person with a character
    trigger, not a person the user named (Understanding labels unnamed people with a lowercase role noun), and not a
    person a locked subject holds (locked_people)."""
    held = locked_people(brief)
    return frozenset(person["label"] for person in brief["characters"]
                     if not person.get("known") and not person.get("triggers") and person["label"][:1].islower()
                     and person["label"] not in held)
