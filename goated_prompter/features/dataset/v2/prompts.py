"""Section 3 — Prompts: each composed scene becomes one final prompt through the Builder.

The scene is fixed: the Builder writes it in the target model's format, style and length and may not move anyone,
change the action, add subjects, objects or a conflicting camera. Builder's own target formatting and clean-up apply
unchanged; one set of library templates is picked for the whole run, so every prompt has the same structure. An
entry's position name reaches the Builder only when the scene's actions say it (position_name). The Director chosen for the run (request.director_preset) and the target
model shape the final prompt together, as in the Prompt Builder; the scene rules keep the Director from redesigning
what happens. The scene writer itself never sees a Director.

The user's triggers (v2/triggers.py) are applied by code, never left to the model. Exact-text triggers are placed by
place_triggers in the user's exact spelling, pinned ones first, the rest where their kind belongs in the target's
format (an Anima tag line, prose, an Ideogram caption), and the model is told not to write them and not to describe
what they carry; a style trigger also turns the Style setting off. Meaning triggers are notes the model writes in its
own words: code rejects a prompt that copies a note of COPY_WORDS or more words, or that drops or changes a number
the note gives (meaning_problem). A known character (brief version 12) is named, never described. Code also checks
that no numbered character label ("man 1", "woman2") is left in the prompt. After the one retry a label or copied
wording is kept; a lost number fails the image.
"""

from dataclasses import replace
import json
import random
import re

from ...builder.service import GoatedPrompterService, PromptValidationError
from ....backends.recovery import GenerationRecovery, RunawayRecoveryError
from ....options.targets import canonical_target
from ....output_repetition import anima_tag_key
from ....prompt_library import pick_references
from ....workflow_output import ideogram_json
from .triggers import brief_triggers, owner, placed, run_style, trigger_text

SCENE_ORDER = ("subjects", "position", "actions", "space", "camera", "frame", "extras")
FRAME_TAGS = {"full body": "full body", "head to knees": "cowboy shot", "head to hips": "upper body",
              "head and shoulders": "portrait"}

SCENE_RULES = """
The idea is one scene of an IMAGE, already decided. Write it as one prompt for the
target model. Keep every person, their appearance, every placement, orientation, support, contact, where each one
looks and the action exactly as given; do not move anyone, change the action or add a touch or gaze the positions
cannot reach. What the scene
leaves open follows the Creativity setting. The actions line is the whole action of the image: write
exactly that, with no other act. When the idea gives a position name, use that name word for word together with
the action, as plain words and never in quotes (quotes mark text drawn in the image): the target model knows it, so
name it instead of only describing the pose.
Do not add subjects or actions. Keep the camera's viewpoint (side and height); its distance gives way only when it
would show a person of the scene as nothing more than a body part: then show enough of that person to join the part to
them. Each person's frame is decided: show at least that much of them, and
their face when it is visible; on a tag-based target write the frame's tag for the image (the widest frame of the
scene), never a tighter shot tag. Show the framing by describing what the camera sees: where each
person is relative to the others, which parts of each body are visible and where their faces, torsos, hands and feet
are when it matters, how much space each takes, and what lies in the foreground, middle ground and background. A
shot name or a phrase such as "fully visible" never stands in for that description. Every person of the scene gets a
real presence in the prompt, not only the body parts of the action, and every body part shown is joined to its
owner, who is described in the frame. The scene leaves clothing, light and mood to you: choose
them to suit the scene and the request (and any Clothing, Lighting or Mood entry in its extras). Dress each person
after reading the action: a body part the action uses is bare, so no garment covers it (no underwear, shorts or
trousers over hips the action uses, no top over a chest it uses); clothing goes only on the rest of the body. Describe a body part only when the scene's positions and camera let the camera see it; a
body part turned away, hidden behind or under another body, or inside someone is never described as visible.
A person's label or number only tells the people apart: never write it, and never call a person by their order;
describe each person by their own appearance instead."""

