"""What code checks in a written scene: its shape, the avoid list, repeats and unnamed people."""

import re

from .settings import AT_LEAST_HIPS, FACES, FIELDS, KNOWN_SUBJECT_FIELDS, SECTIONS, SHOWS, SUBJECT_FIELDS


_NEGATION = re.compile(r"^\s*(?:no|not|without|avoid|never|don'?t|do not)\b\s*", re.IGNORECASE)


def _filled(value, keys):
    return (isinstance(value, dict) and set(value) == set(keys)
            and all(isinstance(value[key], str) and value[key].strip() for key in keys))


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def avoid_patterns(brief):
    """Each avoid phrase without its "no" / "without", matched as a phrase with a flexible ending."""
    patterns = []
    for phrase in brief["avoid"]:
        core = _NEGATION.sub("", phrase.strip().casefold()).strip(" .")
        words = re.findall(r"[a-z0-9]+", core)
        if words:
            patterns.append((phrase, re.compile(r"\b" + r"\W+".join(map(re.escape, words)) + r"\w*", re.IGNORECASE)))
    return patterns


# Fields scenes no longer have (visible clothing and light go in extras). A writer that still sends them out
# of habit, or a scene saved before, keeps working: they are dropped, never a reason to ask again.
RETIRED_SECTIONS = ("lighting", "mood")


RETIRED_SUBJECT_FIELDS = ("clothing", "detail")


def retire_fields(scene):
    """The scene without retired fields; anything that is not a dict comes back unchanged."""
    if not isinstance(scene, dict):
        return scene
    result = {key: value for key, value in scene.items() if key not in RETIRED_SECTIONS}
    if isinstance(result.get("subjects"), dict):
        result["subjects"] = {label: ({key: value for key, value in person.items() if key not in RETIRED_SUBJECT_FIELDS}
                                      if isinstance(person, dict) else person)
                              for label, person in result["subjects"].items()}
    return result


def _bare(entry):
    """An entry without its leading article, as it reads inside a sentence ("a leather collar" -> "leather collar")."""
    return re.sub(r"^(?:a|an|the)\s+", "", " ".join(str(entry).split()).casefold())


def without_copied_props(scene, props, suggested, earlier_extras):
    """The accepted scene without a vocabulary prop copied from an earlier image: a live writer put the prop suggested
    for one image into all twelve, so every image showed the same object. An extras item that names one of the
    selected props stays when that prop was suggested for this image or no earlier image has it; props the request
    names are suggested for every image, so they always stay."""
    earlier = " ".join(map(str, earlier_extras)).casefold()
    offered = {_bare(entry) for entry in suggested}
    copied = [prop for prop in {_bare(entry) for entry in props} if prop not in offered and prop in earlier]
    items = str(scene.get("extras") or "").split(", ")
    kept = [item for item in items if not any(prop in item.casefold() for prop in copied)]
    return {**scene, "extras": ", ".join(kept)} if kept and len(kept) < len(items) else scene


_ENTRY_HEAD = re.compile(r"((?:^|;\s*))([^:;\n]{3,80}):\s*([^,;\n]*)(?:,\s*|;\s*|$)")


def without_entry_copy(scene, labels):
    """The accepted scene without a copied Actions & Poses entry head in its actions: a live writer began the act with
    the entry's name and its placeholder people ("two tops: one person bound, man 1's penis ...", also with an unfilled
    [slot]), so the final prompt named a pack label as the position. A head is dropped only when neither its name nor its
    wording names anyone of the cast and the rest of the act still names everyone; otherwise the act stays as written."""
    names = lambda text: any(re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", text, re.IGNORECASE)
                             for label in labels)

    def drop(found):
        before, name, wording = found.groups()
        if names(name) or names(wording):
            return found[0]
        return "; " if before else ""

    actions = str(scene.get("actions") or "")
    cleaned = _ENTRY_HEAD.sub(drop, actions).strip(" ,;")
    if cleaned == actions.strip(" ,;") or unnamed_people({"actions": cleaned}, labels):
        return scene
    return {**scene, "actions": cleaned}


