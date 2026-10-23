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
    ("mouth_mixed", "share of prompts with a sentence that puts a mouth on a buttock or anus and genitals together (read as genitals where the tongue is)", "aim", False),
    ("genitals_conflict", "share of scenes that give someone's genitals two places: hanging free, pressed or tucked "
     "somewhere while the act puts them in another person, or two such places at once (drawn twice or floating)",
     "aim", False),
    ("contact_misplaced", "share of scenes where a person being entered rests their buttocks or hips against the other "
     "person's chest, face or another part away from the hips (both cannot happen at once)", "aim", False),
    ("tags_misfit", "Anima: share of tag lines that tag an act the scene does not show (\"sex\" for touching) or a tag "
     "beside its opposite (\"aroused, unaroused\")", "aim", False),
    ("template_leaks", "share of scenes with a pack label or an unfilled [slot] left in their text", "guard", False),
    ("repeated_acts", "share of image pairs built on the same Actions & Poses entry (without entries: near-identical "
     "actions)", "aim", False),
    ("opening_conflicts", "share of scenes that contradict themselves about who is in whose mouth or anus (the "
     "actions and positions disagree, or the mouth is covered while something is in it)", "aim", False),
    ("subject_parts_missing", "share of the body parts the request names that no scene's actions or positions mention",
     "aim", False),
    ("pose_act_gap", "share of scenes where two people the act joins are named in neither one's position", "aim", False),
    ("parts_out_of_frame", "share of scenes where the act uses a lower-body part its owner's visible parts leave out",
     "aim", False),
    ("shape_misfit", "with an aspect ratio chosen: share of scenes whose arrangement does not suit a tall or wide frame "
     "(a text hint; the picture decides)", "aim", False),
    ("words", "average prompt length in words", "info", True),
    ("seconds", "average time per run in seconds (more retries cost time)", "info", False),
    ("redone", "average images asked again per run (each one costs writing time)", "info", False),
    ("request_words_echoed", "share of the request's own words repeated in the prompts (told, not shown; a hint)", "info", False),
    ("shot_named", "share of prompts that name a shot size instead of showing the framing (a hint)", "info", False),
    ("extent_shown", "share of prompts that say how far bodies reach in the frame and what is around them (a hint)", "info", True),
)

# Framing hints: a named shot size ("medium shot") versus framing shown through what is visible (feet on the floor,
# knees on a mattress, something in the foreground or background).
SHOT_NAME = re.compile(r"\b(?:(?:extreme |medium |full[- ]body |wide |long |cowboy )?close[- ]?up|(?:medium|wide|long|"
                       r"full[- ]body|cowboy|establishing|two|three)[- ]shot|mid[- ]shot)\b", re.IGNORECASE)
# A log line of an image the scene writer asks for again (scenes/writer.py rejected_note).
REDONE = re.compile(r"\bImage \d+ is asked again\b")
# A sentence with a mouth at someone's rear and genitals in it: the image puts the genitals at the rear.
MOUTH_ON_REAR = re.compile(r"\b(?:mouth|lips?|tongue)\b[^.,;]{0,40}?\b(?:anus|buttocks?|rear)\b",
                           re.IGNORECASE)
GENITALS = re.compile(r"\b(?:penis|testicles|genitals)\b", re.IGNORECASE)
EXTENT = re.compile(r"\b(?:feet|foot|toes|ankles?|knees?|shins?|soles?|floor|ground|mattress|from (?:the )?head|"
                    r"foreground|background)\b", re.IGNORECASE)


def _framing(prompts):
    if not prompts:
        return {"shot_named": None, "extent_shown": None}
    return {"shot_named": round(sum(bool(SHOT_NAME.search(prompt)) for prompt in prompts) / len(prompts), 3),
            "extent_shown": round(sum(len(set(match.casefold() for match in EXTENT.findall(prompt))) >= 2
                                      for prompt in prompts) / len(prompts), 3)}


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
    """{"boy": n, "girl": n, "other": n, "open": n} from the cast: men are boys, women are girls, anyone else other; a
    person the cast gives no gender is open (the scene decides, so any count tag fits them)."""
    counts = {}
    for person in characters:
        kind = {"male": "boy", "female": "girl"}.get(person.get("gender"), "other" if person.get("gender") else "open")
        counts[kind] = counts.get(kind, 0) + int(person.get("count") or 1)
    return counts


