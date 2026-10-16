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
        self.assertEqual([entry.id for entry in found.entries], ["adult:action.sex"],
                         "the broad activity is required, not replaceable position inspiration")
        self.assertEqual(found.warnings, [])
        self.assertEqual(found.intent["content"], "adult")
        self.assertEqual(found.intent["themes"], [{"pack": "adult", "name": "Adult", "why": "the brief names Sex", "scope": "entry"}],
                         "only the named activity, not the rating, reaches the pack")
        positions = [entry for entry in found.inspiration if entry.category == "position"]
        self.assertGreaterEqual(len(positions), 10, "a large pack gives a large rotation")
        adult = [index for index, entry in enumerate(positions) if entry.rating == "adult"]
        self.assertEqual(adult, list(range(len(adult))), "the content level ranks adult positions first")
        self.assertTrue(all(sorted(entry.scopes) == ["arrangement", "category", "content"] for entry in positions if entry.rating == "adult"))
        general = [entry for entry in positions if entry.rating != "adult"]
        self.assertTrue(general, "general positions stay eligible (no cutoff relative to the best), ranked below")
        self.assertTrue(all(entry.score < positions[0].score for entry in general))
        self.assertTrue(ideas(found, "space"))
        self.assertEqual(ideas(found, "action") + ideas(found, "item"), [], "no act or accessory is asked for")

    def test_acts_come_only_when_the_brief_asks_for_them(self):
        found = self.ask("Two adult men having sex.", randomized="sex positions, sexual acts", characters=MEN, nsfw=True)
        acts = [entry for entry in found.inspiration if entry.category == "action"]
        self.assertTrue(acts)
        asked = [index for index, entry in enumerate(acts) if sorted(entry.scopes) == ["category", "content"]]
        self.assertEqual(asked, list(range(len(asked))), "acts at the content level rank first")
        self.assertTrue(all(sorted(entry.scopes) in (["category"], ["category", "content"]) for entry in acts))
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
        self.assertEqual([entry.id for entry in couple.entries], ["general:action.hug"])
        self.assertTrue(ideas(couple, "space"))
        self.assertEqual(ideas(couple, "position") + ideas(couple, "action"), [], "the embrace already declares placement")

    def test_a_place_the_request_sets_is_kept_however_it_is_worded(self):
        for request in ("Two men having sex on a train", "Two men having sex in a dark forest", "Two men having sex on a bed"):
            with self.subTest(request=request):
                found = self.ask(request, randomized="lighting", characters=MEN, nsfw=True)
                self.assertEqual(ideas(found, "space"), [])
                self.assertTrue(ideas(found, "position"))
                # A known place is decided; a place in words the vocabulary does not know is only an uncertain guess.
                self.assertTrue(found.intent["uncertain"].get("place") or found.intent["fixed"].get("space"))
                self.assertNotIn("place", found.intent["fixed"])
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
        self.assertEqual([entry.id for entry in kiss.entries], ["general:action.kiss"])
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
        themed = {"fantasy:space.great_hall", "fantasy:space.enchanted_woods", "fantasy:space.lair"}
        places = ideas(found, "space")
        self.assertEqual(set(places[:3]), themed, "the theme ranks its own places above the core's")
        offered = [entry_id for scene in found.scenes(100) for entry_id in scene["ideas"] if entry_id in places]
        per = lambda group: sum(offered.count(entry_id) for entry_id in group) / len(group)
        self.assertGreater(per(themed), per(set(places) - themed), "and each is offered more often than a core place")
        self.assertNotIn("fantasy:item.staff", ideas(found), "no idea in the pool takes a staff in a hand")
        self.assertIn("general:posture.flying", ideas(found, "posture"))
        self.assertFalse([entry for entry in found.inspiration if entry.id == "general:posture.standing_four" and entry.status == "conflict"])

    def test_shared_description_words_reach_no_theme(self):
        for request, randomized in (("A woman in different places", "location, pose"), ("Two people in many positions", "positions")):
            with self.subTest(request=request):
                found = self.ask(request, randomized=randomized)
                self.assertEqual(found.intent["themes"], [])
                self.assertFalse([entry for entry in found.inspiration if entry.pack != "general"])

    def test_a_cast_body_or_trait_reaches_its_packs_theme(self):
        drake = ({"label": "beast", "gender": "custom", "custom": "a drake", "pronoun": "it"},)
        found = self.ask("A sleeping beast", randomized="setting", characters=drake)
        self.assertEqual(found.intent["themes"][0]["why"], "beast is cast as Dragon")
        self.assertTrue(ideas(found, "space"))
        plain = self.ask("A woman sleeping", randomized="setting", characters=(WOMAN,))
        self.assertEqual(plain.intent["themes"], [], "being human is no theme")

    def test_a_broad_general_request_gets_everyday_ideas_only(self):
        found = self.ask("A woman reading", randomized="activity, props, setting, pose", characters=(WOMAN,))
        self.assertEqual(ideas(found, "action"), ["general:action.hold"])
        self.assertIn("general:item.book", ideas(found, "item"))
        self.assertTrue(ideas(found, "space"))
        self.assertTrue(ideas(found, "posture"))
        self.assertFalse([entry for entry in found.inspiration if entry.pack != "general"], "themed packs need their theme")
        book = next(entry for entry in found.inspiration if entry.id == "general:item.book")
        self.assertEqual(book.attach_to, ["general:action.hold"])

    def test_a_custom_pack_is_treated_like_the_shipped_ones(self):
        self.install("neon", [
            {"id": "neon:space.alley", "category": "space", "name": "Neon alley", "description": "A wet alley under signs.",
             "components": {"environment": {"provides": ["core:surface.ground"]}}},
            {"id": "neon:action.jack_in", "category": "action", "name": "Jack in", "description": "Plugs a cable into a port.",
             "components": {"participants": {"slots": {"user": being()}},
                            "requirements": {"participants": {"user": {"all_of": ["core:limb.hand"]}}}}}],
            description="Cyberpunk: neon cities, hackers and implants.", themes=["cyberpunk"])
        found = self.ask("Cyberpunk street scenes of a woman", randomized="location, activity", characters=(WOMAN,))
        self.assertIn("neon:space.alley", ideas(found, "space"))
        self.assertIn("neon:action.jack_in", ideas(found, "action"))
        plain = self.ask("A woman on a street", randomized="location, activity", characters=(WOMAN,))
        self.assertFalse([entry_id for entry_id in ideas(plain) if entry_id.startswith("neon:")])

    def test_the_content_level_is_the_rating_not_a_pack_or_a_word(self):
        self.manager.set_enabled("adult", False)  # only this custom pack offers adult positions here
        standing = {"participants": {"a": {"posture": "general:posture.standing"}, "b": {"posture": "general:posture.standing"}}}
        self.install("studio", [
            {"id": "studio:position.back_to_back", "category": "position", "name": "Back to back",
             "description": "Backs pressed against each other.",
             "components": {"participants": {"slots": {"a": being(), "b": being()}}, "spatial": standing}},
            {"id": "studio:action.shared_wheel", "category": "action", "name": "Shared wheel",
             "description": "Two people shape one pot on a wheel.",
             "components": {"participants": {"slots": {"a": being(), "b": being()}},
                            "requirements": {"participants": {"a": {"all_of": ["core:limb.hand"]}, "b": {"all_of": ["core:limb.hand"]}}},
                            "claims": {"a": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "contact"}]}}}],
            rating="adult", activation="content", requires={"core": ">=1.0.0", "general": ">=1.0.0"})
        found = self.ask("Two adults together", characters=(WOMAN, MAN), nsfw=True)
        self.assertIn("studio:position.back_to_back", ideas(found, "position"), "an adult-rated arrangement ranks first")
        self.assertNotIn("studio:action.shared_wheel", ideas(found), "an act is never opened by the rating alone")
        asked = self.ask("Two adults together", randomized="activities", characters=(WOMAN, MAN), nsfw=True)
        self.assertIn("studio:action.shared_wheel", ideas(asked, "action"))
        self.assertFalse([entry_id for entry_id in ideas(self.ask("Two adults together", characters=(WOMAN, MAN)))
                          if entry_id.startswith("studio:")], "the rating still decides eligibility")


class Activation(Packs):
    """A pack's manifest activation decides whether the content level alone may offer its ideas (SPEC section 1).

    The rating decides what is allowed; activation decides which allowed packs are offered unasked. Named entries are
    found whatever the activation. Entries here use only generic components, so nothing depends on a pack's id."""

    def install_niche(self, pack_id="niche", **manifest):
        # An opt-in, specialised adult pack that declares no activation: it keeps the conservative default.
        self.install(pack_id, [
            {"id": f"{pack_id}:space.pillory", "category": "space", "name": "Pillory frame",
             "description": "A heavy wooden frame for restraint scenes.",
             "components": {"environment": {"provides": ["core:surface.vertical"]}}}],
            rating="adult", description="Opt-in restraint play: bondage and fetters.", themes=["bondage"], **manifest)

    def offered(self, found, pack_id):
        return [entry.id for entry in found.inspiration if entry.pack == pack_id]

    def test_a_specialised_pack_needs_its_theme_even_when_nsfw_is_on(self):
        self.manager.set_enabled("adult", False)  # the niche place competes only with the core's here
        self.install_niche()
        found = self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=True)
        self.assertEqual(found.intent["content"], "adult")
        self.assertEqual(self.offered(found, "niche"), [], "the content level alone never offers a theme-activated pack")
        self.assertIn({"pack": "niche", "name": "Niche", "state": "inactive", "why": "needs its theme: the content level alone does not offer this pack"},
                      found.intent["activation"])
        self.assertTrue(ideas(found, "space"), "the place still varies")
        themed = self.ask("Bondage scenes of a woman", characters=(WOMAN,), nsfw=True)
        self.assertEqual([theme["pack"] for theme in themed.intent["themes"]], ["niche"])
        self.assertIn("niche:space.pillory", self.offered(themed, "niche"), "its theme still offers it")

    def test_the_general_adult_pack_is_offered_for_the_content_level(self):
        found = self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=True)
        self.assertTrue([entry_id for entry_id in ideas(found, "space") if entry_id.startswith("adult:")],
                        "a content-activated pack offers its places for an open setting")
        self.assertIn({"pack": "adult", "name": "Adult", "state": "content", "why": "the brief asks for adult content"},
                      found.intent["activation"])
        self.assertEqual(found.intent["themes"], [])

    def test_the_core_is_always_available(self):
        self.manager.set_enabled("adult", False)
        self.install_niche()
        for nsfw in (False, True):
            with self.subTest(nsfw=nsfw):
                found = self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=nsfw)
                self.assertTrue(ideas(found, "space"))
                self.assertEqual({entry.pack for entry in found.inspiration}, {"general"})

    def test_a_named_entry_is_found_whatever_its_packs_activation(self):
        self.install_niche()
        found = self.ask("A woman at a pillory frame", characters=(WOMAN,), nsfw=True)
        self.assertEqual(found.intent["themes"], [{"pack": "niche", "name": "Niche", "why": "the brief names Pillory frame", "scope": "entry"}])
        self.assertIn("niche:space.pillory", [entry.id for entry in found.entries])
        sfw = self.ask("A woman at a pillory frame", characters=(WOMAN,))
        self.assertNotIn("niche:space.pillory", [entry.id for entry in sfw.entries], "the rating still decides eligibility")

    def test_a_custom_pack_declares_content_activation_generically(self):
        self.manager.set_enabled("adult", False)
        self.install_niche("plain")
        self.install_niche("broad_content", activation="content")
        found = self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.offered(found, "plain"), [])
        self.assertEqual(self.offered(found, "broad_content"), ["broad_content:space.pillory"])
        self.assertEqual({item["pack"]: item["state"] for item in found.intent["activation"]}, {"broad_content": "content", "plain": "inactive"},
                         "a pack the content level never offered (General-rated Fantasy) is not reported")
        for pack_id in ("plain", "broad_content"):
            self.assertEqual(self.offered(self.ask("A woman teasing her toes", characters=(WOMAN,)), pack_id), [], "SFW: never")

    def test_activation_never_opens_acts_or_items(self):
        self.manager.set_enabled("adult", False)
        self.install("broad_content", [
            {"id": "broad_content:action.strap", "category": "action", "name": "Strapping in", "description": "Buckles a partner in.",
             "components": {"participants": {"slots": {"a": being()}},
                            "requirements": {"participants": {"a": {"all_of": ["core:limb.hand"]}}},
                            "claims": {"a": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "contact"}]}}}],
            rating="adult", activation="content")
        self.assertEqual(ideas(self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=True), "action"), [])

    def test_a_general_theme_pack_is_unaffected(self):
        found = self.ask("A woman teasing her toes", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.offered(found, "fantasy"), [])
        self.assertNotIn("fantasy", {item["pack"] for item in found.intent["activation"] if item["state"] != "inactive"})


