"""Dataset Understanding v10: real-model evaluation of the structured intent.

Each case in fixtures/dataset_understanding_eval.json is one request sent through the production
understanding.understand() call. One run = one understand(): the answer, at most one repair, and runaway
recovery all share one budget of recovery.MAX_ATTEMPTS (3) model calls. Expectations are checked
automatically, including identity coverage, action bindings and search-term coverage/non-echo checks.
Semantic relevance still needs a reviewer in the review sheet. Nothing else in the pipeline runs.

--llama-cpp sends what the app's own llama.cpp adapter sends (the JSON schema as response_format and
thinking disabled through chat_template_kwargs), by building the same shared backend with the same flag.
Use it only for an endpoint you know is a llama.cpp server; it is never inferred from a model name.
Thinking ("reasoning") text is recorded apart from the answer text.

  python -m tests.gpu.dataset_understanding_eval --dry-run [--batch smoke|rest|all]
      No inference. Lists the planned runs and the call ceiling.
  python -m tests.gpu.dataset_understanding_eval --probe --config CONFIG.json
      No inference. Asks the endpoint for its model list and stops if it does not answer.
  python -m tests.gpu.dataset_understanding_eval --allow-live --config CONFIG.json --task-key KEY
                                                  --max-runs N --max-calls M [--batch smoke|rest|all] [--case ID]
      Real engine, after owner approval: an existing OpenAI-compatible endpoint only. The script never
      starts, stops or changes a model process or its settings. Runs are sequential; the endpoint is
      probed first and a failed probe costs no run. A run that would pass --max-calls is refused before it
      starts (a run may use up to 3 calls). Writes understanding-eval-<batch>.json and
      understanding-review-<batch>.json under quality-artifacts/tasks/KEY/gpu/.
  python -m tests.gpu.dataset_understanding_eval --diagnose --allow-live --config CONFIG.json --task-key KEY
                                                  --max-calls 1 [--case simple] [--llama-cpp]
      Exactly one model request: the production Understanding instruction for one case, with no runaway
      recovery and no repair round. Records the request settings, finish reason, reasoning and answer
      size, and whether the answer is a valid v10 brief. Writes understanding-diagnostic.json.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest import mock
from urllib.request import Request, urlopen

from tests.support.artifacts import new_output, task_paths
from tests.support.paths import ROOT
from tests.support.safety import private_storage_guard, synthetic_storage

CASES = Path(__file__).resolve().parent / "fixtures" / "dataset_understanding_eval.json"
WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


class CallLimit(RuntimeError):
    completion_state = "call_limit"


def calls_per_run():
    """The most model calls one understand() can make: the shared recovery budget (answer, repair, retries)."""
    from goated_prompter.backends.recovery import MAX_ATTEMPTS
    return MAX_ATTEMPTS


def record(calls, event):
    """tests.gpu.common.capture, plus thinking text kept apart from the answer text."""
    from tests.gpu.common import capture
    if event.get("type") == "reasoning_delta":
        if calls:
            calls[-1]["reasoning"] = calls[-1].get("reasoning", "") + str(event.get("text") or "")
        return
    capture(calls, event)


def call_report(config, call):
    answer, reasoning = call.get("raw") or "", call.get("reasoning") or ""
    return {**{key: call.get(key) for key in ("stage", "finish_reason", "completion_state", "latency_seconds", "error")},
            "output_chars": len(answer), "output_tokens": count_tokens(config, answer) if answer else 0,
            "reasoning_chars": len(reasoning), "reasoning_tokens": count_tokens(config, reasoning) if reasoning else 0}


def plan(fixture, batch, selected=None):
    """[(case, seed)] in run order: every case once, then the reseeded cases with the second seed."""
    by_id = {case["id"]: case for case in fixture["cases"]}
    if selected:
        unknown = set(selected) - set(by_id)
        if unknown:
            raise ValueError(f"Unknown case id {sorted(unknown)}; see {CASES.name}")
        order = [(by_id[case_id], fixture["seed"]) for case_id in selected]
    else:
        first = [(case, fixture["seed"]) for case in fixture["cases"]]
        second = [(by_id[case_id], fixture["reseed"]) for case_id in fixture["reseeded"]]
        order = first + second
        smoke = set(fixture["smoke"])
        if batch == "smoke":
            order = [(case, seed) for case, seed in first if case["id"] in smoke]
        elif batch == "rest":
            order = [(case, seed) for case, seed in first if case["id"] not in smoke] + second
    return order


def draft(case, seed, amount):
    from goated_prompter.features.dataset.v2.draft import default_dataset_draft
    data = {**default_dataset_draft(), "subject": case["request"], "amount": amount, "seed": seed, "seed_mode": "fixed",
            "nsfw": case.get("nsfw") is True, "constraints": "\n".join(case.get("rules", []))}
    if case.get("guided_inputs"):
        data.update(source_mode="guided", inputs="\n".join(case["guided_inputs"]))
    return data


# ---------------------------------------------------------------- scoring

def _words(text):
    return {word.casefold() for word in WORD.findall(str(text or ""))}


def _names(element):
    return _words(" ".join([element.get("text", ""), element.get("character", ""), *element.get("cast", [])]))


def _find(elements, expected):
    kinds = expected["kind"] if isinstance(expected["kind"], list) else [expected["kind"]]
    wanted = {word.casefold() for word in expected["text"]}
    return next((item for item in elements if item["kind"] in kinds and _words(item["text"]) & wanted), None)


def _linked(parts, ids, words):
    """Every expected word names one of the linked parts (or the owner of one)."""
    linked = [parts[item] for item in ids if item in parts]
    owners = [parts[item["of"]] for item in linked if item.get("of") in parts]
    names = set().union(*(_names(item) for item in linked + owners)) if linked else set()
    return all(word.casefold() in names for word in words)


def _cast(parts, ids):
    return {label for ident in ids if ident in parts for label in parts[ident].get("cast", [])}


def term_checks(item):
    """Lexical novelty only: a new word does not prove a term is a relevant related idea."""
    from goated_prompter.features.vocabulary.semantic import NEGATIONS, STOPWORDS, stem

    def content(text):
        words = _words(str(text).replace("-", " "))
        return {stem(word) for word in words if word not in STOPWORDS and word not in NEGATIONS and not word.isdigit()}

    own = content(item["text"])
    terms = item.get("terms", [])
    echoes = [term for term in terms if not content(term) - own]
    return {"covered": any(content(term) for term in terms), "echoes": echoes}


def score(case, brief):
    """Automatic checks of one brief against the case's expectations: [{check, group, ok, detail}]."""
    expect, checks = case["expect"], []
    intent = brief.get("intent") or {}
    elements = intent.get("elements", [])
    parts = {item["id"]: item for item in elements}

    def add(group, check, ok, detail=""):
        checks.append({"group": group, "check": check, "ok": bool(ok), "detail": detail})

    paths = ("sfw_character", "nsfw_character") if expect["path"] == "character" else (expect["path"],)
    add("subjects", "path", brief.get("path") in paths, brief.get("path"))
    low, high = expect["people"]
    add("subjects", "people", low <= len(brief.get("characters", [])) <= high, len(brief.get("characters", [])))
    if not intent.get("available", False):
        add("intent", "available", False, intent.get("reason") or intent.get("warnings"))
        return checks
    subjects = [item for item in elements if item["kind"] == "subject" and item["status"] != "excluded"]
    people = [person["label"] for person in brief.get("characters", [])]
    bindings = Counter(label for item in subjects for label in item.get("cast", []))
    add("identities", "each person bound once", bindings == Counter(people) and all(item.get("cast") for item in subjects),
        {"expected": people, "bindings": dict(bindings), "unbound": [item["id"] for item in subjects if not item.get("cast")]})
    for item in elements:
        if item["kind"] == "action":
            actors = item.get("by", [])
            add("relationships", f'{item["id"]}: action has bound actors', actors and all(
                ident in parts and parts[ident] in subjects and parts[ident].get("cast") for ident in actors), actors)
    term_parts = [item for item in elements if item["kind"] != "subject"]
    covered = sum(term_checks(item)["covered"] for item in term_parts)
    add("terms", "related ideas coverage >= 90%", covered * 10 >= len(term_parts) * 9, f"{covered}/{len(term_parts)}")
    for item in term_parts:
        checks_for_terms = term_checks(item)
        add("terms", f'{item["id"]}: related ideas add words', not checks_for_terms["echoes"],
            {"terms": item.get("terms", []), "echoes": checks_for_terms["echoes"]})
    for expected in expect.get("elements", []):
        name = "/".join(expected["text"][:2])
        found = _find(elements, expected)
        group = "subjects" if expected["kind"] == "subject" else "requirements"
        add(group, f"{expected['kind']} {name}: present", found, found and found["id"])
        if not found:
            continue
        if "status" in expected:
            statuses = expected["status"] if isinstance(expected["status"], list) else [expected["status"]]
            add("status", f"{name}: status {'/'.join(statuses)}", found["status"] in statuses, found["status"])
        for field in ("by", "to"):
            if field in expected:
                add("relationships", f"{name}: {field} {', '.join(expected[field])}",
                    _linked(parts, found.get(field, []), expected[field]),
                     [parts[item]["text"] for item in found.get(field, []) if item in parts])
        if "by_people" in expected:
            actors = _cast(parts, found.get("by", []))
            add("relationships", f"{name}: by people {expected['by_people']}", len(actors) == expected["by_people"], sorted(actors))
        if "to_actor_of" in expected:
            other = _find(elements, {"kind": "action", "text": expected["to_actor_of"]})
            targets = _cast(parts, found.get("to", []))
            actors = _cast(parts, other.get("by", [])) if other else set()
            add("relationships", f"{name}: targets actor of {expected['to_actor_of'][0]}", actors and targets == actors,
                {"targets": sorted(targets), "actors": sorted(actors)})
        if "of" in expected:
            owner = parts.get(found.get("of"))
            add("relationships", f"{name}: of {', '.join(expected['of'])}",
                owner and all(word in _names(owner) for word in expected["of"]), owner and owner["text"])
        if "input" in expected:
            add("relationships", f"{name}: input {expected['input']}", found.get("input") == expected["input"], found.get("input"))
    for words in expect.get("avoid", []):
        avoid = _words(" ".join(brief.get("avoid", [])))
        add("status", f"avoid has {words[0]}", avoid & set(words), brief.get("avoid"))
    for status in expect.get("no_status", []):
        add("status", f"no {status} parts", not any(item["status"] == status for item in elements),
            [item["text"] for item in elements if item["status"] == status])
    if "unresolved" in expect:
        add("ambiguity", "ambiguity noted" if expect["unresolved"] else "no ambiguity noted",
             bool(intent.get("unresolved")) == expect["unresolved"], intent.get("unresolved"))
    if "different_actors" in expect:
        actions = [_find(elements, {"kind": "action", "text": words}) for words in expect["different_actors"]]
        roles = [_cast(parts, item.get("by", [])) if item else set() for item in actions]
        add("relationships", "distinct action roles", all(roles) and sum(map(len, roles)) == len(set().union(*roles)),
            [sorted(role) for role in roles])
    request = _words(" ".join([case["request"], *case.get("rules", []), *case.get("guided_inputs", [])]))
    for word in expect.get("forbidden", []):
        invented = [f'{item["text"]} ({item["source"]}, {item["status"]})' for item in elements
                    if word.casefold() in _words(item["text"]) and word.casefold() not in request]
        add("invented", f"no invented {word}", not invented, invented)
    # Use production's wording warnings, not a second exact-word rule that rejects normalized people/inflections.
    grounding = [note for note in intent.get("warnings", []) if "request does not seem to say it" in note]
    add("invented", "no ungrounded required parts", not grounding, grounding)
    return checks


