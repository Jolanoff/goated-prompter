"""Phase 3: the capability and spatial resolver. Real core, fixture packs, and a small lab pack per test run."""

import copy
import itertools
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, build_registry, read_pack
from goated_prompter.features.vocabulary.resolver import (
    NO_EVIDENCE, RANK, CompositionError, candidate_bindings, implied, resolve)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCENARIOS = sorted((FIXTURES / "scenarios").glob("*.json"))
H = "core:body.humanoid"


def slot(count=1, kind="being", topology=None):
    spec = {"count": count, "kind": kind}
    if topology:
        spec["topology"] = topology
    return spec


def placement(posture, **extra):
    return {"posture": posture, **extra}


LAB = [
    {"id": "lab:position.line", "category": "position", "name": "Line", "components": {
        "participants": {"slots": {"member": slot({"min": 2, "max": 8}, topology="chain")}},
        "spatial": {"participants": {"member[*]": placement("core:posture.standing")},
                    "access": [{"from": "member[i]", "using": "core:limb.hand", "to": "member[i+1]",
                                "regions": ["core:anatomy.shoulders"], "kind": "touch"}]}}},
    {"id": "lab:position.ranks", "category": "position", "name": "Ranks", "components": {
        "participants": {"slots": {"member": slot({"min": 3, "max": 6})}},
        "requirements": {"participants": {"member[0:2]": {"all_of": ["core:limb.hand"]},
                                          "member[-1]": {"all_of": ["core:locomotion.flight"]}}}}},
    {"id": "lab:action.grip_one", "category": "action", "name": "Grip with one hand", "components": {
        "participants": {"slots": {"actor": slot(), "thing": slot(kind="object")}},
        "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "hold", "key": "grip:{thing}"}]}}},
    {"id": "lab:action.grip_two", "category": "action", "name": "Grip with two hands", "components": {
        "participants": {"slots": {"actor": slot(), "thing": slot(kind="object")}},
        "claims": {"actor": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive", "purpose": "hold", "key": "grip:{thing}"}]}}},
    {"id": "lab:action.rest_hand", "category": "action", "name": "Rest a hand", "components": {
        "participants": {"slots": {"actor": slot()}},
        "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "shared", "purpose": "contact"}]}}},
    {"id": "lab:position.seated_front", "category": "position", "name": "Seated, other in front", "components": {
        "participants": {"slots": {"seated": slot(), "other": slot()}},
        "spatial": {"participants": {"seated": placement("core:posture.sitting", facing={"toward": "other"}),
                                     "other": placement("core:posture.kneeling", facing={"toward": "seated"},
                                                        anchors=[{"relation": "in_front", "of": "seated", "distance": "arm"}])},
                    "access": [{"from": "other", "using": "core:limb.hand", "to": "seated",
                                "regions": ["core:anatomy.ass", "core:anatomy.chest"], "kind": "touch"}]}}},
    {"id": "lab:action.touch_ass", "category": "action", "name": "Touch the ass", "components": {
        "participants": {"slots": {"actor": slot(), "target": slot()}},
        "requirements": {"access": [{"from": "actor", "using": "core:limb.hand", "to": "target",
                                     "regions": ["core:anatomy.ass"], "kind": "touch"}]}}},
    {"id": "lab:mixin.small_back", "category": "position", "name": "Small partner behind", "components": {
        "participants": {"slots": {"front": slot(), "back": slot()}},
        "requirements": {"participants": {"back": {"any_of": ["core:size.small", "core:size.medium"]}}}}},
    {"id": "lab:mixin.winged_front", "category": "position", "name": "Winged or four-legged front", "components": {
        "participants": {"slots": {"front": slot(), "back": slot()}},
        "requirements": {"participants": {"front": {"any_of": ["core:locomotion.flight", "core:locomotion.quadruped"]}}}}},
    {"id": "lab:position.from_behind_winged", "category": "position", "name": "From behind, winged front",
     "extends": ["core:position.from_behind", "lab:mixin.small_back", "lab:mixin.winged_front"], "components": {}},
    {"id": "lab:position.across", "category": "position", "name": "Across from each other", "components": {
        "participants": {"slots": {"a": slot(), "b": slot()}},
        "spatial": {"participants": {"a": {"anchors": [{"relation": "in_front", "of": "b"}, {"relation": "behind", "of": "b"}]}}}}},
    {"id": "lab:position.reach_only", "category": "position", "name": "A hand on the shoulder", "components": {
        "participants": {"slots": {"a": slot(), "b": slot()}},
        "spatial": {"access": [{"from": "a", "using": "core:limb.hand", "to": "b",
                                "regions": ["core:anatomy.shoulders"], "kind": "touch"}]}}},
    {"id": "lab:position.bare", "category": "position", "name": "Together, nothing declared", "components": {
        "participants": {"slots": {"a": slot(), "b": slot()}}}},
    {"id": "lab:item.plain_rod", "category": "item", "name": "Plain rod", "components": {
        "object": {"provides": ["core:item.handheld"], "complete_for": ["fantasy:magic"], "size": "medium", "hands": 1}}},
    {"id": "lab:item.painted_rod", "category": "item", "name": "Painted rod", "extends": ["lab:item.plain_rod"], "components": {}},
]


def lab_registry():
    root = Path(tempfile.mkdtemp())
    try:
        folder = root / "lab"
        folder.mkdir()
        manifest = {"spec": 1, "id": "lab", "name": "Lab", "version": "1.0.0", "rating": "general",
                    "requires": {"core": ">=1.0.0", "fantasy": ">=0.1.0", "adult": ">=0.1.0"}, "files": ["entries.json"]}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "entries.json").write_text(json.dumps({"spec": 1, "entries": LAB}), encoding="utf-8")
        return build_registry([read_pack(BUNDLED_DIRS[0], bundled=True),
                               read_pack(FIXTURES / "packs" / "fantasy", bundled=False),
                               read_pack(FIXTURES / "packs" / "adult", bundled=False),
                               read_pack(folder, bundled=False)])
    finally:
        shutil.rmtree(root, ignore_errors=True)


REGISTRY = lab_registry()


def scenario(name):
    return json.loads((FIXTURES / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))


def human(ident, *traits, **extra):
    return {"id": ident, "body": H, "traits": list(traits), **extra}


def codes(result):
    return {finding.code for finding in result.findings}


class PhaseOneScenarios(unittest.TestCase):
    def test_each_scenario_resolves_to_its_expected_status(self):
        for path in SCENARIOS:
            data = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(scenario=path.stem):
                self.assertEqual(resolve(REGISTRY, data).status, data["expect"]["status"])

    def test_conflict_names_the_over_allocated_resource(self):
        result = resolve(REGISTRY, scenario("conflict_hand"))
        finding = result.findings_with("over_allocated")[0]
        self.assertEqual(finding.participants, ("receiver",))
        self.assertIn("core:posture.all_fours", finding.entries)
        self.assertIn("core:action.hold", finding.entries)
        self.assertIn("2 core:limb.hand but 3", finding.message)

    def test_unknown_and_missing_differ_as_declared(self):
        unknown = resolve(REGISTRY, scenario("unknown_dragon_caster"))
        self.assertEqual(unknown.findings_with("undeclared_capability")[0].participants, ("drake",))
        self.assertFalse(unknown.findings_with("missing_capability"))
        missing = resolve(REGISTRY, scenario("missing_caster"))
        self.assertEqual(missing.findings_with("missing_capability")[0].participants, ("clerk",))

    def test_six_people_ring_wraps_and_every_member_is_placed(self):
        result = resolve(REGISTRY, scenario("six_people"))
        pairs = {(fact["from"], fact["to"]) for fact in result.access}
        self.assertEqual(pairs, {(f"p{n}", f"p{n % 6 + 1}") for n in range(1, 7)})
        self.assertEqual({ident: item["posture"] for ident, item in result.placements.items()},
                         {f"p{n}": "core:posture.kneeling" for n in range(1, 7)})

    def test_shared_key_uses_one_hand_for_hold_and_use(self):
        for name, holder, key in (("object_shared_hand", "giver", "hold:toy"), ("magic", "mage", "hold:staff")):
            result = resolve(REGISTRY, scenario(name))
            hands = {instance: uses for instance, uses in result.allocation[holder].items() if instance.startswith("hand")}
            self.assertEqual(len(hands), 1, name)
            (uses,) = hands.values()
            self.assertEqual(uses[0]["key"], key)
            self.assertEqual(len(uses[0]["entries"]), 2)

    def test_feasible_never_claims_physical_possibility(self):
        result = resolve(REGISTRY, scenario("solo"))
        self.assertEqual(result.status, "feasible")
        self.assertIn("not proof", result.note)
        self.assertEqual(resolve(REGISTRY, scenario("conflict_hand")).note, "")


class ConflictingPositions(unittest.TestCase):
    def test_two_postures_for_one_person(self):
        result = resolve(REGISTRY, {"cast": [human("ana"), human("ben")], "space": "core:space.floor",
                                    "use": [{"entry": "core:position.standing_alone", "bind": {"person": "ana"}},
                                            {"entry": "core:position.from_behind", "bind": {"front": "ana", "back": "ben"}}]})
        self.assertEqual(result.status, "conflict")
        finding = result.findings_with("placement_conflict")[0]
        self.assertIn("core:posture.standing", finding.message)
        self.assertIn("core:posture.all_fours", finding.message)

    def test_opposite_anchors(self):
        result = resolve(REGISTRY, {"cast": [human("a"), human("b")], "use": [{"entry": "lab:position.across", "bind": {"a": "a", "b": "b"}}]})
        self.assertIn("placement_conflict", codes(result))
        self.assertEqual(result.status, "conflict")

    def test_sitting_on_the_region_blocks_reaching_it(self):
        cast = [human("seat"), human("other")]
        result = resolve(REGISTRY, {"cast": cast, "use": [
            {"entry": "lab:position.seated_front", "bind": {"seated": "seat", "other": "other"}},
            {"entry": "lab:action.touch_ass", "bind": {"actor": "other", "target": "seat"}}]})
        self.assertEqual(result.status, "conflict")
        finding = result.findings_with("region_blocked")[0]
        self.assertIn("core:posture.sitting", finding.entries)

    def test_one_person_cannot_fill_two_slots(self):
        result = resolve(REGISTRY, {"cast": [human("ana")], "use": [{"entry": "core:position.from_behind", "bind": {"front": "ana", "back": "ana"}}]})
        self.assertIn("bound_twice", codes(result))


class ResourceSharing(unittest.TestCase):
    def cast_and_toys(self, count):
        return [human("giver"), human("receiver")], [{"id": f"toy{n}", "item": "adult:item.dildo"} for n in range(1, count + 1)]

    def test_different_objects_do_not_share(self):
        cast, toys = self.cast_and_toys(2)
        result = resolve(REGISTRY, {"cast": cast, "objects": toys, "use": [
            {"entry": "core:action.hold", "bind": {"holder": "giver", "item": "toy1"}},
            {"entry": "adult:action.toy_insert", "bind": {"user": "giver", "receiver": "receiver", "toy": "toy2"}}]})
        self.assertEqual(sorted(name for name in result.allocation["giver"] if name.startswith("hand")), ["hand.left", "hand.right"])
        self.assertNotIn("over_allocated", codes(result))

    def test_three_held_objects_need_three_hands(self):
        cast, toys = self.cast_and_toys(3)
        uses = [{"entry": "core:action.hold", "bind": {"holder": "giver", "item": toy["id"]}} for toy in toys]
        result = resolve(REGISTRY, {"cast": cast, "objects": toys, "use": uses})
        self.assertEqual(result.status, "conflict")
        self.assertIn("over_allocated", codes(result))

    def test_same_key_with_different_counts_is_a_conflict(self):
        cast, toys = self.cast_and_toys(1)
        result = resolve(REGISTRY, {"cast": cast, "objects": toys, "use": [
            {"entry": "lab:action.grip_one", "bind": {"actor": "giver", "thing": "toy1"}},
            {"entry": "lab:action.grip_two", "bind": {"actor": "giver", "thing": "toy1"}}]})
        self.assertIn("key_mismatch", codes(result))

    def test_shared_claims_stack_but_never_take_an_exclusive_hand(self):
        cast, toys = self.cast_and_toys(2)
        shared = [{"entry": "lab:action.rest_hand", "bind": {"actor": "giver"}}] * 3
        result = resolve(REGISTRY, {"cast": cast, "use": shared})
        self.assertNotIn("over_allocated", codes(result))
        holds = [{"entry": "core:action.hold", "bind": {"holder": "giver", "item": toy["id"]}} for toy in toys]
        result = resolve(REGISTRY, {"cast": cast, "objects": toys, "use": [*holds, shared[0]]})
        self.assertIn("over_allocated", codes(result), "both hands hold exclusively; a shared rest has no hand left")

    def test_optional_object_slot_drops_its_claim_when_unbound(self):
        cast = [human("mage", "fantasy:trait.spellcaster"), human("foe")]
        bare = resolve(REGISTRY, {"cast": cast, "use": [{"entry": "fantasy:action.cast_on", "bind": {"caster": "mage", "target": "foe"}}]})
        self.assertFalse([name for name in bare.allocation.get("mage", {}) if name.startswith("hand")])
        with_staff = resolve(REGISTRY, {"cast": cast, "objects": [{"id": "staff", "item": "fantasy:item.staff"}],
                                        "use": [{"entry": "fantasy:action.cast_on", "bind": {"caster": "mage", "target": "foe", "focus": "staff"}}]})
        self.assertEqual(len([name for name in with_staff.allocation["mage"] if name.startswith("hand")]), 1)


class IncompleteInformation(unittest.TestCase):
    def test_a_character_without_vocabulary_is_unknown_never_conflict(self):
        result = resolve(REGISTRY, {"cast": [{"id": "x", "body": None}, human("y")], "space": "core:space.bed",
                                    "use": [{"entry": "core:position.from_behind", "bind": {"front": "x", "back": "y"}}]})
        self.assertEqual(result.status, "unknown")
        self.assertFalse(codes(result) & {"missing_capability", "forbidden_capability", "over_allocated"})

    def test_undeclared_anatomy_is_unknown_and_declared_absence_is_conflict(self):
        composition = {"cast": [human("giver"), human("receiver")], "objects": [{"id": "toy", "item": "adult:item.dildo"}],
                       "space": "core:space.bed",
                       "use": [{"entry": "core:position.from_behind", "bind": {"front": "receiver", "back": "giver"}},
                               {"entry": "adult:action.toy_insert", "bind": {"user": "giver", "receiver": "receiver", "toy": "toy"}}]}
        self.assertEqual(resolve(REGISTRY, composition).status, "feasible", "the humanoid's ass satisfies any_of")
        bare = copy.deepcopy(composition)
        bare["cast"][1] = {"id": "receiver", "body": "core:body.vertebrate"}
        self.assertEqual(resolve(REGISTRY, bare).status, "unknown")
        closed = copy.deepcopy(bare)
        closed["cast"][1]["complete_for"] = ["core:anatomy", "core:limb"]
        self.assertEqual(resolve(REGISTRY, closed).status, "conflict")

    def test_missing_space_is_unknown_not_conflict(self):
        composition = scenario("solo")
        del composition["space"]
        result = resolve(REGISTRY, composition)
        self.assertEqual(result.status, "unknown")

    def test_a_character_without_vocabulary_names_what_is_undeclared(self):
        # Decision 4: body null stays valid; relevant capabilities are reported undeclared, even with complete_for.
        for member in ({"id": "x", "body": None}, {"id": "x", "body": None, "complete_for": ["core:limb", "core:anatomy"]}):
            result = resolve(REGISTRY, {"cast": [member, human("y")],
                                        "use": [{"entry": "lab:position.reach_only", "bind": {"a": "x", "b": "y"}}]})
            with self.subTest(member=member):
                self.assertEqual(result.status, "unknown")
                (finding,) = result.findings_with("undeclared_capability")
                self.assertEqual(finding.participants, ("x",))
                self.assertIn("core:limb.hand", finding.entries)
                self.assertFalse(result.findings_with("missing_capability"))


class NoEvidence(unittest.TestCase):
    """Refinement: a composition no vocabulary rule applies to is unknown, never feasible."""

    def test_a_scene_without_any_vocabulary_is_unknown_never_rejected(self):
        result = resolve(REGISTRY, {"cast": [{"id": "dragon", "body": None}, {"id": "city", "body": None}], "use": []})
        self.assertEqual(result.status, "unknown")
        self.assertEqual(codes(result), {NO_EVIDENCE})
        self.assertEqual(result.note, "")

    def test_described_cast_without_uses_is_still_unknown(self):
        result = resolve(REGISTRY, {"cast": [human("a"), human("b")], "space": "core:space.bed", "use": []})
        self.assertEqual(result.status, "unknown")
        self.assertEqual(codes(result), {NO_EVIDENCE})

    def test_an_entry_with_no_rules_is_not_evidence(self):
        result = resolve(REGISTRY, {"cast": [human("a"), human("b")],
                                    "use": [{"entry": "lab:position.bare", "bind": {"a": "a", "b": "b"}}]})
        self.assertEqual(result.status, "unknown")
        finding = result.findings_with(NO_EVIDENCE)[0]
        self.assertEqual(finding.entries, ("lab:position.bare",))

    def test_any_applied_rule_is_evidence(self):
        for name in ("solo", "six_people", "conflict_hand", "unknown_dragon_caster"):
            with self.subTest(scenario=name):
                self.assertFalse(resolve(REGISTRY, scenario(name)).findings_with(NO_EVIDENCE))
        reach = resolve(REGISTRY, {"cast": [human("a"), human("b")],
                                   "use": [{"entry": "lab:position.reach_only", "bind": {"a": "a", "b": "b"}}]})
        self.assertEqual(reach.status, "eligible", "the reach is declared, placements are not")


class ObjectCompleteness(unittest.TestCase):
    """Decision 2: objects may declare complete_for, with the same meaning as on a body."""

    def cast_on(self, item):
        return resolve(REGISTRY, {"cast": [human("mage", "fantasy:trait.spellcaster"), human("foe")], "objects": [item],
                                  "use": [{"entry": "fantasy:action.cast_on",
                                           "bind": {"caster": "mage", "target": "foe", "focus": item["id"]}}]})

    def test_an_item_that_does_not_mention_a_capability_is_undeclared(self):
        result = self.cast_on({"id": "toy", "item": "adult:item.dildo"})
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.findings_with("undeclared_capability")[0].participants, ("toy",))

    def test_an_item_complete_for_a_capability_lacks_it(self):
        result = self.cast_on({"id": "rod", "item": "lab:item.plain_rod"})
        self.assertEqual(result.status, "conflict")
        finding = result.findings_with("missing_capability")[0]
        self.assertEqual(finding.participants, ("rod",))
        self.assertIn("fantasy:magic.focus", finding.entries)
        self.assertIn("lab:item.plain_rod", finding.entries)

    def test_completeness_can_be_declared_in_the_composition(self):
        result = self.cast_on({"id": "toy", "item": "adult:item.dildo", "complete_for": ["fantasy:magic"]})
        self.assertEqual(result.status, "conflict")
        self.assertTrue(result.findings_with("missing_capability"))

    def test_completeness_is_inherited(self):
        self.assertEqual(REGISTRY.resolved("lab:item.painted_rod")["components"]["object"]["complete_for"], ["fantasy:magic"])
        self.assertEqual(self.cast_on({"id": "rod", "item": "lab:item.painted_rod"}).status, "conflict")

    def test_completeness_never_hides_what_is_provided(self):
        staff = self.cast_on({"id": "staff", "item": "fantasy:item.staff", "complete_for": ["fantasy:magic"]})
        self.assertFalse(staff.findings_with("missing_capability"))
        self.assertFalse(staff.findings_with("undeclared_capability"))

    def test_an_object_without_an_item_stays_unknown(self):
        result = self.cast_on({"id": "thing", "item": None, "complete_for": ["fantasy:magic"]})
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.findings_with("missing_capability"))

    def test_unknown_capability_in_object_completeness_is_malformed(self):
        with self.assertRaises(CompositionError):
            self.cast_on({"id": "toy", "item": "adult:item.dildo", "complete_for": ["core:nope"]})


class DeclaredReach(unittest.TestCase):
    """Decision 1: a declared reach presupposes its capability; undeclared stays unknown."""

    def reach(self, member):
        return resolve(REGISTRY, {"cast": [member, human("b")],
                                  "use": [{"entry": "lab:position.reach_only", "bind": {"a": member["id"], "b": "b"}}]})

    def test_reach_without_the_capability_is_a_conflict(self):
        result = self.reach({"id": "drake", "body": "fantasy:creature.dragon"})
        self.assertEqual(result.status, "conflict")
        finding = result.findings_with("missing_capability")[0]
        self.assertEqual(finding.participants, ("drake",))
        self.assertIn("declared reach", finding.message)

    def test_reach_with_an_undeclared_capability_is_unknown(self):
        result = self.reach({"id": "beast", "body": "core:body.vertebrate"})
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.findings_with("undeclared_capability")[0].participants, ("beast",))

    def test_reach_with_the_capability_is_not_flagged(self):
        result = self.reach(human("a"))
        self.assertFalse(codes(result) & {"missing_capability", "undeclared_capability"})


class MultiPersonBinding(unittest.TestCase):
    def test_group_size_must_fit(self):
        for size, ok in ((2, False), (3, True), (12, True), (13, False)):
            cast = [human(f"p{n}") for n in range(size)]
            result = resolve(REGISTRY, {"cast": cast, "space": "core:space.floor",
                                        "use": [{"entry": "core:position.circle", "bind": {"member": [m["id"] for m in cast]}}]})
            with self.subTest(size=size):
                self.assertEqual("slot_count" not in codes(result), ok)

    def test_chain_does_not_wrap(self):
        cast = [human(f"p{n}") for n in range(4)]
        result = resolve(REGISTRY, {"cast": cast, "use": [{"entry": "lab:position.line", "bind": {"member": [m["id"] for m in cast]}}]})
        self.assertEqual({(fact["from"], fact["to"]) for fact in result.access}, {("p0", "p1"), ("p1", "p2"), ("p2", "p3")})

    def test_ranges_and_negative_indexes_select_members(self):
        cast = [human("a"), human("b"), human("c"), {"id": "d", "body": "fantasy:creature.dragon"}]
        result = resolve(REGISTRY, {"cast": cast, "use": [{"entry": "lab:position.ranks", "bind": {"member": ["a", "b", "c", "d"]}}]})
        self.assertNotIn("missing_capability", codes(result), "member[0:2] are humans with hands; member[-1] is the winged dragon")
        swapped = resolve(REGISTRY, {"cast": cast, "use": [{"entry": "lab:position.ranks", "bind": {"member": ["d", "b", "c", "a"]}}]})
        self.assertIn("missing_capability", codes(swapped), "the dragon has no hands; it is complete for limbs")
        self.assertIn("undeclared_capability", codes(swapped), "a human's flight is undeclared")

    def test_candidate_bindings_use_capabilities_not_gender(self):
        cast = [human("a", "core:trait.vagina", "core:trait.breasts"), human("b", "core:trait.penis")]
        results = candidate_bindings(REGISTRY, "core:position.from_behind", cast, space="core:space.bed")
        self.assertEqual(sorted((binding["front"], result.status) for binding, result in results), [("a", "feasible"), ("b", "feasible")])
        with_dragon = candidate_bindings(REGISTRY, "core:position.from_behind",
                                         [human("a"), {"id": "drake", "body": "fantasy:creature.dragon"}], space="core:space.bed")
        self.assertTrue(all(result.status == "conflict" for _, result in with_dragon), "a dragon has no hands to support or reach with")

    def test_candidate_bindings_fill_groups_and_optional_objects(self):
        options = candidate_bindings(REGISTRY, "fantasy:action.cast_on", [human("m", "fantasy:trait.spellcaster"), human("f")],
                                     objects=[{"id": "staff", "item": "fantasy:item.staff"}])
        self.assertIn(None, {binding.get("focus") for binding, _ in options})
        self.assertIn("staff", {binding.get("focus") for binding, _ in options})


class CandidateSearch(unittest.TestCase):
    """Refinements: group slots take subsets of the cast, and a truncated search says so."""

    CAST = [human(f"p{n}") for n in range(5)]

    def test_group_slots_take_every_subset_that_fits(self):
        found = candidate_bindings(REGISTRY, "core:position.circle", self.CAST, space="core:space.floor")
        groups = [tuple(binding["member"]) for binding, _ in found]
        expected = [combo for size in (5, 4, 3) for combo in itertools.combinations([m["id"] for m in self.CAST], size)]
        self.assertEqual(sorted(groups), sorted(expected), "every subset of 3 to 5, each once, in cast order")
        self.assertEqual(len(groups), len(set(groups)), "no duplicated combinations")
        self.assertTrue(all(result.status == "feasible" for _, result in found))
        self.assertEqual((found.searched, found.truncated, found.viable, found.note), (16, False, True, ""))

    def test_subsets_respect_the_group_maximum_and_minimum(self):
        line = candidate_bindings(REGISTRY, "lab:position.ranks", [human(f"p{n}") for n in range(7)])
        self.assertEqual({len(binding["member"]) for binding, _ in line}, {3, 4, 5, 6})
        too_few = candidate_bindings(REGISTRY, "core:position.circle", self.CAST[:2])
        self.assertEqual((too_few.bindings, too_few.truncated, too_few.viable), ([], False, False))

    def test_single_slots_and_groups_never_share_a_member(self):
        for binding, _ in candidate_bindings(REGISTRY, "core:position.from_behind", self.CAST[:3]):
            self.assertNotEqual(binding["front"], binding["back"])
        self.assertEqual(len(list(candidate_bindings(REGISTRY, "core:position.from_behind", self.CAST[:3]))), 6)

    def test_truncation_is_reported(self):
        found = candidate_bindings(REGISTRY, "core:position.circle", self.CAST, space="core:space.floor", limit=5)
        self.assertTrue(found.truncated)
        self.assertEqual((found.searched, found.limit, len(found.bindings)), (5, 5, 5))
        self.assertIn("not proof", found.note)
        self.assertTrue(found.to_dict()["truncated"])
        exact = candidate_bindings(REGISTRY, "core:position.circle", self.CAST, space="core:space.floor", limit=16)
        self.assertFalse(exact.truncated, "reaching the limit with nothing left is a complete search")

    def test_an_incomplete_search_never_proves_that_nothing_works(self):
        dragons = [{"id": f"d{n}", "body": "fantasy:creature.dragon"} for n in range(3)]
        partial = candidate_bindings(REGISTRY, "core:position.from_behind", dragons, space="core:space.bed", limit=2)
        self.assertTrue(all(result.status == "conflict" for _, result in partial))
        self.assertTrue(partial.truncated)
        self.assertIsNone(partial.viable, "unsearched bindings remain")
        complete = candidate_bindings(REGISTRY, "core:position.from_behind", dragons, space="core:space.bed")
        self.assertFalse(complete.truncated)
        self.assertIs(complete.viable, False)

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            candidate_bindings(REGISTRY, "core:position.circle", self.CAST, limit=0)


class Inheritance(unittest.TestCase):
    def composition(self, front):
        return {"cast": [front, human("back")], "space": "core:space.bed",
                "use": [{"entry": "lab:position.from_behind_winged", "bind": {"front": front["id"], "back": "back"}}]}

    def test_every_inherited_any_of_group_must_hold(self):
        groups = REGISTRY.resolved("lab:position.from_behind_winged")["components"]["requirements"]["participants"]
        self.assertEqual(len(groups["front"]["any_of_groups"]), 1)
        self.assertEqual(len(groups["back"]["any_of_groups"]), 1)
        self.assertEqual(REGISTRY.resolved("lab:position.from_behind_winged")["components"]["spatial"]["participants"]["front"]["posture"],
                         "core:posture.all_fours", "spatial facts are inherited from core")
        self.assertEqual(resolve(REGISTRY, self.composition(human("front"))).status, "unknown", "a human's flight is undeclared")
        self.assertEqual(resolve(REGISTRY, self.composition(human("front", complete_for=["core:locomotion"]))).status, "conflict")
        self.assertEqual(resolve(REGISTRY, self.composition(human("front", "fantasy:trait.wings"))).status, "feasible")

    def test_inherited_postures_still_claim_resources(self):
        result = resolve(REGISTRY, {**self.composition(human("front", "fantasy:trait.wings")),
                                    "objects": [{"id": "toy", "item": "adult:item.dildo"}],
                                    "use": [*self.composition(human("front", "fantasy:trait.wings"))["use"],
                                            {"entry": "core:action.hold", "bind": {"holder": "front", "item": "toy"}}]})
        self.assertIn("over_allocated", codes(result))


class Errors(unittest.TestCase):
    def test_malformed_compositions_raise(self):
        cast = [human("a"), human("b")]
        for composition in ({"cast": cast, "use": [{"entry": "core:nope", "bind": {}}]},
                            {"cast": cast, "use": [{"entry": "core:position.from_behind", "bind": {"front": "a", "middle": "b"}}]},
                            {"cast": cast, "objects": [{"id": "toy", "item": "adult:item.dildo"}],
                             "use": [{"entry": "core:position.from_behind", "bind": {"front": "toy", "back": "b"}}]},
                            {"cast": [human("a"), human("a")], "use": []},
                            {"cast": [{"id": "a", "body": "core:nope"}], "use": []}):
            with self.subTest(composition=composition):
                with self.assertRaises(CompositionError):
                    resolve(REGISTRY, composition)

    def test_missing_required_slot_is_a_conflict(self):
        # Decision 3: an unfilled required slot is a conflict; only malformed input raises.
        for entry, bind in (("core:position.from_behind", {"front": "a"}), ("core:position.circle", {})):
            with self.subTest(entry=entry):
                result = resolve(REGISTRY, {"cast": [human("a")], "use": [{"entry": entry, "bind": bind}]})
                self.assertEqual(result.status, "conflict")
                self.assertEqual(result.findings_with("slot_count")[0].entries, (entry,))


class Invariants(unittest.TestCase):
    """Properties that must hold for every scenario, not just the hand-picked examples."""

    ROOTS = sorted(entry_id for entry_id in REGISTRY.ids() if "capability" in REGISTRY.resolved(entry_id)["components"]
                   and not REGISTRY.resolved(entry_id)["components"]["capability"].get("implies"))

    def compositions(self):
        for path in SCENARIOS:
            data = json.loads(path.read_text(encoding="utf-8"))
            yield path.stem, data

    def test_declaring_absence_never_improves_the_status(self):
        for name, data in self.compositions():
            before = RANK[resolve(REGISTRY, data).status]
            for index in range(len(data["cast"])):
                closed = copy.deepcopy(data)
                closed["cast"][index]["complete_for"] = self.ROOTS
                with self.subTest(scenario=name, member=data["cast"][index]["id"]):
                    self.assertGreaterEqual(RANK[resolve(REGISTRY, closed).status], before)

    def test_removing_a_present_trait_never_improves_the_status(self):
        for name, data in self.compositions():
            before = RANK[resolve(REGISTRY, data).status]
            for index, member in enumerate(data["cast"]):
                for trait in member.get("traits", []):
                    changed = copy.deepcopy(data)
                    changed["cast"][index]["traits"].remove(trait)
                    changed["cast"][index]["complete_for"] = self.ROOTS
                    with self.subTest(scenario=name, member=member["id"], trait=trait):
                        self.assertGreaterEqual(RANK[resolve(REGISTRY, changed).status], before)

    def test_every_present_capability_made_absent_never_improves_the_status(self):
        # Swap the body for an empty, complete one that provides everything except one capability.
        for name, data in self.compositions():
            before = RANK[resolve(REGISTRY, data).status]
            for index, member in enumerate(data["cast"]):
                if not member.get("body"):
                    continue
                result = resolve(REGISTRY, data)
                self.assertIsNotNone(result)
                closed = copy.deepcopy(data)
                closed["cast"][index]["complete_for"] = self.ROOTS
                closed["cast"][index]["traits"] = []
                with self.subTest(scenario=name, member=member["id"]):
                    self.assertGreaterEqual(RANK[resolve(REGISTRY, closed).status], before)

    def test_removing_the_space_never_improves_the_status(self):
        for name, data in self.compositions():
            if "space" in data:
                without = {key: value for key, value in data.items() if key != "space"}
                with self.subTest(scenario=name):
                    self.assertGreaterEqual(RANK[resolve(REGISTRY, without).status], RANK[resolve(REGISTRY, data).status])

    def test_unbound_extras_do_not_change_anything(self):
        for name, data in self.compositions():
            extra = copy.deepcopy(data)
            extra["cast"].append(human("bystander"))
            extra.setdefault("objects", []).append({"id": "spare", "item": "fantasy:item.staff"})
            with self.subTest(scenario=name):
                self.assertEqual(resolve(REGISTRY, extra).status, resolve(REGISTRY, data).status)

    def test_cast_order_and_repetition_do_not_matter(self):
        for name, data in self.compositions():
            first = resolve(REGISTRY, data)
            self.assertEqual(resolve(REGISTRY, data).to_dict(), first.to_dict(), f"{name}: not deterministic")
            for order in itertools.islice(itertools.permutations(data["cast"]), 6):
                shuffled = {**data, "cast": list(order)}
                with self.subTest(scenario=name, order=[member["id"] for member in order]):
                    other = resolve(REGISTRY, shuffled)
                    self.assertEqual(other.status, first.status)
                    self.assertEqual(codes(other), codes(first))

    def test_undescribed_bodies_never_cause_capability_conflicts(self):
        for name, data in self.compositions():
            blank = copy.deepcopy(data)
            for member in blank["cast"]:
                member["body"], member["traits"], member["complete_for"] = None, [], []
            result = resolve(REGISTRY, blank)
            with self.subTest(scenario=name):
                self.assertFalse(codes(result) & {"missing_capability", "forbidden_capability", "over_allocated", "region_blocked"})

    def test_feasible_implies_no_open_findings(self):
        for name, data in self.compositions():
            result = resolve(REGISTRY, data)
            with self.subTest(scenario=name):
                if result.status == "feasible":
                    self.assertEqual(result.findings, [])
                else:
                    self.assertEqual(max(RANK[finding.status] for finding in result.findings), RANK[result.status])

    def test_implication_is_reflexive_and_transitive(self):
        closure = implied(REGISTRY, ["core:anatomy.penis"])
        self.assertTrue({"core:anatomy.penis", "core:anatomy.genitals", "core:anatomy"} <= closure)


if __name__ == "__main__":
    unittest.main()
