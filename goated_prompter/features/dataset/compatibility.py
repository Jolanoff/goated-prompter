"""Small section gates and conservative TXT compatibility checks before planning."""

from dataclasses import dataclass, replace
import hashlib
import re

from .modules import ACCESSORY_FAMILIES, EQUIPMENT, GENERIC_PROPS, SECTION_MODULES, SWITCHES
from .modules import position_sections as module_position_sections, styling_sections as module_styling_sections
from .quality import POSITION_ACT_CATEGORIES, activity_categories, position_categories, requested_clothing_state


@dataclass(frozen=True)
class PositionCandidate:
    id: str
    category: str
    label: str
    section: str
    participants: tuple = ()
    contacts: tuple = ()


_CAST_SECTIONS = {("male", "male"): "two men positions", ("female", "female"): "two women positions",
                  ("female", "male"): "man and woman positions", ("male", "female"): "man and woman positions"}
CAST_SEX_SECTIONS = frozenset(_CAST_SECTIONS.values())
# Person words that tie an entry to a sex; neutral wording can serve any cast of the same size.
_MALE_WORDS = re.compile(r"\b(?:he|him|his|himself|man|men|male|males|guy|guys|boy|boys|master|husband|boyfriend|king|daddy)\b")
_FEMALE_WORDS = re.compile(r"\b(?:she|her|hers|herself|woman|women|female|females|girl|girls|lady|ladies|mistress|wife|"
                           r"girlfriend|queen|dominatrix)\b")


# Wording that needs a second person: a partnered position or an act someone else performs.
# Machines, toys and restraints are not partners.
_PARTNER_WORDS = re.compile(r"\b(?:missionary|cowgirl|doggy|mating press|prone bone|spooning|spit[- ]?roast\w*|sixty[- ]?nine|"
                            r"fuck(?:ed|ing)? (?:from|while)|fucked by (?!a (?:\w+ )?machine)|"
                            r"being (?:fucked|taken|used|licked|kissed|held|spanked|choked)\b(?! by (?:a |the )?(?:\w+ )?(?:machine|toy|rope|strap)s?)|"
                            r"(?:licking|licked|kissing|kissed|sucking|sucked|worshipp?(?:ed|ing))\b(?! (?:her|his|their) own)|"
                            r"in (?:his|her|the|a) (?:mouth|lap|hand)s?|toes in mouth|on (?:the|his|her) chest|"
                            r"(?<!mouth )held (?:open|down|by)\b(?! (?:a |the )?(?:rope|strap|cuff|chain|gag)s?)|"
                            r"(?:ankles?|wrists?|legs?|hips?|thighs?) (?:held|pinned|grabbed)\b(?! (?:by|with|in) (?:a |the )?(?:rope|strap|cuff|chain|spreader)s?)|"
                            r"pull(?:s|ed|ing)? out|buried (?:deep|inside)|still (?:thrusting|connected|inside)|"
                            r"cumming (?:deep )?inside|creampie\w*|facials?|swallow\w*|"
                            r"during (?:sex|penetration)|with the tongue|"
                            r"master'?s?|mistress'?s?|owner'?s?|the others?|each other|one (?:man|woman|partner)\b|"
                            r"both\b(?! (?:hands|feet|legs|knees|soles|ankles|wrists|breasts|nipples|holes|arms))|"
                            r"being (?:walked|petted|praised|scratched|groomed|shown|fingered|mounted|fed|served|watched|filled|made|teased)|"
                            r"mounted\b(?! (?:on|onto) (?:a |the )?(?:\w+ )?(?:toy|dildo|machine|sybian)s?)|"
                            r"\bused\b|leash (?:held|pulled|tugged)|scissor\w*|tribb\w*)")