def _counts_fit(found, expected):
    """Whether a tag line's count tags fit the cast: everyone counted once, people of a given gender as that gender."""
    fixed = {kind: number for kind, number in expected.items() if kind != "open"}
    return (sum(found.values()) == sum(expected.values())
            and all(found.get(kind, 0) >= number for kind, number in fixed.items())
            and set(found) <= set(fixed) | ({"boy", "girl", "other"} if expected.get("open") else set()))


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
        good += _counts_fit(found, expected) and not (len(brief.get("characters", [])) > 1 and "solo" in tags)
        bad += bool(NEGATIVE_TAG.search(head) or re.search(r"(?<!score)_(?!up\b)", head))
    return {"count_tags_ok": round(good / len(prompts), 3), "bad_tags": round(bad / len(prompts), 3)}


def _echoed(request, prompts):
    """Share of the request's longer words that the prompts repeat word for word, averaged over the prompts."""
    words = {word for word in _words(request) if len(word) > 3}
    if not words or not prompts:
        return None
    return round(sum(len(words & _words(prompt)) / len(words) for prompt in prompts) / len(prompts), 3)


def _mouth_mixed(prompt):
    """Whether one sentence of the prompt puts a mouth on a buttock or anus and also names genitals."""
    return any(MOUTH_ON_REAR.search(part) and GENITALS.search(part)
               for part in re.split(r"(?<=[.!?])\s+|\n+", prompt))


# A position that puts a person's genitals somewhere other than where the act puts them.
GENITALS_PLACED = re.compile(r"\bhanging free\b|\b(?:his|her|their) (?:penis|genitals) (?:is|are) "
                             r"(pressed|tucked|resting|hanging)\b", re.IGNORECASE)
ENTERS = r"(?:penis|shaft|genitals)\b[^,;.]{0,20}?\b(?:in|inside|into|enter\w*|penetrat\w*)\b"


def _genitals_conflict(scene):
    """Whether a person's genitals get two places: their own position says they hang free, or are tucked or resting
    somewhere, while the actions or a position put them in someone ("man 1's penis in man 2's mouth"); or their
    position gives them two such places ("pressed against man 2's, tucked under him"). Pressed against a body while
    inside it is one place (the testicles rest there)."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    every = " ".join([str(scene.get("actions") or "")] + [str(text) for text in position.values()])
    for label, text in position.items():
        placed = {{"hanging": "free"}.get(word, word) for word in
                  ((match[1] or "free").casefold() for match in GENITALS_PLACED.finditer(str(text)))}
        used = (re.search(_named(label) + r"(?:'s|’s) " + ENTERS, every, re.IGNORECASE)
                or re.search(r"\b(?:his|her|their) " + ENTERS, str(text), re.IGNORECASE))
        if len(placed) > 1 or (used and placed - {"pressed"}):
            return True
    return False


# Where a person being entered meets the other person's body; any other part is too far from the hips.
MEETS = {"hips", "hip", "groin", "pelvis", "thighs", "thigh", "lap", "crotch", "waist", "belly", "stomach", "abdomen",
         "genitals", "penis", "testicles"}


def _contact_misplaced(scene, labels):
    """Whether a person whose anus or vagina the act enters rests their buttocks or hips against the entering person's
    chest, face or another part away from the hips ("his buttocks pressed against man 2's chest")."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    every = " ".join([str(scene.get("actions") or "")] + [str(text) for text in position.values()])
    rests = r"\b(?:buttocks|hips)\b[^,;.]{0,30}?\bagainst "
    for giver, taker in itertools.permutations(labels, 2):
        if not re.search(_named(giver) + r"(?:'s|’s) " + ENTERS + r"[^,;.]{0,20}?" + _named(taker)
                         + r"(?:'s|’s) (?:anus|vagina)\b", every, re.IGNORECASE):
            continue
        parts = re.findall(r"\b(?:his|her|their|" + re.escape(taker) + r"(?:'s|’s)) " + rests + _named(giver)
                           + r"(?:'s|’s) (\w+)", str(position.get(taker) or ""), re.IGNORECASE)
        parts += re.findall(_named(taker) + r"(?:'s|’s) " + rests + r"(?:his|her|their) (\w+)",
                            str(position.get(giver) or ""), re.IGNORECASE)
        if any(part.casefold() not in MEETS for part in parts):
            return True
    return False


