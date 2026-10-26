"""Captures Understanding's place facts (setting, world, ideas) for the places evaluation's unnamed requests, so the
places selection can be compared offline on the ideas the real Understanding gives (tests/eval/places.py --ideas).
Runs the generation model once per request (one Understanding call each, as in the app):

  python -m tests.eval.capture_ideas --settings quality-artifacts/tasks/dataset-workflow/quality-places.json
      --output quality-artifacts/places-eval/ideas.json
"""

import argparse
import json
from pathlib import Path

from tests.quality.worker import _engine, _request

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--settings", required=True, help="a quality settings file (its model_config and model_profile)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=173)
    args = parser.parse_args()
    from goated_prompter.backends.llama_cpp_process import get_process_manager
    from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
    from goated_prompter.features.dataset.v2.understanding import understand
    config, profile = _engine(json.loads(Path(args.settings).read_text(encoding="utf-8")), ROOT)
    config["local_llama_cpp"] = {**config.get("local_llama_cpp", {}), "keep_model_loaded": True}
    cases = [case for name in ("places.json", "places_heldout.json")
             for case in json.loads((CASES / name).read_text(encoding="utf-8"))["free"]]
    captured = {}
    try:
        for case in cases:
            data = validate_dataset_draft({**default_dataset_draft(), "subject": case["request"], "amount": 10,
                                           "nsfw": case.get("path") == "nsfw_character", "seed": args.seed,
                                           "seed_mode": "fixed"}, generation=True)
            request = _request(profile, config, idea=data["subject"], mode="Custom", target_model=data["target"],
                               creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
                               director_preset="general_director")
            brief = understand(config, request, data, progress=lambda _: None)
            captured[case["request"]] = {**brief["places"], "kept_place": brief["kept_words"].get("place", ""),
                                         "kept": brief["kept_words"]}
            print(f"{case['request'][:40]:40} {captured[case['request']]}", flush=True)
    finally:
        get_process_manager().cleanup_all()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(captured, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
