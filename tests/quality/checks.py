"""Layer 3a: objective checks on one side's live outputs, computed the same way for the old and the new code.

Guard checks must never get worse (a lost image, a broken format, a leftover label). Aim checks show whether the
output got more varied. Each check is a number per case and a total; nothing here judges taste.
"""

import itertools
import re

ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
# (name, what it measures, "guard": must not get worse / "aim": should improve, True when higher is better)
CHECKS = (
    ("written", "share of requested prompts that were written", "guard", True),
    ("format_ok", "share of prompts the target's format check accepts", "guard", True),
    ("cast_ok", "share of scenes that keep every person of the cast", "guard", True),
    ("actions_named", "share of scenes whose actions name every person (no copied placeholder people)", "guard", True),
    ("avoid_hits", "phrases the user ruled out that appear anyway", "guard", False),
    ("count_tags_ok", "Anima: share of tag lines whose people-count tags match the cast", "guard", True),
    ("bad_tags", "Anima: share of tag lines with underscores or low-quality tags in the positive prompt", "guard", False),
    ("label_leaks", "share of prompts that still call a person \"man 1\" or \"the first man\"", "guard", False),
    ("repeated_looks", "share of image pairs whose people look identical", "aim", False),
    ("repeated_places", "share of image pairs set in the same place", "aim", False),
    ("repeated_extras", "share of image pairs with the same props and signs", "aim", False),
    ("prompt_similarity", "how alike the prompts are (a set's images; a Builder case's seeds), 0 to 1", "aim", False),
    ("words", "average prompt length in words", "info", True),
    ("seconds", "average time per run in seconds (more retries cost time)", "info", False),
    ("request_words_echoed", "share of the request's own words repeated in the prompts (told, not shown; a hint)", "info", False),
)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").casefold())) - {"a", "an", "the", "and", "of", "in", "on",
                                                                          "with", "his", "her", "their", "to", "is"}


def _overlap(a, b):
    a, b = _words(a), _words(b)
    return len(a & b) / max(1, min(len(a), len(b))) if a and b else 0.0


def _jaccard(a, b):
    a, b = _words(a), _words(b)
    return len(a & b) / max(1, len(a | b)) if a and b else 0.0


def _share(pairs, test):
    pairs = list(pairs)
    return round(sum(1 for a, b in pairs if test(a, b)) / len(pairs), 3) if pairs else None


def _format_ok(prompt, target, normalize):
    if normalize is None:
        return None
    try:
        normalize(prompt, target, mode="Enhance")
        return bool(prompt.strip())
    except (ValueError, TypeError, KeyError):
        return False


def _label_patterns(characters):
    patterns = []
    for person in characters:
        found = re.fullmatch(r"(.+?)\s+(\d+)", str(person.get("label", "")).strip())
        if found and 0 < int(found[2]) <= len(ORDINALS):
            stem = re.escape(found[1])
            patterns.append(re.compile(rf"\b{stem}[\s_-]*{found[2]}\b|\bthe {ORDINALS[int(found[2]) - 1]} {stem}\b",
                                       re.IGNORECASE))
    return patterns


NEGATIVE_TAG = re.compile(r"\b(?:worst|low|bad)[ _]quality\b|\blowres\b", re.IGNORECASE)
COUNT_TAG = re.compile(r"(\d+)\+?(boy|girl|other)s?")


def _expected_counts(characters):
    """{"boy": n, "girl": n, "other": n} from the cast: men are boys, women are girls, anyone else other."""
    counts = {}
    for person in characters:
        kind = {"male": "boy", "female": "girl"}.get(person.get("gender"), "other")
        counts[kind] = counts.get(kind, 0) + int(person.get("count") or 1)
    return counts


