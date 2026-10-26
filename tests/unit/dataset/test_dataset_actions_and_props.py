"""Actions & Poses and Objects & Props dealt by the shared vocabulary engine (v2/scenes/actions.py, props.py): the
entries made for the cast that show the request's action, none when no entry shows it, the objects that suit each
image's pose and place, each paired with its image. Built-in packs and scripted briefs only; no model call."""

import random
import unittest

from goated_prompter.features.dataset.v2.scenes import actions, props
from goated_prompter.features.dataset.v2.scenes.entries import offered_groups
from goated_prompter.features.vocabulary.catalog import load_catalog, selected_vocabulary

CATALOG = load_catalog(user_root=False)


def brief(cast, action="", avoid=()):
    return {"characters": [{"label": f"person {number}", "count": 1} for number in range(1, cast + 1)],
            "kept_words": {"action": action} if action else {}, "avoid": list(avoid)}


def groups(*packs, category="Actions & Poses"):
    selection = {"packs": list(packs)}
    return offered_groups(CATALOG, category, selection, selected_vocabulary(CATALOG, selection))


def entries(found):
    return [entry for group in found for entry in group["entries"]]


class Actions(unittest.TestCase):
    POSES = ("Actions & Poses/Solo-Activities", "Actions & Poses/Couple-Interactions", "Actions & Poses/Romance",
             "Actions & Poses/Group-Interactions", "Actions & Poses/Combat")

    def test_a_cast_gets_the_entries_made_for_its_number_of_people(self):
        rows = groups(*self.POSES)
        people = {entry: count for group in rows for entry, count in group["people"].items()}
        for cast, wanted in ((1, {1}), (2, {2}), (4, {3})):
            with self.subTest(cast=cast):
                self.assertEqual({people[entry] for entry in entries(actions.action_plan(brief(cast), rows))}, wanted)

    def test_the_requests_action_finds_its_group_by_trigger_words(self):
        rows = groups(*self.POSES)
        found = actions.action_plan(brief(2, "slow dancing"), rows)
        self.assertEqual([group["name"] for group in found], ["dancing"])
        found = actions.action_plan(brief(2, "playing a board game"), rows)
        self.assertEqual([group["name"] for group in found], ["board games"])
        found = actions.action_plan(brief(2, "sparring"), rows)
        self.assertEqual([group["name"] for group in found], ["sparring with a partner"], "a pair: the partner drills")
        self.assertEqual(actions.action_plan(brief(1, "sparring"), rows), [], "no solo entry spars")

    def test_an_action_no_entry_shows_deals_none(self):
        # The request's act is never replaced by an unrelated entry: the writer builds it from the request.
        self.assertEqual(actions.action_plan(brief(2, "juggling torches"), groups(*self.POSES)), [])

    def test_what_the_request_rules_out_is_never_dealt(self):
        rows = groups("Actions & Poses/Exploration")
        kept = entries(actions.action_plan(brief(1, avoid=["no kneeling"]), rows))
        self.assertTrue(kept)
        self.assertFalse([entry for entry in kept if "kneel" in entry.casefold()])

    def test_the_set_spreads_over_the_kinds_and_a_locked_action_is_one_pose(self):
        found = actions.action_plan(brief(1), groups("Actions & Poses/Solo-Activities"))
        kinds = {entry: group["name"] for group in found for entry in group["entries"]}
        dealt = actions.deal_actions(found, 10, random.Random(3))
        self.assertEqual(len({kinds[entry] for entry in dealt.values()}), 10, "ten images, ten kinds of activity")
        self.assertEqual(len(set(actions.deal_actions(found, 5, random.Random(3), locked=True).values())), 1)


class Embedder:
    """Scripted meaning: a text's vector counts its words from each of a few topics."""

    model_id = "scripted:topics"
    TOPICS = (("board", "game", "chess", "cards", "dice", "card", "tabletop"),
              ("sword", "blade", "swordsman", "duel", "swordplay", "knight", "melee"))

    def embed(self, texts):
        words = lambda text: set(text.casefold().replace(",", " ").replace(":", " ").split())
        return [[float(len(words(text) & set(topic))) for topic in self.TOPICS] + [1.0] for text in texts]

    def close(self):
        pass


def scripted():
    from unittest.mock import patch
    from goated_prompter.features.vocabulary import embeddings as vectors
    meaning = vectors.Embeddings(Embedder(), None, progress=lambda _: None)
    meaning._cache = {}
    patcher = patch.object(vectors, "atomic_json")
    patcher.start()
    return meaning, patcher


class Props(unittest.TestCase):
    OBJECTS = ("Objects/Toys-and-Games", "Objects/Weapons", "Objects/Kitchen-and-Dining", "Objects/Furniture")

    def setUp(self):
        self.meaning, patcher = scripted()
        self.addCleanup(patcher.stop)

    def test_each_image_gets_an_object_that_suits_its_own_pose_and_place(self):
        rows = groups(*self.OBJECTS, category="Objects & Props")
        kind = {entry: group["name"] for group in rows for entry in group["entries"]}
        partners = {1: "A and B playing chess with cards and dice", 2: "A swordsman in a duel with a blade",
                    3: "A and B playing chess with cards and dice"}
        dealt = props.deal_props(rows, 3, random.Random(2), partners, self.meaning)
        self.assertEqual((kind[dealt[1]], kind[dealt[2]], kind[dealt[3]]),
                         ("board and card games", "swords and blades", "board and card games"))
        self.assertNotEqual(dealt[1], dealt[3], "the same pose gets different objects")

    def test_an_image_nothing_suits_gets_no_object(self):
        # A slow dance and a hug were suggested a spear and a buckler when every image got an object.
        rows = groups(*self.OBJECTS, category="Objects & Props")
        self.assertEqual(props.deal_props(rows, 2, random.Random(2), {1: "A and B in a quiet moment", 2: "A smiling"},
                                          self.meaning), {})
        self.assertEqual(len(props.deal_props(rows, 3, random.Random(2), embeddings=self.meaning)), 3,
                         "no pose or place to suit: any object")
        self.assertEqual(len(props.deal_props(rows, 2, random.Random(2), {1: "A smiling", 2: "A smiling"})), 2,
                         "without meaning nothing can be judged: any object, as before")


if __name__ == "__main__":
    unittest.main()
