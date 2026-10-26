"""Runs Understanding alone on requests of every kind of cast (one person, several, animals, known characters, none)
and prints what it gives for each: the path, the characters and the subject and object words it quoted, with the
model's raw answer. Runs the generation model once per request (one Understanding call each, as in the app):

  python -m tests.eval.understanding_cast --settings <quality settings file> [--output <json>]
"""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from tests.quality.worker import _engine, _request

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).parent / "cases" / "understanding_cast.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--settings", required=True, help="a quality settings file (its model_config and model_profile)")
    parser.add_argument("--output")
    parser.add_argument("--seed", type=int, default=173)
    args = parser.parse_args()
    from goated_prompter.backends.llama_cpp_process import get_process_manager
    from goated_prompter.features.dataset.v2 import understanding
    from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
    config, profile = _engine(json.loads(Path(args.settings).read_text(encoding="utf-8")), ROOT)
    config["local_llama_cpp"] = {**config.get("local_llama_cpp", {}), "keep_model_loaded": True}
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    rows, answers, parse = [], [], understanding.parse
    try:
        with patch.object(understanding, "parse", lambda raw: answers.append(raw) or parse(raw)):
            for case in cases:
                answers.clear()
                data = validate_dataset_draft({**default_dataset_draft(), "subject": case["request"], "amount": 3,
                                               "nsfw": False, "seed": args.seed, "seed_mode": "fixed"}, generation=True)
                request = _request(profile, config, idea=data["subject"], mode="Custom", target_model=data["target"],
                                   creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
                                   director_preset="general_director")
                brief = understanding.understand(config, request, data, progress=lambda _: None)
                cast = [(person["label"], person["gender"], person["known"], person.get("appearance", ""))
                        for person in brief["characters"]]
                ok = (brief["path"] != "non_character") == case["cast"] and len(cast) == case.get("people", len(cast))
                rows.append({"request": case["request"], "ok": ok, "path": brief["path"], "characters": cast,
                             "kept": brief["kept_words"], "calls": len(answers), "raw": answers[:]})
                print(f'{"ok " if ok else "BAD"} {case["request"][:44]:44} {brief["path"]:14} {cast} '
                      f'calls={len(answers)} subject={brief["kept_words"].get("subject", "")!r}', flush=True)
    finally:
        get_process_manager().cleanup_all()
    print(f"{sum(row['ok'] for row in rows)}/{len(rows)} as expected")
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
