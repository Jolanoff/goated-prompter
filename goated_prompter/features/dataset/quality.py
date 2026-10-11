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
_SEXUAL = re.compile(r"\b(?:sex|sexual\w*|intercourse|nsfw|porn\w*|explicit|erotic\w*|nude|nudity|naked|fuck\w*|blowjob\w*|"
                     r"handjob\w*|oral(?! (?:presentations?|exams?|examinations?|hygiene|history|health|surgery|traditions?|reports?|arguments?))|anal|penetrat\w*|masturbat\w*|cum|cums|cumming|cumshot\w*|orgasm\w*|cocks?|"
                     r"dicks?|pussy|pussies|boobs?|tits|nipples?|genitals?|horny|aroused|"
                     # Kink and genre words; ambiguous ones need their sexual form ("collared", not "collar").
                     r"slaves?|sex slaves?|owned by|collared|leash(?:ed)?|pet play|bdsm|dominatrix|dom(?:/| and )sub|"
                     r"submissive|bondage|kinky|kinks?|yaoi|bara|male[- ]male|mm sex|footjob\w*|foot fetish|feet worship|"
                     r"breeding (?:kink|her|him)|breed (?:her|him|me)|"
                     r"presenting (?:herself|himself|themselves|her ass|his ass))\b")
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


NO_ANIMALS = "Sexual content cannot involve animals. Remove the animal from the cast or the sexual request."


def adults_only_error(data):
    """For a sexual or suggestive batch, the reason it cannot run: someone under 18, or an animal."""
    text = _request_text(data)
    if not (_SEXUAL.search(text) or _SUGGESTIVE.search(text)):
        return None
    if word := minor_reference(text):
        return f'{ADULTS_ONLY} ("{word}")'
    cast = (data.get("_confirmed_intent") or {}).get("characters") or ()
    if data.get("trigger_type") == "Animal" or any(isinstance(item, dict) and item.get("kind") == "animal" for item in cast):
        return NO_ANIMALS
    return None


# Image models merge genitals described as touching, and detach body parts described on their
# own, so sexual ideas and prompts that word them that way are redone.
_PART = r"(?:penis(?:es)?|cocks?|dicks?|genitals?|breasts?|limbs?|arms?|legs?|hands?|heads?|body parts?)"
_GENITAL = r"(?:penis(?:es)?|cocks?|dicks?|genitals?)"
_BROKEN_ANATOMY = re.compile(
    rf"\b(?:detached|severed|disembodied|floating|cut[- ]off|amputated|dismembered|separated)\W+(?:\w+\W+){{0,3}}{_PART}\b"
    rf"|\b{_PART}\W+(?:\w+\W+){{0,3}}(?:detached|severed|disembodied|floating|cut off|amputated|separated from)\b"
    rf"|\b{_GENITAL}\W+(?:\w+\W+){{0,3}}(?:shared|joined|connected|merged|fused)\b"
    rf"|\b(?:shared|single|one|joined|connected|merged|fused)\W+(?:\w+\W+){{0,2}}{_GENITAL}\W+(?:\w+\W+){{0,4}}(?:between|both|two)\b"
    rf"|\b(?:cocks|penises|dicks)\W+(?:\w+\W+){{0,3}}(?:touching|together|tip to tip|side by side)\b"
    r"|\bass[- ]to[- ]ass\b"
    rf"|\b{_GENITAL}\W+(?:\w+\W+){{0,6}}{_GENITAL}\W+(?:\w+\W+){{0,2}}(?:touching|pressed|rubbing|together)\b")
BROKEN_ANATOMY = ("Every body part must stay attached to its owner: name each with its owner, keep visible genitals "
                  "with their owner's hips and torso in frame, and never describe a part alone, detached, or shared, "
                  "joined or touching between two people.")


def broken_anatomy(text):
    """The first wording that detaches or merges a body part in a sexual image, or None."""
    match = _BROKEN_ANATOMY.search(str(text or "").casefold())
    return match.group() if match else None