KNOWN_RULE = """
KNOWN CHARACTERS: {names} {verb} {noun} the target model already knows. Refer to them by name (with
the character and series tag on tag-based targets) and never describe or change their face, hair, eyes, skin or body;
write only their expression, clothing, pose and action."""

ADULT_RULE = """
This is an adult dataset: word the act and the bodies in plain, explicit terms, exactly as direct as the scene, in
every prompt. Never soften them into euphemisms, implications or vague wording. Whenever the positions and camera let
the camera see a person's genitals, they get their own short description in that person's description, as concrete as
their skin and build: size, shape and state (relaxed or aroused). Naming them only in the action is not enough.
Genitals the camera cannot see are not described."""


def position_name(scene):
    """The name of the Actions & Poses entry a scene is built on (the words before its colon), or "". The name counts
    only when the scene's actions say it: a writer that had to adapt or swap the entry wrote other actions, and the
    entry's name would then describe a different act."""
    entry = scene.get("entry") or ""
    name, colon, _ = entry.partition(":")
    name = " ".join(name.split())
    actions = " ".join(str(scene.get("actions") or "").split())
    return name if colon and name and name.casefold() in actions.casefold() else ""


ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
            "nineteenth", "twentieth")


def unlabel(text, brief):
    """Numbered labels ("man 1") read as "the first man", so the writer has nothing to copy."""
    for person in brief["characters"]:
        found = re.fullmatch(r"(.+?)\s+(\d+)", person["label"].strip())
        if found and 0 < int(found[2]) <= len(ORDINALS):
            # An article already in front ("the man 1") is part of the replacement, never doubled.
            text = re.sub(r"\b(?:the\s+)?" + re.escape(found[0]) + r"\b", f"the {ORDINALS[int(found[2]) - 1]} {found[1]}",
                          text, flags=re.IGNORECASE)
    return text


# At Creative and Dice a person's role ("the slave", "the queen") is shown, not told: the final writer sees them by
# their own look, and the scene's signs carry the role.
SHOWN_ROLES = ("Creative", "Dice")
_NOUN = {"male": "man", "female": "woman"}


def anchors(scene, brief):
    """{label: how the writer sees that person}: a person whose looks change from image to image is named by their
    own look in this scene ("the man with tan skin") instead of an order ("man 1") or, at Creative and
    Dice, a role ("slave"), so the prompt has an anchor to repeat. Known, triggered and named people keep their label
    (a trigger is placed at its person's mention)."""
    from .scenes import varied_labels
    varied, people = varied_labels(brief), {}
    shown = (brief.get("settings") or {}).get("creativity") in SHOWN_ROLES
    # Written as words, never in brackets or with commas: brackets weigh tags in tag-based targets and commas split a
    # tag line, so an anchor reads the same in prose and in a tag line.
    plain = lambda value: re.sub(r"\s*[,;()\[\]]+\s*", " ", str(value or "")).strip()
    for person in brief["characters"]:
        found = re.fullmatch(r"(.+?)\s+(\d+)", person["label"].strip())
        look = (scene.get("subjects") or {}).get(person["label"]) or {}
        if person["label"] not in varied or not (found or shown):
            continue
        noun = _NOUN.get(person.get("gender")) if shown else None
        noun = noun or (found[1] if found else person["label"])
        hair = plain(look.get("hair"))
        hair = hair if not hair or re.search(r"\bhair\b", hair) else f"{hair} hair"
        # The name takes the skin's tone (its first part); the full skin description still reaches the prompt.
        tone = plain(str(look.get("skin") or "").split(",")[0])
        details = [part for part in (f"{tone} skin" if tone else "", hair,
                                     plain(look.get("detail"))) if part]
        if details:
            people[person["label"]] = (noun, details)
    # Everyone gets the same amount of look: the least that tells them all apart, so no anchor is part of another.
    for size in range(1, 4):
        result = {label: f"the {noun} with {' and '.join(details[:size])}" for label, (noun, details) in people.items()}
        if len(set(result.values())) == len(result):
            return result
    return {label: anchor for label, anchor in result.items() if list(result.values()).count(anchor) == 1}


