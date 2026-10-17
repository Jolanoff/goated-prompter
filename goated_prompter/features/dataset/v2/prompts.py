"""Section 3 — Prompts: each composed scene becomes one final prompt through the Builder.

The scene is fixed: the Builder writes it in the target model's format, style and length and may not move anyone,
change the action, add subjects, objects or a conflicting camera. Builder's own target formatting, library
references and clean-up apply unchanged. The Director chosen for the run (request.director_preset) and the target
model shape the final prompt together, as in the Prompt Builder; the scene rules keep the Director from redesigning
what happens. The scene writer itself never sees a Director.

Code checks the user's exact trigger (a prompt without it is retried once, then marked failed) and that no numbered
character label ("man 1", "woman2") is left in the prompt; a prompt that still has one after its retry is kept.
"""

from dataclasses import replace
import json
import re

from ...builder.service import GoatedPrompterService, PromptValidationError
from ....backends.recovery import GenerationRecovery, RunawayRecoveryError
from .debug import DebugTrace

SCENE_ORDER = ("subjects", "position", "actions", "space", "lighting", "mood", "camera", "extras")

SCENE_RULES = """
The idea is one scene of an IMAGE, already decided. Write it as one prompt for the
target model. Keep every person, their appearance, every placement, orientation, support, contact
and the action exactly as given; do not move anyone, change the action or add contact. Add only
wording the target format and the Director need: the Director decides how explicitly the action and bodies
are worded. Do not add subjects, objects or actions, and do not change the camera or light.
Labels such as "man 1" or "woman" only tell the people apart: describe each person by appearance and role
("the taller man", "his partner"), never by the label itself."""


def scene_text(scene):
    """The scene as plain labelled lines, the Builder's idea."""
    lines = []
    for key in SCENE_ORDER:
        value = scene[key]
        if key == "subjects":
            for label, person in value.items():
                lines.append(f"{label}: " + "; ".join(f"{field} {text}" for field, text in person.items()))
        elif isinstance(value, dict):
            lines.extend(f"{key} of {label}: {text}" for label, text in value.items())
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _trigger_rule(brief):
    trigger = brief["input"]["trigger"]
    if not trigger:
        return ""
    where = "Begin the prompt with it." if brief["input"]["trigger_at_start"] else "Place it where it reads naturally."
    return f'TRIGGER: include this exact, case-sensitive text once: "{trigger}". {where}'


def trigger_problem(prompt, brief):
    trigger = brief["input"]["trigger"]
    if not trigger:
        return None
    if trigger not in prompt:
        return f'The prompt must contain the exact text "{trigger}".'
    if brief["input"]["trigger_at_start"] and not prompt.lstrip().startswith(trigger):
        return f'The prompt must begin with "{trigger}".'
    return None


def label_problem(prompt, brief):
    """A numbered character label ("man 1", "woman_2") left in the prompt, which should describe people instead."""
    for person in brief["characters"]:
        found = re.fullmatch(r"(.+?)\s+(\d+)", person["label"].strip())
        if not found:
            continue  # a name or a single unnumbered label reads naturally in prose
        stem, number = found.groups()
        if re.search(r"\b" + r"\W*".join(map(re.escape, stem.split())) + r"[\s_-]*" + number + r"\b", prompt, re.IGNORECASE):
            return (f'The prompt calls a person "{person["label"]}". Describe each person by appearance and role '
                    "(\"the taller man\", \"his partner\") and never use these labels.")
    return None


def scene_slot(scene, position):
    """The image a scene belongs to: its "slot" (write_scenes sets it), else its 1-based position."""
    slot = scene.get("slot")
    return slot if type(slot) is int and slot > 0 else position


def write_prompts(config, request, brief, scenes, *, checkpoint=lambda: None, progress=print, on_prompt=lambda item: None):
    """One final prompt per scene, in scene order; on_prompt gets each one as it is written.
    Each item is keyed by the scene's slot ("slot", and "index" with the same value), never by its
    position in the list, so a failed earlier image never renumbers a later one.
    One debug JSON file per run."""
    trace = DebugTrace("prompts", amount=len(scenes), target=brief["settings"]["target"], trigger=brief["input"]["trigger"],
                       trigger_at_start=brief["input"]["trigger_at_start"])
    service = GoatedPrompterService(config, checkpoint=checkpoint)
    requirements = "CONFIRMED DATASET REQUIREMENTS\n" + json.dumps({
        "request": brief["input"]["request"], "rules": brief["input"]["rules"],
        "characters": brief["characters"], "people": brief["people"], "fixed": brief["fixed"],
        "must": brief["must"], "avoid": brief["avoid"]}, ensure_ascii=False)
    results = []
    try:
        for position, scene in enumerate(scenes, 1):
            number = scene_slot(scene, position)
            progress(f"Writing final prompt {position} of {len(scenes)} (image {number})...")
            idea = scene_text(scene)
            problem = None
            recovery = GenerationRecovery("dataset_v2:builder", [number],
                report=lambda detail: trace.decide("runaway_recovery", detail), progress=progress)
            for attempt in (1, 2):
                rules = "\n\n".join(part for part in (SCENE_RULES, requirements, _trigger_rule(brief),
                                                      f"CORRECTION: {problem}" if problem else "") if part)
                builder_request = replace(request, idea=idea, mode="Enhance", planning_mode="Direct",
                                          target_model=brief["settings"]["target"], prompt_length=brief["settings"]["length"],
                                          creativity=brief["settings"]["creativity"], style=brief["settings"]["style"] or "Auto",
                                          director_preset=request.director_preset, custom_instructions=rules)
                try:
                    prompt = service.generate_text_only(builder_request, seed=brief["input"].get("seed"), recovery=recovery).prompt
                except RunawayRecoveryError as error:
                    recovery.finish("failed")
                    results.append({"slot": number, "index": number, "prompt": "", "trigger_ok": False, "error": str(error),
                                    "stage": error.stage, "attempts": error.attempts, "reason": error.reason})
                    trace.decide("prompt_failed", results[-1])
                    on_prompt(results[-1])
                    break
                except PromptValidationError as error:
                    recovery.finish("failed")
                    results.append({"slot": number, "index": number, "prompt": "", "trigger_ok": False, "error": str(error),
                                    "stage": "dataset_v2:builder", "attempts": error.attempts})
                    trace.decide("prompt_failed", results[-1])
                    on_prompt(results[-1])
                    break
                problem = trigger_problem(prompt, brief) or label_problem(prompt, brief)
                trace.attempt(scene=number, attempt=attempt, idea=idea, rules=rules, prompt=prompt, problem=problem)
                if not problem:
                    break
            if results and results[-1]["slot"] == number:
                continue
            problem = trigger_problem(prompt, brief)  # a label left after the retry is not worth failing the image
            recovery.finish("succeeded" if not problem else "failed")
            results.append({"slot": number, "index": number, "prompt": "" if problem else prompt,
                            "trigger_ok": trigger_problem(prompt, brief) is None})
            if problem:
                results[-1].update(error=problem, stage="dataset_v2:builder", attempts=recovery.attempts)
                trace.decide("prompt_rejected", {"scene": number, "problem": problem})
            on_prompt(results[-1])
    except Exception as error:
        trace.finish(error=f"{type(error).__name__}: {error}")
        raise
    trace.finish(output=results)
    return results
