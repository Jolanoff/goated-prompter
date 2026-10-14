"""Dataset adult-content switches: one definition per module, reused by routing, filtering and planning.

Core activities are eligible whenever the cast's anatomy allows them. Optional modules stay off
unless the confirmed request asks for them. Event modules are eligible but never forced.
Adding a module means adding one entry here plus its TXT sections; no other file lists modules.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Module:
    name: str
    kind: str                              # "core", "optional" or "event"
    pattern: re.Pattern | None = None      # conservative fallback over the user's own words
    sections: tuple[str, ...] = ()         # position sections for two or more people
    solo_sections: tuple[str, ...] = ()    # position sections for one person (default: sections)
    styling: tuple[tuple[str, str], ...] = ()  # (axis, TXT section) styling guidance
    default: str = "off"                   # "eligible" or "off"
    default_solo: str = ""                 # overrides default for a one-person cast
    implies: tuple[str, ...] = ()          # genuine dependencies only


# Ordinary sex is the default; domination, restraint and fetish dynamics only when asked for.
# Equipment, pet roles, feet focus and costumes have their own switches.
KINK = re.compile(r"\b(?:slaves?|owned by|collared|collars?|leash(?:ed)?|bdsm|dominatrix|dom(?:/| and )sub|"
                  r"submissive|dominant|dominat\w*|bondage|bound|restrain\w*|tied up|handcuff\w*|spank\w*|chok\w*|"
                  r"breeding|degrad\w*|humiliat\w*|(?<!foot )(?<!feet )fetish\w*|kinky|kinks?|"
                  r"rough sex|(?:his|her|my|their) (?:master|mistress))\b")
TOYS = re.compile(r"\b(?:toys?|dildos?|vibrators?|plugs?|strap[- ]?ons?)\b")
# Feet focus is an act or an explicit focus, never bare feet in a pose or "barefoot".
FEET = re.compile(r"\b(?:foot ?jobs?|footjob\w*|foot (?:fetish|worship|play|focus|massage)|"
                  r"feet (?:worship|fetish|focus|play)|soles|"
                  r"(?:lick|suck|kiss|worship|massag|sniff|tickl)\w* (?:(?:the|his|her|their|a partner's|partner's) )?"
                  r"(?:bare )?(?:feet|toes|soles)|(?:focus\w* on|show\w*) (?:\w+ ){0,2}(?:feet|toes|soles))\b")
PET = re.compile(r"\b(?:pet play|petplay|human pets?|puppy play|kitten play|pup play|puppy|kitten|pets?)\b")
# Human-furniture roles only; a sofa, bed or table is ordinary setting.
FURNITURE = re.compile(r"\b(?:human (?:furniture|table|chair|stool|ottoman|bench|carpet|armrest|footrest|side table)|"
                       r"furniture (?:play|pose|role|pet|position)|living furniture|objectif\w*|"
                       r"used as (?:a )?(?:human )?(?:furniture|table|chair|stool|bench|carpet|armrest|pillow|"
                       r"mounting block|footrest|ottoman))\b")
FINISH = re.compile(r"\b(?:climax\w*|finish\w*|orgasm\w*|cum(?:s|ming|shots?)?)\b")

# Objects and costume families. Equipment is owned by Props alone; clothing stays styling and
# appears only when named; toys follow the Toys switch.
ACCESSORY_FAMILIES = {
    "rope": re.compile(r"\b(?:ropes?|roped|shibari|kinbaku|tied|ties?|tying|hogtie\w*|frogtie|crotch rope|box tie|"
                       r"takate-kote|karada|ebi|kikkou|shinju|bound|binding)\b"),
    "restraints": re.compile(r"\b(?:cuff\w*|handcuff\w*|shackle\w*|chain\w*|spreader\w*|armbinder|strappado|restrain\w*|"
                             r"straps?(?![- ]?ons?\b)|strapped|stirrups|st\.? andrew's cross|cross|stocks|pillory|hooks?|bedposts?|bondage|harness\w*|"
                             r"wooden pony|bonding chair)\b"),
    "collar": re.compile(r"\b(?:collar\w*|leash\w*|name tag)\b"),
    "gag": re.compile(r"\b(?:gag\w*|ballgag|blindfold\w*|muzzle\w*|hood(?:ed)?)\b"),
    "impact": re.compile(r"\b(?:paddle\w*|crop(?![- ]?tops?\b)|flogger\w*|whip\w*|cane|caning|spank\w*)\b"),
    "objects": re.compile(r"\b(?:nipple clamps?|clamps?|chastity|marker|writing|written|writes|labels?|property of|lipstick|"
                          r"pedestal|wedge|barrel|medical table|exam table|inspection table|padlock|key held)\b"),
    "pet gear": re.compile(r"\b(?:(?:food |water |dog |pet )?bowls?|kennel|(?<!chastity )cage|crate|tails?)\b"),
    "toys": re.compile(r"\b(?:toys?|dildo\w*|vibrator\w*|wand|plugs?|beads|prostate massager|machines?|sybian|pumps?|"
                       r"tentacle\w*)\b"),
    "clothing": re.compile(r"\b(?:maid|sissy|latex|pvc|catsuit|fishnets?|crossdress\w*|feminiz\w*|whore|"
                           r"micro[- ](?:skirt|dress)|garter\w*|stockings?|heels|apron|frilly|open-cup|bodysuit|"
                           r"panties|corset|crop[- ]?tops?|short skirt|lingerie set)\b"),
}
EQUIPMENT = frozenset(("rope", "restraints", "collar", "gag", "impact", "objects", "pet gear"))
# A generic request for gear permits every equipment family; a named family permits only itself.
GENERIC_PROPS = re.compile(r"\b(?:props?|accessor(?:y|ies)|gear|equipment|bdsm (?:gear|equipment|toys)|costumes?|"
                           r"latex|pvc|catsuit|maid (?:outfit|uniform|costume|dress))\b")
# Activation uses the specific equipment words; generic words such as "writing" or "bowl" only
# filter vocabulary entries and never switch Props on by themselves.
PROPS = re.compile("|".join([GENERIC_PROPS.pattern,
    *(ACCESSORY_FAMILIES[name].pattern for name in ("rope", "restraints", "collar", "gag", "impact")),
    r"\b(?:nipple clamps?|clamps|chastity(?: cage| device| belt)?|body writing|property of|padlock(?:ed)?|"
    r"(?:food|water|dog|pet) bowls?|kennel|cage|crate|tail plug|pet tail)\b"]))

MODULES = (
    Module("anal", "core", sections=("anal positions",), default="eligible"),
    Module("oral", "core", sections=("oral positions",), default="eligible"),
    Module("vaginal", "core", sections=("vaginal positions",), default="eligible"),
    Module("kink", "optional", KINK, ("kink positions",), ("solo kink positions",),
           (("setting", "kink setting"), ("mood", "kink mood"), ("clothing", "kink clothing"),
            ("interaction", "kink interaction"))),
    Module("toys", "optional", TOYS, ("toys",), default_solo="eligible"),
    Module("feet", "optional", FEET, ("feet positions",), ("solo feet positions",)),
    Module("props", "optional", PROPS, styling=(("prop", "props"),)),
    Module("pet", "optional", PET, ("pet positions",), styling=(("mood", "pet mood"), ("interaction", "pet interaction"))),
    Module("furniture", "optional", FURNITURE, ("furniture positions",)),
    Module("finish", "event", FINISH, ("finish positions",), default="eligible"),
)
MODULES_BY_NAME = {module.name: module for module in MODULES}
# Which module a position section belongs to (solo sections included).
SECTION_MODULES = {section: module.name for module in MODULES for section in (*module.sections, *module.solo_sections)}
CORE_ACTIVITIES = frozenset(module.name for module in MODULES if module.kind == "core")
SWITCHES = tuple(module.name for module in MODULES if module.kind != "core")


def default_switches(count):
    """Non-core modules eligible without a request for this cast size."""
    return {module.name for module in MODULES if module.kind != "core"
            and ((module.default_solo or module.default) if count == 1 else module.default) == "eligible"}


def resolve_switches(asked, excluded, count):
    """Requested plus default switches, with implications; exclusions always win."""
    enabled = (set(asked) | default_switches(count)) - set(excluded)
    pending = list(enabled)
    while pending:
        for name in MODULES_BY_NAME[pending.pop()].implies:
            if name not in enabled and name not in excluded:
                enabled.add(name)
                pending.append(name)
    return enabled


def position_sections(enabled, count):
    sections = set()
    for name in enabled:
        module = MODULES_BY_NAME.get(name)
        if module and module.kind != "core":
            sections.update(module.solo_sections or module.sections if count == 1 else module.sections)
    return sections


def styling_sections(enabled):
    """(axis, section) pairs unlocked by enabled optional modules."""
    return [pair for name in sorted(enabled) if name in MODULES_BY_NAME for pair in MODULES_BY_NAME[name].styling]