def name_people(text, brief, scene):
    """The text with every anchored label replaced by its person's look anchor in this scene (anchors), and any
    numbered label without one by its ordinal (unlabel). Quoted words (text written on something) stay as they are."""
    found = anchors(scene, brief)
    parts = re.split(r'("[^"]*"|“[^”]*”)', text)
    for index in range(0, len(parts), 2):
        for label, anchor in found.items():
            parts[index] = re.sub(r"\b(?:(?:the|a|an|his|her|their|its)\s+)?" + re.escape(label) + r"\b",
                                  lambda _match: anchor, parts[index], flags=re.IGNORECASE)
    return unlabel("".join(parts), brief)


def _requirements(brief, scene):
    """The confirmed requirements for one scene's final prompt, with every person named as in that scene's idea."""
    name = lambda text: name_people(text, brief, scene)
    return ("CONFIRMED DATASET REQUIREMENTS (the scene was written from these: where the scene contradicts them, "
            "they win)\n") + json.dumps({
        "rules": [name(rule) for rule in brief["input"]["rules"]],
        "characters": [{**person, "label": name(person["label"])} for person in brief["characters"]],
        "people": brief["people"], "must": [name(item) for item in brief["must"]],
        "avoid": [name(item) for item in brief["avoid"]]}, ensure_ascii=False)


def scene_text(scene, known=frozenset()):
    """The scene as plain labelled lines, the Builder's idea. known: labels of known characters. A scene saved with
    retired fields (clothing, light, mood) is read without them: the final prompt chooses those."""
    from .scenes import retire_fields
    scene = retire_fields(scene)
    lines = []
    for key in SCENE_ORDER:
        if key not in scene:  # a scene saved before frames
            continue
        value = scene[key]
        if key == "subjects":
            for label, person in value.items():
                prefix = f"{label} (known character)" if label in known else label
                lines.append(f"{prefix}: " + "; ".join(f"{field} {text}" for field, text in person.items()))
        elif key == "frame":
            lines.extend(f"frame of {label}: shows {item['shows']} (tag: {FRAME_TAGS[item['shows']]}), face {item['face']}"
                         for label, item in value.items())
        elif isinstance(value, dict):
            lines.extend(f"{key} of {label}: {text}" for label, text in value.items())
        else:
            lines.append(f"{key}: {value}")
        if key == "actions" and position_name(scene):
            lines.append(f"position name: {position_name(scene)}")
    return "\n".join(lines)


def _covers(trigger, person):
    """What an exact-text trigger already carries, so the model never describes it; None when it carries nothing."""
    whose = f"{person}'s" if person else "its person's"
    return {"character": f"{whose} face, hair, eyes, skin and body", "outfit": f"{whose} outfit",
            "style": "the visual style, medium and rendering", "object": "the object or concept it names"}.get(trigger["kind"])


def _meaning(trigger, person):
    who = person or "its person"
    return {"character": f"who {who} is and how they look", "outfit": f"what {who} wears",
            "style": "the visual style of every image", "object": "an object or concept in the image",
            "other": "the whole image"}[trigger["kind"]]


def _trigger_rule(brief):
    triggers = brief_triggers(brief)
    people = [owner(brief, number) for number in range(1, len(triggers) + 1)]
    parts = []
    if exact := placed(triggers):
        parts.append("TRIGGERS: the app adds these exact texts to the prompt itself; do not write them or a variant of "
                     "them: " + "; ".join(f'"{trigger_text(trigger)}"' for trigger in exact) + ".")
    if covered := [phrase for trigger, person in zip(triggers, people)
                   if trigger["expand"] == "off" and (phrase := _covers(trigger, person))]:
        parts.append("Their texts already carry " + "; ".join(covered) + ". Never describe these.")
    if meanings := [(trigger, person) for trigger, person in zip(triggers, people) if trigger["expand"] != "off"]:
        parts.append("MEANINGS: write in every prompt, in your own words, what each of these notes says. They are notes, "
                     "not prompt text: never copy their wording, but keep every number they give.\n" + "\n".join(
                         f"- {_meaning(trigger, person)}: {trigger['text']}" for trigger, person in meanings))
    return "\n".join(parts)


