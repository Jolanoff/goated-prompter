"""Places dealt to every image (v2/scenes/places.py): a named place and its setting, a request without a place spread
over the groups its ideas and words find, the user's packs first, the world and the adult default, and the scene
that must be built where it was dealt. Scripted models only; no model call chooses a place."""

import json
import random
import unittest
from unittest.mock import patch

from goated_prompter.features.dataset.v2.scenes import places
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval, selection
from goated_prompter.features.vocabulary.catalog import load_catalog
from tests.helpers import enter_context
from tests.unit.dataset.test_dataset_scene_quality import Harness
from tests.unit.vocabulary.test_vocabulary_retrieval import Embedder, group
from tests.support.dataset_scenes import composer_user

EVERYDAY = ("everyday",)
GROUPS = [group("bedroom", ["his room", "bed", "sleeping"], ["small bedroom with a single bed",
                                                              "attic bedroom with a round window"], EVERYDAY, adult=True),
          group("living room", ["sofa", "reading"], ["living room with a sofa"], EVERYDAY),
          group("kitchen", ["cooking", "baking"], ["home kitchen with an island", "galley kitchen with a window"],
                EVERYDAY),
          group("city street", ["street", "outside"], ["narrow city alley with brick walls"], EVERYDAY),
          group("park", ["outside", "bench"], ["city park with benches"], EVERYDAY),
          group("forest", ["woods", "trees"], ["forest path between pine trees"], ("everyday", "fantasy")),
          group("space station", ["in space", "space station"], ["space station corridor with portholes"], ("sci-fi",))]


def brief(level="free", words=None, setting="", world="everyday", ideas=(), request="a person in a scene",
          path="sfw_character"):
    return {"input": {"request": request, "seed": 1}, "path": path, "consistency": {"place": level},
            "kept_words": {"place": words} if words else {},
            "places": {"setting": setting, "world": world, "ideas": list(ideas)}}


def names(found):
    return [row["name"] for row in found]


class NamedPlace(unittest.TestCase):
    def test_the_place_words_find_their_group_and_keep_the_setting(self):
        found, setting = places.place_plan(brief("themed", "in his room in space", setting="in space"), GROUPS)
        self.assertEqual((names(found), setting), (["bedroom"], "in space"),
                         "the room is the place, space what surrounds it: never one of them dropped")
        self.assertEqual(places._without("in his room in space", "in space"), "in his room")
        found, setting = places.place_plan(brief("themed", "in the kitchen", request="reading on the sofa in the kitchen"),
                                           GROUPS)
        self.assertEqual((names(found), setting), (["kitchen"], ""), "the place words alone decide")

    def test_a_place_in_no_catalog_uses_its_setting_else_nothing(self):
        found, setting = places.place_plan(brief("themed", "a capsule bunk in space", setting="in space",
                                                 world="sci-fi"), GROUPS)
        self.assertEqual((names(found), setting), (["space station"], ""))
        self.assertEqual(places.place_plan(brief("themed", "aboard a submarine"), GROUPS), ([], ""),
                         "the writer follows the request's words")
        self.assertEqual(places.place_plan(brief("themed"), GROUPS), ([], ""),
                         "an older brief keeps its place without words: nothing is dealt")

    def test_the_ideas_of_a_named_place_widen_it_only_with_close_groups(self):
        # A live named place found one group with one entry and dealt it to every image; widened by its ideas, it
        # then drifted to bedrooms for a bathroom fixture.
        ideas = brief("themed", "in his room", ideas=["a sunny bedroom", "a cosy sofa corner", "a city park"])
        with patch.object(places, "related", lambda candidates, anchors, *_: [
                group for group in candidates if group["name"] in ("bedroom", "living room")]):
            self.assertEqual(names(places.place_plan(ideas, GROUPS)[0]), ["bedroom", "living room"])
        self.assertEqual(names(places.place_plan(ideas, GROUPS)[0]), ["bedroom"], "without embeddings nothing is added")

    def test_place_words_that_name_no_place_fall_back_to_the_ideas(self):
        # Live briefs kept a time of day as the place: no place was dealt at all.
        found, _ = places.place_plan(brief("themed", "at dawn", ideas=["a city park", "a narrow street"],
                                           path="nsfw_character"), GROUPS)
        self.assertEqual(names(found), ["park", "city street"], "the ideas, without the adult default before them")
        self.assertEqual(places.place_plan(brief("themed", "aboard a submarine", ideas=["a submarine bunk"]), GROUPS),
                         ([], ""), "a named place missing from the catalog still deals nothing")

    def test_a_place_found_by_meaning_must_fit_the_world(self):
        vectors = {"a resting chamber": [1, 0], retrieval.group_text(GROUPS[0]): [1, 0],
                   retrieval.group_text(GROUPS[6]): [0, 1]}
        embeddings = vectors_module.Embeddings(Embedder(vectors), None, progress=lambda _: None)
        embeddings._cache = {}  # in memory only
        with patch.object(vectors_module, "atomic_json"):
            found, _ = places.place_plan(brief("themed", "a resting chamber"), GROUPS, embeddings)
            self.assertEqual(names(found), ["bedroom"])
            found, _ = places.place_plan(brief("themed", "a resting chamber", world="sci-fi"), GROUPS, embeddings)
        self.assertEqual(found, [], "a match by meaning outside the request's world is not a match")

    def test_a_word_match_that_leaves_place_words_unexplained_needs_the_meaning_to_agree(self):
        # Held-out words found the wrong group through one of their words ("sports hall" said the corridor's "hall").
        pool = [group("car and bus", ["car"], ["car interior with leather seats"]),
                group("laundry", ["washing"], ["laundromat with washing machines"]),
                group("kitchen", ["cooking"], ["home kitchen with an island"]),
                group("park", ["bench"], ["city park with benches"])]
        vectors = {"at a car wash": [1, 0, 0], retrieval.group_text(pool[1]): [1, 0, 0],
                   retrieval.group_text(pool[0]): [0, 1, 0], retrieval.group_text(pool[2]): [0, 0, 1],
                   retrieval.group_text(pool[3]): [0, .7, .7]}
        embeddings = vectors_module.Embeddings(Embedder(vectors), None, progress=lambda _: None)
        embeddings._cache = {}
        with patch.object(vectors_module, "atomic_json"):
            found, _ = places.place_plan(brief("themed", "at a car wash"), pool, embeddings)
            self.assertNotIn("car and bus", names(found), "the car is only what is washed here")
            found, _ = places.place_plan(brief("themed", "in the car"), pool, embeddings)
        self.assertEqual(names(found), ["car and bus"], "words the match explains need nothing more")

    def test_the_users_selected_places_come_first(self):
        mine = group("my bedroom", ["his room"], ["my own bedroom with red walls"], selected=True)
        found, _ = places.place_plan(brief("themed", "in his room"), [mine, *GROUPS])
        self.assertEqual(names(found), ["my bedroom"])
        found, _ = places.place_plan(brief("themed", "in the kitchen"), [mine, *GROUPS])
        self.assertEqual(names(found), ["kitchen"], "the user's packs have none: the built-in ones")


