"""Inspiration: entries the request does not name, from the categories the brief's intent opens.

The production packs are loaded through the real PackManager (the core mandatory, Fantasy and Adult official),
custom packs are installed in a temporary folder. Nothing here names a pack or a sexual word in engine code: the
same rules reach every pack through its declared categories, theme and rating.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from goated_prompter.features.vocabulary.explorer import inspect_registry, inspection_sample
from goated_prompter.features.vocabulary.packs import PackManager
from goated_prompter.features.vocabulary.retrieval import RetrievalConfig, RetrievalRequest, retrieve
from tests.unit.vocabulary.test_vocabulary_packs import tiny_pack

WOMAN = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she"}
MAN = {"label": "man", "gender": "male", "custom": "", "pronoun": "he"}
MEN = ({"label": "man 1", "gender": "male", "custom": "", "pronoun": "he"},
       {"label": "man 2", "gender": "male", "custom": "", "pronoun": "he"})
WOMEN = ({"label": "woman 1", "gender": "female", "custom": "", "pronoun": "she"},
         {"label": "woman 2", "gender": "female", "custom": "", "pronoun": "she"})
DRAGON = ({"label": "dragon", "gender": "custom", "custom": "a dragon", "pronoun": "it"},)


def being():
    return {"count": 1, "kind": "being"}


def brief(request, *, randomized="lighting, camera angle", characters=(WOMAN, MAN), nsfw=False, avoid=(), seed=0,
          creativity="Balanced", director="", style=""):
    """A RetrievalRequest as RetrievalRequest.from_brief builds it from a confirmed brief."""
    return RetrievalRequest(request=request, summary=request, fixed=request, randomized=randomized,
                            characters=tuple(characters), nsfw=nsfw, avoid=tuple(avoid), seed=seed,
                            creativity=creativity, director=director, style=style)


def ideas(found, category=None):
    return [entry.id for entry in found.inspiration if category is None or entry.category == category]


def category(found, key):
    return next(item for item in found.intent["categories"] if item["id"] == key)


class Packs(unittest.TestCase):
    """The shipped packs, plus custom packs written into a temporary install folder."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.manager = PackManager(self.root / "installed", self.root / "state.json")

    def install(self, pack_id, entries, **manifest):
        folder = self.root / "installed" / pack_id
        folder.mkdir(parents=True)
        files = tiny_pack(pack_id, entries, **{key: value for key, value in manifest.items() if key != "description"})
        if manifest.get("description"):
            files["manifest.json"]["description"] = manifest["description"]
        for name, value in files.items():
            (folder / name).write_text(json.dumps(value), encoding="utf-8")

    def ask(self, *args, config=None, **kwargs):
        return retrieve(self.manager.registry(), brief(*args, **kwargs), config)