# A meaning of one or two words may simply be the natural wording, so only longer ones must be rewritten.
COPY_WORDS = 3


def _flat(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def meaning_problem(prompt, brief):
    """(why the prompt mishandles a meaning-only trigger, whether that loses a fact) or None: it copied the note's
    wording, or it dropped or changed a number the note gives."""
    flat = _flat(prompt)
    for trigger in brief_triggers(brief):
        if trigger["expand"] != "on":
            continue
        for number in re.findall(r"\d+(?:[.,]\d+)?", trigger["text"]):
            if not re.search(r"(?<![\d.,])" + re.escape(number) + r"(?![\d]|[.,]\d)", prompt):
                return (f'The prompt must keep the number {number} from the note "{trigger["text"]}".', True)
        words = _flat(trigger["text"])
        if len(words.split()) >= COPY_WORDS and re.search(r"\b" + re.escape(words) + r"\b", flat):
            return (f'The prompt copies the note "{trigger["text"]}" word for word. Write what it says in your own '
                    "words instead.", False)
    return None


def _known_rule(brief):
    names = [person["label"] for person in brief["characters"] if person.get("known") is True]
    if not names:
        return ""
    one = len(names) == 1
    return KNOWN_RULE.format(names=" and ".join(names), verb="is" if one else "are",
                             noun="an established character" if one else "established characters")


_META_TAG = re.compile(r"(?:score[_ ]\d+(?:[_ ]up)?|masterpiece|(?:best|good|normal|high|amazing|low|worst) quality|absurdres|"
                       r"highres|newest|recent|mid|early|old|year \d{4}|safe|sensitive|nsfw|explicit|questionable|general|"
                       r"\d+\+?(?:boy|girl|other)s?|multiple (?:boys|girls|others)|solo|no humans)", re.IGNORECASE)


def _plain_tag(field):
    return re.sub(r":\d+(?:\.\d+)?\)?$", "", field.strip()).lstrip("(").strip().replace("_", " ")


def _tag_line(text):
    """Whether text is a comma-separated tag line rather than prose."""
    fields = [field.strip() for field in text.split(",") if field.strip()]
    return (len(fields) >= 2 and "\n" not in text.strip() and all(1 <= len(field.split()) <= 8 for field in fields)
            and not re.search(r"[a-z]{2,}[.!?](?:\s+[A-Z]|\s*$)", text))


# Anima's people-count tags (danbooru): 1boy, 2girls, 1other, solo, and the loose forms models invent ("2people").
# "solo focus" is a tag of its own; any other solo phrase a model invents ("solo man") is a count tag.
_COUNT_TAG = re.compile(r"\d+\+?\s*(?:boy|girl|other|people|person|persons|man|men|woman|women)s?|"
                        r"solo(?!\s+focus$)(?:[\s-].*)?|multiple (?:boys|girls|others|people)", re.IGNORECASE)
# Quality tags that belong in a negative prompt, never in the positive one.
_LOW_QUALITY_TAG = re.compile(r"(?:worst|low|bad) quality|lowres", re.IGNORECASE)
# Anima's score tags keep their underscores; every other tag is written with spaces.
_SCORE_TAG = re.compile(r"score_\d+(?:_up)?", re.IGNORECASE)
# Anima's quality tags (score, quality and year tags) and its safety tags, which come first and in that order.
_QUALITY_TAG = re.compile(r"score \d+(?: up)?|masterpiece|(?:best|good|normal|high|amazing) quality|absurdres|highres|"
                          r"newest|recent|mid|early|old|year \d{4}", re.IGNORECASE)
_SAFETY_TAG = re.compile(r"(?:rating\s*:?\s*)?(safe|sensitive|nsfw|explicit|questionable|general)", re.IGNORECASE)
# Anima's framing tags, widest first: a scene's widest frame decides the one the image gets (FRAME_TAGS).
SHOT_TAGS = ("full body", "cowboy shot", "upper body", "portrait", "close-up")


def count_tags(characters):
    """The cast as Anima count tags: men are boys, women are girls, anyone else other; solo for one person."""
    counts = {}
    for person in characters:
        kind = {"male": "boy", "female": "girl"}.get(person.get("gender"), "other")
        counts[kind] = counts.get(kind, 0) + int(person.get("count") or 1)
    tags = [f"{number}{kind}{'s' if number > 1 else ''}" for kind in ("boy", "girl", "other")
            if (number := counts.get(kind))]
    return tags + (["solo"] if sum(counts.values()) == 1 else [])


def scene_shot(scene):
    """The framing tag of a scene's widest frame ("full body", "cowboy shot"...), or None for a scene without frames."""
    shows = [item["shows"] for item in ((scene or {}).get("frame") or {}).values() if isinstance(item, dict)]
    tags = [FRAME_TAGS[value] for value in shows if value in FRAME_TAGS]
    return min(tags, key=SHOT_TAGS.index) if tags else None


def anima_tag_line(prompt, brief, scene=None):
    """An Anima prompt's tag line in Anima's own format: the cast's count tags (the app knows the cast; a model guesses
    them), quality tags first, then one safety tag, then the count tags; spaces instead of underscores (score tags keep
    theirs); no low-quality, unknown score or invented solo tags. With a scene, its framing tag is the one framing tag
    (scene_shot: a model's tighter shot tag would crop the people the scene keeps in frame), and with several people
    "solo focus" is dropped. Prose is left as written."""
    # The tag lines are the leading lines that are tag lines (a model sometimes breaks them over several lines or
    # blocks); everything after them is prose, separated by one blank line as Anima expects.
    lines = prompt.strip().splitlines()
    count = end = 0
    while count < len(lines) and (not lines[count].strip() or _tag_line(lines[count].strip().rstrip(","))):
        count += 1
        end = count if lines[count - 1].strip() else end
    count = end
    if not count:
        return prompt
    head = ", ".join(line.strip().rstrip(",") for line in lines[:count] if line.strip())
    prose = "\n".join(lines[count:]).strip()
    separator, rest = ("\n\n", prose) if prose else ("", "")
    quality, safety, tags = [], [], []
    shot = scene_shot(scene)
    several = sum(int(person.get("count") or 1) for person in brief["characters"]) > 1
    for field in (field.strip() for field in head.split(",")):
        plain = _plain_tag(field).strip("[]").strip()
        if not field or _COUNT_TAG.fullmatch(plain) or _LOW_QUALITY_TAG.fullmatch(plain):
            continue
        if (shot and plain.casefold() in SHOT_TAGS) or (several and plain.casefold() == "solo focus"):
            continue
        if plain.casefold().startswith("score") and not _QUALITY_TAG.fullmatch(plain):
            continue  # a score tag Anima does not know
        if rating := _SAFETY_TAG.fullmatch(plain):
            safety.append(rating[1].casefold())  # one safety tag, in Anima's spelling
            continue
        if not _SCORE_TAG.search(field):
            field = re.sub(r"(?<!\\)_", " ", field)
        group = quality if _QUALITY_TAG.fullmatch(plain) else tags
        if field.casefold() not in (tag.casefold() for tag in quality + tags):
            group.append(field)
    people = count_tags(brief["characters"]) if brief["characters"] else []
    return ", ".join([*quality, *safety[:1], *people, *([shot] if shot else []), *tags]) + separator + rest


def _ordered(triggers):
    """(pinned, the rest), each in list order."""
    return [trigger for trigger in triggers if trigger["start"]], [trigger for trigger in triggers if not trigger["start"]]


def _tag_base(tag):
    """A tag's key without its qualifiers in parentheses, nested ones too ("cu chulainn (fate)" -> "cuchulainn",
    "fate (fate (series))" -> "fate")."""
    plain = re.sub(r":\d+(?:\.\d+)?\)?$", "", tag.strip())
    return anima_tag_key(re.split(r"\s*\\?\(", plain, maxsplit=1)[0] or plain)


def _anima_with_triggers(prompt, triggers):
    """The tag line, in Anima's section order: pinned triggers; quality, safety and count tags; character and outfit
    triggers; style and other triggers; the model's other tags; object triggers. Tags the model wrote for a trigger in
    another spelling (underscores, unescaped parentheses, other case) are replaced by the user's exact text."""
    texts = [trigger_text(trigger) for trigger in triggers]
    parts = re.split(r"(\r?\n[ \t]*\r?\n)", prompt, maxsplit=1)
    head, separator, rest = (parts + ["", ""])[:3]
    pinned, others = _ordered(triggers)
    if not _tag_line(head):
        # No leading tag line to edit: the triggers become one.
        return ", ".join(trigger_text(trigger) for trigger in pinned + others) + "\n\n" + prompt.strip()
    keys = {anima_tag_key(tag) for text in texts for tag in text.split(",") if tag.strip()}
    # A trigger is exact text: the model's own forms of its tags go, also the name without its qualifier ("cu chulainn"
    # for "cu chulainn \(fate\)") and the name with another qualifier ("fate \(fate_series\)" for "fate \(series\)").
    bases = {_tag_base(tag) for text in texts for tag in text.split(",") if _tag_base(tag) != anima_tag_key(tag)}
    kept = [field.strip() for field in head.split(",") if field.strip() and anima_tag_key(field) not in keys
            and _tag_base(field) not in bases]
    meta = next((index for index, field in enumerate(kept) if not _META_TAG.fullmatch(_plain_tag(field))), len(kept))
    group = lambda *kinds: [trigger_text(trigger) for trigger in others if trigger["kind"] in kinds]
    fields = [*map(trigger_text, pinned), *kept[:meta], *group("character", "outfit"), *group("style", "other"),
              *kept[meta:], *group("object")]
    return ", ".join(fields) + separator + rest


def _mention(text, names):
    """Where one of a person's names is first mentioned as a word in text, or -1."""
    found = [match.start() for name in names or () if name
             for match in [re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text, re.IGNORECASE)] if match]
    return min(found, default=-1)