def _anima_checks(target, brief, prompts):
    if target != "Anima" or not prompts:
        return {"count_tags_ok": None, "bad_tags": None}
    expected, good, bad = _expected_counts(brief.get("characters", [])), 0, 0
    for prompt in prompts:
        head = re.split(r"\r?\n[ \t]*\r?\n", prompt, maxsplit=1)[0]
        tags = [tag.strip().casefold().replace("_", " ") for tag in head.split(",") if tag.strip()]
        found = {}
        for tag in tags:
            if match := COUNT_TAG.fullmatch(tag.replace(" ", "")):
                found[match[2]] = found.get(match[2], 0) + int(match[1])
        good += found == expected and not (len(brief.get("characters", [])) > 1 and "solo" in tags)
        bad += bool(NEGATIVE_TAG.search(head) or re.search(r"(?<!score)_(?!up\b)", head))
    return {"count_tags_ok": round(good / len(prompts), 3), "bad_tags": round(bad / len(prompts), 3)}


def _echoed(request, prompts):
    """Share of the request's longer words that the prompts repeat word for word, averaged over the prompts."""
    words = {word for word in _words(request) if len(word) > 3}
    if not words or not prompts:
        return None
    return round(sum(len(words & _words(prompt)) / len(words) for prompt in prompts) / len(prompts), 3)


def _looks(scene):
    return tuple(sorted((label, person.get("skin", ""), person.get("hair", ""), person.get("build", ""))
                        for label, person in (scene.get("subjects") or {}).items()))


def case_checks(row, normalize=None):
    """{check: value} for one case run (None when a check does not apply)."""
    seconds = row.get("seconds")
    return {**_case_checks(row, normalize), "seconds": seconds}


