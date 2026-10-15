"""Capability and spatial resolver (Phase 3) for vocabulary/schemas/SPEC.md.

A composition binds entries of a Registry to a cast:

    {"cast": [{"id": "ana", "body": "core:body.humanoid", "traits": [...], "complete_for": [...]}],
     "objects": [{"id": "toy", "item": "adult:item.dildo", "complete_for": [...]}],
     "space": "core:space.bed",
     "use": [{"entry": "core:position.from_behind", "bind": {"front": "ana", "back": "ben"}}],
     "declared": {"ana": {"posture": "core:posture.all_fours", "facing": ["away_from", "ben"]}}}

declared (optional) is what a scene itself states about a cast member, outside any entry: a posture entry and a
facing toward or away from another member. It is checked like an entry's placement, so a scene that gives a
bound participant another posture or facing than the entry declares is a placement conflict.

resolve() reports conflict, unknown, eligible or feasible (SPEC.md section 3) with findings that
name the entries and participants involved. "feasible" means the declared data supports the
composition; it is never a claim of physical possibility. A cast member or object without a
vocabulary body or item (null) is allowed: everything about it is undeclared, so missing vocabulary
can make a result unknown, never a conflict. A composition in which no vocabulary rule applies at
all is unknown, never feasible.
"""

from dataclasses import dataclass, field
from itertools import combinations
import re

STATUSES = ("feasible", "eligible", "unknown", "conflict")  # increasing severity (SPEC.md section 3)
RANK = {status: rank for rank, status in enumerate(STATUSES)}
FEASIBLE_NOTE = ("feasible: every requirement is satisfied and every placement and required access is "
                 "covered by declared spatial facts. This reflects the declared data only and is not "
                 "proof that the arrangement is physically possible.")
_REF = re.compile(r"^(?P<slot>[a-z][a-z0-9_]*)(\[(?P<index>-?[0-9]+|\*|[0-9]*:[0-9]*|i|i(?P<rel>[+-][0-9]+))\])?$")
NO_EVIDENCE = "no_vocabulary_evidence"
SCENE = "the scene"  # the "entry" of a placement the scene declares itself (composition "declared")
_KEY_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_OPPOSITE = {"in_front": "behind", "behind": "in_front", "left_of": "right_of", "right_of": "left_of",
             "above": "below", "below": "above", "on": "under", "under": "on"}


class CompositionError(ValueError):
    """The composition itself is malformed (unknown entry, slot or id). Not a vocabulary status."""


@dataclass(frozen=True)
class Finding:
    status: str
    code: str
    message: str
    entries: tuple = ()
    participants: tuple = ()

    def to_dict(self):
        return {"status": self.status, "code": self.code, "message": self.message,
                "entries": list(self.entries), "participants": list(self.participants)}


@dataclass
class Resolution:
    status: str
    findings: list
    allocation: dict = field(default_factory=dict)   # {participant: {instance: [claim]}}
    placements: dict = field(default_factory=dict)   # {participant: {"posture", "orientation", "facing", "anchors", "entries"}}
    access: list = field(default_factory=list)       # declared access facts, expanded to participants

    @property
    def note(self):
        return FEASIBLE_NOTE if self.status == "feasible" else ""

    def findings_with(self, code):
        return [finding for finding in self.findings if finding.code == code]

    def to_dict(self):
        return {"status": self.status, "note": self.note, "findings": [finding.to_dict() for finding in self.findings],
                "allocation": self.allocation, "placements": self.placements, "access": self.access}


# ---------------------------------------------------------------- subjects (beings, objects, the space)

class Subject:
    """Something requirements are evaluated against: what it provides and what it declares complete."""

    def __init__(self, registry, ident, provides=(), complete=(), resources=None, described=True, entries=()):
        self.registry, self.id, self.described, self.entries = registry, ident, described, tuple(entries)
        self.resources = dict(resources or {})  # {instance: capability type}
        self.provides = implied(registry, [*provides, *self.resources.values()])
        self.complete = set(complete)

    def state(self, capability):
        """provided, absent (declared complete and not provided) or undeclared (SPEC.md section 3)."""
        if capability in self.provides:
            return "provided"
        if self.described and implied(self.registry, [capability]) & self.complete:
            return "absent"
        return "undeclared"

    def instances(self, capability):
        return sorted(name for name, kind in self.resources.items() if capability in implied(self.registry, [kind]))


