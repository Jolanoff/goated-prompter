"""Dataset V2 content eligibility: adult content shows adults only, and never animals.

The word lists below exist only to recognise adult requests so that the adults-only and no-animals checks apply to
them; they are detection data, not content the app writes.

Understanding (v2/understanding.py) applies these checks to the request and to its own reading of it, before
and at confirmation. Moved here from the retired legacy pipeline (features/dataset/quality.py) unchanged.
"""

import re

from ....presets import get_director_preset
from .triggers import all_text, data_triggers


# A collared garment and a leash for an animal are everyday words, not kink: "collared" right before a garment
# ("a collared shirt", "a high-collared tunic" in a live safe prompt) is that garment's collar; before anything else
# ("a collared slave", "leather-collared") it stays a kink word.
_COLLARED = (r"collared(?! (?:shirts?|blouses?|dress(?:es)?|jackets?|coats?|overcoats?|tops?|polos?|sweaters?|"
             r"uniforms?|tunics?|robes?|gowns?|cloaks?|capes?|vests?|cardigans?|hoodies?|kimonos?|tailcoats?))")
_LEASH = (r"(?<!dog on a )(?<!dog's )(?<!puppy on a )(?<!dog on )leash(?:ed)?"
          r"(?! (?:on|for|to) (?:a |the |his |her |their )?(?:dog|puppy|pet)s?\b)")

# Genitals in everyday words; with their anatomical names, what makes an image explicit (explicit_text).
_GENITALS = r"cocks?|dicks?|pussy|pussies|genitals?"
_EXPLICIT_PARTS = re.compile(r"\b(?:penis(?:es)?|testicles|anus|vagina|vulva|clitoris|" + _GENITALS + r")\b")

# Broad safety detection includes anatomy and styling even when no sexual action is requested.
_SEXUAL = re.compile(r"\b(?:sex|sexual\w*|intercourse|nsfw|porn\w*|explicit|erotic\w*|nude|nudity|naked|fuck\w*|blowjob\w*|"
                     r"handjob\w*|oral(?! (?:presentations?|exams?|examinations?|hygiene|history|health|surgery|traditions?|reports?|arguments?))|anal|penetrat\w*|masturbat\w*|cum(?! laude)|cums|cumming|cumshot\w*|orgasm\w*|"
                     + _GENITALS + r"|boobs?|tits|nipples?|horny|aroused|"
                     # Kink and genre words; ambiguous ones need their sexual form ("collared", not "collar") and
                     # everyday uses are left out (a collared shirt, a dog on a leash, kinky hair).
                     r"slaves?|sex slaves?|" + _COLLARED + r"|" + _LEASH + r"|pet play|bdsm|dominatrix|dom(?:/| and )sub|"
                     r"submissive|bondage|kinky(?! (?:hair|curls?))|kinks?|yaoi|bara|male[- ]male|mm sex|footjob\w*|foot fetish|feet worship|"
                     r"breeding (?:kink|her|him)|breed (?:her|him|me)|"
                     r"presenting (?:herself|himself|themselves|her ass|his ass))\b")


_SUGGESTIVE = re.compile(r"\b(?:lingerie|boudoir|seductive\w*|sensual\w*|undress\w*|striptease|strippers?|"
                         r"strip(?:s|ped|ping)? (?:off|down|naked|nude)|topless|bottomless)\b")


_MINOR = re.compile(r"\b(?:child|children|childlike|kids?|minors?|underage\w*|teens?|teenage\w*|preteens?|"
                    r"tweens?|loli\w*|shota\w*|schoolgirls?|schoolboys?|toddlers?|infants?|bab(?:y|ies)|"
                    r"(?:elementary|primary|middle|high|junior high) school\w*|little (?:girl|boy)s?|young (?:girl|boy)s?|"
                    r"(?:[1-9]|1[0-7])\s*(?:yo|y/o|-?years?[- ]old|-year-old))\b")