def scene_errors(scene, labels, avoid, extra=(), known=frozenset(), subject_fields=SUBJECT_FIELDS):
    """Why one composed scene is unusable as an answer; [] when its shape is right. extra: further text fields the
    answer must have (the Actions & Poses "entry"); known: labels of known characters (expression only), whose cast
    also needs frame; subject_fields: what everyone else's subjects need (request.subject_fields), the same for
    everyone or {label: fields} when characters of different kinds have their own."""
    framed = bool(known)
    if isinstance(scene, dict) and not framed:
        scene = {key: value for key, value in scene.items() if key != "frame"}  # a frame nobody asked for is dropped
    return _shape_errors(scene, labels, avoid, extra, known, subject_fields, framed)


def _field_sets(labels, known, own):
    """{fields: the labels that need them} for everyone but the known characters."""
    sets = {}
    for label in labels:
        if label not in known:
            sets.setdefault(tuple(own(label)), []).append(label)
    return sets or {tuple(own(None)): []}


def _shape_errors(scene, labels, avoid, extra, known, subject_fields, framed):
    own = (lambda label: subject_fields.get(label, SUBJECT_FIELDS)) if isinstance(subject_fields, dict) else (
        lambda label: subject_fields)
    scene = retire_fields(scene)
    # Extras may be empty ("" when there is nothing to add): the final prompt still dresses and lights the image.
    plain = [key for key in SECTIONS if key not in ("subjects", "position", "extras")]
    if (not isinstance(scene, dict) or set(scene) != set(FIELDS) | set(extra) | ({"frame"} if framed else set())
            or not all(isinstance(scene[key], str) for key in (*extra, "extras"))
            or not _filled({key: scene[key] for key in plain}, plain)
            or not (_filled(scene["position"], labels) if labels else scene["position"] in ({}, None))
            or (framed and not _framed(scene["frame"], labels))
            or not isinstance(scene["subjects"], dict) or set(scene["subjects"]) != set(labels)
            or not all(_filled(person, KNOWN_SUBJECT_FIELDS if label in known else own(label))
                       for label, person in scene["subjects"].items())):
        sets = _field_sets(labels, known, own)
        fields = "subjects each with " + "; ".join(
            f"{', '.join(fields)}" + (f" ({', '.join(group)})" if len(sets) > 1 else "") for fields, group in sets.items())
        if known:
            fields += f" (known characters {', '.join(sorted(known))} only with {', '.join(KNOWN_SUBJECT_FIELDS)})"
        if framed:
            fields += f"; frame has each label's shows ({', '.join(SHOWS)}) and face ({', '.join(FACES)})"
        return [f"each scene needs {', '.join([*FIELDS, *(['frame'] if framed else [])])}; subjects, position"
                f"{' and frame' if framed else ''} have exactly "
                f"{', '.join(labels) or 'no labels ({})'}; {fields}"]
    text = " ".join(_strings({key: scene[key] for key in SECTIONS}))
    return [f'the user said "{phrase}" but the scene has "{match[0]}"' for phrase, pattern in avoid
            if (match := pattern.search(text))]


def _framed(frame, labels):
    return (isinstance(frame, dict) and set(frame) == set(labels)
            and all(isinstance(item, dict) and set(item) == {"shows", "face"} and item["shows"] in SHOWS
                    and item["face"] in FACES for item in frame.values()))


# The narrowest frame that holds a body part, widest first. A known character's frame decides the final prompt's
# framing, so it must hold every part its own camera shows: a live set framed a character head to knees in every
# image while each camera showed the feet, and the image model followed the frame.
FRAME_PARTS = (("full body", re.compile(r"\b(?:feet|foot|toes|ankles?|soles|heels)\b", re.IGNORECASE)),
               ("head to knees", re.compile(r"\b(?:knees?|thighs?|legs?)\b", re.IGNORECASE)))
