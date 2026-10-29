"""Vocabulary policies (v2/scenes/policies.py): one registry entry per vocabulary category, and the shared engine that
plans every image's vocabulary in a fixed order. Built-in catalog and scripted briefs only; no model call."""

import json
import random
import unittest

from goated_prompter.features.dataset.v2 import understanding
from goated_prompter.features.dataset.v2.consistency import PART_CATEGORIES
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.dataset.v2.scenes import policies
from goated_prompter.features.dataset.v2.scenes.settings import ACTIONS_CATEGORY
from goated_prompter.features.vocabulary import catalog as vocabulary
from goated_prompter.features.vocabulary.catalog import load_catalog, selected_vocabulary

CATALOG = load_catalog(user_root=False)


def brief(characters=None, **data):
    value = {"path": "character", "summary": "A woman reading in a library", "fixed": "a woman reading",
             "randomized": "", "must": [], "avoid": [],
             "characters": characters or [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she",
                                           "count": 1}]}
    return understanding.apply_rules(value, {**default_dataset_draft(), "subject": "a woman reading in a library",
                                             "amount": 4, "seed": 3, "seed_mode": "fixed", **data})


def plan(packs=(), guided=False, kept=None, acts=None, request=None, **data):
    run = {**brief(**({"subject": request} if request else {}), **data), "_known": frozenset()}  # as write_scenes has it
    if request is not None:
        run["input"] = {**run["input"], "request": request}
    if kept is not None:
        run["kept_words"] = {**run.get("kept_words", {}), **kept}
    if acts is not None:
        run["acts"] = acts
    selection = {"packs": list(packs)}
    return policies.plan_vocabulary(run, CATALOG, selection, selected_vocabulary(CATALOG, selection), None,
                                    random.Random(3), guided)


