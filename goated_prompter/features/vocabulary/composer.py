"""Requirement-driven scene composition (vocabulary/schemas/SPEC.md section 13).

SceneContract combines grounded confirmed intent, lexical requirements and Director
obligations before retrieval. Related search hints are not fulfillment evidence.
Composer searches entries, participant bindings, objects, arrangements and supporting
spaces together, backtracking when later constraints invalidate earlier choices.
Every trial uses the resolver; complete feasible scenes outrank eligible or unknown
ones. Search limits and undeclared requirements never become proof of compatibility.

Selections are deterministic per image and seed. Concrete mechanics, including
visual setups that consume body resources, belong to MODPACK entries, not engine
branches. Unsupported requirements retain an explicit unchecked freeform path.
"""

from dataclasses import dataclass, field
import hashlib
import itertools
import json
import math
import re

from .preferences import Preferences, ROLES
from .packs import pack_schemas
from .resolver import CompositionError, Finding, RANK, enumerate_bindings, object_satisfies, resolve
from .visual import direction, fit
from .semantic import grounded, phrase_terms, split_negated, terms

TRIES = 12            # optional candidates searched per role
BINDINGS = 64         # bindings of one entry tried
ITEMS = 4             # items tried for one object slot (then an undescribed object)
SEARCH_NODES = 2048    # deterministic bound on joint entry/binding search per image
DIRECTOR_TURN = 2     # a Director-named entry is offered to about one image in this many
STANDING = ("director", "style", "hint")  # retrieval sources that prefer, never require
CHECKED = ["every entry, binding and the place were checked together with the resolver while choosing",
           "slot counts, capabilities, placements, exclusive claims, blocked regions, surfaces and declared capacities"]
NOT_CHECKED = ["anything the entries do not declare (it stays open for the scene writer)",
               "prose the scene writer adds: it may not change these facts, but it is not parsed"]
_ID = re.compile(r"\b[a-z][a-z0-9_]*:[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*\b")
_SLOT = re.compile(r"^([a-z][a-z0-9_]*)")


def _unit(*parts):
    digest = hashlib.blake2b("\x1f".join(map(str, parts)).encode("utf-8"), digest_size=8).digest()
    return (int.from_bytes(digest, "big") + 0.5) / 2.0 ** 64


def _count(spec):
    count = spec["count"]
    return (count["min"], count["max"]) if isinstance(count, dict) else (count, count)


def is_posture(entry):
    comp = entry["components"]
    return "self" in comp.get("spatial", {}).get("participants", {}) and not comp.get("participants", {}).get("slots")


def role_of(entry):
    """An entry's role in a scene, from its components only: space, item, arrangement, interaction, or None."""
    comp = entry["components"]
    if entry.get("abstract") is True:
        return None
    if "environment" in comp:
        return "space"
    if "object" in comp:
        return "item"
    slots = comp.get("participants", {}).get("slots", {})
    if any(spec["kind"] == "being" for spec in slots.values()):
        return "arrangement" if "claims" not in comp and comp.get("spatial") else "interaction"
    if is_posture(entry):
        return "arrangement"
    if "visual" in comp:
        return "visual"
    return None


def _phrases(entry):
    return [[term for term in phrase_terms(text) if term != "@"] for text in [entry["name"], *entry.get("aliases", [])]]


def names(entry, words):
    """Whether words (stemmed terms) name the entry: every content word of its name or one alias is among them."""
    words = set(words)
    return any(phrase and set(phrase) <= words for phrase in _phrases(entry))


def span(entry, words):
    """The positions in words (stemmed terms, in order) where the entry's name or an alias occurs in order, as a set;
    empty when it does not. Two entries named by the same words ("hug" naming Hug and an Embrace with the alias hug)
    are alternatives, not two things to do at once."""
    found = set()
    for phrase in _phrases(entry):
        size = len(phrase)
        for start in range(len(words) - size + 1) if size else ():
            if words[start:start + size] == phrase:
                found.update(range(start, start + size))
    return found


def named_spans(registry, ids, words):
    """Matched spans, excluding shorter names contained entirely in another match."""
    matches = {entry_id: span(registry.resolved(entry_id), words) for entry_id in ids}
    return {entry_id: where for entry_id, where in matches.items()
             if not any(where and where < other for other in matches.values())}


def named_groups(registry, ids, words):
    """Overlapping lexical matches are alternatives; disjoint activities are separate obligations."""
    groups = []
    for ident, where in sorted(named_spans(registry, ids, words).items()):
        if not where:
            continue
        overlapping = [group for group in groups if group["span"] & where]
        merged = {"span": set(where), "ids": [ident]}
        for group in overlapping:
            merged["span"] |= group["span"]
            merged["ids"].extend(group["ids"])
            groups.remove(group)
        groups.append(merged)
    return groups