class FixedAndRandomized(Packs):

    def test_a_named_position_and_place_fix_the_interaction_and_the_place(self):
        found = self.ask("Two men having sex in missionary on a bed", characters=MEN, nsfw=True)
        named = {entry.id for entry in found.entries}
        self.assertTrue({"adult:position.missionary", "general:space.bed"} <= named)
        registry = self.manager.registry()
        self.assertTrue(all(entry_id in ("general:space.bed", "adult:position.missionary", "adult:action.sex")
                            or "adult:position.missionary" in registry.entry(entry_id).get("extends", []) for entry_id in named), named)
        self.assertEqual(found.intent["fixed"]["space"], ["Bed"])
        self.assertIn("Missionary", found.intent["fixed"]["interaction"])
        for key in ("position", "action", "space"):
            self.assertEqual(ideas(found, key), [], key)
        self.assertIn("fixes the arrangement", category(found, "position")["reason"])
        self.assertTrue(all(not scene["ideas"] for scene in found.scenes(4)))

    def test_a_place_the_vocabulary_does_not_know_is_never_replaced(self):
        found = self.ask("Two men having sex on a train", randomized="sex positions, lighting, camera angle", characters=MEN, nsfw=True)
        self.assertTrue(ideas(found, "position"))
        self.assertEqual(ideas(found, "space"), [])

    def test_what_may_vary_reopens_a_fixed_category(self):
        found = self.ask("A couple kissing", randomized="positions, location")
        self.assertEqual([entry.id for entry in found.entries], ["general:action.kiss"])
        self.assertEqual(ideas(found, "action"), [], "the kiss stays the action")
        self.assertIn("general:position.side_by_side", ideas(found, "position"))
        self.assertTrue(ideas(found, "space"))

    def test_the_train_platform_goodbye_keeps_its_hug_only(self):
        found = self.ask("A woman and a man hugging goodbye on a train platform",
                         randomized="clothing, facial expression, lighting, time of day, weather, train station details, camera angle")
        self.assertEqual([entry.id for entry in found.entries], ["general:action.hug"])
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
        self.assertEqual(ideas(found, "position")[0], "general:position.circle")
        self.assertTrue(any(item["id"] == "general:position.riding" and item.get("source") == "inspiration"
                            and item["reason"].startswith("conflict") for item in found.excluded))

    def test_one_person_is_never_offered_a_two_person_idea(self):
        found = self.ask("A woman posing", randomized="positions, activity", characters=(WOMAN,))
        offered = {entry.id for entry in found.inspiration}
        self.assertFalse(offered & {"general:position.side_by_side", "general:action.hug", "general:action.kiss"})
        self.assertIn("general:position.standing_alone", offered)

    def test_explicit_anatomy_changes_status_and_gender_does_not(self):
        plain = self.ask("Two adults, oral", characters=(WOMAN, MAN), nsfw=True)
        stated = self.ask("Two adults, oral", nsfw=True,
                          characters=(dict(WOMAN, custom="a woman with a penis"), dict(MAN, custom="a man with a penis")))
        status = lambda found: next(entry.status for entry in found.entries if entry.id == "adult:action.oral")
        self.assertEqual(status(plain), "unknown")
        self.assertEqual(status(stated), "eligible")
        self.assertEqual([member["traits"] for member in stated.cast], [["general:trait.penis"]] * 2)


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
        self.assertEqual([entry.id for entry in found.entries], ["general:action.hold"])
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
        self.install("camp", [lit, fire, smoke, warm, pipe, cigar, logs], description="Campsite life: tents, fires and smoke.",
                     themes=["campsite"])
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

class OptionalThemeSetting(Packs):
    """Activation, content ratings and exclusions do not depend on a retired production pack."""

    def install_theme(self):
        files = tiny_pack("workshop", [
            {"id": "workshop:gear.spark", "name": "Sparks", "category": "capability", "components": {"capability": {}}},
            {"id": "workshop:item.torch", "name": "Torch", "category": "item", "tags": ["sparks"],
             "components": {"object": {"provides": ["workshop:gear.spark"]}}},
            {"id": "workshop:action.welding", "name": "Welding", "category": "action", "tags": ["sparks"],
             "components": {"participants": {"slots": {"actor": {"kind": "being", "count": 1},
                                                         "tool": {"kind": "object", "count": 1}}},
                            "requirements": {"participants": {"tool": {"all_of": ["workshop:gear.spark"]}}}}},
            {"id": "workshop:action.polishing", "name": "Polishing", "category": "action", "tags": ["craft"],
             "components": {"participants": {"slots": {"actor": {"kind": "being", "count": 1}}}}},
        ], rating="adult", themes=["metalwork"])
        folder = self.root / "installed/workshop"
        folder.mkdir(parents=True)
        for name, value in files.items():
            (folder / name).write_text(json.dumps(value), encoding="utf-8")

    def themed(self, found):
        return [entry.id for entry in [*found.entries, *found.inspiration] if entry.pack == "workshop"]

    def test_absent_pack_offers_nothing(self):
        self.assertEqual(self.themed(self.ask("Workshop scenes", randomized="acts", characters=MEN, nsfw=True)), [])

    def test_enabled_theme_offers_ideas_and_disabled_theme_does_not(self):
        self.install_theme()
        found = self.ask("Workshop scenes", randomized="acts", characters=MEN, nsfw=True)
        self.assertIn("workshop:action.polishing", self.themed(found))
        self.manager.set_enabled("workshop", False)
        self.assertEqual(self.themed(self.ask("Workshop scenes", randomized="acts", characters=MEN, nsfw=True)), [])

    def test_adult_rating_is_not_bypassed_by_a_theme(self):
        self.install_theme()
        self.assertEqual(self.themed(self.ask("Workshop scenes", randomized="acts", characters=MEN)), [])

    def test_capability_exclusion_removes_dependent_actions_and_items(self):
        self.install_theme()
        found = self.ask("Workshop scenes", randomized="acts, accessories", avoid=("no sparks",), characters=MEN, nsfw=True)
        self.assertNotIn("workshop:action.welding", self.themed(found))
        self.assertNotIn("workshop:item.torch", self.themed(found))
        self.assertIn("workshop:action.polishing", self.themed(found))

    def test_tag_exclusion_does_not_remove_unrelated_actions(self):
        self.install_theme()
        found = self.ask("Workshop scenes", randomized="acts", avoid=("no craft",), characters=MEN, nsfw=True)
        self.assertNotIn("workshop:action.polishing", self.themed(found))
        self.assertIn("workshop:action.welding", self.themed(found))

    def test_declared_theme_and_explicit_entry_names_are_retrievable(self):
        self.install_theme()
        found = self.ask("Metalwork", randomized="acts", characters=MEN, nsfw=True)
        self.assertTrue(self.themed(found))
        self.assertIn("workshop:action.polishing", self.themed(self.ask("Polishing", characters=MEN, nsfw=True)))


class Rotation(Packs):

    def found(self, seed=0, creativity="Balanced"):
        return self.ask("Two adult men having sex.", randomized="sex positions, acts, location", characters=MEN, nsfw=True,
                        seed=seed, creativity=creativity)

    def test_a_dataset_sees_every_idea_spread_over_its_scenes(self):
        found = self.found()
        main = {entry.id for entry in found.inspiration if not entry.attach_to}
        # A long run for the whole eligible pool: every idea keeps a chance, so each comes (the pools are no longer capped).
        by_role = {}
        for entry in found.inspiration:
            if not entry.attach_to:
                by_role.setdefault(entry.role, set()).add(entry.id)
        plan = found.scenes(8 * max(map(len, by_role.values())))
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
        dice = [entry for entry in self.found(creativity="Dice").ideas(1) if not entry.attach_to]
        self.assertEqual(sorted(entry.role for entry in dice), ["arrangement", "interaction", "space"],
                         "four allowed, but one act, one position and one place are all that combine: no filler")

    def test_the_offer_lists_named_entries_once_and_ideas_per_concept(self):
        found = self.ask("A couple kissing", randomized="positions, location", seed=2)
        block, offered = found.offer([3, 4])
        self.assertIn("Named by the request (every image):\n- Kiss", block)
        self.assertIn("- concept 1: ", block)
        self.assertIn("- concept 2: ", block)
        self.assertEqual(offered[0], "general:action.kiss")
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
        self.assertTrue(all(len(ideas) == 1 for ideas in plan), "alternatives of one kind take turns, never share a scene")
        firsts = [ideas[0] for ideas in plan]
        self.assertEqual((firsts.count("p1"), firsts.count("p2")), (15, 15))
        self.assertTrue(all(first != second for first, second in zip(firsts, firsts[1:])))

    def test_one_idea_is_offered_to_every_scene(self):
        found = self.made([("space", [("s1", 1.0)])], per_scene=4)
        self.assertEqual([scene["ideas"] for scene in found.scenes(7)], [["s1"]] * 7)

    def test_categories_each_get_their_turn_and_counts_follow_relevance(self):
        found = self.made([("position", [("p1", 3.0), ("p2", 2.0), ("p3", 1.0)]), ("space", [("s1", 1.0), ("s2", 1.0)])], per_scene=1)
        plan = [scene["ideas"][0] for scene in found.scenes(20)]
        self.assertEqual(sum(entry_id.startswith("p") for entry_id in plan), 10)
        counts = [plan.count(entry_id) for entry_id in ("p1", "p2", "p3")]
        self.assertTrue(all(counts), "every position comes")
        self.assertGreaterEqual(counts[0], counts[2], "the most relevant comes at least as often as the least")

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


