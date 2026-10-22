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


# Fields scenes no longer have (the final prompt chooses clothing, light and mood). A writer that still sends them out
# of habit, or a scene saved before, keeps working: they are dropped, never a reason to ask again.
RETIRED_SECTIONS = ("lighting", "mood")


RETIRED_SUBJECT_FIELDS = ("clothing",)


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


_PENIS = r"(?:penis|shaft|genitals)"
_FREE = re.compile(r"\bhanging free\b", re.IGNORECASE)
_AT_REST = re.compile(r"\b(?:unaroused|flaccid|limp|soft)\b,?\s*", re.IGNORECASE)


def _genitals_used(scene, label):
    """Whether the scene puts this person's genitals in or on someone: another person's position or the actions say
    "<label>'s penis", or the person's own position puts "his penis" in, inside or against something."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    others = " ".join([str(scene.get("actions") or "")] + [str(text) for who, text in position.items() if who != label])
    own = str(position.get(label) or "")
    return bool(re.search(r"(?<![\w-])" + re.escape(label) + r"['’]s " + _PENIS + r"\b", others, re.IGNORECASE)
                or re.search(r"\b(?:his|her|their) " + _PENIS + r" (?:is|are) (?:\w+ )?(?:in|inside|into|deep|"
                             r"pressed|between|being)\b", own, re.IGNORECASE))


def _at_work(text):
    """A genitals description without its resting state ("thick, unaroused penis" -> "thick penis")."""
    return re.sub(r",\s*(?=" + _PENIS + r"\b)", " ", _AT_REST.sub("", text)).strip(", ")


def placed_genitals(scene, labels):
    """The accepted scene without "hanging free" or a resting state for genitals the scene uses: a live writer put a
    penis in someone's mouth and also left "his genitals are hanging free" (the image showed it twice or floating), and
    described penises inside someone as "unaroused". Only those words go; the act that places them stays."""
    position = scene.get("position")
    if not isinstance(position, dict):
        return scene
    used = [label for label in labels if _genitals_used(scene, label)]
    if not used:
        return scene
    clean = lambda text: ", ".join(part for part in str(text).split(", ") if not _FREE.search(part))
    subjects = scene.get("subjects") if isinstance(scene.get("subjects"), dict) else {}
    return {**scene,
            "position": {who: clean(text) if who in used else text for who, text in position.items()},
            "subjects": {who: ({**person, "genitals": _at_work(clean(person["genitals"])) or person["genitals"]}
                               if who in used and isinstance(person, dict) and isinstance(person.get("genitals"), str)
                               else person) for who, person in subjects.items()}}


def scene_errors(scene, labels, avoid, extra=(), known=frozenset(), subject_fields=SUBJECT_FIELDS):
    """Why one composed scene is unusable as an answer; [] when its shape is right. extra: further text fields the
    answer must have (the Actions & Poses "entry"); known: labels of known characters (expression only), whose cast
    also needs frame; subject_fields: what everyone else's subjects need (request.subject_fields)."""
    framed = bool(known)
    if isinstance(scene, dict) and not framed:
        scene = {key: value for key, value in scene.items() if key != "frame"}  # a frame nobody asked for is dropped
    return _shape_errors(scene, labels, avoid, extra, known, subject_fields, framed)


def _shape_errors(scene, labels, avoid, extra, known, subject_fields, framed):
    scene = retire_fields(scene)
    plain = [key for key in SECTIONS if key not in ("subjects", "position")]
    if (not isinstance(scene, dict) or set(scene) != set(FIELDS) | set(extra) | ({"frame"} if framed else set())
            or not all(isinstance(scene[key], str) for key in extra)
            or not _filled({key: scene[key] for key in plain}, plain)
            or not (_filled(scene["position"], labels) if labels else scene["position"] in ({}, None))
            or (framed and not _framed(scene["frame"], labels))
            or not isinstance(scene["subjects"], dict) or set(scene["subjects"]) != set(labels)
            or not all(_filled(person, KNOWN_SUBJECT_FIELDS if label in known else subject_fields)
                       for label, person in scene["subjects"].items())):
        fields = f"subjects each with {', '.join(subject_fields)}"
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


