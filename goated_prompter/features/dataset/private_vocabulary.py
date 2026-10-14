"""Adult Dataset vocabulary, read from a private plain-text file the user keeps in data/.

The original sectioned TXT is creative guidance, not a source of user requirements.
Only small compatible selections reach generation. Legacy inline records remain readable;
generation does not need conversion, sidecars or per-entry approval.
"""

import json
from dataclasses import dataclass, replace
import os
from pathlib import Path
import re

from ...config import PROJECT_ROOT
from .quality import broken_anatomy, minor_reference, ownership_request, sexual_request
from .routing import assignment_scope, resolve_route, scoped_request
from .compatibility import compatible_entry
from .scene_spec import BODY_PARTS, Contact, LOCATIONS, Participant, POSE_SUPPORTS, SceneSpec, PLANNING_CATEGORIES, validate_scene_mechanics
from ...strict_json import reject_duplicate_keys
from ...json_store import MAX_STORE_BYTES

VOCABULARY_FILE_ENV = "GOATED_PROMPTER_VOCABULARY_FILE"

# What each [section] is used for. Unknown sections are ignored.
SECTIONS = {
    "rules": "extra rule lines for every sexual batch",
    "ownership rules": "extra guidance when the request uses ownership language",
    "mood": "moods for every sexual batch",
    "interaction": "dynamics between partners for multiple-character sexual batches",
    "group interaction": "dynamics for three or more people",
    "setting": "places for every compatible sexual batch",
    "clothing": "clothing states compatible with requested clothing or nudity",
    "kink mood": "moods when kink or ownership is requested",
    "kink interaction": "dynamics when kink or ownership is requested",
    "kink setting": "places when kink or ownership is requested",
    "kink clothing": "clothing states when kink or ownership is requested",
    "pet mood": "moods when pet play is requested",
    "pet interaction": "dynamics when pet play is requested",
    "props": "equipment and costume props, only when props are requested",
    "solo positions": "one person",
    "couple positions": "two people of any sex",
    "two men positions": "two men",
    "two women positions": "two women",
    "man and woman positions": "a man and a woman",
    "three positions": "three people",
    "group positions": "four or more people",
    "oral positions": "oral positions compatible with the cast",
    "anal positions": "anal positions compatible with the cast",
    "vaginal positions": "vaginal activities compatible with the participants' actual anatomy",
    "feet positions": "feet positions for multiple people",
    "solo feet positions": "feet positions for one person",
    "toys": "toy positions compatible with the cast; eligible by default in solo scenes",
    "finish positions": "climax and finish moments compatible with the cast",
    "kink positions": "kink positions for multiple people",
    "solo kink positions": "kink positions for one person",
    "pet positions": "cast-compatible positions when human pet roleplay is requested",
    "furniture positions": "cast-compatible positions when a human-furniture theme is requested",
    "aftercare positions": "kept readable for older files; no longer selected",
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
# Changes apply to the next batch without a restart. Positions are selected per image;
# explicit acts narrow the pool; broad requests use ordinary compatible activities.
# Entries about minors, non-consent, death, family members, animals,
# school, breath restriction or injury, or that detach or merge body parts, are skipped.
# Plain position descriptions are enough. No conversion or approval is needed.
# The model resolves selected guidance into one scene while preserving your request.
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


@dataclass(frozen=True)
class Arrangement:
    id: str
    category: str
    participants: tuple[Participant, ...]
    contacts: tuple[Contact, ...]
    label: str
    section: str


class Vocabulary(dict):
    """Private TXT sections, legacy inline records and content-free diagnostics."""

    def __init__(self, sections=(), *, records=(), diagnostics=(), loaded=0):
        super().__init__(sections)
        self.records = tuple(records)
        self.diagnostics = tuple(diagnostics)
        self.loaded = loaded


def compile_arrangement(value, section):
    if section not in SECTIONS or not (section.endswith("positions") or section == "toys"):
        raise ValueError("Position records need a recognized position category section.")
    fields = {"id", "category", "participantCount", "participants", "contacts", "physicalConstraints"}
    if not isinstance(value, dict) or not fields <= value.keys() or value.keys() - fields - {"label"}:
        raise ValueError("Position records need id, category, participantCount, participants, contacts and physicalConstraints.")
    if blocked_entry(json.dumps(value, ensure_ascii=False)):
        raise ValueError("Decoded record contains blocked content.")
    count, participants, supports = value["participantCount"], value["participants"], value["physicalConstraints"]
    if (type(count) is not int or not 1 <= count <= 100 or not isinstance(participants, dict)
            or len(participants) != count or not isinstance(supports, dict) or set(supports) != set(participants)):
        raise ValueError("Participant count, owners and physical supports must agree.")
    required_count = {"solo positions": 1, "solo kink positions": 1, "solo feet positions": 1, "couple positions": 2,
                      "two men positions": 2, "two women positions": 2, "man and woman positions": 2,
                      "three positions": 3}.get(section)
    if required_count is not None and count != required_count or section == "group positions" and count < 4:
        raise ValueError("Participant count conflicts with the vocabulary section.")
    sexes = [item.get("sex", "unspecified") for item in participants.values() if isinstance(item, dict)]
    if (section == "two men positions" and any(sex not in {"male", "unspecified"} for sex in sexes)
            or section == "two women positions" and any(sex not in {"female", "unspecified"} for sex in sexes)
            or section == "man and woman positions" and "unspecified" not in sexes and sorted(sexes) != ["female", "male"]):
        raise ValueError("Declared participant sexes conflict with the vocabulary section.")
    category = value["category"]
    if not isinstance(category, str) or category not in PLANNING_CATEGORIES - {"general"}:
        raise ValueError("Unknown position category.")
    cast = []
    for owner, item in participants.items():
        if not isinstance(item, dict) or not {"pose", "location"} <= item.keys() or item.keys() - {"pose", "location", "role", "sex", "traits"}:
            raise ValueError("Each owner needs pose and location, with optional role, sex and traits.")
        if not item["pose"] or not item["location"] or not supports[owner]:
            raise ValueError("Vocabulary geometry requires resolved poses, locations and support.")
        if (not isinstance(item["pose"], str) or item["pose"] not in POSE_SUPPORTS
                or not isinstance(item["location"], str) or item["location"] not in LOCATIONS
                or not isinstance(supports[owner], str) or supports[owner] not in POSE_SUPPORTS[item["pose"]]
                or not isinstance(item.get("role", "participant"), str)
                or item.get("role", "participant") not in {"participant", "performer", "receiver"}):
            raise ValueError("Vocabulary mechanics require normalized owned roles, poses, locations and supports.")
        cast.append({"id": owner, "name": owner, "role": item.get("role", "participant"),
                     "pose": item["pose"], "location": item["location"], "support": supports[owner],
                     "sex": item.get("sex", "unspecified"), "traits": item.get("traits", "")})
    if not isinstance(value["contacts"], list) or any(not isinstance(item, dict) or set(item) != {"from", "to"}
                                                   for item in value["contacts"]):
        raise ValueError("Contacts need from/to owned body-part endpoints.")
    template = SceneSpec.from_dict({"index": 1, "route": "adult", "action": category,
        "participants": cast, "contacts": [{"source": item["from"], "target": item["to"]} for item in value["contacts"]],
        "setting": "", "hard": [], "choices": {}, "catalog_id": value["id"],
        "locked": ["action", "participants", "contacts", "hard"], "version": 1, "category": category})
    validate_scene_mechanics(template)
    if any(endpoint.split(".")[1] not in BODY_PARTS for contact in template.contacts
           for endpoint in (contact.source, contact.target)):
        raise ValueError("Specialized vocabulary needs normalized body-part endpoints.")
    act_parts = {"oral": ({"mouth"}, {"penis", "vagina", "genitals", "anus"}),
                 "anal": ({"penis", "genitals", "hand", "left_hand", "right_hand"}, {"anus"}),
                 "vaginal": ({"penis", "genitals", "hand", "left_hand", "right_hand"}, {"vagina"}),
                 "feet": ({"mouth", "feet"}, {"feet", "penis", "genitals"})}
    if category in act_parts:
        sources, targets = act_parts[category]
        if not any(item.source.split(".")[1] in sources and item.target.split(".")[1] in targets
                   for item in template.contacts):
            raise ValueError("The category needs explicit owned contact defining its interaction.")
        defining = next(item for item in template.contacts if item.source.split(".")[1] in sources
                        and item.target.split(".")[1] in targets)
        performer, receiver = defining.source.split(".")[0], defining.target.split(".")[0]
        if any(item.role not in {"participant", "performer" if item.id == performer else "receiver" if item.id == receiver else "participant"}
               for item in template.participants):
            raise ValueError("Participant roles contradict the owned defining contact.")
        template = replace(template, participants=tuple(replace(item, role=("performer" if item.id == performer
            else "receiver" if item.id == receiver else "participant")) if item.role == "participant" else item
            for item in template.participants))
    if not isinstance(value["id"], str) or not value["id"] or len(value["id"]) > 240:
        raise ValueError("Position records need a compact stable id.")
    label = value.get("label", value["id"])
    if not isinstance(label, str) or not label.strip() or len(label) > 240:
        raise ValueError("Position labels must be compact text.")
    return Arrangement(value["id"], category, template.participants, template.contacts,
                        label, section)


def parse_vocabulary(text):
    """Sections of usable entries; requested entries are (pattern, entry) pairs."""
    sections, current, records, diagnostics, loaded = {}, None, [], [], 0
    def reject(number, entry, rule, reason):
        diagnostics.append({"line": number, "rule": rule, "reason": reason})
    for number, raw in enumerate(str(text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = " ".join(line[1:-1].casefold().split())
            current = name if name in SECTIONS else None
            if current is None:
                reject(number, name, "unknown_section", "Unknown vocabulary section.")
            continue
        loaded += 1
        if current is None:
            reject(number, line, "missing_section", "Entry has no recognized section.")
            continue
        if blocked_entry(line):
            reject(number, line, "blocked_content", "Entry contains blocked content.")
            continue
        position_section = current.endswith("positions") or current in {"toys", "requested"}
        if position_section and line.startswith("{"):
            try:
                if current == "requested":
                    raise ValueError("Structured records need a category section, not an unrestricted requested pattern.")
                record = compile_arrangement(json.loads(line, object_pairs_hook=reject_duplicate_keys(
                    "Vocabulary record contains duplicate fields.")), current)
                if any(existing.id == record.id for existing in records):
                    raise ValueError("Position id is already defined.")
            except (ValueError, TypeError, KeyError) as exc:
                reject(number, line, "invalid_record", str(exc))
                continue
            records.append(record)
            sections.setdefault(current, []).append(record.label)
            continue
        if current == "requested":
            pattern, separator, entry = line.partition("=>")
            pattern, entry = pattern.strip(), entry.strip()
            if not separator or not pattern or not entry or blocked_entry(entry):
                reject(number, line, "invalid_requested", "Requested entries require pattern => entry.")
                continue
            try:
                compiled = re.compile(pattern, re.I)
            except re.error:
                compiled = re.compile(re.escape(pattern), re.I)
            sections.setdefault(current, []).append((compiled, entry))
        elif not blocked_entry(line):
            sections.setdefault(current, []).append(line)
    return Vocabulary({name: tuple(dict.fromkeys(entries)) for name, entries in sections.items()},
                      records=records, diagnostics=diagnostics, loaded=loaded)


_cache = {}


def load_vocabulary(path=None):
    """The current file's sections, re-read whenever it changes; empty when it is absent or unreadable."""
    path = Path(path) if path is not None else vocabulary_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return Vocabulary(diagnostics=({"rule": "unavailable", "reason": "Vocabulary file is missing or inaccessible."},))
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        with path.open("rb") as stream:
            source = stream.read(MAX_STORE_BYTES + 1)
        if len(source) > MAX_STORE_BYTES:
            raise OSError("Vocabulary size limit exceeded.")
        sections = parse_vocabulary(source.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return Vocabulary(diagnostics=({"rule": "unreadable", "reason": "Vocabulary file could not be read as UTF-8."},))
    _cache[path] = (stamp, sections)
    return sections


def private_rules(data, *, indexes=None):
    """Optional rule guidance, explicitly limited to the applicable supplied assignments."""
    indexes = range(1, data.get("amount", 1) + 1) if indexes is None else indexes
    applicable = [(index, scoped_request(data, assignment_scope(data, index)), resolve_route(data, assignment_scope(data, index)))
                  for index in indexes]
    applicable = [(index, request, route) for index, request, route in applicable if sexual_request(request, include_director=False)]
    if not applicable:
        return ""
    vocabulary = load_vocabulary()
    sections = []
    for name, label, selected in (
            ("rules", "General", [index for index, _, _ in applicable]),
            ("ownership rules", "Ownership", [index for index, request, _ in applicable
                                               if ownership_request(request, include_director=False)])):
        # Rules are guidance too; never send an unbounded section to the model.
        lines = []
        for line in vocabulary.get(name, ()):
            indexes = [index for index, _, route in applicable if index in selected and compatible_entry(line, route)]
            if indexes:
                lines.append(f"- {line[:240]} (assignment indexes: {', '.join(map(str, indexes))})")
                if len(lines) == 4:
                    break
        if lines:
            sections.append(f"{label} guidance:\n" + "\n".join(lines))
    return ("\n\nMORE SEXUAL CONTENT RULES\n"
             "Optional vocabulary guidance for applicable adult assignments only. Approved hard requirements,\n"
             "SceneSpec, compatible soft preferences and Director defaults take precedence. Never add an unrequested act.\n"
            + "\n".join(sections)) if sections else ""
