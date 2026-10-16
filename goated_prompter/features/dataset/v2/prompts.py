"""Section 3 — Prompts: each written scene becomes one final prompt through the Builder.

The scene is fixed: the Builder writes it in the target model's format, style and length with the
selected Director, and may not move anyone, change the action or add contact. Builder's own target
formatting and clean-up apply unchanged (Dataset delegates final writing to the Builder).

A scene Core composed from the vocabulary (vocabulary/composer.py) also carries its established facts: the entries,
who takes which role, posture, facing, declared contact, busy body parts, the place and items. They are added to the
idea as "arrangement" lines with one more rule to keep them; the Director and the target model still decide the
wording, emphasis and format. A freeform scene gets neither, so nothing unchecked is presented as checked.

Code checks the user's exact trigger and the composed scene's locked clauses. A prompt
that drops either is retried once, then marked failed. Other model prose is not semantically validated.
"""

from dataclasses import replace
import json

from ...builder.service import GoatedPrompterService, PromptValidationError
from ....backends.recovery import GenerationRecovery, RunawayRecoveryError
from .debug import DebugTrace

SCENE_ORDER = ("subjects", "position", "actions", "space", "lighting", "mood", "camera", "extras")

SCENE_RULES = """
The idea is one scene of an IMAGE, already decided. Write it as one prompt for the
target model. Keep every person, their appearance, every placement, orientation, support, contact
and the action exactly as given; do not move anyone, change the action or add contact. Add only
wording the target format needs."""


ESTABLISHED_RULES = """
ESTABLISHED SCENE FACTS: the arrangement lines were composed from vocabulary before the scene
was written. Keep who takes which role, each person's posture and facing, and where they are relative to each
other exactly as listed. The locked clauses below must occur verbatim in the final prompt; target-specific
formatting and creative wording may surround them but must not replace them. Unknown is not validated."""


def established(scene):
    """A vocabulary-checked arrangement of the scene, or None (freeform scenes and scenes from before arrangements)."""
    arrangement = scene.get("arrangement")
    return arrangement if isinstance(arrangement, dict) and arrangement.get("kind") == "vocabulary" else None


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
    arrangement = established(scene)
    if arrangement:
        for entry in arrangement["entries"]:
            roles = "; ".join(f"{role}: {', '.join(who)}" for role, who in entry["roles"].items())
            lines.append(f"arrangement: {entry['name']} ({roles})")
        lines.extend(f"arrangement fact: {fact}" for fact in arrangement["facts"])
        if arrangement.get("space"):
            lines.append(f"arrangement place: {arrangement['space']['name']}")
        lines.extend(f"arrangement item: {item['name']}" for item in arrangement.get("items", []))
    return "\n".join(lines)


def locked_clauses(scene):
    """Code-owned mechanics may not be lost in a target adapter's rewrite."""
    arrangement = established(scene)
    if not arrangement:
        return []
    relationships = [f"{a} {row['relation'].replace('_', ' ')} {b}"
                     for row in arrangement.get("contract", {}).get("relationships", []) for a in row["a"] for b in row["b"]]
    return list(dict.fromkeys([scene["actions"], *arrangement["facts"],
                              *relationships,
                              *arrangement.get("visual", {}).values(),
                              *([arrangement["space"]["name"]] if arrangement.get("space") else []),
                              *(item["name"] for item in arrangement.get("items", []))]))


def mechanics_problem(prompt, scene):
    missing = [clause for clause in locked_clauses(scene) if clause not in prompt]
    return "Preserve these locked scene clauses verbatim: " + " | ".join(missing) if missing else None


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
                rules = "\n\n".join(part for part in (SCENE_RULES, ESTABLISHED_RULES if established(scene) else "",
                                                      "LOCKED SCENE CLAUSES\n" + "\n".join(locked_clauses(scene)) if established(scene) else "",
                                                     requirements, _trigger_rule(brief),
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
                    results.append({"slot": number, "index": number, "prompt": "", "trigger_ok": False,
                                    "mechanics_preserved": False, "error": str(error),
                                    "stage": "dataset_v2:builder", "attempts": error.attempts})
                    trace.decide("prompt_failed", results[-1])
                    on_prompt(results[-1])
                    break
                trigger_error = trigger_problem(prompt, brief)
                problem = trigger_error or mechanics_problem(prompt, scene)
                trace.attempt(scene=number, attempt=attempt, idea=idea, rules=rules, prompt=prompt, problem=problem)
                if not problem:
                    break
            if results and results[-1]["slot"] == number:
                continue
            recovery.finish("succeeded" if not problem else "failed")
            results.append({"slot": number, "index": number, "prompt": "" if problem else prompt,
                            "trigger_ok": trigger_problem(prompt, brief) is None,
                            "mechanics_preserved": mechanics_problem(prompt, scene) is None})
            if problem:
                results[-1].update(error=problem, stage="dataset_v2:builder", attempts=recovery.attempts)
                trace.decide("prompt_rejected", {"scene": number, "problem": problem})
            on_prompt(results[-1])
    except Exception as error:
        trace.finish(error=f"{type(error).__name__}: {error}")
        raise
    trace.finish(output=results)
    return results