def implied(registry, capabilities):
    """Capabilities plus everything they imply, transitively."""
    result, stack = set(), list(capabilities)
    while stack:
        current = stack.pop()
        if current not in result:
            result.add(current)
            if current in registry:
                stack.extend(registry.resolved(current)["components"].get("capability", {}).get("implies", []))
    return result


def _being(registry, member):
    ident = member["id"]
    bodies = [member["body"]] if member.get("body") else []
    bodies += list(member.get("traits", []))
    resources, provides, complete = {}, [], list(member.get("complete_for", []))
    for body_id in bodies:
        if body_id not in registry:
            raise CompositionError(f"{ident}: unknown body or trait {body_id}")
        body = registry.resolved(body_id)["components"].get("body", {})
        resources.update(body.get("resources", {}))
        provides += body.get("provides", [])
        complete += body.get("complete_for", [])
    for capability in member.get("complete_for", []):
        if capability not in registry:
            raise CompositionError(f"{ident}: unknown capability {capability} in complete_for")
    return Subject(registry, ident, provides, complete, {name: item["type"] for name, item in resources.items()},
                   described=bool(member.get("body")), entries=bodies)


def _object(registry, item):
    """Like a body: the item's provides, and complete_for from the item entry and the composition."""
    for capability in item.get("complete_for", []):
        if capability not in registry:
            raise CompositionError(f"{item['id']}: unknown capability {capability} in complete_for")
    if not item.get("item"):
        return Subject(registry, item["id"], described=False)
    if item["item"] not in registry:
        raise CompositionError(f"{item['id']}: unknown item {item['item']}")
    declared = registry.resolved(item["item"])["components"].get("object", {})
    complete = [*declared.get("complete_for", []), *item.get("complete_for", [])]
    return Subject(registry, item["id"], declared.get("provides", []), complete, entries=[item["item"]])


def _space(registry, space_id):
    if not space_id:
        return Subject(registry, "space", described=False)
    if space_id not in registry:
        raise CompositionError(f"unknown space {space_id}")
    provides = registry.resolved(space_id)["components"].get("environment", {}).get("provides", [])
    return Subject(registry, "space", provides, entries=[space_id])


# ---------------------------------------------------------------- the resolver