class BroadRequests(Packs):

    def test_a_broad_adult_request_gets_positions_and_places(self):
        found = self.ask("Two adult men having sex.", randomized="sex positions, location, lighting, camera angle",
                         characters=MEN, nsfw=True)
        self.assertEqual(found.entries, [], "the request names no entry")
        self.assertEqual(found.warnings, [])
        self.assertEqual(found.intent["content"], "adult")
        self.assertEqual(found.intent["themes"], [], '"adult" is a rating word, not a theme')
        positions = [entry for entry in found.inspiration if entry.category == "position"]
        self.assertGreaterEqual(len(positions), 10, "a large pack gives a large rotation")
        self.assertTrue(all(entry.rating == "adult" for entry in positions), "the content level ranks adult positions first")
        self.assertTrue(all(sorted(entry.scopes) == ["arrangement", "category", "content"] for entry in positions))
        self.assertTrue(ideas(found, "space"))
        self.assertEqual(ideas(found, "action") + ideas(found, "item"), [], "no act or accessory is asked for")

    def test_acts_come_only_when_the_brief_asks_for_them(self):
        found = self.ask("Two adult men having sex.", randomized="sex positions, sexual acts", characters=MEN, nsfw=True)
        acts = [entry for entry in found.inspiration if entry.category == "action"]
        self.assertTrue(acts)
        self.assertTrue(all(sorted(entry.scopes) == ["category", "content"] for entry in acts))
        self.assertTrue(any(entry.status == "unknown" for entry in acts), "genitals are never inferred from gender")

    def test_gender_never_changes_what_is_offered(self):
        men = self.ask("Two adults having sex", randomized="sex positions, acts", characters=MEN, nsfw=True)
        women = self.ask("Two adults having sex", randomized="sex positions, acts", characters=WOMEN, nsfw=True)
        self.assertEqual([(entry.id, entry.status) for entry in men.inspiration],
                         [(entry.id, entry.status) for entry in women.inspiration])

    def test_unspecified_arrangement_and_place_vary_without_naming_them(self):
        found = self.ask("Two adult men having sex.", randomized="lighting, camera angle", characters=MEN, nsfw=True)
        self.assertTrue(ideas(found, "position"), "every image arranges its people")
        self.assertTrue(ideas(found, "space"), "the brief sets no place, so places vary")
        self.assertEqual(category(found, "space")["reached"][0]["scope"], "setting")
        self.assertEqual(ideas(found, "action") + ideas(found, "item"), [])
        couple = self.ask("A couple embracing", randomized="lighting")
        self.assertEqual([entry.id for entry in couple.entries], ["core:action.hug"])
        self.assertTrue(ideas(couple, "space"))
        self.assertEqual(ideas(couple, "position") + ideas(couple, "action"), [], "the embrace stays the interaction")

    def test_a_place_the_request_sets_is_kept_however_it_is_worded(self):
        for request in ("Two men having sex on a train", "Two men having sex in a dark forest", "Two men having sex on a bed"):
            with self.subTest(request=request):
                found = self.ask(request, randomized="lighting", characters=MEN, nsfw=True)
                self.assertEqual(ideas(found, "space"), [])
                self.assertTrue(ideas(found, "position"))
                self.assertTrue(found.intent["fixed"].get("place") or found.intent["fixed"].get("space"))
        opened = self.ask("Two men having sex in different locations", randomized="lighting", characters=MEN, nsfw=True)
        self.assertTrue(ideas(opened, "space"), "a phrase that names the category opens it instead")

    def test_without_people_no_place_or_pose_is_invented(self):
        for request in ("a bowl of fruit", "a red sports car"):
            with self.subTest(request=request):
                self.assertEqual(self.ask(request, characters=()).inspiration, [])
        self.assertTrue(ideas(self.ask("a bowl of fruit", randomized="setting", characters=()), "space"), "unless the brief asks")

    def test_the_rating_alone_opens_no_act_accessory_or_unrelated_entry(self):
        solo = self.ask("A naked woman posing alone", randomized="lighting", characters=(WOMAN,), nsfw=True)
        self.assertTrue(ideas(solo, "posture"))
        self.assertTrue(ideas(solo, "space"))
        self.assertEqual(ideas(solo, "action") + ideas(solo, "item"), [], "no restraints or toys nobody asked for")
        kiss = self.ask("Two women kissing", randomized="lighting", characters=WOMEN, nsfw=True)
        self.assertEqual([entry.id for entry in kiss.entries], ["core:action.kiss"])
        self.assertEqual(ideas(kiss, "position") + ideas(kiss, "action") + ideas(kiss, "item"), [])

    def test_an_sfw_brief_is_never_given_adult_ideas(self):
        found = self.ask("Two adult men having sex.", randomized="sex positions, location", characters=MEN)
        self.assertIsNone(found.intent["content"])
        self.assertFalse([entry for entry in found.inspiration if entry.rating == "adult"])
        self.assertTrue(category(found, "position")["counts"].get("rating"), "adult positions are counted as rating-excluded")

    def test_a_broad_fantasy_request_gets_fantasy_actions_and_places(self):
        found = self.ask("Epic fantasy scenes of a dragon", randomized="pose, setting, lighting", characters=DRAGON)
        self.assertEqual([theme["pack"] for theme in found.intent["themes"]], ["fantasy"])
        breathe = next(entry for entry in found.inspiration if entry.id == "fantasy:action.breathe_fire")
        self.assertIn(breathe.status, ("feasible", "eligible"))
        self.assertEqual(set(ideas(found, "space")), {"fantasy:space.great_hall", "fantasy:space.enchanted_woods", "fantasy:space.lair"},
                         "the theme ranks its own places above the core's")
        self.assertNotIn("fantasy:item.staff", ideas(found), "no idea in the pool takes a staff in a hand")
        self.assertIn("core:posture.flying", ideas(found, "posture"))
        self.assertFalse([entry for entry in found.inspiration if entry.id == "core:posture.standing_four" and entry.status == "conflict"])

    def test_shared_description_words_reach_no_theme(self):
        for request, randomized in (("A woman in different places", "location, pose"), ("Two people in many positions", "positions")):
            with self.subTest(request=request):
                found = self.ask(request, randomized=randomized)
                self.assertEqual(found.intent["themes"], [])
                self.assertFalse([entry for entry in found.inspiration if entry.pack != "core"])

    def test_a_cast_body_or_trait_reaches_its_packs_theme(self):
        drake = ({"label": "beast", "gender": "custom", "custom": "a drake", "pronoun": "it"},)
        found = self.ask("A sleeping beast", randomized="setting", characters=drake)
        self.assertEqual(found.intent["themes"][0]["why"], "beast is cast as Dragon")
        self.assertTrue(ideas(found, "space"))
        plain = self.ask("A woman sleeping", randomized="setting", characters=(WOMAN,))
        self.assertEqual(plain.intent["themes"], [], "being human is no theme")

    def test_a_broad_general_request_gets_everyday_ideas_only(self):
        found = self.ask("A woman reading", randomized="activity, props, setting, pose", characters=(WOMAN,))
        self.assertEqual(ideas(found, "action"), ["core:action.hold"])
        self.assertIn("core:item.book", ideas(found, "item"))
        self.assertTrue(ideas(found, "space"))
        self.assertTrue(ideas(found, "posture"))
        self.assertFalse([entry for entry in found.inspiration if entry.pack != "core"], "themed packs need their theme")
        book = next(entry for entry in found.inspiration if entry.id == "core:item.book")
        self.assertEqual(book.attach_to, ["core:action.hold"])

    def test_a_custom_pack_is_treated_like_the_shipped_ones(self):
        self.install("neon", [
            {"id": "neon:space.alley", "category": "space", "name": "Neon alley", "description": "A wet alley under signs.",
             "components": {"environment": {"provides": ["core:surface.ground"]}}},
            {"id": "neon:action.jack_in", "category": "action", "name": "Jack in", "description": "Plugs a cable into a port.",
             "components": {"participants": {"slots": {"user": being()}},
                            "requirements": {"participants": {"user": {"all_of": ["core:limb.hand"]}}}}}],
            description="Cyberpunk: neon cities, hackers and implants.")
        found = self.ask("Cyberpunk street scenes of a woman", randomized="location, activity", characters=(WOMAN,))
        self.assertIn("neon:space.alley", ideas(found, "space"))
        self.assertIn("neon:action.jack_in", ideas(found, "action"))
        plain = self.ask("A woman on a street", randomized="location, activity", characters=(WOMAN,))
        self.assertFalse([entry_id for entry_id in ideas(plain) if entry_id.startswith("neon:")])

    def test_the_content_level_is_the_rating_not_a_pack_or_a_word(self):
        self.manager.set_enabled("adult", False)  # only this custom pack offers adult positions here
        standing = {"participants": {"a": {"posture": "core:posture.standing"}, "b": {"posture": "core:posture.standing"}}}
        self.install("studio", [
            {"id": "studio:position.back_to_back", "category": "position", "name": "Back to back",
             "description": "Backs pressed against each other.",
             "components": {"participants": {"slots": {"a": being(), "b": being()}}, "spatial": standing}},
            {"id": "studio:action.shared_wheel", "category": "action", "name": "Shared wheel",
             "description": "Two people shape one pot on a wheel.",
             "components": {"participants": {"slots": {"a": being(), "b": being()}},
                            "requirements": {"participants": {"a": {"all_of": ["core:limb.hand"]}, "b": {"all_of": ["core:limb.hand"]}}},
                            "claims": {"a": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "contact"}]}}}],
            rating="adult")
        found = self.ask("Two adults together", characters=(WOMAN, MAN), nsfw=True)
        self.assertIn("studio:position.back_to_back", ideas(found, "position"), "an adult-rated arrangement ranks first")
        self.assertNotIn("studio:action.shared_wheel", ideas(found), "an act is never opened by the rating alone")
        asked = self.ask("Two adults together", randomized="activities", characters=(WOMAN, MAN), nsfw=True)
        self.assertIn("studio:action.shared_wheel", ideas(asked, "action"))
        self.assertFalse([entry_id for entry_id in ideas(self.ask("Two adults together", characters=(WOMAN, MAN)))
                          if entry_id.startswith("studio:")], "the rating still decides eligibility")


