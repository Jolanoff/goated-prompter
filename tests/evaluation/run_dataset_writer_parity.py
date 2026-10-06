"""Opt-in fixed Scene -> Writer comparison. No planning calls or downloads."""

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goated_prompter.backends.factory import create_backend, canonical_backend_name
from goated_prompter.core import GoatedPrompterRequest, PromptInstruction, assemble_instruction
from goated_prompter.dataset import default_dataset_draft, validate_dataset_draft
from goated_prompter.prompting.dataset import dataset_instruction, dataset_scene_rules, DATASET_DESCRIPTIVE_CREATIVITY
from goated_prompter.prompting.target_models import get_model_adapter, resolve_target_length
from goated_prompter.workflow_output import normalize_workflow_output, requested_visible_text


CASES = {
    "pottery": {
        "constraints": "no hat; no necklace",
        "concept": "One recurring craftsperson practicing pottery in a ceramics workshop.",
        "idea": "Centering wet clay with both palms on a spinning pottery wheel.",
        "input": "Seat the craftsperson at the wheel, both palms touching the wet clay; show the hands and wheel.",
        "scene": "One craftsperson sits at a spinning pottery wheel in a ceramics workshop, both palms pressing the sides of a wet clay mound to center it. Feet rest on the floor; torso leans slightly toward the wheel, head and gaze follow the clay. A cotton work apron covers the lap. The clay mound and both hand contacts remain clearly visible. An eye-level front three-quarter medium-full view includes the wheel, knees and nearby workbench.",
        "geometry": {"camera_azimuth": "front_three_quarter", "framing": "medium_full", "body_orientation": "front_three_quarter", "head_direction": "toward_action", "gaze_direction": "toward_action", "pose_type": "seated", "action_focus": "centering wet clay with both palms", "face_visibility": "partial", "visibility_focus": ["hands", "clay", "wheel"]},
        "anchors": ["both palms contact clay", "centering on spinning wheel", "seated, feet supported", "workshop", "apron", "eye-level front three-quarter medium-full framing"],
    },
    "hoop": {
        "constraints": "no hat; no necklace",
        "concept": "One recurring aerial performer demonstrating unusual, physically supported hoop poses.",
        "idea": "Sideways aerial suspension with a hooked knee and opposite extended leg.",
        "input": "Suspend the performer sideways, right knee hooked on the upper rim, left hand stabilizing the hoop, left leg extended diagonally downward; torso twists toward the viewer.",
        "scene": "One performer hangs sideways inside a vertical suspended steel aerial hoop in a rehearsal studio. The right knee hooks over the upper rim and bears weight; the left hand grips the side rim to stabilize the suspension. The left leg extends diagonally downward and the right arm extends outward for balance. The torso twists toward the viewer while the hips stay side-on. The performer wears a fitted green training outfit. An eye-level front three-quarter full-body view includes the entire hoop, both feet, the hooked knee contact and the stabilizing hand, with open space around the limbs.",
        "geometry": {"camera_azimuth": "front_three_quarter", "framing": "full_body", "body_orientation": "side", "torso_orientation": "front_three_quarter", "head_direction": "toward_action", "gaze_direction": "toward_action", "pose_type": "custom", "pose_detail": "right knee hooks upper rim to bear weight; left hand stabilizes side rim; left leg extends diagonally down; right arm balances; torso twists toward viewer, hips side-on", "action_focus": "sideways supported aerial suspension", "face_visibility": "partial", "visibility_focus": ["knee contact", "stabilizing hand", "feet", "hoop"]},
        "anchors": ["sideways suspension", "right knee load-bearing rim contact", "left hand stabilizing hoop", "left leg diagonally down", "right arm balance", "torso twist / side-on hips", "green training outfit", "full body and entire hoop visible"],
    },
    "counterbalance": {
        "constraints": "no hat; no necklace",
        "concept": "Two recurring performers practicing shared-contact balance in a rehearsal studio.",
        "type": "Multiple characters", "trigger": "ohwx_person and partner",
        "idea": "A single-hand grip supplies reciprocal tension while two people lean apart.",
        "input": "Exactly two people share one hand grip and lean in opposite directions; show their feet and the contact.",
        "scene": "Two performers face each other on a clear rehearsal-studio floor. Person A's right hand grips Person B's left hand at their shared midpoint. They lean their straight torsos away from each other in opposite directions, using the taut joined arms for reciprocal counterbalance while both keep their feet grounded. Their free arms extend outward for balance. A frontal eye-level full-subject view keeps both complete figures, the single hand contact and their planted feet visible, with clear separation from the background.",
        "geometry": {"camera_azimuth": "front", "framing": "full_subject", "composition": "centered", "primary_subject_count": 2, "action_visibility": "clear", "visibility_focus": ["single hand grip", "grounded feet", "opposing lean"]},
        "anchors": ["exactly two people", "A right hand / B left hand grip", "single shared contact", "opposing lean with taut arms", "grounded feet", "free arms balance", "frontal eye-level full-subject framing"],
    },
}