def posture(entry_id, name, tags=(), extends=None):
    entry = {"id": entry_id, "category": "posture", "name": name, "description": f"{name}, held by one person.", "tags": list(tags),
             "components": {"requirements": {"participants": {"self": {"all_of": ["core:locomotion.biped"]}}},
                            "spatial": {"participants": {"self": {"orientation": "upright"}}}}}
    if extends:
        entry["extends"] = [extends]
    return entry


def venue(entry_id, name, tags=(), provides=("core:surface.ground",)):
    return {"id": entry_id, "category": "space", "name": name, "description": f"A {name.lower()}.", "tags": list(tags),
            "components": {"environment": {"provides": list(provides)}}}


class ThemeScope(Packs):
    """What a brief asks of a theme-activated pack: the pack as a whole (its name or a declared theme phrase), one
    concept (a tag its entries carry) or one entry (named or cast, with what it explicitly extends or is extended by).
    Only declared metadata counts; a pack description never does. Synthetic packs only."""

    def install_studio(self, **manifest):
        k = "studio"
        self.install(k, [
            {"id": f"{k}:surface.padded", "category": "capability", "name": "Padded surface",
             "components": {"capability": {"implies": ["core:surface"]}}},
            posture(f"{k}:posture.pointed_toes", "Pointed toes pose", ["feet", "kink"]),
            posture(f"{k}:posture.soles_up", "Soles up pose", ["feet", "kink"]),
            posture(f"{k}:posture.toe_curl", "Curled toes pose", ["feet", "kink"]),
            posture(f"{k}:posture.arched_foot", "Arched instep pose", ["feet", "kink"]),
            posture(f"{k}:posture.tied_kneel", "Tied kneel", ["bondage", "kink"]),
            venue(f"{k}:space.rack", "Rack frame", ["bondage", "kink"], ("core:surface.ground", f"{k}:surface.padded")),
            venue(f"{k}:space.lounge", "Velvet lounge", (), ("core:surface.ground", f"{k}:surface.padded")),
            posture(f"{k}:posture.base", "Base stance"),
            posture(f"{k}:posture.lean", "Wall lean", extends=f"{k}:posture.base"),
            posture(f"{k}:posture.lean_low", "Low wall lean", extends=f"{k}:posture.lean"),
            posture(f"{k}:posture.sway", "Hip sway", extends=f"{k}:posture.base"),
            {"id": f"{k}:action.foot_rub", "category": "action", "name": "Foot rub", "description": "One rubs the other's feet.",
             "tags": ["feet"], "components": {"participants": {"slots": {"giver": being(), "receiver": being()}},
                                              "requirements": {"participants": {"giver": {"all_of": ["core:limb.hand"]},
                                                                                "receiver": {"all_of": ["core:limb.foot"]}}},
                                              "claims": {"giver": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive",
                                                                    "purpose": "contact"}]}}}],
            rating="adult", themes=["bondage play"],
            description="Opt-in studio: feet, bondage play, BDSM. Install it for kinks; disable or remove it for none.", **manifest)

    def offered(self, found, pack_id="studio"):
        return sorted(entry.id for entry in found.inspiration if entry.pack == pack_id)

    def scope(self, found, pack_id="studio"):
        return next((theme["scope"] for theme in found.intent["themes"] if theme["pack"] == pack_id), None)

    def test_a_concept_offers_its_entries_and_no_unrelated_places(self):
        self.install_studio()
        feet = {"studio:posture.pointed_toes", "studio:posture.soles_up", "studio:posture.toe_curl", "studio:posture.arched_foot"}
        found = self.ask("woman teasing her feet", randomized="", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.scope(found), "concept")
        self.assertEqual([entry.id for entry in found.entries if entry.pack == "studio"], [], "a tag is a concept, never a name")
        self.assertEqual(found.intent["fixed"], {}, "and never a decided pose or action")
        self.assertTrue(set(self.offered(found)) and set(self.offered(found)) <= feet, "the concept's entries are optional ideas")
        self.assertTrue(ideas(found, "space"))
        varied = self.ask("woman teasing her feet", randomized="pose", characters=(WOMAN,), nsfw=True)
        self.assertTrue(set(self.offered(varied)) <= feet)
        for result in (found, varied):
            self.assertFalse({"studio:space.rack", "studio:space.lounge", "studio:posture.tied_kneel"}
                             & ({entry.id for entry in result.entries} | set(ideas(result))))

    def test_toes_open_nothing_of_a_pack_that_declares_no_such_concept(self):
        self.install_studio()
        found = self.ask("slutty woman teasing her toes", randomized="", characters=(WOMAN,), nsfw=True)
        self.assertIsNone(self.scope(found))
        self.assertEqual(self.offered(found), [])

    def test_a_broad_theme_offers_varied_entries_of_the_pack(self):
        self.install_studio()
        found = self.ask("Bondage play scenes of a woman", randomized="pose, location", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.scope(found), "broad")
        everything = set(self.offered(found)) | {entry.id for entry in found.entries}
        self.assertLessEqual({"studio:space.rack", "studio:space.lounge"}, everything)
        self.assertGreater(len(self.offered(found)), 5)
        by_name = self.ask("Studio scenes of a woman", randomized="pose, location", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.scope(by_name), "broad", "the pack name stays a theme without any declaration")

    def test_a_theme_phrase_matches_in_order_and_never_when_ruled_out(self):
        self.install_studio()
        apart = self.ask("Bondage and rope play with a woman", randomized="location", characters=(WOMAN,), nsfw=True)
        self.assertNotEqual(self.scope(apart), "broad", "separated words are not the phrase")
        self.assertNotIn("studio:space.lounge", self.offered(apart))
        for found in (self.ask("A woman, no bondage play", randomized="location", characters=(WOMAN,), nsfw=True),
                      self.ask("Bondage play scenes of a woman", randomized="location", characters=(WOMAN,), nsfw=True,
                               avoid=("bondage play",))):
            self.assertIsNone(self.scope(found))
            self.assertEqual(self.offered(found), [])

    def test_description_words_never_reach_a_pack(self):
        self.install_studio()
        for request in ("BDSM scenes of a woman", "Install a shelf for a woman", "A woman, disable the alarm"):
            with self.subTest(request=request):
                found = self.ask(request, randomized="location", characters=(WOMAN,), nsfw=True)
                self.assertIsNone(self.scope(found))
                self.assertEqual(self.offered(found), [])

    def test_a_named_entry_brings_only_what_it_explicitly_extends_or_is_extended_by(self):
        self.install_studio()
        found = self.ask("A woman in a wall lean", randomized="pose", characters=(WOMAN,), nsfw=True)
        self.assertIn("studio:posture.lean", [entry.id for entry in found.entries])
        self.assertEqual(self.scope(found), "entry")
        self.assertNotIn("studio:posture.sway", self.offered(found), "a sibling under the same parent is unrelated")
        self.assertFalse(set(self.offered(found)) - {"studio:posture.base", "studio:posture.lean_low"})

    def test_a_shared_capability_relates_nothing(self):
        self.install_studio()
        found = self.ask("A woman at a rack frame", randomized="location", characters=(WOMAN,), nsfw=True)
        self.assertIn("studio:space.rack", [entry.id for entry in found.entries])
        self.assertNotIn("studio:space.lounge", self.offered(found), "both provide a padded surface; that is compatibility")

    def test_a_meaningful_tag_most_entries_share_is_still_a_concept(self):
        self.install_studio()
        found = self.ask("Kink scenes of a woman", randomized="pose, location", characters=(WOMAN,), nsfw=True)
        self.assertEqual(self.scope(found), "concept")
        offered = set(self.offered(found)) | {entry.id for entry in found.entries}
        self.assertIn("studio:space.rack", offered)
        self.assertFalse({"studio:space.lounge", "studio:posture.base", "studio:posture.sway"} & offered, "untagged entries stay out")

    def test_requested_entries_rank_above_general_content_ideas(self):
        self.install_studio()
        found = self.ask("woman teasing her feet", randomized="pose", characters=(WOMAN,), nsfw=True)
        postures = [entry for entry in found.inspiration if entry.category == "posture"]
        studio = [index for index, entry in enumerate(postures) if entry.pack == "studio"]
        self.assertTrue(studio)
        self.assertEqual(studio, list(range(len(studio))), "the asked-for concept is not crowded out by the content level")
        self.assertTrue(any(entry.pack == "adult" for entry in postures), "general ideas still follow")
        unasked = [entry for entry in found.inspiration if entry.pack == "adult"]
        self.assertTrue(all("theme" not in entry.scopes for entry in unasked), "only connected entries get the theme weight")

    def test_fantasy_theme_versus_a_cast_creature(self):
        broad = self.ask("Epic fantasy scenes of a dragon", randomized="pose, setting, lighting", characters=DRAGON)
        self.assertEqual(self.scope(broad, "fantasy"), "broad")
        self.assertEqual(set(ideas(broad, "space")[:3]), {"fantasy:space.great_hall", "fantasy:space.enchanted_woods", "fantasy:space.lair"})
        drake = ({"label": "beast", "gender": "custom", "custom": "a drake", "pronoun": "it"},)
        cast = self.ask("A sleeping beast", randomized="setting", characters=drake)
        self.assertEqual(self.scope(cast, "fantasy"), "entry")
        self.assertEqual(self.offered(cast, "fantasy"), [], "a creature asks for itself, not for every fantasy place")

    def test_unrelated_subthemes_of_one_custom_pack_stay_apart(self):
        self.install_studio()
        feet = self.ask("woman teasing her feet", randomized="pose, location", characters=(WOMAN,), nsfw=True)
        bondage = self.ask("A woman, bondage", randomized="pose, location", characters=(WOMAN,), nsfw=True)
        self.assertNotIn("studio:posture.tied_kneel", self.offered(feet))
        self.assertFalse({"studio:posture.pointed_toes", "studio:posture.soles_up"} & set(self.offered(bondage)))
        self.assertIn("studio:space.rack", set(self.offered(bondage)) | {entry.id for entry in bondage.entries})

    def test_ratings_exclusions_and_compatibility_still_apply(self):
        self.install_studio()
        self.assertEqual(self.offered(self.ask("woman teasing her feet", randomized="", characters=(WOMAN,))), [], "SFW: never")
        ruled = self.ask("woman teasing her feet", randomized="", characters=(WOMAN,), nsfw=True, avoid=("feet",))
        self.assertIsNone(self.scope(ruled))
        self.assertFalse([entry_id for entry_id in ideas(ruled) + [entry.id for entry in ruled.entries] if entry_id.startswith("studio:")])
        solo = self.ask("woman teasing her feet", randomized="acts", characters=(WOMAN,), nsfw=True)
        self.assertNotIn("studio:action.foot_rub", ideas(solo) + [entry.id for entry in solo.entries])
        self.assertTrue(any(item["id"] == "studio:action.foot_rub" and "conflict" in item["reason"] for item in solo.excluded),
                        "a two-person act of the concept is still checked against a cast of one")

    def test_seeds_and_per_image_balance_hold(self):
        self.install_studio()
        ask = lambda seed: self.ask("Bondage play scenes of a woman", randomized="pose, location", characters=(WOMAN,), nsfw=True, seed=seed)
        self.assertEqual(ask(4).scenes(10), ask(4).scenes(10))
        found = ask(4)
        roles = {entry.id: entry.role for entry in found.inspiration}
        for scene in found.scenes(10):
            kinds = [roles[entry_id] for entry_id in scene["ideas"] if entry_id in roles]
            self.assertEqual(len(kinds), len(set(kinds)))