class _Run:
    def __init__(self, registry, composition):
        self.registry = registry
        self.findings = []
        self.beings = {member["id"]: _being(registry, member) for member in composition.get("cast", [])}
        self.objects = {item["id"]: _object(registry, item) for item in composition.get("objects", [])}
        if len(self.beings) + len(self.objects) != len(composition.get("cast", [])) + len(composition.get("objects", [])) \
                or set(self.beings) & set(self.objects):
            raise CompositionError("cast and object ids must be unique")
        self.space = _space(registry, composition.get("space"))
        self.uses = composition.get("use", [])
        self.claims = []          # dicts: participant, resource, count, mode, purpose, key, entry
        self.required_access = []  # (from, using, to, regions, kind, entry)
        self.facts = []            # (from, using, to, regions, kind, entry)
        self.placements = {}       # participant -> list of (entry, placement with concrete refs)
        self.bound_beings = set()
        self.evaluated = 0         # vocabulary rules that applied to a bound participant or the space

    def add(self, status, code, message, entries=(), participants=()):
        finding = Finding(status, code, message, tuple(dict.fromkeys(entries)), tuple(dict.fromkeys(participants)))
        if finding not in self.findings:
            self.findings.append(finding)

    def subject(self, ident):
        return self.beings.get(ident) or self.objects.get(ident)

    # -- conditions
    def check(self, subject, condition, entry, where):
        self.evaluated += 1
        for capability in condition.get("all_of", []):
            state = subject.state(capability)
            if state == "absent":
                self.add("conflict", "missing_capability", f"{subject.id} lacks {capability}, which {where} requires",
                         [entry, capability, *subject.entries], [subject.id])
            elif state == "undeclared":
                self.add("unknown", "undeclared_capability", f"{subject.id}: {capability} is not declared ({where} requires it)",
                         [entry, capability, *subject.entries], [subject.id])
        groups = list(condition.get("any_of_groups", [])) + ([condition["any_of"]] if "any_of" in condition else [])
        for group in groups:
            states = [subject.state(capability) for capability in group]
            if "provided" in states:
                continue
            if all(state == "absent" for state in states):
                self.add("conflict", "missing_capability", f"{subject.id} has none of {', '.join(group)}, one of which {where} requires",
                         [entry, *group, *subject.entries], [subject.id])
            else:
                self.add("unknown", "undeclared_capability", f"{subject.id}: none of {', '.join(group)} is declared ({where} requires one)",
                         [entry, *group, *subject.entries], [subject.id])
        for capability in condition.get("none_of", []):
            state = subject.state(capability)
            if state == "provided":
                self.add("conflict", "forbidden_capability", f"{subject.id} has {capability}, which {where} excludes",
                         [entry, capability, *subject.entries], [subject.id])
            elif state == "undeclared":
                self.add("unknown", "undeclared_capability", f"{subject.id}: {capability} is not declared ({where} excludes it)",
                         [entry, capability, *subject.entries], [subject.id])

    # -- references (SPEC.md section 4)
    def members(self, ref, bindings):
        match = _REF.match(ref)
        if not match:
            raise CompositionError(f"bad participant reference {ref}")
        bound = bindings.get(match["slot"], [])
        index = match["index"]
        if index is None or index in ("*", "i") or match["rel"]:
            return list(bound)
        if ":" in index:
            start, stop = index.split(":")
            return bound[int(start) if start else None:int(stop) if stop else None]
        number = int(index)
        return [bound[number]] if -len(bound) <= number < len(bound) else []

    def pairs(self, rule_from, rule_to, bindings, topologies):
        """Concrete (from, to) pairs of one rule; [i] / [i+k] iterate over a group (ring wraps, chain skips)."""
        def iterated(ref):
            match = _REF.match(ref)
            return bool(match) and (match["index"] == "i" or bool(match["rel"]))
        indexed = [ref for ref in (rule_from, rule_to) if iterated(ref)]
        if not indexed:
            return [(a, b) for a in self.members(rule_from, bindings) for b in self.members(rule_to, bindings) if a != b]
        slot = _REF.match(indexed[0])["slot"]
        group, topology = bindings.get(slot, []), topologies.get(slot)
        result = []
        for i in range(len(group)):
            ends = []
            for ref in (rule_from, rule_to):
                match = _REF.match(ref)
                if match["index"] == "i" or match["rel"]:
                    target = i + int(match["rel"] or 0)
                    members = bindings.get(match["slot"], [])
                    if not 0 <= target < len(members):
                        if topology == "ring" and members:
                            target %= len(members)
                        elif topology == "chain":
                            ends = None
                            break
                        else:
                            raise CompositionError(f"{ref} needs a ring or chain topology")
                    ends.append([members[target]])
                else:
                    ends.append(self.members(ref, bindings))
            if ends:
                result += [(a, b) for a in ends[0] for b in ends[1] if a != b]
        return result

    # -- one use of an entry
    def apply(self, use):
        entry_id = use.get("entry")
        if entry_id not in self.registry:
            raise CompositionError(f"unknown entry {entry_id}")
        entry = self.registry.resolved(entry_id)
        comp = entry["components"]
        slots = comp.get("participants", {}).get("slots", {})
        bindings = {}
        for slot, value in use.get("bind", {}).items():
            if slot not in slots:
                raise CompositionError(f"{entry_id} has no slot {slot}")
            ids = value if isinstance(value, list) else [value]
            pool = self.beings if slots[slot]["kind"] == "being" else self.objects
            for ident in ids:
                if ident not in pool:
                    raise CompositionError(f"{entry_id}.{slot}: {ident} is not a {'cast member' if pool is self.beings else 'object'}")
            bindings[slot] = list(ids)
        for slot, spec in slots.items():
            count = spec["count"] if isinstance(spec["count"], dict) else {"min": spec["count"], "max": spec["count"]}
            bound = len(bindings.get(slot, []))
            if not count["min"] <= bound <= count["max"]:
                self.add("conflict", "slot_count", f"{entry_id}.{slot} takes {count['min']}-{count['max']}, {bound} bound", [entry_id])
        everyone = [ident for ids in bindings.values() for ident in ids]
        for ident in sorted({ident for ident in everyone if everyone.count(ident) > 1}):
            self.add("conflict", "bound_twice", f"{ident} fills two slots of {entry_id} at once", [entry_id], [ident])
        self.bound_beings |= {ident for slot, ids in bindings.items() if slots[slot]["kind"] == "being" for ident in ids}
        topologies = {slot: spec.get("topology") for slot, spec in slots.items()}
        requirements = comp.get("requirements", {})
        for ref, condition in requirements.get("participants", {}).items():
            for ident in self.members(ref, bindings):
                self.check(self.subject(ident), condition, entry_id, f"{entry_id} ({ref})")
        if requirements.get("space"):
            self.check(self.space, requirements["space"], entry_id, f"{entry_id} (space)")
        for access in requirements.get("access", []):
            for a, b in self.pairs(access["from"], access["to"], bindings, topologies):
                self.evaluated += 1
                self.required_access.append((a, access["using"], b, tuple(access["regions"]), access["kind"], entry_id))
        spatial = comp.get("spatial", {})
        for ref, placement in spatial.get("participants", {}).items():
            for ident in self.members(ref, bindings):
                self.place(ident, placement, bindings, entry_id)
        for access in spatial.get("access", []):
            for a, b in self.pairs(access["from"], access["to"], bindings, topologies):
                # A declared reach presupposes the capability it uses (SPEC.md section 6).
                self.check(self.subject(a), {"all_of": [access["using"]]}, entry_id, f"{entry_id} (declared reach with {access['using']})")
                self.facts.append((a, access["using"], b, tuple(access["regions"]), access["kind"], entry_id))
        for ref, claims in comp.get("claims", {}).items():
            for ident in self.members(ref, bindings):
                for claim in claims:
                    key = claim.get("key", "")
                    named = _KEY_SLOT.findall(key)
                    if any(not bindings.get(slot) for slot in named):
                        continue  # SPEC.md section 5: a claim keyed to an unbound optional slot is dropped
                    key = _KEY_SLOT.sub(lambda match: "+".join(bindings[match[1]]), key)
                    self.evaluated += 1
                    self.claims.append({**claim, "key": key, "participant": ident, "entry": entry_id})

    def place(self, ident, placement, bindings, entry_id):
        self.evaluated += 1
        concrete = {"entry": entry_id}
        if "posture" in placement:
            posture_id = placement["posture"]
            posture = self.registry.resolved(posture_id)["components"]
            concrete["posture"] = posture_id
            self_placement = posture.get("spatial", {}).get("participants", {}).get("self", {})
            if "orientation" in self_placement:
                concrete["orientation"] = self_placement["orientation"]
            condition = posture.get("requirements", {}).get("participants", {}).get("self")
            if condition:
                self.check(self.subject(ident), condition, posture_id, f"{posture_id} (taken by {ident} in {entry_id})")
            for claim in posture.get("claims", {}).get("self", []):
                self.claims.append({**claim, "key": claim.get("key", ""), "participant": ident, "entry": posture_id})
        if "orientation" in placement:
            concrete["orientation"] = placement["orientation"]
        if "facing" in placement:
            (kind, value), = placement["facing"].items()
            concrete["facing"] = (kind, value if kind == "world" else tuple(self.members(value, bindings)) if value != "center" else ("center",))
        concrete["anchors"] = []
        for anchor in placement.get("anchors", []):
            targets = anchor["of"] if isinstance(anchor["of"], list) else [anchor["of"]]
            others = tuple(other for target in targets for other in (["center"] if target == "center" else self.members(target, bindings)))
            concrete["anchors"].append((anchor["relation"], others, anchor.get("at"), anchor.get("distance")))
        self.placements.setdefault(ident, []).append(concrete)

    def declare(self, ident, declared):
        """A scene's own statement about one cast member (composition "declared"), placed like an entry's."""
        if ident not in self.beings:
            raise CompositionError(f"declared placement for {ident}, who is not a cast member")
        posture = declared.get("posture")
        if posture is not None and (posture not in self.registry or
                                    "self" not in self.registry.resolved(posture)["components"].get("spatial", {}).get("participants", {})):
            raise CompositionError(f"{ident}: {posture} is not a posture")
        if posture and posture not in {item.get("posture") for item in self.placements.get(ident, [])}:
            self.place(ident, {"posture": posture}, {}, SCENE)  # a posture of its own: its requirements and claims apply
        else:  # the same posture an entry already gave (its claims count once), or none
            self.evaluated += 1
            self.placements.setdefault(ident, []).append({"entry": SCENE, **({"posture": posture} if posture else {}), "anchors": []})
        facing = declared.get("facing")
        if facing is not None:
            kind, other = facing
            if kind not in ("toward", "away_from") or other not in self.beings or other == ident:
                raise CompositionError(f"{ident}: facing must be toward or away_from another cast member")
            self.placements[ident][-1]["facing"] = (kind, (other,))

    # -- after every use is applied
    def check_placements(self):
        for ident, placements in self.placements.items():
            entries = [placement["entry"] for placement in placements]
            for key in ("posture", "orientation", "facing"):
                values = {placement[key] for placement in placements if key in placement}
                if len(values) > 1:
                    self.add("conflict", "placement_conflict",
                             f"{ident} is given different {key}s by {', '.join(dict.fromkeys(entries))}: "
                             f"{', '.join(sorted(str(value) for value in values))}", entries, [ident])
            relations = {}
            for placement in placements:
                for relation, others, _, _ in placement["anchors"]:
                    for other in others:
                        relations.setdefault(other, set()).add(relation)
            for other, found in relations.items():
                for relation in found:
                    if _OPPOSITE.get(relation) in found:
                        self.add("conflict", "placement_conflict",
                                 f"{ident} is both {relation} and {_OPPOSITE[relation]} {other}", entries, [ident, other])
        for ident in sorted(self.bound_beings - {ident for ident, placements in self.placements.items()
                                                 if any("posture" in placement or "orientation" in placement for placement in placements)}):
            self.add("eligible", "placement_undeclared", f"no used entry declares how {ident} is placed", [], [ident])

    def allocate(self):
        allocation = {}
        merged, order = {}, []
        for claim in self.claims:
            if claim["key"]:
                group = (claim["participant"], claim["key"])
                if group in merged:
                    first = merged[group]
                    if (first["resource"], first["count"], first["mode"]) != (claim["resource"], claim["count"], claim["mode"]):
                        self.add("conflict", "key_mismatch",
                                 f"{claim['participant']}: claims sharing key {claim['key']} disagree on resource, count or mode",
                                 [first["entry"], claim["entry"]], [claim["participant"]])
                    first["entries"].append(claim["entry"])
                    continue
                merged[group] = {**claim, "entries": [claim["entry"]]}
                order.append(merged[group])
            else:
                order.append({**claim, "entries": [claim["entry"]]})
        for mode in ("exclusive", "shared"):  # exclusive claims take instances first
            for claim in (item for item in order if item["mode"] == mode):
                ident, resource = claim["participant"], claim["resource"]
                subject = self.subject(ident)
                taken = allocation.setdefault(ident, {})
                exclusive = {name for name, uses in taken.items() if any(use["mode"] == "exclusive" for use in uses)}
                free = [name for name in subject.instances(resource) if name not in exclusive and
                        (mode == "shared" or name not in taken)]
                record = {"entries": claim["entries"], "purpose": claim["purpose"], "mode": mode, "key": claim["key"]}
                if len(free) >= claim["count"]:
                    for name in free[:claim["count"]]:
                        taken.setdefault(name, []).append(record)
                    continue
                total = len(subject.instances(resource))
                claimed = sum(item["count"] for item in order if item["participant"] == ident and item["resource"] == resource)
                if subject.state(resource) == "absent" or (subject.described and implied(self.registry, [resource]) & subject.complete):
                    self.add("conflict", "over_allocated",
                             f"{ident} has {total} {resource} but {claimed} are claimed ({mode} claim by {', '.join(claim['entries'])})",
                             [entry for item in order if item["participant"] == ident and item["resource"] == resource
                              for entry in item["entries"]], [ident])
                else:
                    self.add("unknown", "resources_undeclared",
                             f"{ident}: how many {resource} it has is not declared ({', '.join(claim['entries'])} needs {claim['count']})",
                             claim["entries"], [ident])
        return allocation

    def check_access(self, allocation):
        for a, using, b, regions, kind, entry_id in self.required_access:
            self.check(self.subject(a), {"all_of": [using]}, entry_id, f"{entry_id} (reach with {using})")
            target = self.subject(b)
            self.check(target, {"any_of_groups": [list(regions)]} if len(regions) > 1 else {"all_of": list(regions)},
                       entry_id, f"{entry_id} (reach to {b})")
            provided = [region for region in regions if target.state(region) == "provided"]
            if kind == "touch" and provided:
                blocked = []
                for region in provided:
                    names = target.instances(region)
                    if names and all(any(use["purpose"] == "support" and use["mode"] == "exclusive" for use in allocation.get(b, {}).get(name, []))
                                     for name in names):
                        blocked.append(region)
                if len(blocked) == len(provided):
                    supporters = [entry for name, uses in allocation.get(b, {}).items() for use in uses
                                  if use["purpose"] == "support" for entry in use["entries"]]
                    self.add("conflict", "region_blocked",
                             f"{a} cannot reach {b}'s {', '.join(blocked)}: {b} is resting on it", [entry_id, *supporters], [a, b])
                    continue
            covered = any(fact[0] == a and fact[2] == b and fact[4] == kind
                          and using in implied(self.registry, [fact[1]])
                          and any(region in implied(self.registry, [declared]) for declared in fact[3] for region in regions)
                          for fact in self.facts)
            if not covered:
                self.add("eligible", "access_undeclared",
                         f"no used entry declares that {a} can {'see' if kind == 'sight' else 'reach'} {b}'s "
                         f"{' or '.join(regions)} with {using}", [entry_id], [a, b])


