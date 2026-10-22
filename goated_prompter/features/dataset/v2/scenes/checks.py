"""What code checks in a written scene: its shape, the avoid list, repeats and unnamed people."""

import re

from .settings import FIELDS, KNOWN_SUBJECT_FIELDS, SECTIONS, SUBJECT_FIELDS


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


def scene_errors(scene, labels, avoid, extra=(), known=frozenset(), subject_fields=SUBJECT_FIELDS):
    """Why one composed scene is unusable as an answer; [] when its shape is right. extra: further text fields the
    answer must have (the Actions & Poses "entry"); known: labels of known characters (expression only);
    subject_fields: what everyone else's subjects need (request.subject_fields)."""
    scene = retire_fields(scene)
    plain = [key for key in SECTIONS if key not in ("subjects", "position")]
    if (not isinstance(scene, dict) or set(scene) != set(FIELDS) | set(extra)
            or not all(isinstance(scene[key], str) for key in extra)
            or not _filled({key: scene[key] for key in plain}, plain)
            or not (_filled(scene["position"], labels) if labels else scene["position"] in ({}, None))
            or not isinstance(scene["subjects"], dict) or set(scene["subjects"]) != set(labels)
            or not all(_filled(person, KNOWN_SUBJECT_FIELDS if label in known else subject_fields)
                       for label, person in scene["subjects"].items())):
        fields = f"subjects each with {', '.join(subject_fields)}"
        if known:
            fields += f" (known characters {', '.join(sorted(known))} only with {', '.join(KNOWN_SUBJECT_FIELDS)})"
        return [f"each scene needs {', '.join(FIELDS)}; subjects and position have exactly "
                f"{', '.join(labels) or 'no labels ({})'}; {fields}"]
    text = " ".join(_strings({key: scene[key] for key in SECTIONS}))
    return [f'the user said "{phrase}" but the scene has "{match[0]}"' for phrase, pattern in avoid
            if (match := pattern.search(text))]


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


def repeated_parts(scene, other, labels=()):
    """What a new scene reuses of another image, as a list: [] unless it reuses that image's place together with its
    camera, actions or extras (an image asked again tends to copy an accepted one's place and signs). Only the camera's
    opening (its viewpoint) is compared: the rest says what each person shows, which reads alike in every image. The
    character labels never count (every camera names them), and the same place alone is fine (fixed may keep it)."""
    ignore = frozenset(word for label in labels for word in re.findall(r"[a-z0-9]+", label.casefold()))
    if _overlap(scene["space"], other["space"]) < .7:
        return []
    return [name for name, repeated in (
        ("camera", _overlap(scene["camera"][:80], other["camera"][:80], ignore) >= .6),
        ("actions", _overlap(scene["actions"], other["actions"], ignore) >= .6),
        ("extras", _overlap(scene.get("extras"), other.get("extras"), ignore) >= .7)) if repeated]


def repeat_reason(other, parts):
    """Why a scene is asked again: which image it repeats ("an earlier image" when it is from an earlier batch) and
    what it reuses."""
    name = f"image {other['slot']}" if "slot" in other else "an earlier image"
    return f"it repeats {name}'s place together with its {' and '.join(parts)}; write a different scene"