# Anima act tags that need something entering an anus or vagina in the scene.
ACT_TAGS = {"sex", "anal", "vaginal", "penetration"}
ENTERED = re.compile(r"\b(?:penis|toy|dildo|strap-on)\b[^,;.]{0,30}?\b(?:in|inside|into|enter\w*|penetrat\w*)\b"
                     r"[^,;.]{0,30}?\b(?:anus|vagina)\b", re.IGNORECASE)


def _tags_misfit(prompt, scene):
    """Whether an Anima tag line tags an act its scene does not show, or a tag beside its opposite (one person each;
    a tag line cannot say whose)."""
    head = re.split(r"\r?\n[ \t]*\r?\n", prompt, maxsplit=1)[0]
    tags = {tag.strip().casefold() for tag in head.split(",") if tag.strip()}
    shown = " ".join(_strings({"actions": scene.get("actions"), "position": scene.get("position")})) if scene else ""
    return (any("un" + tag in tags for tag in tags)
            or bool(scene and tags & ACT_TAGS and not ENTERED.search(shown)))


# Body parts the checks below read in a scene's own words (plain anatomical names).
BODY_PARTS = ("penis", "testicles", "anus", "mouth", "throat", "buttocks", "vagina", "breasts")
LOWER_PARTS = ("penis", "testicles", "anus", "buttocks", "vagina")
LOWER_SHOWN = re.compile(r"\b(?:entire|whole|full|hips?|groin|waist|lower|legs?|thighs?|pelvis|genitals|penis|testicles|"
                         r"anus|buttocks|rear|vagina)\b", re.IGNORECASE)
SLOT = re.compile(r"\[[^\]\n]{2,}\]")
ENTRY_HEAD = re.compile(r"(?:^|;\s*)([^:;\n]{3,80}):\s*([^,;\n]*)")
HORIZONTAL = re.compile(r"\b(?:left|right|centre|center|beside|side by side)\b", re.IGNORECASE)
VERTICAL = re.compile(r"\b(?:above|below|top|bottom|stacked|underneath|on top)\b", re.IGNORECASE)
LOWERED = re.compile(r"\b(?:kneel\w*|sit\w*|seated|lying|lies|lie|bent|crouch\w*|squat\w*|recline\w*|suspended)\b",
                     re.IGNORECASE)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _named(label):
    return r"(?<![\w-])" + re.escape(label) + r"(?![\w-])"


def _template_leak(scene, labels):
    """Whether the scene still holds an unfilled [slot], or an act copied from a pack entry with its placeholder people
    ("two tops: one person bound, ..."): a name and a colon followed by wording that names nobody of the cast."""
    # The "entry" field holds the pack's own text, slots and all, on purpose.
    if any(SLOT.search(text) for text in _strings({key: value for key, value in scene.items() if key != "entry"})):
        return True
    named = lambda text: any(re.search(_named(label), text, re.IGNORECASE) for label in labels)
    return any(not named(name) and not named(wording)
               for name, wording in ENTRY_HEAD.findall(str(scene.get("actions") or "")))


def _opening_conflict(scene, labels):
    """Whether the scene contradicts itself about who is in whose mouth or anus (read the way the scene writer reads it)."""
    from goated_prompter.features.dataset.v2.scenes.checks import opening_conflicts
    return bool(opening_conflicts(scene, labels))


