"""Small section gates and conservative TXT compatibility checks before planning."""

from dataclasses import dataclass, replace
import hashlib
import re

from .quality import POSITION_ACT_CATEGORIES, activity_categories, position_categories, requested_clothing_state


@dataclass(frozen=True)
class PositionCandidate:
    id: str
    category: str
    label: str
    section: str
    participants: tuple = ()
    contacts: tuple = ()


def position_sections(route):
    count = len(route.position_slots)
    if not route.vocabulary_applicable:
        return set()
    sections = {"solo positions"} if count == 1 else {"couple positions"} if count == 2 else {
        "three positions" if count == 3 else "group positions"}
    sexes = [route.sexes[slot] for slot in route.position_slots]
    if count == 2:
        paired = {("male", "male"): "two men positions", ("female", "female"): "two women positions",
                  ("female", "male"): "man and woman positions", ("male", "female"): "man and woman positions"}
        if section := paired.get(tuple(sexes)):
            sections.add(section)
    if count > 1:
        sections.update({"oral positions", "anal positions", "vaginal positions"})
    for category in route.categories - route.excluded:
        if category == "kink":
            sections.add("solo kink positions" if count == 1 else "kink positions")
        elif category in {"pet", "furniture", "feet", "finish", "aftercare"}:
            sections.add(category + " positions")
        elif category == "toys":
            sections.add("toys")
        elif count == 1 and category in POSITION_ACT_CATEGORIES:
            sections.add(category + " positions")
    return sections


def participant_anatomy(route):
    """Default sex anatomy plus only explicitly supplied exceptions, per owner."""
    subjects = [item for item in route.subjects for _ in range(item["count"])]
    result = []
    for slot in route.position_slots:
        parts = {"penis"} if route.sexes[slot] == "male" else {"vagina"} if route.sexes[slot] == "female" else set()
        traits = subjects[slot].get("traits", "").casefold() if slot < len(subjects) else ""
        for part, pattern in (("penis", r"penis|cock|dick"), ("vagina", r"vagina|vulva|pussy")):
            if re.search(rf"\b(?:no|without|lacks?) (?:a |an )?(?:{pattern})\b", traits):
                parts.discard(part)
            elif re.search(rf"\b(?:{pattern})\b", traits):
                parts.add(part)
        result.append((route.sexes[slot], parts))
    return result


# Objects and roles a kink request does not imply: each appears only when the request names it.
ACCESSORY_FAMILIES = {
    "rope": re.compile(r"\b(?:ropes?|roped|shibari|kinbaku|tied|ties?|tying|hogtie\w*|frogtie|crotch rope|box tie|"
                       r"takate-kote|karada|ebi|kikkou|shinju|bound|binding)\b"),
    "restraints": re.compile(r"\b(?:cuff\w*|handcuff\w*|shackle\w*|chain\w*|spreader\w*|armbinder|strappado|restrain\w*|"
                             r"straps?(?![- ]?ons?\b)|strapped|stirrups|st\.? andrew's cross|cross|stocks|pillory|hooks?|bedposts?|bondage|harness\w*|"
                             r"wooden pony|bonding chair)\b"),
    "collar": re.compile(r"\b(?:collar\w*|leash\w*|name tag)\b"),
    "gag": re.compile(r"\b(?:gag\w*|ballgag|blindfold\w*|muzzle\w*|hood(?:ed)?)\b"),
    "impact": re.compile(r"\b(?:paddle\w*|crop(?![- ]?tops?\b)|flogger\w*|whip\w*|cane|caning|spank\w*)\b"),
    "props": re.compile(r"\b(?:nipple clamps?|clamps?|chastity|marker|writing|written|writes|labels?|property of|lipstick|"
                        r"pedestal|wedge|barrel|medical table|exam table|inspection table|padlock|key held)\b"),
    "toys": re.compile(r"\b(?:toys?|dildo\w*|vibrator\w*|wand|plugs?|beads|prostate massager|machines?|sybian|pumps?|"
                       r"tentacle\w*)\b"),
    "pet": re.compile(r"\b(?:pets?|puppy|kitten|crawl\w*|bowls?|kennel|(?<!chastity )cage|crate|tail|"
                      r"beg\w* like (?:a )?(?:pet|puppy|dog))\b"),
    "furniture": re.compile(r"\b(?:human (?:furniture|table|chair|stool|ottoman|bench|carpet|armrest|pillow|footrest|"
                            r"side table|display piece)|footrest|furniture (?:pose|pet|position)|living furniture|"
                            r"used as (?:a )?(?:human )?(?:furniture|table|chair|stool|bench|carpet|armrest|pillow|"
                            r"mounting block|footrest)|objectif\w*)\b"),
    "clothing": re.compile(r"\b(?:maid|sissy|latex|pvc|catsuit|fishnets?|crossdress\w*|feminiz\w*|whore|"
                           r"micro[- ](?:skirt|dress)|garter\w*|stockings?|heels|apron|frilly|open-cup|bodysuit|"
                           r"panties|corset|crop[- ]?tops?|short skirt|lingerie set)\b"),
}
# "Bondage" names restraint itself, so it permits rope and restraint hardware.
_ACCESSORY_ALIASES = {"rope": re.compile(r"\bbondage\b")}


def _positive_clauses(text):
    return "\n".join(clause for clause in re.split(r"[.!?;\n,]", str(text).casefold())
                     if not re.search(r"\b(?:no|not|without|avoid|never)\b", clause))


def accessory_families(text):
    text = str(text).casefold()
    return {name for name, pattern in ACCESSORY_FAMILIES.items() if pattern.search(text)}


