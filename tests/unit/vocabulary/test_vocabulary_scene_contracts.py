"""Additive spec-1 fields, validated using installed synthetic packs."""

import unittest

from goated_prompter.features.vocabulary.packs import VocabularyError, OFFICIAL_DIR, PackManager
from goated_prompter.features.vocabulary.preferences import Preferences, validate
from goated_prompter.features.vocabulary.resolver import resolve
from goated_prompter.features.vocabulary.retrieval import RetrievalRequest, retrieve
from tests.unit.vocabulary.test_vocabulary_packs import ManagerTest, archive, tiny_pack


class SceneContracts(ManagerTest):
    def setUp(self):
        super().setUp()
        self.manager = PackManager(self.root / "packs", self.root / "state.json", official_dir=OFFICIAL_DIR)

    def install(self, entries):
        self.manager.install_archive(archive(tiny_pack("lab", entries, requires={"core": ">=1.0.0", "general": ">=1.0.0"})))
        return self.manager.registry()

    def test_abstract_template_is_inherited_but_never_retrieved(self):
        registry = self.install([
            {"id": "lab:pose.template", "name": "Template stance", "category": "posture", "abstract": True,
             "components": {"spatial": {"participants": {"self": {"orientation": "upright"}}},
                            "visibility": {"participants": {"self": {"whole": True}}}}},
            {"id": "lab:pose.ready", "name": "Ready stance", "category": "posture", "extends": ["lab:pose.template"],
             "components": {}},
        ])
        self.assertTrue(registry.is_abstract("lab:pose.template"))
        self.assertFalse(registry.is_abstract("lab:pose.ready"))
        self.assertTrue(registry.resolved("lab:pose.ready")["components"]["visibility"]["participants"]["self"]["whole"])
        found = retrieve(registry, RetrievalRequest(request="Template stance and Ready stance",
                                                    characters=({"label": "person", "custom": "human"},)))
        self.assertNotIn("lab:pose.template", [entry.id for entry in found.entries])
        self.assertIn("lab:pose.ready", [entry.id for entry in found.entries])

    def test_replaced_ids_redirect_old_pack_references_and_preferences(self):
        registry = self.install([
            {"id": "lab:light.copy", "name": "Copy", "category": "visual_lighting", "extends": ["visual:lighting.soft"],
             "components": {}},
        ])
        # The old Visual id is now owned by Core; installed spec-1 packs still load.
        self.assertEqual(registry.canonical("visual:lighting.soft"), "general:lighting.soft")
        self.assertEqual(registry.resolved("lab:light.copy")["components"]["visual"]["dimension"], "lighting")
        prefs = Preferences({"visual": {"prefer": ["visual:lighting.soft"]}}, registry)
        self.assertEqual(prefs.visual["prefer"], ["general:lighting.soft"])

    def test_replacement_cannot_take_over_a_live_id(self):
        with self.assertRaises(VocabularyError):
            self.install([{"id": "lab:pose.copy", "name": "Copy", "category": "posture",
                           "replaces": ["general:posture.standing"], "components": {}}])

    def test_space_capacity_boundary_and_unspecified_capacity(self):
        registry = self.install([
            {"id": "lab:space.booth", "name": "Booth", "category": "space",
             "components": {"environment": {"provides": [], "capacity": {"beings": 1}}}},
        ])
        cast = [{"id": "a", "body": "general:body.human"}, {"id": "b", "body": "general:body.human"}]
        full = resolve(registry, {"cast": cast, "space": "lab:space.booth", "use": []})
        self.assertTrue(any(f.code == "over_capacity" for f in full.findings))
        for composition in ({"cast": cast[:1], "space": "lab:space.booth", "use": []},
                            {"cast": cast, "space": "general:space.sofa", "use": []}):
            self.assertFalse(any(f.code == "over_capacity" for f in resolve(registry, composition).findings))

    def test_visibility_collects_bound_whole_bodies_contact_and_space(self):
        registry = self.install([
            {"id": "lab:action.touch", "name": "Touch", "category": "action", "components": {
                "participants": {"slots": {"actor": {"kind": "being", "count": 1},
                                            "target": {"kind": "being", "count": 1}}},
                "visibility": {"participants": {"target": {"whole": True}}, "contact": True, "space": True},
                "spatial": {"access": [{"from": "actor", "using": "core:limb.hand", "to": "target",
                                         "regions": ["core:anatomy.back"], "kind": "touch"}]}}},
        ])
        result = resolve(registry, {"cast": [{"id": "a", "body": "general:body.human"},
                                             {"id": "b", "body": "general:body.human"}],
                                    "use": [{"entry": "lab:action.touch", "bind": {"actor": "a", "target": "b"}}]})
        self.assertEqual(result.visibility, {"participants": {
            "a": {"whole": False, "regions": ["core:limb.hand"]},
            "b": {"whole": True, "regions": ["core:anatomy.back"]}}, "space": True})

    def test_item_capacity_counts_only_beings_on_or_astride_that_item(self):
        registry = self.install([
            {"id": "lab:item.seat", "name": "Seat", "category": "item", "components": {
                "object": {"provides": [], "capacity": {"beings": 1}}}},
            {"id": "lab:position.seated", "name": "On a seat", "category": "position", "components": {
                "participants": {"slots": {"people": {"kind": "being", "count": {"min": 1, "max": 4}},
                                            "seat": {"kind": "object", "count": 1}}},
                "spatial": {"participants": {"people[*]": {"anchors": [{"relation": "on", "of": "seat"}]}}}}},
        ])
        composition = {"cast": [{"id": "a", "body": "general:body.human"}, {"id": "b", "body": "general:body.human"}],
                       "objects": [{"id": "seat", "item": "lab:item.seat"}],
                       "use": [{"entry": "lab:position.seated", "bind": {"people": ["a", "b"], "seat": "seat"}}]}
        self.assertTrue(any(f.code == "over_capacity" for f in resolve(registry, composition).findings))
        composition["use"][0]["bind"]["people"] = ["a"]
        self.assertFalse(any(f.code == "over_capacity" for f in resolve(registry, composition).findings))

    def test_pack_object_templates_work_through_inheritance_and_joint_resolution(self):
        registry = self.install([
            {"id": "lab:action.tool", "name": "Use tool", "category": "action", "extends": ["general:action.wield"], "components": {}},
            {"id": "lab:action.seated", "name": "Use seat", "category": "action", "extends": ["general:action.sit_on"], "components": {}},
            {"id": "lab:item.seat", "name": "Seat", "category": "item", "components": {
                "object": {"provides": ["core:surface.seat"], "capacity": {"beings": 1}}}},
        ])
        composition = {"cast": [{"id": "a", "body": "general:body.human"}],
                       "objects": [{"id": "tool", "item": "general:item.book"}, {"id": "seat", "item": "lab:item.seat"}],
                       "use": [{"entry": "lab:action.tool", "bind": {"actor": "a", "item": "tool"}},
                               {"entry": "lab:action.seated", "bind": {"actor": "a", "item": "seat"}}]}
        result = resolve(registry, composition)
        self.assertNotEqual(result.status, "conflict", result.to_dict())
        self.assertEqual(result.placements["a"]["posture"], "general:posture.sitting")
        self.assertTrue(result.allocation["a"])
        composition["use"].pop()
        composition["declared"] = {"a": {"posture": "general:posture.all_fours"}}
        self.assertEqual(resolve(registry, composition).status, "conflict")


class DirectorPreferences(unittest.TestCase):
    def test_rejects_invalid_unknown_and_contradictory_fields(self):
        for value in ([], {"unknown": []}, {"prefer": {"entries": ["bad"]}},
                      {"priorities": ["item"]}, {"themes": [" "]},
                      {"prefer": {"tags": ["quiet"]}, "avoid": {"tags": ["quiet"]}},
                      {"visual": {"prefer": ["core:framing.wide"], "avoid": ["core:framing.wide"]}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_normalizes_and_preserves_priority_order(self):
        prefs = Preferences({"prefer": {"entries": ["core:action.hug", "core:action.hug"]},
                             "priorities": ["space"], "themes": ["  quiet   afternoons "]})
        self.assertEqual(prefs.order(("arrangement", "interaction", "space")), ("space", "arrangement", "interaction"))
        self.assertEqual(prefs.block["prefer"]["entries"], ["core:action.hug"])
        self.assertEqual(prefs.themes, ("quiet afternoons",))
        self.assertGreater(prefs.weight("core:action.hug"), prefs.weight("core:action.kiss"))
