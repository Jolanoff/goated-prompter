"""Looks dealt to the people whose looks vary (v2/scenes/looks.py): the group a person's gender names, different
people in one image, nothing for named, known or custom characters, the request's own words about a person, and the
scene that must give each person their dealt look. Scripted models only."""

import json
import random
import unittest
from unittest.mock import patch

from goated_prompter.features.dataset.v2.scenes import looks
from goated_prompter.features.vocabulary.catalog import load_catalog
from tests.helpers import enter_context
from tests.support.dataset_scenes import composer_user
from tests.unit.dataset.test_dataset_scene_quality import Harness


def look_group(name, words, entries):
    return {"name": name, "words": [name, *words], "entries": list(entries), "worlds": None, "adult": False,
            "selected": False}


GROUPS = [look_group("female", ["woman", "girl"],
                     ["long black hair with green eyes and fair skin", "black bob hair with brown eyes and olive skin",
                      "wavy blonde hair with blue eyes and pale skin", "blonde braided hair with grey eyes and tan skin"]),
          look_group("male", ["man", "guy"],
                     ["black crew-cut hair with hazel eyes and deep brown skin",
                      "black undercut hair with amber eyes and caramel skin",
                      "ginger shaggy hair with grey-green eyes and freckled skin",
                      "auburn quiffed hair with steel blue eyes and rosy skin"])]
GROUP = {entry: group["name"] for group in GROUPS for entry in group["entries"]}


def brief(*people, subject=""):
    return {"characters": [{"label": label, "gender": gender, "appearance": (looks or [""])[0]}
                           for label, gender, *looks in people],
            "consistency": {}, "kept_words": {"subject": subject} if subject else {}}


class DealLooks(unittest.TestCase):
    def deal(self, request, total=4):
        return looks.deal_looks(request, GROUPS, total, random.Random(1))

    def test_a_persons_gender_finds_its_group_by_the_groups_words(self):
        dealt = self.deal(brief(("woman", "female"), ("man", "male")))
        self.assertEqual(sorted(dealt), [1, 2, 3, 4], "a look in every image")
        self.assertEqual({GROUP[image["woman"]] for image in dealt.values()}, {"female"})
        self.assertEqual({GROUP[image["man"]] for image in dealt.values()}, {"male"})
        self.assertEqual(len({image["woman"] for image in dealt.values()}), 4, "no look again before all are dealt")
        either = self.deal(brief(("person", "")), total=8)
        self.assertEqual({GROUP[image["person"]] for image in either.values()}, {"female", "male"},
                         "no stated gender: looks of either")

    def test_the_people_of_one_image_get_different_looks(self):
        dealt = self.deal(brief(("woman 1", "female"), ("woman 2", "female")), total=2)
        self.assertTrue(all(image["woman 1"] != image["woman 2"] for image in dealt.values()), dealt)

    def test_named_known_or_custom_characters_keep_their_own_look(self):
        self.assertEqual(self.deal(brief(("Anna", "female"))), {}, "a person the user named is not varied")
        known = brief(("woman", "female"))
        known["characters"][0]["known"] = True
        self.assertEqual(self.deal(known), {})
        self.assertEqual(set(self.deal(brief(("robot", "custom"), ("woman", "female")))[1]), {"woman"},
                         "a custom character is not a human man or woman: its description is its look")

    def test_a_persons_own_words_fix_only_the_parts_they_name(self):
        # A live "blonde woman" dealt every look got red, lilac and black hair; a live ginger man with green eyes kept
        # one whole look, hairstyle and skin, in every image.
        dealt = self.deal(brief(("man", "male"), ("blonde woman", "female")))
        hair = lambda look: look.split(" with ")[0]
        self.assertEqual({hair(image["blonde woman"]) for image in dealt.values()}, {"wavy blonde hair", "blonde braided hair"})
        self.assertGreater(len({image["blonde woman"].rsplit(" and ", 1)[1] for image in dealt.values()}), 1,
                           "her skin is not asked for: it varies")
        man = self.deal(brief(("man", "male", "green eyes"), ("woman", "female", "a tall build")))
        self.assertEqual({image["man"].split(" with ")[1].split(" and ")[0] for image in man.values()}, {"grey-green eyes"})
        self.assertGreater(len({hair(image["man"]) for image in man.values()}), 1, "his hair is not asked for")
        self.assertEqual(len({image["woman"] for image in man.values()}), 4, "words no look says fix nothing")


