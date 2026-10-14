"""Section 3 — Prompts: each written scene becomes one final prompt through the Builder.

The scene is fixed: the Builder writes it in the target model's format, style and length with the
selected Director, and may not move anyone, change the action or add contact. Builder's own target
formatting and clean-up apply unchanged (Dataset delegates final writing to the Builder).

Code checks one thing: when the user gave a trigger, the prompt contains it exactly (and starts
with it when "Require trigger at start" is on). A prompt that misses it is written once more with
the reason; if it misses again it is kept and flagged trigger_ok: false.
"""

from dataclasses import replace
import json

from ...builder.service import GoatedPrompterService
from .debug import DebugTrace

SCENE_ORDER = ("subjects", "position", "actions", "space", "lighting", "mood", "camera", "extras")

SCENE_RULES = """DATASET SCENE (fixed)
The idea is one scene of an image-training dataset, already decided. Write it as one prompt for the
target model. Keep every person, their appearance, every placement, orientation, support, contact
and the action exactly as given; do not move anyone, change the action or add contact. Add only
wording the target format needs."""


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


def write_prompts(config, request, brief, scenes, *, checkpoint=lambda: None, progress=print, on_prompt=lambda item: None):
    """One final prompt per scene, in scene order; on_prompt gets each one as it is written.
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
        for number, scene in enumerate(scenes, 1):
            progress(f"Writing final prompt {number} of {len(scenes)}...")
            idea = scene_text(scene)
            problem = None
            for attempt in (1, 2):
                rules = "\n\n".join(part for part in (SCENE_RULES, requirements, _trigger_rule(brief),
                                                     f"CORRECTION: {problem}" if problem else "") if part)
                builder_request = replace(request, idea=idea, mode="Enhance", planning_mode="Direct",
                                          target_model=brief["settings"]["target"], prompt_length=brief["settings"]["length"],
                                          creativity=brief["settings"]["creativity"], style=brief["settings"]["style"] or "Auto",
                                          director_preset=request.director_preset, custom_instructions=rules)
                prompt = service.generate_text_only(builder_request, seed=brief["input"].get("seed")).prompt
                problem = trigger_problem(prompt, brief)
                trace.attempt(scene=number, attempt=attempt, idea=idea, rules=rules, prompt=prompt, problem=problem)
                if not problem:
                    break
            results.append({"index": number, "prompt": prompt, "trigger_ok": problem is None})
            if problem:
                trace.decide("trigger_missing", {"scene": number, "problem": problem})
            on_prompt(results[-1])
    except Exception as error:
        trace.finish(error=f"{type(error).__name__}: {error}")
        raise
    trace.finish(output=results)
    return results
