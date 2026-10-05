"""Opt-in same-engine Direct/Auto probe. Human review, not semantic guarantees."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goated_prompter.core import GoatedPrompterRequest, GoatedPrompterService
from goated_prompter.minimax import MiniMaxService
from goated_prompter.backends.llama_cpp_process import get_process_manager


CASES = [
    {"id": "hoop", "workflow": "builder", "request": "a performer suspended sideways from a hoop, one knee hooked over the top, opposite leg extended downward, torso twisted toward the viewer, no hat",
     "review": ["sideways suspension", "hooked knee/equipment contact", "opposite leg extended downward", "torso twist toward viewer", "no forbidden hat or exclusion prose"]},
    {"id": "counterbalance", "workflow": "builder", "request": 'two people counterbalancing each other, holding one hand while leaning in opposite directions. A placard reads "BALANCE".',
     "review": ["exactly two people", "single shared hand contact", "opposing lean and reciprocal balance", "literal BALANCE"]},
    {"id": "motion", "workflow": "minimax", "request": "Two dancers exchange positions while rotating around each other, then one lifts the other as the camera circles them.",
     "review": ["two dancers", "rotation/exchange precedes lift", "shared lift support", "camera circles pair", "continuous action, no unrequested cuts"]},
    {"id": "shots-dialogue", "workflow": "minimax", "request": '<shot1> 0-4s Two people hold one hand and counterbalance while leaning apart. Person A says "No, don’t stop—go!" <shot2> 4-10s They release hands and recover their balance.',
     "review": ["two shots, order and exact 0-4s/4-10s boundaries", "exact dialogue", "shared contact then release/recovery"]},
    {"id": "symbolic-motion", "workflow": "minimax", "references": ["image1", "video1"], "request": "Use only identity from <image1> and movement characteristics from <video1>. Two dancers exchange positions while rotating around each other, then one lifts the other. Place them in a plain rehearsal room. Do not use source wardrobe, source environment or source audio.",
     "review": ["identity from image; movement from video", "symbolic/unseen media, no invented observed facts", "no source wardrobe/environment/audio transfer", "rotation/exchange then lift", "requested rehearsal room"]},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--artifacts", type=Path, help="Explicitly save generated content for human review")
    parser.add_argument("--case", action="append", choices=[row["id"] for row in CASES])
    parser.add_argument("--target", default="Generic", help="Builder target; MiniMax uses its existing H3 writer")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cases = [row for row in CASES if not args.case or row["id"] in args.case]
    if args.dry_run:
        print(json.dumps({"cases": cases, "conditions": ["Direct", "Auto"],
                          "note": "Auto adds one planning pass; existing reference analysis and repairs remain."}, indent=2))
        return
    if args.config is None:
        parser.error("--config is required for opt-in real generation.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("backend") in {"mock", "debug"}:
        parser.error("Live evaluation refuses mock backends.")
    local = config.get("local_llama_cpp", {})
    records = []
    try:
        for case in cases:
            for mode in ("Direct", "Auto"):
                calls = []
                def activity(event):
                    if event.get("type") == "request":
                        calls.append({"stage": event.get("stage"), "messages": event.get("messages"), "output": ""})
                    elif event.get("type") == "response_delta" and calls:
                        calls[-1]["output"] += str(event.get("text") or "")
                request = GoatedPrompterRequest(idea=case["request"], target_model=args.target,
                    creativity="Strict", prompt_length="Medium", planning_mode=mode, prompt_model="Custom",
                    director_keep_model_loaded=True, director_llama_server=local.get("llama_server", ""),
                    director_context_size=local.get("context_size", 32768), director_model_path=local.get("model_path", ""),
                    director_mmproj_path=local.get("mmproj_path", ""))
                run_config = {**config, "_activity_callback": activity}
                record = {"id": case["id"], "workflow": case["workflow"], "mode": mode,
                          "target": args.target if case["workflow"] == "builder" else "MiniMax H3",
                          "request": case["request"], "review": case["review"]}
                try:
                    if case["workflow"] == "builder":
                        result = GoatedPrompterService(config=run_config).generate(request)
                        record.update(prompt=result.prompt, planning_status=result.planning_status)
                    else:
                        result = MiniMaxService(run_config, lambda: None).run(request,
                            {"planning_mode": mode, "user_request": case["request"], "duration_seconds": 10,
                             "references": case.get("references", [])}, lambda _message: None)
                        record.update(prompt=result["prompt"], planning_status=result["planning_status"])
                except Exception as exc:
                    record["error"] = str(exc)
                record["calls"] = calls
                records.append(record)
                if args.artifacts:
                    args.artifacts.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"id": record["id"], "mode": mode, "planning_status": record.get("planning_status"),
                    "calls": len(calls), "error": record.get("error")}), flush=True)
    finally:
        # This evaluator owns its process manager, not the app's engine settings.
        get_process_manager().request_unload()


if __name__ == "__main__":
    main()
