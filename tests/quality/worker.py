"""One side of a quality run, run in its own process against one copy of the app's code.

    python worker.py audit --code-root DIR --out FILE
    python worker.py live  --code-root DIR --out FILE --settings FILE --main-root DIR
    python worker.py judge --code-root DIR --out FILE --settings FILE --main-root DIR --packet FILE

The code root goes first on the import path, so the same worker reads the old commit and the new one. "audit" reads
every guide's text and the instructions the app assembles for a set of settings; it never runs a model and never
reads the private data folder. "live" runs each case through the app's real pipeline with the user's model. "judge"
asks a model to compare blind pairs (only when the settings choose an LLM judge).
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

IDEA = "two friends talk on a bench"


def _owners(gp):
    """{owner: {name: text}} for every guide the app has, read from the code itself."""
    from goated_prompter.prompting import base, creativity, details, directors, modes, styles, target_models
    from goated_prompter.options.targets import TARGET_MODEL_NAMES
    owners = {
        "core": {"system": base.CORE_SYSTEM_PROMPT},
        "priority": {name: getattr(base, name) for name in ("PRIORITY_CONTRACT", "LINKED_PRIORITY_CONTRACT",
                                                             "TEXT_ONLY_PRIORITY_CONTRACT") if hasattr(base, name)},
        "mode": dict(modes.MODE_ADAPTERS),
        "vision": {**modes.VISION_MODE_ADAPTERS, "default": modes.DEFAULT_VISION_ADAPTER},
        "target": {name: target_models.get_model_adapter(name) for name in TARGET_MODEL_NAMES},
        "target_envelope": {name: target_models.get_target_capabilities(name).detail_envelope for name in TARGET_MODEL_NAMES},
        "length": {name: text for name, text in details.LENGTH_ADAPTERS.items() if name != "Maximum"},
        "preserve": dict(details.PRESERVATION_ADAPTERS),
        "creativity": dict(creativity.CREATIVITY_ADAPTERS),
        "director": {preset.label: preset.instructions for preset in directors.DIRECTOR_PRESETS},
        "style": {**styles.STYLE_ADAPTERS, **{f"capture {name}": text for name, text in styles.CAPTURE_ADAPTERS.items()}},
    }
    try:
        from goated_prompter.prompting import output
        owners["output"] = {"contract": output.OUTPUT_CONTRACT,
                            **{name: output.output_contract(name) for name in TARGET_MODEL_NAMES}}
    except Exception:  # an older or newer layout: report what exists
        pass
    for owner, module, names in (
            ("planner", "goated_prompter.planning.scene_planner", ("AUTHORITY",)),
            ("repair", "goated_prompter.planning.semantic_validation", ("AUDIT_CONTRACT",)),
            ("dataset_understanding", "goated_prompter.features.dataset.v2.understanding", ("SYSTEM",)),
            ("dataset_scenes", "goated_prompter.features.dataset.v2.scenes",
             ("COMPOSE_SYSTEM", "VOCABULARY_RULES", "NO_PEOPLE_RULE", "GUIDED_RULE", "ENTRY_RULE", "ENTRY_FIT_SYSTEM")),
            ("dataset_prompts", "goated_prompter.features.dataset.v2.prompts", ("SCENE_RULES", "KNOWN_RULE")),
            ("nsfw", "goated_prompter.features.dataset.v2.scenes", ("NSFW_RULE", "SFW_RULE")),
            ("nsfw", "goated_prompter.features.dataset.v2.prompts", ("ADULT_RULE",))):
        try:
            loaded = __import__(module, fromlist=["_"])
        except Exception:
            continue
        for name in names:
            if isinstance(getattr(loaded, name, None), str):
                owners.setdefault(owner, {})[name] = getattr(loaded, name)
    return owners


def _assembled():
    """The full instructions the Builder sends for one changed setting at a time (the rest at their defaults)."""
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.features.builder.service import assemble_instruction
    from goated_prompter.options.creativity import CREATIVITY_NAMES
    from goated_prompter.options.lengths import PROMPT_LENGTH_NAMES
    from goated_prompter.options.styles import STYLE_NAMES
    from goated_prompter.options.targets import TARGET_MODEL_NAMES
    from goated_prompter.prompting.directors import DIRECTOR_PRESETS
    from goated_prompter.prompting.modes import MODE_ADAPTERS
    combos = {"default": {}}
    combos.update({f"target {name}": {"target_model": name} for name in TARGET_MODEL_NAMES})
    combos.update({f"director {preset.label}": {"director_preset": preset.id} for preset in DIRECTOR_PRESETS})
    combos.update({f"creativity {name}": {"creativity": name} for name in CREATIVITY_NAMES})
    combos.update({f"length {name}": {"prompt_length": name} for name in PROMPT_LENGTH_NAMES})
    combos.update({f"style {name}": {"style": name} for name in STYLE_NAMES})
    combos.update({f"mode {name}": {"mode": name} for name in MODE_ADAPTERS if name not in ("Image Edit", "Style Transfer")})
    result = {}
    combos.pop("mode Remix", None)  # Remix needs saved prompts, which the audit never reads
    for name, fields in combos.items():
        try:
            result[name] = assemble_instruction(GoatedPrompterRequest(idea=IDEA, **fields)).system_message
        except Exception as error:  # a setting the code does not accept is reported, not fatal
            result[name] = f"ERROR: {error}"
    return result


def _block_private_reads(roots):
    """Audit only: the guides never need the private data folder, so reading it is an error."""
    blocked = [Path(root, "data").resolve() for root in roots]

    def hook(event, args):
        if event in {"open", "os.listdir", "os.scandir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if any(path == root or root in path.parents for root in blocked):
                raise PermissionError("The quality audit never reads the private data folder.")
    sys.addaudithook(hook)


def audit(args):
    with tempfile.TemporaryDirectory(prefix="quality-audit-") as empty:
        # No Prompt Library, no custom Directors: the audit reads only what the code itself says.
        os.environ["GOATED_PROMPTER_LIBRARY_DIR"] = str(Path(empty) / "library")
        os.environ["GOATED_PROMPTER_USER_DIR"] = str(Path(empty) / "directors")
        _block_private_reads([args.code_root, args.main_root or args.code_root])
        import goated_prompter as gp
        return {"owners": _owners(gp), "assembled": _assembled()}


def _engine(settings, main_root):
    """The app's config and model choice, read the way the app reads them."""
    from goated_prompter.config import load_config
    config = load_config(main_root / settings["model_config"])
    if not config:
        raise SystemExit(f"Model config not found: {settings['model_config']}")
    profile = ""
    app_settings = main_root / settings["app_settings"] if settings.get("app_settings") else None
    if app_settings and app_settings.is_file():
        saved = json.loads(app_settings.read_text(encoding="utf-8"))
        local = dict(config.get("local_llama_cpp") or {})
        if "models_directory" in saved:
            local["models_dir"] = local["discovery_root"] = saved["models_directory"]
        if "keep_model_loaded" in saved:
            local["keep_model_loaded"] = saved["keep_model_loaded"]
        config["local_llama_cpp"] = local
        profile = str(saved.get("selected_profile") or "")
    if config.get("backend") in ("mock", "openai_compatible"):
        return config, ""
    # Like the app: the model chosen in quality.json, else the one selected in the app, else the first ready one.
    from goated_prompter.director_profiles import discover_director_profiles
    ready = [item for item in discover_director_profiles(dict(config.get("local_llama_cpp") or {})).profiles
             if item.vision_ready]
    wanted = str(settings.get("model_profile") or profile or "").strip().casefold()
    chosen = next((item for item in ready if wanted in (item.profile_id.casefold(), item.label.casefold())), None) \
        or (ready[0] if ready else None)
    if chosen is None:
        raise SystemExit("No ready model found (a model and its mmproj in the models folder). Check the app's Models "
                         "folder setting, or set model_profile in quality.json.")
    print(f"Model: {chosen.label}", flush=True)
    return config, chosen.profile_id


