"""Selected vocabulary in the existing Dataset scene writer: only what the user picked, grouped under its Core
instruction, as optional material. The scene writer is scripted, so this checks what it receives, not how a live
model uses it."""

import json
import unittest
from unittest.mock import patch
from tests.helpers import enter_context

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.features.dataset.v2.tickets import intent_signature
from goated_prompter.features.vocabulary.catalog import load_catalog
from tests.support.dataset_scenes import composer_user, without_looks, without_places

SCENE = {"skin": "fair", "build": "slim", "hair": "long silver hair", "eyes": "grey", "expression": "a soft smile", "clothing": "a robe"}


class SceneVocabulary(unittest.TestCase):
    def setUp(self):
        without_places(self)
        without_looks(self)
        self.catalog = load_catalog(user_root=False)
        romance = next(pack for pack in self.catalog["packs"] if pack["id"] == "Actions & Poses/Romance")["entries"]
        self.dance = next(entry for entry in romance if entry.startswith("Slow dance:"))
        self.hands = next(entry for entry in romance if "inner hands joined" in entry)
        self.forehead = next(entry for entry in romance if "kiss B's forehead" in entry)
        self.calls, self.entries, self.copy_dealt = [], [], False
        self.backend = MockBackend()
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        enter_context(self, patch.object(scenes, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.request = GoatedPrompterRequest(idea="dataset", planning_mode="Direct", director_preset="general_director")

    def brief(self, subject, cast, *, nsfw=False, amount=2, things=""):
        data = {**default_dataset_draft(), "subject": subject, "amount": amount, "nsfw": nsfw, "seed": 7, "seed_mode": "fixed"}
        value = {"path": "character" if cast else "non_character", "summary": subject, "fixed": "", "randomized": "",
                 "must": [], "avoid": [], "characters": cast}
        if things:  # the things Understanding keeps (its kept objects), quoted from the request
            value["kept"] = {"objects": things}
        return understanding.apply_rules(understanding.recover(value), data)

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage != "dataset_v2:scenes":
            return "A finished prompt."
        user = composer_user(instruction.user_message)
        labels = [person["label"] for person in user["understanding"]["characters"]]
        wants_entry = "entry" in instruction.json_schema["properties"]["scenes"]["items"]["required"]
        return json.dumps({"scenes": [{
            "subjects": {label: {**SCENE, **{field: f"{field}{row['image']}{label}".replace(" ", "")
                                             for field in ("skin", "build", "hair", "eyes")}} for label in labels},
            "position": {label: "standing" for label in labels},
            "actions": f"{' and '.join(labels)}: {user['request']}", "space": f"clearing {row['image']}", "lighting": "moonlight",
            "mood": "calm", "camera": "wide shot", "extras": f"extras{row['image']}",
            "frame": {label: {"shows": "full body", "face": "visible"} for label in labels},
            **({"entry": self.entries.pop(0) if self.entries else self.copied(row) if self.copy_dealt
                  else self.dance} if wants_entry else {})}
            for row in user["images"]]})

    @staticmethod
    def copied(row):
        """The entry a faithful writer copies: the image's own, or every entry of its separate acts."""
        return row["entry"] if "entry" in row else " | ".join(item["entry"] for item in row["acts"] if item["entry"])

    def acting(self, subject, cast, acts, amount=2):
        """A brief whose request has separate acts ({who, act, to} with the answer's labels), kept in its words."""
        data = {**default_dataset_draft(), "subject": subject, "amount": amount, "seed": 7, "seed_mode": "fixed"}
        value = {"path": "character", "summary": subject, "fixed": "", "randomized": "", "must": [], "avoid": [],
                 "characters": cast, "kept": {"action": subject}, "acts": acts}
        return understanding.apply_rules(understanding.recover(value), data)

    def test_separate_acts_are_each_dealt_their_own_entry_with_their_own_people(self):
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        acts = [{"who": ["woman"], "act": "planting seedlings", "to": []},
                {"who": ["man"], "act": "writing a letter", "to": []}]
        self.copy_dealt = True
        result = self.write(self.acting("woman planting seedlings while a man is writing a letter", cast, acts),
                            ["Actions & Poses/Solo-Activities"])
        call = self.composer()[0]
        images = composer_user(call.user_message)["images"]
        self.assertTrue(all("entry" not in image for image in images), "no single entry for separate acts")
        for image in images:
            planting, writing = image["acts"]
            self.assertEqual((planting["who"], planting["act"], writing["who"], writing["act"]),
                             (["woman"], "planting seedlings", ["man"], "writing a letter"), "each act its own people")
            self.assertIn("seedling", planting["entry"].casefold())
            self.assertIn("writing", writing["entry"].casefold())
        self.assertIn("SEVERAL ACTS", call.system_message)
        self.assertIn("named by their label once", call.system_message, "every act stays with its person")
        self.assertTrue(result["complete"])
        self.assertEqual(result["scenes"][0]["entry"], self.copied(images[0]), "both entries, in the acts' order")

    def test_an_act_no_entry_fits_is_kept_for_the_writer(self):
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        acts = [{"who": ["woman"], "act": "planting seedlings", "to": []},
                {"who": ["man"], "act": "whistling a tune", "to": []}]
        self.copy_dealt = True
        self.write(self.acting("woman planting seedlings while a man is whistling a tune", cast, acts),
                   ["Actions & Poses/Solo-Activities"])
        for image in composer_user(self.composer()[0].user_message)["images"]:
            self.assertEqual([item["act"] for item in image["acts"]], ["planting seedlings", "whistling a tune"])
            self.assertIsNone(image["acts"][1]["entry"], "every act stays, the one without an entry too")

    def test_only_the_entries_an_image_was_dealt_reach_the_writer(self):
        catalog = load_catalog(user_root=False)
        planting, humming = ["A planting a seedling in a pot", "A kneeling to plant a row of bulbs"], [
            "A humming with eyes half closed", "A humming while leaning on a fence"]
        catalog["packs"].append({"id": "Actions & Poses/Test-Acts", "name": "Test Acts", "category": "Actions & Poses",
                                 "description": "", "source": "builtin", "people": {}, "entries": planting + humming,
                                 "groups": [{"name": "planting", "words": ["planting"], "entries": planting},
                                            {"name": "humming", "words": ["humming"], "entries": humming}]})
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        acts = [{"who": ["woman"], "act": "planting seedlings", "to": []}, {"who": ["man"], "act": "humming", "to": []}]
        self.copy_dealt = True
        self.write(self.acting("woman planting seedlings while a man is humming", cast, acts, amount=1),
                   ["Actions & Poses/Test-Acts"], catalog=catalog)
        user = composer_user(self.composer()[0].user_message)
        dealt = {item["entry"] for image in user["images"] for item in image["acts"]}
        self.assertEqual(len(dealt), 2, "one entry for each act")
        for entry in planting + humming:
            (self.assertIn if entry in dealt else self.assertNotIn)(entry, user.get("vocabulary", ""))

    def test_acts_sharing_a_person_get_no_entry(self):
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        acts = [{"who": ["woman"], "act": "planting seedlings", "to": ["man"]},
                {"who": ["man"], "act": "writing a letter", "to": []}]
        self.write(self.acting("woman planting seedlings for a man while a man is writing a letter", cast, acts),
                   ["Actions & Poses/Solo-Activities"])
        call = self.composer()[0]
        self.assertTrue(all("acts" not in image and "entry" not in image
                            for image in composer_user(call.user_message)["images"]))
        self.assertNotIn("SEVERAL ACTS", call.system_message)

    def test_words_in_the_entry_field_that_are_no_dealt_entry_are_dropped_not_asked_again(self):
        # A live writer added a placeholder for an act without an entry, and all three images were asked again.
        cast = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
                {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        acts = [{"who": ["woman"], "act": "planting seedlings", "to": []},
                {"who": ["man"], "act": "writing a letter", "to": []}]
        self.copy_dealt = True
        self.entries = ["a made-up pose | null"]
        result = self.write(self.acting("woman planting seedlings while a man is writing a letter", cast, acts, amount=1),
                            ["Actions & Poses/Solo-Activities"])
        self.assertEqual(len(self.composer()), 1, "no image asked again")
        self.assertEqual(result["scenes"][0]["entry"], "", "only dealt entries are counted as used")

    def write(self, brief, packs=(), catalog=None):
        return scenes.write_scenes({"backend": "mock"}, self.request, brief, progress=lambda _: None,
                                   vocabulary={"packs": list(packs)}, catalog=catalog or self.catalog)

    def composer(self):
        return [call for call in self.calls if call.diagnostic_stage == "dataset_v2:scenes"]

    def test_example_a_no_packs_generates_from_the_request_alone(self):
        result = self.write(self.brief("A banana fighting an apple", []))
        self.assertTrue(result["complete"])
        call = self.composer()[0]
        self.assertNotIn("SELECTED VOCABULARY", call.user_message)
        self.assertNotIn("VOCABULARY USAGE RULES", call.system_message)
        self.assertTrue(call.user_message.startswith("USER REQUEST:\nA banana fighting an apple\n\nEXISTING APPROVED REQUIREMENTS:\n"))
        self.assertEqual(result["vocabulary"], {"selection": {"packs": []}})

    def test_example_b_only_the_selected_packs_and_their_categories_are_sent(self):
        woman = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.write(self.brief("A magical woman in a magical world", woman),
                   ["Spaces/Fantasy", "Effects & Atmosphere/Magic-Effects"])
        call = self.composer()[0]
        vocabulary = composer_user(call.user_message)["vocabulary"]
        self.assertEqual(vocabulary.count("Core instruction:"), 2)
        self.assertIn("Spaces\nCore instruction:\nSpaces provides vocabulary describing where the action takes place.", vocabulary)
        self.assertIn("Effects & Atmosphere\nCore instruction:", vocabulary)
        self.assertIn("floating castle", vocabulary)
        self.assertIn("glowing aura", vocabulary)
        for unselected in ("Subjects\n", "Clothing\n", "Actions & Poses\n", "foggy graveyard", "athletic woman"):
            self.assertNotIn(unselected, vocabulary)
        system = " ".join(call.system_message.split())
        self.assertIn("Entries of every other category are possibilities", system)
        self.assertIn("Never add a subject or object only to use an entry.", system)
        self.assertIn("choose from any pack of a category", system, "one entry per category, from any pack")
        self.assertIn("Each selected category shapes its part of the scene", system)
        self.assertIn("none at all when the category does not fit the image", system, "optional for each image")

    def test_example_c_packs_of_an_adult_run_are_optional_material_beside_the_request(self):
        cast = [{"label": "model", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        packs = ["Actions & Poses/Solo-Activities", "Expressions/Happy-Expressions",
                 "Clothing/Modern-Fashion", "Objects/Furniture"]
        result = self.write(self.brief("A seductive adult character posing with a prop", cast, nsfw=True), packs)
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual([line for line in user["vocabulary"].split("\n") if line in {"Actions & Poses", "Expressions", "Clothing", "Objects & Props"}],
                         ["Actions & Poses", "Expressions", "Clothing"], "registry order; the objects are dealt instead")
        furniture = next(pack["entries"] for pack in self.catalog["packs"] if pack["id"] == "Objects/Furniture")
        self.assertTrue(all(image["needed"]["Objects & Props"][0] in furniture for image in user["images"]),
                        "a selected Objects pack puts one of its objects in every image")
        self.assertFalse([image for image in user["images"] if "Clothing" in image.get("needed", {})],
                         "an adult set's selected Clothing stays a suggestion")
        self.assertEqual(len(result["vocabulary"]["selection"]["packs"]), 4)

    def test_example_d_a_group_keeps_its_cast_from_understanding(self):
        group = [{"label": "adult", "gender": "", "custom": "", "pronoun": "", "count": 3}]
        result = self.write(self.brief("A group of adults in an intimate scene", group, nsfw=True),
                            ["Actions & Poses/Group-Interactions", "Mood & Tone/Romantic"])
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual([person["label"] for person in user["understanding"]["characters"]], ["adult 1", "adult 2", "adult 3"])
        self.assertTrue(all(set(scene["subjects"]) == {"adult 1", "adult 2", "adult 3"} for scene in result["scenes"]))

    def test_every_batch_gets_the_same_vocabulary_and_the_writer_is_called_once_per_batch(self):
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=13)
        self.write(brief, ["Lighting/Dramatic"])
        calls = self.composer()
        self.assertEqual(len(calls), 2)
        # The same entries in every batch (each batch gets its own seeded order).
        self.assertEqual(*(sorted(composer_user(call.user_message)["vocabulary"].splitlines()) for call in calls))
        self.assertEqual({call.diagnostic_stage for call in self.calls}, {"dataset_v2:scenes"}, "no extra LLM call")

    def test_every_image_gets_its_own_optional_suggestions_so_the_whole_pack_spreads(self):
        packs = ["Lighting/Dramatic", "Objects/Furniture"]
        amount = max(len(pack["entries"]) for pack in self.catalog["packs"] if pack["id"] in packs)
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=amount)
        self.write(brief, packs)
        images = [image for call in self.composer() for image in composer_user(call.user_message)["images"]]
        hands = [image["suggested"] for image in images]
        self.assertEqual({tuple(sorted(hand)) for hand in hands}, {("Lighting",)})
        # A selected Objects pack is the user's instruction: one of its objects is needed in every image, dealt through
        # the whole pack.
        objects = [image["needed"]["Objects & Props"] for image in images]
        for category, dealt in (("Lighting", [entry for hand in hands for entry in hand["Lighting"]]),
                                ("Objects & Props", [entry for needed in objects for entry in needed])):
            pack = {"Lighting": "Lighting/Dramatic", "Objects & Props": "Objects/Furniture"}[category]
            self.assertEqual(set(dealt), set(next(p for p in load_catalog()["packs"] if p["id"] == pack)["entries"]),
                             "every entry is dealt")
        self.assertTrue(all(len(needed) == 1 for needed in objects), "one object per image")
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn('none at all when the category does not fit the image', system)
        # Live scenes fixed restraints to furniture the place lacked and wrote a mark on a body part against a wall.
        self.assertIn("A used entry agrees with the positions, the space and the camera", system)
        # A live run with three suggestions per category used two or three of them in one image.
        self.assertTrue(all(len(hand[category]) == 1 for hand in hands for category in hand), "one suggestion per category")
        self.assertIn("use at most one per category", system)

    def lights(self, request, things=""):
        catalog = load_catalog(user_root=False)
        catalog["packs"].append({"id": "Objects/Test-Lights", "name": "Light Sources", "category": "Objects & Props",
                                 "description": "", "source": "builtin",
                                 "entries": ["lantern: a lantern swinging from a hook", "double lantern: two lanterns on one pole",
                                             "candle stub", "oil lamp", "torch", "glow stick", "string lights", "desk lamp",
                                             "flashlight beam"]})
        self.calls.clear()
        knight = [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        self.write(self.brief(request, knight, amount=4, things=things), ["Objects/Test-Lights"], catalog=catalog)
        images = composer_user(self.composer()[0].user_message)["images"]
        return [image.get("needed", image.get("suggested", {})).get("Objects & Props") for image in images]

    def test_a_request_naming_one_thing_gets_that_entry_in_every_image_and_nothing_else(self):
        # A live run gave every image three unrelated entries of a pack and almost never the entry about the one object
        # the request names.
        self.assertEqual(self.lights("A knight holding a red lantern", "a red lantern"),
                         [["lantern: a lantern swinging from a hook"]] * 4,
                         "the entry named in full wins over one that only shares the word")

    def test_only_the_things_the_request_keeps_name_an_entry(self):
        # A live set read words of the act as asking for objects that share them: a word of the act is no thing. Only
        # Understanding's kept objects name an entry; otherwise the selected pack's objects are dealt across the set.
        hands = self.lights("A knight holding a lamp and practicing his torch juggling")
        self.assertNotEqual(hands, [["torch"]] * 4, "no kept thing: no word of the act names an entry")
        self.assertEqual(len({entry for hand in hands for entry in hand}), 4, "a different object in every image")
        self.assertEqual(self.lights("A knight practicing his torch juggling", "his torch"), [["torch"]] * 4)
        # Understanding's kept objects are the words that mention things, and can name an activity ("practicing
        # juggling" kept "juggling"): only an entry whose whole name they say is needed, so an activity names none and
        # the pack's objects are dealt instead.
        hands = self.lights("A knight practicing juggling at night", "juggling")
        self.assertEqual(len({entry for hand in hands for entry in hand}), 4)
        from goated_prompter.features.dataset.v2.scenes.entries import named_in
        # A live set kept a thing described by its material and then needed other things of that material.
        self.assertEqual(named_in(["paper lantern", "paper fan", "flying kite", "kite"], {"small", "paper", "kite"}),
                         ["kite"], "the whole name, never one shared word")

    def test_a_request_asking_for_the_kind_in_general_gets_its_named_entry_and_one_other(self):
        hands = self.lights("A knight carrying light sources, among them a lantern", "light sources; a lantern")
        self.assertTrue(all(len(hand) == 2 and "lantern" in hand[0] and "lantern" not in hand[1] for hand in hands), hands)

    def test_a_word_of_a_packs_name_that_is_not_its_kind_never_asks_for_the_whole_pack(self):
        # A request word that was only the first word of a pack's name read as asking for the whole pack: every image
        # also got a random other place, and a live run kept only one of six images in the requested place.
        import random
        spaces = ["a library table", "a quiet library aisle", "a museum hall", "a storage room", "a cafe",
                  "a music room", "a hotel lobby", "a park bench", "a train", "a balcony", "a garden", "a garage"]
        groups = [{"category": "Spaces", "packs": [{"name": "Reading Spaces", "entries": spaces}]}]
        hands = scenes.entries.deal_hands(groups, 6, random.Random(3), words=frozenset({"people", "reading", "library"}))
        self.assertTrue(all(hand["Spaces"] and all("library" in entry for entry in hand["Spaces"])
                            for hand in hands.values()), hands)
        general = scenes.entries.deal_hands(groups, 6, random.Random(3), words=frozenset({"reading", "spaces", "library"}))
        self.assertTrue(all(len(hand["Spaces"]) == 2 for hand in general.values()), "the kind asked for in general")

    def test_a_request_word_naming_another_categorys_pack_never_pins_one_entry(self):
        # A live request about "public" places, with an Actions & Poses pack called Public Risk, got the one prop entry
        # that also said "public" in all ten images.
        import random
        props = ["a public notice taped to his back", "a paper map", "a wooden chair", "a red scarf", "a lamp",
                 "a blue cup", "a book", "a clock"]
        groups = [{"category": "Actions & Poses", "packs": [{"name": "Public Walks", "entries": ["A walks past B"]}]},
                  {"category": "Objects & Props", "packs": [{"name": "Things", "entries": props}]}]
        hands = scenes.entries.deal_hands(groups, 6, random.Random(3), words=frozenset({"two", "people", "public", "places"}))
        self.assertGreater(len({hand["Objects & Props"][0] for hand in hands.values()}), 1, hands)
        named = scenes.entries.deal_hands(groups, 6, random.Random(3), words=frozenset({"public", "notice"}))
        self.assertEqual({hand["Objects & Props"][0] for hand in named.values()}, {"a public notice taped to his back"},
                         "a word of its own that the request names still asks for that entry")

    def test_an_entry_about_less_of_the_request_gives_way_to_one_about_more(self):
        # "room" was in a quarter of a live Spaces pack, so every other room counted as the requested one.
        rooms = ["a reading room corner", "a quiet reading room", "a storage room", "a music room", "a hotel room",
                 *(f"outdoor place {number}" for number in range(15))]
        self.assertEqual(scenes.requested_entries(rooms, frozenset({"reading", "room"})),
                         ["a reading room corner", "a quiet reading room"])
        lights = ["a lantern", "an oil lamp", "a desk lamp", "a torch", "a candle", "a spotlight", "a glow stick", "a fire"]
        self.assertEqual(scenes.requested_entries(lights, frozenset({"lantern", "oil", "lamp"})),
                         ["a lantern", "an oil lamp"], "two things the request names both stay")

    def test_a_request_word_that_most_entries_share_never_counts_and_other_runs_deal_as_before(self):
        entries = [f"the one who serves with toy {n}" for n in range(8)]
        self.assertEqual(scenes.requested_entries(entries, frozenset({"serves", "toy"})), [])
        self.assertEqual(scenes.requested_entries(["a lantern", "a lamp"], frozenset({"lamp"})), ["a lamp"])
        import random
        groups = [{"category": "Lighting", "packs": [{"entries": ["spotlight", "chiaroscuro", "red light"]}]}]
        self.assertEqual(scenes.entries.deal_hands(groups, 4, random.Random(3)),
                         scenes.entries.deal_hands(groups, 4, random.Random(3), words=frozenset({"knight"})),
                         "no entry about the request: the same seeded deal as before")

    def slot_packs(self, poses, props=("wine glass", "teapot", "fruit bowl", "candle"), people=None):
        """A catalog with a pose pack and a props pack (people: {entry: count} for either)."""
        catalog = load_catalog(user_root=False)
        for ident, name, category, entries in (("Actions & Poses/Test-Poses", "Test Poses", "Actions & Poses", poses),
                                               ("Objects/Test-Props", "Test Props", "Objects & Props", props)):
            needs = {entry: count for entry, count in (people or {}).items() if entry in entries}
            catalog["packs"].append({"id": ident, "name": name, "category": category, "description": "",
                                     "source": "built-in", "entries": list(entries), **({"people": needs} if needs else {})})
        self.calls.clear()
        return catalog

    PAIR = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
            {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
    SOLO = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]

    def test_an_entry_with_a_slot_is_used_only_when_the_pack_it_names_is_selected(self):
        catalog = self.slot_packs(["two people by the table, one holding [Test Props]",
                                   "two people seated, one pouring from [Test-Props: teapot]",
                                   "two people standing, one holding [Not Selected Pack]",
                                   "two people kneeling, one holding [Test Props: anvil]",
                                   "two people dancing"])
        self.copy_dealt = True
        result = self.write(self.brief("A couple", self.PAIR, amount=4), ["Actions & Poses/Test-Poses", "Objects/Test-Props"],
                            catalog=catalog)
        kept = ["two people by the table, one holding [Test Props]", "two people seated, one pouring from [Test-Props: teapot]",
                "two people dancing"]
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual(set(image["entry"] for image in user["images"]), set(kept),
                         "a slot names a pack by its name or file name, and kept slots stay as written")
        for unused in ("standing", "kneeling"):
            self.assertNotIn(unused, user["vocabulary"], "a slot nothing selected can fill: never used")
        self.assertIn("teapot", user["vocabulary"], "the pack a slot names is offered beside it")
        self.assertEqual(len(self.composer()), 1)
        self.assertTrue(result["complete"])

    def test_slots_work_in_every_category(self):
        catalog = self.slot_packs(["two people dancing", "two people resting"])
        catalog["packs"].append({"id": "Lighting/Test-Light", "name": "Test Light", "category": "Lighting",
                                 "description": "", "source": "built-in",
                                 "entries": ["candlelight falling on [Test Props]", "light from [Actions & Poses]",
                                             "a lamp beside [Not Selected Pack]"]})
        self.write(self.brief("A couple", self.PAIR, amount=2),
                   ["Actions & Poses/Test-Poses", "Objects/Test-Props", "Lighting/Test-Light"], catalog=catalog)
        lights = {entry for image in composer_user(self.composer()[0].user_message)["images"]
                  for entry in image["suggested"]["Lighting"]}
        self.assertEqual(lights, {"candlelight falling on [Test Props]", "light from [Actions & Poses]"})

    def test_entries_are_made_for_the_casts_number_of_people(self):
        poses = ["two people dancing close", "the person stretching by the window", "the person reading"]
        props = ["wine glass", "two-seat swing", "teapot"]
        people = {"two people dancing close": 2, "two-seat swing": 2, "the person reading": 1}
        catalog = self.slot_packs(poses, props, people)
        self.write(self.brief("A man at home", self.SOLO, amount=4), ["Actions & Poses/Test-Poses", "Objects/Test-Props"],
                   catalog=catalog)
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual({image["entry"] for image in user["images"]},
                         {"the person reading", "the person stretching by the window"}, "an entry without a count fits")
        self.assertNotIn("two people dancing close", user["vocabulary"])
        self.assertNotIn("two-seat swing", user["vocabulary"])
        dealt = {entry for image in user["images"] for entry in image["needed"]["Objects & Props"]}
        self.assertEqual(dealt, {"wine glass", "teapot"}, "an object without a count always stays")
        catalog = self.slot_packs(poses, props, people)
        self.write(self.brief("A couple at home", self.PAIR, amount=4), ["Actions & Poses/Test-Poses", "Objects/Test-Props"],
                   catalog=catalog)
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual({image["entry"] for image in user["images"]},
                         {"two people dancing close", "the person stretching by the window"},
                         "a pair gets the entries made for two, never one made for one person alone")
        self.assertEqual({entry for image in user["images"] for entry in image["needed"]["Objects & Props"]},
                         {"wine glass", "two-seat swing", "teapot"}, "an object for fewer people than the cast still fits")

    def test_a_kept_action_lets_only_entries_that_show_it_fit(self):
        # A request naming one position got scenes built on other positions its activity also covers.
        catalog = self.slot_packs(["two people dancing close", "two people dancing apart", "two people reading a map",
                                   "two people cooking side by side"])
        brief = self.brief("A couple dancing", self.PAIR, amount=4)
        brief["kept_words"] = {"action": "dancing"}
        self.write(brief, ["Actions & Poses/Test-Poses"], catalog=catalog)
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual({image["entry"] for image in user["images"]}, {"two people dancing close", "two people dancing apart"})
        self.assertNotIn("cooking", user["vocabulary"], "an entry that does not show the action is never offered")
        self.assertFalse([call for call in self.calls if call.diagnostic_stage == "dataset_v2:entries"], "no model call")
        self.calls.clear()
        self.write(self.brief("A couple", self.PAIR, amount=4), ["Actions & Poses/Test-Poses"],
                   catalog=self.slot_packs(["two people dancing close", "two people dancing apart",
                                            "two people reading a map", "two people cooking side by side"]))
        self.assertEqual(len({image["entry"] for image in composer_user(self.composer()[0].user_message)["images"]}), 4,
                         "an action the request leaves open: every entry, a different one for each image")

    def test_a_request_that_rules_an_act_out_never_gets_it(self):
        catalog = self.slot_packs(["two people dancing close", "two people kneeling by a fire", "two people reading a map"])
        brief = {**self.brief("A couple", self.PAIR, amount=3), "avoid": ["no kneeling"]}
        self.write(brief, ["Actions & Poses/Test-Poses"], catalog=catalog)
        self.assertNotIn("kneeling", composer_user(self.composer()[0].user_message)["vocabulary"])

    def test_packs_without_slots_or_counts_are_written_exactly_as_before(self):
        packs = ["Actions & Poses/Romance", "Lighting/Dramatic", "Objects/Furniture"]
        self.write(self.brief("A couple", self.PAIR, amount=3), packs)
        now = [(call.system_message, call.user_message) for call in self.calls]
        self.calls.clear()
        with patch.object(scenes, "only_fillable", lambda groups: groups), \
                patch.object(scenes, "fit_cast", lambda groups, size: groups):
            self.write(self.brief("A couple", self.PAIR, amount=3), packs)
        self.assertEqual(now, [(call.system_message, call.user_message) for call in self.calls])

    def test_pack_descriptions_reach_the_scene_writer(self):
        catalog = load_catalog(user_root=False)
        for pack in catalog["packs"]:
            if pack["id"] in ("Actions & Poses/Solo-Activities", "Lighting/Dramatic"):
                pack["description"] = f"note for {pack['name']}"
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=2)
        self.write(brief, ["Actions & Poses/Solo-Activities", "Lighting/Dramatic"], catalog=catalog)
        vocabulary = composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertIn('Pack "Dramatic" (its author\'s note: note for Dramatic):', vocabulary)
        self.assertIn('Pack "Solo Activities" (its author\'s note: note for Solo Activities):', vocabulary)
        self.assertIn("its author's note", self.composer()[0].system_message)

    def test_the_sample_keeps_every_pack_and_its_description(self):
        groups = [{"category": "Objects & Props", "instruction": "",
                   "packs": [{"name": "A", "description": "a", "entries": [f"a{n}" for n in range(50)]},
                             {"name": "B", "description": "", "entries": [f"b{n}" for n in range(50)]}]}]
        packs = scenes._shuffled(groups, __import__("random").Random(1), 40)[0]["packs"]
        self.assertEqual([(pack["name"], pack["description"], len(pack["entries"])) for pack in packs],
                         [("A", "a", 20), ("B", "", 20)])

    def test_a_request_without_people_still_works_with_vocabulary(self):
        brief = self.brief("An empty throne room", [], amount=2)
        result = self.write(brief, ["Objects/Furniture", "Lighting/Dramatic"])
        self.assertEqual(result["written"], 2)

    def test_final_prompts_and_understanding_never_see_the_vocabulary(self):
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=1)
        result = self.write(brief, ["Lighting/Dramatic"])
        prompts.write_prompts({"backend": "mock"}, self.request, brief, result["scenes"], progress=lambda _: None)
        builder = [call for call in self.calls if call.diagnostic_stage != "dataset_v2:scenes"]
        self.assertTrue(builder)
        for call in builder:
            self.assertNotIn("hard chiaroscuro", call.system_message + call.user_message)
            self.assertNotIn("SELECTED VOCABULARY", call.system_message + call.user_message)
        draft = validate_dataset_draft({**default_dataset_draft(), "subject": "A knight", "vocabulary_packs": ["Lighting/Dramatic"]})
        self.assertNotIn("Lighting/Dramatic", understanding.instruction(draft).user_message)

    def test_the_packs_are_a_saved_dataset_setting_that_does_not_need_a_new_review(self):
        draft = validate_dataset_draft({**default_dataset_draft(), "vocabulary_packs": ["Spaces/Fantasy", "Spaces/Fantasy"]})
        self.assertEqual(draft["vocabulary_packs"], ["Spaces/Fantasy"])
        self.assertEqual(validate_dataset_draft(default_dataset_draft())["vocabulary_packs"], [])
        self.assertEqual(intent_signature(draft), intent_signature({**draft, "vocabulary_packs": []}))
        with self.assertRaises(ValueError):
            validate_dataset_draft({**default_dataset_draft(), "vocabulary_packs": "Spaces/Fantasy"})

    def test_actions_and_poses_entries_are_placeholders_the_writer_must_resolve(self):
        cast = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.write(self.brief("A couple in a romantic scene", cast, amount=1), ["Actions & Poses/Romance"])
        call = self.composer()[0]
        vocabulary = composer_user(call.user_message)["vocabulary"]
        self.assertIn("Actions & Poses\nCore instruction:\nActions & Poses provides vocabulary", vocabulary)
        self.assertIn(self.forehead, vocabulary)
        # Live scenes that rewrote an entry's arrangement reversed or doubled the act, so an entry is used as written:
        # its people become the scene's, and only what conflicts with the request, the cast or the kept place changes.
        system = " ".join(call.system_message.split())
        for rule in ("The entry is the image's act and arrangement and is used as written",
                     "its people (letters or placeholders) become this scene's people, chosen from the request, with "
                     "their own pronouns and bodies",
                     "Adapt only the part that conflicts with the request, the cast or the kept place",
                     # The final prompt keeps the act's words, so the scene copies them.
                     "the actions copy its words with only its people replaced",
                     # A live writer copied the whole earlier image whenever an entry came round again.
                     "Images dealt the same entry share only its act and pose: each still gets its own place, camera, "
                     "light and props",
                     "Entries of every other category are possibilities"):
            self.assertIn(rule, system)
        self.assertNotIn("Objects, furniture and surfaces named in an entry are examples", system)

    def test_every_image_is_dealt_its_own_entry_by_the_seed(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = [self.dance, self.hands, self.forehead]
        self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        dealt = [image["entry"] for image in composer_user(self.composer()[0].user_message)["images"]]
        self.assertEqual(len(set(dealt)), 3, "no entry is dealt twice while the pack has more")
        import random
        from goated_prompter.features.dataset.v2.scenes import actions
        groups = [{"name": f"kind {kind}", "entries": [f"entry {kind}{number}" for number in range(5)]} for kind in "ab"]
        deal = lambda seed: actions.deal_actions(groups, 10, random.Random(seed))
        self.assertEqual(deal(4), deal(4))
        self.assertNotEqual(deal(4), deal(5))
        self.assertEqual(sorted(deal(4).values()), sorted(entry for group in groups for entry in group["entries"]))
        self.assertEqual(len({entry[:7] for entry in list(deal(4).values())[:2]}), 2, "the first two images: both kinds")
        self.assertEqual(set(actions.deal_actions(groups, 4, random.Random(4), locked=True).values()).__len__(), 1)

    def test_a_scene_may_keep_neutral_wording_from_an_entry(self):
        labels = ["man", "woman"]
        scene = {"subjects": {label: dict(SCENE) for label in labels}, "position": {"man": "kneeling", "woman": "on all fours"},
                 "actions": "one person kneels behind the other person", "space": "a cabin", "lighting": "lamp",
                 "mood": "warm", "camera": "side view", "extras": "rug",
                 "frame": {label: {"shows": "full body", "face": "visible"} for label in labels}}
        self.assertEqual(scenes.scene_errors(scene, labels, []), [])
        # The scene rules allow empty extras, so an image with nothing to add is never asked again for it.
        self.assertEqual(scenes.scene_errors({**scene, "extras": ""}, labels, []), [])
        self.assertNotEqual(scenes.scene_errors({**scene, "camera": " "}, labels, []), [])

    def test_the_builder_gets_the_position_name_of_the_entry(self):
        scene = {"slot": 1, "subjects": {}, "position": {}, "actions": "they dance", "space": "hall", "lighting": "lamps",
                 "mood": "warm", "camera": "wide", "extras": "none", "entry": "slow dance: two people dancing close"}
        self.assertNotIn("position name", prompts.scene_text(scene), "The writer adapted the entry: its name would mislead.")
        scene["actions"] = "they hold each other in a Slow  Dance"
        self.assertIn("in a Slow  Dance\nposition name: slow dance\n", prompts.scene_text(scene))
        self.assertEqual(prompts.position_name({**scene, "entry": "two people holding hands"}), "")
        self.assertIn("use that name word for word", prompts.SCENE_RULES)
        # Image models know a position by its name, so the final prompt keeps the name the scene's actions give; the
        # scene writer names the position its pose really is.
        self.assertNotIn("name no position", prompts.SCENE_RULES)
        self.assertIn("with the act's own verb and the position's name", scenes.NSFW_RULE)


    def test_scene_ideas_never_get_vocabulary(self):
        knight = [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        data = {**default_dataset_draft(), "subject": "A knight", "amount": 2, "seed": 7, "seed_mode": "fixed",
                "source_mode": "guided", "inputs": "kneels in a chapel\nrides at dawn"}
        brief = understanding.apply_rules({"path": "character", "summary": "A knight", "fixed": "", "randomized": "",
                                           "must": [], "avoid": [], "characters": knight}, data)
        result = self.write(brief, ["Lighting/Dramatic", "Actions & Poses/Romance"])
        call = self.composer()[0]
        self.assertNotIn("SELECTED VOCABULARY", call.user_message)
        self.assertNotIn("ACTIONS & POSES ENTRY", call.system_message)
        self.assertNotIn("looks", json.dumps(composer_user(call.user_message)["images"]))
        self.assertEqual(result["vocabulary"], {"selection": {"packs": []}})

    def test_a_locked_part_gets_one_pose_and_no_suggestions_for_its_category(self):
        # A pose dataset dealt each image a different entry of the act, so the pose drifted from image to image.
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        brief = self.brief("A couple", pair, amount=4)
        brief["consistency"] = {**brief["consistency"], "action": "locked", "light": "locked"}
        self.write(brief, ["Actions & Poses/Romance", "Lighting/Dramatic"])
        images = composer_user(self.composer()[0].user_message)["images"]
        self.assertEqual(len({image["entry"] for image in images}), 1, "one pose for the whole set")
        self.assertTrue(all("Lighting" not in image.get("suggested", {}) for image in images), "the light is locked")
        self.assertIn("used by fewer than 4 images", self.composer()[0].system_message, "nobody is told to move off it")
        self.calls.clear()
        brief["consistency"] = {**brief["consistency"], "action": "themed", "light": "free"}
        self.write(brief, ["Actions & Poses/Romance", "Lighting/Dramatic"])
        images = composer_user(self.composer()[0].user_message)["images"]
        self.assertGreater(len({image["entry"] for image in images}), 1)
        self.assertTrue(all("Lighting" in image["suggested"] for image in images))

    def test_an_entry_used_by_more_images_than_the_cap_is_kept_and_later_batches_see_the_count(self):
        # Reusing an entry is repetition, which the vocabulary's deal handles: the scene is kept, never asked again.
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = [self.dance] * 3
        result = self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual([scene["entry"] for scene in result["scenes"]], [self.dance] * 3)
        self.assertEqual(len(self.composer()), 1, "nobody is asked again for a reused entry")
        self.assertIn("used by fewer than 2 images", self.composer()[0].system_message)
        self.entries = [self.dance] * 12
        self.calls.clear()
        self.write(self.brief("A couple", pair, amount=12), ["Actions & Poses/Romance"])
        self.assertEqual(composer_user(self.composer()[1].user_message)["already_used"]["entries"], {self.dance: 10})

    def test_an_entry_that_is_not_in_the_vocabulary_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = ["a made-up entry", self.hands.upper().replace(" ", "   ")]
        result = self.write(self.brief("A couple", pair, amount=1), ["Actions & Poses/Romance"])
        self.assertEqual(result["scenes"][0]["entry"], self.hands)
        self.assertIn("copied word for word", self.composer()[1].system_message)

    def test_only_entries_that_fit_the_request_are_offered_dealt_and_counted(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        brief = self.brief("A couple with hands joined", pair, amount=5)
        brief["kept_words"] = {"action": "hands joined"}
        romance = next(pack for pack in self.catalog["packs"] if pack["id"] == "Actions & Poses/Romance")["entries"]
        seated = next(entry for entry in romance if "hands joined between their knees" in entry)
        self.entries = [self.hands, seated] * 2 + [self.hands]
        result = self.write(brief, ["Actions & Poses/Romance"])
        first = self.composer()[0]
        vocabulary = composer_user(first.user_message)["vocabulary"]
        self.assertIn(self.hands, vocabulary)
        self.assertNotIn(self.forehead, vocabulary, "an entry that does not show the action is never offered")
        self.assertEqual({image["entry"] for image in composer_user(first.user_message)["images"]},
                         {self.hands, seated, self.dance}, "the slow dance joins one hand of each too")
        self.assertIn("used by fewer than 2 images", first.system_message, "five images share three fitting entries")
        self.assertTrue(result["complete"])

    def test_when_no_entry_fits_the_writer_gets_no_actions_vocabulary(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        brief = self.brief("A couple juggling", pair, amount=2)
        brief["kept_words"] = {"action": "juggling"}
        result = self.write(brief, ["Actions & Poses/Romance", "Lighting/Dramatic"])
        call = self.composer()[0]
        vocabulary = composer_user(call.user_message)["vocabulary"]
        self.assertNotIn("Actions & Poses", vocabulary, "the request's act is never replaced by an unrelated entry")
        self.assertIn("Lighting", vocabulary)
        self.assertNotIn("ACTIONS & POSES ENTRY", call.system_message)
        self.assertTrue(result["complete"])

    def test_fewer_entries_than_images_raise_the_cap(self):
        self.assertEqual(scenes.entries.entry_cap(["a", "b", "c"], 10), 4)
        self.assertEqual(scenes.entries.entry_cap(["a"] * 20, 10), 2)
        self.assertIsNone(scenes.entries.entry_cap([], 10))

    def test_unselected_subjects_never_supply_character_looks(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        for packs in ([], ["Spaces/Fantasy"]):
            with self.subTest(packs=packs):
                self.calls.clear()
                with patch("goated_prompter.features.vocabulary.catalog.read_pack",
                           side_effect=AssertionError("The supplied catalog needs no extra pack reads")):
                    result = self.write(self.brief("A couple", pair, amount=3), packs)
                self.assertTrue(result["complete"])
                for call in self.composer():
                    user = composer_user(call.user_message)
                    self.assertTrue(all("looks" not in image for image in user["images"]))
                    self.assertNotIn("Subjects\n", user.get("vocabulary", ""))
                    self.assertNotIn("An image lists a look for each character", call.system_message)

    def test_only_the_manually_selected_subjects_pack_is_sent(self):
        knight = [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        for pack_id in ("Subjects/Robots", "Subjects/Humans"):
            with self.subTest(pack=pack_id):
                self.calls.clear()
                result = self.write(self.brief("A knight", knight, amount=1), [pack_id])
                user = composer_user(self.composer()[0].user_message)
                self.assertNotIn("looks", user["images"][0])
                self.assertIn("Subjects\nCore instruction:", user["vocabulary"])
                pack = next(pack for pack in self.catalog["packs"] if pack["id"] == pack_id)
                sent = [entry for entry in pack["entries"] if entry in user["vocabulary"]]
                # A large pack is sampled (a different seeded sample per batch) so it never drowns the request.
                self.assertEqual(len(sent), min(len(pack["entries"]), scenes.VOCABULARY_SAMPLE))
                self.assertEqual([pack["id"] for pack in result["vocabulary"]["selection"]["packs"]], [pack_id])

    def test_the_seed_shuffles_the_vocabulary_order(self):
        def order(seed):
            self.calls.clear()
            brief = self.brief("A place", [], amount=1)
            brief["input"]["seed"] = seed
            self.write(brief, ["Subjects/Humans"])
            return composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertEqual(order(1), order(1))
        self.assertNotEqual(order(1), order(2))


if __name__ == "__main__":
    unittest.main()
