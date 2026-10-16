"""Deterministic scene composition with synthetic installed packs, never inference."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from goated_prompter.features.dataset.v2.vocabulary_packs import vocabulary_reference
from goated_prompter.features.dataset.v2 import intent
from tests.unit.dataset.test_dataset_vocabulary_integration import PEOPLE, brief, packs_folder


class Composition(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.manager = packs_folder(Path(folder.name))

    def reference(self, text, **changes):
        value = brief(text, **{"characters": PEOPLE, **changes})
        value["input"]["seed"] = 7
        return vocabulary_reference({}, value, manager=self.manager)

    def test_same_words_require_only_one_alternative_across_roles(self):
        composer = self.reference("two friends hug on a sofa")["composer"]
        alternatives = {"general:action.hug", "scene:action.embrace"}
        for number in range(1, 5):
            record = composer.compose(number)
            self.assertEqual(record["kind"], "vocabulary")
            self.assertEqual(len(alternatives & {entry["id"] for entry in record["entries"]}), 1)

    def test_different_actions_are_both_required(self):
        record = self.reference("two friends hug and hold hands")["composer"].compose(1)
        ids = {entry["id"] for entry in record["entries"]}
        self.assertIn("general:action.hold_hands", ids)
        self.assertEqual(len(ids & {"general:action.hug", "scene:action.embrace"}), 1)

    def test_composition_is_repeatable_and_independent_of_image_order(self):
        first = self.reference("two friends hug on a sofa")["composer"]
        expected = copy.deepcopy(first.compose(2))
        first.compose(1)
        second = self.reference("two friends hug on a sofa")["composer"]
        second.compose(1)
        self.assertEqual(second.compose(2), expected)
        self.assertEqual(first.compose(2), expected)

    def test_no_matching_place_or_cast_is_explicitly_freeform(self):
        composer = self.reference("a perfume bottle on marble", characters=[])["composer"]
        record = composer.compose(1)
        self.assertEqual((record["kind"], record["status"]), ("freeform", "unchecked"))

    def test_named_action_that_cannot_fit_the_cast_fails_instead_of_disappearing(self):
        record = self.reference("a person does an aerial carry", characters=PEOPLE[:1])["composer"].compose(1)
        self.assertEqual(record["kind"], "failed")
        self.assertIn("Aerial carry", record["reason"])

    def test_guided_inputs_require_their_own_named_actions(self):
        value = brief("two friends", characters=PEOPLE)
        value["input"].update(source_mode="guided", guided_inputs=["hug", "hold hands"])
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        self.assertEqual(len({"general:action.hug", "scene:action.embrace"} &
                             {e["id"] for e in composer.compose(1)["entries"]}), 1)
        self.assertIn("general:action.hold_hands", {e["id"] for e in composer.compose(2)["entries"]})

    def test_guided_longer_action_name_does_not_alternate_with_its_shorter_substring(self):
        value = brief("two friends", characters=PEOPLE, amount=4)
        value["input"].update(source_mode="guided", guided_inputs=["hold hands"])
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        for number in range(1, 5):
            record = composer.compose(number)
            self.assertEqual(record["kind"], "vocabulary", record)
            ids = {entry["id"] for entry in record["entries"]}
            self.assertIn("general:action.hold_hands", ids)
            self.assertNotIn("general:action.hold", ids)

    def test_guided_actions_keep_shared_fixed_requirements(self):
        value = brief("two friends", characters=PEOPLE)
        value["fixed"] = "hold hands"
        value["input"].update(source_mode="guided", guided_inputs=["sword duel"])
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        record = composer.compose(1)
        self.assertEqual(record["kind"], "vocabulary", record)
        self.assertIn("general:action.hold_hands", {entry["id"] for entry in record["entries"]})

    def test_unsupported_guided_input_is_not_replaced_by_an_unrelated_position(self):
        value = brief("two friends hug", characters=PEOPLE)
        value["input"].update(source_mode="guided", guided_inputs=["hug", "sharing a meal"])
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        self.assertEqual(composer.compose(1)["kind"], "vocabulary")
        self.assertEqual((composer.compose(2)["kind"], composer.compose(2)["status"]), ("freeform", "unchecked"))

    def test_required_incompatible_actions_fail_with_a_resource_reason(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for ident, name in (("lift", "Overhead lift"), ("sign", "Carrying a sign")):
            data["entries"].append({"id": f"scene:action.{ident}", "name": name, "category": "action", "components": {
                "participants": {"slots": {"actor": {"kind": "being", "count": 1}}},
                "claims": {"actor": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive", "purpose": "hold"}]}}})
        path.write_text(json.dumps(data), encoding="utf-8")
        record = self.reference("a woman doing an overhead lift while carrying a sign", characters=PEOPLE[:1])["composer"].compose(1)
        self.assertEqual(record["kind"], "failed")
        self.assertIn("hand", record["reason"].lower())

    def test_director_avoid_never_overrides_the_requests_named_action(self):
        value = brief("two friends hug", characters=PEOPLE)
        ref = vocabulary_reference({}, value, manager=self.manager, preferences={
            "avoid": {"entries": ["general:action.hug", "scene:action.embrace"]}, "priorities": ["space"]})
        self.assertEqual(ref["log"]["composer"]["order"], ["space", "arrangement", "interaction"])
        self.assertEqual(len({"general:action.hug", "scene:action.embrace"} &
                             {e["id"] for e in ref["composer"].compose(1)["entries"]}), 1)

    def test_understood_performer_and_target_control_role_assignment(self):
        value = brief("the woman embraces the man", characters=PEOPLE, amount=4)
        value.update(version=10)
        value["intent"] = intent.normalize({"elements": [
            {"id": "a", "kind": "subject", "text": "woman", "character": "woman", "source": "request", "status": "fixed"},
            {"id": "b", "kind": "subject", "text": "man", "character": "man", "source": "request", "status": "fixed"},
            {"id": "act", "kind": "action", "text": "embrace", "by": ["a"], "to": ["b"],
             "source": "request", "status": "fixed"}], "relations": []}, value["characters"], [], [value["summary"]])
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        matches = [entry for n in range(1, 5) for entry in composer.compose(n)["entries"]
                   if entry["id"] == "scene:action.embrace"]
        self.assertTrue(matches)
        self.assertTrue(all(entry["roles"] == {"holder": ["woman"], "held": ["man"]} for entry in matches))

    def test_cooperative_performers_accept_understood_recipient_without_replacing_people(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"].append({"id": "scene:action.high_five", "name": "High five", "category": "action", "components": {
            "participants": {"slots": {"a": {"kind": "being", "count": 1, "role": "performer"},
                                         "b": {"kind": "being", "count": 1, "role": "performer"}}},
            "spatial": {"access": [{"from": "a", "using": "core:limb.hand", "to": "b",
                                     "regions": ["core:limb.hand"], "kind": "touch"}]}}})
        path.write_text(json.dumps(data), encoding="utf-8")
        characters = [*PEOPLE, {**PEOPLE[0], "label": "friend"}]
        for by, to in ((["a"], ["b"]), (["a", "b"], []), ([], ["a", "b"])):
            with self.subTest(by=by, to=to):
                value = brief("the woman and man high five", characters=characters, amount=4)
                value["version"] = 10
                value["intent"] = intent.normalize({"elements": [
                    {"id": "a", "kind": "subject", "text": "woman", "character": "woman", "source": "request", "status": "fixed"},
                    {"id": "b", "kind": "subject", "text": "man", "character": "man", "source": "request", "status": "fixed"},
                    {"id": "act", "kind": "action", "text": "high five", "by": by, "to": to,
                     "source": "request", "status": "fixed"}], "relations": []}, characters, [], [value["summary"]])
                composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
                for number in range(1, 5):
                    record = composer.compose(number)
                    self.assertEqual(record["kind"], "vocabulary", record)
                    activity = next(entry for entry in record["entries"] if entry["id"] == "scene:action.high_five")
                    self.assertEqual({person for people in activity["roles"].values() for person in people}, {"woman", "man"})

    def test_optional_postures_cannot_spend_a_required_actions_resources(self):
        value = brief("a woman holding a lantern", characters=PEOPLE[:1], amount=10)
        value["randomized"] = "postures"
        composer = vocabulary_reference({}, value, manager=self.manager)["composer"]
        for number in range(1, 11):
            record = composer.compose(number)
            self.assertEqual(record["kind"], "vocabulary", record)
            self.assertIn("general:action.hold", {entry["id"] for entry in record["entries"]})
            self.assertNotEqual(record["placements"]["woman"].get("posture"), "general:posture.all_fours")

    def test_incompatible_intent_roles_cannot_be_silently_reversed(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"].append({"id": "scene:action.flying_touch", "name": "Sky greeting", "category": "action", "components": {
            "participants": {"slots": {"actor": {"kind": "being", "count": 1}, "target": {"kind": "being", "count": 1}}},
            "spatial": {"access": [{"from": "actor", "using": "core:locomotion.flight", "to": "target",
                                     "regions": ["core:anatomy.back"], "kind": "touch"}]}}})
        path.write_text(json.dumps(data), encoding="utf-8")
        characters = [PEOPLE[0], {"label": "dragon", "gender": "custom", "custom": "dragon", "pronoun": "it"}]
        value = brief("a woman does a sky greeting to a dragon", characters=characters)
        value["version"] = 10
        value["intent"] = intent.normalize({"elements": [
            {"id": "a", "kind": "subject", "text": "woman", "character": "woman", "source": "request", "status": "fixed"},
            {"id": "b", "kind": "subject", "text": "dragon", "character": "dragon", "source": "request", "status": "fixed"},
            {"id": "act", "kind": "action", "text": "sky greeting", "by": ["a"], "to": ["b"],
             "source": "request", "status": "fixed"}], "relations": []}, characters, [], [value["summary"]])
        record = vocabulary_reference({}, value, manager=self.manager)["composer"].compose(1)
        self.assertEqual(record["kind"], "failed", record)

    def test_each_object_slot_can_choose_a_different_compatible_item(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"].extend([
            {"id": "scene:item.stool", "name": "Stool", "category": "item",
             "components": {"object": {"provides": ["core:surface.seat"], "complete_for": ["core:item"]}}},
            {"id": "scene:action.balance", "name": "Balancing equipment", "category": "action", "components": {
                "participants": {"slots": {"actor": {"kind": "being", "count": 1},
                                            "tool": {"kind": "object", "count": 1},
                                            "support": {"kind": "object", "count": 1}}},
                "requirements": {"participants": {"tool": {"all_of": ["core:item.handheld"]},
                                                    "support": {"all_of": ["core:surface.seat"]}}}}},
        ])
        path.write_text(json.dumps(data), encoding="utf-8")
        record = self.reference("a woman balancing equipment with a book and a stool", characters=PEOPLE[:1])["composer"].compose(1)
        self.assertEqual(record["kind"], "vocabulary", record)
        self.assertEqual({item["id"] for item in record["items"]}, {"general:item.book", "scene:item.stool"})
        self.assertEqual(record["open_objects"], [])

    def test_required_bindings_backtrack_instead_of_rejecting_a_compatible_cast(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for ident, name in (("lift", "Overhead lift"), ("sign", "Carrying a sign")):
            data["entries"].append({"id": f"scene:action.{ident}", "name": name, "category": "action", "components": {
                "participants": {"slots": {"actor": {"kind": "being", "count": 1}}},
                "claims": {"actor": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive", "purpose": "hold"}]}}})
        path.write_text(json.dumps(data), encoding="utf-8")
        value = brief("overhead lift while carrying a sign", characters=PEOPLE)
        # The first action is unconstrained; the second must belong to the woman.
        value["version"] = 10
        value["intent"] = intent.normalize({"elements": [
            {"id": "a", "kind": "subject", "text": "woman", "character": "woman", "source": "request", "status": "fixed"},
            {"id": "act", "kind": "action", "text": "carrying a sign", "by": ["a"],
             "source": "request", "status": "fixed"}], "relations": []}, value["characters"], [], [value["summary"]])
        for seed in range(6):
            value["input"]["seed"] = seed
            record = vocabulary_reference({}, value, manager=self.manager)["composer"].compose(1)
            self.assertEqual(record["kind"], "vocabulary", record)
            acts = {e["id"]: e for e in record["entries"]}
            self.assertEqual(acts["scene:action.sign"]["roles"]["actor"], ["woman"])
            self.assertEqual(acts["scene:action.lift"]["roles"]["actor"], ["man"])

    def test_director_required_mechanics_are_not_optional_inspiration(self):
        value = brief("two friends", characters=PEOPLE, amount=4)
        composer = vocabulary_reference({}, value, manager=self.manager, preferences={
            "require": ["general:action.hold_hands"]})["composer"]
        for number in range(1, 5):
            record = composer.compose(number)
            self.assertIn("general:action.hold_hands", {e["id"] for e in record["entries"]})

    def test_unmatched_confirmed_action_cannot_be_validated_by_related_content(self):
        value = brief("two friends sharing a meal", characters=PEOPLE)
        value["version"] = 10
        value["intent"] = {"available": True, "elements": [
            {"id": "act", "kind": "action", "text": "sharing a meal", "terms": ["hug"],
             "source": "request", "status": "fixed", "input": 0}], "relations": [], "unresolved": [], "truncated": False}
        record = vocabulary_reference({}, value, manager=self.manager)["composer"].compose(1)
        self.assertEqual((record["kind"], record["status"]), ("freeform", "unchecked"), record)
        self.assertIn("sharing a meal", record["reason"])

    def test_a_requested_item_is_shared_across_compatible_object_actions(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"].append({"id": "scene:action.operate", "name": "Operate equipment", "category": "action",
                                "extends": ["general:action.wield"], "components": {}})
        path.write_text(json.dumps(data), encoding="utf-8")
        record = self.reference("a woman holds a book and operates equipment", characters=PEOPLE[:1])["composer"].compose(1)
        self.assertEqual(record["kind"], "vocabulary", record)
        self.assertEqual(len(record["items"]), 1, "holding and using the same requested object do not create copies")
        self.assertEqual(record["items"][0]["id"], "general:item.book")

    def test_surface_requirements_choose_declared_support_instead_of_unknown_space(self):
        path = self.manager.install_dir / "scene/entries.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["entries"].extend([
            {"id": "scene:space.platform", "name": "Declared platform", "category": "space", "components": {
                "environment": {"provides": ["core:surface.wide"], "complete_for": ["core:surface"]}}},
            {"id": "scene:action.rest", "name": "Platform resting", "category": "action", "components": {
                "participants": {"slots": {"actor": {"kind": "being", "count": 1}}},
                "requirements": {"space": {"all_of": ["core:surface.wide"]}},
                "spatial": {"participants": {"actor": {"orientation": "face_up"}}}}},
        ])
        path.write_text(json.dumps(data), encoding="utf-8")
        value = brief("a woman platform resting", characters=PEOPLE[:1])
        for seed in range(4):
            value["input"]["seed"] = seed
            record = vocabulary_reference({}, value, manager=self.manager)["composer"].compose(1)
            self.assertEqual(record["status"], "feasible", record)
            self.assertTrue(record["verified"])

    def test_director_missing_required_content_is_explicitly_unverified(self):
        value = brief("two friends", characters=PEOPLE)
        record = vocabulary_reference({}, value, manager=self.manager, preferences={
            "require": ["absent:action.capture"]})["composer"].compose(1)
        self.assertEqual((record["kind"], record["status"]), ("freeform", "unchecked"))
        self.assertIn("absent:action.capture", record["reason"])


if __name__ == "__main__":
    unittest.main()
