"""Nonblocking lexical idea-diversity hints; no scene or final-prompt evaluator."""

import re


_CONCEPT_FAMILIES = {
    "juggle": r"juggl\w*",
    "failure": r"fail\w*|dropp\w*|drops?|spill\w*|fumbl\w*|losing|lost",
    "fruit": r"oranges?|apples?|pears?|bananas?|fruits?",
    "walk": r"walk\w*|stroll\w*|stepp\w*|steps?|strid\w*|trudg\w*",
    "run": r"runn\w*|runs?|sprint\w*|dash\w*|jogg\w*",
    "laugh": r"laugh\w*|chuckl\w*|giggl\w*",
    "wear": r"wear\w*|dressed|donning",
    "catch": r"catch\w*|catches|caught|snatch\w*|intercept\w*",
    "read": r"read\w*",
}


def idea_concepts(text):
    text = text.casefold()
    for family, pattern in _CONCEPT_FAMILIES.items():
        text = re.sub(r"\b(?:" + pattern + r")\b", family, text)
    text = re.sub(r"\b(?:trying|attempting|attempt|control|airborne|air|flight|three|two|one|and|to)\b", "", text)
    text = re.sub(r"\b(?:at (?:night|dawn|dusk|sunset)|in (?:warm|soft|bright) light|from a low angle)\b", "", text)
    event = re.split(r";|\b(?:under|with)\s+(?:soft|bright|diffuse|warm|dramatic|overcast)\b", text, maxsplit=1)[0]
    event = re.split(r"\b(?:in|at|beside|against)\s+(?:a |an |the )?(?:bedroom|kitchen|office|park|studio|room|interior)\b", event, maxsplit=1)[0]
    stop = {"a", "an", "the", "she", "he", "they", "her", "his", "their", "woman", "man",
            "person", "character", "is", "are", "and", "while", "with", "in", "on", "at", "to",
            "of", "for", "by", "from", "as", "it", "its", "outside", "indoors", "outdoors"}
    return {word for word in re.findall(r"[a-z0-9]+", event) if word not in stop}


def analyze_idea_diversity(data, rows):
    rows = [row for row in rows if row.get("idea", "").strip()]
    records = {row["index"]: {"index": row["index"], "issues": []} for row in rows}
    guided = data.get("source_mode") == "guided"
    scope = (data.get("subject", "") + " " + data.get("constraints", "")).casefold()
    expression_scope = bool(re.search(r"(?:different|various|funny|facial)\s+(?:facial\s+)?expressions\b", scope))
    for position, left in enumerate(rows):
        for right in rows[position + 1:]:
            if guided and (not left.get("input") or not right.get("input")
                           or " ".join(left["input"].split()) == " ".join(right["input"].split())):
                continue
            a, b = [" ".join(row["idea"].casefold().split()) for row in (left, right)]
            aw, bw = [idea_concepts(text) for text in (a, b)]
            facial = all(re.search(r"\b(?:face|facial|expression|expressions)\b", text) for text in (a, b))
            code = None
            if a == b:
                code = "exact_duplicate_idea"
            elif facial and expression_scope:
                continue
            elif (aw and aw == bw and not facial) or (min(len(aw), len(bw)) >= 3 and len(aw & bw) / len(aw | bw) >= .85):
                code = "similar_idea_category"
            if code:
                for current, other in ((left, right), (right, left)):
                    records[current["index"]]["issues"].append({"code": code, "severity": "warning", "related": other["index"],
                        "message": f"Idea may repeat the concept of idea {other['index']}. Check distinct activities, not just presentation differences."})
    return {"ideas": list(records.values()), "method": "concept-aware lexical hints; not semantic verification"}


# An idea where the cast only watches, looks at or admires something is passive: one per batch
# at most. The main clause decides; standing, sitting or holding hands while watching counts too.
_PASSIVE = re.compile(r"\b(?:watch\w*|look(?:s|ing)? (?:at|out|on|over)|gaz\w*|admir\w*|observ\w*|star(?:e|es|ing)|"
                      r"overlook\w*|sightsee\w*|views?|vista|scenery|in awe|taking in)\b")
_STANCE = re.compile(r"\b(?:stand\w*|sit|sits|sitting|seated|lean\w*|rest\w*|kneel\w*|wait\w*|hold(?:s|ing)? hands)\b")


def passive_idea(text):
    text = " ".join(str(text or "").casefold().split())
    parts = re.split(r"\bwhile\b|\bas\b|,|;", text, maxsplit=1)
    main, rest = parts[0], parts[1] if len(parts) > 1 else ""
    if _PASSIVE.search(main):
        return True
    return bool(_STANCE.search(main) and _PASSIVE.search(rest))


_MOTIF_STOP = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "from", "into", "onto",
               "while", "as", "her", "his", "their", "its", "she", "he", "they", "is", "are", "one", "two", "three",
               "each", "other", "both", "together", "small", "large", "little", "big", "old", "year", "yo"}


def _bigrams(text, ignore):
    words = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    keep = lambda word: word not in _MOTIF_STOP and word not in ignore and not any(char.isdigit() for char in word)
    return {(left, right) for left, right in zip(words, words[1:]) if keep(left) and keep(right)}


def repeated_motif(text, others, ignore=()):
    """A two-word place, prop or activity ("vending machine") already in two other ideas of the batch."""
    ignore = set(ignore)
    counts = {}
    for other in others:
        for pair in _bigrams(other, ignore):
            counts[pair] = counts.get(pair, 0) + 1
    repeated = sorted(" ".join(pair) for pair in _bigrams(text, ignore) if counts.get(pair, 0) >= 2)
    return repeated[0] if repeated else None