class MatchClasses(Packs):
    """Part C: explicit, contextual, weak and unrelated matches (SPEC section 10). Only explicit matches are named or
    decide anything; contextual ones are optional ideas; weak ones are reported as not used. Synthetic packs only."""

    def install_lounge(self, pack_id="lounge", **manifest):
        k = pack_id
        self.install(k, [
            {"id": f"{k}:music.instrument", "category": "capability", "name": "Instrument",
             "components": {"capability": {"implies": ["core:item"]}}},
            venue(f"{k}:space.play_room", "Play room", ["games"]),
            venue(f"{k}:space.den", "Den", [], ),
            {**venue(f"{k}:space.reading_nook", "Reading nook"), "aliases": ["book corner"]},
            {"id": f"{k}:action.strum", "category": "action", "name": "Strum a song", "description": "Plays chords on an instrument.",
             "components": {"participants": {"slots": {"player": being(), "instrument": {"count": 1, "kind": "object"}}},
                            "requirements": {"participants": {"player": {"all_of": ["core:limb.hand"]},
                                                              "instrument": {"all_of": [f"{k}:music.instrument"]}}},
                            "claims": {"player": [{"resource": "core:limb.hand", "count": 1, "mode": "shared", "purpose": "hold"}]}}},
            {"id": f"{k}:item.guitar", "category": "item", "name": "Old guitar", "description": "A worn acoustic guitar.",
             "components": {"object": {"provides": ["core:item.handheld", f"{k}:music.instrument"], "hands": 1}}},
            {"id": f"{k}:item.banjo", "category": "item", "name": "Banjo",
             "components": {"object": {"provides": ["core:item.handheld", f"{k}:music.instrument"], "hands": 1}}},
            posture(f"{k}:posture.lounging", "Lounging", ["relaxed"]),
            posture(f"{k}:posture.sprawled", "Sprawled out", ["relaxed"])],
            themes=["lounge life"], **manifest)

    def related(self, found):
        return {item["id"]: item["why"] for item in found.intent["related"]}

    def rejected(self, found):
        return {item["id"]: item["why"] for item in found.intent["rejected"]}

    def test_one_word_of_a_longer_name_or_alias_names_nothing(self):
        self.install_lounge()
        found = self.ask("Two men at play in a garden", characters=MEN)
        self.assertNotIn("lounge:space.play_room", [entry.id for entry in found.entries])
        self.assertNotIn("space", found.intent["fixed"], "a weak match never decides the place")
        self.assertEqual(self.rejected(found).get("lounge:space.play_room"), "only one word of a longer name or alias")

    def test_an_exact_multiword_name_or_alias_is_explicit_and_decides(self):
        self.install_lounge()
        found = self.ask("A woman reading in a book corner", characters=(WOMAN,))
        self.assertIn("lounge:space.reading_nook", [entry.id for entry in found.entries], "the alias, in full and in order")
        self.assertEqual(found.intent["fixed"].get("space"), ["Reading nook"])
        for request in ("A woman in a corner with a book", "A woman with a book, a lamp and a corner"):
            apart = self.ask(request, characters=(WOMAN,))
            self.assertNotIn("lounge:space.reading_nook", [entry.id for entry in apart.entries], "reordered or separated: no name")

    def test_a_named_participant_may_sit_inside_a_name(self):
        found = self.ask("A woman sitting on a man's lap", randomized="", characters=(WOMAN, MAN))
        self.assertIn("general:position.lap_sit", [entry.id for entry in found.entries],
                      "the cast's own words stand for the participant in \"Sitting on a lap\"")

    def test_a_requirement_of_a_named_entry_relates_a_weak_object(self):
        self.install_lounge()
        found = self.ask("A man strumming a song on a guitar", randomized="", characters=(MAN,))
        self.assertEqual([entry.id for entry in found.entries if entry.pack == "lounge"], ["lounge:action.strum"])
        self.assertEqual(self.related(found).get("lounge:item.guitar"), "it provides what Strum a song, which the request names, needs")
        self.assertNotIn("item", found.intent["fixed"], "a related object is an idea, never a decided one")
        offered = {entry.id: entry for entry in found.inspiration}
        self.assertIn("lounge:item.guitar", offered)
        self.assertEqual(offered["lounge:item.guitar"].attach_to, ["lounge:action.strum"])
        self.assertNotIn("lounge:item.banjo", offered, "an object that also fits but nothing names stays out")

    def test_a_shared_capability_is_no_relation(self):
        self.install_lounge()
        found = self.ask("A man with a banjo", randomized="", characters=(MAN,))
        self.assertIn("lounge:item.banjo", [entry.id for entry in found.entries])
        self.assertNotIn("lounge:item.guitar", self.related(found), "both provide an instrument; that is compatibility")
        self.assertNotIn("lounge:action.strum", [entry.id for entry in found.entries], "an object is no requested action")

    def test_a_tag_is_a_concept_offered_never_decided(self):
        self.install_lounge()
        found = self.ask("A relaxed woman", randomized="", characters=(WOMAN,))
        self.assertEqual([entry.id for entry in found.entries if entry.pack == "lounge"], [])
        self.assertEqual(found.intent["fixed"], {})
        self.assertLessEqual({"lounge:posture.lounging", "lounge:posture.sprawled"}, set(self.related(found)))
        self.assertTrue({"lounge:posture.lounging", "lounge:posture.sprawled"} & set(ideas(found, "posture")))

    def test_a_body_part_or_concept_never_becomes_a_decided_action(self):
        studio = ThemeScope("test_a_concept_offers_its_entries_and_no_unrelated_places")
        studio.setUp(), self.addCleanup(studio.doCleanups)
        studio.install_studio()
        found = studio.ask("woman teasing her feet", randomized="", characters=(WOMAN,), nsfw=True)
        self.assertEqual(found.intent["fixed"], {})
        self.assertFalse([entry.id for entry in found.entries if entry.pack == "studio"])
        self.assertNotIn("studio:action.foot_rub", ideas(found), "a two-person act stays out for one woman")

    def test_paraphrases_need_declared_words(self):
        self.install_lounge()
        self.assertFalse([entry.id for entry in self.ask("A woman curled up in a cosy library corner", characters=(WOMAN,)).entries
                          if entry.pack == "lounge"], "no declared name, alias or tag says it: nothing is invented")
        self.assertIn("lounge:space.reading_nook",
                      [entry.id for entry in self.ask("A woman in a reading nook", characters=(WOMAN,)).entries])

    def test_negations_and_avoid_block_every_class(self):
        self.install_lounge()
        for found in (self.ask("A woman, not relaxed, in a den", randomized="pose", characters=(WOMAN,)),
                      self.ask("A relaxed woman in a den", randomized="pose", characters=(WOMAN,), avoid=("relaxed",))):
            self.assertFalse({"lounge:posture.lounging", "lounge:posture.sprawled"} & set(self.related(found)))
        ruled = self.ask("A woman in a reading nook", characters=(WOMAN,), avoid=("reading nook",))
        self.assertNotIn("lounge:space.reading_nook", [entry.id for entry in ruled.entries])

    def test_ambiguous_wording_decides_nothing(self):
        self.install_lounge()
        for request in ("A woman with a pet cat in the den of her house", "Children's games in a park"):
            with self.subTest(request=request):
                found = self.ask(request, characters=(WOMAN,))
                self.assertFalse([entry.id for entry in found.entries if entry.pack == "lounge" and entry.id != "lounge:space.den"])
                self.assertNotIn("interaction", found.intent["fixed"])

    def test_two_packs_with_overlapping_names_and_tags_both_take_part(self):
        self.install_lounge("lounge")
        self.install_lounge("parlour")
        named = self.ask("A woman in a reading nook", characters=(WOMAN,))
        self.assertLessEqual({"lounge:space.reading_nook", "parlour:space.reading_nook"},
                             {entry.id for entry in named.entries} | {item["id"] for item in named.suppressed})
        concept = self.ask("A relaxed woman", randomized="", characters=(WOMAN,))
        self.assertEqual({entry_id.split(":")[0] for entry_id in self.related(concept)}, {"lounge", "parlour"})

    def test_an_unrelated_new_pack_changes_nothing_and_a_relevant_one_contributes(self):
        before = self.ask("Two men at play in a garden", characters=MEN, seed=2)
        self.install_lounge()
        after = self.ask("Two men at play in a garden", characters=MEN, seed=2)
        self.assertEqual([entry.id for entry in after.entries], [entry.id for entry in before.entries])
        self.assertEqual(after.scenes(6), before.scenes(6))
        self.assertIn("lounge:action.strum", [entry.id for entry in self.ask("A man strumming a song", characters=(MAN,)).entries])

    def test_contextual_ideas_fill_no_quota(self):
        self.install_lounge()
        found = self.ask("A man strumming a song on a guitar", randomized="", characters=(MAN,), creativity="Dice")
        roles = {entry.id: entry.role for entry in found.inspiration}
        for scene in found.scenes(6):
            kinds = [roles[entry_id] for entry_id in scene["ideas"] if not next(entry for entry in found.inspiration
                                                                                  if entry.id == entry_id).attach_to]
            self.assertEqual(len(kinds), len(set(kinds)))
            self.assertLessEqual(len(scene["ideas"]), 4)