def experiments(suites, cases, targets):
    rows = {}
    def add(case, target="Generic", length="Maximum Detail", creativity="Balanced", director="general_director"):
        key = "|".join((case, target, length, creativity, director))
        rows[key] = {"id": key, "case": case, "target": target, "length": length, "creativity": creativity, "director": director}
    if "parity" in suites:
        for case in cases:
            for target in targets:
                for length in ("Detailed", "Maximum Detail"):
                    add(case, target, length)
    if "length" in suites:
        for target in targets:
            for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
                add(cases[0], target=target, length=length)
    if "creativity" in suites:
        for target in targets:
            for creativity in ("Strict", "Balanced", "Creative", "Dice"):
                add(cases[-1], target=target, creativity=creativity)
    if "director" in suites:
        for target in targets:
            for director in ("general_director", "photography_director", "smartphone_realism"):
                add(cases[0], target=target, director=director)
    if "sampling" in suites:
        for case in cases:
            for target in targets:
                add(case, target=target)
    return list(rows.values())


def inputs(row, *, cases=None):
    case = (CASES if cases is None else cases)[row["case"]]
    if case.get("evaluation_blocked"):
        raise ValueError(f"Case {row['case']} is blocked: {case['evaluation_blocked']}")
    data = {**default_dataset_draft(), "amount": 1, "subject": case["concept"], "target": row["target"],
            "length": row["length"], "director_preset": row["director"], "source_mode": "guided", "inputs": case["input"],
            "trigger": case.get("trigger", "ohwx_person"), "trigger_type": case.get("type", "Character"),
            "creativity": row["creativity"], "planning_mode": "Quality",
            "custom_type": case.get("custom_type", ""),
            "visual_style": case.get("visual_style", "Photorealistic"), "custom_style": case.get("custom_style", ""),
            "constraints": case.get("constraints", ""),
            **{key: case[key] for key in ("trigger_connected", "trigger_at_start", "expand_trigger") if key in case}}
    data = validate_dataset_draft(data)
    plan = {"index": 1, "input": case["input"], "idea": case["idea"], "scene": case["scene"], "geometry": deepcopy(case["geometry"])}
    request = GoatedPrompterRequest(idea=case["concept"], target_model=row["target"], prompt_length=row["length"],
        director_preset=row["director"], creativity=row["creativity"], planning_mode="Direct")
    return request, data, plan