# Semen on a lone body must come from that body: its own, or while masturbating or using a toy.
_SOLO_SEMEN = re.compile(r"\b(?:own|masturbat\w*|stroking|toy|dildo)\b")
_BREASTS = re.compile(r"\b(?:breasts?|tits|boobs|cleavage)\b")
# Feminization and chastity cages describe a man.
_MALE_ONLY = re.compile(r"\b(?:sissy|sissies|feminiz\w*|crossdress\w*|chastity cages?|cage locked|cage on)\b")
# Semen needs someone with a penis in the cast; "cumming" alone is anyone's orgasm.
_SEMEN = re.compile(r"\b(?:cum|cumshots?|semen|jizz|creampie\w*)\b")
# Wording that needs three or more people, without a number.
_GROUP_WORDS = re.compile(r"\b(?:group|the others|several partners|multiple (?:partners|men|women|people)|"
                          r"spit[- ]?roast\w*|double[- ]team\w*|gangbang\w*|bukkake\w*|orgy|"
                          r"cent(?:er|re) (?:partner|receiver)|both partners)\b")


def gender_neutral(text):
    text = str(text).casefold()
    return not (_MALE_WORDS.search(text) or _FEMALE_WORDS.search(text))


def position_sections(route):
    count = len(route.position_slots)
    if not route.vocabulary_applicable:
        return set()
    sections = {"solo positions"} if count == 1 else {"couple positions"} if count == 2 else {
        "three positions" if count == 3 else "group positions"}
    if count == 2:
        # Another cast's section is a hint: only its gender-neutral entries are reused (compatible_arrangements).
        sections.update(CAST_SEX_SECTIONS)
    eligible = POSITION_ACT_CATEGORIES - route.excluded
    sections.update(f"{act} positions" for act in (eligible if count > 1 else route.required & eligible))
    sections.update(module_position_sections(route.enabled - route.excluded, count))
    return sections


def own_cast_section(route):
    sexes = tuple(route.sexes[slot] for slot in route.position_slots)
    return _CAST_SECTIONS.get(sexes) if len(sexes) == 2 else None


def anatomy_from(sex, traits=""):
    """Default sex anatomy plus only explicitly supplied exceptions."""
    parts = {"penis"} if sex == "male" else {"vagina"} if sex == "female" else set()
    traits = str(traits or "").casefold()
    for part, pattern in (("penis", r"penis|cock|dick"), ("vagina", r"vagina|vulva|pussy")):
        if re.search(rf"\b(?:no|without|lacks?) (?:a |an )?(?:{pattern})\b", traits):
            parts.discard(part)
        elif re.search(rf"\b(?:{pattern})\b", traits):
            parts.add(part)
    return parts


def participant_anatomy(route):
    """Default sex anatomy plus only explicitly supplied exceptions, per owner."""
    subjects = [item for item in route.subjects for _ in range(item["count"])]
    return [(route.sexes[slot], anatomy_from(route.sexes[slot], subjects[slot].get("traits", "") if slot < len(subjects) else ""))
            for slot in route.position_slots]


# "Bondage" names restraint itself, so it permits rope and restraint hardware.
_ACCESSORY_ALIASES = {"rope": re.compile(r"\bbondage\b")}


def positive_clauses(text):
    return "\n".join(clause for clause in re.split(r"[.!?;\n,]", str(text).casefold())
                     if not re.search(r"\b(?:no|not|without|avoid|never)\b", clause))


def accessory_families(text):
    text = str(text).casefold()
    return {name for name, pattern in ACCESSORY_FAMILIES.items() if pattern.search(text)}


def permitted_accessories(route):
    """Object families an entry may show. Equipment needs Props and is limited to the families the
    request names (all of them for a generic request); clothing appears only when named; toys follow Toys."""
    positive = positive_clauses(route.request_text)
    named = accessory_families(positive) | {name for name, pattern in _ACCESSORY_ALIASES.items() if pattern.search(positive)}
    permitted = named & {"clothing"}
    if "toys" in route.enabled:
        permitted.add("toys")
    if "props" in route.enabled:
        permitted |= named & EQUIPMENT or EQUIPMENT
    return permitted