def _without(text, trigger):
    """text with the trigger's exact text taken out where it stands as its own list item (it is placed again)."""
    found = text.casefold().find(trigger.casefold())
    if found < 0 or not re.search(r"(?:^|[,;]\s*)$", text[:found]) or not re.match(r"\s*(?:[,;.]|$)", text[found + len(trigger):]):
        return text
    text = text[:found] + text[found + len(trigger):]
    text = re.sub(r"[ \t]{2,}", " ", re.sub(r"\s+([,.;:!?])", r"\1", text)).strip()
    return re.sub(r"^[,;:.]\s*|[,;]\s*(?=[,;.])", "", text)


def _lead(texts, text):
    """texts in front of text, comma separated."""
    texts = [item for item in texts if item]
    if not texts:
        return text
    lead = ", ".join(texts)
    return lead + ("" if not text else " " if lead[-1] in ",.;:" else ", ") + text.lstrip()


def _prose_with_triggers(prompt, triggers, owners):
    """Prose: a character trigger goes in front of its person's first mention ("the clo21 woman kneels"); pinned
    triggers lead the prompt, then every other trigger. A trigger already standing as its own list item is moved."""
    for trigger in triggers:
        prompt = _without(prompt, trigger_text(trigger))
    pinned, others = _ordered(triggers)
    lead = []
    for trigger in others:
        text = trigger_text(trigger)
        position = _mention(prompt, owners.get(id(trigger))) if trigger["kind"] == "character" else -1
        if position >= 0 and text.casefold() not in prompt.casefold():
            prompt = prompt[:position] + text + " " + prompt[position:]
        elif text.casefold() not in prompt.casefold() or trigger["kind"] != "character":
            lead.append(text)
    return _lead([*map(trigger_text, pinned), *lead], prompt)


