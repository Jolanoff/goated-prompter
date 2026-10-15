"""Vocabulary-backed arrangements: who takes which role in a checked position or action, per image.

Three states, never confused:
1. inspiration  the vocabulary block (vocabulary_packs.py): optional ideas, not a scene choice;
2. vocabulary   an arrangement the concept chose from its image's options and code checked with the resolver
                (vocabulary/resolver.py): its entries and role bindings are fixed from then on;
3. freeform     the concept chose no option ([]): generation stays as flexible as before and nothing about it is
                described as vocabulary-checked.

Options for image N are the bindable entries (positions and actions) the request names, for every image, plus the
bindable ideas retrieval offers image N (its seeded plan), from the run's selected packs only. The active Director
shapes them twice: its instructions are a retrieval source (they rank and open ideas) and the concept request is
written under them, so the Director chooses among the options and assigns the roles. It cannot add an option from a
pack the run did not select, and when the request names options (outside guided inputs), one of them must be used.

Code checks, per concept (check): the chosen options exist for that image, every role is assigned to the brief's
people, and the resolver finds no conflict for the composition (slot counts, people bound twice, capabilities,
placements of several entries, exclusive claims on hands or legs, regions blocked by support). A conflict rejects
that concept only and it is written again; unknown, eligible and feasible are kept as they are and recorded. The
place is free text, so space requirements stay unknown.

At staging, each person's posture and facing are also given as structured choices (placement) and checked against
the arrangement with the resolver (check_staging): a different posture or facing for a bound role, including a
reversal of roles with different postures, is a conflict, and that slot's staging is written again. Prose in
position and actions is never interpreted: anchors ("astride", "above"), contact and reach are passed to staging and
the Builder as facts, not verified.
"""

import hashlib
import re

from ...vocabulary.resolver import CompositionError, candidate_bindings, resolve

STANDING = ("director", "style", "hint")  # sources that prefer, never require (retrieval.STANDING plus semantic hints)
MAX_ENTRIES = 2          # options one concept may combine (a position and an action)
OTHER = "other"          # a posture or facing outside the vocabulary: allowed only where no option fixes it
CHECKED = ["chosen options exist for the image", "every role is assigned to the brief's people",
           "resolver: slot counts, capabilities, placements, exclusive claims and blocked regions"]
NOT_CHECKED = ["the place (free text): space requirements stay unknown", "anchors, contact and reach in the prose",
               "anything the prose adds beyond posture and facing"]
_ID = re.compile(r"\b[a-z][a-z0-9_]*:[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*\b")


def _bindable(entry):
    return any(spec["kind"] == "being" for spec in entry["components"].get("participants", {}).get("slots", {}).values())


def _is_posture(entry):
    comp = entry["components"]
    return "self" in comp.get("spatial", {}).get("participants", {}) and not comp.get("participants", {}).get("slots")


def _count(spec):
    count = spec["count"]
    return (count["min"], count["max"]) if isinstance(count, dict) else (count, count)