def _request(profile, config, **fields):
    from goated_prompter.contracts import GoatedPrompterRequest
    keep = bool((config.get("local_llama_cpp") or {}).get("keep_model_loaded", False))
    return GoatedPrompterRequest(prompt_model="Custom", director_profile=profile, director_keep_model_loaded=keep, **fields)


def _builder_case(case, seed, config, profile, log):
    from goated_prompter.features.builder.service import GoatedPrompterService
    request = _request(profile, config, idea=case["idea"], mode=case.get("mode", "Enhance"),
                       target_model=case.get("target", "Generic"), creativity=case.get("creativity", "Balanced"),
                       style=case.get("style", "Auto"), capture=case.get("capture", "Auto"),
                       prompt_length=case.get("length", "Medium"), director_preset=case.get("director", "general_director"),
                       custom_instructions=case.get("rules", ""))
    result = GoatedPrompterService(config).generate_text_only(request, seed=seed)
    return {"prompt": result.prompt}


def _dataset_case(case, seed, config, profile, log):
    from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
    from goated_prompter.features.dataset.v2.prompts import write_prompts
    from goated_prompter.features.dataset.v2.scenes import write_scenes
    from goated_prompter.features.dataset.v2.understanding import confirm, understand
    from goated_prompter.features.vocabulary.catalog import catalog_for, validate_selection
    fields = {"subject": case["subject"], "amount": case.get("amount", 4), "nsfw": bool(case.get("nsfw", False)),
              "target": case.get("target", "Generic"), "length": case.get("length", "Medium"),
              "creativity": case.get("creativity", "Balanced"), "style": case.get("style", "Auto"),
              "capture": case.get("capture", "Auto"), "aspect": case.get("aspect", "Auto"),
              "director_preset": case.get("director", "general_director"),
              "constraints": case.get("rules", ""), "triggers": case.get("triggers", []),
              "trigger_type": case.get("type", "Character"), "vocabulary_packs": case.get("vocabulary_packs", []),
              "source_mode": "guided" if case.get("inputs") else "random", "inputs": case.get("inputs", ""),
              "seed": seed, "seed_mode": "fixed"}
    data = validate_dataset_draft({**default_dataset_draft(), **fields}, generation=True)
    understanding = _request(profile, config, idea=data["subject"], mode="Custom", target_model=data["target"],
                             creativity=data["creativity"], style=data["style"], prompt_length=data["length"],
                             director_preset="general_director")
    brief = confirm(understand(config, understanding, data, progress=log), data)
    director = _request(profile, config, idea=brief["input"]["request"], mode="Custom", target_model=brief["settings"]["target"],
                        creativity=brief["settings"]["creativity"], style=brief["settings"]["style"],
                        capture=brief["settings"].get("capture") or "Auto", prompt_length=brief["settings"]["length"],
                        director_preset=brief["settings"]["director"])
    packs = [] if data["source_mode"] == "guided" else data["vocabulary_packs"]
    vocabulary = validate_selection(catalog_for(packs), packs)
    result = write_scenes(config, director, brief, progress=log, vocabulary=vocabulary)
    prompts = write_prompts(config, director, brief, result["scenes"], progress=log)
    return {"brief": brief, "scenes": result["scenes"], "missing": result["missing"], "slots": result.get("slots", []),
            "prompts": prompts}