class NoPlaceNamed(unittest.TestCase):
    def test_the_set_spreads_over_the_groups_the_ideas_name(self):
        request = brief(ideas=["a city street", "a quiet bedroom", "a kitchen at home", "a crowded park", "the moon"],
                        request="a person cooking and telling jokes")
        found, setting = places.place_plan(request, GROUPS)
        self.assertEqual((names(found), setting), (["city street", "bedroom", "kitchen", "park"], ""),
                         "each idea's group, in the ideas' order; an idea no group has adds nothing, and the request's "
                         "own words choose nothing beside them")
        dealt = selection.deal_spread(found, 8, random.Random(1))
        kinds = {entry: row["name"] for row in found for entry in row["entries"]}
        self.assertEqual(len({kinds[place] for place in dealt.values()}), 4, "never one kind of place for the set")

    def test_the_world_and_the_adult_default_shape_the_groups(self):
        found, _ = places.place_plan(brief(world="fantasy", ideas=["a forest", "a city street"]), GROUPS)
        self.assertEqual(names(found), ["forest"], "a modern street does not fit a fantasy world")
        found, _ = places.place_plan(brief(ideas=["a park"], path="nsfw_character"), GROUPS)
        self.assertEqual(names(found), ["bedroom", "park"], "an adult request leads with its default groups")
        self.assertEqual(places.place_plan(brief(), GROUPS), ([], ""), "nothing found: the writer chooses")
        older = brief(request="a person sleeping", path="nsfw_character")
        del older["places"]  # a version 15 brief: its words and the adult default only
        self.assertEqual(names(places.place_plan(older, GROUPS)[0]), ["bedroom"])

    def test_the_users_selected_places_are_the_set_when_there_are_any(self):
        mine = [group("my bedroom", entries=["my own bedroom with red walls"], selected=True),
                group("my roof", entries=["my rooftop at dusk"], selected=True)]
        found, _ = places.place_plan(brief(ideas=["a kitchen"]), [*mine, *GROUPS])
        self.assertEqual(names(found), ["my bedroom", "my roof"])