class FixedAndRandomized(Packs):

    def test_a_named_position_and_place_fix_the_interaction_and_the_place(self):
        found = self.ask("Two men having sex in missionary on a bed", characters=MEN, nsfw=True)
        named = {entry.id for entry in found.entries}
        self.assertTrue({"adult:position.missionary", "core:space.bed"} <= named)
        registry = self.manager.registry()
        self.assertTrue(all(entry_id in ("core:space.bed", "adult:position.missionary")
                            or "adult:position.missionary" in registry.entry(entry_id).get("extends", []) for entry_id in named), named)
        self.assertEqual(found.intent["fixed"]["space"], ["Bed"])
        self.assertIn("Missionary", found.intent["fixed"]["interaction"])
        for key in ("position", "action", "space"):
            self.assertEqual(ideas(found, key), [], key)
        self.assertIn("fixes the interaction", category(found, "position")["reason"])
        self.assertTrue(all(not scene["ideas"] for scene in found.scenes(4)))

    def test_a_place_the_vocabulary_does_not_know_is_never_replaced(self):
        found = self.ask("Two men having sex on a train", randomized="sex positions, lighting, camera angle", characters=MEN, nsfw=True)
        self.assertTrue(ideas(found, "position"))
        self.assertEqual(ideas(found, "space"), [])

    def test_what_may_vary_reopens_a_fixed_category(self):
        found = self.ask("A couple kissing", randomized="positions, location")
        self.assertEqual([entry.id for entry in found.entries], ["core:action.kiss"])
        self.assertEqual(ideas(found, "action"), [], "the kiss stays the action")
        self.assertIn("core:position.side_by_side", ideas(found, "position"))
        self.assertTrue(ideas(found, "space"))

    def test_the_train_platform_goodbye_keeps_its_hug_only(self):
        found = self.ask("A woman and a man hugging goodbye on a train platform",
                         randomized="clothing, facial expression, lighting, time of day, weather, train station details, camera angle")
        self.assertEqual([entry.id for entry in found.entries], ["core:action.hug"])
        self.assertEqual(found.inspiration, [])

    def test_director_and_style_never_open_anything(self):
        plain = self.ask("A woman and a man")
        found = self.ask("A woman and a man", director="Vary the positions, poses, locations, props and actions. Fantasy and adult.",
                         style="Fantasy")
        self.assertEqual(ideas(found), ideas(plain))
        self.assertEqual(found.intent["themes"], [])
        self.assertEqual(ideas(found, "action") + ideas(found, "item") + ideas(found, "posture"), [])