# Ordinary sex is the default; domination, restraint and fetish dynamics only when asked for.
_KINK = re.compile(r"\b(?:slaves?|owned by|collared|collars?|leash(?:ed)?|pet play|bdsm|dominatrix|dom(?:/| and )sub|"
                   r"submissive|dominant|dominat\w*|bondage|bound|restrain\w*|tied up|handcuff\w*|spank\w*|chok\w*|"
                   r"foot fetish|feet worship|breeding|degrad\w*|humiliat\w*|fetish\w*|kinky|kinks?|"
                   r"latex|rough sex|(?:his|her|my|their) (?:master|mistress))\b")
_ORAL = re.compile(r"\b(?:oral|blowjob\w*|suck\w*|deepthroat\w*|69|sixty-nine|face[- ]?sitting|cunnilingus|"
                   r"face[- ]?fuck\w*|mouth[- ]?fuck\w*|eat(?:s|ing)? (?:her|him) out|lick\w*)\b")


# The user's own words (concept, rules, trigger, guided input) and the Director, without the
# brief the model wrote, so a word the model added never unlocks anything.
def requested_text(data):
    parts = [str(data.get(key) or "") for key in ("subject", "constraints", "inputs", "trigger")]
    parts.append(get_director_preset(data.get("director_preset")).instructions)
    return " ".join(parts).casefold()


_FEET = re.compile(r"\b(?:feet|foot\w*|soles|toes)\b")


def feet_request(data):
    return bool(_FEET.search(requested_text(data)))


# A Director only unlocks BDSM when it is built for it; a general NSFW Director that mentions
# control or dominance in passing keeps sex ordinary.
_KINK_DIRECTOR = re.compile(r"\b(?:bdsm|bondage|collar(?:ed|s)?|leash(?:ed)?|slaves?|restrain\w*|handcuff\w*|"
                            r"spank\w*|dominatrix|fetish\w*|kinky|submissives?|domination|power exchange)\b")
_NEGATED = re.compile(r"\b(?:do not|don't|never|no|not|avoid|without|unrequested|unless)\b")
_NOT_A_PERSON = r"(?! (?:bedroom|bath\w*|suite|key|plan|class|chef|piece|copy|cylinder|degree))"
# Ownership and slave roles ask for the power exchange in every image, not as one option among many.
_OWNERSHIP = re.compile(r"\b(?:slaves?|(?<!-)owned|ownership|property|dominated|human pets?|pet play|petplay|"
                        r"collared|leashed|(?:master|mistress)"
                        + _NOT_A_PERSON + r")\b")
_PET = re.compile(r"\b(?:pet play|petplay|human pets?|puppy play|kitten play|puppy|kitten|pets?)\b")
_FURNITURE = re.compile(r"\b(?:human furniture|furniture|footrest|human (?:table|chair|stool)|objectif\w*)\b")
_AFTERCARE = re.compile(r"\b(?:aftercare|aftermath)\b")
_GROUNDED_FEET = re.compile(r"^\s+(?:(?:are|stay|rest)\s+)?(?:planted|flat|firmly|on (?:the )?(?:floor|ground|mat))\b")


def _mentions(text, pattern, *, ignore_conditional=False):
    asked, forbidden = False, False
    for match in pattern.finditer(text):
        if pattern is _FEET and match.group() == "feet" and _GROUNDED_FEET.search(text[match.end():]):
            continue
        clause = re.split(r"[.,;:!?\n]|\b(?:but|however|instead)\b", text[:match.start()])[-1]
        if _NEGATED.search(clause):
            if not (ignore_conditional and re.search(r"\b(?:unrequested|unless)\b", clause)):
                forbidden = True
        else:
            asked = True
    return asked, forbidden


def _asked(text, pattern):
    """True when the pattern appears in a clause that does not forbid it."""
    return _mentions(text, pattern)[0]


def _user_text(data):
    return "\n".join(str(data.get(key) or "") for key in ("subject", "constraints", "inputs", "trigger")).casefold()


def _director_text(data):
    return get_director_preset(data.get("director_preset")).instructions.casefold()


def ownership_request(data):
    return _asked(_user_text(data) + "\n" + _director_text(data), _OWNERSHIP)


def kink_request(data):
    return (_asked(_user_text(data), _KINK) or _asked(_director_text(data), _KINK_DIRECTOR)
            or ownership_request(data))


def pet_request(data):
    return _asked(_user_text(data) + "\n" + _director_text(data), _PET)


def furniture_request(data):
    return _asked(_user_text(data) + "\n" + _director_text(data), _FURNITURE)


