"""Shared real-engine capture, run metadata and per-case scaffolding.

Workflow modules in ``tests.gpu.workflows`` supply only their production call;
everything that must match across workflows (request scaffolding, sample IDs,
timing, failure diagnostics) is built here once.
"""

from datetime import datetime, timezone
import hashlib
import subprocess
import time
from types import SimpleNamespace

from tests.support.paths import ROOT

SUBJECT_ID = "eval_subject"
IDENTITY_RULES = ("Include the exact subject identifier eval_subject. Do not invent stable identity traits or gender; "
                  "compatible temporary clothing and scene detail are allowed.")


def capture(calls, event):
    """Record one backend activity event against the current model call."""
    kind = event.get("type")
    if kind == "request":
        calls.append({"stage": event.get("stage"), "parameters": event.get("parameters"),
                      "messages": event.get("messages"), "raw": "", "finish_reason": None,
                      "started_at": time.perf_counter()})
    elif calls and kind == "response_delta":
        calls[-1]["raw"] += str(event.get("text") or "")
    elif calls and kind == "response_complete":
        calls[-1].update(finish_reason=event.get("finish_reason"), completion_state=event.get("completion_state", "completed"))
        if isinstance(event.get("usage"), dict):
            calls[-1]["usage"] = event["usage"]
        calls[-1]["latency_seconds"] = time.perf_counter() - calls[-1]["started_at"]
    elif calls and kind == "error":
        calls[-1].update(error=event.get("message"), completion_state=event.get("completion_state", "provider_error"))
        calls[-1]["latency_seconds"] = time.perf_counter() - calls[-1]["started_at"]
    elif calls and kind in {"semantic_review", "validation"}:
        calls[-1].setdefault("validation_events", []).append(event)


def token_usage(calls):
    """Sum reported token usage; None unless every model call reported it."""
    if not calls or any(not isinstance(call.get("usage"), dict) for call in calls):
        return None
    totals = {}
    for call in calls:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if isinstance(call["usage"].get(key), int):
                totals[key] = totals.get(key, 0) + call["usage"][key]
    return totals or None


def run_metadata(config, corpus_digest):
    code = hashlib.sha256()
    source_root = ROOT / "goated_prompter"
    for path in sorted(source_root.rglob("*.py")):
        code.update(str(path.relative_to(source_root)).replace("\\", "/").encode())
        code.update(path.read_bytes())
    return {"run_id": datetime.now(timezone.utc).isoformat(),
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "code_digest": code.hexdigest(), "corpus_digest": corpus_digest,
            "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
            "engine": {key: config.get("openai_compatible", {}).get(key) for key in ("model", "context_size")}}


def run_case(case, workflow, config, args, run, *, approve=None):
    """Run one corpus case through a workflow's production entry point."""
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.planning.constraints import compile_request
    from tests.gpu.workflows import WORKFLOWS
    module = WORKFLOWS[workflow]
    calls = []
    config = {**config, "_activity_callback": lambda event: capture(calls, event)}
    length = case.get("length", args.length)
    compiled_source = compile_request(case["request"])
    rules = case.get("rules", "")
    if compiled_source.forbidden:
        rules += "\n" + "; ".join("no " + fact for fact in compiled_source.forbidden)
    # Builder and Dataset share Dataset's explicit trigger/identity restriction for
    # parity; it is evaluation scaffolding, not a production planning step.
    source = "eval_subject represents " + case["request"] if module.SUBJECT_SCAFFOLD else case["request"]
    common_rules = rules
    identity_rules = ""
    if module.SUBJECT_SCAFFOLD:
        identity_rules = IDENTITY_RULES
        common_rules += "\n" + identity_rules
    request = GoatedPrompterRequest(idea=source, target_model=args.target, prompt_length=length,
        director_preset=args.director, creativity=args.creativity, planning_mode=args.planning,
        custom_instructions=common_rules)
    sample_id = "|".join(str(value) for value in (case["id"], workflow, args.target, length, args.director,
                                               args.creativity, args.planning, run)) + module.SAMPLE_SUFFIX
    row = {"sample_id": sample_id, "case_id": case["id"], "workflow": workflow,
           "run": run, "request": case["request"], "anchors": case["anchors"], "rules": rules,
           "target": module.TARGET or args.target, "length": length, "director": args.director,
           "creativity": args.creativity, "planning": args.planning,
           "effective_request": source, "calls": calls}
    if module.SUBJECT_SCAFFOLD:
        row.update(trigger=SUBJECT_ID, expand_trigger=False)
    context = SimpleNamespace(case=case, config=config, args=args, request=request, rules=rules,
                              identity_rules=identity_rules, length=length, approve=approve)
    start = time.perf_counter()
    try:
        module.execute(row, context)
        row.setdefault("completion_state", "completed")
    except Exception as exc:
        row.update(error=str(exc), completion_state=getattr(exc, "completion_state", "provider_error"),
                   partial_text=getattr(exc, "partial_text", ""))
    row.update(latency_seconds=time.perf_counter() - start,
               finish_reason=calls[-1].get("finish_reason") if calls else None)
    return row
