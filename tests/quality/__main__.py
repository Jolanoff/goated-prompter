"""Quality check: does a change make Goated Prompter better, worse or no different?

    python -m tests.quality            full run: audit, live comparison, checks, report
    python -m tests.quality audit      audit only (no model, takes seconds)
    python -m tests.quality report     rebuild the latest report (after you saved a review.json)
    python -m tests.quality judge      let the model in the settings judge the latest run blind
    python -m tests.quality clean      remove the old code copies made for comparisons

Settings: quality.json in the project folder (made from tests/quality/quality.example.json on the first run). It is
yours and never tracked, like every result under quality-artifacts/quality/.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

from . import audit as audit_module
from .checks import compare, per_request, side_checks, stage_calls
from .judge import (attach_scene_review, build_packet, build_scene_packet, packet_markdown, review_template, save,
                    unblind)
from .report import render, verdict

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / "quality-artifacts" / "quality"
WORKTREES = ROOT / "quality-artifacts" / "worktrees"
SETTINGS = ROOT / "quality.json"
EXAMPLE = HERE / "quality.example.json"
CASE_KINDS = ("builder", "dataset")


def say(message):
    print(message, flush=True)


def load_settings(path):
    if not path.exists():
        shutil.copyfile(EXAMPLE, path)
        say(f"Made {path.name} from the example. Edit it to change the requests or settings.")
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings = {"baseline": "HEAD", "candidate": "working", "model_config": "config/config.json",
                "app_settings": "data/settings.json", "seeds": [1], "live": True, "judge": {"mode": "manual"},
                **settings}
    ids = [case.get("id") for case in settings.get("cases", [])]
    if settings["live"] and not ids:
        raise SystemExit("quality.json has no cases.")
    if len(set(ids)) != len(ids) or not all(ids):
        raise SystemExit("Every case in quality.json needs its own id.")
    for case in settings.get("cases", []):
        if case.get("kind") not in CASE_KINDS:
            raise SystemExit(f"Case {case.get('id')}: kind must be builder or dataset.")
        if not str(case.get("idea" if case["kind"] == "builder" else "subject") or "").strip():
            raise SystemExit(f"Case {case['id']}: write its {'idea' if case['kind'] == 'builder' else 'subject'}.")
    return settings


def git(*args):
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("Comparing with a commit needs Git on the PATH.") from None
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _link_data(copy):
    """The code copy uses the same private data folder as the app (library, packs, settings), never a copy of it."""
    source, link = ROOT / "data", copy / "data"
    if not source.exists() or link.exists():
        return
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(source), str(link))
    else:
        link.symlink_to(source, target_is_directory=True)


def code_root(ref):
    """(folder, label) for "working" (this folder as it is now) or any commit, branch or tag."""
    if str(ref or "working") == "working":
        return ROOT, "working folder"
    sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    copy = WORKTREES / sha[:12]
    if not (copy / "goated_prompter").is_dir():
        git("worktree", "prune")
        WORKTREES.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "--detach", "--force", str(copy), sha)
    _link_data(copy)
    return copy, f"{ref} ({sha[:8]})"


def worker(action, root, out, **options):
    command = [sys.executable, str(HERE / "worker.py"), action, "--code-root", str(root), "--main-root", str(ROOT),
               "--out", str(out)]
    for key, value in options.items():
        command += [f"--{key.replace('_', '-')}", str(value)]
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "GOATED_PROMPTER_CONFIG": str(ROOT / "config" / "config.json")}
    if subprocess.run(command, cwd=ROOT, env=environment).returncode != 0:
        raise SystemExit(f"The {action} step failed for {root}.")
    return json.loads(out.read_text(encoding="utf-8"))


def run_audit(run_dir, roots):
    dumps = {side: worker("audit", root, run_dir / f"audit-{side}.json") for side, root in roots.items()}
    found = {side: audit_module.collisions(dump) for side, dump in dumps.items()}
    new, fixed, remaining = audit_module.compare_findings(found["baseline"], found["candidate"])
    changes, assembled = audit_module.changes(dumps["baseline"], dumps["candidate"])
    errors_before = audit_module.summary(dumps["baseline"])["errors"]
    errors = {name: text for name, text in audit_module.summary(dumps["candidate"])["errors"].items()
              if name not in errors_before}
    return {"new": new, "fixed": fixed, "remaining": remaining, "duplicates": audit_module.duplicates(dumps["candidate"]),
            "changes": changes, "assembled": assembled, "errors": errors,
            "size": audit_module.summary(dumps["candidate"])["largest_instruction"]}


def finish(run_dir, run, open_page=True):
    """Add the review (when one was saved), decide the verdict and write the report."""
    review_file = run_dir / "review.json"
    run["review"] = None
    if review_file.exists() and run.get("key"):
        review = json.loads(review_file.read_text(encoding="utf-8"))
        if any(any(answers.values()) for answers in (review.get("pairs") or {}).values()):
            run["review"] = unblind(review, run["key"])
    run["verdict"] = verdict(run.get("audit"), run.get("checks"), run["review"])
    page, markdown = render(run)
    (run_dir / "report.html").write_text(page, encoding="utf-8")
    (run_dir / "report.md").write_text(markdown, encoding="utf-8")
    save(run_dir / "run.json", run)
    say(f"\nVerdict: {run['verdict'][0]}")
    for item in run["verdict"][1]:
        say(f"  worse:  {item}")
    for item in run["verdict"][2]:
        say(f"  better: {item}")
    for item in run["verdict"][3]:
        say(f"  note:   {item}")
    say(f"Report: {run_dir / 'report.html'}")
    if open_page:
        webbrowser.open((run_dir / "report.html").as_uri())


def full_run(settings, settings_path, audit_only=False, open_page=True):
    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True)
    save(run_dir / "settings.json", settings)
    baseline, baseline_label = code_root(settings["baseline"])
    candidate, candidate_label = code_root(settings["candidate"])
    roots = {"baseline": baseline, "candidate": candidate}
    run = {"label": f"old: {baseline_label} · new: {candidate_label} · {run_dir.name}"}
    say(f"Comparing {baseline_label} (old) with {candidate_label} (new).\n1. Audit...")
    run["audit"] = run_audit(run_dir, roots)
    if settings["live"] and not audit_only:
        sides = {}
        for side, root in roots.items():
            say(f"2. Live run, {side} ({len(settings['cases'])} case(s) x {len(settings['seeds'])} seed(s))...")
            sides[side] = worker("live", root, run_dir / f"live-{side}.json", settings=run_dir / "settings.json", side=side)
        if (settings.get("judge") or {}).get("scenes"):
            # Opt-in: one model call per image of both sides; its answers are hints, never the verdict.
            say("2b. Scene review...")
            scene_packet = build_scene_packet(sides, seed=run_dir.name)
            save(run_dir / "scene_packet.json", scene_packet)
            answers = worker("scenes", candidate, run_dir / "scene_review.json", settings=run_dir / "settings.json",
                             packet=run_dir / "scene_packet.json")
            attach_scene_review(sides, scene_packet, answers)
        say("3. Checks...")
        try:
            from goated_prompter.workflow_output import normalize_workflow_output as normalize
        except ImportError:
            normalize = None
        old, new = side_checks(sides["baseline"], normalize), side_checks(sides["candidate"], normalize)
        save(run_dir / "checks.json", {"baseline": old, "candidate": new})
        run["checks"] = compare(old, new)
        run["case_checks"] = per_request(old, new)
        run["stages"] = {side: stage_calls(rows) for side, rows in sides.items()}
        packet, key = build_packet(sides["baseline"], sides["candidate"], seed=run_dir.name)
        run["packet"], run["key"] = packet, key
        save(run_dir / "key.json", key)
        save(run_dir / "review_packet.json", packet)
        save(run_dir / "review_template.json", review_template(packet))
        (run_dir / "review_packet.md").write_text(packet_markdown(packet), encoding="utf-8")
        if (settings.get("judge") or {}).get("mode") == "llm":
            say("4. Blind judge...")
            save(run_dir / "review.json", worker("judge", candidate, run_dir / "review.json",
                                                 settings=run_dir / "settings.json", packet=run_dir / "review_packet.json"))
    finish(run_dir, run, open_page)


def latest_run(name=None):
    if name:
        path = Path(name) if Path(name).is_dir() else RUNS / name
    else:
        runs = sorted(path for path in RUNS.glob("*") if (path / "run.json").exists()) if RUNS.exists() else []
        path = runs[-1] if runs else None
    if not path or not (path / "run.json").exists():
        raise SystemExit("No finished quality run found.")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", default="run", choices=("run", "audit", "report", "judge", "clean"))
    parser.add_argument("run", nargs="?", help="report/judge: a run folder name (default: the latest)")
    parser.add_argument("--settings", type=Path, default=SETTINGS)
    parser.add_argument("--no-open", action="store_true", help="do not open the report in the browser")
    args = parser.parse_args(argv)
    if args.action == "clean":
        if WORKTREES.exists():
            for copy in WORKTREES.iterdir():
                subprocess.run(["git", "worktree", "remove", "--force", str(copy)], cwd=ROOT)
        git("worktree", "prune")
        say("Removed the code copies.")
        return
    if args.action in ("report", "judge"):
        run_dir = latest_run(args.run)
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if args.action == "judge":
            settings = json.loads((run_dir / "settings.json").read_text(encoding="utf-8"))
            candidate, _ = code_root(settings["candidate"])
            save(run_dir / "review.json", worker("judge", candidate, run_dir / "review.json",
                                                 settings=run_dir / "settings.json", packet=run_dir / "review_packet.json"))
        finish(run_dir, run, not args.no_open)
        return
    settings = load_settings(args.settings)
    full_run(settings, args.settings, audit_only=args.action == "audit", open_page=not args.no_open)


if __name__ == "__main__":
    main()