def compatible_entry(text, route, *, category="general", position=False, clothing_detail=False):
    """Reject clear contradictions; the model resolves prose, not a new geometry schema."""
    text = text.casefold()
    categories, _ = position_categories({"subject": text}, include_director=False)
    acts = activity_categories(text)
    if category in POSITION_ACT_CATEGORIES:
        acts.add(category)
    if categories & route.excluded or acts & route.excluded:
        return False
    # Every switch is independent: an entry using a module's content needs that module enabled.
    if (categories & set(SWITCHES)) - route.enabled:
        return False
    if accessory_families(text) - permitted_accessories(route):
        return False
    count = len(route.position_slots)
    if count < 3 and _GROUP_WORDS.search(text):
        return False
    for match in re.finditer(r"\b(one|two|three|four|five|\d+) (?:adult )?(?:people|persons?|participants?|adults?|partners?)\b", text):
        needed = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(match[1], int(match[1]) if match[1].isdigit() else 1)
        if needed > count:
            return False
    if count == 1 and (re.search(r"\b(?:partners?|couple|another (?:person|man|woman)|two (?:men|women|people)|69|sixty-nine|face[- ]?sitting)\b", text)
                       or _PARTNER_WORDS.search(text)
                       or acts and not re.search(r"\b(?:solo|self|own)\b", text)):
        return False
    anatomy = participant_anatomy(route)
    sexes = {sex for sex, _ in anatomy}
    if "unspecified" not in sexes and (_MALE_WORDS.search(text) and "male" not in sexes
                                       or _FEMALE_WORDS.search(text) and "female" not in sexes):
        return False
    for sex, pattern in (("male", r"men|man|male"), ("female", r"women|woman|female")):
        available = sum(item[0] == sex for item in anatomy)
        if re.search(rf"\banother (?:adult )?(?:{pattern})\b", text) and available < 2:
            return False
        for match in re.finditer(rf"\b(?:(one|two|three|four|five|\d+) (?:adult )?)?({pattern})\b", text):
            needed = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(match[1], int(match[1]) if (match[1] or "").isdigit() else 1)
            if needed > available and not any(item[0] == "unspecified" for item in anatomy):
                return False
    if _SEMEN.search(text) and (not any("penis" in parts for _, parts in anatomy)
                                or count == 1 and not _SOLO_SEMEN.search(text)):
        return False
    if _BREASTS.search(text) and not any(sex in {"female", "unspecified"} for sex, _ in anatomy):
        return False
    if _MALE_ONLY.search(text) and not any(sex in {"male", "unspecified"} for sex, _ in anatomy):
        return False
    for part, pattern in (("penis", r"penis(?:es)?|cocks?|dicks?|fellatio|blowjobs?"),
                          ("vagina", r"vagina|vulva|pussy|cunnilingus|clit\w*|labia|squirt\w*")):
        if re.search(rf"\b(?:{pattern})\b", text) and not any(part in parts for _, parts in anatomy):
            return False
        for sex, owner in (("female", r"her|woman's|female's"), ("male", r"his|man's|male's")):
            if re.search(rf"\b(?:{owner}) (?:\w+ )?(?:{pattern})\b", text) and not any(
                    actual == sex and part in parts for actual, parts in anatomy):
                return False
        for match in re.finditer(rf"\b(two|three|four|\d+) (?:{pattern})\b", text):
            needed = {"two": 2, "three": 3, "four": 4}.get(match[1], int(match[1]) if match[1].isdigit() else 1)
            if needed > sum(part in parts for _, parts in anatomy):
                return False
    if "vaginal" in acts and not any("vagina" in parts for _, parts in anatomy):
        return False
    if "vaginal" in acts and not re.search(r"\b(?:hand|finger|toy|dildo|vibrator|strap[- ]?on)\w*\b", text):
        if not any("penis" in source and "vagina" in target for i, (_, source) in enumerate(anatomy)
                   for j, (_, target) in enumerate(anatomy) if i != j):
            return False
    # Literal exclusions also apply outside activity categories (e.g. a forbidden setting).
    for match in re.finditer(r"\b(?:no|without|avoid)\s+([^.!?;\n,]+)", route.request_text.casefold()):
        excluded = re.split(r"\b(?:but|or|and)\b", match[1])[0].strip().removesuffix(" allowed")
        if excluded and re.search(r"\b" + re.escape(excluded) + r"\b", text):
            return False
    clothing = requested_clothing_state(route.request_text)
    if clothing == "nude" and clothing_detail and re.search(r"\b(?:tops?|bottoms?)\b", text):
        return False
    if clothing == "nude" and re.search(r"\b(?:wear\w*|clothed|clothing|lingerie|dress(?:es)?|shirts?|pants|outfits?|uniforms?|"
                                       r"bras?|skirts?|robes?|bikinis?|corsets?|stockings?|jeans|jackets?|underwear|underpants)\b", text):
        return False
    if clothing == "clothed" and re.search(r"\b(?:nude|naked|unclothed|topless|bottomless|undress\w*)\b", text):
        return False
    if clothing == "clothed" and clothing_detail and re.search(
            r"\b(?:pulled|slid|pushed|rolled) (?:down|off|aside)\b|\b(?:tops?|bottoms?) (?:off|removed)\b|"
            r"\bcrop(?:ped)?[- ]tops?\b|\bbarely cover\w*\b", text):
        return False
    return True