@dataclass
class SceneContract:
    """Confirmed obligations, compiled before retrieval; semantic hints never prove fulfillment."""
    requirements: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    constraints: dict = field(default_factory=dict)

    @classmethod
    def build(cls, registry, brief, preferences, director=""):
        contract = cls(constraints={"request": brief.get("input", {}).get("request", ""),
                                   "rules": brief.get("input", {}).get("rules", []), "fixed": brief.get("fixed", ""),
                                   "must": brief.get("must", []), "avoid": brief.get("avoid", [])})
        intent = brief.get("intent") or {}
        if brief.get("version", 9) >= 10 and intent.get("available"):
            contract.unresolved.extend(intent.get("unresolved", []))
            if intent.get("truncated"):
                contract.unresolved.append("the confirmed intent is truncated")
            for item in intent.get("elements", []):
                if item.get("source") != "request" or item.get("status") != "fixed" or item.get("kind") not in (
                        "action", "pose", "object", "environment"):
                    continue
                sources = [brief.get("input", {}).get("request", ""), brief.get("fixed", ""),
                           *brief.get("must", []), *brief.get("input", {}).get("rules", [])]
                guided = brief.get("input", {}).get("guided_inputs", [])
                if item.get("input", 0) and item["input"] <= len(guided):
                    sources.append(guided[item["input"] - 1])
                if not grounded(item["text"], sources):
                    continue
                words = split_negated(item["text"])[0]
                roles = {"action": ("interaction", "arrangement"), "pose": ("arrangement",),
                         "object": ("item",), "environment": ("space",)}[item["kind"]]
                ids = [ident for ident in registry.ids() if role_of(registry.resolved(ident)) in roles
                       and span(registry.resolved(ident), words)]
                for group in named_groups(registry, ids, words) or [{"ids": []}]:
                    contract.requirements.append({"source": "user", "text": item["text"],
                                                  "input": item.get("input", 0), "entries": sorted(group["ids"])})
            elements = {item["id"]: item for item in intent.get("elements", [])}
            relations = pack_schemas()["entry"]["$defs"]["anchor"]["properties"]["relation"]["enum"]
            for row in intent.get("relations", []):
                if row.get("status") != "fixed":
                    continue
                a, b = elements.get(row["a"], {}), elements.get(row["b"], {})
                relation = row["rel"].strip().lower().replace(" ", "_")
                if relation in relations and a.get("cast") and b.get("cast"):
                    contract.relationships.append({"a": a["cast"], "relation": relation, "b": b["cast"],
                                                   "input": a.get("input", 0) or b.get("input", 0)})
                elif not any(span(registry.resolved(ident), split_negated(row["rel"])[0])
                             for req in contract.requirements for ident in req["entries"]):
                    contract.unresolved.append("unsupported relationship: " + row["rel"])
        for ident in preferences.require:
            contract.requirements.append({"source": "director", "text": ident, "input": 0,
                                          "entries": [ident] if ident in registry else []})
        visual_ids = [ident for ident in registry.ids() if role_of(registry.resolved(ident)) == "visual"]
        visual_groups = {}
        for text in [brief.get("input", {}).get("request", ""), brief.get("fixed", ""),
                     *brief.get("must", []), *brief.get("input", {}).get("rules", [])]:
            words = split_negated(text)[0]
            for ident, where in named_spans(registry, visual_ids, words).items():
                if where:
                    dimension = registry.resolved(ident)["components"]["visual"]["dimension"]
                    visual_groups.setdefault(dimension, set()).add(ident)
        for ids in visual_groups.values():
            contract.requirements.append({"source": "user", "text": " or ".join(registry.resolved(ident)["name"] for ident in sorted(ids)),
                                          "input": 0, "entries": sorted(ids)})
        # Explicit pack-defined names in Director prose are obligations, not related
        # descriptions or the names added by soft preferences.text().
        first = re.split(r"[.!?]", director, maxsplit=1)[0]
        directive = re.match(r"\s*(?:construct|depict|show|require|include)\s+(.+)", first, re.IGNORECASE)
        words = split_negated(directive[1] if directive else "")[0]
        groups = named_groups(registry, [ident for ident in registry.ids() if role_of(registry.resolved(ident))], words)
        if directive and not groups and not preferences.require:
            contract.unresolved.append("unsupported Director requirement: " + directive[1])
        for group in groups:
            ids = group["ids"]
            if not any(set(ids) & set(row["entries"]) for row in contract.requirements if row["source"] == "director"):
                contract.requirements.append({"source": "director", "text": registry.resolved(ids[0])["name"],
                                              "input": 0, "entries": sorted(ids)})
        return contract

    def record(self):
        return {"requirements": self.requirements, "unresolved": self.unresolved, "constraints": self.constraints,
                "relationships": self.relationships,
                "priority": ["user", "director", "preferences"]}


