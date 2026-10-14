"""Phase 1 contracts of the vocabulary specification (vocabulary/schemas/SPEC.md).

These tests check the files, not a resolver: schemas, references, inheritance, ratings, participant
references, claim keys and the stress-test scenarios. Scenario statuses are what the Phase 3 resolver
must report; here only the data each expectation relies on is checked.
"""

import json
import re
import unittest
from pathlib import Path

import jsonschema  # required (requirements-local.txt): schema validation is mandatory, never skipped

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "vocabulary" / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PACK_DIRS = [ROOT / "vocabulary" / "core", FIXTURES / "packs" / "fantasy", FIXTURES / "packs" / "adult"]
SCENARIOS = sorted((FIXTURES / "scenarios").glob("*.json"))
RATINGS = ["general", "mature", "adult"]
REF = re.compile(r"^(?P<slot>[a-z][a-z0-9_]*)(\[(?P<index>-?[0-9]+|\*|[0-9]*:[0-9]*|i|i(?P<rel>[+-][0-9]+))\])?$")
KEY_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load():
    """{pack_id: manifest}, {entry_id: (entry, pack_id)}, {pack_id: folder}."""
    manifests, entries, folders = {}, {}, {}
    for folder in PACK_DIRS:
        manifest = read(folder / "manifest.json")
        manifests[manifest["id"]], folders[manifest["id"]] = manifest, folder
        for name in manifest["files"]:
            for entry in read(folder / name)["entries"]:
                assert entry["id"] not in entries, f"duplicate id {entry['id']}"
                entries[entry["id"]] = (entry, manifest["id"])
    return manifests, entries, folders


MANIFESTS, ENTRIES, FOLDERS = load()


def components(entry_id):
    return ENTRIES[entry_id][0]["components"]


def is_capability(entry_id):
    return entry_id in ENTRIES and "capability" in components(entry_id)


def ancestors(entry_id):
    """The entry and everything it extends, depth first."""
    seen, order = set(), []
    def visit(current):
        if current not in seen:
            seen.add(current)
            order.append(current)
            for parent in ENTRIES[current][0].get("extends", []):
                visit(parent)
    visit(entry_id)
    return order


def implied(capabilities):
    """Capabilities plus everything they imply, transitively."""
    result, stack = set(), list(capabilities)
    while stack:
        current = stack.pop()
        if current not in result:
            result.add(current)
            stack.extend(components(current)["capability"].get("implies", []))
    return result


def body_parts(body_ids):
    """Merged resources, provided capabilities and complete_for of bodies and traits with their parents."""
    resources, provides, complete = {}, set(), set()
    for body_id in body_ids:
        for entry_id in ancestors(body_id):
            body = components(entry_id).get("body", {})
            resources.update(body.get("resources", {}))
            provides.update(body.get("provides", []))
            complete.update(body.get("complete_for", []))
    provides.update(item["type"] for item in resources.values())
    return resources, implied(provides), complete


def slots(entry_id):
    merged = {}
    for current in reversed(ancestors(entry_id)):
        merged.update(components(current).get("participants", {}).get("slots", {}))
    return merged


def required_packs(pack_id):
    result, stack = set(), [pack_id]
    while stack:
        current = stack.pop()
        if current not in result:
            result.add(current)
            stack.extend(MANIFESTS[current].get("requires", {}))
    return result


def capability_refs(comp):
    """Every capability reference in an entry's components, with where it was found."""
    found = []
    found += [("implies", ref) for ref in comp.get("capability", {}).get("implies", [])]
    body = comp.get("body", {})
    found += [("resource type", item["type"]) for item in body.get("resources", {}).values()]
    found += [("body provides", ref) for ref in body.get("provides", [])]
    found += [("complete_for", ref) for ref in body.get("complete_for", [])]
    requirements = comp.get("requirements", {})
    for condition in [*requirements.get("participants", {}).values(), requirements.get("space", {})]:
        for key in ("all_of", "any_of", "none_of"):
            found += [(key, ref) for ref in condition.get(key, [])]
    for access in [*requirements.get("access", []), *comp.get("spatial", {}).get("access", [])]:
        found += [("access using", access["using"])] + [("access region", ref) for ref in access["regions"]]
    for placement in comp.get("spatial", {}).get("participants", {}).values():
        found += [("anchor at", anchor["at"]) for anchor in placement.get("anchors", []) if "at" in anchor]
    for claims in comp.get("claims", {}).values():
        found += [("claim resource", claim["resource"]) for claim in claims]
    found += [("object provides", ref) for ref in comp.get("object", {}).get("provides", [])]
    found += [("object complete_for", ref) for ref in comp.get("object", {}).get("complete_for", [])]
    found += [("environment provides", ref) for ref in comp.get("environment", {}).get("provides", [])]
    return found