def styling_sections(route):
    """Universal sections stay universal; each optional module adds only its own registry sections."""
    sections = {"setting": ["setting"], "mood": ["mood"], "clothing": ["clothing"]}
    if len(route.position_slots) > 1:
        # Interaction stays an optional hint; it never overrides the chosen activity or position.
        sections["interaction"] = ["interaction"]
        if len(route.position_slots) >= 3:
            sections["interaction"].append("group interaction")
    for axis, section in module_styling_sections(route.enabled - route.excluded):
        if axis in sections or axis == "prop":
            sections.setdefault(axis, []).append(section)
    return sections


def vocabulary_choices(catalog, route, record, alternatives, rng, used):
    """The selected position, the planner's alternatives and a few compatible details, never whole sections."""
    selected_route = replace(route, categories=route.categories | ({record.category} if record else set()))
    choices = {}
    if record:
        labels = [item.label[:240] for item in alternatives if item.label != record.label]
        choices["position_candidates"] = "\n".join(dict.fromkeys([record.label[:240], *labels[:2]]))
        if record.category in POSITION_ACT_CATEGORIES | set(SWITCHES):
            choices["activity"] = record.category
        if record.category == "finish" and len(route.categories & POSITION_ACT_CATEGORIES) == 1:
            choices["activity"] = next(iter(route.categories & POSITION_ACT_CATEGORIES))
    for axis, sections in styling_sections(route).items():
        values = list(dict.fromkeys(text for section in sections for text in catalog.get(section, ())
                                    if compatible_entry(text, selected_route, clothing_detail=axis == "clothing")))
        rng.shuffle(values)
        if axis == "setting":
            key = record.label if record else ""
            fresh = [text for text in values if (key, text) not in used]
            values = fresh or values
            if values:
                used.add((key, values[0]))
        if values:
            choices[axis] = values[0][:240]
    return choices


