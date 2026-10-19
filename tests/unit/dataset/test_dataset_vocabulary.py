"""Selected vocabulary in the existing Dataset scene writer: only what the user picked, grouped under its Core
instruction, as optional material. The scene writer is scripted, so this checks what it receives, not how a live
model uses it."""

import json
import unittest
from unittest.mock import Mock, patch
from tests.helpers import enter_context

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.features.dataset.v2.tickets import intent_signature
from goated_prompter.features.vocabulary.catalog import load_catalog
from tests.support.dataset_scenes import composer_user

SCENE = {"skin": "fair", "build": "slim", "hair": "long silver hair", "detail": "a freckled nose", "expression": "a soft smile", "clothing": "a robe"}


class SceneVocabulary(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(user_root=False)
        self.calls, self.entries, self.fit = [], [], None
        self.backend = MockBackend()
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        enter_context(self, patch.object(scenes, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.request = GoatedPrompterRequest(idea="dataset", planning_mode="Direct", director_preset="general_director")

    def brief(self, subject, cast, *, nsfw=False, amount=2):
        data = {**default_dataset_draft(), "subject": subject, "amount": amount, "nsfw": nsfw, "seed": 7, "seed_mode": "fixed"}
        value = {"path": "character" if cast else "non_character", "summary": subject, "fixed": "", "randomized": "",
                 "must": [], "avoid": [], "characters": cast}
        return understanding.apply_rules(value, data)

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage == "dataset_v2:entries":
            entries = json.loads(instruction.user_message)["entries"]
            if self.fit is None:
                return json.dumps({"fit": [int(number) for number in entries]})
            return json.dumps({"fit": [int(number) for number, entry in entries.items() if entry in self.fit]})
        if instruction.diagnostic_stage != "dataset_v2:scenes":
            return "A finished prompt."
        user = composer_user(instruction.user_message)
        labels = [person["label"] for person in user["understanding"]["characters"]]
        wants_entry = "entry" in instruction.json_schema["properties"]["scenes"]["items"]["required"]
        return json.dumps({"scenes": [{
            "subjects": {label: dict(SCENE) for label in labels}, "position": {label: "standing" for label in labels},
            "actions": user["request"], "space": f"clearing {row['image']}", "lighting": "moonlight",
            "mood": "calm", "camera": "wide shot", "extras": "none",
            **({"entry": self.entries.pop(0) if self.entries else "two people slow dancing"} if wants_entry else {})}
            for row in user["images"]]})

    def write(self, brief, packs=()):
        return scenes.write_scenes({"backend": "mock"}, self.request, brief, progress=lambda _: None,
                                   vocabulary={"packs": list(packs)}, catalog=self.catalog)

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
        self.assertIn("Treat vocabulary entries as creative possibilities, not mandatory instructions.", call.system_message)
        self.assertIn("Do not create missing subjects merely to satisfy vocabulary entries.", call.system_message)
        self.assertIn("A selected category shapes that part of every image", call.system_message)

    def test_example_c_packs_of_an_adult_run_are_optional_material_beside_the_request(self):
        cast = [{"label": "model", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        packs = ["Actions & Poses/Solo-Activities", "Expressions/Happy-Expressions",
                 "Clothing/Modern-Fashion", "Objects/Furniture"]
        result = self.write(self.brief("A seductive adult character posing with a prop", cast, nsfw=True), packs)
        vocabulary = composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertEqual([line for line in vocabulary.split("\n") if line in {"Actions & Poses", "Expressions", "Clothing", "Objects"}],
                         ["Actions & Poses", "Objects", "Expressions", "Clothing"], "registry order")
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
        self.assertEqual(composer_user(calls[0].user_message)["vocabulary"], composer_user(calls[1].user_message)["vocabulary"])
        self.assertEqual({call.diagnostic_stage for call in self.calls}, {"dataset_v2:scenes"}, "no extra LLM call")

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
        self.assertIn("one person kissing the other person's forehead", vocabulary)
        for rule in ("If it does, that pose is\n   decided", "If it defines only an\n   action, choose a pose",
                     "correct gender", "Objects, furniture and surfaces named in an entry", "keeping the pose physically the same"):
            self.assertIn(rule, call.system_message)

    def test_every_image_is_dealt_its_own_entry_by_the_seed(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = ["two people slow dancing", "two people holding hands", "one person kissing the other person's forehead"]
        self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        dealt = [image["entry"] for image in composer_user(self.composer()[0].user_message)["images"]]
        self.assertEqual(len(set(dealt)), 3, "no entry is dealt twice while the pack has more")
        import random
        entries = [f"entry {number}" for number in range(10)]
        self.assertEqual(scenes.deal_entries(entries, 10, random.Random(4)), scenes.deal_entries(entries, 10, random.Random(4)))
        self.assertNotEqual(scenes.deal_entries(entries, 10, random.Random(4)), scenes.deal_entries(entries, 10, random.Random(5)))
        self.assertEqual(sorted(scenes.deal_entries(entries, 10, random.Random(4)).values()), sorted(entries))
        self.assertEqual(scenes.deal_entries([], 3, random.Random(4)), {})

    def test_a_scene_may_keep_neutral_wording_from_an_entry(self):
        labels = ["man", "woman"]
        scene = {"subjects": {label: dict(SCENE) for label in labels}, "position": {"man": "kneeling", "woman": "on all fours"},
                 "actions": "one person kneels behind the other person", "space": "a cabin", "lighting": "lamp",
                 "mood": "warm", "camera": "side view", "extras": "rug"}
        self.assertEqual(scenes.scene_errors(scene, labels, []), [])

    def test_the_builder_gets_the_position_name_of_the_entry(self):
        scene = {"slot": 1, "subjects": {}, "position": {}, "actions": "they dance", "space": "hall", "lighting": "lamps",
                 "mood": "warm", "camera": "wide", "extras": "none", "entry": "slow dance: two people dancing close"}
        self.assertNotIn("position name", prompts.scene_text(scene), "The writer adapted the entry: its name would mislead.")
        scene["actions"] = "they hold each other in a Slow  Dance"
        self.assertIn("in a Slow  Dance\nposition name: slow dance\n", prompts.scene_text(scene))
        self.assertEqual(prompts.position_name({**scene, "entry": "two people holding hands"}), "")
        self.assertIn("use that name word for word", prompts.SCENE_RULES)


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

    def test_an_entry_is_used_by_at_most_two_images_and_an_overused_one_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = ["two people slow dancing"] * 3 + ["two people holding hands"]
        result = self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual([scene["entry"] for scene in result["scenes"]],
                         ["two people slow dancing", "two people slow dancing", "two people holding hands"])
        retry = self.composer()[1]
        self.assertIn('the entry "two people slow dancing" is already used by 2 images', retry.system_message)
        self.assertEqual(composer_user(retry.user_message)["already_used"]["entries"], {"two people slow dancing": 2})
        self.assertIn("used by fewer than 2 images", self.composer()[0].system_message)

    def test_an_entry_that_is_not_in_the_vocabulary_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = ["a made-up entry", "Two People   Holding Hands"]
        result = self.write(self.brief("A couple", pair, amount=1), ["Actions & Poses/Romance"])
        self.assertEqual(result["scenes"][0]["entry"], "two people holding hands")
        self.assertIn("copied word for word", self.composer()[1].system_message)

    def test_only_entries_that_fit_the_request_are_offered_dealt_and_counted(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.fit = ["two people slow dancing", "two people holding hands"]
        self.entries = ["two people slow dancing", "two people holding hands"] * 2 + ["two people slow dancing"]
        result = self.write(self.brief("A couple dancing", pair, amount=5), ["Actions & Poses/Romance"])
        fitting = [call for call in self.calls if call.diagnostic_stage == "dataset_v2:entries"]
        self.assertEqual(len(fitting), 1)
        self.assertIn("A couple dancing", fitting[0].user_message)
        self.assertIn('"cast"', fitting[0].user_message)
        first = self.composer()[0]
        vocabulary = composer_user(first.user_message)["vocabulary"]
        self.assertIn("two people slow dancing", vocabulary)
        self.assertNotIn("one person kissing the other person's forehead", vocabulary, "an entry that does not fit is never offered")
        self.assertEqual({image["entry"] for image in composer_user(first.user_message)["images"]}, set(self.fit))
        self.assertIn("used by fewer than 3 images", first.system_message, "five images share two fitting entries")
        self.assertTrue(result["complete"])

    def test_when_no_entry_fits_the_writer_gets_no_actions_vocabulary(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.fit = []
        result = self.write(self.brief("A couple", pair, amount=2), ["Actions & Poses/Romance", "Lighting/Dramatic"])
        call = self.composer()[0]
        vocabulary = composer_user(call.user_message)["vocabulary"]
        self.assertNotIn("Actions & Poses", vocabulary)
        self.assertIn("Lighting", vocabulary)
        self.assertNotIn("ACTIONS & POSES ENTRY", call.system_message)
        self.assertTrue(result["complete"])

    def test_a_failed_fitting_call_keeps_every_entry(self):
        self.assertEqual(scenes.fitting_entries(Mock(generate=Mock(return_value="not json")),
                                                {"_family": "qwen", "input": {"request": "x", "seed": 1}, "summary": "",
                                                 "fixed": "", "must": [], "avoid": [], "characters": []},
                                                ["a", "b"], progress=lambda _: None), ["a", "b"])

    def test_fewer_entries_than_images_raise_the_cap(self):
        self.assertEqual(scenes.entry_cap(["a", "b", "c"], 10), 4)
        self.assertEqual(scenes.entry_cap(["a"] * 20, 10), 2)
        self.assertIsNone(scenes.entry_cap([], 10))

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