# Everyday words that contain a minor term but describe no person: baby oil, kid gloves, a baby-blue dress.
_NOT_MINOR = re.compile(r"\b(?:bab(?:y|ies)[- ](?:oil|blue|pink|powder)|kids?[- ](?:gloves?|leather))\b")


ADULTS_ONLY = ("Adult content can only show adults. Remove anything that makes a character a child or teen "
               "(age under 18, school, childlike body); describe every character as an adult.")


def _request_text(data):
    brief = data.get("_confirmed_intent") or {}
    parts = [str(data.get(key) or "") for key in ("subject", "constraints", "inputs", "custom_type")]
    parts.append(all_text(data_triggers(data)))
    parts += [str(item.get(key) or "") for item in brief.get("characters") or () if isinstance(item, dict)
              for key in ("name", "traits")]
    parts += [str(brief.get(field) or "") for field in ("requested_generation", "dataset_contents")]
    parts += [str(item.get("text") or "") for field in ("hard", "soft", "action_options", "interactions")
              for item in brief.get(field) or () if isinstance(item, dict)]
    parts.append(get_director_preset(data.get("director_preset")).instructions)
    return "\n".join(parts).casefold()


_SEXUAL_ACTION = re.compile(r"\b(?:sex|intercourse|nsfw|porn\w*|erotic\w*|fuck\w*|blowjob\w*|handjob\w*|"
    r"vaginal|cunnilingus|fellatio|self[- ]pleasure|dildos?|vibrators?|strap[- ]?ons?|"
    r"oral(?! (?:presentations?|exams?|examinations?|hygiene|history|health|surgery|traditions?|reports?|arguments?))|"
    r"anal|penetrat\w*|masturbat\w*|cum(?:s|ming|shots?)?(?! laude)|orgasm\w*|horny|aroused|"
    r"slaves?|" + _COLLARED + r"|" + _LEASH + r"|pet play|bdsm|dominatrix|dom(?:/| and )sub|"
    r"submissive|bondage|kinky(?! (?:hair|curls?))|kinks?|yaoi|bara|mm sex|footjob\w*|foot fetish|feet worship|"
    r"breeding (?:kink|her|him)|breed (?:her|him|me)|"
    r"presenting (?:herself|himself|themselves|her ass|his ass)|sexual (?:acts?|scenes?|content|activity|aftercare|roleplay))\b")


def sexual_request(data, *, include_director=True):
    """Authorize act-focused routing from requested activity, not anatomy or model-added facts."""
    patterns = (_SEXUAL_ACTION, _ACT_EVIDENCE["feet"])
    return (any(_asked(_user_text(data), pattern) for pattern in patterns)
            or include_director and any(_asked(_director_text(data), pattern) for pattern in patterns))


def sexual_text(text):
    """Whether a text names a sexual act in the words the request detection knows (a scene written in everyday
    words, which has no anatomical name for the act)."""
    return bool(_SEXUAL_ACTION.search(str(text or "").casefold()))


def explicit_text(text):
    """Whether a text shows genitals or names a sexual act, in anatomical or everyday words: an image it describes is
    explicit."""
    return bool(_EXPLICIT_PARTS.search(str(text or "").casefold())) or sexual_text(text)


def adult_text(text):
    """Whether a text shows adult content of any kind (nudity, anatomy, suggestive styling) in the words the request
    detection knows: an image it describes is never safe."""
    text = str(text or "").casefold()
    return bool(_SEXUAL.search(text) or _SUGGESTIVE.search(text))


def adult_content_request(data, *, include_director=True):
    """Keep anatomy, nudity and suggestive styling subject to the existing safety checks."""
    text = _request_text(data) if include_director else _user_text(data)
    return (_asked(text, _SEXUAL) or _asked(text, _SUGGESTIVE)
            or sexual_request(data, include_director=include_director))


def minor_reference(text):
    """The first wording that makes someone a child or teen, or None."""
    match = _MINOR.search(_NOT_MINOR.sub(" ", str(text or "").casefold()))
    return match.group() if match else None


