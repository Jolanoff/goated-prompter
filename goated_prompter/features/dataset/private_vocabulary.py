"""Adult Dataset vocabulary, read from a private plain-text file the user keeps in data/.

The file is never shipped or committed: without it, sexual batches still run on the rules
alone and the model invents its own moods, places and positions. Entries are inspiration for
the model, drawn at random, never forced. Every entry passes the same adults-only and anatomy
checks as generated text, plus checks for consent, death, family, animals and breathing, so a
line added to the file can never bring that content back.
"""

import os
from pathlib import Path
import re

from ...config import PROJECT_ROOT
from .quality import broken_anatomy, minor_reference, ownership_request, sexual_request

VOCABULARY_FILE_ENV = "GOATED_PROMPTER_VOCABULARY_FILE"

# What each [section] is used for. Unknown sections are ignored.
SECTIONS = {
    "rules": "extra rule lines for every sexual batch",
    "ownership rules": "extra rule lines when the request or Director uses ownership language",
    "mood": "moods for every sexual batch",
    "interaction": "dynamics between partners for every sexual batch",
    "group interaction": "dynamics for three or more people",
    "setting": "private places for every sexual batch",
    "clothing": "clothing states for every sexual batch",
    "kink mood": "moods when kink or ownership is requested",
    "kink interaction": "dynamics when kink or ownership is requested",
    "kink setting": "places when kink or ownership is requested",
    "kink clothing": "clothing states when kink or ownership is requested",
    "pet mood": "moods when pet play is requested",
    "pet interaction": "dynamics when pet play is requested",
    "props": "props when kink or ownership is requested",
    "solo positions": "one person",
    "couple positions": "two people of any sex",
    "two men positions": "two men",
    "two women positions": "two women",
    "man and woman positions": "a man and a woman",
    "three positions": "three people",
    "group positions": "four or more people",
    "oral positions": "when oral is requested",
    "feet positions": "when feet are requested",
    "kink positions": "when kink or ownership is requested",
    "pet positions": "when pet play is requested",
    "furniture positions": "when human furniture or ownership is requested",
    "aftercare positions": "when aftercare is requested",
    "requested": "lines 'pattern => entry': the entry joins the positions when the request matches the pattern",
}

# Content no request can unlock: non-consent and incapacitation, death, family, animals,
# school, and breath restriction or injury.
_BLOCKED = re.compile(
    r"\b(?:rap(?:e|ed|ing)|non-?consens\w*|forc(?:e|ed|es|ing)\b|against (?:her|his|their) will|reluctant\w*|"
    r"unwilling|drugged|unconscious|asleep|sleeping|passed out|dehumaniz\w*|broken(?:-in)?|"
    r"corpses?|dead|death|morgue|embalm\w*|funeral\w*|cremat\w*|mausoleums?|crypts?|tombs?|graves?|graveyards?|"
    r"cemeter\w*|ossuar\w*|catacombs?|charnel|sepulch\w*|"
    r"incest\w*|step-?(?:sis\w*|bro\w*|mom|mother|dad|father|daughter|son)|sisters?|brothers?|mothers?|fathers?|"
    r"daughters?|sons|cousins?|aunts?|uncles?|nieces?|nephews?|"
    r"dogs?|horses?|bestial\w*|zoophil\w*|"
    r"schools?|classrooms?|daycare|playground|"
    r"chok\w*|strangl\w*|smother\w*|suffocat\w*|mummif\w*|plastic wrap|vacuum bed|"
    r"(?:hand|hands) (?:on|around) (?:the|her|his|their) (?:throat|neck)|covering (?:the|her|his|their) (?:partner's )?mouth|"
    r"blood\w*|bleed\w*|knife|knives|guns?|wounds?|injur\w*)\b")


def vocabulary_path():
    configured = os.environ.get(VOCABULARY_FILE_ENV, "").strip()
    return Path(configured).expanduser() if configured else PROJECT_ROOT / "data" / "vocabulary" / "sexual.txt"


TEMPLATE_HEADER = """# Private adult vocabulary for the Dataset tab. It stays on this computer and is never committed.
# Add one entry per line under a [section] heading; lines starting with # are comments.
# Changes apply to the next batch without a restart. Entries are inspiration drawn at random,
# never forced on an image. Entries about minors, non-consent, death, family members, animals,
# school, breath restriction or injury, or that detach or merge body parts, are skipped.
"""


def ensure_vocabulary_file(path=None):
    """On first launch, create an empty file listing every section, so the user can fill it in."""
    path = Path(path) if path is not None else vocabulary_path()
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = "".join(f"\n[{name}]\n# {description}\n" for name, description in SECTIONS.items())
    path.write_text(TEMPLATE_HEADER + sections, encoding="utf-8")


def blocked_entry(text):
    """Why an entry can never be used, or None."""
    lowered = str(text).casefold()
    if word := minor_reference(lowered):
        return word
    if word := broken_anatomy(lowered):
        return word
    match = _BLOCKED.search(lowered)
    return match.group() if match else None


def parse_vocabulary(text):
    """Sections of usable entries; requested entries are (pattern, entry) pairs."""
    sections, current = {}, None
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = " ".join(line[1:-1].casefold().split())
            current = name if name in SECTIONS else None
            continue
        if current is None:
            continue
        if current == "requested":
            pattern, separator, entry = line.partition("=>")
            pattern, entry = pattern.strip(), entry.strip()
            if not separator or not pattern or not entry or blocked_entry(entry):
                continue
            try:
                compiled = re.compile(pattern, re.I)
            except re.error:
                compiled = re.compile(re.escape(pattern), re.I)
            sections.setdefault(current, []).append((compiled, entry))
        elif not blocked_entry(line):
            sections.setdefault(current, []).append(line)
    return {name: tuple(dict.fromkeys(entries)) for name, entries in sections.items()}


_cache = {}


def load_vocabulary(path=None):
    """The current file's sections, re-read whenever it changes; empty when it is absent or unreadable."""
    path = Path(path) if path is not None else vocabulary_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        sections = parse_vocabulary(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return {}
    _cache[path] = (stamp, sections)
    return sections


def private_rules(data):
    """The file's extra rule lines for this batch, as a prompt section, or an empty string."""
    if not sexual_request(data):
        return ""
    vocabulary = load_vocabulary()
    lines = list(vocabulary.get("rules", ())) + (list(vocabulary.get("ownership rules", ()))
                                                  if ownership_request(data) else [])
    return ("\n\nMORE SEXUAL CONTENT RULES\n" + "\n".join(f"- {line}" for line in lines)) if lines else ""