_NOT_SHOWN = re.compile(r"\b(?:not|no|without|hidden|cropped|cut off|outside|out of (?:the )?frame)\b", re.IGNORECASE)


def _camera_about(camera, label, labels):
    """The pieces of a camera text about one person: from each mention of their label to the next person's."""
    marks = sorted((match.start(), name) for name in labels
                   for match in re.finditer(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", camera, re.IGNORECASE))
    return [camera[start:marks[index + 1][0] if index + 1 < len(marks) else len(camera)]
            for index, (start, name) in enumerate(marks) if name == label]


def named_frame(texts):
    """(frame, part): the narrowest frame that holds every body part the texts say is shown, or None. A clause that
    says a part is not shown (hidden, out of frame) does not count."""
    for frame, pattern in FRAME_PARTS:
        for text in texts:
            for clause in re.split(r"[;.]", str(text or "")):
                if (found := pattern.search(clause)) and not _NOT_SHOWN.search(clause):
                    return frame, found[0]
    return None


def shown_frame(camera, label, labels):
    """(frame, part): the narrowest frame that holds the body parts the camera says it shows of this person, or None."""
    return named_frame(_camera_about(str(camera or ""), label, labels))


def framed_to_camera(scene):
    """The accepted scene with every frame at least as wide as the body parts its own camera shows of that person
    (shown_frame): the camera owns what is visible, so the frame follows it. A scene whose frames already agree comes
    back unchanged."""
    frames, labels = scene.get("frame"), list(scene.get("frame") or {})
    if not isinstance(frames, dict):
        return scene
    widened = {label: ({**item, "shows": needed[0]} if (needed := shown_frame(scene.get("camera"), label, labels))
                       and SHOWS.index(item["shows"]) > SHOWS.index(needed[0]) else item)
               for label, item in frames.items()}
    return {**scene, "frame": widened} if widened != frames else scene


def framing_problems(scene, known=frozenset()):
    """Why a scene's frames drop someone the image needs, as reasons to ask again ([] when they are right): a known
    character is shown at least head to hips with the face visible (they are what the dataset is about). Everyone else's
    frame is the writer's choice (an adult scene is told to show whoever takes part at least head to hips; checking it
    in code cost a round of rewrites that came back as repeats). The frame dealt to each image (entries.deal_frames)
    only spreads the set: a scene framed otherwise is never asked again for it. A frame narrower than its own camera
    is widened, never asked again (framed_to_camera)."""
    problems = []
    for label, item in (scene.get("frame") or {}).items():
        if label in known and (item["shows"] not in AT_LEAST_HIPS or item["face"] != "visible"):
            problems.append(f"{label} is a known character: show them at least head to hips with the face visible, "
                            "and change the arrangement or viewpoint so the action still shows")
    return problems


def unnamed_people(scene, labels):
    """The character labels a scene's actions never name (an entry copied with its placeholder people)."""
    actions = str(scene.get("actions") or "")
    return [label for label in labels if not re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", actions, re.IGNORECASE)]


def _summary(scene):
    """What a later request reads of an earlier scene, so the set spreads out (known characters have no looks)."""
    # Field by field, so a writer that copies an earlier look never puts its hair into the skin field.
    looks = {label: {"skin": person["skin"], "hair": person["hair"]} for label, person in scene["subjects"].items()
             if "skin" in person and "hair" in person}
    # A character that is not a human is listed by what covers it and its own parts, so later images vary it too.
    looks.update({label: {"covering": person["covering"], "features": person.get("features", "")}
                  for label, person in scene["subjects"].items() if "covering" in person})
    return {"space": scene["space"][:120], "camera": scene["camera"][:80], "actions": scene["actions"][:120],
            "extras": scene["extras"][:120], "looks": looks}


_FILLER = frozenset("a an the and with of in on at to from for by into over his her their its is are".split())


def _words(text, ignore=frozenset()):
    """The words of a text without filler, the ignored words and the possessive "'s" ("man 1's" is the label alone)."""
    return {word for word in re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", str(text).casefold()))
            if word not in _FILLER and word not in ignore}