class PlaceCheck(unittest.TestCase):
    def test_a_scene_must_be_built_in_its_dealt_place(self):
        place = "attic bedroom with a round window"
        self.assertEqual(places.place_problems({"space": "an attic bedroom, a bed under the slanted ceiling"}, place), [])
        # Live scenes in their dealt place were asked again for naming it differently, and came back as copies.
        self.assertEqual(places.place_problems({"space": "the top floor room, a round window behind him"}, place), [],
                         "one of the place's own features is enough")
        self.assertEqual(places.place_problems({"space": "a dark kitchen", "actions": "a reader turns a page"}, place),
                         ['its space is not its dealt place: build it in "attic bedroom" and keep its act '
                          '("a reader turns a page")'])

    def test_only_the_words_that_tell_places_apart_count(self):
        rows = [group("a", entries=["galley kitchen with a window"]), group("b", entries=["attic bedroom with a window"]),
                group("c", entries=["living room with a window"])]
        words = retrieval.telling_words(rows)
        self.assertEqual(words["galley kitchen with a window"], {"galley", "kitchen"}, "every place has a window")
        self.assertTrue(places.place_problems({"space": "a living room by the window"}, "galley kitchen with a window",
                                              words), "a window alone is not this kitchen")

    def test_each_pose_gets_the_dealt_place_that_suits_it(self):
        poses = {1: "a reader seated at a desk, writing", 2: "a walker stepping across shallow water on stones",
                 3: "a reader seated at a desk, writing"}
        dealt = {1: "river bank with shallow water and stones", 2: "office with a desk and a lamp", 3: "a quiet library"}
        matched = selection.pair(dealt, poses, retrieval.fit_scores)
        self.assertEqual(matched[2], "river bank with shallow water and stones")
        self.assertEqual(sorted(matched.values()), sorted(dealt.values()), "the same places, only moved")
        self.assertEqual(selection.pair(dealt, {}, retrieval.fit_scores), dealt, "no poses: nothing moves")

    def test_the_built_in_places_answer_a_room_without_a_library(self):
        rows = retrieval.groups_of(load_catalog(user_root=False), places.SPACES, {"packs": []})
        found, _ = places.place_plan(brief("themed", "in his room", request="young person reading a book in his room"),
                                     rows)
        self.assertTrue(found and all("bedroom" in entry for row in found for entry in row["entries"]), found)


class DealtPlaces(Harness):
    def setUp(self):
        super().setUp()
        enter_context(self, patch("goated_prompter.features.dataset.v2.scenes.place_plan", places.place_plan))

    def write(self):
        from goated_prompter.features.dataset.v2 import scenes
        return scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)

    def generate(self, instruction):
        self.assertNotEqual(instruction.diagnostic_stage, "dataset_v2:places", "no model call chooses a place")
        if instruction.diagnostic_stage == "dataset_v2:scenes" and getattr(self, "dealt", False):
            # The first batch builds every scene in a kitchen; asked again, each is built in its dealt place.
            self.calls.append(instruction)
            images = composer_user(instruction.user_message)["images"]
            asked_again = len(self.composer()) > 1
            return json.dumps({"scenes": [self.scene(places.entry_name(row["place"]) if asked_again else "a kitchen")
                                          for row in images]})
        return super().generate(instruction)

    def test_each_image_is_dealt_a_place_the_scene_must_use(self):
        # The harness request is adult and names no place: the adult default groups, one per image.
        self.brief["input"]["amount"], self.dealt = 2, True
        rows = retrieval.groups_of(load_catalog(user_root=False), places.SPACES, {"packs": []})
        kinds = {entry: row["name"] for row in rows if row["adult"] for entry in row["entries"]}
        result = self.write()
        first, second = self.composer()
        dealt = [image["place"] for image in composer_user(first.user_message)["images"]]
        self.assertEqual(len({kinds[place] for place in dealt}), 2, "each image from a different group")
        self.assertIn("PLACES\nEvery image in IMAGES names its place", first.system_message)
        self.assertIn("its space is not its dealt place", second.system_message, "the dealt place is binding")
        self.assertEqual(sorted(scene["space"] for scene in result["scenes"]), sorted(map(places.entry_name, dealt)))

    def test_a_setting_goes_to_every_image_with_its_place(self):
        self.brief["input"]["amount"] = 2
        self.brief["consistency"] = {**self.brief["consistency"], "place": "themed"}
        self.brief["kept_words"] = {**self.brief["kept_words"], "place": "in his room in space"}
        self.brief["places"] = {**self.brief["places"], "setting": "in space"}
        self.write()
        first = self.composer()[0]
        images = composer_user(first.user_message)["images"]
        self.assertTrue(all(image["setting"] == "in space" and "bedroom" in image["place"] for image in images), images)
        self.assertIn('also names a setting ("setting")', " ".join(first.system_message.split()))

    def test_no_place_found_leaves_the_place_to_the_writer(self):
        self.brief["input"]["amount"] = 1
        self.brief["consistency"] = {**self.brief["consistency"], "place": "themed"}
        self.brief["kept_words"] = {**self.brief["kept_words"], "place": "aboard a submarine"}
        self.write()
        first = self.composer()[0]
        self.assertNotIn("place", composer_user(first.user_message)["images"][0])
        self.assertNotIn("PLACES\n", first.system_message)


if __name__ == "__main__":
    unittest.main()