def aftercare_request(data):
    return _asked(_user_text(data) + "\n" + _director_text(data), _AFTERCARE)


_POSITION_CATEGORIES = {
    "penetration": re.compile(r"\b(?:fuck(?:s|ed|ing)?|intercourse|penetrat\w*)\b"),
    "anal": re.compile(r"\b(?:anal|sodomy|sodomiz\w*)\b"),
    "vaginal": re.compile(r"\b(?:vaginal|vagina|pussy)\b"),
    "oral": _ORAL,
    "feet": _FEET,
    "kink": _KINK,
    "pet": _PET,
    "furniture": _FURNITURE,
    "aftercare": _AFTERCARE,
    "solo": re.compile(r"\b(?:masturbat\w*|solo|self[- ]pleasure)\b"),
    "toys": re.compile(r"\b(?:toys?|dildos?|vibrators?|plugs?)\b"),
    "finish": re.compile(r"\b(?:climax\w*|finish\w*|orgasm\w*|cum(?:s|ming|shots?)?)\b"),
}
POSITION_ACT_CATEGORIES = frozenset(("anal", "vaginal", "oral", "feet"))
_MAN_ROLE = re.compile(r"\b(?:master|sir|king|prince|husband|boyfriend|daddy|groom|man|men|males?)\b")
_WOMAN_ROLE = re.compile(r"\b(?:mistress|queen|princess|wife|girlfriend|dominatrix|goddess|bride|woman|women|females?)\b")
MALE_PAIR = re.compile(r"\b(?:two|2|three|3|several) (?:men|males|guys)\b|\b(?:gay|yaoi|bara|male[- ]male)\b|"
                       r"\bmm\b|\bmale (?:partner|slave|sub|lover|pet|friend)s?\b")
FEMALE_PAIR = re.compile(r"\b(?:two|2|three|3|several) (?:women|females)\b|\b(?:lesbian\w*|yuri|female[- ]female)\b|"
                         r"\bfemale (?:partner|slave|sub|lover|pet|friend)s?\b")


def resolved_sex(item, data):
    """Keep a stated sex, or fill an open one from a role or an unambiguous pairing."""
    if item.get("sex") in ("male", "female"):
        return item["sex"]
    role = f"{item.get('name') or ''} {item.get('traits') or ''}".casefold()
    male, female = bool(_MAN_ROLE.search(role)), bool(_WOMAN_ROLE.search(role))
    if male != female:
        return "male" if male else "female"
    text = _user_text(data)
    male, female = bool(MALE_PAIR.search(text)), bool(FEMALE_PAIR.search(text))
    return ("male" if male else "female") if male != female else None


def position_categories(data, *, include_director=True):
    """Requested acts and exclusions; explicit user acts take precedence over Director defaults."""
    user = _user_text(data)
    director = _director_text(data) if include_director else ""
    user_penetration = any(_asked(user, _POSITION_CATEGORIES[name]) for name in ("penetration", "anal", "vaginal"))
    asked, defaults, forbidden = set(), set(), set()
    for name, pattern in _POSITION_CATEGORIES.items():
        user_asked, user_forbids = _mentions(user, pattern)
        director_asked, director_forbids = _mentions(director, pattern, ignore_conditional=True)
        if user_asked:
            asked.add(name)
        if director_asked:
            defaults.add(name)
        user_overrides = user_asked or (name == "penetration" and user_penetration)
        if user_forbids or (director_forbids and not user_overrides):
            forbidden.add(name)
    for text, positive in ((user, asked), (director, defaults)):
        if "feet" in positive and not any(not match.group().startswith(("lick", "suck"))
                                          for match in _ORAL.finditer(text)):
            positive.discard("oral")
    if _asked(user, _OWNERSHIP):
        asked.add("kink")
    elif _asked(director, _OWNERSHIP):
        defaults.add("kink")
    return (asked or defaults) - forbidden, forbidden


def position_presence_error(text, position):
    """The selected phrase is a preservation contract, not a semantic pose classifier."""
    def words(value):
        return " ".join(re.findall(r"\w+", str(value or "").casefold()))
    expected = words(position)
    if expected and f" {expected} " not in f" {words(text)} ":
        return "Preserve the selected position wording in the scene description: " + position
    return None