class Participants(Packs):

    def test_ideas_that_involve_the_whole_cast_rank_first(self):
        three = (WOMAN, MAN, {"label": "friend", "gender": "female", "custom": "", "pronoun": "she"})
        found = self.ask("Three friends posing together", randomized="positions", characters=three)
        self.assertEqual(ideas(found, "position")[0], "core:position.circle")
        self.assertTrue(any(item["id"] == "core:position.riding" and item.get("source") == "inspiration"
                            and item["reason"].startswith("conflict") for item in found.excluded))

    def test_one_person_is_never_offered_a_two_person_idea(self):
        found = self.ask("A woman posing", randomized="positions, activity", characters=(WOMAN,))
        offered = {entry.id for entry in found.inspiration}
        self.assertFalse(offered & {"core:position.side_by_side", "core:action.hug", "core:action.kiss"})
        self.assertIn("core:position.standing_alone", offered)

    def test_explicit_anatomy_changes_status_and_gender_does_not(self):
        plain = self.ask("Two adults, oral", characters=(WOMAN, MAN), nsfw=True)
        stated = self.ask("Two adults, oral", nsfw=True,
                          characters=(dict(WOMAN, custom="a woman with a penis"), dict(MAN, custom="a man with a penis")))
        status = lambda found: next(entry.status for entry in found.entries if entry.id == "adult:action.oral")
        self.assertEqual(status(plain), "unknown")
        self.assertEqual(status(stated), "eligible")
        self.assertEqual([member["traits"] for member in stated.cast], [["core:trait.penis"]] * 2)