def framing_problems(scene, known=frozenset(), dealt=None):
    """Why a scene's frames drop someone the image needs, as reasons to ask again ([] when they are right): a known
    character is shown at least head to hips with the face visible (they are what the dataset is about). Everyone else's
    frame is the writer's choice (an adult scene is told to show whoever takes part at least head to hips; checking it
    in code cost a round of rewrites that came back as repeats). dealt: the frame the image's known characters get
    (entries.deal_frames): that one or wider."""
    problems = []
    allowed = SHOWS[:SHOWS.index(dealt) + 1] if dealt in SHOWS else AT_LEAST_HIPS
    for label, item in (scene.get("frame") or {}).items():
        if label in known and dealt in SHOWS and item["shows"] not in allowed:
            problems.append(f"this image shows {label} {dealt}: frame them that wide (or wider) with the face visible, "
                            "and change the arrangement or viewpoint so the action still shows")
        elif label in known and (item["shows"] not in AT_LEAST_HIPS or item["face"] != "visible"):
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
    return {"space": scene["space"][:120], "camera": scene["camera"][:80], "actions": scene["actions"][:120],
            "extras": scene["extras"][:120], "looks": looks}


_FILLER = frozenset("a an the and with of in on at to from for by into over his her their its is are".split())


def _words(text, ignore=frozenset()):
    """The words of a text without filler, the ignored words and the possessive "'s" ("man 1's" is the label alone)."""
    return {word for word in re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", str(text).casefold()))
            if word not in _FILLER and word not in ignore}


def _overlap(first, second, ignore=frozenset()):
    """How much of the shorter text the other one repeats (0 to 1), ignoring filler words and the character labels."""
    first, second = _words(first, ignore), _words(second, ignore)
    return len(first & second) / min(len(first), len(second)) if first and second else 0.0


def _without(text, labels=()):
    """The text without the character labels themselves ("man 1, man 2 and man 3 on a bed" -> ", and on a bed"); other
    numbers stay ("2 chairs")."""
    for label in sorted(labels, key=len, reverse=True):
        text = re.sub(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", " ", str(text or ""), flags=re.IGNORECASE)
    return str(text or "")


def _viewpoint(camera, labels=()):
    """The camera's opening, up to where it first names a person: the viewpoint ("side view, low angle"), without
    what each person shows, which reads alike in every image."""
    camera = str(camera or "")[:80]
    found = [match.start() for label in labels
             if (match := re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", camera, re.IGNORECASE))]
    return camera[:min(found)] if found and min(found) else camera


def _arrangement(scene):
    """Where each person is, as one text: the scene's position field."""
    position = scene.get("position")
    return " ".join(map(str, position.values())) if isinstance(position, dict) else str(position or "")


def repeated_parts(scene, other, labels=()):
    """What a new scene reuses of another image, as a list: [] unless it reuses that image's place together with its
    camera, actions or extras (an image asked again tends to copy an accepted one's place and signs). The camera
    counts only when its viewpoint and the people's arrangement (position) both match: a fixed place seen from the
    usual side view is not a copy while the people are arranged differently. The character labels never count (every
    place, camera and position names them), and the same place alone is fine (fixed may keep it)."""
    ignore = frozenset(word for label in labels for word in re.findall(r"[a-z0-9]+", label.casefold()))
    if _overlap(_without(scene["space"], labels), _without(other["space"], labels)) < .7:
        return []
    return [name for name, repeated in (
        ("camera", _overlap(_viewpoint(scene["camera"], labels), _viewpoint(other["camera"], labels)) >= .6
         and _overlap(_without(_arrangement(scene), labels), _without(_arrangement(other), labels)) >= .6),
        ("actions", _overlap(scene["actions"], other["actions"], ignore) >= .6),
        ("extras", _overlap(scene.get("extras"), other.get("extras"), ignore) >= .7)) if repeated]


def repeat_reason(other, parts):
    """Why a scene is asked again: which image it repeats ("an earlier image" when it is from an earlier batch) and
    what it reuses."""
    name = f"image {other['slot']}" if "slot" in other else "an earlier image"
    return f"it repeats {name}'s place together with its {' and '.join(parts)}; write a different scene"