class Arrangements:
    """The arrangement options and checks of one run. Inactive (no field, no rule) when no image has an option."""

    def __init__(self, registry, found, brief, *, allowed):
        self.registry, self.found = registry, found
        self.labels = [item["label"] for item in brief["characters"]]
        self.cast = [{"id": item["character"], "body": item["body"], "traits": list(item.get("traits", []))}
                     for item in found.cast if item.get("character") in self.labels]
        seed = brief["input"].get("seed")
        self.seed = seed if type(seed) is int else 0
        amount = brief["input"].get("amount")
        self.amount = amount if type(amount) is int and amount > 0 else 1
        self.guided = brief["input"].get("source_mode") == "guided"
        self.named = [entry for entry in found.entries if _bindable(registry.resolved(entry.id))]
        # What the brief itself names is required; what only the Director (or style, or a hint) names is preferred.
        self.asked = {entry.id for entry in self.named if set(found.named_by.get(entry.id, ["request"])) - set(STANDING)}
        self.postures = sorted(entry_id for entry_id in registry.ids()
                               if _is_posture(registry.resolved(entry_id)) and registry.resolved(entry_id).get("rating") in allowed)
        self.preferred = {entry.id for entry in self.named if entry.id not in self.asked}
        self._options, self._only = {}, {}
        self.active = bool(self.cast) and len(self.cast) == len(self.labels) and any(
            self.options(number) for number in range(1, self.amount + 1))

    # -- what each image may use
    def director_turn(self, entry_id, number):
        """Whether a Director-only preference is offered to this image: about every other image, by seed, so a
        preference adds variety instead of taking over every image (what the brief names is offered everywhere)."""
        return int(hashlib.sha256(f"{self.seed}\0{entry_id}\0{number}".encode()).hexdigest(), 16) % 2 == 0

    def options(self, number):
        if number not in self._options:
            named = [entry for entry in self.named if entry.id in self.asked or self.director_turn(entry.id, number)]
            entries = named + [entry for entry in self.found.ideas(number) if _bindable(self.registry.resolved(entry.id))]
            self._options[number] = list({entry.id: entry for entry in entries}.values())
        return self._options[number]

    def required(self, number):
        """Options the request names for this image: one of them must be used (never for guided inputs)."""
        if self.guided:
            return []
        return [entry for entry in self.options(number) if entry.id in self.asked]

    def name(self, entry_id):
        return self.registry.resolved(entry_id)["name"] if entry_id in self.registry else entry_id

    def slots(self, entry_id):
        return self.registry.resolved(entry_id)["components"].get("participants", {}).get("slots", {})

    def offer(self, numbers, rejected=None):
        """arrangement_options for a concept request writing these images, one item per concept in order.

        roles describe what each role does, from the entry's declared placements and claims; no binding is suggested
        unless it is the only one the resolver accepts (only_valid_roles), since any other suggestion would be an
        arbitrary order of the cast. rejected_before lists arrangements already refused for that image, and why."""
        items = []
        for position, number in enumerate(numbers, 1):
            named = {entry.id for entry in self.required(number)}
            options = []
            for entry in self.options(number):
                option = {"id": entry.id, "name": entry.name, "description": " ".join(str(entry.description).split())[:200],
                          "roles": self.role_notes(entry.id), "status": entry.status, "named_by_request": entry.id in named,
                          "director_prefers": entry.id in self.preferred}
                only = self.only_binding(entry.id)
                if only:
                    option["only_valid_roles"] = only
                options.append(option)
            item = {"concept": position, "options": options}
            if rejected and rejected.get(number):
                item["rejected_before"] = [{"arrangement": entry["arrangement"], "why": entry["why"]} for entry in rejected[number]]
            items.append(item)
        return items

    def role_notes(self, entry_id):
        """{role: what it takes and does}, from declared data only (count, posture, facing, anchors, claims)."""
        comp = self.registry.resolved(entry_id)["components"]
        placements = comp.get("spatial", {}).get("participants", {})
        notes = {}
        for slot, spec in sorted(self.slots(entry_id).items()):
            if spec["kind"] != "being":
                continue
            low, high = _count(spec)
            parts = ["1 person" if (low, high) == (1, 1) else f"{low}-{high} people"]
            placement = placements.get(slot, {})
            if placement.get("posture"):
                posture = self.registry.resolved(placement["posture"])["components"]
                held = [f"{claim['count']} {self.name(claim['resource']).lower()}" for claim in posture.get("claims", {}).get("self", [])
                        if claim["mode"] == "exclusive"]
                parts.append(self.name(placement["posture"]).lower()
                             + (f" (its {' and '.join(held)} are busy holding the body up)" if held else ""))
            if placement.get("facing"):
                (way, other), = placement["facing"].items()
                parts.append(f"facing {way.replace('_', ' ')} the {other}")
            for anchor in placement.get("anchors", []):
                targets = anchor["of"] if isinstance(anchor["of"], list) else [anchor["of"]]
                parts.append(f"{anchor['relation'].replace('_', ' ')} the {' and '.join(targets)}"
                             + (f" at {self.name(anchor['at']).lower()}" if anchor.get("at") else ""))
            claims = [f"uses {claim['count']} {self.name(claim['resource']).lower()} to {claim['purpose']}"
                      for claim in comp.get("claims", {}).get(slot, [])]
            notes[slot] = ", ".join(parts + claims)
        return notes

    def only_binding(self, entry_id):
        """{role: labels} when exactly one binding of the cast is not a conflict; None otherwise."""
        if entry_id not in self._only:
            cast = self.cast
            objects = [{"id": f"{slot} {index}", "item": None} for slot, spec in sorted(self.slots(entry_id).items())
                       if spec["kind"] == "object" for index in range(1, _count(spec)[0] + 1)]
            found = candidate_bindings(self.registry, entry_id, cast, objects=objects, limit=64)
            viable = [bind for bind, result in found if result.status != "conflict"]
            only = None
            if len(viable) == 1 and not found.truncated:
                only = {slot: (value if isinstance(value, list) else [value]) for slot, value in sorted(viable[0].items())
                        if self.slots(entry_id)[slot]["kind"] == "being"}
            self._only[entry_id] = only
        return self._only[entry_id]

    def schema(self):
        ids = sorted({entry.id for number in range(1, self.amount + 1) for entry in self.options(number)})
        roles = sorted({slot for entry_id in ids for slot, spec in self.slots(entry_id).items() if spec["kind"] == "being"})
        who = {"type": "array", "minItems": 1, "maxItems": max(1, len(self.labels)), "items": {"enum": self.labels}}
        role = {"type": "object", "additionalProperties": False, "required": ["role", "who"],
                "properties": {"role": {"enum": roles}, "who": who}}
        option = {"type": "object", "additionalProperties": False, "required": ["option", "roles"],
                  "properties": {"option": {"enum": ids}, "roles": {"type": "array", "maxItems": len(roles), "items": role}}}
        return {"type": "array", "maxItems": MAX_ENTRIES, "items": option}

    def placement_schema(self):
        facing = [OTHER] + [f"{way} {label}" for label in self.labels for way in ("toward", "away from")]
        person = {"type": "object", "additionalProperties": False, "required": ["posture", "facing"],
                  "properties": {"posture": {"enum": [*self.postures, OTHER]}, "facing": {"enum": facing}}}
        return {"type": "object", "additionalProperties": False, "required": self.labels,
                "properties": {label: person for label in self.labels}}

    # -- checks
    def humanize(self, text):
        return _ID.sub(lambda match: self.name(match.group()) if match.group() in self.registry else match.group(), text)

    def _composition(self, chosen, declared=None):
        objects, uses = [], []
        for number, item in enumerate(chosen, 1):
            bind = {}
            for slot, spec in self.slots(item["option"]).items():
                if spec["kind"] == "object":  # an object the entry needs: not chosen here, so undeclared (unknown)
                    low, _ = _count(spec)
                    ids = [f"{slot} {number}.{index}" for index in range(1, low + 1)]
                    objects += [{"id": ident, "item": None} for ident in ids]
                    if ids:
                        bind[slot] = ids if len(ids) > 1 else ids[0]
            for role in item["roles"]:
                bind[role["role"]] = list(role["who"]) if len(role["who"]) > 1 or _count(self.slots(item["option"])[role["role"]])[1] > 1 \
                    else role["who"][0]
            uses.append({"entry": item["option"], "bind": bind})
        return {"cast": self.cast, "objects": objects, "space": None, "use": uses, **({"declared": declared} if declared else {})}

    def check(self, number, chosen, rejected=()):
        """(record, errors) for the arrangement a concept chose for image number. rejected: [{arrangement, why}]
        already refused for this image; choosing one again is refused with its earlier reasons."""
        for item in rejected:
            if chosen == item["arrangement"]:
                return None, ["this arrangement was already rejected for this image (" + "; ".join(item["why"])
                              + "): choose other options or other roles, or []"]
        if not isinstance(chosen, list) or len(chosen) > MAX_ENTRIES:
            return None, [f"arrangement is a list of at most {MAX_ENTRIES} options, or [] for none"]
        options = {entry.id: entry for entry in self.options(number)}
        required = self.required(number)
        if not chosen:
            if required:
                return None, [f"the request names {', '.join(entry.name for entry in required)}: "
                              "use one of them as the arrangement, with every role assigned"]
            return {"kind": "freeform", "status": "unchecked", "chosen": []}, []
        errors = []
        for item in chosen:
            entry_id = item.get("option") if isinstance(item, dict) else None
            if entry_id not in options:
                errors.append(f"{entry_id} is not an arrangement option for this image; choose one of "
                              f"{', '.join(options) or 'none'} or use []")
                continue
            slots = {slot for slot, spec in self.slots(entry_id).items() if spec["kind"] == "being"}
            given = [role.get("role") for role in item.get("roles", [])]
            if sorted(given) != sorted(slots):
                errors.append(f"{options[entry_id].name} needs exactly the roles {', '.join(sorted(slots))}, each once")
            for role in item.get("roles", []):
                low, high = _count(self.slots(entry_id).get(role.get("role"), {"count": 1}))
                who = role.get("who", [])
                if not low <= len(who) <= high or any(label not in self.labels for label in who):
                    errors.append(f"{options[entry_id].name}: {role.get('role')} takes {low}-{high} of "
                                  f"{', '.join(self.labels)}")
        if not errors and required and not {item["option"] for item in chosen} & {entry.id for entry in required}:
            errors.append(f"the request names {', '.join(entry.name for entry in required)}: use one of them")
        if errors:
            return None, errors
        try:
            result = resolve(self.registry, self._composition(chosen))
        except CompositionError as error:
            return None, [str(error)]
        if result.status == "conflict":
            return None, [self.explain(finding, chosen) for finding in result.findings if finding.status == "conflict"][:3]
        return {"kind": "vocabulary", "status": result.status, "chosen": chosen,
                "entries": [{"id": item["option"], "name": self.name(item["option"]), "pack": self.registry.owner(item["option"]),
                             "roles": {role["role"]: list(role["who"]) for role in item["roles"]}} for item in chosen],
                "placements": result.placements, "facts": self.facts(result),
                "findings": [{**finding.to_dict(), "message": self.humanize(finding.message)}
                             for finding in result.findings if finding.status != "feasible"][:8],
                "checked": CHECKED, "not_checked": NOT_CHECKED}, []

    def check_staging(self, record, placement):
        """Errors in a staging's placement (posture and facing per person) against its concept's arrangement."""
        if not record or record.get("kind") != "vocabulary":
            return []
        if not isinstance(placement, dict) or set(placement) != set(self.labels):
            return [f"placement needs exactly {', '.join(self.labels)}"]
        declared, errors = {}, []
        for label, value in placement.items():
            fixed = record["placements"].get(label, {})
            posture, facing = value.get("posture"), value.get("facing")
            if posture == OTHER and fixed.get("posture"):
                errors.append(f"{label}'s posture is fixed by the arrangement: {self.name(fixed['posture']).lower()}")
            if facing == OTHER and fixed.get("facing") and fixed["facing"][0] in ("toward", "away_from"):
                errors.append(f"{label}'s facing is fixed by the arrangement: {fixed['facing'][0].replace('_', ' ')} "
                              f"{', '.join(fixed['facing'][1])}")
            item = {}
            if posture not in (None, OTHER):
                item["posture"] = posture
            if facing not in (None, OTHER):
                way = "toward" if facing.startswith("toward ") else "away_from"
                item["facing"] = [way, facing[len("toward "):] if way == "toward" else facing[len("away from "):]]
            if item:
                declared[label] = item
        if errors:
            return errors
        try:
            result = resolve(self.registry, self._composition(record["chosen"], declared))
        except CompositionError as error:
            return [str(error)]
        return [self.humanize(finding.message) for finding in result.findings if finding.status == "conflict"][:3]

    def explain(self, finding, chosen):
        """A conflict as the concept can act on it: for claimed resources, which option and role (and posture)
        claims what of whom, and that one role must go to someone else or one option be dropped."""
        message = self.humanize(finding.message)
        if finding.code != "over_allocated" or not finding.participants:
            return message
        who = finding.participants[0]
        resources = [entry for entry in finding.entries if entry in self.registry and "capability" in self.registry.resolved(entry)["components"]]
        claims = []
        for item in chosen:
            comp = self.registry.resolved(item["option"])["components"]
            placements = comp.get("spatial", {}).get("participants", {})
            for role in item["roles"]:
                if who not in role["who"]:
                    continue
                sources = [(comp.get("claims", {}).get(role["role"], []), None)]
                posture = placements.get(role["role"], {}).get("posture")
                if posture:
                    sources.append((self.registry.resolved(posture)["components"].get("claims", {}).get("self", []), posture))
                for found, via in sources:
                    for claim in found:
                        if not resources or claim["resource"] in resources:
                            how = f" ({self.name(via).lower()})" if via else ""
                            claims.append(f"{self.name(item['option'])} as {role['role']}{how}: {claim['count']} "
                                          f"{self.name(claim['resource']).lower()} for {claim['purpose']}")
        if not claims:
            return message
        return (f"{message}. {who}'s claims: " + "; ".join(claims)
                + f". Give one of these roles to someone else, or drop one option")

    def facts(self, result):
        """The checked arrangement as short lines for staging and the Builder (from declared data, never prose)."""
        lines = []
        for who, placement in sorted(result.placements.items()):
            parts = []
            if placement.get("posture"):
                parts.append(self.name(placement["posture"]).lower())
            if placement.get("facing"):
                way, others = placement["facing"]
                parts.append(f"facing {way.replace('_', ' ')} {' and '.join(others)}")
            for anchor in placement.get("anchors", []):
                where = f" at {self.name(anchor['at']).lower()}" if anchor.get("at") else ""
                parts.append(f"{anchor['relation'].replace('_', ' ')} {' and '.join(anchor['of'])}{where}"
                             + (f" ({anchor['distance']})" if anchor.get("distance") else ""))
            if parts:
                lines.append(f"{who}: " + ", ".join(parts))
        for fact in result.access:
            regions = " or ".join(self.name(region).lower() for region in fact["regions"])
            lines.append(f"{fact['from']} can {'see' if fact['kind'] == 'sight' else 'reach'} {fact['to']}'s {regions} "
                         f"with {self.name(fact['using']).lower()}")
        for who, instances in sorted(result.allocation.items()):
            for instance, uses in sorted(instances.items()):
                purposes = sorted({use["purpose"] for use in uses if use["mode"] == "exclusive"})
                if purposes:
                    lines.append(f"{who}'s {instance.replace('_', ' ').replace('.', ' ')}: {', '.join(purposes)}")
        return lines

    # -- what later steps receive
    def for_model(self, record):
        """The arrangement as staging and description read it; None for freeform (nothing is claimed)."""
        if not record or record.get("kind") != "vocabulary":
            return None
        return {"checked_by_vocabulary": record["status"], "entries": [{"name": entry["name"], "roles": entry["roles"]}
                                                                        for entry in record["entries"]],
                "facts": record["facts"], "placement": self.required_placement(record)}

    def required_placement(self, record):
        """{label: {posture, facing}} the arrangement fixes, in the staging placement's own terms."""
        out = {}
        for label, placement in sorted(record["placements"].items()):
            item = {}
            if placement.get("posture"):
                item["posture"] = placement["posture"]
            facing = placement.get("facing")
            if facing and facing[0] in ("toward", "away_from") and len(facing[1]) == 1:
                item["facing"] = f"{facing[0].replace('_', ' ')} {facing[1][0]}"
            if item:
                out[label] = item
        return out

    def established(self, record, placement):
        """What the finished scene keeps of its arrangement, for the Builder and the run record."""
        if not record:
            return None
        if record.get("kind") != "vocabulary":
            return {"kind": "freeform", "status": "unchecked"}
        return {"kind": "vocabulary", "status": record["status"], "entries": record["entries"], "facts": record["facts"],
                "placement": placement or {}, "checked": record["checked"], "not_checked": record["not_checked"]}

    def record(self):
        """Run-level diagnostics: whether arrangements were offered and each image's options."""
        return {"enabled": self.active, "required": sorted(self.asked) if not self.guided else [],
                "director_prefers": sorted(self.preferred),
                "images": [{"slot": number, "options": [entry.id for entry in self.options(number)]}
                           for number in range(1, self.amount + 1)] if self.active else []}
