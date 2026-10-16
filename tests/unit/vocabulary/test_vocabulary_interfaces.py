"""Core-only contracts: no bundled content can supply mechanics for these tests."""

from goated_prompter.features.vocabulary.packs import VocabularyError, read_foundation, build_registry
from goated_prompter.features.vocabulary.resolver import resolve
from goated_prompter.features.vocabulary.visual import default_settings, fit, plan
from tests.unit.vocabulary.test_vocabulary_packs import ManagerTest, tiny_pack, archive
from tests.unit.vocabulary.test_vocabulary_visual import brief


def entry(name, components, category="action", **extra):
    return {"id": "lab:" + name, "name": name, "category": category, "components": components, **extra}


SLOTS = {"actor": {"count": 1, "kind": "being"}}
CAST = [{"id": "a", "body": "lab:body"}]
CLAIM = {"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "use"}
EXAMPLES = {
    "Actor": {"slots": SLOTS},
    "Anatomy": {"resources": {"gripper": {"type": "core:limb.hand"}}, "complete_for": ["core:limb"]},
    "Object": {"provides": ["core:item.handheld"]},
    "Space": {"provides": ["core:surface.ground"]},
    "PostureBase": {"participants": {"self": {"orientation": "upright"}}},
    "PositionBase": {"participants": {"actor": {"orientation": "upright"}}},
    "ActionBase": {"participants": {"actor": {"all_of": ["core:limb.hand"]}}},
    "RelationshipBase": {"participants": {"actor": {"anchors": [{"relation": "above", "of": "other"}]}}},
    "Framing": {"shows": {"whole": True}},
    "CameraAngle": {"people": {"min": 1}},
    "Composition": {"people": {"max": 2}},
    "LightingBase": {"media": ["realistic"]},
    "CapabilityCompatibility": {"participants": {"actor": {"none_of": ["core:locomotion.flight"]}}},
    "BodyResourceUsage": {"actor": [CLAIM]},
    "VisibilityRequirements": {"participants": {"actor": {"whole": True}}},
    "SupportSurfaceRequirements": {"space": {"all_of": ["core:surface.ground"]}},
    "OccupancyCapacity": {"beings": 1},
}


class CoreInterfaces(ManagerTest):
    def load(self, entries, component_types=None):
        files = tiny_pack("lab", entries)
        if component_types:
            files["manifest.json"]["component_types"] = component_types
        self.manager.install_archive(archive(files), replace=(self.root / "packs/lab").exists())
        return self.manager.registry()

    def test_all_17_are_validated_and_independently_extensible(self):
        foundation = read_foundation()
        self.assertEqual(set(foundation.manifest["component_types"]), set(EXAMPLES))
        for name, value in EXAMPLES.items():
            with self.subTest(interface=name):
                registry = self.load([entry("example", {"lab:custom": value})], {"lab:custom": {"base": name}})
                base = foundation.manifest["component_types"][name]["base"]
                self.assertIn(base, registry.resolved("lab:example")["components"])
                with self.assertRaises(VocabularyError):
                    self.load([entry("example", {"lab:custom": {"not_a_contract_field": True}})],
                              {"lab:custom": {"base": name}})

    def test_core_has_no_body_or_scene_content_and_components_are_optional(self):
        registry = build_registry([read_foundation()])
        self.assertTrue(registry.ids())
        self.assertTrue(all(set(registry.entry(i)["components"]) == {"capability"} for i in registry.ids()))
        self.assertFalse(any(i.startswith("core:body.") for i in registry.ids()))
        registry = self.load([entry("empty", {})])
        self.assertEqual(registry.resolved("lab:empty")["components"], {})
        self.assertEqual(resolve(registry, {"use": [{"entry": "lab:empty"}]}).status, "unknown")

    def test_anatomy_actor_action_and_resource_usage_share_runtime_checks(self):
        registry = self.load([
            entry("body", {"Anatomy": EXAMPLES["Anatomy"]}, "body"),
            entry("use", {"Actor": EXAMPLES["Actor"], "ActionBase": EXAMPLES["ActionBase"],
                          "BodyResourceUsage": EXAMPLES["BodyResourceUsage"]}),
            entry("second", {"Actor": EXAMPLES["Actor"], "BodyResourceUsage": EXAMPLES["BodyResourceUsage"]}),
        ])
        scene = {"cast": CAST, "use": [{"entry": "lab:use", "bind": {"actor": "a"}}]}
        result = resolve(registry, scene)
        self.assertNotEqual(result.status, "conflict")
        self.assertIn("gripper", result.allocation["a"])
        scene["use"].append({"entry": "lab:second", "bind": {"actor": "a"}})
        self.assertTrue(resolve(registry, scene).findings_with("over_allocated"))
        scene["use"] = [{"entry": "lab:use", "bind": {}}]
        self.assertTrue(resolve(registry, scene).findings_with("slot_count"))

    def test_posture_position_and_relationship_conflicts(self):
        registry = self.load([
            entry("body", {"Anatomy": {}}, "body"),
            entry("pose", {"PostureBase": EXAMPLES["PostureBase"]}, "posture"),
            entry("position", {"Actor": EXAMPLES["Actor"], "PositionBase": {
                "participants": {"actor": {"posture": "lab:pose"}}}}, "position"),
            entry("other", {"Actor": EXAMPLES["Actor"], "PositionBase": {
                "participants": {"actor": {"orientation": "face_down"}}}}, "position"),
            entry("above", {"Actor": {"slots": {**SLOTS, "other": {"kind": "being", "count": 1}}},
                            "RelationshipBase": EXAMPLES["RelationshipBase"]}),
            entry("below", {"Actor": {"slots": {**SLOTS, "other": {"kind": "being", "count": 1}}},
                            "RelationshipBase": {"participants": {"actor": {"anchors": [{"relation": "below", "of": "other"}]}}}}),
        ])
        scene = {"cast": CAST, "use": [{"entry": "lab:position", "bind": {"actor": "a"}}]}
        self.assertEqual(resolve(registry, scene).placements["a"]["orientation"], "upright")
        scene["use"].append({"entry": "lab:other", "bind": {"actor": "a"}})
        self.assertTrue(resolve(registry, scene).findings_with("placement_conflict"))
        scene = {"cast": [*CAST, {"id": "b", "body": None}], "use": [
            {"entry": "lab:" + name, "bind": {"actor": "a", "other": "b"}} for name in ("above", "below")]}
        self.assertTrue(resolve(registry, scene).findings_with("placement_conflict"))

    def test_object_space_support_and_standalone_capacity(self):
        registry = self.load([
            entry("body", {"Anatomy": {}}, "body"),
            entry("surface", {"Space": EXAMPLES["Space"], "OccupancyCapacity": {"beings": 1}}, "space"),
            entry("seat", {"Object": {"provides": ["core:surface.seat"]}, "OccupancyCapacity": {"beings": 1}}, "item"),
            entry("supported", {"Actor": EXAMPLES["Actor"], "SupportSurfaceRequirements": EXAMPLES["SupportSurfaceRequirements"]}),
            entry("seated", {"Actor": {"slots": {"actors": {"kind": "being", "count": {"min": 1, "max": 2}},
                                                       "seat": {"kind": "object", "count": 1}}},
                              "PositionBase": {"participants": {"actors[*]": {"anchors": [{"relation": "on", "of": "seat"}]}}}}),
        ])
        scene = {"cast": CAST, "space": "lab:surface", "use": [{"entry": "lab:supported", "bind": {"actor": "a"}}]}
        self.assertFalse(resolve(registry, scene).findings_with("undeclared_capability"))
        scene.pop("space")
        self.assertTrue(resolve(registry, scene).findings_with("undeclared_capability"))
        scene = {"cast": [*CAST, {"id": "b", "body": None}], "space": "lab:surface"}
        self.assertTrue(resolve(registry, scene).findings_with("over_capacity"))
        scene.pop("space")
        self.assertFalse(resolve(registry, scene).findings_with("over_capacity"))
        scene.update(objects=[{"id": "seat", "item": "lab:seat"}], use=[
            {"entry": "lab:seated", "bind": {"actors": ["a", "b"], "seat": "seat"}}])
        self.assertTrue(resolve(registry, scene).findings_with("over_capacity"))

    def test_visual_interfaces_keep_dimension_and_visibility_behavior(self):
        registry = self.load([
            entry("body", {"Anatomy": {}}, "body"),
            entry("visible", {"Actor": EXAMPLES["Actor"], "VisibilityRequirements": EXAMPLES["VisibilityRequirements"]}),
            *[entry(name.lower(), {name: value}, "visual_" + dimension)
              for name, dimension, value in (("Framing", "framing", {"shows": {"whole": False, "complete": True}}),
                                              ("CameraAngle", "camera", EXAMPLES["CameraAngle"]),
                                              ("Composition", "composition", EXAMPLES["Composition"]),
                                              ("LightingBase", "lighting", EXAMPLES["LightingBase"]))],
        ])
        need = resolve(registry, {"cast": CAST, "use": [{"entry": "lab:visible", "bind": {"actor": "a"}}]}).visibility
        self.assertTrue(need["participants"]["a"]["whole"])
        framing = registry.resolved("lab:framing")["components"]["visual"]
        self.assertEqual(framing["dimension"], "framing")
        self.assertEqual(fit(registry, framing["shows"], need)[0], "conflict")

    def test_extensions_require_dependencies_and_reject_cycles_and_dimension_changes(self):
        for definitions in ({"lab:custom": {"base": "missing"}},
                            {"lab:a": {"base": "lab:b"}, "lab:b": {"base": "lab:a"}},
                            {"lab:a": {"base": "Framing", "dimension": "lighting"}},
                            {"another:custom": {"base": "Actor"}}):
            with self.subTest(definitions=definitions), self.assertRaises(VocabularyError):
                self.load([], definitions)

    def test_posture_keeps_support_and_visibility_when_referenced(self):
        registry = self.load([
            entry("body", {"Anatomy": {}}, "body"),
            entry("pose", {"PostureBase": EXAMPLES["PostureBase"],
                           "SupportSurfaceRequirements": EXAMPLES["SupportSurfaceRequirements"],
                           "VisibilityRequirements": {"participants": {"self": {"whole": True}}, "space": True}}, "posture"),
            entry("position", {"Actor": EXAMPLES["Actor"], "PositionBase": {
                "participants": {"actor": {"posture": "lab:pose"}}}}, "position"),
            entry("surface", {"Space": {"provides": [], "complete_for": ["core:surface"]}}, "space"),
        ])
        scene = {"cast": CAST, "space": "lab:surface", "use": [{"entry": "lab:position", "bind": {"actor": "a"}}]}
        result = resolve(registry, scene)
        self.assertTrue(result.findings_with("missing_capability"))
        self.assertTrue(result.visibility["participants"]["a"]["whole"])
        self.assertTrue(result.visibility["space"])
        scene.pop("space")
        self.assertTrue(resolve(registry, scene).findings_with("undeclared_capability"))

    def test_dependent_pack_derives_an_interface_and_inherits_its_template(self):
        self.load([entry("template", {"lab:grip": EXAMPLES["BodyResourceUsage"]}, abstract=True)],
                  {"lab:grip": {"base": "BodyResourceUsage"}})
        files = tiny_pack("other", [
            {"id": "other:body", "category": "body", "name": "Body", "components": {"Anatomy": EXAMPLES["Anatomy"]}},
            {"id": "other:use", "category": "action", "name": "Use", "extends": ["lab:template"],
             "components": {"Actor": EXAMPLES["Actor"], "other:grip": EXAMPLES["BodyResourceUsage"]}},
        ], requires={"core": ">=1.0.0", "lab": ">=1.0.0"})
        files["manifest.json"]["component_types"] = {"other:grip": {"base": "lab:grip"}}
        self.manager.install_archive(archive(files))
        registry = self.manager.registry()
        scene = {"cast": [{"id": "a", "body": "other:body"}], "use": [{"entry": "other:use", "bind": {"actor": "a"}}]}
        self.assertTrue(resolve(registry, scene).findings_with("over_allocated"))
        self.manager.remove("other")
        files["manifest.json"]["requires"].pop("lab")
        with self.assertRaises(VocabularyError):
            self.manager.install_archive(archive(files))

    def test_capacity_sources_cannot_silently_override_each_other(self):
        with self.assertRaisesRegex(VocabularyError, "conflicting occupancy"):
            self.load([entry("seat", {"Object": {"provides": [], "capacity": {"beings": 2}},
                                      "OccupancyCapacity": {"beings": 1}}, "item")])

    def test_visual_interface_limits_and_conflicts_reach_selection(self):
        registry = self.load([
            entry("frame", {"Framing": {"shows": {"whole": True}}}, "visual_framing"),
            entry("camera", {"CameraAngle": {"people": {"min": 2}}}, "visual_camera"),
            entry("layout", {"Composition": {"conflicts": ["lab:camera"]}}, "visual_composition"),
            entry("light", {"LightingBase": {"media": ["realistic"]}}, "visual_lighting"),
        ])
        settings = default_settings()
        single = plan(registry, brief("A person", people=1, style="Anime"), settings)
        excluded = {item["id"] for item in single.log["excluded"]}
        self.assertIn("lab:camera", excluded)
        self.assertIn("lab:light", excluded)
        pair = plan(registry, brief("Two people", people=2, style="Realistic"), settings)
        self.assertIn("lab:camera", [item.id for item in pair.pools["camera_angle"]])
        for number in range(1, 12):
            chosen = {item.id for item in pair.directions(number)[0].values()}
            self.assertFalse({"lab:camera", "lab:layout"} <= chosen)

    def test_custom_capabilities_and_combined_interface_conditions_are_enforced(self):
        registry = self.load([
            entry("gripper", {"capability": {"implies": ["core:limb.hand"]}}, "capability"),
            entry("body", {"Anatomy": {"resources": {"tool": {"type": "lab:gripper"}},
                                         "complete_for": ["core:locomotion"]}}, "body"),
            entry("flying", {"Anatomy": {"provides": ["core:locomotion.flight"]}}, "trait"),
            entry("act", {"Actor": EXAMPLES["Actor"],
                          "ActionBase": {"participants": {"actor": {"all_of": ["core:limb"]}}},
                          "CapabilityCompatibility": EXAMPLES["CapabilityCompatibility"]}),
        ])
        scene = {"cast": CAST, "use": [{"entry": "lab:act", "bind": {"actor": "a"}}]}
        result = resolve(registry, scene)
        self.assertFalse(result.findings_with("missing_capability"))
        self.assertFalse(result.findings_with("undeclared_capability"))
        scene["cast"] = [{"id": "a", "body": "lab:body", "traits": ["lab:flying"]}]
        self.assertTrue(resolve(registry, scene).findings_with("forbidden_capability"))
        scene["cast"] = [{"id": "a", "body": None}]
        result = resolve(registry, scene)
        self.assertEqual(result.status, "unknown")
        self.assertTrue(result.findings_with("undeclared_capability"))