def participant_refs(comp):
    """Every participant reference with the rule it belongs to (for i / i+k pairing)."""
    refs = []
    requirements, spatial = comp.get("requirements", {}), comp.get("spatial", {})
    refs += [(ref, None) for ref in requirements.get("participants", {})]
    refs += [(ref, None) for ref in spatial.get("participants", {})]
    refs += [(ref, None) for ref in comp.get("claims", {})]
    for number, access in enumerate([*requirements.get("access", []), *spatial.get("access", [])]):
        refs += [(access["from"], number), (access["to"], number)]
    for placement in spatial.get("participants", {}).values():
        if "facing" in placement:
            refs += [(value, None) for key, value in placement["facing"].items() if key != "world"]
        for anchor in placement.get("anchors", []):
            refs += [(value, None) for value in (anchor["of"] if isinstance(anchor["of"], list) else [anchor["of"]])]
    return refs


class SchemaValidation(unittest.TestCase):
    def test_schemas_are_valid_json_schema(self):
        for name in ("manifest", "entry"):
            jsonschema.Draft202012Validator.check_schema(read(SCHEMAS / f"{name}.schema.json"))
        jsonschema.Draft202012Validator.check_schema(read(FIXTURES / "scenario.schema.json"))

    def test_every_file_matches_its_schema(self):
        manifest_schema = jsonschema.Draft202012Validator(read(SCHEMAS / "manifest.schema.json"))
        entry_schema = jsonschema.Draft202012Validator(read(SCHEMAS / "entry.schema.json"))
        for pack_id, folder in FOLDERS.items():
            manifest_schema.validate(MANIFESTS[pack_id])
            for name in MANIFESTS[pack_id]["files"]:
                with self.subTest(file=f"{pack_id}/{name}"):
                    entry_schema.validate(read(folder / name))
        scenario_schema = jsonschema.Draft202012Validator(read(FIXTURES / "scenario.schema.json"))
        for path in SCENARIOS:
            with self.subTest(scenario=path.name):
                scenario_schema.validate(read(path))

    def test_unknown_keys_and_code_are_rejected(self):
        entry_schema = jsonschema.Draft202012Validator(read(SCHEMAS / "entry.schema.json"))
        base = {"id": "test:thing", "category": "thing", "name": "Thing", "components": {}}
        for extra in ({"script": "print(1)"}, {"attributes": {"anything": 1}}, {"components": {"behaviour": {}}}):
            with self.subTest(extra=extra):
                self.assertFalse(entry_schema.is_valid({"spec": 1, "entries": [{**base, **extra}]}))


class PackContracts(unittest.TestCase):
    def test_manifest_files_match_the_pack_folder(self):
        for pack_id, folder in FOLDERS.items():
            listed = set(MANIFESTS[pack_id]["files"])
            present = {path.name for path in folder.glob("*.json")} - {"manifest.json"}
            self.assertEqual(listed, present, pack_id)

    def test_dependencies_exist_and_versions_satisfy(self):
        def version(text):
            return tuple(int(part) for part in text.split("."))
        operators = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
                     "<": lambda a, b: a < b, "=": lambda a, b: a == b}
        for pack_id, manifest in MANIFESTS.items():
            for required, spec in manifest.get("requires", {}).items():
                self.assertIn(required, MANIFESTS, f"{pack_id} requires missing pack {required}")
                for part in spec.split():
                    op = re.match(r"^(>=|>|<=|<|=)?", part).group(1) or "="
                    self.assertTrue(operators[op](version(MANIFESTS[required]["version"]), version(part[len(op):])),
                                    f"{pack_id}: {required} {MANIFESTS[required]['version']} does not satisfy {spec}")

    def test_entry_ids_carry_their_pack_prefix(self):
        for entry_id, (_, pack_id) in ENTRIES.items():
            self.assertEqual(entry_id.split(":", 1)[0], pack_id, entry_id)

    def test_categories_are_declared_by_the_pack_or_its_requirements(self):
        for entry_id, (entry, pack_id) in ENTRIES.items():
            declared = {category["id"] for pack in required_packs(pack_id) for category in MANIFESTS[pack].get("categories", [])}
            self.assertIn(entry["category"], declared, entry_id)

    def test_entry_category_is_not_an_engine_enum(self):
        # Rule: no hardcoded category list. The schema only constrains the category's spelling.
        category = read(SCHEMAS / "entry.schema.json")["$defs"]["entry"]["properties"]["category"]
        self.assertNotIn("enum", json.dumps(category))

    def test_ratings_are_never_looser_than_the_pack(self):
        for entry_id, (entry, pack_id) in ENTRIES.items():
            pack_rating = MANIFESTS[pack_id]["rating"]
            self.assertGreaterEqual(RATINGS.index(entry.get("rating", pack_rating)), RATINGS.index(pack_rating), entry_id)