NO_ANIMALS = "Adult content cannot involve animals. Remove the animal from the cast or the adult request."


def adults_only_error(data, *, include_director=True):
    """For a sexual or suggestive batch, the reason it cannot run: someone under 18, or an animal."""
    if not adult_content_request(data, include_director=include_director):
        return None
    text = _request_text(data) if include_director else _user_text(data)
    if word := minor_reference(text):
        return f'{ADULTS_ONLY} ("{word}")'
    cast = (data.get("_confirmed_intent") or {}).get("characters") or ()
    if data.get("trigger_type") == "Animal" or any(isinstance(item, dict) and item.get("kind") == "animal" for item in cast):
        return NO_ANIMALS
    return None


_NEGATED = re.compile(r"\b(?:do not|don't|never|no|not|avoid|without|unrequested|unless)\b")


_DIRECTOR_CONDITION = re.compile(r"\b(?:if|when|unless)\b|^\s*(?:[-*]\s*)?for\s+(?!every\b|each\b|all\b|any\b)"
                                 r"[^.!?;\n]*\b(?:requests?|requested|focus(?:es)?)\b")


_GROUNDED_FEET = re.compile(r"^\s+(?:(?:are|stay|rest)\s+)?(?:planted|flat|firmly|on (?:the )?(?:floor|ground|mat))\b")


def _mentions(text, pattern, *, ignore_conditional=False):
    asked, forbidden = False, False
    for sentence in re.split(r"[.!?;\n]", text):
        for match in pattern.finditer(sentence):
            if match.group() == "feet" and _GROUNDED_FEET.search(sentence[match.end():]):
                continue
            segment = re.split(r"\b(?:but|however|instead)\b", sentence[:match.start()])[-1]
            clauses = re.split(r"[,:]", segment)
            clause = clauses[-1]
            # A comma-separated prohibition still governs later nouns in its list.
            # A new positive directive or adversative starts a separate clause.
            if (any(_NEGATED.search(item) for item in clauses[:-1])
                    and not re.match(r"\s*(?:always|only|use|allow|include|show|depict|wear|want|request|with|keep)\b", clause)):
                clause = segment
            if _NEGATED.search(clause):
                if not (ignore_conditional and re.search(r"\bunrequested\b", clause)):
                    forbidden = True
            else:
                asked = True
    return asked, forbidden


def _asked(text, pattern, *, ignore_conditional=False):
    """True when the pattern appears in a clause that does not forbid it."""
    return _mentions(text, pattern, ignore_conditional=ignore_conditional)[0]


def _user_text(data):
    fields = ("subject", "constraints") + (("inputs",) if data.get("source_mode") == "guided" else ())
    return "\n".join([*(str(data.get(key) or "") for key in fields), all_text(data_triggers(data))]).casefold()


def _director_text(data):
    """Unconditional standing direction for routing; prompts still receive the full Director."""
    text = get_director_preset(data.get("director_preset")).instructions.casefold()
    return "\n".join(sentence for sentence in re.split(r"[.!?;\n]", text)
                     if not _DIRECTOR_CONDITION.search(sentence))


# A body part or ordinary support is not evidence of a different act.
_ACT_EVIDENCE = {
    "anal": re.compile(r"\b(?:anal(?![- ](?:beads?|plugs?|toys?|anatomy|opening|area|sphincter|muscles?)\b)|"
                       r"sodomy|sodomiz\w*)\b"),
    "vaginal": re.compile(r"\bvaginal\b"),
    "oral": re.compile(r"\b(?:oral|blowjob\w*|deepthroat\w*|cunnilingus|fellatio|"
                       r"face[- ]?(?:sitting|fuck\w*)|mouth[- ]?fuck\w*|sixty-nine|69)\b"),
    "feet": re.compile(r"\b(?:footjob\w*|foot fetish|feet worship|foot worship|"
                       r"(?:lick\w*|suck\w*) (?:the |his |her |their |a partner's )?(?:feet|toes|soles))\b"),
}