def resolve(registry, composition):
    """Evaluate one composition. Raises CompositionError for malformed input; otherwise returns a Resolution."""
    run = _Run(registry, composition)
    for use in run.uses:
        run.apply(use)
    for ident, declared in composition.get("declared", {}).items():
        run.declare(ident, declared)
    run.check_placements()
    allocation = run.allocate()
    run.check_access(allocation)
    if not run.evaluated:
        # Nothing in the vocabulary spoke about this scene: absence of rules is not support (SPEC.md section 3).
        run.add("unknown", NO_EVIDENCE, "no vocabulary rule applies to this composition, so nothing supports or "
                "rejects it", [use.get("entry") for use in run.uses])
    status = max((finding.status for finding in run.findings), key=RANK.get, default="feasible")
    placements = {}
    for ident, items in run.placements.items():
        summary = {"entries": [item["entry"] for item in items], "anchors": []}
        for item in items:
            for key in ("posture", "orientation", "facing"):
                if key in item:
                    summary[key] = list(item[key]) if isinstance(item[key], tuple) else item[key]
            summary["anchors"] += [{"relation": relation, "of": list(others), "at": at, "distance": distance}
                                   for relation, others, at, distance in item["anchors"]]
        placements[ident] = summary
    access = [{"from": a, "using": using, "to": b, "regions": list(regions), "kind": kind, "entry": entry}
              for a, using, b, regions, kind, entry in run.facts]
    return Resolution(status, sorted(run.findings, key=lambda finding: -RANK[finding.status]), allocation, placements, access)