def _caption_with_triggers(prompt, triggers, owners):
    """An Ideogram caption: character and outfit triggers lead the description of the element that mentions their
    person, style triggers lead style_description.aesthetics, and the rest (and pinned ones, first) lead
    high_level_description, the caption's first text."""
    try:
        caption = json.loads(prompt)
    except ValueError:
        return prompt  # not a caption: trigger_problem reports it
    elements = caption["compositional_deconstruction"]["elements"]
    style = caption.get("style_description")
    pinned, others = _ordered(triggers)
    lead = []
    for trigger in others:
        text = trigger_text(trigger)
        element = next((item for item in elements if trigger["kind"] in ("character", "outfit")
                        and _mention(item["desc"], owners.get(id(trigger))) >= 0), None)
        if element is not None:
            element["desc"] = _lead([text], _without(element["desc"], text))
        elif trigger["kind"] == "style" and style:
            style["aesthetics"] = _lead([text], _without(style["aesthetics"], text))
        else:
            lead.append(text)
    summary = caption.get("high_level_description", "")
    for text in map(trigger_text, pinned + others):
        summary = _without(summary, text)
    summary = _lead([*map(trigger_text, pinned), *lead], summary)
    return ideogram_json({**({"high_level_description": summary} if summary else {}),
                          **{key: value for key, value in caption.items() if key != "high_level_description"}})


