"""Layer 3a: objective checks on one side's live outputs, computed the same way for the old and the new code.

Guard checks must never get worse (a lost or doubled image, a broken format, a leftover label). Aim checks show whether
the output got more varied, and know what the request keeps the same (the brief's kept): repeating a kept part is
asked for, never a repeat. Hint checks read word patterns (a body contact named in a sentence) and point at scenes to
read; they never decide the verdict. Info checks report time, retries and length. Each check is a number per case and a
total; nothing here judges taste, follows the request's meaning or looks at an image: those need a review.
"""

import itertools
import json
import re
import statistics

ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")
# (name, what it measures, "guard": must not get worse / "aim": should improve / "hint": a word-pattern pointer /
# "info": reported only, True when higher is better)
CHECKS = (
    ("written", "share of the requested images (the case's amount) that got a prompt, each image counted once",
     "guard", True),
    ("slot_problems", "scenes or prompts for an image that was not requested, an image given twice, or a requested "
     "image without a scene", "guard", False),
    ("format_ok", "share of prompts already in the target's final form (its format check accepts them unchanged)",
     "guard", True),
    ("known_changed", "share of scenes that give a known character a look of their own", "guard", False),
    ("sfw_leaks", "safe sets: share of prompts the app's own adult-content filter flags", "guard", False),
    ("cast_ok", "share of scenes that keep every person of the cast", "guard", True),
    ("actions_named", "share of scenes whose actions name every person (no copied placeholder people)", "guard", True),
    ("avoid_hits", "phrases the user ruled out that appear anyway", "guard", False),
    ("count_tags_ok", "Anima: share of tag lines whose people-count tags match the cast", "guard", True),
    ("bad_tags", "Anima: share of tag lines with underscores or low-quality tags in the positive prompt", "guard", False),
    ("label_leaks", "share of prompts that still call a person \"man 1\" or \"the first man\"", "guard", False),
    ("repeated_looks", "share of image pairs whose people look identical (known characters, who keep their looks, "
     "left out)", "aim", False),
    ("repeated_places", "share of image pairs set in the same place (when the request keeps the place: the same spot "
     "of it)", "aim", False),
    ("repeated_extras", "share of image pairs with the same props and signs (when the request keeps some of them: "
     "nearly identical extras)", "aim", False),
    ("prompt_similarity", "how alike the prompts are (a set's images; a Builder case's seeds), 0 to 1", "aim", False),
    ("mouth_mixed", "share of prompts with a sentence that names a mouth at someone's rear and genitals together "
     "(may read as genitals where the mouth is)", "hint", False),
    ("genitals_conflict", "share of scenes whose words give someone's genitals two places at once: a place of their "
     "own while the act puts them elsewhere, or two such places (drawn twice or floating)", "hint", False),
    ("contact_misplaced", "share of scenes where two people the act joins at the hips are placed touching at a part of "
     "the body away from the hips instead (both cannot happen at once)", "hint", False),
    ("tags_misfit", "Anima: share of tag lines that tag an entering act the scene does not show, or a tag beside its "
     "opposite (\"tired, untired\")", "aim", False),
    ("template_leaks", "share of scenes with a pack label or an unfilled [slot] left in their text", "guard", False),
    ("repeated_acts", "share of image pairs built on the same Actions & Poses entry (without entries: near-identical "
     "actions; when the request keeps the action: near-identical positions)", "aim", False),
    ("opening_conflicts", "share of scenes that contradict themselves about who is in whose mouth or anus (the "
     "actions and positions disagree, or the mouth is covered while something is in it)", "aim", False),
    ("subject_parts_missing", "share of the body parts the request names that an image's actions and positions leave "
     "out, image by image", "aim", False),
    ("pose_act_gap", "share of scenes where two people the act joins are named in neither one's position",
     "hint", False),
    ("parts_out_of_frame", "share of scenes where the act uses a lower-body part that neither its owner's visible "
     "parts nor the camera's words include", "hint", False),
    ("shape_misfit", "with an aspect ratio chosen: share of scenes that set three or more people side by side in a "
     "tall frame (a text hint; the picture decides)", "aim", False),
    ("words", "average prompt length in words", "info", True),
    ("seconds", "average time per run in seconds (more retries cost time)", "info", False),
    ("redone", "average images asked again per run (each one costs writing time)", "info", False),
    ("first_pass", "share of the requested images whose scene was accepted without being asked again", "info", True),
    ("request_words_echoed", "share of the request's own words repeated in the prompts (told, not shown; a hint)", "info", False),
    ("shot_named", "share of prompts that name a shot size instead of showing the framing (a hint)", "info", False),
    ("extent_shown", "share of prompts that say how far bodies reach in the frame and what is around them (a hint)", "info", True),
)