def load_accepted_cases(path):
    """Read benchmark-owned accepted scenes; never generate or semantically approve them."""
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Accepted-scene file exceeds its one-megabyte limit.")
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 25:
        raise ValueError("Supply one to 25 explicitly accepted benchmark scenes.")
    cases = {}
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                for key in ("id", "accepted_by", "concept", "idea", "scene", "trigger")):
            raise ValueError("Each case needs id, accepted_by, concept, idea, scene and trigger text.")
        if row["id"] in cases:
            raise ValueError("Accepted-scene IDs must be unique.")
        anchors = row.get("anchors")
        if not isinstance(anchors, list) or not anchors or any(not isinstance(anchor, str) or not anchor.strip() for anchor in anchors):
            raise ValueError("Each case needs explicit benchmark-only fidelity anchors.")
        if not isinstance(row.get("input", ""), str) or not isinstance(row.get("geometry", {}), dict):
            raise ValueError("Accepted input must be text and geometry must be an object.")
        cases[row["id"]] = {"type": "Custom", "custom_type": "general image concept",
                            "visual_style": "Keep described style", **row,
                            "input": row.get("input", ""), "geometry": row.get("geometry", {})}
    return cases


def baseline_dataset_writer(ref):
    """Load the historical writer with unchanged shared dependencies, without checkout edits."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], cwd=ROOT,
        text=True, encoding="utf-8").strip()
    source = subprocess.check_output(
        ["git", "show", f"{commit}:goated_prompter/prompting/dataset.py"], cwd=ROOT,
        text=True, encoding="utf-8")
    namespace = {"__name__": "goated_prompter.prompting._baseline_dataset",
                 "__package__": "goated_prompter.prompting"}
    exec(compile(source, f"{commit}:goated_prompter/prompting/dataset.py", "exec"), namespace)
    return namespace["dataset_instruction"], commit


def comparison_instructions(request, data, plan, *, before=None):
    """Match accepted context and controls, not Builder's production invention defaults."""
    writer = dataset_instruction(request, data, plan["index"], plan_item=plan)
    locks = dataset_scene_rules(data)
    builder_request = replace(request, idea=writer.user_message, custom_instructions=locks,
        mode="Enhance", target_model=data["target"], prompt_length=data["length"],
        creativity=data.get("creativity", "Balanced"), director_preset=data["director_preset"],
        system_prompt_override="", planning_mode="Direct")
    builder = assemble_instruction(builder_request, model_family=writer.model_family,
                                   text_only=True, compile_user_constraints=False)
    controls = ("max_tokens", "hard_max_tokens", "unlimited_tokens", "temperature", "top_p")
    builder = replace(builder, **{field: getattr(writer, field) for field in controls},
                      diagnostic_stage="benchmark:builder:final")
    instructions = {"builder": builder, "dataset": writer}
    if before is not None:
        if before.user_message != writer.user_message:
            raise ValueError("Frozen baseline must contain the same accepted scene and complete context.")
        if any(getattr(before, field) != getattr(writer, field) for field in (*controls, "director_preset", "model_family")):
            raise ValueError("Frozen baseline must have matched writer controls.")
        required_rules = [*locks.splitlines(), get_model_adapter(data["target"]),
                          resolve_target_length(data["target"], data["length"]),
                          DATASET_DESCRIPTIVE_CREATIVITY[data.get("creativity", "Balanced")]]
        if any(rule not in before.system_message for rule in required_rules):
            raise ValueError("Frozen baseline must have matched scene, style, target and length rules.")
        instructions["before"] = before
    return instructions


FIELDS = ("system_message", "user_message", "model_family", "director_preset", "diagnostic_stage",
          "max_tokens", "hard_max_tokens", "unlimited_tokens", "temperature", "top_p")