def place_triggers(prompt, brief):
    """The final prompt with the exact text of every exact-text trigger in it, placed for the target's format."""
    every = brief_triggers(brief)
    triggers = placed(every)
    if not triggers or not prompt.strip():
        return prompt
    # A person is found by their label or, for a numbered label, the ordinal the writer saw ("first man").
    owners = {id(trigger): [label, re.sub(r"^the\s+", "", unlabel(label, brief))] if (label := owner(brief, number)) else []
              for number, trigger in enumerate(every, 1)}
    target = canonical_target(brief["settings"]["target"])
    if target == "Ideogram4":
        return _caption_with_triggers(prompt, triggers, owners)
    if target == "Anima":
        return _anima_with_triggers(prompt, triggers)
    return _prose_with_triggers(prompt, triggers, owners)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def trigger_problem(prompt, brief):
    """Why the final prompt does not carry its exact-text triggers as asked, or None."""
    triggers = placed(brief_triggers(brief))
    if not triggers:
        return None
    first = prompt
    texts = [prompt]
    if canonical_target(brief["settings"]["target"]) == "Ideogram4":
        try:
            caption = json.loads(prompt)
        except ValueError:
            return "The prompt is not an Ideogram caption."
        first, texts = caption.get("high_level_description", ""), list(_strings(caption))
    for trigger in triggers:
        if not any(trigger_text(trigger) in text for text in texts):
            return f'The prompt must contain the exact text "{trigger_text(trigger)}".'
    pinned = ", ".join(trigger_text(trigger) for trigger in triggers if trigger["start"])
    if pinned and not first.lstrip().startswith(pinned):
        return f'The prompt must begin with "{pinned}".'
    return None


_UNIT = r"(?!\s*(?:m|cm|mm|km|ft|in|meters?|metres?|feet|foot|inch(?:es)?|yards?|steps?|%)\b)"


def label_problem(prompt, brief):
    """A numbered character label ("man 1", "woman_2") or the ordinal the writer saw for it ("the first man") left in
    the prompt, which should describe people by their look instead."""
    for person in brief["characters"]:
        found = re.fullmatch(r"(.+?)\s+(\d+)", person["label"].strip())
        if not found:
            continue  # a name or a single unnumbered label reads naturally in prose
        stem, number = found.groups()
        words = r"\W*".join(map(re.escape, stem.split()))
        if re.search(r"\b" + words + r"[\s_-]*" + number + r"\b" + _UNIT, prompt, re.IGNORECASE):
            return (f'The prompt calls a person "{person["label"]}". Describe each person by appearance and role '
                    "and never use these labels.")
        if 0 < int(number) <= len(ORDINALS) and (match := re.search(
                r"\b" + ORDINALS[int(number) - 1] + r"\s+" + words + r"\b", prompt, re.IGNORECASE)):
            return (f'The prompt calls a person "{match[0]}". Name each person by one short anchor from their own '
                    "look instead, and never by their order.")
    return None