@dataclass
class Candidates:
    """The outcome of candidate_bindings: resolved bindings, best first, and whether the search finished.

    When truncated is True the search stopped at limit: bindings were left unevaluated, so an absent
    or rejected binding in this list proves nothing about the ones that were not searched."""
    bindings: list        # [(binding, Resolution)], best status first
    searched: int         # bindings resolved
    limit: int
    truncated: bool       # True when unsearched bindings remain

    @property
    def viable(self):
        """True if some searched binding is not a conflict; False only when the search was complete and
        every binding conflicts (or none exists); None when it was truncated without finding one."""
        if any(result.status != "conflict" for _, result in self.bindings):
            return True
        return None if self.truncated else False

    @property
    def note(self):
        if not self.truncated:
            return ""
        return (f"search stopped after {self.searched} bindings (limit {self.limit}); more bindings exist and "
                "were not evaluated, so this list is not proof that no other binding works")

    def __iter__(self):
        return iter(self.bindings)

    def to_dict(self):
        return {"bindings": [{"bind": bind, "resolution": result.to_dict()} for bind, result in self.bindings],
                "searched": self.searched, "limit": self.limit, "truncated": self.truncated,
                "viable": self.viable, "note": self.note}


def _count_range(spec):
    count = spec["count"]
    return (count["min"], count["max"]) if isinstance(count, dict) else (count, count)