class Phase1Evidence(Packs):
    """Phrase structure, evidence labels and uncertain place guesses (Part C follow-up, Phase 1)."""

    install_lounge = MatchClasses.install_lounge

    def test_a_name_never_skips_a_preposition_or_conjunction_it_does_not_contain(self):
        self.install_lounge()
        for request in ("A woman with a book in the corner", "A woman with a book and a corner seat", "A book or a corner"):
            with self.subTest(request=request):
                found = self.ask(request, characters=(WOMAN,))
                self.assertNotIn("lounge:space.reading_nook", [entry.id for entry in found.entries])
        self.assertIn("lounge:space.reading_nook", [entry.id for entry in self.ask("A woman in her book corner", characters=(WOMAN,)).entries],
                      "an article or possessive between other words is no structure")

    def test_a_name_keeps_its_shape_with_another_preposition_or_a_participant(self):
        for request in ("A woman sitting on a man's lap", "A woman sitting in his lap", "A woman sitting on his lap"):
            with self.subTest(request=request):
                found = self.ask(request, randomized="", characters=(WOMAN, MAN))
                self.assertIn("general:position.lap_sit", [entry.id for entry in found.entries])
        self.assertNotIn("general:position.lap_sit", [entry.id for entry in self.ask("A woman sitting, a lap dog", characters=(WOMAN, MAN)).entries])

    def test_theme_and_tag_phrases_keep_their_shape(self):
        studio = ThemeScope("test_a_concept_offers_its_entries_and_no_unrelated_places")
        studio.setUp(), self.addCleanup(studio.doCleanups)
        studio.install_studio()
        self.assertEqual(studio.scope(studio.ask("Bondage play scenes of a woman", characters=(WOMAN,), nsfw=True)), "broad")
        self.assertNotEqual(studio.scope(studio.ask("Bondage and play scenes of a woman", characters=(WOMAN,), nsfw=True)), "broad")

    def test_evidence_names_the_field_that_matched(self):
        self.install_lounge()
        hold = next(entry for entry in self.ask("A man holding a lantern", characters=(MAN,)).entries if entry.id == "general:action.hold")
        self.assertIn('alias matches "hold" (request)', hold.why, "Hold an object is named by its one-word alias, from \"holding\"")
        nook = next(entry for entry in self.ask("A woman in a book corner", characters=(WOMAN,)).entries if entry.id == "lounge:space.reading_nook")
        self.assertTrue(any(reason.startswith('alias "book corner" in the request') for reason in nook.why), nook.why)
        relaxed = self.ask("A relaxed woman", randomized="pose", characters=(WOMAN,))
        lounging = next(entry for entry in relaxed.inspiration if entry.id == "lounge:posture.lounging")
        self.assertTrue(any("concept" in reason for reason in lounging.why), lounging.why)
        self.assertFalse([reason for entry in [*relaxed.entries, *relaxed.inspiration] for reason in entry.why
                          if reason.startswith("name matches") and "relax" in reason], "a tag is never reported as a name")

    def test_a_guessed_place_is_uncertain_never_decided(self):
        for request in ("Two men at play in a garden", "A couple in love", "A woman in a hurry"):
            with self.subTest(request=request):
                found = self.ask(request, characters=MEN)
                self.assertNotIn("place", found.intent["fixed"])
                self.assertTrue(found.intent["uncertain"].get("place"))
                space = category(found, "space")
                if space["state"] == "closed":
                    self.assertIn("uncertain text guess", space["reason"])
        known = self.ask("Two men on a bed", characters=MEN)
        self.assertEqual(known.intent["fixed"].get("space"), ["Bed"], "a place the vocabulary names is decided")
        self.assertEqual(known.intent["uncertain"], {})


class SelectedPacks(Packs):
    """Phase 2: only a run's (or the Inspector's) selected packs, their dependencies and the core take part."""

    def inspect(self, request, packs=None, recorded=None, **sample):
        from goated_prompter.features.vocabulary.explorer import inspect_retrieval
        sample = {"nsfw": False, "characters": [], "randomized": "", "avoid": [], "seed": 3, "scenes": 6, **sample}
        return inspect_retrieval(self.manager, request, packs=packs, recorded=recorded, **sample)

    def packs_of(self, result):
        return {item["pack"] for item in result["inspiration"]} | {item["pack"] for item in result["entries"]}

    def test_an_unselected_pack_never_takes_part(self):
        dragon = dict(characters=["a dragon"], randomized="pose, setting")
        self.assertNotIn("fantasy", self.packs_of(self.inspect("Epic fantasy scenes of a dragon", packs=[], **dragon)))
        self.assertIn("fantasy", self.packs_of(self.inspect("Epic fantasy scenes of a dragon", packs=["fantasy"], **dragon)))
        adult = dict(nsfw=True, characters=["adult man", "adult man"], randomized="sex positions, location")
        self.assertEqual(self.packs_of(self.inspect("Two adult men having sex", packs=[], **adult)) - {"core"}, set(),
                         "NSFW allows the rating; only selection brings the pack")
        self.assertIn("adult", self.packs_of(self.inspect("Two adult men having sex", packs=["adult"], **adult)))

    def test_a_custom_pack_takes_part_only_when_selected_even_if_disabled_globally(self):
        self.install("neon", [venue("neon:space.alley", "Neon alley")], themes=["cyberpunk"])
        sample = dict(characters=["a woman"], randomized="location")
        self.manager.set_enabled("neon", False)
        self.assertIn("neon", self.packs_of(self.inspect("Cyberpunk scenes of a woman", packs=["neon"], **sample)))
        self.assertNotIn("neon", self.packs_of(self.inspect("Cyberpunk scenes of a woman", packs=[], **sample)))
        self.assertNotIn("neon", {owner for owner in (self.manager.registry().owner(entry_id) for entry_id in self.manager.registry().ids())},
                         "the global selection is unchanged")

    def test_selections_are_deterministic_and_isolated(self):
        sample = dict(characters=["a woman"], randomized="activity, props, location, pose")
        core_only = self.inspect("A woman reading", packs=[], **sample)
        self.assertEqual(core_only, self.inspect("A woman reading", packs=[], **sample))
        self.assertEqual(core_only["entries"], [])
        self.assertEqual(core_only["inspiration"], [])
        general_only = self.inspect("A woman reading", packs=["general"], **sample)
        with_fantasy = self.inspect("A woman reading", packs=["fantasy"], **sample)
        strip = lambda result: {key: value for key, value in result.items() if key not in ("selection",)}
        self.assertEqual(strip(with_fantasy)["entries"], strip(general_only)["entries"])
        self.assertEqual([item["id"] for item in with_fantasy["inspiration"]], [item["id"] for item in general_only["inspiration"]],
                         "an unreached pack changes nothing beyond its selected content dependencies")
        self.assertEqual(with_fantasy["scenes"], general_only["scenes"])

    def test_a_recorded_selection_is_inspected_exactly_or_refused(self):
        from goated_prompter.features.vocabulary.packs import PackDrift
        self.install("neon", [venue("neon:space.alley", "Neon alley")], themes=["cyberpunk"])
        sample = dict(characters=["a woman"], randomized="location")
        selection = self.manager.resolve_selection(["neon"])
        recorded = self.inspect("Cyberpunk scenes of a woman", recorded=selection, **sample)
        self.assertEqual(recorded, self.inspect("Cyberpunk scenes of a woman", packs=["neon"], **sample))
        self.assertEqual(recorded["selection"], selection)
        entries = self.root / "installed" / "neon" / "entries.json"
        entries.write_text(entries.read_text(encoding="utf-8").replace("Neon alley", "Neon arcade"), encoding="utf-8")
        with self.assertRaises(PackDrift):
            self.inspect("Cyberpunk scenes of a woman", recorded=selection, **sample)


class PackIsolation(Packs):
    """Installing or enabling a pack the request does not ask for changes nothing it retrieves or offers.

    Each entry is scored against its own pack and the packs it requires; a category's description words are
    distinctive against the categories of its own pack and the packs it requires; a capability's commonness is
    counted among the two entries' packs and their requirements. So an unrelated pack's words, categories and
    capabilities cannot shift existing scores, reaches or links."""

    REQUESTS = [("A woman reading", dict(randomized="activity, props, location, pose", characters=(WOMAN,))),
                ("A couple kissing", dict(randomized="positions, location")),
                ("A woman reading a book on a sofa", dict(randomized="lighting", characters=(WOMAN,))),
                ("Two adult men having sex.", dict(randomized="sex positions, acts, location", characters=MEN, nsfw=True)),
                ("Epic fantasy scenes of a dragon", dict(randomized="pose, setting", characters=DRAGON)),
                ("A wizard holding a magic staff", dict(randomized="props", characters=(MAN,))),
                ("slutty woman teasing her toes", dict(randomized="", characters=(WOMAN,), nsfw=True))]

    def snapshot(self, packs=None, requests=None):
        out = []
        for text, options in requests or self.REQUESTS:
            for seed in (0, 3, 7):
                found = self.ask(text, seed=seed, **options)
                keep = lambda entry: packs is None or entry.pack in packs
                out.append({"entries": [(entry.id, entry.status, round(entry.score, 9), round(entry.relevance, 9))
                                        for entry in found.entries if keep(entry)],
                            "ideas": [(entry.id, entry.status, round(entry.score, 9), tuple(entry.scopes))
                                      for entry in found.inspiration if keep(entry)],
                            "excluded": sorted(item["id"] for item in found.excluded),
                            "reached": {item["id"]: [reach["scope"] for reach in item["reached"]] for item in found.intent["categories"]
                                        if packs is None or item["reached"]},
                            "themes": found.intent["themes"],
                            # A pack the content level would offer but which needs its theme is reported, never offered.
                            "activation": [item for item in found.intent["activation"] if item["state"] != "inactive"],
                            "fixed": found.intent["fixed"], "scenes": found.scenes(8)})
        return out

    def nautical(self, category_description="Boats and ships."):
        self.install("nautical", [
            venue("nautical:space.deck", "Ship deck", ["outdoor", "place"]),
            {**venue("nautical:vessel.lifeboat", "Lifeboat", ["outdoor"]), "category": "vessel",
             "description": "A small boat among other places, settings and locations."},
            posture("nautical:posture.sea_legs", "Sea legs stance", ["outdoor"])],
            categories=[{"id": "vessel", "name": "Vessels", "description": category_description}], rating="adult",
            description="Nautical life: reading the sea, woman and man aboard, kissing the shore.", themes=["nautical"])

    def assertUnchanged(self, before, after):
        for (text, _), index in zip([(text, seed) for text, _ in self.REQUESTS for seed in (0, 3, 7)], range(len(before))):
            with self.subTest(request=text, index=index):
                self.assertEqual({key: value for key, value in after[index].items() if key != "reached"},
                                 {key: value for key, value in before[index].items() if key != "reached"})
                self.assertEqual({key: scopes for key, scopes in after[index]["reached"].items() if key in before[index]["reached"]},
                                 before[index]["reached"], "an existing category is reached exactly as before")

    def test_an_unrelated_pack_changes_no_result_and_disabling_it_restores_them(self):
        before = self.snapshot()
        self.nautical()  # reuses the space category, shares tags, descriptions and a core capability
        self.assertUnchanged(before, self.snapshot())
        self.manager.set_enabled("nautical", False)
        self.assertEqual(self.snapshot(), before)

    def test_an_overlapping_category_description_suppresses_no_existing_category(self):
        before = self.snapshot()
        self.nautical("Boats, ships and other places, settings and locations.")
        self.assertUnchanged(before, self.snapshot())
        found = self.ask("A woman in different locations", randomized="lighting", characters=(WOMAN,))
        self.assertEqual(category(found, "space")["reached"][0]["scope"], "category", '"locations" still opens the places')
        self.assertFalse(category(found, "vessel")["reached"],
                         "the new category's wording is not distinctive against the core it requires")

    def test_overlapping_words_shift_no_existing_score_or_order(self):
        old = {"general", "adult", "fantasy"}
        before = self.snapshot(packs=old)
        words = "woman man reading book sofa kissing bed sex position location pose couple adult two lighting wizard staff magic"
        self.install("cabins", [{**venue(f"cabins:space.cabin{n}", f"Cabin {n}"), "description": " ".join(words.split()[n:n + 4])}
                                for n in range(14)], themes=["cabins"])
        after = self.snapshot(packs=old)
        for b, a in zip(before, after):
            for key in ("entries", "ideas"):
                kept = [item for item in b[key] if item[0] in {other[0] for other in a[key]}]
                self.assertEqual([item for item in a[key] if item[0] in {other[0] for other in kept}], kept,
                                 "an existing entry keeps its exact score and its order among the existing entries")

    def test_a_shared_capability_cuts_no_existing_link(self):
        before = self.snapshot()
        self.install("charms", [{"id": f"charms:item.charm{n}", "category": "item", "name": f"Lucky trinket {n}",
                                 "description": "A pocket trinket.",
                                 "components": {"object": {"provides": ["core:item.handheld", "fantasy:magic.focus"]}}} for n in range(6)],
                     requires={"core": ">=1.0.0", "fantasy": ">=0.1.0"}, themes=["charms"])
        self.assertUnchanged(before, self.snapshot())
        staff = self.ask("A wizard holding a magic staff", randomized="props", characters=(MAN,))
        self.assertEqual([entry.id for entry in staff.entries], ["fantasy:item.staff", "general:action.hold"])
        self.assertIn({"id": "fantasy:action.cast_spell", "why": "only related to the request through shared capabilities or links"},
                      staff.intent["rejected"], "a shared capability is reported, never a requested action")

    def test_a_matching_request_may_change(self):
        self.nautical()
        found = self.ask("Nautical scenes of a woman", randomized="location", characters=(WOMAN,), nsfw=True)
        self.assertTrue([entry.id for entry in found.inspiration if entry.pack == "nautical"])

    def test_two_relevant_packs_both_contribute(self):
        self.nautical()
        self.install("harbour", [venue("harbour:space.quay", "Stone quay"), venue("harbour:space.fish_market", "Fish market")],
                     rating="adult", themes=["harbour"])
        for seed in (0, 3, 7):
            found = self.ask("Nautical and harbour scenes of a woman", randomized="location", characters=(WOMAN,), nsfw=True, seed=seed)
            packs = {entry.pack for entry in found.inspiration if entry.role == "space"}
            self.assertLessEqual({"nautical", "harbour"}, packs, "neither relevant pack is arbitrarily excluded")
            self.assertEqual(found.scenes(6), self.ask("Nautical and harbour scenes of a woman", randomized="location",
                                                       characters=(WOMAN,), nsfw=True, seed=seed).scenes(6))