def _record_call(calls, event):
    """One entry per model call from the backend's activity events: {"stage", "outcome", "tokens"?}."""
    kind = event.get("type")
    if kind == "request":
        calls.append({"stage": str(event.get("stage") or "final"), "outcome": "open"})
    elif calls and calls[-1]["outcome"] == "open" and kind in ("response_complete", "error"):
        calls[-1]["outcome"] = "ok" if kind == "response_complete" else "error"
        if event.get("tokens"):
            calls[-1]["tokens"] = event["tokens"]


def live(args):
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    main_root = Path(args.main_root)
    # The app's own data (Prompt Library, custom Directors, vocabulary packs) is used exactly as the app uses it.
    os.environ.setdefault("GOATED_PROMPTER_LIBRARY_DIR", str(main_root / "data" / "prompt_library"))
    config, profile = _engine(settings, main_root)
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.director_profiles import resolve_director_config
    effective, _ = resolve_director_config(config, _request(profile, config, idea="x"))
    out = Path(args.out)
    results = {"side": args.side, "code_root": str(args.code_root), "cases": []}
    runners = {"builder": _builder_case, "dataset": _dataset_case}
    # One session for the whole side keeps the model loaded between cases.
    with create_backend(effective).generation_session():
        for case in settings["cases"]:
            for seed in settings.get("seeds", [1]):
                print(f"[{args.side}] {case['id']} seed {seed}", flush=True)
                started = time.perf_counter()
                row = {"id": case["id"], "kind": case["kind"], "seed": seed, "case": case, "log": []}

                def log(message, row=row, started=started):
                    print(f"    {message}", flush=True)
                    row["log"].append(f"{time.perf_counter() - started:6.1f}s {message}")
                row["calls"] = []
                # The app listens to every model call (local_app.py) and so streams; the run does the same and keeps
                # each call's stage, outcome and the server's token counts, never the text.
                record = lambda event, calls=row["calls"]: _record_call(calls, event)
                try:
                    row["output"] = runners[case["kind"]](case, seed, {**config, "_activity_callback": record}, profile, log)
                    row["ok"] = True
                except Exception as error:  # one failing case is a result, not the end of the run
                    row.update(ok=False, error=f"{type(error).__name__}: {error}", trace=traceback.format_exc(limit=4))
                    print(f"    failed: {row['error']}", flush=True)
                row["seconds"] = round(time.perf_counter() - started, 1)
                results["cases"].append(row)
                out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