def run_summary(row):
    calls = row["calls"]
    intent = (row.get("brief") or {}).get("intent") or {}
    checks = row.get("checks", [])
    groups = {}
    for check in checks:
        passed, total = groups.get(check["group"], (0, 0))
        groups[check["group"]] = (passed + check["ok"], total + 1)
    return {"model_calls": len(calls), "repairs": max(0, len(row.get("attempts", [])) - 1),
            "unfinished_calls": sum(1 for call in calls if call.get("completion_state") != "completed"),
            "intent_fallback": bool(row.get("brief")) and not intent.get("available", False),
            "intent_truncated": intent.get("truncated", False),
            "cut_off_calls": sum(1 for call in calls if call.get("completion_state") == "token_limit"),
            "output_chars": [call.get("output_chars") for call in calls],
            "output_tokens": [call.get("output_tokens") for call in calls],
            "reasoning_tokens": [call.get("reasoning_tokens") for call in calls],
            "calls_with_reasoning": sum(1 for call in calls if call.get("reasoning_chars")),
            "elements": len(intent.get("elements", [])), "relations": len(intent.get("relations", [])),
            "unresolved": len(intent.get("unresolved", [])), "warnings": intent.get("warnings", []),
            "checks": {group: f"{passed}/{total}" for group, (passed, total) in groups.items()},
            "passed": sum(check["ok"] for check in checks), "total": len(checks)}