def bind_arrangement(record, route, constraints):
    """Match template owners to approved slots without changing either owner's attributes."""
    if len(record.participants) != len(route.position_slots):
        return record
    subjects = [item for item in route.subjects for _ in range(item["count"])]
    anatomy = dict(zip(route.position_slots, (parts for _, parts in participant_anatomy(route))))
    approved_endpoints = {endpoint for constraint in constraints for contact in constraint["contacts"]
                          for endpoint in (contact["source"], contact["target"])}
    edges = []
    for number, participant in enumerate(record.participants):
        parts = [endpoint.split(".")[1] for contact in record.contacts for endpoint in (contact.source, contact.target)
                 if endpoint.split(".")[0] == participant.id]
        available = []
        for slot in route.position_slots:
            if participant.sex not in {"unspecified", route.sexes[slot]}:
                continue
            if participant.traits and (slot >= len(subjects) or participant.traits != subjects[slot].get("traits", "")):
                continue
            if any(part in {"penis", "vagina"} and part not in anatomy[slot]
                   and f"P{slot + 1}.{part}" not in approved_endpoints for part in parts):
                continue
            if any(item["id"] == f"P{slot + 1}" and any(item[field] is not None and item[field] != getattr(participant, field)
                for field in ("role", "pose", "location", "support")) for constraint in constraints for item in constraint["participants"]):
                continue
            available.append(slot)
        original = route.position_slots[number]
        edges.append(sorted(available, key=lambda slot: (slot != original, slot)))
    assigned = {}
    def place(number, seen):
        for slot in edges[number]:
            if slot in seen:
                continue
            seen.add(slot)
            if slot not in assigned or place(assigned[slot], seen):
                assigned[slot] = number
                return True
        return False
    for number in sorted(range(len(edges)), key=lambda index: len(edges[index])):
        if not place(number, set()):
            return record
    return replace(record, participants=tuple(record.participants[assigned[slot]] for slot in route.position_slots))


def entry_key(text):
    """Identical vocabulary lines share one identity, whatever section lists them."""
    return " ".join(re.findall(r"\w+", str(text).casefold()))