# Framing hints: a named shot size ("medium shot") versus framing shown through what is visible (feet on the floor,
# knees on a mattress, something in the foreground or background).
SHOT_NAME = re.compile(r"\b(?:(?:extreme |medium |full[- ]body |wide |long |cowboy )?close[- ]?up|(?:medium|wide|long|"
                       r"full[- ]body|cowboy|establishing|two|three)[- ]shot|mid[- ]shot)\b", re.IGNORECASE)
# A log line of an image the scene writer asks for again (scenes/writer.py rejected_note).
REDONE = re.compile(r"\bImage (\d+) is asked again\b")
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
    """Whether the prompt is already in the target's final form: the target's normalizer accepts it and returns it
    unchanged (a container it had to unwrap, or a caption it had to repair, is not final), spacing and JSON layout
    aside."""
    if normalize is None:
        return None
    if not prompt.strip():
        return False
    try:
        result = normalize(prompt, target, mode="Enhance")
    except (ValueError, TypeError, KeyError):
        return False
    return isinstance(result, str) and _same_text(result, prompt)


def _adult_text(prompt):
    """Whether the app's own adult-content filter flags the prompt's words (it reads requests; here a prompt)."""
    from goated_prompter.features.dataset.v2.safety import adult_content_request
    return adult_content_request({"subject": prompt}, include_director=False)


