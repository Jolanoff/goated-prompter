"""Visual Direction (vocabulary/visual.py, SPEC.md section 11): directions per image from visual vocabulary entries.

Uses the bundled core and the read-only official packs (vocabulary/packs, with the Visual Direction pack) and
synthetic packs in temporary folders. No model is called."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from goated_prompter.features.vocabulary import visual
from goated_prompter.features.vocabulary.packs import OFFICIAL_DIR, PackManager, VocabularyError
from goated_prompter.features.vocabulary.retrieval import RetrievalRequest, retrieve

CAMERA_PROP = {"id": "props:item.camera", "category": "item", "name": "Camera", "aliases": ["camera", "film camera"],
               "description": "A handheld camera.", "components": {"object": {"provides": [], "size": "small", "hands": 1}}}


def brief(request, *, people=2, fixed="The people.", randomized="pose, location", must=(), avoid=(), rules=(),
          style="Auto", target="Generic", creativity="Balanced", seed=11, amount=8, nsfw=False):
    characters = [{"label": f"person {n}", "gender": "custom", "custom": "adult", "pronoun": "they"} for n in range(1, people + 1)]
    return {"version": 9, "path": "nsfw_character" if nsfw else "sfw_character" if people else "non_character",
            "summary": request, "people": people, "characters": characters, "fixed": fixed, "randomized": randomized,
            "must": list(must), "avoid": list(avoid),
            "input": {"request": request, "rules": list(rules), "amount": amount, "seed": seed, "nsfw": nsfw},
            "settings": {"style": style, "target": target, "director": "", "length": "", "creativity": creativity}}


def settings(**changes):
    value = visual.default_settings()
    for dimension, patch in changes.items():
        value[dimension] = {**value[dimension], **patch}
    return value


class VisualHarness(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "packs").mkdir()
        self.manager = PackManager(self.root / "packs", self.root / "state.json", official_dir=OFFICIAL_DIR)
        self.registry = self.manager.registry_for(self.manager.resolve_selection(["visual"]))

    def install(self, pack_id, entries, *, categories=(), rating="general"):
        folder = self.root / "packs" / pack_id
        folder.mkdir()
        manifest = {"spec": 1, "id": pack_id, "name": pack_id.title(), "version": "1.0.0", "rating": rating,
                    "requires": {"core": ">=1.0.0"}, "categories": [{"id": c, "name": c.title()} for c in categories],
                    "files": ["entries.json"]}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "entries.json").write_text(json.dumps({"spec": 1, "entries": entries}), encoding="utf-8")

    def plan(self, value, config=None, registry=None, **kwargs):
        return visual.plan(registry or self.registry, value, config, **kwargs)

    def chosen(self, plan, count=8):
        return [{dimension: item.id for dimension, item in plan.directions(number)[0].items()} for number in range(1, count + 1)]


class Selection(VisualHarness):
    def test_visibility_recomputes_open_framing_but_keeps_user_named_framing(self):
        need = {"participants": {"person 1": {"whole": True, "regions": []}}, "space": True}
        plan = self.plan(brief("friends in different places"))
        plan.directions(1)
        plan.see(1, need)
        chosen = plan.directions(1)[0]
        self.assertNotEqual(visual.fit(self.registry, chosen["framing"].showing(), need)[0], "conflict")
        fixed = self.plan(brief("extreme close-up of two friends"))
        fixed.see(1, need)
        self.assertEqual(fixed.directions(1)[0]["framing"].id, "general:framing.extreme_close_up")

    def test_undeclared_visibility_is_unknown_not_incompatible(self):
        need = {"participants": {"person 1": {"whole": True, "regions": ["core:limb.hand"]}}}
        self.assertEqual(visual.fit(self.registry, {}, need)[0], "unknown")
        self.assertEqual(visual.fit(self.registry, {"whole": False}, need)[0], "conflict")
        self.assertEqual(visual.fit(self.registry, {"whole": True}, need)[0], "feasible")

    def test_detail_region_limits_count_each_participants_required_region(self):
        need = {"participants": {"a": {"regions": ["core:limb.hand"]},
                                 "b": {"regions": ["core:limb.hand"]}}}
        self.assertEqual(visual.fit(self.registry, {"max_regions": 1}, need)[0], "conflict")
        self.assertEqual(visual.fit(self.registry, {"max_regions": 2}, need)[0], "feasible")

    def test_complete_region_declarations_apply_even_with_a_detail_limit(self):
        need = {"participants": {"a": {"regions": ["core:limb.hand"]}}}
        shows = {"regions": ["core:anatomy.face"], "complete": True, "max_regions": 2}
        self.assertEqual(visual.fit(self.registry, shows, need)[0], "conflict")

    def test_framing_is_not_rejected_solely_by_legacy_cast_limits(self):
        self.install("legacy", [{"id": "legacy:framing.detail", "name": "Detail crop", "category": "visual_framing",
                                 "components": {"visual": {"dimension": "framing", "people": {"min": 1, "max": 1}}}}])
        registry = self.manager.registry_for(self.manager.resolve_selection(["legacy"]))
        plan = self.plan(brief("detail crop of friends", people=4), registry=registry)
        self.assertEqual(plan.directions(1)[0]["framing"].id, "legacy:framing.detail")

    def test_deterministic_per_slot_and_independent_of_other_slots(self):
        value = brief("two friends reading in a library")
        first, second = self.plan(value), self.plan(value)
        self.assertEqual(self.chosen(first), self.chosen(second))
        backwards = [{dimension: item.id for dimension, item in second.directions(number)[0].items()} for number in range(8, 0, -1)]
        self.assertEqual(backwards[::-1], self.chosen(first), "the order images are asked for changes nothing")
        lone = self.plan(value)
        self.assertEqual({d: item.id for d, item in lone.directions(5)[0].items()}, self.chosen(first)[4],
                         "image 5 is the same when images 1-4 never ran (failed or regenerated images change no other)")
        other_seed = self.plan(brief("two friends reading in a library", seed=12))
        self.assertNotEqual(self.chosen(other_seed), self.chosen(first))

    def test_images_differ_and_each_cycle_uses_the_whole_pool(self):
        plan = self.plan(brief("two friends reading in a library", creativity="Creative"))
        rows = self.chosen(plan, 12)
        for dimension in visual.DIMENSIONS:
            pool = plan.dimensions[dimension]["pool"]
            seen = [row[dimension] for row in rows[:len(pool)] if dimension in row]
            self.assertGreaterEqual(len(set(seen)), max(1, len(pool) - 2), f"{dimension}: a cycle covers its pool")
        self.assertGreater(len({json.dumps(row, sort_keys=True) for row in rows}), 10, "combinations vary across images")

    def test_toggles_and_variations(self):
        plan = self.plan(brief("a reader"), settings(lighting={"enabled": False}, framing={"variation": "same"},
                                                     camera_angle={"variation": "low"}))
        rows = self.chosen(plan)
        self.assertEqual(plan.dimensions["lighting"]["status"], "off")
        self.assertFalse([row for row in rows if "lighting" in row])
        self.assertEqual(len({row["framing"] for row in rows}), 1)
        self.assertEqual(len({row["camera_angle"] for row in rows}), 2)
        strict = self.plan(brief("a reader", creativity="Strict"))
        creative = self.plan(brief("a reader", creativity="Creative"))
        self.assertEqual(strict.dimensions["lighting"]["effective_variation"], "low")
        self.assertEqual(creative.dimensions["lighting"]["effective_variation"], "high")
        self.assertGreater(len(creative.pools["lighting"]), len(strict.pools["lighting"]))
        everything_off = self.plan(brief("a reader"), {dimension: {"enabled": False} for dimension in visual.DIMENSIONS})
        self.assertFalse(everything_off.active)
        self.assertEqual(everything_off.offer([1, 2]), [])

    def test_settings_are_validated(self):
        self.assertEqual(visual.validate_settings(None), visual.default_settings())
        self.assertEqual(visual.validate_settings({"lighting": {"enabled": False}})["lighting"], {"enabled": False, "variation": "auto"})
        for bad in ({"mood": {}}, {"lighting": {"variation": "wild"}}, {"lighting": {"enabled": "yes"}}, [], {"lighting": {"x": 1}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                visual.validate_settings(bad)


class Compatibility(VisualHarness):
    def assert_never_together(self, rows, first, second):
        self.assertFalse([row for row in rows if first in row.values() and second in row.values()], f"{first} with {second}")

    def test_conflicting_directions_never_share_an_image(self):
        for seed in range(6):
            rows = self.chosen(self.plan(brief("two dancers", creativity="Dice", seed=seed)), 30)
            self.assert_never_together(rows, "general:camera_angle.dutch_angle", "general:composition.symmetrical")
            self.assert_never_together(rows, "general:framing.establishing_shot", "visual:atmosphere.bokeh")
            self.assert_never_together(rows, "general:framing.establishing_shot", "visual:atmosphere.shallow_depth_of_field")
            self.assert_never_together(rows, "general:lighting.high_key", "visual:atmosphere.dramatic_shadows")
            for row in rows:
                self.assertEqual(len(row), len(set(row)), "one direction per dimension")

    def test_a_direction_the_brief_names_wins_every_conflict(self):
        rows = self.chosen(self.plan(brief("a dutch angle portrait of two dancers", creativity="Dice")), 20)
        self.assertTrue(all(row["camera_angle"] == "general:camera_angle.dutch_angle" for row in rows))
        self.assertFalse([row for row in rows if row.get("composition") == "general:composition.symmetrical"])

    def test_conflicts_must_name_directions(self):
        self.install("bad", [{"id": "bad:look.tilt", "category": "look", "name": "Tilt", "components": {"visual": {
            "dimension": "camera_angle", "conflicts": ["core:limb.hand"]}}}], categories=["look"])
        with self.assertRaises(VocabularyError) as caught:
            self.manager.registry_for(self.manager.resolve_selection(["bad"]))
        self.assertIn("not one", " ".join(caught.exception.problems))


class TheBriefComesFirst(VisualHarness):
    def test_fixed_camera_and_lighting_are_kept_in_every_image(self):
        plan = self.plan(brief("low angle shots of two knights in golden hour light"))
        rows = self.chosen(plan)
        self.assertEqual({row["camera_angle"] for row in rows}, {"general:camera_angle.low_angle"})
        self.assertEqual({row["lighting"] for row in rows}, {"general:lighting.golden_hour"})
        self.assertEqual(plan.dimensions["camera_angle"]["status"], "fixed")
        self.assertEqual(plan.dimensions["camera_angle"]["source"], "request")

    def test_a_dimension_the_brief_sets_in_its_own_words_gets_no_direction(self):
        plan = self.plan(brief("two knights", must=["dramatic, moody lighting"]))
        self.assertEqual(plan.dimensions["lighting"]["status"], "kept")
        self.assertFalse([row for row in self.chosen(plan) if "lighting" in row])
        self.assertEqual(self.plan(brief("a woman in a light blue dress")).dimensions["lighting"]["status"], "open",
                         "the word light is not the lighting")
        opened = self.plan(brief("two knights with dramatic lighting", randomized="lighting, location"))
        self.assertEqual(opened.dimensions["lighting"]["status"], "open", "randomized reopens what the request mentions")

    def test_directions_randomized_names_take_turns(self):
        plan = self.plan(brief("two knights", randomized="close-ups and wide shots, location"))
        self.assertEqual({row["framing"] for row in self.chosen(plan)}, {"general:framing.close_up", "general:framing.wide_shot"})
        extreme = self.plan(brief("an extreme close-up of two hands"))
        self.assertEqual(extreme.dimensions["framing"]["named"], ["general:framing.extreme_close_up"],
                         "a match inside a longer one is not a mention")

    def test_avoid_and_negation_rule_directions_out(self):
        plan = self.plan(brief("two knights, no dutch angle", avoid=["no bokeh", "lens flare"], style="Realistic"))
        excluded = {item["id"]: item["reason"] for item in plan.log["excluded"]}
        for entry_id in ("general:camera_angle.dutch_angle", "visual:atmosphere.bokeh", "visual:atmosphere.lens_flare"):
            self.assertEqual(excluded[entry_id], "ruled out by the brief")
        used = {value for row in self.chosen(plan, 30) for value in row.values()}
        self.assertFalse(used & set(excluded))


class StylesCastAndPacks(VisualHarness):
    def test_media_follow_the_style_without_forcing_photography(self):
        anime = self.plan(brief("two friends", style="Anime"))
        excluded = {item["id"]: item["reason"] for item in anime.log["excluded"]}
        self.assertIn("visual:atmosphere.film_grain", excluded)
        self.assertIn("general:lighting.studio", excluded)
        self.assertNotIn("visual:atmosphere.bokeh", excluded, "anime keeps bokeh")
        auto = self.plan(brief("two friends", style="Auto"))
        limited = {item["id"] for item in auto.log["excluded"]}
        self.assertTrue({"visual:atmosphere.film_grain", "visual:atmosphere.bokeh", "general:lighting.studio"} <= limited,
                        "Auto (style left to the request): only directions for every style")
        self.assertEqual(self.plan(brief("two friends", target="Anima")).log["style"], "Anime")
        photo = {item["id"] for item in self.plan(brief("two friends", style="Realistic")).log["excluded"]}
        self.assertNotIn("visual:atmosphere.film_grain", photo)

    def test_cast_size(self):
        # Framing is never limited by head count alone (SPEC section 12): close-ups stay possible for five people,
        # and what a composed scene must show decides instead.
        crowd = self.plan(brief("five friends at a party", people=5))
        excluded = {item["id"] for item in crowd.log["excluded"]}
        self.assertTrue({"general:framing.extreme_close_up", "general:framing.close_up"}.isdisjoint(excluded))
        self.assertTrue({"general:camera_angle.over_the_shoulder", "general:camera_angle.pov"}.isdisjoint(excluded))
        still_life = self.plan(brief("a perfume bottle on marble", people=0))
        excluded = {item["id"] for item in still_life.log["excluded"]}
        self.assertTrue({"general:camera_angle.over_the_shoulder", "general:camera_angle.pov"} <= excluded,
                        "a direction that needs a person still declares it")

    def test_only_selected_packs_provide_directions(self):
        core_only = self.manager.registry_for(self.manager.resolve_selection([]))
        plan = self.plan(brief("two friends"), registry=core_only)
        self.assertFalse(plan.active, "Core contains interfaces, not concrete visual choices")
        general = self.manager.registry_for(self.manager.resolve_selection(["general"]))
        self.assertTrue(self.plan(brief("two friends"), registry=general).active)
        self.assertNotIn("atmosphere", plan.pools, "atmosphere comes only with the Atmosphere pack")
        self.install("looks", [{"id": "looks:light.aurora", "category": "look", "name": "Aurora glow",
                                "description": "Green and violet aurora light.", "components": {"visual": {"dimension": "lighting"}}}],
                     categories=["look"])
        self.manager.set_enabled("looks", False)
        with_custom = self.manager.registry_for(self.manager.resolve_selection(["looks"]))
        custom = self.plan(brief("two friends", creativity="Dice"), registry=with_custom)
        self.assertIn("looks:light.aurora", [item.id for item in custom.pools["lighting"]],
                      "a custom pack's directions, even if off globally")
        self.assertNotIn("atmosphere", custom.pools)
        self.assertNotIn("looks:light.aurora", {item.id for items in self.plan(brief("two friends")).every.values() for item in items})

    def test_ratings_follow_the_brief(self):
        self.install("spicy", [{"id": "spicy:light.boudoir", "category": "look", "name": "Boudoir glow", "rating": "adult",
                                "description": "Low red light.", "components": {"visual": {"dimension": "lighting"}}}],
                     categories=["look"], rating="adult")
        registry = self.manager.registry_for(self.manager.resolve_selection(["spicy"]))
        sfw = self.plan(brief("two adults"), registry=registry, allowed=("general", "mature"))
        self.assertIn({"id": "spicy:light.boudoir", "reason": "rating adult is not allowed"}, sfw.log["excluded"])
        nsfw = self.plan(brief("two adults", nsfw=True), registry=registry)
        self.assertIn("spicy:light.boudoir", [item.id for item in nsfw.every["lighting"]], "allowed: a candidate")


class ContentRetrievalIsUnchanged(VisualHarness):
    def requests(self):
        return ["two friends hugging on a sofa", "Epic fantasy scenes of a dragon", "low angle shot of a woman with a camera",
                "two adults in golden hour light on a beach, close-up"]

    def test_directions_are_never_offered_as_scene_content(self):
        with_visual = self.manager.registry_for(self.manager.resolve_selection(["fantasy", "visual"]))
        without = self.manager.registry_for(self.manager.resolve_selection(["fantasy"]))
        for text in self.requests():
            request = RetrievalRequest(request=text, randomized="lighting, camera angle, place", seed=3)
            first, second = retrieve(with_visual, request).to_dict(), retrieve(without, request).to_dict()
            self.assertEqual(first, second, text)
            self.assertFalse([entry for entry in first["entries"] + first["inspiration"] if entry["pack"] == "visual"])

    def test_camera_direction_never_finds_a_camera_prop(self):
        self.install("props", [CAMERA_PROP], categories=[])
        registry = self.manager.registry_for(self.manager.resolve_selection(["props", "visual"]))
        value = brief("a low camera angle portrait of two dancers")
        plan = self.plan(value, registry=registry)
        self.assertEqual(plan.dimensions["camera_angle"]["named"], ["general:camera_angle.low_angle"])
        named = lambda text: [entry["id"] for entry in retrieve(registry, RetrievalRequest(request=text)).to_dict()["entries"]]
        self.assertIn("props:item.camera", named(value["input"]["request"]), "without Visual Direction the word finds the prop")
        masked = visual.masked_brief(value, plan.mask)
        self.assertEqual(masked["input"]["request"], "a portrait of two dancers")
        self.assertNotIn("props:item.camera", named(masked["input"]["request"]))
        holding = brief("a photographer holding a camera")
        self.assertEqual(visual.masked_brief(holding, self.plan(holding, registry=registry).mask)["input"]["request"],
                         "a photographer holding a camera", "a camera in the scene stays scene content")


if __name__ == "__main__":
    unittest.main()