def requested_accessories(route):
    """Accessory families the request names; toys are ordinary in a solo scene."""
    positive = _positive_clauses(route.request_text)
    requested = accessory_families(positive) | {name for name, pattern in _ACCESSORY_ALIASES.items() if pattern.search(positive)}
    return requested | ({"toys"} if len(route.position_slots) == 1 else set())


def compatible_entry(text, route, *, category="general", position=False, clothing_detail=False):
    """Reject clear contradictions; the model resolves prose, not a new geometry schema."""
    text = text.casefold()
    categories, _ = position_categories({"subject": text}, include_director=False)
    acts = activity_categories(text)
    if category in POSITION_ACT_CATEGORIES:
        acts.add(category)
    if categories & route.excluded or acts & route.excluded:
        return False
    # Aftercare is ordinary; toys are ordinary in a solo scene.
    themes = {"kink", "pet", "furniture", "feet", "finish"} | ({"toys"} if len(route.position_slots) != 1 else set())
    if (categories & themes) - route.categories:
        return False
    if accessory_families(text) - requested_accessories(route):
        return False
    requested_acts = route.categories & POSITION_ACT_CATEGORIES
    if requested_acts and acts - requested_acts:
        return False
    if position and len(acts) > 1 and not acts <= requested_acts:
        return False
    count = len(route.position_slots)
    for match in re.finditer(r"\b(one|two|three|four|five|\d+) (?:adult )?(?:people|persons?|participants?|adults?|partners?)\b", text):
        needed = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(match[1], int(match[1]) if match[1].isdigit() else 1)
        if needed > count:
            return False
    if count == 1 and (re.search(r"\b(?:partners?|couple|another (?:person|man|woman)|two (?:men|women|people)|69|sixty-nine|face[- ]?sitting)\b", text)
                       or acts and not re.search(r"\b(?:solo|self|own)\b", text)):
        return False
    anatomy = participant_anatomy(route)
    for sex, pattern in (("male", r"men|man|male"), ("female", r"women|woman|female")):
        available = sum(item[0] == sex for item in anatomy)
        if re.search(rf"\banother (?:adult )?(?:{pattern})\b", text) and available < 2:
            return False
        for match in re.finditer(rf"\b(?:(one|two|three|four|five|\d+) (?:adult )?)?({pattern})\b", text):
            needed = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(match[1], int(match[1]) if (match[1] or "").isdigit() else 1)
            if needed > available and not any(item[0] == "unspecified" for item in anatomy):
                return False
    for part, pattern in (("penis", r"penis(?:es)?|cocks?|dicks?|fellatio|blowjobs?"),
                          ("vagina", r"vagina|vulva|pussy|cunnilingus")):
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
    """Universal sections stay universal; each optional theme has its own gate."""
    sections = {"setting": ["setting"], "mood": ["mood"], "clothing": ["clothing"]}
    if len(route.position_slots) > 1:
        sections["interaction"] = ["interaction"]
        if len(route.position_slots) >= 3:
            sections["interaction"].append("group interaction")
    if route.kink:
        for axis in tuple(sections):
            sections[axis].append("kink " + axis)
    if "pet" in route.categories:
        sections["mood"].append("pet mood")
        if "interaction" in sections:
            sections["interaction"].append("pet interaction")
    if route.categories & {"kink", "pet", "furniture", "feet", "toys"}:
        sections["prop"] = ["props"]
    return sections


def vocabulary_choices(catalog, route, record, candidates, rng, used):
    """One activity's alternatives and a few compatible details, never whole sections."""
    selected_route = replace(route, categories=route.categories | ({record.category} if record else set()))
    choices = {}
    if record:
        alternatives = [item.label[:240] for item in candidates if item.category == record.category and item.label != record.label]
        rng.shuffle(alternatives)
        choices["position_candidates"] = "\n".join([record.label[:240], *alternatives[:2]])
        if record.category in POSITION_ACT_CATEGORIES | {"toys", "feet", "finish", "aftercare"}:
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


def compatible_arrangements(catalog, route, *, constraints=()):
    eligible, rejected = [], []
    subjects = [item for item in route.subjects for _ in range(item["count"])]
    acts = route.categories & POSITION_ACT_CATEGORIES
    anatomy = dict(zip(route.position_slots, (parts for _, parts in participant_anatomy(route))))
    sections = position_sections(route)
    records = list(catalog.records)
    legacy = {(item.section, item.label) for item in records}
    for section in sorted(sections):
        for text in catalog.get(section, ()):
            if (section, text) in legacy:
                continue
            categories = activity_categories(text)
            category = next(iter(categories)) if len(categories) == 1 else section.removesuffix(" positions")
            if category not in POSITION_ACT_CATEGORIES | {"solo", "toys", "feet", "kink", "pet", "furniture", "finish", "aftercare"}:
                category = "paired_pose" if len(route.position_slots) == 2 else "group_pose" if len(route.position_slots) > 2 else "solo"
            records.append(PositionCandidate(hashlib.sha256((section + text).encode()).hexdigest(), category, text, section))
    for pattern, text in catalog.get("requested", ()):
        positive = _positive_clauses(route.request_text)
        if route.vocabulary_applicable and pattern.search(positive):
            categories = activity_categories(text)
            category = next(iter(categories)) if len(categories) == 1 else "general"
            records.append(PositionCandidate(hashlib.sha256(text.encode()).hexdigest(), category, text, "requested"))
    for number, record in enumerate(records, 1):
        if record.section not in sections | {"requested"}:
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
        elif acts and record.category not in acts:
            reason = "requested_category"
        elif record.category in {"kink", "pet", "furniture", "feet", "toys", "finish", "aftercare"} and record.category not in route.categories:
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