def compatible_arrangements(catalog, route, *, constraints=()):
    eligible, rejected = [], []
    subjects = [item for item in route.subjects for _ in range(item["count"])]
    anatomy = dict(zip(route.position_slots, (parts for _, parts in participant_anatomy(route))))
    sections = position_sections(route)
    own = own_cast_section(route)
    records = list(catalog.records)
    legacy = {(item.section, item.label) for item in records}
    # One entry per distinct line: the same position listed under several sections is offered once.
    texts = {}
    for section in sorted(sections):
        for text in catalog.get(section, ()):
            if (section, text) in legacy or (section in CAST_SEX_SECTIONS and section != own and not gender_neutral(text)):
                continue
            texts.setdefault(entry_key(text), (text, []))[1].append(section)
    preference = [*sorted(route.required), *sorted(route.asked), *sorted(POSITION_ACT_CATEGORIES), *SWITCHES]
    for key, (text, found) in texts.items():
        categories = activity_categories(text)
        named = [SECTION_MODULES.get(section, section.removesuffix(" positions")) for section in found]
        named = [name for name in preference if name in named]
        category = next(iter(categories)) if len(categories) == 1 else named[0] if named else (
            "paired_pose" if len(route.position_slots) == 2 else "group_pose" if len(route.position_slots) > 2 else "solo")
        records.append(PositionCandidate(hashlib.sha256(key.encode()).hexdigest(), category, text, found[0]))
    for pattern, text in catalog.get("requested", ()):
        positive = positive_clauses(route.user_text or route.request_text)
        if route.vocabulary_applicable and pattern.search(positive):
            categories = activity_categories(text)
            category = next(iter(categories)) if len(categories) == 1 else "general"
            records.append(PositionCandidate(hashlib.sha256(text.encode()).hexdigest(), category, text, "requested"))
    for number, record in enumerate(records, 1):
        if record.section not in sections | {"requested"} or (
                record.participants and record.section in CAST_SEX_SECTIONS and record.section != own
                and not gender_neutral(record.label)):
            rejected.append({"record": number, "rule": "inactive_section", "reason": "Section is not active for this request."})
            continue
        if not record.participants:
            if compatible_entry(record.label, route, category=record.category, position=True):
                eligible.append(record)
            else:
                rejected.append({"record": number, "rule": "incompatible_entry",
                                 "reason": "Entry conflicts with the cast, request or active theme."})
            continue
        record = bind_arrangement(record, route, constraints)
        reason = None
        if not route.vocabulary_applicable and route.subjects:
            reason = "irrelevant_subjects"
        elif len(record.participants) != len(route.position_slots):
            reason = "participant_count"
        elif record.category in route.excluded:
            reason = "excluded_category"
        elif record.category in SWITCHES and record.category not in route.enabled:
            reason = "requested_category"
        elif any(item.sex not in {"unspecified", route.sexes[slot]} for item, slot in zip(record.participants, route.position_slots)):
            reason = "participant_sex"
        elif any(item.traits and item.traits != subjects[slot].get("traits", "")
                 for item, slot in zip(record.participants, route.position_slots) if slot < len(subjects)):
            reason = "participant_attributes"
        else:
            mapped = {f"P{slot + 1}": item for slot, item in zip(route.position_slots, record.participants)}
            owners = {item.id: f"P{slot + 1}" for slot, item in zip(route.position_slots, record.participants)}
            def bind(endpoint):
                owner, part = endpoint.split(".")
                return owners[owner] + "." + part
            contacts = {(bind(item.source), bind(item.target)) for item in record.contacts}
            approved_endpoints = {endpoint for constraint in constraints for contact in constraint["contacts"]
                                  for endpoint in (contact["source"], contact["target"])}
            for source, target in contacts:
                for endpoint in (source, target):
                    owner, part = endpoint.split(".")
                    if part in {"penis", "vagina"} and part not in anatomy[int(owner[1:]) - 1] and endpoint not in approved_endpoints:
                        reason = "participant_anatomy"
            for constraint in constraints:
                for participant in constraint["participants"]:
                    candidate = mapped.get(participant["id"])
                    if candidate is not None and any(participant[field] is not None and getattr(candidate, field) != participant[field]
                                                for field in ("role", "pose", "location", "support")):
                        reason = "approved_mechanics"
                if not {(item["source"], item["target"]) for item in constraint["contacts"]
                        if item["source"].split(".")[0] in mapped and item["target"].split(".")[0] in mapped} <= contacts:
                    reason = "approved_mechanics"
            if not reason and not compatible_entry(record.label, route, category=record.category, position=True):
                reason = "requested_category"
        if reason:
            rejected.append({"record": number, "rule": reason, "reason": {
                "irrelevant_subjects": "Specialized arrangements do not apply to these subjects.",
                "participant_attributes": "The arrangement requires attributes not approved for these subjects.",
                "participant_anatomy": "The arrangement needs anatomy not established for its approved owner.",
                "participant_count": "The arrangement needs a different participant count.",
                "excluded_category": "The request excludes this category.",
                "requested_category": "The arrangement does not explicitly match a requested category.",
                "participant_sex": "The arrangement's owned roles do not match the approved cast.",
                "approved_mechanics": "The arrangement conflicts with approved participant or contact requirements.",
            }[reason]})
        else:
            eligible.append(record)
    return eligible, rejected


def vocabulary_diagnostics(catalog, route, *, constraints=()):
    eligible, rejected = compatible_arrangements(catalog, route, constraints=constraints)
    diagnostics = [*catalog.diagnostics, *rejected]
    unresolved = [item["reason"] for item in catalog.diagnostics if item["rule"] in {"unreadable", "unavailable"}]
    return {"loaded": catalog.loaded, "eligible": len(eligible),
             "rejected": len({("line", item["line"]) if "line" in item else ("record", item["record"])
                              for item in diagnostics if ("line" in item or "record" in item) and item["rule"] != "unknown_section"}),
            "diagnostics": list(catalog.diagnostics)[:8], "unresolved_constraints": list(dict.fromkeys(unresolved)),
            "filtering_rules": ["Approved cast and explicitly supplied anatomy", "Requested activities and exclusions",
                                "Specialized themes only when requested", "Small TXT selections; creative guidance, not requirements"]}
