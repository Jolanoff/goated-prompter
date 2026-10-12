"""Typed catalog compatibility; broad pools cannot stand in for a requested category."""

from dataclasses import replace

from .quality import POSITION_ACT_CATEGORIES


def bind_arrangement(record, route, constraints):
    """Match template owners to approved slots without changing either owner's attributes."""
    if len(record.participants) != len(route.position_slots):
        return record
    subjects = [item for item in route.subjects for _ in range(item["count"])]
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
            if any((needed := {"penis": "male", "vagina": "female"}.get(part))
                   and route.sexes[slot] != needed and f"P{slot + 1}.{part}" not in approved_endpoints for part in parts):
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
    for number, record in enumerate(catalog.records, 1):
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
        elif route.categories and not acts and record.category not in route.categories:
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
                    needed_sex = {"penis": "male", "vagina": "female"}.get(part)
                    if needed_sex and route.sexes[int(owner[1:]) - 1] != needed_sex and endpoint not in approved_endpoints:
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
    unresolved = [item["reason"] for item in catalog.diagnostics if item["rule"] in {"unresolved_structure", "invalid_record", "unreadable", "unavailable"}]
    if route.vocabulary_applicable and not eligible:
        unresolved.append("No compatible vocabulary arrangement was selected; use provisional LLM-assisted planning.")
    return {"loaded": catalog.loaded, "eligible": len(eligible),
             "rejected": len({("line", item["line"]) if "line" in item else ("record", item["record"])
                              for item in diagnostics if ("line" in item or "record" in item) and item["rule"] != "unknown_section"}),
            "diagnostics": diagnostics, "unresolved_constraints": list(dict.fromkeys(unresolved)),
            "filtering_rules": ["Validated owners, poses, body-part endpoints and physical support",
                                "Approved participant count and declared sex", "Requested and excluded categories",
                                "Approved owned roles, placement and contacts"]}
