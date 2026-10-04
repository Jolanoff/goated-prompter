"""Opt-in fixed Scene -> Writer comparison. No planning calls or downloads."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goated_prompter.backends.factory import create_backend
from goated_prompter.backends.llama_cpp_process import get_process_manager
from goated_prompter.core import GoatedPrompterRequest, PromptInstruction, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.prompting.dataset import dataset_instruction, STYLE_RULES
from goated_prompter.workflow_output import normalize_workflow_output, requested_visible_text


CASES = {
    "pottery": {
        "concept": "One recurring craftsperson practicing pottery in a ceramics workshop.",
        "idea": "Centering wet clay with both palms on a spinning pottery wheel.",
        "input": "Seat the craftsperson at the wheel, both palms touching the wet clay; show the hands and wheel.",
        "scene": "One craftsperson sits at a spinning pottery wheel in a ceramics workshop, both palms pressing the sides of a wet clay mound to center it. Feet rest on the floor; torso leans slightly toward the wheel, head and gaze follow the clay. A cotton work apron covers the lap. The clay mound and both hand contacts remain clearly visible. An eye-level front three-quarter medium-full view includes the wheel, knees and nearby workbench.",
        "geometry": {"camera_azimuth": "front_three_quarter", "framing": "medium_full", "body_orientation": "front_three_quarter", "head_direction": "toward_action", "gaze_direction": "toward_action", "pose_type": "seated", "action_focus": "centering wet clay with both palms", "face_visibility": "partial", "visibility_focus": ["hands", "clay", "wheel"]},
        "anchors": ["both palms contact clay", "centering on spinning wheel", "seated, feet supported", "workshop", "apron", "eye-level front three-quarter medium-full framing"],
    },
    "hoop": {
        "concept": "One recurring aerial performer demonstrating unusual, physically supported hoop poses.",
        "idea": "Sideways aerial suspension with a hooked knee and opposite extended leg.",
        "input": "Suspend the performer sideways, right knee hooked on the upper rim, left hand stabilizing the hoop, left leg extended diagonally downward; torso twists toward the viewer.",
        "scene": "One performer hangs sideways inside a vertical suspended steel aerial hoop in a rehearsal studio. The right knee hooks over the upper rim and bears weight; the left hand grips the side rim to stabilize the suspension. The left leg extends diagonally downward and the right arm extends outward for balance. The torso twists toward the viewer while the hips stay side-on. The performer wears a fitted green training outfit. An eye-level front three-quarter full-body view includes the entire hoop, both feet, the hooked knee contact and the stabilizing hand, with open space around the limbs.",
        "geometry": {"camera_azimuth": "front_three_quarter", "framing": "full_body", "body_orientation": "side", "torso_orientation": "front_three_quarter", "head_direction": "toward_action", "gaze_direction": "toward_action", "pose_type": "custom", "pose_detail": "right knee hooks upper rim to bear weight; left hand stabilizes side rim; left leg extends diagonally down; right arm balances; torso twists toward viewer, hips side-on", "action_focus": "sideways supported aerial suspension", "face_visibility": "partial", "visibility_focus": ["knee contact", "stabilizing hand", "feet", "hoop"]},
        "anchors": ["sideways suspension", "right knee load-bearing rim contact", "left hand stabilizing hoop", "left leg diagonally down", "right arm balance", "torso twist / side-on hips", "green training outfit", "full body and entire hoop visible"],
    },
    "counterbalance": {
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
        for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
            add("pottery", length=length)
    if "creativity" in suites:
        for creativity in ("Strict", "Balanced", "Creative", "Dice"):
            add("hoop", creativity=creativity)
    if "director" in suites:
        for director in ("general_director", "photography_director", "smartphone_realism"):
            add("pottery", director=director)
    if "sampling" in suites:
        for case in cases:
            add(case)
    return list(rows.values())


def inputs(row):
    case = CASES[row["case"]]
    data = {**default_dataset_draft(), "amount": 1, "subject": case["concept"], "target": row["target"],
            "length": row["length"], "director_preset": row["director"], "source_mode": "guided", "inputs": case["input"],
            "trigger": case.get("trigger", "ohwx_person"), "trigger_type": case.get("type", "Character"),
            "creativity": row["creativity"], "planning_mode": "Quality", "constraints": "no hat; no necklace"}
    plan = {"index": 1, "input": case["input"], "idea": case["idea"], "scene": case["scene"], "geometry": case["geometry"]}
    request = GoatedPrompterRequest(idea=case["concept"], target_model=row["target"], prompt_length=row["length"],
        director_preset=row["director"], creativity=row["creativity"], planning_mode="Direct")
    return request, data, plan


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
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--suite", action="append", choices=["parity", "length", "creativity", "director", "sampling"])
    parser.add_argument("--case", action="append", choices=list(CASES))
    parser.add_argument("--target", action="append", help="Default: Generic; repeat for target parity")
    parser.add_argument("--conditions", nargs="+", choices=["before", "builder", "dataset", "sampling"], default=["before", "builder", "dataset"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tokenizer-url", help="Explicit llama.cpp /tokenize endpoint when using an already loaded engine")
    parser.add_argument("--repeats", type=int, default=1, help="Repeated unseeded trials, alternating condition order")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats must be between 1 and 10.")
    rows = experiments(args.suite or ["parity", "length"], args.case or list(CASES), args.target or ["Generic"])
    if args.dry_run:
        print(json.dumps({"experiments": rows, "conditions": args.conditions, "planning_calls": 0}, indent=2))
        return
    if args.snapshot_only:
        if args.baseline_instructions is None:
            parser.error("--snapshot-only requires --baseline-instructions output path.")
        snapshot = {}
        for row in rows:
            request, data, plan = inputs(row)
            instruction = dataset_instruction(request, data, 1, plan_item=plan)
            snapshot[row["id"]] = {field: getattr(instruction, field) for field in FIELDS}
        args.baseline_instructions.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Froze {len(snapshot)} instructions without loading a model.")
        return
    if args.config is None:
        parser.error("Live evaluation requires --config.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("backend") in {"mock", "debug"}:
        parser.error("Live evaluation refuses mock backends.")
    baseline = json.loads(args.baseline_instructions.read_text(encoding="utf-8")) if args.baseline_instructions else {}
    if "before" in args.conditions and any(row["id"] not in baseline for row in rows):
        parser.error("Baseline snapshot does not cover all requested experiments.")
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
    try:
        with backend.generation_session() as session:
            service = DatasetService(config, lambda: None)
            for trial, row in ((trial, row) for trial in range(1, args.repeats + 1) for row in rows):
                request, data, plan = inputs(row)
                for condition in (args.conditions if trial % 2 else list(reversed(args.conditions))):
                    calls = []
                    record = {**row, "trial": trial, "condition": condition, "anchors": CASES[row["case"]]["anchors"]}
                    try:
                        if condition == "before":
                            instruction = PromptInstruction(**baseline[row["id"]])
                        elif condition == "builder":
                            source = f"{data['trigger']} represents {data['subject']}\n{plan['input']}\n{plan['idea']}\n{plan['scene']}"
                            rules = (STYLE_RULES[data["visual_style"]] + "\nInclude the exact trigger phrase " + data["trigger"]
                                + ". Do not invent stable identity traits (face, hair, body proportions or markings). "
                                "Compatible scene lighting, materials and temporary clothing detail are allowed. Apply no hat and no necklace silently.")
                            builder_request = replace(request, idea=source, custom_instructions=rules)
                            instruction = assemble_instruction(builder_request, text_only=True)
                            # Match sampling to isolate instruction ownership rather
                            # than giving the Builder a different temperature.
                            instruction = replace(instruction, temperature=.25, top_p=.85)
                        else:
                            instruction = dataset_instruction(request, data, 1, plan_item=plan)
                            if condition == "sampling":
                                instruction = replace(instruction, temperature=.45, top_p=.9)
                        record["instruction"] = {field: getattr(instruction, field) for field in FIELDS}
                        if condition == "builder":
                            raw = session.generate(instruction)
                            prompt = normalize_workflow_output(raw, data["target"], mode="Enhance", expected_visible_text=requested_visible_text(plan["input"]))
                        else:
                            prompt = service._generate(session, instruction, data, 1, lambda _message: None, plan)
                        record.update(prompt=prompt, target_valid=True, final_text_tokens=token_count(session, prompt, args.tokenizer_url),
                                      word_count=len(prompt.split()), repetition_hint=repetition_hint(prompt))
                    except Exception as exc:
                        record.update(error=str(exc), target_valid=False)
                    record["calls"] = [{**call, "generated_text_tokens": token_count(session, call["raw"], args.tokenizer_url)} for call in calls]
                    record["repair_calls"] = sum(":transport_retry" not in (call.get("stage") or "") for call in calls[1:])
                    record["truncation_hint"] = any(re.search(r"truncat|token limit|safety limit", str(call.get("error", "")), re.I) for call in calls)
                    records.append(record)
                    if args.artifacts:
                        args.artifacts.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({key: record.get(key) for key in ("id", "condition", "final_text_tokens", "repair_calls", "error")}), flush=True)
    finally:
        get_process_manager().request_unload()


if __name__ == "__main__":
    main()