class Restrictions(Packs):

    def toyish(self, entry_id):
        provides = self.manager.registry().resolved(entry_id)["components"].get("object", {}).get("provides", [])
        return bool({"adult:item.insertable", "adult:item.vibrating"} & set(provides))

    def test_no_toys_rules_out_toy_play_and_the_toys_only_it_takes(self):
        found = self.ask("A man and a woman having sex", randomized="sex positions, acts, toys and accessories", avoid=("no toys",), nsfw=True)
        self.assertTrue(any(item["id"] == "adult:action.toy_play" and "ruled out" in item["reason"] for item in found.excluded))
        self.assertFalse([entry_id for entry_id in ideas(found) if self.toyish(entry_id)])
        reason = next(item["reason"] for item in found.excluded if item["id"] == "adult:item.dildo")
        self.assertRegex(reason, r"^ruled out with (Toy play|Using a toy on a partner): it provides insertable")

    def test_no_toys_holds_even_when_another_named_interaction_could_take_them(self):
        found = self.ask("A woman holding something", randomized="props", avoid=("no toys",), characters=(WOMAN,), nsfw=True)
        self.assertEqual([entry.id for entry in found.entries], ["core:action.hold"])
        self.assertFalse([entry_id for entry_id in ideas(found) if self.toyish(entry_id)])
        self.assertIn("ruled out with", next(item["reason"] for item in found.excluded if item["id"] == "adult:item.dildo"))
        self.assertTrue(ideas(found, "item"), "other things to hold stay")
        allowed = self.ask("A woman holding something", randomized="props", characters=(WOMAN,), nsfw=True)
        self.assertTrue([entry_id for entry_id in ideas(allowed) if self.toyish(entry_id)], "without the exclusion toys are fitting ideas")

    def test_exclusions_follow_the_vocabularys_dependencies_in_any_pack(self):
        lit = {"id": "camp:item.lit", "category": "capability", "name": "Burning", "components": {"capability": {"implies": ["core:item"]}}}
        smoke = {"id": "camp:action.smoke", "category": "action", "name": "Smoking", "description": "Draws on something lit.",
                 "components": {"participants": {"slots": {"smoker": being(), "thing": {"count": 1, "kind": "object"}}},
                                "requirements": {"participants": {"smoker": {"all_of": ["core:limb.hand"]},
                                                                  "thing": {"all_of": ["camp:item.lit"]}}},
                                "claims": {"smoker": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "hold"}]}}}
        warm = {"id": "camp:action.warm_hands", "category": "action", "name": "Warm hands", "description": "Hands held to a fire.",
                "components": {"participants": {"slots": {"person": being(), "fire": {"count": 1, "kind": "object"}}},
                               "requirements": {"participants": {"person": {"all_of": ["core:limb.hand"]},
                                                                 "fire": {"all_of": ["camp:item.campfire"]}}},
                               "claims": {"person": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive", "purpose": "contact"}]}}}
        fire = {"id": "camp:item.campfire", "category": "capability", "name": "A fire", "components": {"capability": {"implies": ["core:item"]}}}
        pipe = {"id": "camp:item.pipe", "category": "item", "name": "Pipe", "components": {"object": {"provides": ["core:item.handheld", "camp:item.lit"]}}}
        cigar = {"id": "camp:item.cigar", "category": "item", "name": "Cigar", "components": {"object": {"provides": ["core:item.handheld", "camp:item.lit"]}}}
        logs = {"id": "camp:item.fire_pit", "category": "item", "name": "Fire pit", "components": {"object": {"provides": ["camp:item.campfire"]}}}
        self.install("camp", [lit, fire, smoke, warm, pipe, cigar, logs], description="Campsite life: tents, fires and smoke.")
        asked = self.ask("Campsite evenings of a man", randomized="activities, props", characters=(MAN,))
        self.assertTrue({"camp:item.pipe", "camp:item.cigar"} <= set(ideas(asked)))
        found = self.ask("Campsite evenings of a man", randomized="activities, props", avoid=("no smoking",), characters=(MAN,))
        self.assertNotIn("camp:action.smoke", ideas(found))
        self.assertFalse({"camp:item.pipe", "camp:item.cigar"} & set(ideas(found)), "what only smoking takes goes with it")
        self.assertIn("camp:item.fire_pit", ideas(found))
        pit = self.ask("Campsite evenings of a man", randomized="activities, props", avoid=("no fire pit",), characters=(MAN,))
        self.assertNotIn("camp:action.warm_hands", ideas(pit), "an act whose only object is ruled out goes with it")
        self.assertTrue(any(item["id"] == "camp:action.warm_hands" and "Fire pit" in item["reason"] for item in pit.excluded))

    def test_no_bondage_removes_the_restraints_with_it(self):
        found = self.ask("A man and a woman having sex", randomized="acts, accessories", avoid=("no bondage",), nsfw=True)
        self.assertNotIn("adult:action.restrained", ideas(found))
        self.assertFalse({"adult:item.handcuffs", "adult:item.bondage_rope"} & set(ideas(found)))

    def test_ruling_out_a_category_closes_it(self):
        found = self.ask("A man and a woman having sex", randomized="acts, accessories", avoid=("no accessories",), nsfw=True)
        self.assertEqual(ideas(found, "item"), [])
        self.assertIn("rules it out", category(found, "item")["reason"])

    def test_an_item_is_offered_only_with_an_interaction_it_serves(self):
        seen_items = False
        for seed in range(6):
            found = self.ask("Two adult men having sex.", randomized="sex positions, acts, toys and accessories, location",
                             characters=MEN, nsfw=True, seed=seed)
            named = {entry.id for entry in found.entries}
            attached = {entry.id: set(entry.attach_to) for entry in found.inspiration if entry.attach_to}
            seen_items = seen_items or bool(attached)
            for scene in found.scenes(24):
                for entry_id in scene["ideas"]:
                    if entry_id in attached:
                        self.assertTrue(attached[entry_id] & (set(scene["ideas"]) | named), scene)
        self.assertTrue(seen_items)

KINKS_SOURCE = Path(__file__).resolve().parents[3] / "vocabulary" / "optional" / "adult_kinks"


class KinksSetting(Packs):
    """The opt-in kinks pack: the kinks setting is installing (or enabling) it; without it there are no kinks."""

    def install_kinks(self):
        shutil.copytree(KINKS_SOURCE, self.root / "installed" / "adult_kinks")

    def kinks(self, found):
        return [entry.id for entry in [*found.entries, *found.inspiration] if entry.pack == "adult_kinks"]

    def test_without_the_pack_there_are_no_kinks(self):
        found = self.ask("BDSM scenes of two men in bondage, foot worship", randomized="acts, accessories, location",
                         characters=MEN, nsfw=True)
        self.assertEqual(self.kinks(found), [])
        self.assertNotIn("adult_kinks", {pack["id"] for pack in self.manager.discover()})

    def test_installed_kinks_come_with_kink_words(self):
        self.install_kinks()
        found = self.ask("BDSM scenes of two men", randomized="sex positions, location", characters=MEN, nsfw=True)
        self.assertEqual([theme["pack"] for theme in found.intent["themes"]], ["adult_kinks"])
        self.assertTrue([entry for entry in found.inspiration if entry.pack == "adult_kinks" and entry.category == "action"])
        self.manager.set_enabled("adult_kinks", False)
        self.assertEqual(self.kinks(self.ask("BDSM scenes of two men", randomized="sex positions, location", characters=MEN, nsfw=True)),
                         [], "disabled is the no-kinks setting")

    def test_kinks_are_never_offered_to_sfw_briefs(self):
        self.install_kinks()
        self.assertEqual(self.kinks(self.ask("BDSM scenes of two men", randomized="acts, location", characters=MEN)), [])

    def test_no_bondage_takes_every_restraint_act_and_item_with_it(self):
        self.install_kinks()
        found = self.ask("BDSM scenes of two men", randomized="acts, accessories", avoid=("no bondage",), characters=MEN, nsfw=True)
        registry = self.manager.registry()
        restraint = "adult_kinks:gear.restraint"

        def bound(entry_id):
            comp = registry.resolved(entry_id)["components"]
            needs = comp.get("requirements", {}).get("participants", {}).values()
            return restraint in comp.get("object", {}).get("provides", []) or any(restraint in need.get("all_of", []) for need in needs)
        offered = [entry.id for entry in found.inspiration]
        self.assertTrue(offered)
        self.assertFalse([entry_id for entry_id in offered if bound(entry_id)])
        self.assertTrue(any(item["id"] == "adult_kinks:action.hogtie" for item in found.excluded))
        spanking = self.ask("BDSM spanking", randomized="acts", avoid=("no bondage",), characters=MEN, nsfw=True)
        self.assertIn("adult_kinks:action.spanking", [entry.id for entry in spanking.entries], "impact play is not bondage")

    def test_no_feet_rules_out_the_foot_acts_by_their_tag(self):
        self.install_kinks()
        found = self.ask("BDSM scenes of two men", randomized="acts", avoid=("no feet",), characters=MEN, nsfw=True)
        registry = self.manager.registry()
        self.assertFalse([entry.id for entry in found.inspiration if "feet" in registry.entry(entry.id).get("tags", [])])
        asked = self.ask("Two men, foot worship", characters=MEN, nsfw=True)
        self.assertIn("adult_kinks:action.foot_worship", [entry.id for entry in asked.entries])

    def test_pet_play_is_adult_humans_in_pet_roles(self):
        self.install_kinks()
        registry = self.manager.registry()
        pets = [entry_id for entry_id in registry.ids() if "pet_play" in registry.entry(entry_id).get("tags", [])]
        self.assertGreaterEqual(len(pets), 10)
        for entry_id in pets:
            with self.subTest(entry=entry_id):
                self.assertEqual(registry.resolved(entry_id)["rating"], "adult")
                self.assertEqual(registry.owner(entry_id), "adult_kinks")
        for entry_id in ("adult_kinks:action.puppy_play", "adult_kinks:action.kitten_play", "adult_kinks:action.pony_play"):
            self.assertIn("adult human", registry.entry(entry_id)["description"])
        self.assertFalse([entry_id for entry_id in registry.ids() if registry.owner(entry_id) == "adult_kinks"
                          and registry.resolved(entry_id)["category"] == "body"], "the pack defines no animal bodies")


class Rotation(Packs):

    def found(self, seed=0, creativity="Balanced"):
        return self.ask("Two adult men having sex.", randomized="sex positions, acts, location", characters=MEN, nsfw=True,
                        seed=seed, creativity=creativity)

    def test_a_dataset_sees_every_idea_spread_over_its_scenes(self):
        found = self.found()
        plan = found.scenes(40)
        main = {entry.id for entry in found.inspiration if not entry.attach_to}
        self.assertEqual({entry_id for scene in plan for entry_id in scene["ideas"]} & main, main)
        for scene in plan:
            self.assertEqual(len(scene["ideas"]), len(set(scene["ideas"])))
            self.assertLessEqual(len(scene["ideas"]), found.per_scene + 1)
            kinds = [next(entry.category for entry in found.inspiration if entry.id == entry_id) for entry_id in scene["ideas"]
                     if entry_id in main]
            self.assertEqual(len(kinds), len(set(kinds)), "one idea per category while several categories are open")
        self.assertTrue(all(first["ideas"] != second["ideas"] for first, second in zip(plan, plan[1:])))

    def test_the_same_seed_gives_the_same_ideas_and_another_seed_others(self):
        self.assertEqual(self.found(seed=5).scenes(12), self.found(seed=5).scenes(12))
        self.assertTrue(any(self.found(seed=5).scenes(12) != self.found(seed=other).scenes(12) for other in (6, 7, 8)))

    def test_a_scene_gets_the_same_ideas_whatever_was_asked_before(self):
        found, fresh = self.found(seed=3), self.found(seed=3)
        found.ideas(9)
        self.assertEqual([entry.id for entry in found.ideas(4)], [entry.id for entry in fresh.ideas(4)])
        self.assertEqual(found.offer([4, 5]), fresh.offer([4, 5]))

    def test_creativity_sets_how_many_ideas_a_scene_gets(self):
        self.assertEqual(len([entry for entry in self.found(creativity="Strict").ideas(1) if not entry.attach_to]), 2)
        self.assertEqual(len([entry for entry in self.found(creativity="Dice").ideas(1) if not entry.attach_to]), 4)

    def test_the_offer_lists_named_entries_once_and_ideas_per_concept(self):
        found = self.ask("A couple kissing", randomized="positions, location", seed=2)
        block, offered = found.offer([3, 4])
        self.assertIn("Named by the request (every image):\n- Kiss", block)
        self.assertIn("- concept 1: ", block)
        self.assertIn("- concept 2: ", block)
        self.assertEqual(offered[0], "core:action.kiss")
        self.assertEqual(set(offered[1:]), {entry.id for number in (3, 4) for entry in found.ideas(number)})
        self.assertIn("optional inspiration", block)

    def test_without_ideas_the_offer_is_the_named_block(self):
        found = self.ask("A woman and a man hugging goodbye on a train platform")
        self.assertEqual(found.offer([1, 2])[0], found.render())


class SmallPools(unittest.TestCase):
    """Rotation itself, on hand-made pools: fewer ideas than scenes, more ideas per scene than exist, one idea."""

    @staticmethod
    def made(pools, per_scene=3, seed=0, entries=()):
        from goated_prompter.features.vocabulary.retrieval import Retrieval, RetrievedEntry

        def entry(entry_id, score, attach=()):
            return RetrievedEntry(id=entry_id, name=entry_id.title(), category=entry_id[0], pack="test", rating="general", description="",
                                  status="eligible", relevance=1.0, score=score, why=[], source="inspiration", attach_to=list(attach))
        built = [(key, [entry(*item) for item in items]) for key, items in pools]
        return Retrieval([entry(entry_id, 1.0) for entry_id in entries], [], [], [], [], RetrievalConfig(), pools=built,
                         seed=seed, per_scene=per_scene)

    def test_two_ideas_over_thirty_scenes_alternate_evenly(self):
        found = self.made([("position", [("p1", 2.0), ("p2", 1.0)])])
        plan = [scene["ideas"] for scene in found.scenes(30)]
        self.assertTrue(all(len(ideas) == 2 and len(set(ideas)) == 2 for ideas in plan), "never the same idea twice in a scene")
        firsts = [ideas[0] for ideas in plan]
        self.assertEqual((firsts.count("p1"), firsts.count("p2")), (15, 15))
        self.assertTrue(all(first != second for first, second in zip(firsts, firsts[1:])))

    def test_one_idea_is_offered_to_every_scene(self):
        found = self.made([("space", [("s1", 1.0)])], per_scene=4)
        self.assertEqual([scene["ideas"] for scene in found.scenes(7)], [["s1"]] * 7)

    def test_categories_each_get_their_turn_and_counts_stay_even(self):
        found = self.made([("position", [("p1", 3.0), ("p2", 2.0), ("p3", 1.0)]), ("space", [("s1", 1.0), ("s2", 1.0)])], per_scene=1)
        plan = [scene["ideas"][0] for scene in found.scenes(20)]
        self.assertEqual(sum(entry_id.startswith("p") for entry_id in plan), 10)
        counts = [plan.count(entry_id) for entry_id in ("p1", "p2", "p3")]
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_an_item_without_its_interaction_in_the_scene_waits(self):
        found = self.made([("position", [("p1", 1.0), ("p2", 1.0)]), ("item", [("i1", 1.0, ["p1"])])], per_scene=1)
        for scene in found.scenes(12):
            if "i1" in scene["ideas"]:
                self.assertIn("p1", scene["ideas"])
        self.assertTrue(any("i1" in scene["ideas"] for scene in found.scenes(12)))
        named = self.made([("item", [("i1", 1.0, ["n1"])])], entries=["n1"])
        self.assertEqual([scene["ideas"] for scene in named.scenes(3)], [["i1"]] * 3, "a named interaction anchors it in every scene")
        orphan = self.made([("item", [("i1", 1.0, ["gone"])])])
        self.assertEqual([scene["ideas"] for scene in orphan.scenes(3)], [[]] * 3)

    def test_long_runs_finish_and_are_reproducible(self):
        pools = [("position", [(f"p{n}", 1.0 + n) for n in range(5)]), ("space", [(f"s{n}", 1.0) for n in range(3)])]
        first = self.made(pools, seed=9).scenes(5000)
        self.assertEqual(len(first), 5000)
        self.assertEqual(first, self.made(pools, seed=9).scenes(5000))
        self.assertTrue(any(first[:10] != self.made(pools, seed=other).scenes(10) for other in (10, 11, 12)))
        self.assertEqual(self.made([]).scenes(3), [{"scene": n, "entries": [], "ideas": []} for n in (1, 2, 3)])


class EmptyAndDisabled(Packs):

    def test_no_packs_no_ideas(self):
        found = retrieve(None, brief("Two adult men having sex.", characters=MEN, nsfw=True))
        self.assertEqual((found.entries, found.inspiration), ([], []))
        self.assertEqual(found.warnings, ["no vocabulary packs are enabled"])
        self.assertEqual(found.scenes(2), [{"scene": 1, "entries": [], "ideas": []}, {"scene": 2, "entries": [], "ideas": []}])

    def test_an_irrelevant_pack_adds_nothing(self):
        self.install("kitchen", [{"id": "kitchen:item.whisk", "category": "item", "name": "Whisk", "components": {
            "object": {"provides": ["core:item.handheld"]}}}], description="Cooking tools and kitchens.")
        found = self.ask("A red sports car on a mountain road at dusk", characters=())
        self.assertEqual(found.inspiration, [])
        self.assertEqual(found.warnings, ["no relevant vocabulary for this request"])

    def test_a_pack_with_no_entries_is_harmless(self):
        self.install("blank", [], description="Nothing yet.")
        found = self.ask("Two adult men having sex.", randomized="sex positions", characters=MEN, nsfw=True)
        self.assertTrue(found.inspiration)
        self.assertFalse([entry for entry in found.inspiration if entry.pack == "blank"])

    def test_a_disabled_pack_offers_nothing(self):
        self.manager.set_enabled("adult", False)
        found = self.ask("Two adult men having sex.", randomized="sex positions", characters=MEN, nsfw=True)
        self.assertFalse([entry for entry in found.inspiration if entry.pack == "adult"])
        self.assertEqual(ideas(found, "position"), ["core:position.from_behind"], "the core's adult-rated position remains")

    def test_inspiration_can_be_turned_off(self):
        found = self.ask("Two adult men having sex.", characters=MEN, nsfw=True, config=RetrievalConfig(inspiration=False))
        self.assertEqual(found.inspiration, [])
        self.assertEqual(found.warnings, ["no relevant vocabulary for this request"])


class SameBehaviourEverywhere(Packs):

    def test_the_inspector_projection_is_the_engines_result(self):
        registry = self.manager.registry()
        sample = inspection_sample({"request": "Two adult men having sex.", "nsfw": True, "characters": ["adult man", "adult man"],
                                    "randomized": "sex positions, location", "avoid": ["no toys"], "seed": 9, "scenes": 4})
        shown = inspect_registry(registry, **sample)
        cast = tuple({"label": f"Character {number}", "gender": "custom", "custom": text} for number, text in enumerate(sample["characters"], 1))
        found = retrieve(registry, RetrievalRequest(request=sample["request"], nsfw=True, characters=cast, randomized=sample["randomized"],
                                                    avoid=("no toys",), seed=9))
        self.assertEqual(shown["inspiration"], found.to_dict()["inspiration"])
        self.assertEqual(shown["intent"], found.to_dict()["intent"])
        self.assertEqual(shown["scenes"], found.scenes(4))
        self.assertEqual(shown["seed"], 9)
        json.dumps(shown)

    def test_the_inspector_sample_keeps_its_old_shape_and_checks_the_new_fields(self):
        self.assertEqual(inspection_sample({"request": "a lantern"}),
                         {"request": "a lantern", "nsfw": False, "characters": [], "randomized": "", "avoid": [], "seed": 0, "scenes": 5})
        for bad in ({"seed": -1}, {"seed": True}, {"scenes": 0}, {"scenes": 21}, {"avoid": [""]}, {"randomized": 3},
                    {"unknown": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspection_sample({"request": "a lantern", **bad})


if __name__ == "__main__":
    unittest.main()