def review_rows(case, brief):
    """Include missing terms; novelty/coverage cannot decide semantic relevance or safety."""
    elements = ((brief or {}).get("intent") or {}).get("elements", [])
    focus = {word.casefold() for word in case["expect"].get("review_terms", [])}
    return [{"id": item["id"], "part": item["text"], "kind": item["kind"], "status": item["status"], "source": item["source"],
             "terms": item.get("terms", []), "focus": bool(_words(item["text"]) & focus),
             **term_checks(item), "term_quality_1_to_5": None, "notes": ""}
            for item in elements if item["kind"] != "subject"]


# ---------------------------------------------------------------- live

def models_url(config):
    from goated_prompter.backends.openai_compatible import _chat_completions_url
    return _chat_completions_url(config.get("openai_compatible", {}).get("base_url"))[:-len("/chat/completions")] + "/models"


def count_tokens(config, text, timeout=10):
    """Tokens in text by the endpoint's own tokenizer (llama.cpp /tokenize; no inference). None when unsupported."""
    base = config.get("openai_compatible", {}).get("base_url", "").rstrip("/")
    root = re.sub(r"/v1(?:/chat/completions)?$", "", base)
    try:
        request = Request(root + "/tokenize", data=json.dumps({"content": text}).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            tokens = json.loads(response.read().decode("utf-8")).get("tokens")
        return len(tokens) if isinstance(tokens, list) else None
    except Exception:
        return None


def probe(config, timeout=10):
    """The endpoint's model list (no inference); raises when it does not answer."""
    request = Request(models_url(config), headers={"Accept": "application/json"})
    key = config.get("openai_compatible", {}).get("api_key")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    with urlopen(request, timeout=timeout) as response:
        return [item.get("id") for item in json.loads(response.read().decode("utf-8")).get("data", [])]


class _Counted:
    """Refuses a model call past the approved ceiling before it reaches the endpoint."""

    def __init__(self, backend, budget):
        self.backend, self.budget = backend, budget

    @contextmanager
    def generation_session(self):
        with self.backend.generation_session() as session:
            yield _CountedSession(session, self.budget)


class _CountedSession:
    def __init__(self, session, budget):
        self.session, self.budget = session, budget

    def generate(self, instruction):
        if self.budget["used"] >= self.budget["max"]:
            raise CallLimit(f"The approved ceiling of {self.budget['max']} model calls is reached.")
        self.budget["used"] += 1
        return self.session.generate(instruction)

    def __getattr__(self, name):
        return getattr(self.session, name)


def run_case(config, case, seed, amount, budget):
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.features.dataset.v2 import understanding
    calls, traces = [], []

    class KeptTrace(understanding.DebugTrace):
        def finish(self, output=None, error=None):
            self.record.update(output=output, error=error)
            traces.append(self.record)

    data = draft(case, seed, amount)
    request = GoatedPrompterRequest(idea=case["request"], planning_mode="Direct", director_preset=data["director_preset"])
    run_config = {**config, "_activity_callback": lambda event: record(calls, event)}
    row = {"case": case["id"], "covers": case["covers"], "seed": seed, "request": case["request"],
           "guided_inputs": case.get("guided_inputs", [])}
    with mock.patch.object(understanding, "create_backend", lambda effective: _Counted(create_backend(effective), budget)), \
            mock.patch.object(understanding, "DebugTrace", KeptTrace):
        try:
            row["brief"] = understanding.understand(run_config, request, data, progress=lambda message: print(f"  {message}", flush=True))
        except Exception as error:  # the row keeps the failure for the reviewer
            row["error"] = f"{type(error).__name__}: {error}"
            row["call_limit"] = isinstance(error, CallLimit)
    trace = traces[-1] if traces else {}
    row["attempts"] = [{"errors": item.get("errors", []), "raw": item.get("raw", "")} for item in trace.get("attempts", [])]
    row["decisions"] = trace.get("decisions", [])
    row["calls"] = [call_report(config, call) for call in calls]
    row["checks"] = score(case, row["brief"]) if row.get("brief") else []
    row["summary"] = run_summary(row)
    return row


def totals(rows):
    done = [row for row in rows if row.get("brief")]
    checks = [check for row in rows for check in row.get("checks", [])]
    groups = {}
    for check in checks:
        passed, total = groups.get(check["group"], (0, 0))
        groups[check["group"]] = (passed + check["ok"], total + 1)
    tokens = [value for row in rows for value in row["summary"]["output_tokens"] if isinstance(value, int)]
    chars = [value for row in rows for value in row["summary"]["output_chars"] if isinstance(value, int)]
    return {"runs": len(rows), "briefs": len(done), "failed_runs": len(rows) - len(done),
            "passed": bool(rows) and len(done) == len(rows) and bool(checks) and all(check["ok"] for check in checks),
            "model_calls": sum(row["summary"]["model_calls"] for row in rows),
            "runs_with_repair": sum(row["summary"]["repairs"] > 0 for row in rows),
            "intent_fallbacks": sum(row["summary"]["intent_fallback"] for row in rows),
            "intent_truncated": sum(bool(row["summary"]["intent_truncated"]) for row in rows),
            "cut_off_calls": sum(row["summary"]["cut_off_calls"] for row in rows),
            "calls_with_reasoning": sum(row["summary"]["calls_with_reasoning"] for row in rows),
            "output_tokens": {"max": max(tokens), "mean": round(sum(tokens) / len(tokens)), "limit": 3072} if tokens else None,
            "output_chars": {"max": max(chars), "mean": round(sum(chars) / len(chars))} if chars else None,
            "checks": {group: f"{passed}/{total}" for group, (passed, total) in groups.items()},
            "failed_checks": [{"case": row["case"], "seed": row["seed"], "check": check["check"], "detail": check["detail"]}
                              for row in rows for check in row.get("checks", []) if not check["ok"]]}


# ---------------------------------------------------------------- one-request diagnostic

ANSWER_TOKEN_LIMIT, SECONDS_LIMIT = 1024, 30


def diagnose(config, case, seed, amount, budget):
    """One model request with the production instruction, then the production checks on its answer."""
    from goated_prompter.backends.factory import create_backend
    from goated_prompter.contracts import GoatedPrompterRequest
    from goated_prompter.features.dataset.v2 import understanding
    calls = []
    data = draft(case, seed, amount)
    request = GoatedPrompterRequest(idea=case["request"], planning_mode="Direct", director_preset=data["director_preset"])
    run_config = {**config, "_activity_callback": lambda event: record(calls, event)}
    effective, profile = understanding.resolve_director_config(run_config, request)
    family = understanding.effective_model_family(request, profile, effective)
    prompt = understanding.instruction(data, family)
    result = {"case": case["id"], "seed": seed, "request": case["request"], "model_family": family}
    raw = None
    try:
        with _Counted(create_backend(effective), budget).generation_session() as session:
            raw = session.generate(prompt)  # no GenerationRecovery and no repair round: one request
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    call = calls[-1] if calls else {}
    result["request_settings"] = {"model": config["openai_compatible"].get("model"), "parameters": call.get("parameters"),
                                  "instruction": {"max_tokens": prompt.max_tokens, "hard_max_tokens": prompt.hard_max_tokens,
                                                  "temperature": prompt.temperature, "top_p": prompt.top_p, "seed": prompt.seed,
                                                  "json_output": prompt.json_output},
                                  "system_message": prompt.system_message, "user_message": prompt.user_message}
    result["call"] = call_report(config, call) if call else None
    result["reasoning_text"] = call.get("reasoning", "")
    result["answer_text"] = raw if raw is not None else call.get("raw", "")
    validation = {"parsed": False, "model_errors": None, "intent_errors": None, "brief_valid": False}
    if raw is not None:
        try:
            value = understanding.parse(raw)
            validation["parsed"] = True
            validation["model_errors"] = understanding.model_errors(value, data.get("nsfw") is True)
            validation["intent_errors"] = [] if validation["model_errors"] else understanding.intent_errors(value, data)
            if not validation["model_errors"] and not validation["intent_errors"]:
                brief = understanding.validate_brief(understanding.apply_rules(value, data, understanding.DebugTrace("diagnostic")))
                validation.update(brief_valid=True, version=brief["version"], intent_available=brief["intent"]["available"],
                                  intent_parts=len(brief["intent"]["elements"]), intent_warnings=brief["intent"]["warnings"])
                result["brief"] = brief
        except Exception as error:
            validation["error"] = f"{type(error).__name__}: {error}"
    result["validation"] = validation
    report = result["call"] or {}
    tokens = report.get("output_tokens")
    criteria = {
        "normal completion": report.get("completion_state") == "completed" and report.get("finish_reason") == "stop",
        "valid v10 JSON": validation["brief_valid"] and validation.get("version") == 10 and validation.get("intent_available") is True,
        "no reasoning output": report.get("reasoning_chars", 0) == 0 and bool(report),
        "no repair": validation["brief_valid"],  # one request only: a repair would have been needed otherwise
        f"fewer than {ANSWER_TOKEN_LIMIT} answer tokens": isinstance(tokens, int) and 0 < tokens < ANSWER_TOKEN_LIMIT,
        f"under {SECONDS_LIMIT} seconds": isinstance(report.get("latency_seconds"), (int, float)) and report["latency_seconds"] < SECONDS_LIMIT}
    if tokens is None:
        criteria[f"fewer than {ANSWER_TOKEN_LIMIT} answer tokens"] = None  # the endpoint has no /tokenize: not measured
    result["criteria"] = criteria
    result["passed"] = all(value is True for value in criteria.values())
    return result


def diagnose_main(config, fixture, run_plan, args):
    case, seed = run_plan
    try:
        results_dir, scratch = task_paths(args.task_key, "gpu")
        output = new_output(results_dir / "understanding-diagnostic.json", args.task_key, "gpu")
    except ValueError as exc:
        print(str(exc))
        return 2
    from tests.gpu.common import run_metadata
    budget = {"used": 0, "max": 1}
    with synthetic_storage(scratch):
        print(f"Diagnostic: one request for {case['id']} (seed {seed}); "
              f"{'llama.cpp adapter' if args.llama_cpp else 'generic OpenAI-compatible'} request path", flush=True)
        result = diagnose(config, case, seed, fixture["amount"], budget)
    run = {**run_metadata(config, hashlib.sha256(CASES.read_bytes()).hexdigest()),
           "request_path": "llama.cpp adapter" if args.llama_cpp else "generic OpenAI-compatible",
           "calls_used": budget["used"], **result}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"calls_used": budget["used"], "call": result["call"], "validation": result["validation"],
                      "criteria": result["criteria"], "passed": result["passed"], "error": result.get("error")},
                     ensure_ascii=False, indent=2))
    print(f"Results: {output.relative_to(ROOT)}")
    return 0 if result["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe", action="store_true", help="Check the endpoint answers; no inference")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--task-key")
    parser.add_argument("--max-runs", type=int, help="Approved maximum understand() runs")
    parser.add_argument("--max-calls", type=int, help="Approved maximum Understanding model calls")
    parser.add_argument("--batch", choices=("smoke", "rest", "all"), default="smoke")
    parser.add_argument("--case", action="append")
    parser.add_argument("--llama-cpp", action="store_true",
                        help="The endpoint is a llama.cpp server: send what the app's own llama.cpp adapter sends")
    parser.add_argument("--diagnose", action="store_true", help="Exactly one model request for one case; no recovery or repair")
    args = parser.parse_args(argv)
    if args.diagnose:
        args.case = args.case or ["simple"]
        if len(args.case) != 1:
            parser.error("--diagnose takes exactly one --case.")
    sys.addaudithook(private_storage_guard)  # nothing under data/ is read
    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    try:
        runs = plan(fixture, args.batch, args.case)
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        print(json.dumps({"inference": False, "batch": args.batch, "runs": len(runs), "call_ceiling": 1 if args.diagnose else calls_per_run() * len(runs),
                          "plan": [{"case": case["id"], "seed": seed, "covers": case["covers"]} for case, seed in runs]},
                         ensure_ascii=False, indent=2))
        return 0

    if not args.config:
        parser.error("--config is required for --probe and live runs.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("backend") != "openai_compatible":
        parser.error("Use an explicitly configured existing OpenAI-compatible endpoint; no process ownership changes.")
    try:
        models = probe(config)
    except Exception as error:
        print(f"Endpoint unavailable at {models_url(config)}: {type(error).__name__}: {error}\nStopped; no run spent.")
        return 2
    print(f"Endpoint answered at {models_url(config)}; models: {models}")
    if not config["openai_compatible"].get("model") and len(models) == 1:
        config["openai_compatible"]["model"] = models[0]  # the one model the endpoint serves; nothing on it is changed
    if args.llama_cpp:
        config["openai_compatible"]["_is_llama_cpp"] = True  # exactly what LocalLlamaCppBackend passes the same backend
    if args.probe:
        return 0
    if args.diagnose:
        if not (args.allow_live and args.task_key and args.max_calls == 1):
            parser.error("The diagnostic requires --allow-live, --config, --task-key and --max-calls 1 after owner approval.")
        return diagnose_main(config, fixture, runs[0], args)

    if not (args.allow_live and args.task_key and args.max_runs is not None and args.max_calls is not None):
        parser.error("Real-engine runs require --allow-live, --config, --task-key, --max-runs and --max-calls after owner approval.")
    if len(runs) > args.max_runs:
        parser.error(f"{len(runs)} runs are planned; --max-runs is {args.max_runs}. Narrow --batch or --case.")
    try:
        results_dir, scratch = task_paths(args.task_key, "gpu")
        output = new_output(results_dir / f"understanding-eval-{args.batch}.json", args.task_key, "gpu")
        review_output = new_output(results_dir / f"understanding-review-{args.batch}.json", args.task_key, "gpu")
    except ValueError as exc:
        parser.error(str(exc))
    from tests.gpu.common import run_metadata
    run = {**run_metadata(config, hashlib.sha256(CASES.read_bytes()).hexdigest()), "batch": args.batch,
           "request_path": "llama.cpp adapter" if args.llama_cpp else "generic OpenAI-compatible",
           "approved": {"max_runs": args.max_runs, "max_calls": args.max_calls}, "rows": []}
    budget = {"used": 0, "max": args.max_calls}
    output.parent.mkdir(parents=True, exist_ok=True)
    stopped = None
    with synthetic_storage(scratch):
        for number, (case, seed) in enumerate(runs, 1):
            if args.max_calls - budget["used"] < calls_per_run():  # never start a run the ceiling could cut short
                stopped = "call ceiling reached"
                break
            print(f"[{number}/{len(runs)}] {case['id']} (seed {seed}); calls used {budget['used']}/{args.max_calls}", flush=True)
            row = run_case(config, case, seed, fixture["amount"], budget)
            run["rows"].append(row)
            run["totals"] = totals(run["rows"])
            output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: row["summary"][key] for key in ("model_calls", "repairs", "intent_fallback", "checks",
                                                                     "passed", "total", "output_tokens")}, ensure_ascii=False))
            if row.get("call_limit"):
                stopped = "call ceiling reached"
                break
            if row.get("error") and not row.get("brief") and any(call.get("completion_state") == "provider_error"
                                                                 for call in row["calls"]):
                stopped = "endpoint error: " + row["error"]
                break
    run["calls_used"], run["stopped"] = budget["used"], stopped
    run["totals"] = totals(run["rows"])
    output.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    review = [{"case": row["case"], "seed": row["seed"], "request": row["request"], "parts": review_rows(case, row.get("brief"))}
              for row, case in ((row, next(item for item in fixture["cases"] if item["id"] == row["case"])) for row in run["rows"])]
    review_output.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(run["rows"]), "calls_used": budget["used"], "stopped": stopped, **run["totals"]},
                     ensure_ascii=False, indent=2))
    print(f"Results: {output.relative_to(ROOT)}\nReview sheet: {review_output.relative_to(ROOT)}")
    return 1 if stopped or not run["totals"]["passed"] else 0


if __name__ == "__main__":
    sys.exit(main())
