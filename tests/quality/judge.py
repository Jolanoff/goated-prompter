"""Layer 3b: blind side-by-side review of the old and the new outputs.

Every case and seed becomes one pair. Which side is A and which is B is decided at random and kept in key.json, so
whoever judges (you, an agent or a model) cannot know which output is new. A review names its reviewer and kind:
"human" and "independent" reviews count as evidence, "self_review" (the same local model judging its own output) is
shown as a hint only.
"""

import json
import random

DIMENSIONS = {
    "fidelity": "Keeps everything the request asks for: who appears and how many, what they do, quoted text, rules.",
    "physics": "Every body, pose, contact and support is physically possible, with nothing merged or impossible.",
    "separation": "Each person is clearly told apart, and every body part named belongs to someone.",
    "show": "Abstract words of the request (roles, feelings, themes) are shown as visible signs, not just named.",
    "creativity": "Interesting, unexpected but faithful choices; the images of a set differ from each other.",
    "director": "Emphasizes what the selected Director asks for.",
    "format": "Written the way the target model needs (structure, syntax, length).",
}
GUARD = ("fidelity", "physics")  # a loss here makes a change worse, whatever else improved
RUBRIC = ("You compare two outputs, A and B, made from the same request and settings by two versions of a prompt "
          "writer. Judge only what is written. For each dimension answer which output is better, or tie when they "
          "are equally good or the dimension does not apply.\n" + "\n".join(f"- {name}: {about}"
                                                                           for name, about in DIMENSIONS.items()))
REVIEW_KINDS = ("human", "independent", "self_review", "exploratory")
COUNTING_KINDS = ("human", "independent")


def _render(row):
    """One side's output as plain text for a reviewer."""
    if not row.get("ok"):
        where = f" after: {row['log'][-1].strip()}" if row.get("log") else ""
        return f"(failed: {row.get('error', 'no output')}{where})"
    output = row["output"]
    if row["kind"] == "builder":
        return output.get("prompt", "")
    parts = []
    prompts = {item.get("slot"): item for item in output.get("prompts") or []}
    for scene in output.get("scenes") or []:
        slot = scene.get("slot")
        prompt = prompts.get(slot, {})
        parts.append(f"Image {slot}\nScene actions: {scene.get('actions', '')}\nPrompt: "
                     + (prompt.get("prompt") or f"(not written: {prompt.get('error', 'missing')})"))
    return "\n\n".join(parts) or "(no images)"


def _settings_line(case):
    keys = ("kind", "target", "director", "creativity", "length", "style", "mode", "amount", "nsfw")
    return ", ".join(f"{key}: {case[key]}" for key in keys if key in case)


def build_packet(baseline, candidate, seed=0):
    """(packet, key): the blind pairs, and which side each A and B really is."""
    rng = random.Random(seed)
    old = {(row["id"], row["seed"]): row for row in baseline["cases"]}
    pairs, key = [], {}
    for row in candidate["cases"]:
        before = old.get((row["id"], row["seed"]))
        if before is None:
            continue
        pair = f"{row['id']} / seed {row['seed']}"
        flip = rng.random() < .5
        a, b = (row, before) if flip else (before, row)
        key[pair] = {"A": "candidate" if flip else "baseline", "B": "baseline" if flip else "candidate"}
        request = row["case"].get("idea") or row["case"].get("subject", "")
        text = (f"REQUEST: {request}\nSETTINGS: {_settings_line(row['case'])}\n\n=== OUTPUT A ===\n{_render(a)}\n\n"
                f"=== OUTPUT B ===\n{_render(b)}")
        pairs.append({"pair": pair, "request": request, "settings": _settings_line(row["case"]),
                      "a": _render(a), "b": _render(b), "text": text})
    return {"dimensions": DIMENSIONS, "rubric": RUBRIC, "pairs": pairs}, key


def packet_markdown(packet):
    lines = ["# Blind review", "", RUBRIC, "",
             "Write your answers in review.json (a template is next to this file): for each pair and dimension "
             "\"A\", \"B\" or \"tie\". Set reviewer and review_kind (human, independent, self_review or exploratory).", ""]
    for pair in packet["pairs"]:
        lines += [f"## {pair['pair']}", "", f"**Request:** {pair['request']}  ", f"**Settings:** {pair['settings']}", "",
                  "### Output A", "", "```", pair["a"], "```", "", "### Output B", "", "```", pair["b"], "```", ""]
    return "\n".join(lines)


def review_template(packet):
    return {"reviewer": "", "review_kind": "", "pairs": {pair["pair"]: {name: "" for name in packet["dimensions"]}
                                                         for pair in packet["pairs"]}}


def unblind(review, key):
    """{dimension: {"wins", "losses", "ties", "answered"}} for the candidate, plus whether the review counts."""
    result = {name: {"wins": 0, "losses": 0, "ties": 0} for name in DIMENSIONS}
    for pair, answers in (review.get("pairs") or {}).items():
        sides = key.get(pair)
        if not sides:
            continue
        for name, answer in (answers or {}).items():
            if name not in result or answer not in ("A", "B", "tie"):
                continue
            if answer == "tie":
                result[name]["ties"] += 1
            elif sides[answer] == "candidate":
                result[name]["wins"] += 1
            else:
                result[name]["losses"] += 1
    kind = review.get("review_kind", "")
    return {"dimensions": result, "reviewer": review.get("reviewer", ""), "kind": kind,
            "counts": kind in COUNTING_KINDS and bool(review.get("reviewer"))}


def leaning(tally):
    """"better", "worse" or "same" for one dimension: a clear majority of the answered pairs, at least two."""
    wins, losses = tally["wins"], tally["losses"]
    answered = wins + losses + tally["ties"]
    margin = max(2, round(.2 * answered))
    if wins - losses >= margin:
        return "better"
    if losses - wins >= margin:
        return "worse"
    return "same"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
