"""Section 3 — Prompts: each composed scene becomes one final prompt through the Builder.

The scene is fixed: the Builder writes it in the target model's format, style and length and may not move anyone,
change the action, add subjects, objects or a conflicting camera. Builder's own target formatting, library
references and clean-up apply unchanged. The Director chosen for the run (request.director_preset) and the target
model shape the final prompt together, as in the Prompt Builder; the scene rules keep the Director from redesigning
what happens. The scene writer itself never sees a Director.

The user's triggers (v2/triggers.py) are applied by code, never left to the model. Exact-text triggers are placed by
place_triggers in the user's exact spelling, pinned ones first, the rest where their kind belongs in the target's
format (an Anima tag line, prose, an Ideogram caption), and the model is told not to write them and not to describe
what they carry; a style trigger also turns the Style setting off. Meaning triggers are written by the model in its own
words. A known character (brief version 12) is named, never described. Code also checks that no numbered character
label ("man 1", "woman2") is left in the prompt; a prompt that still has one after its retry is kept.
"""

from dataclasses import replace
import json
import re

from ...builder.service import GoatedPrompterService, PromptValidationError
from ....backends.recovery import GenerationRecovery, RunawayRecoveryError
from ....options.targets import canonical_target
from ....output_repetition import anima_tag_key
from ....workflow_output import ideogram_json
from .triggers import brief_triggers, locked, owner, placed, trigger_text

SCENE_ORDER = ("subjects", "position", "actions", "space", "lighting", "mood", "camera", "extras")

SCENE_RULES = """
The idea is one scene of an IMAGE, already decided. Write it as one prompt for the
target model. Keep every person, their appearance, every placement, orientation, support, contact
and the action exactly as given; do not move anyone, change the action or add contact. Add only
wording the target format and the Director need. When the idea gives a position name, use that name word for word
together with the action: the target model knows it, so name it instead of only describing the pose.
Do not add subjects, objects or actions, and do not change the camera or light.
Words such as "the first man" or "woman" only tell the people apart: describe each person by appearance and role
rather than by that word."""

KNOWN_RULE = """
KNOWN CHARACTERS: {names} {verb} {noun} the target model already knows. Refer to them by name (with
the character and series tag on tag-based targets) and never describe or change their face, hair, eyes, skin or body;
write only their expression, clothing, pose and action from the idea."""

ADULT_RULE = """
This is an adult dataset: word the act and the bodies in plain, explicit terms, exactly as direct as the scene, in
every prompt. Never soften them into euphemisms, implications or vague wording, whatever the Director's style."""


def position_name(scene):
    """The name of the Actions & Poses entry a scene is built on (the words before its colon), or ""."""
    entry = scene.get("entry") or ""
    name, colon, _ = entry.partition(":")
    return name.strip() if colon and name.strip() else ""


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


def scene_text(scene, known=frozenset()):
    """The scene as plain labelled lines, the Builder's idea. known: labels of known characters."""
    lines = []
    for key in SCENE_ORDER:
        value = scene[key]
        if key == "subjects":
            for label, person in value.items():
                prefix = f"{label} (known character)" if label in known else label
                lines.append(f"{prefix}: " + "; ".join(f"{field} {text}" for field, text in person.items()))
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
        parts.append("Express in every prompt, in your own words: " + "; ".join(
            f'"{trigger["text"]}" ({_meaning(trigger, person)})' for trigger, person in meanings) + ".")
    return "\n".join(parts)


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


def _ordered(triggers):
    """(pinned, the rest), each in list order."""
    return [trigger for trigger in triggers if trigger["start"]], [trigger for trigger in triggers if not trigger["start"]]


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
    kept = [field.strip() for field in head.split(",") if field.strip() and anima_tag_key(field) not in keys]
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
    """A numbered character label ("man 1", "woman_2") left in the prompt, which should describe people instead."""
    for person in brief["characters"]:
        found = re.fullmatch(r"(.+?)\s+(\d+)", person["label"].strip())
        if not found:
            continue  # a name or a single unnumbered label reads naturally in prose
        stem, number = found.groups()
        if re.search(r"\b" + r"\W*".join(map(re.escape, stem.split())) + r"[\s_-]*" + number + r"\b" + _UNIT,
                     prompt, re.IGNORECASE):
            return (f'The prompt calls a person "{person["label"]}". Describe each person by appearance and role '
                    "and never use these labels.")
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
    requirements = "CONFIRMED DATASET REQUIREMENTS\n" + json.dumps({
        "request": brief["input"]["request"], "rules": brief["input"]["rules"],
        "characters": brief["characters"], "people": brief["people"], "fixed": brief["fixed"],
        "must": brief["must"], "avoid": brief["avoid"]}, ensure_ascii=False)
    requirements = unlabel(requirements, brief)
    # An exact-text style trigger carries the style: the Style setting would only fight it.
    style = "Auto" if locked(brief_triggers(brief), "style") else brief["settings"]["style"] or "Auto"
    results = []
    for position, scene in enumerate(scenes, 1):
        number = scene_slot(scene, position)
        progress(f"Writing final prompt {position} of {len(scenes)} (image {number})...")
        idea = unlabel(scene_text(scene, known), brief)
        problem = None
        recovery = GenerationRecovery("dataset_v2:builder", [number], progress=progress)
        for _ in (1, 2):
            adult = ADULT_RULE if brief["path"] == "nsfw_character" else ""
            rules = "\n\n".join(part for part in (SCENE_RULES, _known_rule(brief), adult, requirements,
                                                  _trigger_rule(brief), f"CORRECTION: {problem}" if problem else "")
                                if part)
            builder_request = replace(request, idea=idea, mode="Enhance", planning_mode="Direct",
                                      target_model=brief["settings"]["target"], prompt_length=brief["settings"]["length"],
                                      creativity=brief["settings"]["creativity"], style=style,
                                      director_preset=request.director_preset, custom_instructions=rules,
                                      compile_rules=False)
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
            problem = label_problem(prompt, brief)
            if not problem:
                break
        if results and results[-1]["slot"] == number:
            continue
        prompt = place_triggers(prompt, brief)  # a label left after the retry is not worth failing the image
        problem = trigger_problem(prompt, brief)
        recovery.finish("succeeded" if not problem else "failed")
        results.append({"slot": number, "index": number, "prompt": "" if problem else prompt, "trigger_ok": problem is None})
        if problem:
            results[-1].update(error=problem, stage="dataset_v2:builder", attempts=recovery.attempts)
        on_prompt(results[-1])
    return results
