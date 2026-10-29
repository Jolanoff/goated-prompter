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


def brief(**data):
    value = {"path": "character", "summary": "A woman reading in a library", "fixed": "a woman reading",
             "randomized": "", "must": [], "avoid": [],
             "characters": [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]}
    return understanding.apply_rules(value, {**default_dataset_draft(), "subject": "a woman reading in a library",
                                             "amount": 4, "seed": 3, "seed_mode": "fixed", **data})


def plan(packs=(), guided=False, **data):
    run = {**brief(**data), "_known": frozenset()}  # as write_scenes passes it
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

    def test_built_in_packs_are_used_only_where_every_image_is_dealt_one(self):
        self.assertEqual({policy.category for policy in policies.POLICIES if policy.always_available},
                         {"Spaces", "Subjects", "Camera & Composition"})
        run = {"catalog": CATALOG, "selection": {"packs": []}, "groups": [], "guided": False}
        for policy in policies.POLICIES:
            with self.subTest(category=policy.category):
                found = policies.retrieve(policy, run)
                self.assertEqual(bool(found), policy.always_available, "no other category retrieves built-in entries")


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

    def test_scene_ideas_get_no_dealt_places(self):
        result, _, outcome = plan(guided=True)
        self.assertNotIn("places", result)
        self.assertEqual(result["arrangement"], [])
        self.assertEqual(outcome["Spaces"], "none")


if __name__ == "__main__":
    unittest.main()
