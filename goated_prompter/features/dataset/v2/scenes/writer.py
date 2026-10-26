"""Composing one batch: asking again for the images still missing."""

import json
import re

from .....backends.recovery import GenerationRecovery, RunawayRecoveryError

from .checks import (_summary, framed_to_camera, framing_problems, retire_fields, scene_errors, unnamed_people,
                     without_copied_props, without_entry_copy)
from .entries import _entry_key
from .request import _labels, compose_instruction, subject_fields
from .settings import ROUNDS, SECTIONS


def _parse(raw):
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(raw or ""))
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {"scenes"} or not isinstance(value["scenes"], list):
        raise ValueError('the answer must be {"scenes": [...]}')
    return value["scenes"]


def rejected_note(number, reason, scene):
    """One log line saying why an image is asked again and what its answer's actions said, so a run's log shows what
    the writer wrote instead (the run's output never changes)."""
    actions = " ".join(str(scene.get("actions") or "").split()) if isinstance(scene, dict) else ""
    said = f' Its actions were: "{actions[:300]}{"..." if len(actions) > 300 else ""}"' if actions else ""
    return f"Image {number} is asked again: {reason}.{said}"


def _compose(session, brief, numbers, plan, inputs, earlier, checkpoint, progress, on_slot):
    """Compose one batch, asking again for the images still missing: ({number: scene}, {number: failure}).
    plan: {"vocabulary": section, "entries": {key: entry} or None, "cap", "used": {entry: images}, "dealt": {slot: entry}}."""
    labels, avoid = _labels(brief), brief["_avoid"]
    people_fields = subject_fields(brief, None)  # everyone who is not a known character
    entries, cap, used = plan["entries"], plan["cap"], plan["used"]
    extra = ("entry",) if entries else ()
    scenes, reasons, tries = {}, {number: [] for number in numbers}, {number: 0 for number in numbers}
    failed = {}
    recovery = GenerationRecovery("dataset_v2:scenes", numbers, progress=progress)
    for round_ in range(1, ROUNDS + 1):
        todo = [number for number in numbers if number not in scenes and number not in failed]
        if not todo or recovery.exhausted:
            break
        recovery.items = tuple(todo)
        progress(f"Composing scene{'s' if len(todo) > 1 else ''} {', '.join(map(str, todo))}"
                 + (" again: " + "; ".join(f"{number}: {reasons[number][0][:70]}" for number in todo if reasons[number])
                    if round_ > 1 else "") + "...")
        images = [{"image": number, **({"input": inputs[number]} if inputs[number] else {}),
                   **({"entry": plan["dealt"][number]} if plan.get("dealt") else {}),
                   **({"frame": plan["frames"][number]} if plan.get("frames") else {}),
                   **({"suggested": plan["hands"][number]} if (plan.get("hands") or {}).get(number) else {})}
                  for number in todo]
        errors = sorted({f"image {number}: {reason}" for number in todo for reason in reasons[number]})
        prompt = compose_instruction(brief, images, earlier + [_summary(scenes[n]) for n in sorted(scenes)], errors,
                                     plan["vocabulary"], cap if entries else None, used if entries else None)
        checkpoint()
        before = recovery.attempts
        try:
            raw = recovery.generate(session, prompt, checkpoint)
            answer, error = _parse(raw), None
        except RunawayRecoveryError as exc:
            raw, answer, error = "", None, str(exc)
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            answer, error = None, f"Return one valid JSON object ({exc})."
        checkpoint()
        for number, scene in zip(todo, (answer or []) + [None] * len(todo)):
            scene = retire_fields(scene)
            tries[number] += max(1, recovery.attempts - before)
            problems = ([error] if error else ["an answer was missing"] if scene is None
                        else scene_errors(scene, labels, avoid, extra, brief["_known"], people_fields))
            entry = entries.get(_entry_key(scene["entry"])) if entries and not problems else None
            # Only a scene that would ruin the image is asked again; repeating an earlier image, its place, camera,
            # entry or frame never is (a live run asked seven images again for the place and camera the request keeps;
            # asking copies again cost a third more time, still came back as copies and lost part of the act). Variety
            # is the prompt's and the vocabulary's job. The last round keeps what it gets rather than lose the image.
            if not problems and round_ < ROUNDS:
                if framing := framing_problems(scene, brief["_known"]):
                    problems = framing
                elif missing := unnamed_people(scene, labels):
                    problems = [f"its actions do not name {', '.join(missing)}: name every person by their character "
                                "label and never leave a placeholder person from an entry"]
                elif entries and entry is None:
                    problems = ['its "entry" must be copied word for word from the Actions & Poses vocabulary']
            if problems:
                reasons[number] = problems
                progress(rejected_note(number, problems[0], scene))
                continue
            scene = framed_to_camera(without_entry_copy(scene, labels))
            suggested = [entry for hand in ((plan.get("hands") or {}).get(number) or {}).values() for entry in hand]
            scene = without_copied_props(scene, plan.get("props") or (), suggested,
                                         [item["extras"] for item in earlier] + [item["extras"] for item in scenes.values()])
            finished = {"slot": number, **{key: scene[key] for key in SECTIONS}}
            if brief["_known"]:
                finished["frame"] = scene["frame"]
            if not labels:
                finished["position"] = {}
            if entries:
                finished["entry"] = entry or " ".join(scene["entry"].split())
                used[finished["entry"]] = used.get(finished["entry"], 0) + 1
            scenes[number] = finished
            on_slot("description", number, finished)
    recovery.finish("succeeded" if len(scenes) == len(numbers) else "failed")
    for number in numbers:
        if number not in scenes and number not in failed:
            failed[number] = {"tries": tries[number], "reasons": reasons[number] or ["no usable scene was written"]}
    return scenes, failed
