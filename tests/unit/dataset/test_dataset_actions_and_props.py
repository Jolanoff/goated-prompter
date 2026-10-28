"""Actions & Poses and Objects & Props dealt by the shared vocabulary engine (v2/scenes/actions.py, props.py): the
entries made for the cast that show the request's action, none when no entry shows it, the objects that suit each
image's pose and place, each paired with its image. Built-in packs and scripted briefs only; no model call."""

import random
import unittest

from goated_prompter.features.dataset.v2.scenes import actions, props
from goated_prompter.features.dataset.v2.scenes.entries import offered_groups
from goated_prompter.features.vocabulary.catalog import load_catalog, selected_vocabulary

CATALOG = load_catalog(user_root=False)


def brief(cast, action="", avoid=(), acts=None, objects="", others=()):
    """A cast of people (and other characters: (label, kind)) with the request's kept words and acts."""
    return {"characters": [*({"label": f"person {number}", "count": 1, "kind": "human"} for number in range(1, cast + 1)),
                           *({"label": label, "count": 1, "kind": kind} for label, kind in others)],
            "kept_words": {key: text for key, text in (("action", action), ("objects", objects)) if text},
            "avoid": list(avoid), **({"acts": acts} if acts is not None else {})}


def act(words, who=("person 1",), to=()):
    return {"who": list(who), "act": words, "to": list(to)}


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

    def test_an_entry_gives_someone_their_own_part_only_when_it_names_them_alone(self):
        for entry, own in (("A and B walking side by side, each keeping their own pace.", False),
                           ("Greeting: A and B face to face, each clasping the other's hand.", False),
                           ("A group cleaning a room, each working outside the others' paths.", False),
                           ("A holding a ladder at its base while B climbs it.", True),
                           ("Lift: B raising a box while A steadies its far end.", True),
                           ("A writing on a board while the others face it.", True),
                           ("A, B and C seated in a row, A turned toward C.", True)):
            with self.subTest(entry=entry):
                self.assertEqual(actions.distinct_roles(entry), own)
        # Everyone doing the group's own act together stays a shared act, whatever detail one of them adds.
        walk = "A and B walking side by side, A turning their head toward B."
        self.assertFalse(actions.distinct_roles(walk, ["walking together", "walking"]))
        self.assertTrue(actions.distinct_roles(walk), "for a group that is not about walking, A's own part counts")

    def test_an_act_done_to_another_character_keeps_only_entries_with_their_own_parts(self):
        # A live set turned one person instructing another into two equal opponents: the shared-act entry fit the
        # act's words but dropped who does what to whom.
        rows = groups(*self.POSES)
        shared = entries(actions.action_plan(brief(2, "sparring", acts=[act("sparring", ("person 1", "person 2"))]), rows))
        directed = entries(actions.action_plan(brief(2, "sparring", acts=[act("sparring", to=("person 2",))]), rows))
        self.assertTrue(directed)
        self.assertTrue(all(actions.distinct_roles(entry) for entry in directed))
        self.assertTrue(set(directed) < set(shared), "together: every partner entry; to another: only the directed ones")

    def test_an_entry_keeps_what_the_act_is_done_with(self):
        # A live set dealt a drill with other gear to a request that named its gear: it fit the words, not the gear.
        rows = [{"name": "drills", "words": ["drills", "drill", "training"], "selected": True, "people": {},
                 "entries": ["A and B facing each other, each holding a racket at the ready.",
                             "B throwing a ball while A steps aside.",
                             "A and B stretching side by side."]}]
        kept = entries(actions.action_plan(brief(2, "training with rackets", objects="two rackets"), rows))
        self.assertEqual(kept, ["A and B facing each other, each holding a racket at the ready."])
        self.assertEqual(actions.action_plan(brief(2, "training with hoops", objects="hoops"), rows), [],
                         "no entry has the gear: none, the writer builds it from the request")
        self.assertEqual(len(entries(actions.action_plan(brief(2, "training", objects="a bench"), rows))), 3,
                         "a thing the act does not name is no part of the act")

    def test_entries_for_people_place_only_people(self):
        # A live set gave a person and an animal a pose made for two people.
        rows = groups(*self.POSES)
        goat = [("goat", "animal")]
        feed = [act("walking with the goat", to=("goat",))]
        self.assertEqual(actions.action_plan(brief(1, "walking with the goat", acts=feed, others=goat), rows), [],
                         "an act with an animal in it gets no entry made for people")
        alone = entries(actions.action_plan(brief(1, others=goat), rows))
        people = {entry: count for group in rows for entry, count in group["people"].items()}
        self.assertTrue(alone)
        self.assertEqual({people[entry] for entry in alone}, {1}, "the animal is not counted as a second person")
        held = [{"name": "leading", "words": ["leading"], "kinds": ["animal"], "selected": True,
                 "people": {"A leading B by a rope.": 2}, "entries": ["A leading B by a rope."]}]
        self.assertEqual(entries(actions.action_plan(brief(1, "leading", acts=[act("leading", to=("goat",))], others=goat),
                                                     held)), ["A leading B by a rope."], "a group made for that kind")

    def test_several_separate_acts_deal_no_entry(self):
        # One entry is one interaction of the cast: it would keep one act and drop the others.
        rows = groups(*self.POSES)
        self.assertTrue(actions.action_plan(brief(2, "slow dancing", acts=[act("slow dancing", ("person 1", "person 2"))]),
                                            rows))
        self.assertEqual(actions.action_plan(brief(2, "reading while the other paints",
                                                   acts=[act("reading"), act("paints", ("person 2",))]), rows), [])

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

    def test_an_optional_object_never_adds_a_second_of_what_the_image_has(self):
        # A live set offered a second seat to someone already seated, and another tool of the same kind to a worker.
        seats = {"name": "seating", "words": ["seat"], "entries": ["weathered park bench", "padded stool", "deck chair"]}
        lamps = {"name": "lamps", "words": ["light"], "entries": ["desk lamp", "lantern"]}
        kept = props.the_same_things([seats, lamps], "A seated on a bench beside a window")
        self.assertEqual([row["entries"] for row in kept], [["weathered park bench"], ["desk lamp", "lantern"]],
                         "the bench they sit on, described more closely; a group it names nothing of is unchanged")

    def test_a_needed_thing_the_scene_leaves_out_is_added_to_its_extras(self):
        scene = {"actions": "the woman reads", "position": {}, "space": "a den", "camera": "medium shot",
                 "extras": "a grey cardigan"}
        self.assertEqual(props.with_needed(scene, ["porcelain teacup", "hardcover book"])["extras"],
                         "a grey cardigan; porcelain teacup; hardcover book")
        held = {**scene, "actions": "the woman reads a book, a teacup in her other hand"}
        self.assertEqual(props.with_needed(held, ["porcelain teacup", "hardcover book"]), held, "already shown")

    def test_a_group_deals_only_its_objects_close_to_the_image(self):
        group = {"name": "brushes", "words": [], "entries": ["A flat brush", "A fan brush", "A spray gun"]}
        self.assertEqual(props.closest([group], "a painter at an easel", None), [group], "without meaning: unchanged")
        kept = props.closest([group], "a painter holding a brush", self.meaning)
        self.assertTrue(kept[0]["entries"] and len(kept[0]["entries"]) <= 3)

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