class Balance(Packs):
    """One image gets a coherent set of ideas: at most one per role (interaction, arrangement, place), resolved from
    components, never from a category name; asked-for roles first, the open place last, and no filler."""

    def roles(self, found, scene):
        by_id = {entry.id: entry for entry in found.inspiration}
        return [by_id[entry_id].role for entry_id in scene["ideas"] if not by_id[entry_id].attach_to]

    def assertBalanced(self, found, count=12):
        offered = {entry.id for entry in found.inspiration}
        for scene in found.scenes(count):
            roles = self.roles(found, scene)
            self.assertEqual(len(roles), len(set(roles)), f"one idea per role: {scene}")
            self.assertLessEqual(len(roles), found.per_scene)
            self.assertLessEqual(set(scene["ideas"]), offered, "balancing only chooses among checked ideas")
            if "space" in roles:
                self.assertEqual(roles[-1], "space", "the place comes last")

    def test_the_toes_request_gets_one_pose_and_at_most_one_place_per_image(self):
        for seed in range(8):
            with self.subTest(seed=seed):
                found = self.ask("slutty woman teasing her toes", randomized="", characters=(WOMAN,), nsfw=True, seed=seed)
                self.assertBalanced(found)
                for scene in found.scenes(10):
                    roles = self.roles(found, scene)
                    self.assertEqual(roles.count("space"), 1 if "space" in roles else 0)
                    self.assertEqual(roles[0], "arrangement", "the pose first, then one optional place")
        first = self.ask("slutty woman teasing her toes", randomized="", characters=(WOMAN,), nsfw=True, seed=0).scenes(10)
        places = [entry_id for scene in first for entry_id in scene["ideas"] if ":space." in entry_id]
        self.assertGreater(len(set(places)), 3, "places still vary across images")

    def test_at_most_one_place_per_image_whatever_the_creativity_and_seed(self):
        for creativity in ("Strict", "Balanced", "Creative", "Dice"):
            for seed in range(4):
                with self.subTest(creativity=creativity, seed=seed):
                    found = self.ask("Two adult men having sex.", randomized="sex positions, acts, location, places", characters=MEN,
                                     nsfw=True, seed=seed, creativity=creativity)
                    self.assertBalanced(found, 16)

    def test_places_from_several_packs_and_categories_count_as_one_role(self):
        def place(pack_id, key, name):
            return {"id": f"{pack_id}:{key}.{name.lower().replace(' ', '_')}", "category": key, "name": name,
                    "description": f"A {name.lower()}.", "components": {"environment": {"provides": ["core:surface.ground"]}}}
        self.install("nightlife", [place("nightlife", "venue", "Neon bar"), place("nightlife", "venue", "Rooftop club")],
                     categories=[{"id": "venue", "name": "Venues", "description": "Bars, clubs and venues."}])
        self.install("wilds", [place("wilds", "biome", "Salt flat"), place("wilds", "biome", "Fern gully")],
                     categories=[{"id": "biome", "name": "Biomes", "description": "Natural biomes."}])
        found = self.ask("Nightlife and wilds portraits of a woman", randomized="venues, biomes, location", characters=(WOMAN,), seed=1)
        categories = {entry.category for entry in found.inspiration if entry.role == "space"}
        self.assertLessEqual({"venue", "biome"}, categories, "custom categories resolve to places by their components")
        self.assertBalanced(found, 24)
        seen = {entry_id.split(":")[0] for scene in found.scenes(24) for entry_id in scene["ideas"] if entry_id.split(":")[1].startswith(("venue", "biome", "space"))}
        self.assertLessEqual({"nightlife", "wilds"}, seen, "the place rotation walks through every pack's places")

    def test_an_interaction_a_pose_and_a_place_combine(self):
        found = self.ask("Two adult men having sex.", randomized="sex positions, acts, location", characters=MEN, nsfw=True, seed=3)
        for scene in found.scenes(8):
            self.assertEqual(self.roles(found, scene), ["interaction", "arrangement", "space"])

    def test_named_entries_and_fixed_places_are_kept(self):
        kiss = self.ask("A couple kissing", randomized="positions, location", seed=2)
        self.assertEqual([entry.id for entry in kiss.entries], ["general:action.kiss"])
        for scene in kiss.scenes(6):
            self.assertEqual(scene["entries"], ["general:action.kiss"], "the named entry is offered to every image")
            self.assertNotIn("interaction", self.roles(kiss, scene))
        block, offered = kiss.offer([1, 2])
        self.assertEqual(offered[0], "general:action.kiss")
        bed = self.ask("Two men having sex on a bed", randomized="lighting", characters=MEN, nsfw=True)
        self.assertIn("general:space.bed", [entry.id for entry in bed.entries])
        for request in ("Two men having sex on a bed", "Two men having sex on a train"):
            found = self.ask(request, randomized="lighting", characters=MEN, nsfw=True)
            self.assertFalse([role for scene in found.scenes(6) for role in self.roles(found, scene) if role == "space"],
                             "a place the request fixes is never varied")

    def test_a_randomized_place_is_asked_for_and_comes_even_at_strict(self):
        found = self.ask("A woman reading", randomized="location", characters=(WOMAN,), creativity="Strict", seed=4)
        for scene in found.scenes(8):
            self.assertIn("space", self.roles(found, scene))
        self.assertBalanced(found, 8)

    def test_core_only_fantasy_and_custom_packs_are_balanced_alike(self):
        self.manager.set_enabled("adult", False)
        self.assertBalanced(self.ask("A woman reading", randomized="activity, props, setting, pose", characters=(WOMAN,)))
        self.assertBalanced(self.ask("Epic fantasy scenes of a dragon", randomized="pose, setting, lighting", characters=DRAGON))
        self.install("neon", [
            {"id": "neon:space.alley", "category": "space", "name": "Neon alley", "description": "A wet alley under signs.",
             "components": {"environment": {"provides": ["core:surface.ground"]}}},
            {"id": "neon:space.arcade", "category": "space", "name": "Neon arcade", "description": "Rows of glowing cabinets.",
             "components": {"environment": {"provides": ["core:surface.ground"]}}}],
            description="Cyberpunk: neon cities, hackers and implants.", themes=["cyberpunk"])
        self.assertBalanced(self.ask("Cyberpunk street scenes of a woman", randomized="location, activity", characters=(WOMAN,)))

    def test_fewer_ideas_than_the_quota_when_fewer_roles_are_open(self):
        found = self.ask("A woman reading", randomized="location", characters=(WOMAN,), creativity="Dice")
        for scene in found.scenes(6):
            self.assertLessEqual(len(self.roles(found, scene)), 2, "a pose and a place; four are allowed but nothing fills")

    def test_seeds_reproduce_and_images_vary(self):
        ask = lambda seed: self.ask("Two adult men having sex.", randomized="sex positions, acts, location", characters=MEN,
                                    nsfw=True, seed=seed)
        self.assertEqual(ask(5).scenes(12), ask(5).scenes(12))
        self.assertTrue(any(ask(5).scenes(12) != ask(other).scenes(12) for other in (6, 7, 8)))
        plan = ask(5).scenes(12)
        self.assertTrue(all(first["ideas"] != second["ideas"] for first, second in zip(plan, plan[1:])))

    def test_exclusions_and_compatibility_still_decide_the_pool(self):
        found = self.ask("Two adults having sex", randomized="sex positions, acts, toys and accessories", avoid=("no toys",),
                         characters=(WOMAN, MAN), nsfw=True)
        excluded = {item["id"] for item in found.excluded}
        for scene in found.scenes(12):
            self.assertFalse(set(scene["ideas"]) & excluded)
        solo = self.ask("A woman posing alone", randomized="location", characters=(WOMAN,))
        offered = [entry for entry in solo.inspiration]
        self.assertFalse([entry.id for entry in offered if entry.role == "interaction"], "no two-person act for one person")