@dataclass
class Composer:
    """The composition of one run. compose(n) is image n's record (cached)."""
    registry: object
    found: object                    # retrieval.Retrieval of the confirmed brief
    brief: dict
    preferences: object = None       # preferences.Preferences (None or empty: none)
    plan: object = None              # visual.Plan: told what each image must show
    allowed: tuple = ("general", "mature", "adult")
    contract: object = None
    _memo: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        labels = [item["label"] for item in self.brief.get("characters", [])]
        self.labels = labels
        self.cast = [{"id": item["character"], "body": item.get("body"), "traits": list(item.get("traits", []))}
                     for item in self.found.cast if item.get("character") in labels]
        if len(self.cast) != len(labels):  # every character must stand in the composition, described or not
            self.cast = [{"id": label, "body": None, "traits": []} for label in labels]
        data = self.brief.get("input", {})
        seed = data.get("seed")
        self.seed = seed if type(seed) is int else 0
        self.guided = data.get("source_mode") == "guided" and bool(data.get("guided_inputs"))
        self.inputs = list(data.get("guided_inputs") or [])
        amount = data.get("amount")
        self.amount = amount if type(amount) is int and amount > 0 else 1
        self.order = self.preferences.order(ROLES) if self.preferences else ROLES
        self.contract = self.contract or SceneContract.build(self.registry, self.brief, self.preferences or Preferences())
        self.directed = self._directed()
        named = {entry.id: entry for entry in self.found.entries}
        # Retrieval omits confirmed conflicts from suggestions, but a named requirement
        # must still reach composition so its image can fail with the resolver's reason.
        ruled_out = {item["id"] for item in self.found.excluded if not item["reason"].startswith("conflict:")}
        self.ruled_out = ruled_out
        conflicts = {item["id"] for item in self.found.excluded if item["reason"].startswith("conflict:")}
        self.asked = {entry_id for entry_id in set(self.found.named_by) | conflicts
                      if set(self.found.named_by.get(entry_id, ())) - set(STANDING) and entry_id not in ruled_out}
        self.guided_named = {}
        if self.guided:
            for text in self.inputs:
                words = split_negated(text)[0]
                matches = [entry_id for entry_id in self.registry.ids()
                           if entry_id not in ruled_out and role_of(self.registry.resolved(entry_id))
                           and names(self.registry.resolved(entry_id), words)]
                self.guided_named[text] = list(named_spans(self.registry, matches, words))
            self.asked.update(entry_id for ids in self.guided_named.values() for entry_id in ids)
        self.director_named = [entry_id for entry_id in named if entry_id not in self.asked]
        self.scores = {entry.id: entry.score for entry in [*self.found.entries, *self.found.inspiration]}
        self.pool = {}
        for entry in [*self.found.entries, *self.found.inspiration]:
            if entry.id in self.registry and self._usable(entry.id):
                role = role_of(self.registry.resolved(entry.id))
                if role:
                    self.pool.setdefault(role, {}).setdefault(entry.id, entry.score)
        self.asked.update(ident for row in self.contract.requirements if row["source"] == "user" for ident in row["entries"])

    # -- what may be used
    def _usable(self, entry_id):
        entry = self.registry.resolved(entry_id)
        if entry_id in self.ruled_out or entry.get("rating") not in self.allowed or role_of(entry) is None:
            return False
        return not (self.preferences and self.preferences.avoids(entry_id) and entry_id not in self.asked
                    and entry_id not in self.preferences.require)

    def _directed(self):
        """[(action words, performers, targets)] from the brief's structured intent: who does an action to whom."""
        intent = self.brief.get("intent") or {}
        if (self.brief.get("version", 9) < 10 or not intent.get("available")
                or intent.get("unresolved") or intent.get("truncated")):
            return []
        elements = {item["id"]: item for item in intent.get("elements", [])}

        def people(ident, depth=0):
            item = elements.get(ident)
            if not item or depth > 4:
                return set()
            if item["kind"] == "subject":
                return set(item.get("cast") or [])
            return people(item.get("of"), depth + 1) if item.get("of") else set()
        out = []
        for item in elements.values():
            if item["kind"] != "action" or item.get("status") == "excluded":
                continue
            performers = set().union(*(people(ident) for ident in item.get("by", []))) if item.get("by") else set()
            targets = set().union(*(people(ident) for ident in item.get("to", []))) if item.get("to") else set()
            if performers or targets:
                out.append((set(terms(" ".join([item["text"], *item.get("terms", [])]))), performers, targets,
                            item.get("input", 0)))
        return out

    def required(self, number):
        """{role: [[ids], ...]} the request (or this image's guided input) requires for image number: one group per
        thing it asks for, and every group must be met (for the arrangement and the place, one group). Entries named by
        the same words are one group of alternatives, which take turns across the images."""
        if self.guided:
            text = self.inputs[(number - 1) % len(self.inputs)] if self.inputs else ""
            shared = [self.brief.get("fixed", ""), *self.brief.get("must", []),
                      *self.brief.get("input", {}).get("rules", [])]
            words = [term for source in [text, *shared] for term in [*split_negated(source)[0], "|"]]
            shared_ids = {entry_id for entry_id in self.asked
                          if set(self.found.named_by.get(entry_id, ())) & {"fixed", "must", "rules"}}
            ids = [entry_id for entry_id in set(self.guided_named.get(text, [])) | shared_ids if self._usable(entry_id)]
        else:
            data = self.brief.get("input", {})
            texts = [data.get("request", ""), self.brief.get("summary", ""), *self.brief.get("must", []),
                     *data.get("rules", []), self.brief.get("fixed", "")]
            words = [term for text in texts for term in [*terms(text), "|"]]
            ids = [entry_id for entry_id in self.asked if entry_id in self.registry and self._usable(entry_id)]
        groups = named_groups(self.registry, ids, words)
        by_role = {}
        for group in groups:
            group["ids"].sort()
            # Alias alternatives can declare different mechanics. Try the group once,
            # at the earliest role it can fill, rather than requiring both roles.
            role = min((role_of(self.registry.resolved(entry_id)) for entry_id in group["ids"]),
                       key=(*self.order, "item", "visual").index)
            by_role.setdefault(role, []).append(group)
        out = {}
        for role, items in by_role.items():
            if role in ("arrangement", "space"):  # one arrangement and one place: named ones are alternatives
                items = [{"span": set(), "ids": [entry_id for group in items for entry_id in group["ids"]]}]
            rotated = []
            for group in items:
                shift = (number - 1) % len(group["ids"])
                rotated.append(group["ids"][shift:] + group["ids"][:shift])
            out[role] = rotated
        scope = (number - 1) % len(self.inputs) + 1 if self.guided else 0
        for row in self.contract.requirements:
            if ((not row["input"] or row["input"] == scope) and row["entries"]
                    and all(role_of(self.registry.resolved(ident)) == "item" for ident in row["entries"])
                    and row["entries"] not in out.get("item", [])):
                out.setdefault("item", []).append(row["entries"])
        return out

    def candidates(self, role, number, required):
        """Ordered candidate ids for one role of image number (required ones are handled apart)."""
        seen, out = set(required), []

        def add(entry_id):
            if entry_id not in seen and entry_id in self.pool.get(role, {}):
                seen.add(entry_id)
                out.append(entry_id)
        for entry in self.found.ideas(number):
            add(entry.id)
        for entry_id in self.director_named:
            if int(hashlib.sha256(f"{self.seed}\0{entry_id}\0{number}".encode()).hexdigest(), 16) % DIRECTOR_TURN == 0:
                add(entry_id)
        weight = self.preferences.weight if self.preferences else (lambda entry_id: 1.0)
        rest = sorted(self.pool.get(role, {}),
                      key=lambda entry_id: -math.log(_unit(self.seed, number, role, entry_id))
                      / (max(self.pool[role][entry_id], 1e-9) * weight(entry_id)))
        for entry_id in rest:
            add(entry_id)
        return out

    # -- building one image
    def compose(self, number):
        if number in self._memo:
            return self._memo[number]
        record = self._compose(number)
        selected_visual = [entry["id"] for entry in record.get("entries", [])
                           if "visual" in self.registry.resolved(entry["id"])["components"]]
        if self.plan is not None:
            self.plan.see(number, record.get("visibility") if record["kind"] == "vocabulary" else None, selected_visual)
        if record["kind"] == "vocabulary":
            fields = {}
            for ident in selected_visual:
                item = direction(self.registry, ident)
                fields.setdefault(item.section, []).append(item.text())
            record["visual"] = self.plan.concept(number) if self.plan else {
                section: "; ".join(parts) for section, parts in fields.items()}
            record["verified"] = record["status"] == "feasible"
            if not record["verified"]:
                record["checked"] = []
        self._memo[number] = record
        return record

    def _compose(self, number):
        composition = {"cast": self.cast, "objects": [], "space": None, "use": [], "declared": {}, "slot": number}
        notes = []
        required = self.required(number)
        scope = (number - 1) % len(self.inputs) + 1 if self.guided else 0
        composition["relationships"] = [row for row in self.contract.relationships if not row["input"] or row["input"] == scope]
        obligations = [row for row in self.contract.requirements if not row["input"] or row["input"] == scope]
        unsupported = [row["text"] for row in obligations if not row["entries"]]
        if unsupported or self.contract.unresolved:
            return {"kind": "freeform", "status": "unchecked", "slot": number,
                    "reason": "unsupported scene requirements: " + "; ".join([*unsupported, *self.contract.unresolved]),
                    "contract": self.contract.record(), "skipped": []}
        # Named lexical requirements and confirmed intent share one set of groups.
        # Each group is an OR; all groups are mandatory. User groups precede Director groups.
        tasks = [group for role in (*self.order, "visual") for group in required.get(role, [])]
        for row in obligations:
            if all(role_of(self.registry.resolved(ident)) == "item" for ident in row["entries"]):
                continue  # required() also exposes these groups to object-slot search
            elif not any(set(group) <= set(row["entries"]) for group in tasks):
                tasks.append(row["entries"])
        named = [entry_id for groups in required.values() for group in groups for entry_id in group]
        if self.guided and not named:
            return {"kind": "freeform", "status": "unchecked", "slot": number,
                    "reason": "no vocabulary entry matches this image's guided input", "skipped": []}
        mandatory_count = len(tasks)
        for role in self.order:
            if not required.get(role) and not (role == "arrangement" and not self.cast):
                tasks.append(self.candidates(role, number, named)[:TRIES])
        best, best_rank, nodes = None, None, 0
        conflicts = []

        def search(current, index):
            nonlocal best, best_rank, nodes
            if nodes >= SEARCH_NODES:
                return False
            nodes += 1
            if index == len(tasks):
                if any(not {obj["item"] for obj in current["objects"]}.intersection(group)
                       for group in required.get("item", [])):
                    return False
                result = self._resolve(current)
                if result is None or result.status == "conflict":
                    return False
                rank = (RANK[result.status], -len(current["use"]), -bool(current["space"]))
                if best_rank is None or rank < best_rank:
                    best, best_rank = (current, result), rank
                return result.status == "feasible"
            used = {use["entry"] for use in current["use"]}
            for ident in tasks[index]:
                if ident in used:
                    if search(current, index + 1):
                        return True
                    continue
                if ident not in self.registry or not self._usable(ident):
                    continue
                extended = False
                for trial, _ in self.options(current, ident, number):
                    extended = True
                    if search(trial, index + 1):
                        return True
                    if nodes >= SEARCH_NODES:
                        break
                if not extended and index < mandatory_count and len(conflicts) < 8:
                    conflicts.append(f"{self.name(ident)}: {self.why_not(current, ident, number)}")
            return search(current, index + 1) if index >= mandatory_count else False

        search(composition, 0)
        if best is None:
            names_required = [" or ".join(self.name(ident) for ident in group) for group in tasks[:mandatory_count]]
            reasons = conflicts
            return {"kind": "freeform" if nodes >= SEARCH_NODES else "failed", "status": "unchecked", "slot": number,
                    "reason": ("joint search limit reached before satisfying " if nodes >= SEARCH_NODES
                               else "no compatible joint composition found within search limits for ")
                    + ", ".join(names_required or ["the required objects"])
                    + " (" + "; ".join(reasons or ["no compatible object slot"]) + ")",
                    "search_exhausted": nodes >= SEARCH_NODES, "contract": self.contract.record()}
        composition, result = best
        if nodes >= SEARCH_NODES:
            notes.append("joint search budget reached; feasibility has not been established" if result.status != "feasible"
                         else "joint search budget reached")
        if self.cast and not any(composition["use"]) and not composition["declared"]:
            return {"kind": "freeform", "status": "unchecked", "slot": number,
                    "reason": "no vocabulary entry places these people in this image", "skipped": notes[:6]}
        if not self.cast and not composition["space"]:
            return {"kind": "freeform", "status": "unchecked", "slot": number,
                    "reason": "no vocabulary place for this image", "skipped": notes[:6]}
        return self.record(number, composition, result, notes)

    def options(self, composition, entry_id, number):
        """All bounded nonconflicting bindings, so later requirements can revise earlier decisions."""
        entry = self.registry.resolved(entry_id)
        role = role_of(entry)
        if role == "space":
            if composition["space"]:
                return
            trial = {**composition, "space": entry_id}
            result = self._resolve(trial)
            if result is not None and result.status != "conflict":
                yield trial, result
            return
        if is_posture(entry):
            for ident in self._order(number, entry_id, [member["id"] for member in self.cast]):
                if ident in composition["declared"] or self._placed(composition, ident):
                    continue
                trial = {**composition, "declared": {**composition["declared"], ident: {"posture": entry_id}}}
                result = self._resolve(trial)
                if result is not None and result.status != "conflict":
                    yield trial, result
            return
        slots = entry["components"].get("participants", {}).get("slots", {})
        being_slots = {slot: spec for slot, spec in slots.items() if spec["kind"] == "being"}
        object_slots = {slot: spec for slot, spec in slots.items() if spec["kind"] == "object"}
        index = len(composition["use"]) + 1
        for objects in self._object_options(entry_id, object_slots, number, index, composition):
            bindings = list(itertools.islice(enumerate_bindings(being_slots, [member["id"] for member in self.cast], []), BINDINGS * 4))
            for bind in self._rank(entry, bindings, number, role):
                full = {**bind}
                for slot, ids in objects["bind"].items():
                    full[slot] = ids
                trial = {**composition, "objects": [*composition["objects"], *objects["objects"]],
                         "use": [*composition["use"], {"entry": entry_id, "bind": full}]}
                result = self._resolve(trial)
                if result is not None and result.status != "conflict":
                    yield trial, result

    def _object_options(self, entry_id, object_slots, number, index, composition=None):
        """Slot-specific providers from the selected registry; reuse existing objects before making instances.
        An undescribed fallback remains unknown and never outranks a declared feasible composition."""
        if not object_slots:
            yield {"objects": [], "bind": {}}
            return
        required = [item for group in self.required(number).get("item", []) for item in group]
        items = [entry.id for entry in self.found.inspiration if entry.attach_to and entry_id in entry.attach_to]
        items = [item for item in dict.fromkeys([*(entry.id for entry in self.found.entries
                                                     if role_of(self.registry.resolved(entry.id)) == "item"), *required, *items])
                 if self._usable(item)]
        # Required capabilities reach their providers even if text retrieval did
        # not offer them. Filter each slot separately before applying the limit.
        items += [ident for ident in self.registry.ids() if role_of(self.registry.resolved(ident)) == "item"
                  and self._usable(ident) and ident not in items]
        slots = sorted(object_slots.items())
        conditions = self.registry.resolved(entry_id)["components"].get("requirements", {}).get("participants", {})
        options = []
        for slot, _ in slots:
            condition = conditions.get(slot, {})

            ranked = sorted(set(items), key=lambda item: (item not in required,
                            _unit(self.seed, number, f"items:{entry_id}:{slot}", item)))
            candidates = [item for item in ranked if object_satisfies(self.registry, item, condition)][:ITEMS]
            reused = [(obj["item"], obj["id"]) for obj in (composition or {}).get("objects", []) if obj["item"] in candidates]
            options.append([*reused, *((item, None) for item in candidates), *([(None, None)] if not required else [])])
        for choices in itertools.islice(itertools.product(*options), BINDINGS):
            objects, bind = [], {}
            for (slot, spec), (item, existing) in zip(slots, choices):
                low, high = _count(spec)
                amount = min(max(low, 1), high)
                ids = [existing] if existing and amount == 1 else [f"{slot} {index}.{n}" for n in range(1, amount + 1)]
                objects += [{"id": ident, "item": item} for ident in ids if ident != existing]
                bind[slot] = ids if len(ids) != 1 else ids[0]
            yield {"objects": objects, "bind": bind}

    def _rank(self, entry, bindings, number, role):
        """Bindings that keep the brief's who-does-what; for an arrangement,
        those that place more of the cast; then a seeded order, so who takes which role varies across images."""
        performers, targets = self._sides(entry)
        being_slots = {slot for slot, spec in entry["components"].get("participants", {}).get("slots", {}).items()
                       if spec["kind"] == "being"}
        if len(being_slots) == 1 and not performers:
            performers = being_slots
        if len(being_slots) > 1 and performers == being_slots and not targets:
            # Explicit co-performers share the activity, regardless of the brief's by/to phrasing.
            targets = performers
        scope = (number - 1) % len(self.inputs) + 1 if self.guided else 0
        wanted = [(who, whom) for words, who, whom, source in self.directed
                  if (not source or source == scope) and names(entry, words)]

        def keeps(bind):
            if not wanted or not (performers or targets):
                return True
            bound = lambda slots: {ident for slot in slots for ident in (bind.get(slot) if isinstance(bind.get(slot), list)
                                                                        else [bind.get(slot)] if bind.get(slot) else [])}
            return any(who <= bound(performers) and whom <= bound(targets) for who, whom in wanted)

        def size(bind):
            return sum(len(value) if isinstance(value, list) else 1 for value in bind.values())
        return sorted((bind for bind in bindings if keeps(bind)), key=lambda bind: (-size(bind) if role == "arrangement" else 0,
                                                  _unit(self.seed, number, entry["id"], json.dumps(bind, sort_keys=True))))[:BINDINGS]

    def _sides(self, entry):
        """(performer slots, target slots): who reaches and who is reached in the entry's declared access."""
        comp = entry["components"]
        slots = comp.get("participants", {}).get("slots", {})
        if any("role" in spec for spec in slots.values()):
            return ({slot for slot, spec in slots.items() if spec.get("role") == "performer"},
                    {slot for slot, spec in slots.items() if spec.get("role") == "target"})
        access = [*comp.get("spatial", {}).get("access", []), *comp.get("requirements", {}).get("access", [])]
        slot = lambda ref: _SLOT.match(ref).group(1) if _SLOT.match(ref) else ref
        return ({slot(item["from"]) for item in access}, {slot(item["to"]) for item in access})

    def _order(self, number, key, items):
        return sorted(items, key=lambda item: _unit(self.seed, number, key, item))

    def _resolve(self, composition):
        try:
            result = resolve(self.registry, composition)
        except CompositionError:
            return None
        selected = [direction(self.registry, use["entry"]) for use in composition["use"]
                    if "visual" in self.registry.resolved(use["entry"])["components"]]
        if self.plan:
            # User-fixed camera choices are constraints, not optional decorations.
            selected += [pool[0] for dim, pool in self.plan.pools.items()
                         if self.plan.dimensions[dim]["status"] == "fixed" and len(pool) == 1]
            self.plan.see(composition.get("slot", 1), result.visibility, [item.id for item in selected])
            selected += [item for item in self.plan.directions(composition.get("slot", 1))[0].values()
                         if item.id not in {existing.id for existing in selected}]
        for index, item in enumerate(selected):
            status, reason = fit(self.registry, item.showing(), result.visibility)
            if status != "feasible":
                result.findings.append(Finding(status, "visual_visibility", reason or "visual coverage is undeclared", (item.id,)))
            for other in selected[:index]:
                if (item.id != other.id and (item.dimension == other.dimension
                        or item.id in other.conflicts or other.id in item.conflicts)):
                    result.findings.append(Finding("conflict", "visual_conflict", "incompatible visual directions", (item.id, other.id)))
        result.status = max([result.status, *(finding.status for finding in result.findings)], key=RANK.get)
        return result

    def _placed(self, composition, ident):
        result = self._resolve(composition)
        return bool(result and result.placements.get(ident, {}).get("posture"))

    def why_not(self, composition, entry_id, number):
        """The first conflict of the entry's best binding against the scene so far, in the brief's words."""
        entry = self.registry.resolved(entry_id)
        if role_of(entry) == "space" and composition["space"]:
            return "the image already has a place"
        if is_posture(entry):
            trials = [{**composition, "declared": {**composition["declared"], member["id"]: {"posture": entry_id}}}
                      for member in self.cast if member["id"] not in composition["declared"]]
        elif role_of(entry) == "space":
            trials = [{**composition, "space": entry_id}]
        else:
            slots = entry["components"].get("participants", {}).get("slots", {})
            beings = {slot: spec for slot, spec in slots.items() if spec["kind"] == "being"}
            objects = next(self._object_options(entry_id, {s: v for s, v in slots.items() if v["kind"] == "object"},
                                                number, len(composition["use"]) + 1), None)
            if objects is None:
                return "no declared object satisfies its required capabilities"
            trials = [{**composition, "objects": [*composition["objects"], *objects["objects"]],
                       "use": [*composition["use"], {"entry": entry_id, "bind": {**bind, **objects["bind"]}}]}
                       for bind in itertools.islice(enumerate_bindings(beings, [member["id"] for member in self.cast], []), 8)]
        for trial in trials:
            result = self._resolve(trial)
            if result is not None:
                conflicts = [finding for finding in result.findings if finding.status == "conflict"]
                if conflicts:
                    return self.humanize(conflicts[0].message)
        return "no binding of this cast fits it" if trials else "nobody is left to take it"

    # -- the record
    def name(self, entry_id):
        return self.registry.resolved(entry_id)["name"] if entry_id in self.registry else entry_id

    def humanize(self, text):
        return _ID.sub(lambda match: self.name(match.group()) if match.group() in self.registry else match.group(), text)

    def record(self, number, composition, result, notes):
        entries = []
        for use in composition["use"]:
            slots = self.registry.resolved(use["entry"])["components"].get("participants", {}).get("slots", {})
            roles = {slot: (value if isinstance(value, list) else [value]) for slot, value in sorted(use["bind"].items())
                     if slots[slot]["kind"] == "being"}
            entries.append({"id": use["entry"], "name": self.name(use["entry"]), "pack": self.registry.owner(use["entry"]),
                            "role": role_of(self.registry.resolved(use["entry"])), "roles": roles,
                            "objects": {slot: value if isinstance(value, list) else [value]
                                        for slot, value in use["bind"].items() if slots[slot]["kind"] == "object"}})
        for ident, declared in sorted(composition["declared"].items()):
            entries.append({"id": declared["posture"], "name": self.name(declared["posture"]),
                            "pack": self.registry.owner(declared["posture"]), "role": "arrangement", "roles": {"self": [ident]}})
        items = [{"id": item["item"], "name": self.name(item["item"]), "object": item["id"]}
                 for item in composition["objects"] if item["item"]]
        open_objects = [item["id"] for item in composition["objects"] if not item["item"]]
        space = composition["space"]
        placed = set(result.placements)
        record = {"kind": "vocabulary", "composed": True, "slot": number, "status": result.status, "entries": entries,
                  "space": {"id": space, "name": self.name(space),
                            "description": " ".join(str(self.registry.resolved(space).get("description", "")).split())}
                  if space else None,
                  "items": items, "open_objects": open_objects,
                  "placements": result.placements, "facts": facts(self.registry, result, self.name),
                  "unplaced": [label for label in self.labels if label not in placed],
                  "visibility": result.visibility,
                  "findings": [{**finding.to_dict(), "message": self.humanize(finding.message)}
                               for finding in result.findings if finding.status != "feasible"][:8],
                   "verified": result.status == "feasible", "contract": self.contract.record(),
                   "checked": CHECKED if result.status == "feasible" else [], "not_checked": NOT_CHECKED}
        if notes:
            record["skipped"] = notes[:6]
        return record

    def summary(self):
        """Run-level diagnostics: each image's composition, or why it is freeform or failed."""
        rows = []
        for number in range(1, self.amount + 1):
            record = self.compose(number)
            row = {"slot": number, "kind": record["kind"]}
            if record["kind"] == "vocabulary":
                row.update(status=record["status"], entries=[entry["id"] for entry in record["entries"]],
                           space=record["space"]["id"] if record["space"] else None, items=[item["id"] for item in record["items"]])
            else:
                row["reason"] = record["reason"]
            rows.append(row)
        return {"enabled": True, "order": list(self.order), "required": sorted(self.asked) if not self.guided else "per guided input",
                "contract": self.contract.record(),
                "director_named": sorted(self.director_named),
                **({"director": self.preferences.record()} if self.preferences else {}), "images": rows}