def _pose_act_gap(scene, labels):
    """Whether two people the actions join in one clause are named in neither one's position. Two people named together
    ("man 3 and man 4 are waiting", "man 2 and man 3 are holding man 1 up", "stroking man 3's and man 4's penises")
    share a role and do nothing to each other, so that pair is not joined; each is still checked against whoever they
    act on or who acts on them."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    again = "(?=\\s+(?:" + "|".join(re.escape(label) for label in labels) + r")['’]s)"  # "... and man 2's penis ..."
    anyone = "(" + "|".join(re.escape(label) for label in labels) + ")"
    for clause in re.split(r"[;,]|\bwhile\b|\bas\b|\bthen\b|\band\b" + again, str(scene.get("actions") or ""),
                           flags=re.IGNORECASE):
        named = [label for label in labels if re.search(_named(label), clause, re.IGNORECASE)]
        shared = [{match[1].casefold(), match[2].casefold()} for match in re.finditer(
            r"(?<![\w-])" + anyone + r"(?:['’]s)?\s+and\s+" + anyone + r"(?![\w-])", clause, re.IGNORECASE)]
        for first, second in itertools.combinations(named, 2):
            if {first.casefold(), second.casefold()} in shared:
                continue
            if not (re.search(_named(second), str(position.get(first) or ""), re.IGNORECASE)
                    or re.search(_named(first), str(position.get(second) or ""), re.IGNORECASE)):
                return True
    return False


def _out_of_frame(scene, labels):
    """Whether the actions use a lower-body part of a person whose position lists what is visible and leaves it out."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    actions = str(scene.get("actions") or "")
    for label in labels:
        shown = [part for part in str(position.get(label) or "").split(";") if "visible" in part.casefold()]
        uses = re.search(_named(label) + r"['’]s (?:" + "|".join(LOWER_PARTS) + r")\b|(?:in|inside|into|on|onto|against) "
                         r"(?:the )?(?:" + "|".join(LOWER_PARTS) + r") of " + _named(label)
                         + "|" + _named(label) + r"['’]s [\w ]{1,30}?(?:in|inside|into|onto|against) [\w ]{1,30}?"
                         r"(?:" + "|".join(LOWER_PARTS) + r")\b", actions, re.IGNORECASE)
        if shown and uses and not LOWER_SHOWN.search(shown[-1]):
            return True
    return False


def _shape_misfit(scene, labels, ratio):
    """Whether the people are arranged against the frame's shape: three or more side by side in a tall frame, or
    everyone standing with the whole body shown in a wide one. A hint from the text; the picture decides."""
    from goated_prompter.features.dataset.v2.aspect import aspect_shape
    shape = (aspect_shape(ratio) or ("",))[0]
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    texts = [str(position.get(label) or "") for label in labels]
    if shape == "tall":
        return (len(texts) >= 3 and all(HORIZONTAL.search(text) for text in texts)
                and not any(VERTICAL.search(text) for text in texts))
    if shape == "wide":
        return (len(texts) >= 2 and all(re.search(r"\bstanding\b", text, re.IGNORECASE) and not LOWERED.search(text)
                                        for text in texts)
                and any(re.search(r"\b(?:entire|whole|full) body\b", text, re.IGNORECASE) for text in texts))
    return False


def _parts_missing(subject, scenes):
    """The share of the body parts the request names that no scene mentions; None when it names none."""
    named = [part for part in BODY_PARTS if re.search(r"\b" + part + r"(?:s|es)?\b", subject or "", re.IGNORECASE)]
    if not named:
        return None
    shown = " ".join(str(scene.get("actions") or "") + " " + " ".join(map(str, (scene.get("position") or {}).values()))
                     for scene in scenes if isinstance(scene.get("position"), dict) or scene.get("actions"))
    return round(sum(not re.search(r"\b" + part + r"(?:s|es)?\b", shown, re.IGNORECASE) for part in named) / len(named), 3)


def _without(text, labels):
    """The text without the character labels, which every act names."""
    for label in sorted(labels, key=len, reverse=True):
        text = re.sub(_named(label), " ", str(text or ""), flags=re.IGNORECASE)
    return text