def _same_text(first, second):
    """Whether two prompts are the same text, ignoring spacing, or the same JSON value."""
    try:
        return json.loads(first) == json.loads(second)
    except ValueError:
        return " ".join(first.split()) == " ".join(second.split())


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
    somewhere, while the actions or a position put them into another person; or their position gives them two such
    places at once. Pressed against a body while inside it is one place."""
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
    """Whether a person the act enters rests their buttocks or hips against the other person's chest, face or another
    part away from the hips (MEETS)."""
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


# Anima act tags that name an entering act, so the scene must show one; a broad tag that covers any act never counts.
ACT_TAGS = {"anal", "vaginal", "penetration"}
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
CAMERA_LOWER = re.compile(r"\b(?:body|bodies|fully|knees?|shins?|ankles?|feet|foot|toes)\b", re.IGNORECASE)
SLOT = re.compile(r"\[[^\]\n]{2,}\]")
ENTRY_HEAD = re.compile(r"(?:^|;\s*)([^:;\n]{3,80}):\s*([^,;\n]*)")
HORIZONTAL = re.compile(r"\b(?:left|right|centre|center|beside|side by side)\b", re.IGNORECASE)
VERTICAL = re.compile(r"\b(?:above|below|top|bottom|stacked|underneath|on top)\b", re.IGNORECASE)


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
    ("man 3 and man 4 are waiting", "man 2 and man 3 are holding man 1 up", "touching man 3's and man 4's hands")
    share a role and do nothing to each other, so that pair is not joined; each is still checked against whoever they
    act on or who acts on them."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    again = "(?=\\s+(?:" + "|".join(re.escape(label) for label in labels) + r")['’]s)"  # "... and man 2's hand ..."
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
    """Whether the actions use a lower-body part of a person whose visible parts leave it out: what the person's position
    says is visible and every camera clause that names them are both read, and either one showing the lower body is
    enough. A camera clause that puts a lower-body part at the focus or centre shows the act for everyone."""
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    actions = str(scene.get("actions") or "")
    camera = re.split(r"[,;]\s*", str(scene.get("camera") or ""))
    if any(LOWER_SHOWN.search(part) and re.search(r"\b(?:focus\w*|connection|contact|cent(?:re|er)|point)\b", part,
                                                  re.IGNORECASE) for part in camera):
        return False
    for label in labels:
        shown = [part for part in str(position.get(label) or "").split(";") if "visible" in part.casefold()][-1:]
        # A camera clause also shows the lower body when it shows the whole body or parts below the hips.
        shown += [part if not CAMERA_LOWER.search(part) else "lower" for part in camera
                  if re.search(_named(label), part, re.IGNORECASE)]
        uses = re.search(_named(label) + r"['’]s (?:" + "|".join(LOWER_PARTS) + r")\b|(?:in|inside|into|on|onto|against) "
                         r"(?:the )?(?:" + "|".join(LOWER_PARTS) + r") of " + _named(label)
                         + "|" + _named(label) + r"['’]s [\w ]{1,30}?(?:in|inside|into|onto|against) [\w ]{1,30}?"
                         r"(?:" + "|".join(LOWER_PARTS) + r")\b", actions, re.IGNORECASE)
        if shown and uses and not any(LOWER_SHOWN.search(part) for part in shown):
            return True
    return False


def _shape_misfit(scene, labels, ratio):
    """Whether the people are arranged against the frame's shape: three or more side by side in a tall frame. A hint
    from the text; the picture decides. Standing people in a wide frame are not counted: many such images are right."""
    from goated_prompter.features.dataset.v2.aspect import aspect_shape
    shape = (aspect_shape(ratio) or ("",))[0]
    position = scene.get("position") if isinstance(scene.get("position"), dict) else {}
    texts = [str(position.get(label) or "") for label in labels]
    return (shape == "tall" and len(texts) >= 3 and all(HORIZONTAL.search(text) for text in texts)
            and not any(VERTICAL.search(text) for text in texts))


def _parts_missing(subject, scenes):
    """The share of (image, body part the request names) pairs where that image's actions and positions leave the part
    out: a part the request names belongs in every image, not in one. None when it names none."""
    named = [part for part in BODY_PARTS if re.search(r"\b" + part + r"(?:s|es)?\b", subject or "", re.IGNORECASE)]
    if not named or not scenes:
        return None
    text = lambda scene: " ".join([str(scene.get("actions") or ""), *map(str, (scene.get("position") or {}).values()
                                                                        if isinstance(scene.get("position"), dict) else ())])
    missing = sum(not re.search(r"\b" + part + r"(?:s|es)?\b", text(scene), re.IGNORECASE)
                  for scene in scenes for part in named)
    return round(missing / (len(scenes) * len(named)), 3)


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


def _looks(scene, known=frozenset()):
    """The people's looks (skin, hair, build and their distinguishing detail), without the known characters, whose
    looks come from their name and stay the same on purpose."""
    return tuple(sorted((label, *(str(person.get(field, "")) for field in ("skin", "hair", "build", "detail")))
                        for label, person in (scene.get("subjects") or {}).items()
                        if label not in known and isinstance(person, dict)))


def _same_arrangement(first, second):
    """Whether two images place the people the same way: their positions repeat each other almost word for word. Used
    when the request keeps one action, so the act repeats on purpose and only an identical pose is a repeat."""
    labels = set(first.get("subjects") or {}) | set(second.get("subjects") or {})
    arrangement = lambda scene: " ".join(map(str, (scene.get("position") or {}).values())
                                         if isinstance(scene.get("position"), dict) else ())
    return _overlap(_without(arrangement(first), labels), _without(arrangement(second), labels)) >= .9


NEGATION = re.compile(r"\b(?:no|not|without|never|avoid|free of)\b(?:\W+\w+){0,2}\W*$", re.IGNORECASE)


def _avoid_hits(prompts, avoid):
    """How many times a phrase the user ruled out is described anyway: a whole-word match that no "no", "not",
    "without" or "never" just before it negates."""
    return sum(any(not NEGATION.search(prompt[:match.start()])
                   for match in re.finditer(r"\b" + re.escape(phrase.strip()) + r"\b", prompt, re.IGNORECASE))
               for prompt in prompts for phrase in avoid if phrase.strip())


def _slot_of(item, index):
    """An image's slot number (its position in the list when it gives none)."""
    return item.get("slot") if isinstance(item.get("slot"), int) else item.get("index") or index