def facts(registry, result, name=None):
    """A composed scene as short lines for the scene writer and the Builder (declared data, never prose)."""
    name = name or (lambda entry_id: registry.resolved(entry_id)["name"] if entry_id in registry else entry_id)
    lines = []
    for who, placement in sorted(result.placements.items()):
        parts = []
        if placement.get("posture"):
            parts.append(name(placement["posture"]).lower())
        if placement.get("orientation") and not placement.get("posture"):
            parts.append(placement["orientation"].replace("_", " "))
        if placement.get("facing"):
            way, others = placement["facing"]
            parts.append(f"facing {way.replace('_', ' ')} {' and '.join(others)}" if way != "world" else f"facing {others}")
        for anchor in placement.get("anchors", []):
            where = f" at {name(anchor['at']).lower()}" if anchor.get("at") else ""
            parts.append(f"{anchor['relation'].replace('_', ' ')} {' and '.join(anchor['of'])}{where}"
                         + (f" ({anchor['distance']})" if anchor.get("distance") else ""))
        if parts:
            lines.append(f"{who}: " + ", ".join(dict.fromkeys(parts)))
    for fact in result.access:
        regions = " or ".join(name(region).lower() for region in fact["regions"])
        line = (f"{fact['from']} {'sees' if fact['kind'] == 'sight' else 'touches'} {fact['to']}'s {regions} "
                f"with {name(fact['using']).lower()}")
        if line not in lines:
            lines.append(line)
    for who, instances in sorted(result.allocation.items()):
        for instance, uses in sorted(instances.items()):
            purposes = sorted({use["purpose"] for use in uses if use["mode"] == "exclusive"})
            if purposes:
                lines.append(f"{who}'s {instance.replace('_', ' ').replace('.', ' ')}: {', '.join(purposes)}")
    return lines


def scene_mechanics(record, labels):
    """(position by label, actions) of a composed scene, rendered from its facts: what the vocabulary fixed. A person no
    entry places gets "" (the scene writer fills it, marked as not set by the vocabulary)."""
    position = {}
    for label in labels:
        lines = [line.split(": ", 1)[1] for line in record["facts"] if line.startswith(f"{label}: ")]
        own = [line for line in record["facts"] if line.startswith(f"{label}'s ") or line.startswith(f"{label} touches ")
               or line.startswith(f"{label} sees ")]
        position[label] = "; ".join([*lines, *own])
    acts = []
    for entry in record["entries"]:
        roles = "; ".join(f"{role}: {', '.join(who)}" for role, who in entry["roles"].items())
        acts.append(f"{entry['name']} ({roles})" if roles else entry["name"])
    items = [f"{item['name']} ({item['object']})" for item in record["items"]]
    actions = "; ".join(acts) + (f"; with {', '.join(items)}" if items else "")
    return position, actions
