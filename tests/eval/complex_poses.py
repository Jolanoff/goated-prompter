"""Opt-in end-to-end complex-pose text evaluation; raw calls, no automatic semantic verdicts.

Uses an already running configured backend; does not edit settings or own servers.
GPU-backed runs require explicit user permission first; --allow-live is not a
substitute for permission. CPU-only offline checks do not call this evaluator.
Run: python -m tests.eval.complex_poses --config config.json --output run.json --allow-live
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset import DatasetService, default_dataset_draft
from .runner import capture

REQUESTS = (
    ("feet_behind_neck", "upper body, character with both feet behind her neck, feet visible"),
    ("knees_near_face", "waist-up, curled pose, both knees beside her face"),
    ("closeup_hands", "close-up, both hands framing her face"),
    ("foreshortened_feet", "waist-up reclining pose with feet toward the camera"),
    ("shoulder_inversion", "shoulder-supported inverted pose with legs folded around the upper body"),
    ("asymmetric_balance", "one-arm acrobatic balance with asymmetric leg positioning, one knee near shoulder and opposite leg extended"),
)


def evaluate(config, output, *, modes=("Fast", "Quality")):
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in sorted((root / "goated_prompter").rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    result = {"code_digest":digest.hexdigest(), "semantic_review":"pending explicit text review; valid JSON is not a pass",
              "records":[]}
    for mode in modes:
        for name, source in REQUESTS:
            calls, snapshots = [], []
            row = {"id":name,"mode":mode,"source":source,"calls":calls}
            data = {**default_dataset_draft(), "subject":"A character demonstrating the specified pose",
                "source_mode":"guided", "inputs":source, "amount":1, "planning_mode":mode,
                "trigger":"pose_subject", "trigger_type":"Character", "target":"Generic", "length":"Detailed"}
            start = time.perf_counter()
            try:
                final = DatasetService({**config,"_activity_callback":lambda event:capture(calls,event)},lambda:None).run(
                    GoatedPrompterRequest(idea=source), data, lambda _:None, snapshots.append)
                row.update(scene_plan=final["scene_plan"],prompts=final["prompts"],failed=final.get("failed",0))
            except Exception as exc:
                row.update(error=str(exc))
            row.update(latency_seconds=time.perf_counter()-start,snapshots=snapshots)
            result["records"].append(row)
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            print(mode,name,"prompts",len(row.get("prompts",[])),"calls",len(calls),row.get("error",""),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--allow-live",action="store_true")
    args=parser.parse_args()
    if not args.allow_live:parser.error("--allow-live is required; obtain explicit user permission before GPU use")
    config=json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("backend","mock")=="mock":parser.error("A real configured backend is required")
    evaluate(config,args.output)


if __name__=="__main__":main()