def token_count(session, text, tokenizer_url=None):
    if tokenizer_url is None and not getattr(session, "is_llama_cpp", False):
        return None
    url = tokenizer_url or session.url.removesuffix("/v1/chat/completions") + "/tokenize"
    request = urllib.request.Request(url, data=json.dumps({"content": text, "add_special": False}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return len(json.load(response)["tokens"])
    except (OSError, ValueError, KeyError):
        return None


def repetition_hint(text):
    words = re.findall(r"\w+", text.casefold())
    chunks = [tuple(words[i:i + 6]) for i in range(max(0, len(words) - 5))]
    return round(1 - len(set(chunks)) / max(1, len(chunks)), 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--artifacts", type=Path, help="Explicit content-bearing output; checkpoints are not changed")
    parser.add_argument("--baseline-instructions", type=Path, help="Frozen pre-change instruction snapshot")
    parser.add_argument("--accepted-scenes", type=Path,
        help="JSON array: id, accepted_by, concept, idea, scene, trigger, anchors; optional input, geometry and Dataset style/trigger rules")
    parser.add_argument("--allow-live", action="store_true", help="Requires prior inference/resource approval")
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--baseline-ref", help="Historical local Git commit for snapshot-only; shared dependencies remain current")
    parser.add_argument("--suite", action="append", choices=["parity", "length", "creativity", "director", "sampling"])
    parser.add_argument("--case", action="append", help="Case ID from accepted-scenes; built-in scenes are unreviewed controls")
    parser.add_argument("--target", action="append", help="Default: Anima; repeat for target parity")
    parser.add_argument("--conditions", nargs="+", choices=["before", "builder", "dataset", "sampling"], default=["before", "builder", "dataset"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tokenizer-url", help="Explicit llama.cpp /tokenize endpoint when using an already loaded engine")
    parser.add_argument("--repeats", type=int, default=1, help="Repeated unseeded trials, alternating condition order")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10.")
    if len(set(args.conditions)) != len(args.conditions):
        parser.error("Comparison conditions must be unique.")
    try:
        cases = load_accepted_cases(args.accepted_scenes) if args.accepted_scenes else CASES
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    selected = args.case or [key for key, case in cases.items() if not case.get("evaluation_blocked")]
    if any(case not in cases for case in selected):
        parser.error("Requested case is absent from the selected scene file.")
    if not selected or any(cases[key].get("evaluation_blocked") for key in selected):
        parser.error("No runnable scenes selected, or a selected scene has an evaluation blocker.")
    if args.baseline_ref and not args.snapshot_only:
        parser.error("--baseline-ref is only permitted with --snapshot-only.")
    rows = experiments(args.suite or ["parity"], selected, args.target or ["Anima"])
    if args.dry_run:
        print(json.dumps({"experiments": rows, "conditions": args.conditions, "planning_calls": 0,
                          "initial_writer_calls": len(rows) * len(args.conditions) * args.repeats,
                          "accepted_scenes": bool(args.accepted_scenes), "comparison_phase": "first_pass",
                          "blocked_cases": {key: case["evaluation_blocked"] for key, case in cases.items()
                                            if case.get("evaluation_blocked")}}, indent=2))
        return
    if args.snapshot_only:
        if args.baseline_instructions is None:
            parser.error("--snapshot-only requires --baseline-instructions output path.")
        snapshot = {}
        writer = dataset_instruction
        if args.baseline_ref:
            try:
                writer, commit = baseline_dataset_writer(args.baseline_ref)
            except subprocess.CalledProcessError:
                parser.error("Cannot load the requested historical local writer.")
            print(f"Historical writer: {commit}; shared dependencies from current worktree.")
        for row in rows:
            request, data, plan = inputs(row, cases=cases)
            instruction = writer(request, data, 1, plan_item=plan)
            snapshot[row["id"]] = {field: getattr(instruction, field) for field in FIELDS}
        try:
            with args.baseline_instructions.open("x", encoding="utf-8") as output:
                output.write(json.dumps(snapshot, ensure_ascii=False, indent=2))
        except FileExistsError:
            parser.error("Refusing to overwrite frozen baseline instructions. Choose a new snapshot path.")
        print(f"Froze {len(snapshot)} instructions without loading a model.")
        return
    if args.config is None:
        parser.error("Live evaluation requires --config.")
    if not args.allow_live or not args.accepted_scenes:
        parser.error("Live evaluation requires --allow-live and --accepted-scenes; planning is never run here.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if canonical_backend_name(config.get("backend")) != "openai_compatible":
        parser.error("Live evaluation requires an already running OpenAI-compatible endpoint; it never manages model processes.")
    baseline = json.loads(args.baseline_instructions.read_text(encoding="utf-8")) if args.baseline_instructions else {}
    if "before" in args.conditions and any(row["id"] not in baseline for row in rows):
        parser.error("Baseline snapshot does not cover all requested experiments.")
    prepared = []
    try:
        for row in rows:
            request, data, plan = inputs(row, cases=cases)
            before = PromptInstruction(**baseline[row["id"]]) if "before" in args.conditions else None
            instructions = comparison_instructions(request, data, plan, before=before)
            instructions["sampling"] = replace(instructions["dataset"], temperature=.45, top_p=.9)
            prepared.append((row, data, plan, instructions))
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    records, calls = [], []
    def activity(event):
        if event.get("type") == "request":
            calls.append({"stage": event.get("stage"), "parameters": event.get("parameters"), "raw": "", "finish_reason": None})
        elif event.get("type") == "response_delta" and calls:
            calls[-1]["raw"] += str(event.get("text") or "")
        elif event.get("type") == "response_complete" and calls:
            calls[-1]["finish_reason"] = event.get("finish_reason")
        elif event.get("type") == "error" and calls:
            calls[-1]["error"] = event.get("message")
    backend = create_backend({**config, "_activity_callback": activity})
    with backend.generation_session() as session:
        for trial, (row, data, plan, instructions) in ((trial, prepared_row)
                for trial in range(1, args.repeats + 1) for prepared_row in prepared):
            for condition in (args.conditions if trial % 2 else list(reversed(args.conditions))):
                calls = []
                case = cases[row["case"]]
                record = {**row, "trial": trial, "condition": condition, "anchors": case["anchors"],
                          "accepted_by": case["accepted_by"], "comparison_phase": "first_pass",
                          "visual_style": data["visual_style"], "custom_style": data["custom_style"],
                          "controls_matched": condition != "sampling"}
                instruction = instructions[condition]
                context = {"source": instruction.user_message, "locks": dataset_scene_rules(data),
                           "settings": {key: row[key] for key in ("target", "length", "creativity", "director")}}
                record["context_id"] = hashlib.sha256(json.dumps(context, sort_keys=True).encode("utf-8")).hexdigest()
                record["instruction"] = {field: getattr(instruction, field) for field in FIELDS}
                started = time.monotonic()
                try:
                    session.validate_instruction(instruction)
                    raw = session.generate(instruction)
                    expected_text = requested_visible_text("\n".join((data["subject"], data["constraints"], plan["input"])))
                    prompt = normalize_workflow_output(raw, data["target"], mode="Enhance", expected_visible_text=expected_text)
                    record.update(prompt=prompt, target_valid=True, word_count=len(prompt.split()), repetition_hint=repetition_hint(prompt))
                except Exception as exc:
                    record.update(error=str(exc), target_valid=False)
                record["latency_seconds"] = time.monotonic() - started
                record["final_text_tokens"] = token_count(session, record["prompt"], args.tokenizer_url) if "prompt" in record else None
                record["calls"] = [{**call, "generated_text_tokens": token_count(session, call["raw"], args.tokenizer_url)} for call in calls]
                record["repair_calls"] = sum(":transport_retry" not in (call.get("stage") or "") for call in calls[1:])
                record["truncation_hint"] = any(re.search(r"truncat|token limit|safety limit", str(call.get("error", "")), re.I) for call in calls)
                records.append(record)
                if args.artifacts:
                    args.artifacts.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({key: record.get(key) for key in ("id", "condition", "final_text_tokens", "repair_calls", "error")}), flush=True)
                if "Could not reach the OpenAI-compatible backend" in str(record.get("error", "")):
                    print("Stopped comparison: the engine endpoint is no longer reachable; retained prior results.", flush=True)
                    return


if __name__ == "__main__":
    main()