def _bindings(slots, cast_ids, object_ids):
    """Every binding of the slots: each slot takes a subset (size within its count) of the members of
    its kind that earlier slots left free, in the cast's order. Larger subsets come first."""
    names = list(slots)

    def fill(index, free, bind):
        if index == len(names):
            yield dict(bind)
            return
        name = names[index]
        kind = slots[name]["kind"]
        low, high = _count_range(slots[name])
        pool = free[kind]
        for size in range(min(high, len(pool)), low - 1, -1):
            for chosen in combinations(pool, size):
                if size:
                    bind[name] = chosen[0] if high == 1 else list(chosen)
                rest = {**free, kind: [ident for ident in pool if ident not in chosen]}
                yield from fill(index + 1, rest, bind)
                bind.pop(name, None)

    yield from fill(0, {"being": list(cast_ids), "object": list(object_ids)}, {})


def candidate_bindings(registry, entry_id, cast, objects=(), space=None, limit=2000):
    """Ways to bind the cast and objects to one entry's slots, resolved and best first (a Candidates).

    Binding uses capabilities only: who may fill a slot is decided by the entry's requirements against
    each body's declared capabilities, never by gender, species or label. A single slot takes one
    member; a group slot takes any subset of the remaining members whose size fits its count (members
    keep the cast's order); a slot whose count allows zero may stay empty. Cast members left out of a
    binding are simply not part of this entry. At most limit bindings are resolved; Candidates.truncated
    reports whether more remained."""
    if entry_id not in registry:
        raise CompositionError(f"unknown entry {entry_id}")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    slots = registry.resolved(entry_id)["components"].get("participants", {}).get("slots", {})
    generator = _bindings(slots, [member["id"] for member in cast], [item["id"] for item in objects])
    results = []
    for bind in generator:
        composition = {"cast": list(cast), "objects": list(objects), "space": space, "use": [{"entry": entry_id, "bind": bind}]}
        results.append((bind, resolve(registry, composition)))
        if len(results) >= limit:
            break
    truncated = len(results) >= limit and next(generator, None) is not None
    results.sort(key=lambda item: RANK[item[1].status])
    return Candidates(results, len(results), limit, truncated)