class Details(unittest.TestCase):
    def test_what_the_request_gives_a_person_that_no_look_holds_is_kept(self):
        # Live sets lost a requested beard, tattoos and age in most images: no field or look held them.
        request = brief(("man", "male", "ginger, sleeve tattoos and a nose ring"), ("woman", "female", "22 year old"))
        self.assertEqual(looks.requested_details(request, GROUPS), {"man": ["sleeve tattoos", "nose ring"],
                                                                    "woman": ["22 year old"]})
        self.assertEqual({image["man"].split(" with ")[0] for image in looks.deal_looks(request, GROUPS, 2,
                                                                                         random.Random(1)).values()},
                         {"ginger shaggy hair"}, "ginger is a part of a look")
        known = brief(("Hatsune Miku", "female", "short hair"))
        known["characters"][0]["known"] = True
        self.assertEqual(looks.requested_details(known, GROUPS), {"Hatsune Miku": ["short hair"]},
                         "a person without a look keeps their details")
        self.assertEqual(looks.requested_details(request, []), {"man": ["ginger", "sleeve tattoos", "nose ring"],
                                                                "woman": ["22 year old"]}, "whatever the vocabulary")
        self.assertEqual(looks.requested_details(brief(("dancer", "female", "a dancer")), GROUPS), {},
                         "a person's own label is not a detail")
        older = brief(("man", "male"), subject="a man with a nose ring")
        del older["characters"][0]["appearance"]
        self.assertEqual(looks.requested_details(older, GROUPS), {"man": ["nose ring"]},
                         "a brief before version 17: the subject's words are its only person's")

    def test_a_requested_detail_the_scene_leaves_out_is_added_in_the_requests_words(self):
        # A live writer asked three times to show a requested beard never did.
        scene = lambda **fields: {"subjects": {"man": {"skin": "tan", "hair": "short", **fields}},
                                  "extras": "he wears a black tank top."}
        self.assertEqual(looks.with_details(scene(skin="tan, a tattooed sleeve on each arm"),
                                            {"man": ["sleeve tattoos", "nose ring"]})["extras"],
                         "he wears a black tank top; man: nose ring")
        shown = {**scene(), "extras": "a silver nose ring; tattoos on his arms"}
        self.assertIs(looks.with_details(shown, {"man": ["sleeve tattoos", "nose ring"]}), shown,
                      "any of its words, in any form")
        self.assertIs(looks.with_details(shown, {}), shown)


class LookCheck(unittest.TestCase):
    LOOK = "wavy blonde hair with blue eyes and pale skin"

    def test_a_scene_must_give_each_person_their_dealt_look(self):
        person = lambda **fields: {"subjects": {"woman": {"skin": "", "hair": "", "eyes": "", **fields}}}
        self.assertEqual(looks.look_problems(person(hair="wavy blonde hair", eyes="blue", skin="pale"), "woman",
                                             self.LOOK), [])
        self.assertEqual(looks.look_problems(person(hair="blonde", skin="olive", eyes="brown"), "woman", self.LOOK), [],
                         "one part of the look is enough")
        self.assertEqual(looks.look_problems(person(hair="short black hair", skin="tan", eyes="brown"), "woman",
                                             self.LOOK),
                         [f"woman does not have their dealt look: give woman {self.LOOK} (skin, hair and eyes)"])
        self.assertEqual(looks.look_problems({"subjects": {}}, "woman", self.LOOK), [], "nobody to check")

    def test_the_words_that_tell_looks_apart_and_the_requests_own_words_count(self):
        words = looks.look_words(GROUPS, brief(("woman", "female", "red hair and grey eyes")), {1: {"woman": self.LOOK}})
        self.assertNotIn("hair", words[self.LOOK], "every look has hair")
        self.assertTrue(looks.look_problems({"subjects": {"woman": {"hair": "long hair", "eyes": "", "skin": ""}}},
                                            "woman", self.LOOK, words))
        self.assertEqual(looks.look_problems({"subjects": {"woman": {"hair": "red hair", "eyes": "grey eyes",
                                                                     "skin": "tan"}}}, "woman", self.LOOK, words), [],
                         "the request's own words replace the parts of the look they name")

    def test_the_built_in_looks_are_one_female_and_one_male_group(self):
        rows = looks.look_groups(load_catalog(user_root=False))
        self.assertEqual([row["name"] for row in rows], ["female", "male"])
        dealt = looks.deal_looks(brief(("woman", "female"), ("man", "male")), rows, 3, random.Random(2))
        self.assertTrue({image["woman"] for image in dealt.values()} <= set(rows[0]["entries"]), "nothing asked: whole looks")
        self.assertTrue({image["man"] for image in dealt.values()} <= set(rows[1]["entries"]))
        self.assertEqual(len({image["woman"] for image in dealt.values()}), 3)