def _same_act(first, second):
    """Whether two images have the same act: the same entry when both name one (the act the writer was given), else
    actions that repeat each other almost word for word. Word overlap alone is too coarse: short acts share most of
    their few words ("penis", "mouth", "inside") even when the positions differ."""
    if first.get("entry") and second.get("entry"):
        return " ".join(first["entry"].split()).casefold() == " ".join(second["entry"].split()).casefold()
    labels = set(first.get("subjects") or {}) | set(second.get("subjects") or {})
    return _overlap(_without(first.get("actions"), labels), _without(second.get("actions"), labels)) >= .9


def _scene_share(scenes, test):
    """The share of scenes the test accepts; None without scenes or people."""
    return round(sum(bool(test(scene)) for scene in scenes) / len(scenes), 3) if scenes else None


def _looks(scene):
    return tuple(sorted((label, person.get("skin", ""), person.get("hair", ""), person.get("build", ""))
                        for label, person in (scene.get("subjects") or {}).items()))


def case_checks(row, normalize=None):
    """{check: value} for one case run (None when a check does not apply)."""
    seconds = row.get("seconds")
    redone = sum(bool(REDONE.search(line)) for line in row.get("log") or [] if isinstance(line, str))
    return {**_case_checks(row, normalize), "seconds": seconds, "redone": redone if row["kind"] != "builder" else None}


def _case_checks(row, normalize=None):
    case, output = row["case"], row.get("output") or {}
    target = case.get("target", "Generic")
    if row["kind"] == "builder":
        prompt = output.get("prompt", "") if row.get("ok") else ""
        return {"written": 1.0 if prompt.strip() else 0.0, "format_ok": _format_ok(prompt, target, normalize) if prompt else 0.0,
                "cast_ok": None, "avoid_hits": None, "label_leaks": None, "repeated_looks": None,
                "repeated_places": None, "repeated_extras": None, "prompt_similarity": None,
                "words": len(prompt.split()) if prompt else None,
                "request_words_echoed": _echoed(case.get("idea", ""), [prompt] if prompt else []),
                **_framing([prompt] if prompt else [])}
    if not row.get("ok"):
        return {"written": 0.0, **{name: None for name, *_ in CHECKS if name != "written"}}
    brief, scenes = output.get("brief") or {}, output.get("scenes") or []
    written = [item for item in output.get("prompts") or [] if item.get("prompt", "").strip()]
    prompts = [item["prompt"] for item in written]
    by_slot = {scene.get("slot"): scene for scene in scenes}
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
        "mouth_mixed": round(sum(_mouth_mixed(prompt) for prompt in prompts) / len(prompts), 3)
        if prompts and brief.get("path") == "nsfw_character" else None,
        "genitals_conflict": round(sum(_genitals_conflict(scene) for scene in scenes) / len(scenes), 3)
        if scenes and brief.get("path") == "nsfw_character" else None,
        "contact_misplaced": _scene_share(scenes, lambda scene: _contact_misplaced(scene, sorted(labels)))
        if brief.get("path") == "nsfw_character" else None,
        "tags_misfit": round(sum(_tags_misfit(item["prompt"], by_slot.get(item.get("slot"))) for item in written)
                             / len(written), 3) if target == "Anima" and written else None,
        "repeated_acts": _share(pairs, _same_act) if labels else None,
        "template_leaks": _scene_share(scenes, lambda scene: _template_leak(scene, labels)),
        "opening_conflicts": _scene_share(scenes, lambda scene: _opening_conflict(scene, sorted(labels))),
        "subject_parts_missing": _parts_missing(case.get("subject", ""), scenes) if scenes else None,
        "pose_act_gap": _scene_share(scenes, lambda scene: _pose_act_gap(scene, sorted(labels))),
        "parts_out_of_frame": _scene_share(scenes, lambda scene: _out_of_frame(scene, sorted(labels))),
        "shape_misfit": _scene_share(scenes, lambda scene: _shape_misfit(scene, sorted(labels), case.get("aspect")))
        if case.get("aspect") not in (None, "", "Auto") else None,
        "words": round(sum(len(prompt.split()) for prompt in prompts) / len(prompts)) if prompts else None,
        "request_words_echoed": _echoed(case.get("subject", ""), prompts),
        **_framing(prompts),
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