def _slot_problems(scenes, prompts, requested):
    """How many slots are wrong: a scene or prompt for an image that was not requested, a slot given twice, or a
    requested image without a scene. Missing prompts are written's job."""
    expected = set(range(1, requested + 1))
    problems = 0
    for items in (scenes, prompts):
        slots = [_slot_of(item, index) for index, item in enumerate(items, 1)]
        problems += len(slots) - len(set(slots)) + len(set(slots) - expected)
    return problems + len(expected - {_slot_of(scene, index) for index, scene in enumerate(scenes, 1)})


def _requested(row):
    """How many images the case asked for: the test case's own amount (the brief's only when the case has none), never
    the number of prompts that came back, so a missing image always shows."""
    amount = row["case"].get("amount") or ((row.get("output") or {}).get("brief") or {}).get("input", {}).get("amount")
    return amount if isinstance(amount, int) and amount > 0 else None


def case_checks(row, normalize=None):
    """{check: value} for one case run (None when a check does not apply)."""
    seconds = row.get("seconds")
    lines = [line for line in row.get("log") or [] if isinstance(line, str)]
    redone = sum(bool(REDONE.search(line)) for line in lines)
    again = {match[1] for line in lines for match in REDONE.finditer(line)}
    requested = _requested(row) if row["kind"] != "builder" else None
    return {**_case_checks(row, normalize), "seconds": seconds, "redone": redone if row["kind"] != "builder" else None,
            "first_pass": round(1 - min(len(again), requested) / requested, 3) if requested and row.get("ok") else None}


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
    by_slot = {}
    for index, scene in enumerate(scenes, 1):  # a slot given twice keeps its first scene (slot_problems counts it)
        by_slot.setdefault(_slot_of(scene, index), scene)
    requested = _requested(row)
    labels = {person["label"] for person in brief.get("characters", [])}
    known = frozenset(person["label"] for person in brief.get("characters", []) if person.get("known") is True)
    kept = set(brief.get("kept") or ())
    avoid = [re.sub(r"^\s*(?:no|not|without|avoid|never)\s+", "", phrase, flags=re.IGNORECASE)
             for phrase in brief.get("avoid", [])]
    patterns = _label_patterns(brief.get("characters", []))
    pairs = list(itertools.combinations(scenes, 2))
    adult = brief.get("path") == "nsfw_character" or (brief.get("input") or {}).get("nsfw") is True
    expected = set(range(1, requested + 1)) if requested else set()
    return {
        "written": round(len({_slot_of(item, index) for index, item in enumerate(written, 1)} & expected) / requested, 3)
        if requested else None,
        "slot_problems": _slot_problems(scenes, output.get("prompts") or [], requested) if requested else None,
        "format_ok": round(sum(bool(_format_ok(prompt, target, normalize)) for prompt in prompts) / len(prompts), 3)
        if prompts and normalize else None,
        "known_changed": _scene_share(scenes, lambda scene: any(
            str(((scene.get("subjects") or {}).get(label) or {}).get(field) or "").strip()
            for label in known for field in ("skin", "hair", "build", "detail"))) if known else None,
        "sfw_leaks": round(sum(_adult_text(prompt) for prompt in prompts) / len(prompts), 3)
        if prompts and brief and not adult else None,
        "cast_ok": round(sum(set(scene.get("subjects") or {}) == labels for scene in scenes) / len(scenes), 3)
        if scenes else None,
        "actions_named": round(sum(all(re.search(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])",
                                                 str(scene.get("actions") or ""), re.IGNORECASE) for label in labels)
                                   for scene in scenes) / len(scenes), 3) if scenes and labels else None,
        "avoid_hits": _avoid_hits(prompts, avoid),
        "label_leaks": round(sum(any(pattern.search(prompt) for pattern in patterns) for prompt in prompts)
                             / len(prompts), 3) if prompts and patterns else None,
        "repeated_looks": _share(pairs, lambda a, b: bool(_looks(a, known)) and _looks(a, known) == _looks(b, known))
        if labels - known else None,
        # A part the request keeps repeats on purpose: only a near copy of it counts.
        "repeated_places": _share(pairs, lambda a, b: _overlap(a.get("space"), b.get("space"))
                                  >= (.9 if "place" in kept else .7)),
        "repeated_extras": _share(pairs, lambda a, b: _overlap(a.get("extras"), b.get("extras"))
                                  >= (.9 if kept & {"objects", "clothing", "light", "mood"} else .7)),
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
        "repeated_acts": _share(pairs, _same_arrangement if "action" in kept else _same_act) if labels else None,
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