class DealtLooks(Harness):
    def setUp(self):
        super().setUp()
        enter_context(self, patch("goated_prompter.features.dataset.v2.scenes.deal_looks", looks.deal_looks))
        self.brief["input"]["amount"] = 2

    def write(self, vocabulary=None):
        from goated_prompter.features.dataset.v2 import scenes
        return scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None,
                                   vocabulary=vocabulary)

    def generate(self, instruction):
        if instruction.diagnostic_stage == "dataset_v2:scenes":
            # The first batch keeps the harness looks; asked again, each person wears their dealt look.
            self.calls.append(instruction)
            asked_again = len(self.composer()) > 1
            scenes = []
            for row in composer_user(instruction.user_message)["images"]:
                scene = self.scene(f"room {row['image']}")
                for label, look in (row.get("looks") or {}).items() if asked_again else ():
                    scene["subjects"][label]["hair"] = look
                scenes.append(scene)
            return json.dumps({"scenes": scenes})
        return super().generate(instruction)

    def test_each_person_is_dealt_a_look_the_scene_must_use(self):
        result = self.write()
        first, second = self.composer()
        images = composer_user(first.user_message)["images"]
        self.assertTrue(all(set(image["looks"]) == {"man 1", "man 2"} for image in images), images)
        self.assertIn("LOOKS\nAn image in IMAGES may give people a look", first.system_message)
        system = " ".join(first.system_message.split())
        self.assertIn("A person gets nothing that neither the request nor the look gives", system)
        self.assertIn("A character with no look (an animal, a creature) still changes from image to image", system)
        self.assertIn("A look never gives a build: unless the request gives one, choose each person's build anew for "
                      "every image", " ".join(first.system_message.split()))
        self.assertIn("does not have their dealt look", second.system_message, "the dealt look is binding")
        self.assertNotIn("DETAILS\n", first.system_message, "the request says nothing about how they look")
        self.assertEqual([scene["subjects"]["man 1"]["hair"] for scene in result["scenes"]],
                         [image["looks"]["man 1"] for image in images])

    def test_what_the_request_says_a_person_looks_like_is_in_every_scene(self):
        self.brief["characters"][0]["appearance"] = "sleeve tattoos"
        result = self.write()
        first = self.composer()[0]
        self.assertTrue(all(image["details"] == {"man 1": ["sleeve tattoos"]}
                            for image in composer_user(first.user_message)["images"]))
        self.assertIn("every one is on that person in every image, in the field it belongs to",
                      " ".join(first.system_message.split()))
        self.assertTrue(all(scene["extras"].endswith("; man 1: sleeve tattoos") for scene in result["scenes"]),
                        "the writer left them out: code adds them in the request's words")

    def test_the_users_own_subjects_packs_deal_no_look(self):
        mine = [pack["id"] for pack in load_catalog(user_root=False)["packs"]
                if pack["category"] == looks.SUBJECTS and not pack.get("always")][:1]
        self.assertTrue(mine)
        self.write({"packs": mine})
        first = self.composer()[0]
        self.assertFalse([image for image in composer_user(first.user_message)["images"] if "looks" in image])
        self.assertNotIn("LOOKS\n", first.system_message)


if __name__ == "__main__":
    unittest.main()
