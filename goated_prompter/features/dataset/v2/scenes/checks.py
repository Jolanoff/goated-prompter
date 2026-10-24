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
    """Whether the scene puts this person's genitals in or on someone: the actions or another person's position name
    this person's genitals, or the person's own position puts their genitals in, inside or against something (written
    with or without "is")."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    others = " ".join([str(scene.get("actions") or "")] + [str(text) for who, text in position.items() if who != label])
    own = str(position.get(label) or "")
    return bool(re.search(r"(?<![\w-])" + re.escape(label) + r"['’]s " + _PENIS + r"\b", others, re.IGNORECASE)
                or re.search(r"\b(?:his|her|their) " + _PENIS + r" (?:(?:is|are) )?(?:\w+ )?(?:in|inside|into|deep|"
                             r"pressed|between|being)\b", own, re.IGNORECASE))


def _at_work(text):
    """A genitals description without its resting state ("thick, unaroused penis" -> "thick penis")."""
    return re.sub(r",\s*(?=" + _PENIS + r"\b)", " ", _AT_REST.sub("", text)).strip(", ")


def _edit_parts(text, edit):
    """The text with each of its comma or semicolon parts replaced by edit(part); a part edit returns empty for goes."""
    pieces = re.split(r"\s*([,;])\s+", str(text))
    kept = [(sep, new) for sep, part in zip([""] + pieces[1::2], pieces[0::2]) if (new := edit(part))]
    return "".join((f"{sep} " if index else "") + part for index, (sep, part) in enumerate(kept))


def _awake_part(part):
    """A part without a resting state on its genitals ("his genitals visible and unaroused" -> "his genitals visible",
    "soft and pressed against" -> "pressed against"); a part that said nothing but the state ("man 2's genitals are
    unaroused") goes rather than dangle."""
    if not re.search(r"\b" + _PENIS + r"\b", part, re.IGNORECASE):
        return part
    part = re.sub(r"\s*\b(?:unaroused|flaccid|limp|soft)\b(?:\s+and\b)?|\s*(?:and\s+)?\b(?:unaroused|flaccid|limp|soft)\b",
                  "", part, flags=re.IGNORECASE)
    return "" if re.search(r"\b(?:is|are)\s*$", part, re.IGNORECASE) else part


def _own(label):
    """How a position names its own person's body part: "his", "her", "their" or the label's possessive."""
    return r"(?:\b(?:his|her|their)|(?<![\w-])" + re.escape(label) + r"['’]s) "


def _enters(scene, label, labels):
    """Whether the actions or the person's own position put this person's penis in or into another person's body
    ("in man 1's anus"), not into a toy that is in them."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    someone = "(?:" + "|".join(re.escape(other) for other in labels if other != label) + r")['’]s\b"
    into = (r"(?:penis|shaft)\b[^,;.]{0,20}?\b(?:in|inside|into|enter\w*|penetrat\w*)\s+(?:(?:deep|the)\s+)?"
            + someone)
    return len(labels) > 1 and bool(
        re.search(r"(?<![\w-])" + re.escape(label) + r"['’]s " + into, str(scene.get("actions") or ""), re.IGNORECASE)
        or re.search(_own(label) + into, str(position.get(label) or ""), re.IGNORECASE))


def _into(giver, taker):
    """A pattern for giver's penis in or into taker's body; giver is a label or a pattern ("his")."""
    return (giver + r"(?:penis|shaft)\b[^,;.]{0,20}?\b(?:in|inside|into|enter\w*|penetrat\w*)\s+(?:(?:deep|the)\s+)?"
            + r"(?<![\w-])" + re.escape(taker) + r"['’]s\b")


def _reversed_part(scene, label, labels):
    """edit dropping a part of this person's own position that puts their penis into the person whose penis the actions
    put into them: a live receiver's position said "his penis is inside man 2's anus" while the actions said "man 2's
    penis in man 1's anus". When the actions also put this person's penis into that person (two acts), it stays."""
    actions = str(scene.get("actions") or "")
    named = lambda who: r"(?<![\w-])" + re.escape(who) + r"['’]s "
    givers = [other for other in labels if other != label
              and re.search(_into(named(other), label), actions, re.IGNORECASE)
              and not re.search(_into(named(label), other), actions, re.IGNORECASE)]
    if not givers:
        return lambda part: part
    return lambda part: "" if any(re.search(_into(_own(label), giver), part, re.IGNORECASE) for giver in givers) else part


def _named_by_act(scene, label, alone):
    """Whether the actions or another person's position name this person's genitals; for a cast of one, the actions'
    "his penis" is theirs."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    others = " ".join([str(scene.get("actions") or "")] + [str(text) for who, text in position.items() if who != label])
    # "man 3's and man 4's penises" names both.
    return bool(re.search(r"(?<![\w-])" + re.escape(label) + r"['’]s(?: and [\w ]{1,20}?['’]s)? " + _PENIS, others,
                          re.IGNORECASE)
                or (alone and re.search(r"\b(?:his|her|their) " + _PENIS + r"\b", str(scene.get("actions") or ""),
                                        re.IGNORECASE)))


def _stray_part(scene, label, labels):
    """edit for one person's position parts that give their genitals a place the act does not: genitals whose penis is
    already in someone get no second place ("his penis is in man 1's anus; his genitals are near man 1's chest"), and
    genitals the actions do not name touch nothing and nobody ("his penis is joined to a toy", "pressed against the
    toy", "inside a toy that is in man 1's anus"). What the camera sees of them ("his genitals visible"), "hanging
    free", what they wear ("in a harness"), their own body the pose rests them on ("pressed against his chest") and
    what someone does to them ("being stroked") are no place and stay. A part that only goes on describing dropped
    genitals ("his genitals are his thick, | long penis and testicles") goes with it."""
    own = _own(label)
    kept = re.compile(r"\bvisible\b|\bbeing\b|\b(?:against|on) (?:his|her|their) |" + _FREE.pattern, re.IGNORECASE)
    if _enters(scene, label, labels):
        stray = lambda part: (re.search(own + r"(?:genitals|testicles)\b", part, re.IGNORECASE)
                              and not re.search(r"\b(?:penis|shaft)\b", part, re.IGNORECASE))
    elif _named_by_act(scene, label, len(labels) == 1):
        return lambda part: part
    else:
        others = "|".join(re.escape(other) for other in labels if other != label)
        stray = lambda part: re.search(own + _PENIS + r"\b[^,;]*(?:\b(?:against|pressed|joined|attached|rubbing|"
                                       r"touching|resting)\b" + (rf"|(?<![\w-])(?:{others})['’]s\b" if others else "")
                                       + ")", part, re.IGNORECASE)
    dropped = [False]

    def edit(part):
        going = bool(stray(part)) and not kept.search(part)
        # A part with no verb of its own that names genitals right after a dropped one only goes on describing them.
        going = going or (dropped[0] and not re.search(r"\b(?:is|are)\b", part, re.IGNORECASE)
                          and re.search(r"\b(?:penis|testicles)\b", part, re.IGNORECASE))
        dropped[0] = bool(going)
        return "" if going else part
    return edit


def placed_genitals(scene, labels):
    """The accepted scene without "hanging free" or a resting state for genitals the scene uses: a live writer put a
    penis in someone's mouth and also left "his genitals are hanging free" (the image showed it twice or floating), and
    described penises inside someone as "unaroused", in the look and in the position. Nor a penetration the actions
    reverse (_reversed_part) or a place the act does not give them (_stray_part): live writers joined a penis to the toy
    its owner moved and pressed genitals against a toy in someone else. Only those words go; the act that places them
    stays."""
    position = scene.get("position")
    if not isinstance(position, dict):
        return scene
    position = {who: _edit_parts(text, _reversed_part(scene, who, list(labels)))
                if who in labels and isinstance(text, str) else text for who, text in position.items()}
    scene = {**scene, "position": position}
    position = {who: _edit_parts(text, _stray_part(scene, who, list(labels)))
                if who in labels and isinstance(text, str) else text for who, text in position.items()}
    scene = {**scene, "position": position}
    used = [label for label in labels if _genitals_used(scene, label)]
    if not used:
        return scene
    clean = lambda text: _edit_parts(text, lambda part: "" if _FREE.search(part) else part)
    subjects = scene.get("subjects") if isinstance(scene.get("subjects"), dict) else {}
    return {**scene,
            "position": {who: _edit_parts(clean(text), _awake_part) if who in used else text
                         for who, text in position.items()},
            "subjects": {who: ({**person, "genitals": _at_work(clean(person["genitals"])) or person["genitals"]}
                               if who in used and isinstance(person, dict) and isinstance(person.get("genitals"), str)
                               else person) for who, person in subjects.items()}}


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


# Openings and the body parts that go into them. How many things one opening holds is the request's choice; what code
# checks is that the scene does not contradict itself.
OPENINGS = ("mouth", "anus", "vagina")
FILLING_PARTS = "(?:penis|tongue|fingers?|fist)"
# Something that covers or fills the mouth so nothing else fits (a ring that holds the mouth open leaves room).
MOUTH_COVER = re.compile(r"\b(?:ball|bit|bar|panel|tape)[- ]gag\w*|\bgagged\b", re.IGNORECASE)


def _named(label):
    return r"(?<![\w-])" + re.escape(label) + r"(?![\w-])"


def _clauses(texts, labels):
    """The texts as short clauses, with "the mouth of man 2" read as "man 2's mouth"."""
    clauses = []
    for text in texts:
        for label in labels:
            text = re.sub(r"\bthe (" + "|".join(OPENINGS) + r") of " + _named(label), label + r"'s \1", text,
                          flags=re.IGNORECASE)
        clauses += re.split(r"[,;.]|\bwhile\b|\band\b", text, flags=re.IGNORECASE)
    return clauses


def _openings_used(texts, person, other, labels):
    """Which of the person's openings the texts put the other person's penis, tongue, fingers or fist in."""
    return {opening for clause in _clauses(texts, labels) for opening in OPENINGS
            if re.search(_named(person) + r"['’]s " + opening, clause, re.IGNORECASE)
            and re.search(_named(other) + r"['’]s " + FILLING_PARTS, clause, re.IGNORECASE)}


def opening_conflicts(scene, labels):
    """Why a scene contradicts itself about who is in whose mouth or anus, as reasons to ask that image again ([] when
    it does not): the actions and the positions put someone's body part in different places (a live scene's actions
    and positions swapped who was where), or the mouth is covered while a body part is in it. How many things one
    opening holds is never judged: the request decides that."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    actions = [str(scene.get("actions") or "")]
    # In a position, "his" is that position's own person.
    positions = [re.sub(r"\bhis\b", f"{label}'s", str(text), flags=re.IGNORECASE) for label, text in position.items()]
    reasons = []
    for person in labels:
        for other in (label for label in labels if label != person):
            said, placed = (_openings_used(texts, person, other, labels) for texts in (actions, positions))
            if said and placed and said != placed:
                reasons.append(f"the actions put {other}'s body part in {person}'s {' and '.join(sorted(said))} but the "
                               f"positions put it in their {' and '.join(sorted(placed))}: make the actions and every "
                               "position agree")
            if MOUTH_COVER.search(str(position.get(person) or "")) and "mouth" in said | placed:
                reasons.append(f"{person}'s mouth is covered while {other}'s body part is in it: keep one of them")
    return reasons


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


def repeated_parts(scene, other, labels=(), kept=()):
    """What a new scene reuses of another image, as a list: [] unless it reuses that image's place together with its
    camera, actions or extras (an image asked again tends to copy an accepted one's place and signs). The camera
    counts only when its viewpoint and the people's arrangement (position) both match: a fixed place seen from the
    usual side view is not a copy while the people are arranged differently. The character labels never count (every
    place, camera and position names them), and the same place alone is fine (fixed may keep it). kept: the parts the
    request mentions (the brief's kept), which every image keeps, so they are never a copy: the action, the camera,
    and the extras when it mentions what they hold (objects, clothing, light or mood)."""
    ignore = frozenset(word for label in labels for word in re.findall(r"[a-z0-9]+", label.casefold()))
    if _overlap(_without(scene["space"], labels), _without(other["space"], labels)) < .7:
        return []
    kept = set(kept)
    return [name for name, repeated in (
        ("camera", "camera" not in kept
         and _overlap(_viewpoint(scene["camera"], labels), _viewpoint(other["camera"], labels)) >= .6
         and _overlap(_without(_arrangement(scene), labels), _without(_arrangement(other), labels)) >= .6),
        ("actions", "action" not in kept and _overlap(scene["actions"], other["actions"], ignore) >= .6),
        ("extras", not kept & {"objects", "clothing", "light", "mood"}
         and _overlap(scene.get("extras"), other.get("extras"), ignore) >= .7)) if repeated]


def repeat_reason(other, parts):
    """Why a scene is asked again: which image it repeats ("an earlier image" when it is from an earlier batch) and
    what it reuses."""
    name = f"image {other['slot']}" if "slot" in other else "an earlier image"
    return f"it repeats {name}'s place together with its {' and '.join(parts)}; write a different scene"