class ReferenceContracts(unittest.TestCase):
    def test_references_resolve_within_reachable_packs(self):
        for entry_id, (entry, pack_id) in ENTRIES.items():
            reachable = required_packs(pack_id)
            comp = entry["components"]
            refs = [("extends", ref) for ref in entry.get("extends", [])] + capability_refs(comp)
            refs += [("posture", placement["posture"]) for placement in comp.get("spatial", {}).get("participants", {}).values()
                     if "posture" in placement]
            for where, ref in refs:
                with self.subTest(entry=entry_id, where=where, ref=ref):
                    self.assertIn(ref, ENTRIES)
                    self.assertIn(ENTRIES[ref][1], reachable, "reference into a pack that is not required")
                    if where == "posture":
                        self.assertIn("self", components(ref).get("spatial", {}).get("participants", {}))
                    elif where != "extends":
                        self.assertTrue(is_capability(ref), "must reference a capability entry")

    def test_inheritance_has_no_cycles(self):
        for entry_id in ENTRIES:
            visiting = set()
            def visit(current):
                self.assertNotIn(current, visiting, f"cycle through {current}")
                visiting.add(current)
                for parent in ENTRIES[current][0].get("extends", []):
                    visit(parent)
                visiting.discard(current)
            visit(entry_id)

    def test_inherited_resources_do_not_contradict(self):
        for entry_id in ENTRIES:
            seen = {}
            for current in ancestors(entry_id):
                for name, resource in components(current).get("body", {}).get("resources", {}).items():
                    self.assertEqual(seen.setdefault(name, resource), resource, f"{entry_id}: {name}")

    def test_inherited_requirements_do_not_contradict(self):
        for entry_id in ENTRIES:
            needs, forbids = {}, {}
            for current in ancestors(entry_id):
                for ref, condition in components(current).get("requirements", {}).get("participants", {}).items():
                    needs.setdefault(ref, set()).update(condition.get("all_of", []))
                    forbids.setdefault(ref, set()).update(condition.get("none_of", []))
            for ref in needs:
                self.assertFalse(needs[ref] & forbids.get(ref, set()), f"{entry_id}: {ref}")

    def test_participant_references_name_real_slots(self):
        for entry_id in ENTRIES:
            comp, entry_slots = components(entry_id), slots(entry_id)
            is_posture = "self" in comp.get("spatial", {}).get("participants", {})
            for ref, rule in participant_refs(comp):
                with self.subTest(entry=entry_id, ref=ref):
                    if ref == "center" or (ref == "self" and is_posture):
                        continue
                    match = REF.match(ref)
                    self.assertIsNotNone(match)
                    slot = entry_slots.get(match["slot"])
                    self.assertIsNotNone(slot, "unknown slot")
                    index = match["index"]
                    if index is None or index == "*" or ":" in index:
                        continue
                    count = slot["count"] if isinstance(slot["count"], dict) else {"min": slot["count"], "max": slot["count"]}
                    if re.fullmatch(r"-?[0-9]+", index):
                        self.assertTrue(-count["min"] <= int(index) < count["min"], "literal index may not exist")
                    elif match["rel"]:
                        self.assertIn("topology", slot, "relative reference without topology")
                        partners = [other for other, number in participant_refs(comp) if number == rule and other != ref]
                        self.assertTrue(any(other.endswith("[i]") for other in partners), "relative reference needs [i] in the same rule")

    def test_claim_keys_name_real_slots(self):
        for entry_id in ENTRIES:
            for claims in components(entry_id).get("claims", {}).values():
                for claim in claims:
                    for slot in KEY_SLOT.findall(claim.get("key", "")):
                        self.assertIn(slot, slots(entry_id), f"{entry_id}: key {claim['key']}")