class Registry(unittest.TestCase):
    def test_every_vocabulary_category_has_one_policy(self):
        registered = json.loads((vocabulary.ROOT / "core" / "scene_category_registry.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(policy.category for policy in policies.POLICIES),
                         sorted(row["category"] for row in registered["categories"]))
        self.assertEqual(policies.POLICIES[0].category, ACTIONS_CATEGORY, "the actions are dealt first")

    def test_each_policy_follows_the_parts_its_category_varies(self):
        # consistency.PART_CATEGORIES says which category's suggestions vary a part; the actions have their own deal.
        parts = {category: tuple(part for part, owners in PART_CATEGORIES.items() if category in owners)
                 for category in policies.POLICY}
        for policy in policies.POLICIES:
            with self.subTest(category=policy.category):
                expected = ("action",) if policy.category == ACTIONS_CATEGORY else parts[policy.category]
                self.assertEqual(policy.understanding_fields, expected)

    def test_built_in_packs_are_used_only_where_every_image_is_dealt_one_or_a_thing_is_named(self):
        self.assertEqual({policy.category for policy in policies.POLICIES if policy.always_available},
                         {"Spaces", "Subjects", "Camera & Composition", "Objects & Props"})
        run = {"catalog": CATALOG, "selection": {"packs": []}, "groups": [], "guided": False,
               "brief": {"path": "sfw_character"}}
        for policy in policies.POLICIES:
            with self.subTest(category=policy.category):
                found = policies.retrieve(policy, run)
                self.assertEqual(bool(found), policy.always_available and policy.auto_when(run),
                                 "no other category retrieves built-in entries")
        two = {**run, "selection": {"packs": ["Clothing/Cyberpunk-Clothing", "Clothing/Outdoor-Gear"]}}
        self.assertEqual(len([entry for row in policies.retrieve(policies.POLICY["Clothing"], two)
                              for entry in row["entries"]]), 40, "every selected Clothing pack, nothing else")
        selected = {**run, "selection": {"packs": ["Objects/Furniture"]}}
        self.assertEqual({row["name"] for row in policies.retrieve(policies.POLICY["Objects & Props"], selected)},
                         {group["name"] for pack in CATALOG["packs"] if pack["id"] == "Objects/Furniture"
                          for group in pack["groups"]}, "a selected pack comes instead of the built-in ones")


class Engine(unittest.TestCase):
    def test_without_packs_the_writer_covers_what_the_scene_needs(self):
        _, groups, outcome = plan()
        self.assertEqual(groups, [])
        self.assertEqual(outcome["Actions & Poses"], "writer")
        self.assertEqual(outcome["Spaces"], "writer", "no place ideas to find one by: the writer chooses the place")
        self.assertEqual(outcome["Lighting"], "writer", "every scene has light; no pack means the writer gives it")
        self.assertEqual(outcome["Mood & Tone"], "none")
        self.assertEqual(outcome["Effects & Atmosphere"], "none")

    def test_selected_packs_of_other_categories_are_suggested_to_every_image(self):
        result, _, outcome = plan(["Lighting/Natural", "Mood & Tone/Calm-and-Wonder"])
        self.assertEqual(outcome["Lighting"], "suggested")
        self.assertEqual(outcome["Mood & Tone"], "suggested")
        self.assertTrue(all({"Lighting", "Mood & Tone"} <= set(hand) for hand in result["hands"].values()))

    def test_a_thing_the_request_names_is_needed_in_every_image_and_nothing_else_is_added(self):
        acts = [{"who": ["woman"], "act": "typing on a laptop", "to": []}]
        result, _, outcome = plan(kept={"objects": "a red umbrella"}, acts=acts)
        self.assertEqual(outcome["Objects & Props"], "dealt")
        self.assertEqual([result["needed"][number]["Objects & Props"] for number in range(1, 5)],
                         [["umbrella", "laptop"]] * 4, "the kept object and the act's object, in every image")
        self.assertFalse([hand for hand in result["hands"].values() if "Objects & Props" in hand], "no optional object")
        unnamed, _, _ = plan(kept={"objects": "a hammock"}, acts=[{"who": ["woman"], "act": "resting", "to": []}])
        self.assertEqual(unnamed["needed"], {}, "no entry names it: the request's own words stay")
        own, _, _ = plan(["Objects/Furniture"], kept={"objects": "a red umbrella"})
        self.assertFalse([items for items in own["needed"].values() if "umbrella" in str(items)],
                         "a selected pack comes instead of the built-in ones")

    PAIR = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
            {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]

    @staticmethod
    def worn_by(result, label):
        """{slot: what label wears} from the needed Clothing entries."""
        return {number: [item.split(": ", 1)[1] for item in needed.get("Clothing", []) if item.startswith(label + ": ")]
                for number, needed in result["needed"].items()}

    TWO = ["Clothing/Cyberpunk-Clothing", "Clothing/Outdoor-Gear"]

    def pool(self, *packs):
        return {entry for pack in CATALOG["packs"] if pack["id"] in packs for entry in pack["entries"]}

    def test_without_a_clothing_pack_the_writer_dresses_everyone(self):
        result, _, outcome = plan(characters=self.PAIR, request="a man in a tailored suit dancing with a woman",
                                  kept={"clothing": "a tailored suit"})
        self.assertEqual(result["needed"], {}, "the request's own words stay with the writer")
        self.assertEqual(outcome["Clothing"], "writer")

    def test_selected_clothing_packs_are_one_pool_dealt_to_every_person(self):
        result, _, outcome = plan(self.TWO, characters=self.PAIR, request="a man and a woman walking in a park")
        self.assertEqual(outcome["Clothing"], "dealt")
        worn = {label: self.worn_by(result, label) for label in ("man", "woman")}
        self.assertTrue(all(len(worn[label][number]) == 1 for label in worn for number in range(1, 5)),
                        "one entry per person per image; the writer completes the rest")
        self.assertTrue(all(worn["man"][number] != worn["woman"][number] for number in range(1, 5)))
        dealt = {entry for items in worn.values() for entries in items.values() for entry in entries}
        self.assertTrue(dealt <= self.pool(*self.TWO), "no world, scene or other filter on what the user chose")
        self.assertGreaterEqual(len(dealt), 6, "varied across images")
        self.assertFalse([hand for hand in result["hands"].values() if "Clothing" in hand], "dealt, not suggested")

    def test_the_requests_garments_stay_and_a_locked_part_keeps_each_persons_entry(self):
        request = "a man in a tailored suit dancing with a woman"
        result, _, _ = plan(["Clothing/Modern-Fashion-Male"], characters=self.PAIR, request=request,
                            kept={"clothing": "a tailored suit"})
        self.assertEqual(self.worn_by(result, "man"), {number: ["tailored suit"] for number in range(1, 5)},
                         "the request's garment on its wearer in every image, nothing dealt over it")
        self.assertNotIn("tailored suit", {entry for entries in self.worn_by(result, "woman").values() for entry in entries})
        armor, _, _ = plan(["Clothing/Modern-Fashion-Male"], characters=self.PAIR, request="a man in armor dancing with a woman",
                           kept={"clothing": "armor"})
        self.assertEqual(self.worn_by(armor, "man"), {number: [] for number in range(1, 5)},
                         "no entry names it: the request's words stay and nothing is dealt over them")
        twins = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 2}]
        fixed, _, _ = plan(self.TWO, characters=twins, request="two women talking", consistency={"clothing": "locked"})
        self.assertEqual(len({entry for entries in self.worn_by(fixed, "woman 1").values() for entry in entries}), 1)

    def test_a_pack_made_for_one_sex_dresses_only_the_people_of_that_sex(self):
        packs = ["Clothing/Modern-Fashion-Female", "Clothing/Modern-Fashion-Male"]
        result, _, _ = plan(packs, characters=self.PAIR, request="a man and a woman walking in a park")
        female, male = self.pool(packs[0]), self.pool(packs[1])
        worn = {label: {entry for entries in self.worn_by(result, label).values() for entry in entries}
                for label in ("man", "woman")}
        self.assertTrue(worn["woman"] <= female and worn["man"] <= male, worn)
        friends = [{"label": "friend", "gender": "", "custom": "", "pronoun": "", "count": 2}]
        unknown, _, _ = plan(packs, characters=friends, request="two friends walking in a park")
        self.assertTrue({entry for entries in self.worn_by(unknown, "friend 1").values() for entry in entries}
                        <= female | male, "an unstated sex draws from every selected pack")
        for pack in CATALOG["packs"]:
            if pack["id"] in packs:
                sex = "female" if pack["id"].endswith("-Female") else "male"
                self.assertTrue(pack["description"].startswith(f"For {sex} characters only"), "the writer reads it")

    def test_adult_sets_keep_their_clothing_rule(self):
        suggested, _, _ = plan(["Clothing/Modern-Fashion-Female"], characters=self.PAIR, nsfw=True, request="a man with a woman")
        self.assertEqual(suggested["needed"], {}, "nothing dealt: whoever takes part is bare unless the request dresses them")
        self.assertTrue(all("Clothing" in hand for hand in suggested["hands"].values()), "selected packs as before")

    def test_only_people_whose_look_is_their_own_are_dealt_clothing(self):
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "cat", "gender": "custom", "custom": "a cat", "pronoun": "it", "count": 1, "kind": "animal"}]
        result, _, _ = plan(self.TWO, characters=cast, request="a woman with her cat")
        self.assertTrue(all(self.worn_by(result, "woman").values()))
        self.assertFalse([item for needed in result["needed"].values() for item in needed.get("Clothing", [])
                          if item.startswith("cat: ")])

    def test_a_selected_objects_pack_puts_one_of_its_objects_in_every_image(self):
        result, groups, outcome = plan(["Objects/Furniture"], request="a woman reading in a library")
        furniture = self.pool("Objects/Furniture")
        dealt = [result["needed"][number]["Objects & Props"] for number in range(1, 5)]
        self.assertTrue(all(len(entries) == 1 and entries[0] in furniture for entries in dealt), "needed, not optional")
        self.assertEqual(len({entries[0] for entries in dealt}), 4, "a different object in every image")
        self.assertEqual(outcome["Objects & Props"], "dealt")
        self.assertTrue(result["placed"])
        self.assertFalse([group for group in groups if group["category"] == "Objects & Props"], "not a list to pick from")
        kept, _, _ = plan(["Objects/Furniture"], kept={"objects": "a velvet armchair"},
                          request="a woman reading in a velvet armchair")
        self.assertEqual({tuple(kept["needed"][number]["Objects & Props"]) for number in range(1, 5)},
                         {("velvet armchair",)}, "the request's object comes first and nothing is dealt over it")
        acted, _, _ = plan(["Objects/Toys-and-Games"], request="a woman playing chess on a chess board",
                           acts=[{"who": ["woman"], "act": "playing chess on a chess board", "to": []}])
        self.assertEqual({tuple(acted["needed"][number]["Objects & Props"]) for number in range(1, 5)},
                         {("chess board",)}, "an act's thing in the selected packs comes first too")

    def test_the_people_of_one_image_never_wear_the_same_entry(self):
        from goated_prompter.features.dataset.v2.scenes.clothing import deal_outfits
        pools = {"a": ["shirt", "coat"], "b": ["shirt", "coat", "cape"], "c": ["shirt", "coat", "cape"]}
        dealt = deal_outfits(pools, 8, random.Random(5))
        self.assertTrue(all(len(set(row.values())) == 3 for row in dealt.values()), dealt)
        self.assertEqual(len({row[label] for row in dealt.values() for label in "bc"}), 3, "the whole pool is worn")
        self.assertGreater(len({row["b"] for row in dealt.values()}), 1, "varied across images")
        fixed = deal_outfits(pools, 4, random.Random(5), fixed=True)
        self.assertEqual(len({tuple(sorted(row.items())) for row in fixed.values()}), 1)

    def test_clothing_belongs_to_whom_the_request_names_before_it(self):
        from goated_prompter.features.dataset.v2.scenes.clothing import worn
        person = lambda label: {"label": label}
        given = lambda request, clothing, *labels: worn({"input": {"request": request}, "kept_words": {"clothing": clothing},
                                                        "characters": [person(label) for label in labels]})
        self.assertEqual(given("two friends in matching hoodies at a cafe", "matching hoodies", "friend 1", "friend 2"),
                         {"friend 1": ["matching hoodies"], "friend 2": ["matching hoodies"]}, "both friends")
        self.assertEqual(given("a woman wearing her boyfriend's hoodie", "her boyfriend's hoodie", "woman", "boyfriend"),
                         {"woman": ["her boyfriend's hoodie"]}, "the wearer, not the owner the phrase names")
        self.assertEqual(given("a friend in a tailored suit talking with a friend in a denim jacket",
                               "a tailored suit; a denim jacket", "friend 1", "friend 2"),
                         {"friend 1": ["a tailored suit"], "friend 2": ["a denim jacket"]}, "people of one name by order")
        self.assertEqual(given("a knight in armor", "armor", "knight"), {"knight": ["armor"]}, "the only person")
        self.assertEqual(given("armor on display while two guards talk", "armor", "guard 1", "guard 2"), {},
                         "nobody named before it: no one is given it")

    def test_scene_ideas_get_no_dealt_places(self):
        result, _, outcome = plan(guided=True)
        self.assertNotIn("places", result)
        self.assertEqual(result["arrangement"], [])
        self.assertEqual(outcome["Spaces"], "none")


if __name__ == "__main__":
    unittest.main()