class FullPool(Packs):
    """The whole eligible pool is offered across a dataset: no top-N, complete weighted cycles, reproducible images."""

    REQUEST = ("Two adult men having sex.", dict(randomized="sex positions, acts, location", characters=MEN, nsfw=True))

    def found(self, seed=0, **options):
        text, base = self.REQUEST
        return self.ask(text, seed=seed, **{**base, **options})

    @staticmethod
    def picks(found, count, role):
        by_id = {entry.id: entry for entry in found.inspiration}
        return [entry_id for scene in found.scenes(count) for entry_id in scene["ideas"] if by_id[entry_id].role == role]

    def test_every_eligible_position_is_in_the_pool_and_ranks_below_twelve_are_offered(self):
        found = self.found()
        positions = [entry for category, pool in found.pools for entry in pool if entry.role == "arrangement"]
        self.assertGreaterEqual(len(positions), 30, "30+ eligible positions, not a pool of 12")
        self.assertFalse([item for item in found.suppressed if "beyond" in item["because"]], "no count limit suppresses ideas")
        self.assertEqual(found.stats["eligible"][positions[0].category], len(positions))
        # Renaming content ids changes seeded draws. Test reachability across seeds, not a complete fixed-length cycle.
        offered = {entry_id for seed in range(4) for entry_id in self.picks(self.found(seed), 100, "arrangement")}
        lower = [entry.id for entry in positions[12:]]
        self.assertTrue(lower)
        self.assertFalse(set(lower) - offered, "entries ranked below the old top 12 are offered")

    def test_more_images_explore_more_and_a_rested_idea_does_not_repeat_early(self):
        found = self.found()
        positions = [entry for _, pool in found.pools for entry in pool if entry.role == "arrangement"]
        size = len(positions)
        distinct = {count: len(set(self.picks(found, count, "arrangement"))) for count in (5, 30, 100)}
        self.assertLess(distinct[5], distinct[30])
        self.assertLess(distinct[30], distinct[100])
        self.assertGreater(distinct[100], 0.8 * size, "100 images reach most of the pool")
        sequence = self.picks(found, 100, "arrangement")
        rest = max(1, int(found.cooldown * (size - 1)))
        for index, entry_id in enumerate(sequence):
            self.assertNotIn(entry_id, sequence[max(0, index - rest):index], f"{entry_id} came back within its rest of {rest}")

    def test_ideas_the_old_floor_dropped_are_offered_less_often_but_offered(self):
        found = self.found()
        plan = found.scenes(100)
        offered = [entry_id for scene in plan for entry_id in scene["ideas"]]
        for entry_id in ("general:space.bed", "general:action.kiss"):
            self.assertIn(entry_id, {entry.id for entry in found.inspiration}, f"{entry_id} is eligible again")
        places = [entry for _, pool in found.pools for entry in pool if entry.role == "space"]
        core = [entry.id for entry in places if entry.pack == "general"]
        adult = [entry.id for entry in places if entry.pack == "adult"]
        self.assertTrue(set(core) & set(offered), "core places come")
        per = lambda group: sum(offered.count(entry_id) for entry_id in group) / len(group)
        self.assertGreater(per(adult), per(core), "the better-matched adult places come more often each")

    def test_seeds_explore_different_parts_of_the_pool(self):
        firsts = [set(self.picks(self.found(seed=seed), 5, "arrangement")) for seed in range(8)]
        self.assertGreater(len(set().union(*firsts)), 12, "eight 5-image runs together see more than an old pool")
        self.assertGreater(len({frozenset(first) for first in firsts}), 4)

    def test_an_image_gets_the_same_ideas_however_it_is_asked_for(self):
        full = self.found(seed=4).scenes(100)
        alone = self.found(seed=4)
        self.assertEqual([entry.id for entry in alone.ideas(20)], full[19]["ideas"], "image 20 alone equals image 20 of 1-100")
        forward, backward = self.found(seed=4), self.found(seed=4)
        blocks = {number: forward.offer([number]) for number in (1, 2, 3, 5, 8, 13)}
        self.assertEqual({number: backward.offer([number]) for number in (13, 8, 5, 3, 2, 1)}, blocks, "offer order changes nothing")
        survivors = self.found(seed=4)
        for number in (1, 2, 4, 5):  # image 3 failed: later images keep their own ideas
            self.assertEqual(survivors.ideas(number), forward.ideas(number))
        self.assertEqual([entry.id for entry in survivors.ideas(5)], full[4]["ideas"])

    def test_places_and_items_are_only_offered_with_what_they_fit(self):
        found = self.ask("Two adults having sex", randomized="sex positions, acts, toys and accessories, location",
                         characters=(WOMAN, MAN), nsfw=True, seed=1)
        pairing = found.pairing
        by_id = {entry.id: entry for entry in found.inspiration}
        named = [entry.id for entry in found.entries]
        seen_items = 0
        for scene in found.scenes(60):
            context = [*named, *(entry_id for entry_id in scene["ideas"] if by_id[entry_id].role in ("interaction", "arrangement"))]
            for entry_id in scene["ideas"]:
                entry = by_id[entry_id]
                if entry.role == "space":
                    self.assertTrue(pairing.space(entry_id, context), f"{entry_id} conflicts in {scene}")
                if entry.attach_to:
                    seen_items += 1
                    partners = [partner for partner in context if partner in entry.attach_to]
                    self.assertTrue(any(pairing.item(entry_id, partner) for partner in partners), f"{entry_id} serves nothing in {scene}")
        self.assertTrue(seen_items, "items still come along with what they serve")

    def test_avoid_and_exclusions_hold_over_the_whole_pool(self):
        found = self.ask("Two adults having sex", randomized="sex positions, acts, toys and accessories", avoid=("no toys",),
                         characters=(WOMAN, MAN), nsfw=True)
        excluded = {item["id"] for item in found.excluded}
        offered = {entry_id for scene in found.scenes(100) for entry_id in scene["ideas"]}
        self.assertFalse(offered & excluded, "nothing the request rules out comes back over 100 images")
        self.assertTrue([entry_id for entry_id in excluded if ":item." in entry_id], "the toys are ruled out, not merely unpicked")

    def test_an_unrelated_large_pack_changes_no_offer(self):
        before = self.found(seed=2).scenes(30)
        self.install("harbour", [{"id": f"harbour:space.pier_{number}", "category": "space", "name": f"Pier {number}",
                                  "description": "A wooden pier over the water.",
                                  "components": {"environment": {"provides": ["core:surface.ground"]}}} for number in range(300)],
                     description="Harbours, piers and boats.", themes=["harbour"])
        self.assertEqual(self.found(seed=2).scenes(30), before)


class WeightedCycles(unittest.TestCase):
    """The order of a cycle on hand-made pools: weighted random without replacement, and fitting checks."""

    @staticmethod
    def made(pools, per_scene=3, seed=0, sharpness=1.0, pairing=None):
        from goated_prompter.features.vocabulary.retrieval import Retrieval, RetrievedEntry
        built = [(key, [RetrievedEntry(id=entry_id, name=entry_id, category=key, pack="test", rating="general", description="",
                                       status="eligible", relevance=1.0, score=score, why=[], source="inspiration",
                                       scopes=["category"], role=role) for entry_id, role, score in items]) for key, items in pools]
        return Retrieval([], [], [], [], [], RetrievalConfig(), pools=built, seed=seed, per_scene=per_scene,
                         sharpness=sharpness, pairing=pairing)

    def test_higher_scores_come_first_more_often_but_every_entry_can(self):
        pool = [("position", [(f"high{n}", "arrangement", 3.0) for n in range(10)] + [(f"low{n}", "arrangement", 1.0) for n in range(10)])]
        firsts = [self.made(pool, per_scene=1, seed=seed, sharpness=2.0).ideas(1)[0].id for seed in range(3000)]
        high = sum(entry_id.startswith("high") for entry_id in firsts) / len(firsts)
        self.assertGreater(high, 0.85, "expected 0.9 (weights 9 and 1), uniform would be 0.5")
        self.assertLess(high, 0.95)
        self.assertEqual(len(set(firsts)), 20, "every entry, low ones included, comes first for some seed")
        uniform = [self.made(pool, per_scene=1, seed=seed, sharpness=0.0).ideas(1)[0].id for seed in range(3000)]
        self.assertAlmostEqual(sum(entry_id.startswith("high") for entry_id in uniform) / 3000, 0.5, delta=0.05)

    def test_long_runs_offer_relevant_ideas_more_often_and_every_idea_some_time(self):
        pool = [("position", [(f"high{n}", "arrangement", 3.0) for n in range(10)] + [(f"mid{n}", "arrangement", 2.0) for n in range(15)]
                 + [(f"low{n}", "arrangement", 1.0) for n in range(15)])]
        per = {"high": [], "mid": [], "low": []}
        for seed in range(6):
            plan = [scene["ideas"][0] for scene in self.made(pool, per_scene=1, seed=seed, sharpness=2.0).scenes(600)]
            for tier in per:
                per[tier].append(sum(entry_id.startswith(tier) for entry_id in plan) / {"high": 10, "mid": 15, "low": 15}[tier])
            self.assertEqual(len(set(plan)), 40, "every eligible idea, the least relevant included, comes in a long run")
        mean = {tier: sum(values) / len(values) for tier, values in per.items()}
        self.assertGreater(mean["high"], 1.2 * mean["mid"], mean)
        self.assertGreater(mean["mid"], 1.2 * mean["low"], mean)
        self.assertLess(mean["high"], 600 / (int(0.5 * 39) + 1) + 1, "a rested idea cannot exceed its cap")

    def test_cooldown_is_per_category_and_small_pools_never_go_empty(self):
        pools = [("one", [("solo", "space", 1.0)]), ("two", [("a", "space", 1.0), ("b", "space", 1.0)]),
                 ("five", [(f"f{n}", "space", 1.0) for n in range(5)]), ("forty", [(f"x{n}", "space", 1.0) for n in range(40)])]
        for seed in range(4):
            found = self.made(pools, per_scene=1, seed=seed)
            plan = [scene["ideas"][0] for scene in found.scenes(120)]
            self.assertTrue(all(first != second for first, second in zip(plan, plan[1:])), "no consecutive repeat while another fits")
            for entry_id in ("solo", "a", "b", "f0", "x0"):
                self.assertIn(entry_id, plan)
            for small, rest in (("a", 1), ("f0", 2)):  # rests come from the entry's own category, not the role's 48
                indexes = [index for index, entry_id in enumerate(plan) if entry_id == small]
                self.assertTrue(all(later - earlier > rest for earlier, later in zip(indexes, indexes[1:])))
        alone = self.made([("one", [("solo", "space", 1.0)])], per_scene=1)
        self.assertEqual([scene["ideas"] for scene in alone.scenes(5)], [["solo"]] * 5, "a single compatible entry repeats")
        pair = self.made([("two", [("a", "space", 2.0), ("b", "space", 1.0)])], per_scene=1)
        plan = [scene["ideas"][0] for scene in pair.scenes(10)]
        self.assertTrue(all(first != second for first, second in zip(plan, plan[1:])), "two compatible entries alternate")

    def test_an_exhausted_cooldown_never_empties_a_scene(self):
        class Pairing:  # only one place fits p_dry; it must still come every time p_dry does, rested or not
            def space(self, space_id, context):
                return space_id == "s_only" or "p_dry" not in context

            def item(self, item_id, partner):
                return True
        pools = [("position", [("p_dry", "arrangement", 1.0)]),
                 ("space", [("s_only", "space", 1.0), *((f"s{n}", "space", 1.0) for n in range(6))])]
        plan = [scene["ideas"] for scene in self.made(pools, per_scene=2, pairing=Pairing()).scenes(8)]
        self.assertEqual(plan, [["p_dry", "s_only"]] * 8)

    def test_old_floor_excluded_ideas_are_selectable(self):
        pool = [("space", [("best", "space", 2.0), ("plain1", "space", 1.0), ("plain2", "space", 1.0), ("plain3", "space", 1.0)])]
        found = self.made(pool, per_scene=1, sharpness=2.0)
        offered = {scene["ideas"][0] for scene in found.scenes(30)}
        self.assertLessEqual({"plain1", "plain2", "plain3"}, offered, "half the best score is no longer below any floor")

    def test_a_place_that_does_not_fit_is_skipped_and_keeps_its_turn(self):
        class Pairing:
            def space(self, space_id, context):
                return not (space_id == "s_wet" and "p_dry" in context)

            def item(self, item_id, partner):
                return True
        pools = [("position", [("p_dry", "arrangement", 5.0), ("p_any", "arrangement", 1.0)]),
                 ("space", [("s_wet", "space", 5.0), ("s_a", "space", 1.0), ("s_b", "space", 1.0)])]
        for seed in range(6):
            plan = [scene["ideas"] for scene in self.made(pools, per_scene=2, seed=seed, pairing=Pairing()).scenes(12)]
            self.assertFalse([ideas for ideas in plan if {"p_dry", "s_wet"} <= set(ideas)], "never an invalid pairing")
            places = [entry_id for ideas in plan for entry_id in ideas if entry_id.startswith("s_")]
            self.assertIn("s_wet", places, "its turn waits for a scene it fits")
            self.assertEqual(len(places), 12, "the other places fill the scenes it cannot")
        never = type("Never", (), {"space": lambda self, space_id, context: False, "item": lambda self, item_id, partner: True})()
        plan = [scene["ideas"] for scene in self.made(pools, per_scene=2, pairing=never).scenes(4)]
        self.assertTrue(all(len(ideas) == 1 for ideas in plan), "no place fits: none is forced")


