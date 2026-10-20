"""Layer 1: collisions inside one copy of the code, and what changed between two copies.

A collision is a guide using the words of a decision another setting owns (owners.json), or the same rule written in
two places. The audit reports; accepted exceptions live in audit_allow.json with the reason they are fine.
"""

import difflib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DUPLICATE_SIMILARITY = 0.75  # words two sentences share out of all their words, to count as the same rule
DUPLICATE_MIN_WORDS = 8


def load_rules():
    owners = json.loads((HERE / "owners.json").read_text(encoding="utf-8"))
    allowed = json.loads((HERE / "audit_allow.json").read_text(encoding="utf-8"))["allowed"]
    return owners, allowed


def sentences(text):
    """The text split into sentences (and lines), whitespace normalised."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
    return [" ".join(part.split()) for part in parts if part.strip()]


def _words(sentence):
    return set(re.findall(r"[a-z0-9]+", sentence.casefold()))


def _allowed(allowed, owner, name, decision, sentence):
    return any(item["owner"] == owner and item.get("name", name) == name and item["decision"] == decision
               and item["phrase"].casefold() in sentence.casefold() for item in allowed)


def collisions(dump, rules=None):
    """[{owner, name, decision, word, sentence}] for every sentence that speaks for a decision its guide does not own."""
    owners, allowed = rules or load_rules()
    patterns = {decision: [re.compile(r"\b" + word, re.IGNORECASE) for word in words]
                for decision, words in owners["decisions"].items()}
    found = []
    for owner, texts in dump["owners"].items():
        own = set(owners["owners"].get(owner, []))
        for name, text in texts.items():
            for sentence in sentences(text):
                for decision, regexes in patterns.items():
                    if decision in own:
                        continue
                    match = next((m for regex in regexes if (m := regex.search(sentence))), None)
                    if match and not _allowed(allowed, owner, name, decision, sentence):
                        found.append({"owner": owner, "name": name, "decision": decision, "word": match[0],
                                      "sentence": sentence})
    return found


def _allowed_pair(allowed, owner_a, owner_b, sentence):
    return any(item.get("decision") == "duplicate" and {item["owner"], item.get("other")} == {owner_a, owner_b}
               and item["phrase"].casefold() in sentence.casefold() for item in allowed)


def duplicates(dump, rules=None):
    """The same rule written in two guides of different owners: [{a, b, sentence_a, sentence_b, similarity}]."""
    _, allowed = rules or load_rules()
    rows = [(owner, name, sentence, _words(sentence)) for owner, texts in dump["owners"].items()
            for name, text in texts.items() for sentence in sentences(text)
            if len(sentence.split()) >= DUPLICATE_MIN_WORDS]
    found, seen = [], set()
    for i, (owner_a, name_a, sentence_a, words_a) in enumerate(rows):
        for owner_b, name_b, sentence_b, words_b in rows[i + 1:]:
            if owner_a == owner_b or (sentence_a, sentence_b) in seen or _allowed_pair(allowed, owner_a, owner_b, sentence_a):
                continue
            similarity = len(words_a & words_b) / max(1, len(words_a | words_b))
            if similarity >= DUPLICATE_SIMILARITY:
                seen.add((sentence_a, sentence_b))
                found.append({"a": f"{owner_a} / {name_a}", "b": f"{owner_b} / {name_b}", "sentence_a": sentence_a,
                              "sentence_b": sentence_b, "similarity": round(similarity, 2)})
    return found


def _key(item):
    return (item.get("owner"), item.get("name"), item.get("decision"), item.get("sentence"))


def compare_findings(baseline, candidate):
    """(new, fixed, remaining) between two lists of findings."""
    old, new = {_key(item): item for item in baseline}, {_key(item): item for item in candidate}
    return ([new[key] for key in new if key not in old], [old[key] for key in old if key not in new],
            [new[key] for key in new if key in old])


def changes(baseline, candidate):
    """What changed in each guide and in each assembled instruction: [{where, added, removed}] (sentences)."""
    rows = []

    def diff(where, old, new):
        if old == new:
            return
        a, b = sentences(old), sentences(new)
        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        added, removed = [], []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                removed += a[i1:i2]
                added += b[j1:j2]
        rows.append({"where": where, "added": added, "removed": removed})

    for owner in sorted(set(baseline["owners"]) | set(candidate["owners"])):
        old, new = baseline["owners"].get(owner, {}), candidate["owners"].get(owner, {})
        for name in sorted(set(old) | set(new)):
            diff(f"{owner} / {name}", old.get(name, ""), new.get(name, ""))
    assembled = []
    for name in sorted(set(baseline["assembled"]) | set(candidate["assembled"])):
        old, new = baseline["assembled"].get(name, ""), candidate["assembled"].get(name, "")
        if old != new:
            assembled.append(name)
    return rows, assembled


def summary(dump):
    """Size of each guide in words, and the largest assembled instruction."""
    sizes = {f"{owner} / {name}": len(text.split()) for owner, texts in dump["owners"].items()
             for name, text in texts.items()}
    biggest = max(dump["assembled"].items(), key=lambda item: len(item[1].split()), default=("", ""))
    return {"guide_words": sizes, "largest_instruction": {"settings": biggest[0], "words": len(biggest[1].split())},
            "errors": {name: text for name, text in dump["assembled"].items() if text.startswith("ERROR:")}}