def _case_checks(row, normalize=None):
    case, output = row["case"], row.get("output") or {}
    target = case.get("target", "Generic")
    if row["kind"] == "builder":
        prompt = output.get("prompt", "") if row.get("ok") else ""
        return {"written": 1.0 if prompt.strip() else 0.0, "format_ok": _format_ok(prompt, target, normalize) if prompt else 0.0,
                "cast_ok": None, "avoid_hits": None, "label_leaks": None, "repeated_looks": None,
                "repeated_places": None, "repeated_extras": None, "prompt_similarity": None,
                "words": len(prompt.split()) if prompt else None,
                "request_words_echoed": _echoed(case.get("idea", ""), [prompt] if prompt else [])}
    if not row.get("ok"):
        return {"written": 0.0, **{name: None for name, *_ in CHECKS if name != "written"}}
    brief, scenes = output.get("brief") or {}, output.get("scenes") or []
    prompts = [item.get("prompt", "") for item in output.get("prompts") or [] if item.get("prompt", "").strip()]
    requested = (brief.get("input") or {}).get("amount") or case.get("amount") or max(1, len(prompts))
    labels = {person["label"] for person in brief.get("characters", [])}
    avoid = [re.sub(r"^\s*(?:no|not|without|avoid|never)\s+", "", phrase, flags=re.IGNORECASE)
             for phrase in brief.get("avoid", [])]
    patterns = _label_patterns(brief.get("characters", []))
    pairs = list(itertools.combinations(scenes, 2))
    return {
        "written": round(len(prompts) / requested, 3),
        "format_ok": round(sum(bool(_format_ok(prompt, target, normalize)) for prompt in prompts) / len(prompts), 3)
        if prompts and normalize else None,
        "cast_ok": round(sum(set(scene.get("subjects") or {}) == labels for scene in scenes) / len(scenes), 3)
        if scenes else None,
        "actions_named": round(sum(all(re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])",
                                                 str(scene.get("actions") or ""), re.IGNORECASE) for label in labels)
                                   for scene in scenes) / len(scenes), 3) if scenes and labels else None,
        "avoid_hits": sum(bool(re.search(r"\b" + re.escape(word), prompt, re.IGNORECASE))
                          for prompt in prompts for word in avoid if word.strip()),
        "label_leaks": round(sum(any(pattern.search(prompt) for pattern in patterns) for prompt in prompts)
                             / len(prompts), 3) if prompts and patterns else None,
        "repeated_looks": _share(pairs, lambda a, b: bool(_looks(a)) and _looks(a) == _looks(b)) if labels else None,
        "repeated_places": _share(pairs, lambda a, b: _overlap(a.get("space"), b.get("space")) >= .7),
        "repeated_extras": _share(pairs, lambda a, b: _overlap(a.get("extras"), b.get("extras")) >= .7),
        "prompt_similarity": round(sum(_jaccard(a, b) for a, b in itertools.combinations(prompts, 2))
                                   / max(1, len(prompts) * (len(prompts) - 1) // 2), 3) if len(prompts) > 1 else None,
        "words": round(sum(len(prompt.split()) for prompt in prompts) / len(prompts)) if prompts else None,
        "request_words_echoed": _echoed(case.get("subject", ""), prompts),
        **_anima_checks(target, brief, prompts),
    }


AIM_STEP = 0.05  # an aim check must move at least this much to count


def side_checks(side, normalize=None):
    """{"cases", "totals", "noise"} for one side. noise: the standard error of each total, from how much a check
    moves between seeds of the same request."""
    cases = {f"{row['id']} / seed {row['seed']}": case_checks(row, normalize) for row in side["cases"]}
    # A Builder case writes one prompt per seed: its variety is how alike those prompts are across the seeds.
    builder = {}
    for row in side["cases"]:
        if row["kind"] == "builder" and row.get("ok") and (row.get("output") or {}).get("prompt", "").strip():
            builder.setdefault(row["id"], []).append(row["output"]["prompt"])
    for row in side["cases"]:
        found = builder.get(row["id"], [])
        if row["kind"] == "builder" and len(found) > 1:
            pairs = list(itertools.combinations(found, 2))
            cases[f"{row['id']} / seed {row['seed']}"]["prompt_similarity"] = round(
                sum(_jaccard(a, b) for a, b in pairs) / len(pairs), 3)
    by_case = {}
    for row in side["cases"]:
        by_case.setdefault(row["id"], []).append(cases[f"{row['id']} / seed {row['seed']}"])
    totals, noise = {}, {}
    for name, *_ in CHECKS:
        values = [value[name] for value in cases.values() if value.get(name) is not None]
        totals[name] = round(sum(values) / len(values), 3) if values else None
        # Standard error of the total: the spread between seeds of the same request, over the number of runs.
        deviations = [(run - sum(found) / len(found)) ** 2 for runs in by_case.values()
                      if len(found := [item[name] for item in runs if item.get(name) is not None]) > 1 for run in found]
        degrees = sum(len(found) - 1 for runs in by_case.values()
                      if len(found := [item[name] for item in runs if item.get(name) is not None]) > 1)
        noise[name] = round((sum(deviations) / degrees) ** .5 / len(values) ** .5, 3) if degrees and values else 0.0
    return {"cases": cases, "totals": totals, "noise": noise}


def compare(baseline, candidate):
    """[{check, about, kind, baseline, candidate, noise, change}] on the totals. change is "better", "worse",
    "same" (no real move: within noise, twice the combined standard error, or an aim check moving less than
    AIM_STEP) or "n/a"."""
    rows = []
    for name, about, kind, higher in CHECKS:
        old, new = baseline["totals"].get(name), candidate["totals"].get(name)
        # A real change is larger than twice the combined standard error of the two totals (about 95% sure).
        noise = round(2 * (((baseline.get("noise") or {}).get(name, 0.0)) ** 2
                           + ((candidate.get("noise") or {}).get(name, 0.0)) ** 2) ** .5, 3)
        if old is None or new is None:
            change = "n/a"
        elif kind == "info" or abs(new - old) <= max(noise, AIM_STEP if kind == "aim" else 1e-9):
            change = "same"
        else:
            change = "better" if (new > old) == higher else "worse"
        rows.append({"check": name, "about": about, "kind": kind, "baseline": old, "candidate": new, "noise": noise,
                     "change": change})
    return rows


def per_request(baseline, candidate):
    """{request id: {"baseline": {check: seed average}, "candidate": {...}}}."""
    def averages(side):
        grouped = {}
        for key, values in side["cases"].items():
            grouped.setdefault(key.rsplit(" / seed ", 1)[0], []).append(values)
        return {case: {name: (round(sum(found) / len(found), 3) if (found := [run[name] for run in runs
                                                                              if run.get(name) is not None]) else None)
                       for name, *_ in CHECKS} for case, runs in grouped.items()}
    old, new = averages(baseline), averages(candidate)
    return {case: {"baseline": old.get(case, {}), "candidate": new.get(case, {})} for case in new}
