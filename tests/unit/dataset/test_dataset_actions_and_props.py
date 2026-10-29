"""Actions & Poses and Objects & Props dealt by the shared vocabulary engine (v2/scenes/actions.py, props.py): the
entries made for the cast that show the request's action, none when no entry shows it, and the things the request
names. Built-in packs and scripted briefs only; no model call."""

import random
import unittest

from goated_prompter.features.dataset.v2.scenes import actions, props
from goated_prompter.features.dataset.v2.scenes import entries as entries_module
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

    def test_several_acts_are_planned_act_by_act_even_when_they_share_a_person(self):
        two = [act("reading"), act("painting", ("person 2",))]
        self.assertEqual(actions.several_acts(brief(2, acts=two)), two)
        self.assertIsNone(actions.several_acts(brief(2, acts=[act("reading")])), "one act is planned whole")
        shared = [act("reading", to=("person 2",)), act("painting", ("person 2",))]
        self.assertEqual(actions.several_acts(brief(2, acts=shared)), shared, "a person in two acts")
        self.assertIsNone(actions.several_acts(brief(2, acts=[act("reading", ()), act("painting", ("person 2",))])),
                          "an act with nobody in it")
        plans = actions.act_plans(brief(2, acts=shared), groups(*self.POSES))
        self.assertTrue(all(found == [] for _, found in plans), "a person in two acts gets no entry for either")
        mixed = [act("reading"), act("painting", ("person 1",)), act("painting", ("person 2",))]
        found = [groups_ for _, groups_ in actions.act_plans(brief(2, acts=mixed), groups(*self.POSES))]
        self.assertEqual((found[0], found[1]), ([], []), "the shared person's acts")
        self.assertTrue(found[2], "another person's own act keeps its entries")

    def test_letters_are_bound_to_the_acts_own_people_the_same_way_every_time(self):
        directed = act("guiding", ("person 1",), to=("person 2",))
        self.assertEqual(actions.roles("A guiding B by the elbow", directed), {"A": "person 1", "B": "person 2"})
        self.assertEqual(actions.roles("A seated with a book", act("reading", ("person 3",))), {"A": "person 3"},
                         "a solo entry's A is whoever does this act")
        group = act("planting", ("person 1", "person 2", "person 3"))
        self.assertEqual(actions.roles("A group planting a bed, A kneeling while the others carry pots", group),
                         {"A": "person 1", "others": ["person 2", "person 3"]})

    def test_each_assignment_binds_its_entrys_letters_and_one_without_an_entry_binds_none(self):
        item = lambda words, who, entry: {"act": words, "who": [who], "to": [], "entry": entry}
        bound = actions.with_roles({1: [item("reading", "person 1", "A seated with a book"),
                                        item("painting", "person 2", None)]})[1]
        self.assertEqual([row["roles"] for row in bound], [{"A": "person 1"}, {}])

    def test_groups_placing_as_many_characters_share_one_cast_size(self):
        people = lambda group: {entry: count for entry, count in group["people"].items()}
        plain = {"name": "lifting", "words": ["lifting"], "selected": True, "people": {"A, B and C lifting a beam": 3},
                 "entries": ["A, B and C lifting a beam"]}
        kinds = {"name": "carrying", "words": ["carrying"], "kinds": ["animal"], "selected": True,
                 "people": {"A and B carrying a crate": 2}, "entries": ["A and B carrying a crate"]}
        found = actions.action_plan(brief(3), [plain, kinds])
        self.assertEqual({count for group in found for count in people(group).values()}, {3},
                         "an entry for fewer only when no group has one for the whole cast")

    def test_each_separate_act_is_planned_and_dealt_with_its_own_people(self):
        rows = groups(*self.POSES)
        plans = actions.act_plans(brief(3, "playing a board game while the third is writing a letter",
                                        acts=[act("playing a board game", ("person 1", "person 2")),
                                              act("writing a letter", ("person 3",)), act("whistling", ("person 4",))],
                                        others=[("person 4", "human")]), rows)
        names = [[group["name"] for group in found] for _, found in plans]
        self.assertEqual(names, [["board games"], ["writing"], []], "each act its own entries; none fits whistling")
        dealt = actions.deal_assignments(plans, 3, random.Random(1))
        self.assertEqual([item["act"] for item in dealt[1]], ["playing a board game", "writing a letter", "whistling"])
        self.assertTrue(dealt[1][0]["entry"] and dealt[1][1]["entry"] and dealt[1][2]["entry"] is None)
        self.assertEqual(dealt[2][0]["who"], ["person 1", "person 2"])

    def test_an_entry_its_place_does_not_suit_is_dropped_but_its_act_stays(self):
        assigned = {1: [{"act": "writing", "who": ["a"], "to": [], "entry": "A writing at a desk"},
                        {"act": "rowing", "who": ["b"], "to": [], "entry": "A rowing on a lake"}]}
        pool = ["a study with a desk", "a library", "a reading room", "an office", "a lake shore"]
        meaning = {"A writing at a desk": [1.0, 0.0], "A rowing on a lake": [0.0, 1.0],
                   **{place: [1.0, 0.0] for place in pool[:4]}, "a lake shore": [0.0, 1.0]}
        from tests.unit.vocabulary.test_vocabulary_retrieval import Embedder as Scripted
        import tempfile
        from pathlib import Path
        from goated_prompter.features.vocabulary import embeddings as vectors
        with tempfile.TemporaryDirectory() as folder:
            scripted = vectors.Embeddings(Scripted(meaning), Path(folder) / "c.json", progress=lambda _: None)
            kept = actions.suited_to_place(assigned, {1: "a study with a desk"}, pool, scripted)
        self.assertEqual([(item["act"], item["entry"]) for item in kept[1]],
                         [("writing", "A writing at a desk"), ("rowing", None)])
        self.assertEqual(actions.suited_to_place(assigned, {1: "a study with a desk"}, pool, None), assigned)
        quiet = {1: [{**assigned[1][0]}, {"act": "sorting", "who": ["b"], "to": [], "entry": "A writing at a desk"}]}
        with tempfile.TemporaryDirectory() as folder:
            scripted = vectors.Embeddings(Scripted(meaning), Path(folder) / "c.json", progress=lambda _: None)
            self.assertEqual(actions.suited_to_place(quiet, {1: "a library"}, pool, scripted), quiet,
                             "entries a place suits together share it")

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