AIM_STEP = 0.05  # an aim or hint check must move at least this much to count
INFO_STEP = 0.1  # an info check must move at least this share of its old value to count


def _run_keys(rows):
    """One key per run, "<case> / seed <seed>", with " (run 2)" and on when a case and seed come back more than once,
    so no run overwrites another."""
    keys, seen = [], {}
    for row in rows:
        key = f"{row['id']} / seed {row['seed']}"
        seen[key] = seen.get(key, 0) + 1
        keys.append(key if seen[key] == 1 else f"{key} (run {seen[key]})")
    return keys


def side_checks(side, normalize=None):
    """{"cases", "totals", "noise"} for one side. noise: the standard error of each total, from how much a check
    moves between seeds of the same request (compare prefers the paired differences between the two sides)."""
    keys = _run_keys(side["cases"])
    cases = {key: case_checks(row, normalize) for key, row in zip(keys, side["cases"])}
    # A Builder case writes one prompt per seed: its variety is how alike those prompts are across the seeds.
    builder = {}
    for row in side["cases"]:
        if row["kind"] == "builder" and row.get("ok") and (row.get("output") or {}).get("prompt", "").strip():
            builder.setdefault(row["id"], []).append(row["output"]["prompt"])
    for key, row in zip(keys, side["cases"]):
        found = builder.get(row["id"], [])
        if row["kind"] == "builder" and len(found) > 1:
            pairs = list(itertools.combinations(found, 2))
            cases[key]["prompt_similarity"] = round(sum(_jaccard(a, b) for a, b in pairs) / len(pairs), 3)
    by_case = {}
    for key, row in zip(keys, side["cases"]):
        by_case.setdefault(row["id"], []).append(cases[key])
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


def _paired_noise(baseline, candidate, name):
    """Twice the standard error of the per-run differences (new minus old) of runs both sides have, or None with fewer
    than two such runs. The two sides run the same requests and seeds, so the differences are paired. A rough guide
    for few runs, not a confidence level."""
    old, new = baseline.get("cases") or {}, candidate.get("cases") or {}
    differences = [new[key][name] - old[key][name] for key in old.keys() & new.keys()
                   if old[key].get(name) is not None and new[key].get(name) is not None]
    return round(2 * statistics.stdev(differences) / len(differences) ** .5, 3) if len(differences) > 1 else None


def compare(baseline, candidate):
    """[{check, about, kind, baseline, candidate, noise, change}] on the totals. change is "better", "worse",
    "same" (no real move: within noise, an aim or hint check moving less than AIM_STEP, an info check moving less
    than INFO_STEP of its old value) or "n/a". Info changes are shown, and the verdict only notes them."""
    rows = []
    for name, about, kind, higher in CHECKS:
        old, new = baseline["totals"].get(name), candidate["totals"].get(name)
        noise = _paired_noise(baseline, candidate, name)
        if noise is None:  # too few paired runs: the spread between seeds of the same request, from both sides
            noise = round(2 * (((baseline.get("noise") or {}).get(name, 0.0)) ** 2
                               + ((candidate.get("noise") or {}).get(name, 0.0)) ** 2) ** .5, 3)
        step = {"aim": AIM_STEP, "hint": AIM_STEP, "info": INFO_STEP * abs(old or 0)}.get(kind, 1e-9)
        if old is None or new is None:
            change = "n/a"
        elif abs(new - old) <= (step if kind == "guard" else max(noise, step)):  # a guard change is never noise
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