class ScenarioContracts(unittest.TestCase):
    def test_scenarios_cover_every_status_the_examples_need(self):
        statuses = {read(path)["expect"]["status"] for path in SCENARIOS}
        self.assertTrue({"feasible", "unknown", "conflict"} <= statuses)

    def test_scenarios_bind_every_slot_correctly(self):
        for path in SCENARIOS:
            scenario = read(path)
            cast, objects = {item["id"] for item in scenario["cast"]}, {item["id"] for item in scenario.get("objects", [])}
            packs = set(scenario["packs"])
            refs = [item["body"] for item in scenario["cast"]] + [ref for item in scenario["cast"] for ref in item.get("traits", [])]
            refs += [item["item"] for item in scenario.get("objects", [])] + [use["entry"] for use in scenario["use"]]
            refs += [scenario["space"]] if "space" in scenario else []
            for ref in refs:
                with self.subTest(scenario=path.name, ref=ref):
                    self.assertIn(ref, ENTRIES)
                    self.assertIn(ENTRIES[ref][1], packs)
            for use in scenario["use"]:
                for name, slot in slots(use["entry"]).items():
                    with self.subTest(scenario=path.name, entry=use["entry"], slot=name):
                        bound = use["bind"].get(name)
                        bound = [] if bound is None else bound if isinstance(bound, list) else [bound]
                        count = slot["count"] if isinstance(slot["count"], dict) else {"min": slot["count"], "max": slot["count"]}
                        self.assertTrue(count["min"] <= len(bound) <= count["max"], "bound count outside the slot's count")
                        self.assertTrue(set(bound) <= (cast if slot["kind"] == "being" else objects), "bound to the wrong kind")
                self.assertEqual(set(use["bind"]) - set(slots(use["entry"])), set(), f"{path.name}: binds unknown slots")

    def test_deliberate_conflict_over_allocates_a_declared_resource(self):
        scenario = read(FIXTURES / "scenarios" / "conflict_hand.json")
        detail = scenario["expect"]["detail"]
        member = next(item for item in scenario["cast"] if item["id"] == detail["participant"])
        resources, _, _ = body_parts([member["body"], *member.get("traits", [])])
        available = sum(1 for item in resources.values() if item["type"] == detail["resource"])
        self.assertEqual(available, detail["available"])
        claimed = 0
        for claim_source in detail["claims"]:
            exclusive = [claim for claims in components(claim_source["entry"]).get("claims", {}).values() for claim in claims
                         if claim["resource"] == detail["resource"] and claim["mode"] == "exclusive"]
            self.assertEqual(sum(claim["count"] for claim in exclusive), claim_source["count"], claim_source["entry"])
            claimed += claim_source["count"]
        self.assertEqual(claimed, detail["claimed"])
        self.assertGreater(claimed, available)

    def test_unknown_and_missing_differ_only_in_declared_completeness(self):
        for name, state in (("unknown_dragon_caster", "undeclared"), ("missing_caster", "absent")):
            scenario = read(FIXTURES / "scenarios" / f"{name}.json")
            detail = scenario["expect"]["detail"]
            self.assertEqual(detail["state"], state)
            member = next(item for item in scenario["cast"] if item["id"] == detail["participant"])
            _, provides, complete = body_parts([member["body"], *member.get("traits", [])])
            complete |= set(member.get("complete_for", []))
            self.assertNotIn(detail["capability"], provides, name)
            covered = bool(implied([detail["capability"]]) & complete)
            self.assertEqual(covered, state == "absent", name)

    def test_shared_hand_scenarios_use_the_same_key(self):
        for name in ("object_shared_hand", "magic"):
            scenario = read(FIXTURES / "scenarios" / f"{name}.json")
            holder = scenario["expect"]["detail"]["participant"]
            keys = []
            for use in scenario["use"]:
                for role, claims in components(use["entry"]).get("claims", {}).items():
                    if use["bind"].get(role) == holder:
                        for claim in claims:
                            keys.append(KEY_SLOT.sub(lambda match: use["bind"][match[1]], claim["key"]))
            self.assertEqual(len(keys), 2, name)
            self.assertEqual(len(set(keys)), 1, f"{name}: the two hand claims must share one key")


if __name__ == "__main__":
    unittest.main()