class LargePack(Packs):
    """A synthetic pack of 1,200 entries: the whole pool is available and the checks stay bounded."""

    WORDS = ("amber brisk cobalt dusky ember fern gilded hazel ivory jade kelp lilac maple nimbus ochre pewter quartz "
             "russet sable topaz").split()
    POSES = "lean curl drift sway fold twist arch coil tilt glide perch lunge spiral cradle brace vault hinge ripple swirl bend".split()
    ACTS = "toss twirl juggle polish tap wave spin flip shake hoist dangle balance stack tuck sort wrap fan roll buff swap".split()
    PROPS = "orb wand bell gourd lantern quill flute ladle mallet prism".split()
    ROOMS = "alcove bower cove dell eyrie foyer grotto hollow inlet jetty knoll loft mews nook oriel parlor quay rotunda solar".split()

    def names(self, nouns, count):
        """count distinct two-word names: no two entries share both words, so none is a near-duplicate of another."""
        return [f"{self.WORDS[number % 20].title()} {nouns[number // 20 % len(nouns)]}" for number in range(count)]

    def setUp(self):
        super().setUp()
        entries = []
        for number, name in enumerate(self.names(self.POSES, 400)):
            entries.append({"id": f"grid:position.p{number}", "category": "position", "name": name,
                            "description": f"{name}, for two.", "components": {
                                "participants": {"slots": {"a": {"count": 1, "kind": "being"}, "b": {"count": 1, "kind": "being"}}},
                                **({"requirements": {"space": {"all_of": ["core:surface.seat"]}}} if number % 4 == 0 else {}),
                                "spatial": {"participants": {"a": {"facing": {"same_as": "b"}}}}}})
        for number, name in enumerate(self.names(self.ACTS, 300)):
            entries.append({"id": f"grid:action.a{number}", "category": "action", "name": name,
                            "description": f"{name}, by hand.", "components": {
                                "participants": {"slots": {"user": {"count": 1, "kind": "being"}, "thing": {"count": 1, "kind": "object"}}},
                                "requirements": {"participants": {"user": {"all_of": ["core:limb.hand"]},
                                                                  "thing": {"all_of": ["core:item.handheld"]}}},
                                "claims": {"user": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "hold",
                                                     "key": "hold:{thing}"}]}}})
        for number, name in enumerate(self.names(self.PROPS, 200)):
            entries.append({"id": f"grid:item.i{number}", "category": "item", "name": name,
                            "description": f"{name}.", "components": {
                                "object": {"provides": ["core:item.handheld"] if number % 2 else ["core:surface.ground"],
                                           "size": "small", "hands": 1}}})
        for number, name in enumerate(self.names(self.ROOMS, 300)):
            entries.append({"id": f"grid:space.s{number}", "category": "space", "name": name,
                            "description": f"{name}.", "components": {"environment": {
                                "provides": ["core:surface.ground", "core:surface.seat"] if number % 3 else ["core:surface.ground"]}}})
        self.install("grid", entries, description="Grid studio sets for testing.", themes=["grid studio"])

    def test_the_whole_pool_is_offered_with_bounded_checks(self):
        import time
        from goated_prompter.features.vocabulary import retrieval as module
        calls = {"space": 0, "item": 0, "bindable": 0}
        originals = {name: getattr(module._Retrieval, f"check_{name}") for name in calls}

        def counted(name):
            def check(self, *args):
                calls[name] += 1
                return originals[name](self, *args)
            return check
        for name in calls:
            setattr(module._Retrieval, f"check_{name}", counted(name))
        self.addCleanup(lambda: [setattr(module._Retrieval, f"check_{name}", original) for name, original in originals.items()])
        started = time.perf_counter()
        found = self.ask("Grid studio scenes of a couple", randomized="positions, acts, props, location", seed=3)
        plan = found.scenes(100)
        elapsed = time.perf_counter() - started
        eligible = {category: len(pool) for category, pool in found.pools}
        self.assertGreaterEqual(eligible.get("position", 0), 300, eligible)
        self.assertGreaterEqual(eligible.get("space", 0), 250, eligible)
        places = {entry_id for scene in plan for entry_id in scene["ideas"] if ":space." in entry_id}
        self.assertGreaterEqual(len(places), 90, "100 images see about 100 different places, not 12")
        spaces, partners = eligible.get("space", 0), 400 + 300
        self.assertLess(calls["space"], spaces * partners // 20, f"space checks stay far from all pairs: {calls}")
        self.assertLess(calls["item"], eligible.get("item", 0) * 300 // 20, f"item checks stay far from all pairs: {calls}")
        self.assertLess(elapsed, 60, f"retrieval and 100 images took {elapsed:.1f}s")


class RoleRotation(unittest.TestCase):
    """The per-image rule on hand-made pools with explicit roles and scopes."""

    @staticmethod
    def made(pools, per_scene=3, seed=0):
        from goated_prompter.features.vocabulary.retrieval import Retrieval, RetrievedEntry
        built = [(key, [RetrievedEntry(id=entry_id, name=entry_id, category=key, pack="test", rating="general", description="",
                                       status="eligible", relevance=1.0, score=1.0, why=[], source="inspiration",
                                       scopes=list(scopes), role=role) for entry_id, role, scopes in items]) for key, items in pools]
        return Retrieval([], [], [], [], [], RetrievalConfig(), pools=built, seed=seed, per_scene=per_scene)

    def test_two_place_categories_share_one_slot_and_take_turns(self):
        found = self.made([("space", [("s1", "space", ["setting"]), ("s2", "space", ["setting"])]),
                           ("venue", [("v1", "space", ["setting"])])])
        plan = [scene["ideas"] for scene in found.scenes(9)]
        self.assertTrue(all(len(ideas) == 1 for ideas in plan))
        self.assertEqual({ideas[0] for ideas in plan}, {"s1", "s2", "v1"})

    def test_asked_roles_first_then_the_arrangement_then_the_place(self):
        pools = [("space", [("s1", "space", ["setting"])]), ("posture", [("p1", "arrangement", ["arrangement"])]),
                 ("action", [("a1", "interaction", ["category"])])]
        self.assertEqual([scene["ideas"] for scene in self.made(pools).scenes(2)], [["a1", "p1", "s1"]] * 2)
        self.assertEqual([scene["ideas"] for scene in self.made(pools, per_scene=2).scenes(2)], [["a1", "p1"]] * 2,
                         "an open place yields to what the brief asked for")
        asked = [("space", [("s1", "space", ["category"])]), ("posture", [("p1", "arrangement", ["arrangement"])])]
        self.assertEqual([scene["ideas"] for scene in self.made(asked, per_scene=1).scenes(2)], [["s1"]] * 2,
                         "a place the brief asks to vary is an asked role")

    def test_asked_roles_that_do_not_all_fit_take_turns(self):
        pools = [("action", [("a1", "interaction", ["category"])]), ("position", [("p1", "arrangement", ["category"])]),
                 ("space", [("s1", "space", ["category"])])]
        plan = [scene["ideas"] for scene in self.made(pools, per_scene=2).scenes(6)]
        for entry_id in ("a1", "p1", "s1"):
            self.assertEqual(sum(entry_id in ideas for ideas in plan), 4)


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
        self.assertEqual(ideas(found, "position")[0], "general:position.from_behind", "the General pack's adult-rated position remains, first")

    def test_inspiration_can_be_turned_off(self):
        found = self.ask("Two adult men having sex.", characters=MEN, nsfw=True, config=RetrievalConfig(inspiration=False))
        self.assertEqual(found.inspiration, [])
        self.assertEqual([entry.id for entry in found.entries], ["adult:action.sex"], "turning off ideas keeps required activities")
        self.assertEqual(found.warnings, [])


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

    def test_the_inspector_counts_eligible_offered_and_suggested_ideas(self):
        registry = self.manager.registry()
        sample = inspection_sample({"request": "Two adult men having sex.", "nsfw": True, "characters": ["adult man", "adult man"],
                                    "randomized": "sex positions, acts, location", "seed": 3, "scenes": 20})
        shown = inspect_registry(registry, **sample)
        counts = shown["coverage"]
        offered = [entry_id for scene in shown["scenes"] for entry_id in scene["ideas"]]
        category = {entry["id"]: entry["category"] for entry in shown["inspiration"]}
        self.assertEqual(counts["images"], 20)
        self.assertEqual(counts["suggestions"], len(offered))
        self.assertEqual(counts["distinct"], len(set(offered)))
        self.assertEqual(counts["offered_ids"], list(dict.fromkeys(offered)))
        self.assertEqual(sum(counts["eligible"].values()), len(shown["inspiration"]), "eligible counts the whole pool")
        for key, number in counts["offered"].items():
            self.assertEqual(number, len({entry_id for entry_id in offered if category[entry_id] == key}))
            self.assertLessEqual(number, counts["eligible"][key])
        self.assertGreater(counts["eligible"]["position"], counts["offered"]["position"], "20 images use part of a larger pool")
        self.assertEqual(counts["named_per_image"], len(shown["entries"]))

    def test_the_inspector_sample_keeps_its_old_shape_and_checks_the_new_fields(self):
        self.assertEqual(inspection_sample({"request": "a lantern"}),
                         {"request": "a lantern", "nsfw": False, "characters": [], "randomized": "", "avoid": [], "seed": 0, "scenes": 5})
        for bad in ({"seed": -1}, {"seed": True}, {"scenes": 0}, {"scenes": 21}, {"avoid": [""]}, {"randomized": 3},
                    {"unknown": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspection_sample({"request": "a lantern", **bad})


if __name__ == "__main__":
    unittest.main()