def scene_slot(scene, position):
    """The image a scene belongs to: its "slot" (write_scenes sets it), else its 1-based position."""
    slot = scene.get("slot")
    return slot if type(slot) is int and slot > 0 else position


def write_prompts(config, request, brief, scenes, *, checkpoint=lambda: None, progress=print, on_prompt=lambda item: None):
    """One final prompt per scene, in scene order; on_prompt gets each one as it is written.
    Each item is keyed by the scene's slot ("slot", and "index" with the same value), never by its
    position in the list, so a failed earlier image never renumbers a later one."""
    service = GoatedPrompterService(config, checkpoint=checkpoint)
    known = frozenset(person["label"] for person in brief["characters"] if person.get("known") is True)
    # The raw request and "fixed" are sentences the scene already carries: shown again, the model pastes them into the
    # prompt as content. The people, rules and must/avoid stay, since a drifted scene could lose them.
    # A style trigger carries the style: the Style setting would only fight it.
    style, capture = run_style(brief)
    describe_style = not any(trigger["kind"] == "style" and trigger["expand"] == "off"
                             for trigger in brief_triggers(brief))
    # One set of library templates for the whole run, so every prompt of the dataset has the same structure.
    templates = pick_references(brief["settings"]["target"], brief["input"]["request"],
                                rng=random.Random(brief["input"].get("seed")))
    results = []
    for position, scene in enumerate(scenes, 1):
        number = scene_slot(scene, position)
        progress(f"Writing final prompt {position} of {len(scenes)} (image {number})...")
        idea = name_people(scene_text(scene, known), brief, scene)
        named = _requirements(brief, scene)
        problem = None
        recovery = GenerationRecovery("dataset_v2:builder", [number], progress=progress)
        for _ in (1, 2):
            adult = ADULT_RULE if brief["path"] == "nsfw_character" else ""
            rules = "\n\n".join(part for part in (SCENE_RULES, _known_rule(brief), adult, named,
                                                  _trigger_rule(brief), f"CORRECTION: {problem}" if problem else "")
                                if part)
            builder_request = replace(request, idea=idea, mode="Enhance", planning_mode="Direct",
                                      target_model=brief["settings"]["target"], prompt_length=brief["settings"]["length"],
                                      creativity=brief["settings"]["creativity"], style=style, capture=capture, describe_style=describe_style,
                                      director_preset=request.director_preset, custom_instructions=rules,
                                      compile_rules=False, library_references=templates)
            try:
                prompt = service.generate_text_only(builder_request, seed=brief["input"].get("seed"), recovery=recovery).prompt
            except RunawayRecoveryError as error:
                recovery.finish("failed")
                results.append({"slot": number, "index": number, "prompt": "", "trigger_ok": False, "error": str(error),
                                "stage": error.stage, "attempts": error.attempts, "reason": error.reason})
                on_prompt(results[-1])
                break
            except PromptValidationError as error:
                recovery.finish("failed")
                results.append({"slot": number, "index": number, "prompt": "", "trigger_ok": False, "error": str(error),
                                "stage": "dataset_v2:builder", "attempts": error.attempts})
                on_prompt(results[-1])
                break
            meaning = meaning_problem(prompt, brief)
            problem = label_problem(prompt, brief) or (meaning[0] if meaning else None)
            if not problem:
                break
        if results and results[-1]["slot"] == number:
            continue
        # A label or copied wording left after the retry is not worth failing the image; a lost number is a wrong fact.
        if canonical_target(brief["settings"]["target"]) == "Anima":
            prompt = anima_tag_line(prompt, brief, scene)
        prompt = place_triggers(prompt, brief)
        problem = trigger_problem(prompt, brief) or (meaning[0] if meaning and meaning[1] else None)
        recovery.finish("succeeded" if not problem else "failed")
        results.append({"slot": number, "index": number, "prompt": "" if problem else prompt, "trigger_ok": problem is None})
        if problem:
            results[-1].update(error=problem, stage="dataset_v2:builder", attempts=recovery.attempts)
        on_prompt(results[-1])
    return results