def judge(args):
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    judge_settings = settings.get("judge") or {}
    config, profile = _engine({**settings, "model_config": judge_settings.get("config") or settings["model_config"]},
                              Path(args.main_root))
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.contracts import PromptInstruction
    from goated_prompter.director_profiles import resolve_director_config
    effective, _ = resolve_director_config(config, _request(profile, config, idea="x"))
    dimensions = packet["dimensions"]
    schema = {"type": "object", "additionalProperties": False, "required": list(dimensions),
              "properties": {name: {"type": "string", "enum": ["A", "B", "tie"]} for name in dimensions}}
    system = (packet["rubric"] + "\n\nReturn one JSON object with one key per dimension, each \"A\", \"B\" or \"tie\".")
    review = {"reviewer": judge_settings.get("name") or "LLM judge", "review_kind": judge_settings.get("kind", "self_review"),
              "pairs": {}}
    with create_backend(effective).generation_session() as session:
        for pair in packet["pairs"]:
            print(f"[judge] {pair['pair']}", flush=True)
            try:
                raw = session.generate(PromptInstruction(system_message=system, user_message=pair["text"],
                                                         diagnostic_stage="quality:judge", json_output=True,
                                                         json_schema=schema, temperature=0.0, max_tokens=400,
                                                         hard_max_tokens=400))
                answer = json.loads(str(raw).strip().strip("`").removeprefix("json"))
                review["pairs"][pair["pair"]] = {name: answer.get(name, "") for name in dimensions}
            except Exception as error:
                print(f"    judge failed: {error}", flush=True)
    return review


def scenes(args):
    """{item number: {question: "yes"/"no"/"n/a"}}: the scene reviewer's answers for every image of the packet."""
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    judge_settings = settings.get("judge") or {}
    config, profile = _engine({**settings, "model_config": judge_settings.get("config") or settings["model_config"]},
                              Path(args.main_root))
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.contracts import PromptInstruction
    from goated_prompter.director_profiles import resolve_director_config
    effective, _ = resolve_director_config(config, _request(profile, config, idea="x"))
    questions = packet["questions"]
    schema = {"type": "object", "additionalProperties": False, "required": list(questions),
              "properties": {name: {"type": "string", "enum": ["yes", "no", "n/a"]} for name in questions}}
    system = packet["rubric"] + '\n\nReturn one JSON object with one key per question, each "yes", "no" or "n/a".'
    answers = {}
    with create_backend(effective).generation_session() as session:
        for number, item in enumerate(packet["items"]):
            print(f"[scene review] {number + 1} of {len(packet['items'])}", flush=True)
            try:
                raw = session.generate(PromptInstruction(system_message=system, user_message=item["text"],
                                                         diagnostic_stage="quality:scene_review", json_output=True,
                                                         json_schema=schema, temperature=0.0, max_tokens=200,
                                                         hard_max_tokens=200))
                answers[str(number)] = json.loads(str(raw).strip().strip("`").removeprefix("json"))
            except Exception as error:
                print(f"    scene review failed: {error}", flush=True)
    return answers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "live", "judge", "scenes"))
    parser.add_argument("--code-root", required=True, type=Path)
    parser.add_argument("--main-root", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--side", default="")
    args = parser.parse_args()
    sys.path.insert(0, str(args.code_root.resolve()))
    result = {"audit": audit, "live": live, "judge": judge, "scenes": scenes}[args.action](args)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