class Props(unittest.TestCase):
    def test_a_needed_thing_the_scene_leaves_out_is_added_to_its_extras(self):
        scene = {"actions": "the woman reads", "position": {}, "space": "a den", "camera": "medium shot",
                 "extras": "a grey cardigan"}
        self.assertEqual(props.with_needed(scene, ["porcelain teacup", "hardcover book"])["extras"],
                         "a grey cardigan; porcelain teacup; hardcover book")
        held = {**scene, "actions": "the woman reads a book, a teacup in her other hand"}
        self.assertEqual(props.with_needed(held, ["porcelain teacup", "hardcover book"]), held, "already shown")

    def test_built_in_packs_name_only_the_things_the_request_asks_for(self):
        rows = [{"name": "things", "words": [], "entries": ["chess board", "wooden table", "lighthouse", "umbrella",
                                                            "lantern: brass", "lantern: paper"]}]
        self.assertEqual(entries_module.named_things(rows, "", ["playing chess on a chess board"]), [["chess board"]],
                         "an act names the thing it is done with")
        self.assertEqual(entries_module.named_things(rows, "chess pieces; a board", ["reading"]), [],
                         "words of two phrases never make one name")
        self.assertEqual(entries_module.named_things(rows, "", ["reading in a lighthouse"], place="a lighthouse"), [],
                         "the place, not a thing in it")
        self.assertEqual(entries_module.named_things(rows, "a lighthouse", [], place="a lighthouse"), [["lighthouse"]],
                         "a kept object always counts")
        things = entries_module.named_things(rows, "a red umbrella; a lantern", ["holding a lantern"])
        self.assertEqual(things, [["umbrella"], ["lantern: brass", "lantern: paper"]], "each thing once")
        self.assertEqual(entries_module.deal_named(things, 3), {1: ["umbrella", "lantern: brass"], 2: ["umbrella", "lantern: paper"],
                                                       3: ["umbrella", "lantern: brass"]},
                         "every thing in every image, entries of one name in turn")
        self.assertEqual(entries_module.deal_named([], 3), {})


if __name__ == "__main__":
    unittest.main()
