"""Lexical idea checks: diversity hints, passive ideas, and sexual or adults-only requests."""

import re

from ...presets import get_director_preset
from .director import director_fixes_shot


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
                      r"marvel\w*|overlook\w*|sightsee\w*|views?|vista|scenery|in awe|taking in|"
                      r"(?:shar|enjoy|spend)\w* a (?:quiet|peaceful|calm|still|tender|silent) moment|"
                      r"(?:walk|stroll|wander)\w* (?:together )?(?:through|along|past|across|down|around|among))\b")
_STANCE = re.compile(r"\b(?:stand\w*|sit|sits|sitting|seated|lean\w*|rest\w*|kneel\w*|wait\w*|hold(?:s|ing)? hands|"
                     r"paus\w*|linger\w*|react\w*)\b")
# After a stance, seeing something or a show put on by others is still only watching.
_SEEN = re.compile(r"\b(?:see|sees|seeing|spot\w*|performance|parade|fireworks|show)\b")


def passive_request(data):
    """True when the user asked for watching or strolling, or the Director fixes a posed shot such as a
    mirror selfie, so it is not limited."""
    return (passive_idea(" ".join(str(data.get(key) or "") for key in ("subject", "constraints")))
            or director_fixes_shot(data))


def passive_idea(text):
    text = " ".join(str(text or "").casefold().split())
    parts = re.split(r"\bwhile\b|\bas\b|,|;", text, maxsplit=1)
    main, rest = parts[0], parts[1] if len(parts) > 1 else ""
    if _PASSIVE.search(main):
        return True
    return bool(_STANCE.search(main) and (_PASSIVE.search(rest) or _SEEN.search(main + " " + rest)))


# Sexual requests get act-focused directions, and everyone in them must be an adult. The request,
# rules, guided inputs, cast and selected Director all count, since any of them can make a batch sexual.
_SEXUAL = re.compile(r"\b(?:sex|sexual\w*|nsfw|porn\w*|explicit|erotic\w*|nude|nudity|naked|fuck\w*|blowjob\w*|"
                     r"handjob\w*|oral(?! (?:presentations?|exams?|examinations?|hygiene|history|health|surgery|traditions?|reports?|arguments?))|anal|penetrat\w*|masturbat\w*|cum|cums|cumming|cumshot\w*|orgasm\w*|cocks?|"
                     r"dicks?|pussy|pussies|boobs?|tits|nipples?|genitals?|horny|aroused)\b")
_SUGGESTIVE = re.compile(r"\b(?:lingerie|boudoir|seductive\w*|sensual\w*|undress\w*|striptease|strippers?|"
                         r"strip(?:s|ped|ping)? (?:off|down|naked|nude)|topless|bottomless)\b")
_MINOR = re.compile(r"\b(?:child|children|childlike|kids?|minors?|underage\w*|teens?|teenage\w*|preteens?|"
                    r"tweens?|loli\w*|shota\w*|schoolgirls?|schoolboys?|toddlers?|infants?|bab(?:y|ies)|"
                    r"(?:elementary|primary|middle|high|junior high) school\w*|little (?:girl|boy)s?|young (?:girl|boy)s?|"
                    r"(?:[1-9]|1[0-7])\s*(?:yo|y/o|-?years?[- ]old|-year-old))\b")
ADULTS_ONLY = ("Sexual content can only show adults. Remove anything that makes a character a child or teen "
               "(age under 18, school, childlike body); describe every character as an adult.")


def _request_text(data):
    brief = data.get("_confirmed_intent") or {}
    parts = [str(data.get(key) or "") for key in ("subject", "constraints", "inputs", "trigger", "custom_type")]
    parts += [str(item.get(key) or "") for item in brief.get("characters") or () if isinstance(item, dict)
              for key in ("name", "traits")]
    parts += [str(brief.get(field) or "") for field in ("requested_generation", "dataset_contents")]
    parts += [str(item.get("text") or "") for field in ("hard", "soft", "action_options", "interactions")
              for item in brief.get(field) or () if isinstance(item, dict)]
    parts.append(get_director_preset(data.get("director_preset")).instructions)
    return " ".join(parts).casefold()


def sexual_request(data):
    return bool(_SEXUAL.search(_request_text(data)))


def minor_reference(text):
    """The first wording that makes someone a child or teen, or None."""
    match = _MINOR.search(str(text or "").casefold())
    return match.group() if match else None


def adults_only_error(data):
    """For a sexual or suggestive batch, the reason it cannot run when anyone in it is under 18."""
    text = _request_text(data)
    if (_SEXUAL.search(text) or _SUGGESTIVE.search(text)) and (word := minor_reference(text)):
        return f'{ADULTS_ONLY} ("{word}")'
    return None
