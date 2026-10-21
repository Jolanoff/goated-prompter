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
        self.romance = next(pack["entries"] for pack in self.catalog["packs"] if pack["id"] == "Actions & Poses/Romance")
        self.calls, self.entries, self.fit = [], [], None
        self.relevance = {}
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
            if "direct" in instruction.json_schema["properties"]:
                result = {level: [] for level in ("direct", "supporting", "optional", "conflict")}
                for number, row in entries.items():
                    level = self.relevance.get((row["category"], row["text"]), "direct")
                    if self.fit is not None and row["category"] == scenes.ACTIONS_CATEGORY and row["text"] not in self.fit:
                        level = "conflict"
                    result[level].append(int(number))
                return json.dumps(result)
            raise AssertionError("The fitting contract must classify every entry's relevance")
        if instruction.diagnostic_stage != "dataset_v2:scenes":
            return "A finished prompt."
        user = composer_user(instruction.user_message)
        labels = [person["label"] for person in user["understanding"]["characters"]]
        wants_entry = "entry_id" in instruction.json_schema["properties"]["scenes"]["items"]["required"]
        def entry_id(row):
            if not self.entries:
                return row["entry_id"]
            selected = self.entries.pop(0)
            return next((key for key, text in user["action_entries"].items() if text == selected), "unknown")
        return json.dumps({"scenes": [{
            "subjects": {label: {**SCENE, **{field: f"{field}{row['image']}{label}".replace(" ", "")
                                             for field in ("skin", "build", "hair", "detail")}} for label in labels},
            "position": {label: "standing" for label in labels},
            "actions": f"{' and '.join(labels)}: {user['request']}", "space": f"clearing {row['image']}", "lighting": "moonlight",
            "mood": "calm", "camera": "wide shot", "extras": f"extras{row['image']}",
            **({"entry_id": entry_id(row)} if wants_entry else {})}
            for row in user["images"]]})

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
        self.assertIn("Treat vocabulary entries as creative possibilities, not mandatory instructions.", call.system_message)
        self.assertIn("Do not create missing subjects merely to satisfy vocabulary entries.", call.system_message)
        self.assertIn("A selected category shapes that part of the images it fits", call.system_message)
        self.assertIn("It is optional for each image", call.system_message)

    def test_example_c_packs_of_an_adult_run_are_optional_material_beside_the_request(self):
        cast = [{"label": "model", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        packs = ["Actions & Poses/Solo-Activities", "Expressions/Happy-Expressions",
                 "Clothing/Modern-Fashion", "Objects/Furniture"]
        result = self.write(self.brief("A seductive adult character posing with a prop", cast, nsfw=True), packs)
        vocabulary = composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertEqual([line for line in vocabulary.split("\n") if line in {"Actions & Poses", "Expressions", "Clothing", "Objects & Props"}],
                         ["Actions & Poses", "Objects & Props", "Expressions", "Clothing"], "registry order")
        self.assertEqual(len(result["vocabulary"]["selection"]["packs"]), 4)

    def test_example_d_a_group_keeps_its_cast_from_understanding(self):
        group = [{"label": "adult", "gender": "", "custom": "", "pronoun": "", "count": 3}]
        result = self.write(self.brief("A group of adults in an intimate scene", group, nsfw=True),
                            ["Actions & Poses/Group-Interactions", "Mood & Tone/Romantic"])
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual([person["label"] for person in user["understanding"]["characters"]], ["adult 1", "adult 2", "adult 3"])
        self.assertTrue(all(set(scene["subjects"]) == {"adult 1", "adult 2", "adult 3"} for scene in result["scenes"]))

    def test_every_batch_gets_its_suggestions_and_the_writer_is_called_once_per_batch(self):
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=13)
        self.write(brief, ["Lighting/Dramatic"])
        calls = self.composer()
        self.assertEqual(len(calls), 2)
        for call in calls:
            user = composer_user(call.user_message)
            offered = {entry for image in user["images"] for entry in image["suggested"]["Lighting"]}
            self.assertEqual(set(user["vocabulary"].partition("Available vocabulary:\n")[2].splitlines()),
                             {f"[direct fit] {entry}" for entry in offered})
        self.assertEqual(sum(call.diagnostic_stage == "dataset_v2:entries" for call in self.calls), 1,
                         "one relevance pass is reused across batches")

    def test_every_image_gets_its_own_optional_suggestions_so_the_whole_pack_spreads(self):
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=4)
        self.write(brief, ["Lighting/Dramatic", "Objects/Furniture"])
        images = composer_user(self.composer()[0].user_message)["images"]
        hands = [image["suggested"] for image in images]
        self.assertEqual({tuple(sorted(hand)) for hand in hands}, {("Lighting", "Objects & Props")})
        for category in ("Lighting", "Objects & Props"):
            dealt = [entry for hand in hands for entry in hand[category]]
            self.assertTrue(all(len(set(hand[category])) == len(hand[category]) for hand in hands), "no repeat in a hand")
            pack = {"Lighting": "Lighting/Dramatic", "Objects & Props": "Objects/Furniture"}[category]
            self.assertEqual(set(dealt), set(next(p for p in self.catalog["packs"] if p["id"] == pack)["entries"]),
                             "every entry is dealt")
        self.assertIn('none at all when the category does not fit the image', self.composer()[0].system_message)

    def test_pack_descriptions_reach_the_scene_writer_and_the_fitting_call(self):
        catalog = load_catalog(user_root=False)
        for pack in catalog["packs"]:
            if pack["id"] in ("Actions & Poses/Solo-Activities", "Lighting/Dramatic"):
                pack["description"] = f"note for {pack['name']}"
        brief = self.brief("A knight", [{"label": "knight", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], amount=2)
        self.write(brief, ["Actions & Poses/Solo-Activities", "Lighting/Dramatic"], catalog=catalog)
        vocabulary = composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertIn('Pack "Dramatic" (its author\'s note: note for Dramatic):', vocabulary)
        self.assertIn("its author's note", self.composer()[0].system_message)
        fit = next(call for call in self.calls if call.diagnostic_stage == "dataset_v2:entries")
        rows = json.loads(fit.user_message)["entries"].values()
        self.assertEqual({row["category"] for row in rows}, {"Actions & Poses", "Lighting"})
        for row in rows:
            self.assertEqual(row["notes"], ["note for " + {"Actions & Poses": "Solo Activities", "Lighting": "Dramatic"}[row["category"]]])

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
        builder = [call for call in self.calls if call.diagnostic_stage not in ("dataset_v2:scenes", "dataset_v2:entries")]
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
        self.assertIn(self.romance[1], vocabulary)
        for rule in ("If it does, that pose is\n   decided", "If it defines only an\n   action, choose a pose",
                     "correct gender", "Objects, furniture and surfaces named in an entry", "keeping the pose physically the same"):
            self.assertIn(rule, call.system_message)
        for rule in ("replace those placeholders with the actual subject names",
                     "A group arrangement uses exactly the requested number of people"):
            self.assertIn(rule, vocabulary)

    def test_every_image_is_dealt_its_own_entry_by_the_seed(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.entries = self.romance[:3].copy()
        self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        dealt = [image["entry_id"] for image in composer_user(self.composer()[0].user_message)["images"]]
        self.assertEqual(len(set(dealt)), 3, "no entry is dealt twice while the pack has more")
        import random
        entries = [f"entry {number}" for number in range(10)]
        self.assertEqual(scenes.deal_entries(entries, 10, random.Random(4)), scenes.deal_entries(entries, 10, random.Random(4)))
        self.assertNotEqual(scenes.deal_entries(entries, 10, random.Random(4)), scenes.deal_entries(entries, 10, random.Random(5)))
        self.assertEqual(sorted(scenes.deal_entries(entries, 10, random.Random(4)).values()), sorted(entries))
        self.assertEqual(scenes.deal_entries([], 3, random.Random(4)), {})

    def test_composer_selects_a_reference_instead_of_returning_canonical_text(self):
        cast = [{"label": "guide", "gender": "", "custom": "", "pronoun": "", "count": 2}]
        self.write(self.brief("Two guides consulting a map", cast, amount=1), ["Actions & Poses/Romance"])
        call = self.composer()[0]
        item = call.json_schema["properties"]["scenes"]["items"]
        self.assertNotIn("entry", item["properties"])
        self.assertIn("entry_id", item["required"])
        choices = composer_user(call.user_message)["action_entries"]
        self.assertEqual(set(item["properties"]["entry_id"]["enum"]), set(choices))
        self.assertEqual(list(choices.values()), self.romance)
        self.assertNotIn("Copy the entry you used word for word", call.system_message)

    def test_placeholder_actions_are_repaired_without_assigning_roles_in_code(self):
        for count in (2, 4):
            with self.subTest(people=count):
                self.calls.clear()
                labels = ["curator", "courier", *[f"observer {n}" for n in range(1, count - 1)]]
                cast = [{"label": label, "gender": "", "custom": "", "pronoun": "", "count": 1} for label in labels]
                entry = "one person passes a map to the other person" if count == 2 else (
                    "one person passes a map to another while the others watch from beside them")
                catalog = {**self.catalog, "packs": [{**pack, "entries": [entry]} if pack["id"] == "Actions & Poses/Romance"
                                                    else pack for pack in self.catalog["packs"]]}
                action = "courier passes the map to curator" + (" while observer 1 and observer 2 watch" if count == 4 else "")
                positions = {"courier": "left, standing facing curator, holding the map out",
                             "curator": "right, standing facing courier, reaching for the map"}
                positions.update({label: "standing beside curator, watching courier hand over the map" for label in labels[2:]})
                emitted = []

                def generate(instruction):
                    response = self.generate(instruction)
                    if instruction.diagnostic_stage != "dataset_v2:scenes":
                        return response
                    scene = json.loads(response)["scenes"][0]
                    scene.update(actions=entry if not emitted else action, position=positions)
                    emitted.append(scene)
                    return json.dumps({"scenes": [scene]})

                self.backend.generate.side_effect = generate
                result = self.write(self.brief("courier hands a map to curator; any observers watch", cast, amount=1),
                                    ["Actions & Poses/Romance"], catalog=catalog)
                self.assertTrue(result["complete"])
                self.assertEqual(len(self.composer()), 2, "placeholder leakage must still trigger repair")
                self.assertIn("its actions do not name", self.composer()[1].system_message)
                finished = result["scenes"][0]
                self.assertEqual(finished["actions"], action, "giver follows request, not first cast label")
                self.assertEqual(finished["position"], positions)
                self.assertEqual(finished["entry"], entry)
                self.assertNotIn("entry_id", finished)
                self.assertEqual(set(finished["subjects"]), set(labels))
                for field in ("subjects", "extras", "space", "camera"):
                    self.assertEqual(finished[field], scenes.retire_fields(emitted[-1])[field])

    def test_a_compatible_alternative_keeps_its_exact_reference_and_named_builder_handoff(self):
        first = "one person carries the other person in their arms"
        alternative = "Piggyback: one person carries the other person on their back."
        catalog = {**self.catalog, "packs": [{**pack, "entries": [alternative, first]} if pack["id"] == "Actions & Poses/Romance"
                                            else pack for pack in self.catalog["packs"]]}
        cast = [{"label": label, "gender": "", "custom": "", "pronoun": "", "count": 1} for label in ("rider", "carrier")]
        action = "carrier carries rider in a Piggyback"
        positions = {"carrier": "standing, supporting rider on carrier's back with both arms under rider's thighs",
                     "rider": "on carrier's back, facing forward, arms around carrier's shoulders"}

        def generate(instruction):
            response = self.generate(instruction)
            if instruction.diagnostic_stage != "dataset_v2:scenes":
                return response
            user = composer_user(instruction.user_message)
            self.assertEqual(user["images"][0]["entry_id"], "2", "seed deals the other compatible entry")
            scene = json.loads(response)["scenes"][0]
            scene.update(entry_id="1", actions=action, position=positions)
            return json.dumps({"scenes": [scene]})

        self.backend.generate.side_effect = generate
        result = self.write(self.brief("carrier carries rider", cast, amount=1), ["Actions & Poses/Romance"], catalog=catalog)
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.composer()), 1)
        scene = result["scenes"][0]
        self.assertEqual(scene["entry"], alternative)
        self.assertEqual(scene["actions"], action)
        self.assertEqual(scene["position"], positions)
        self.assertEqual(set(scene["subjects"]), {"rider", "carrier"})
        prompts.write_prompts({"backend": "mock"}, self.request, self.brief("carrier carries rider", cast, amount=1),
                              result["scenes"], progress=lambda _: None)
        builder = self.calls[-1]
        self.assertIn("position name: Piggyback", builder.user_message)
        self.assertIn(action, builder.user_message)
        self.assertNotIn(alternative, builder.user_message, "canonical placeholder text is not Builder input")

    def test_unknown_entry_ids_never_become_saved_vocabulary_references(self):
        cast = [{"label": "guide", "gender": "", "custom": "", "pronoun": "", "count": 2}]
        self.entries = ["unknown vocabulary"] * scenes.ROUNDS
        result = self.write(self.brief("Two guides", cast, amount=1), ["Actions & Poses/Romance"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["scenes"], [])
        self.assertEqual(len(self.composer()), scenes.ROUNDS)
        self.assertIn("entry_id", result["missing"][0]["reasons"][0])

    def test_reference_binding_does_not_admit_an_extra_participant(self):
        cast = [{"label": "guide", "gender": "", "custom": "", "pronoun": "", "count": 2}]
        emitted = []

        def generate(instruction):
            response = self.generate(instruction)
            if instruction.diagnostic_stage != "dataset_v2:scenes":
                return response
            scene = json.loads(response)["scenes"][0]
            if not emitted:
                scene["subjects"]["visitor"] = dict(SCENE)
                scene["position"]["visitor"] = "beside the guides"
            emitted.append(scene)
            return json.dumps({"scenes": [scene]})

        self.backend.generate.side_effect = generate
        result = self.write(self.brief("Two guides", cast, amount=1), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.composer()), 2)
        self.assertIn("exactly guide 1, guide 2", self.composer()[1].system_message)
        scene = result["scenes"][0]
        self.assertEqual(set(scene["subjects"]), {"guide 1", "guide 2"})
        self.assertEqual(set(scene["position"]), {"guide 1", "guide 2"})

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

    def test_bundled_position_names_reach_builder_only_when_the_actions_keep_them(self):
        named = [entry for pack in self.catalog["packs"] if pack["category"] == "Actions & Poses"
                 for entry in pack["entries"] if ":" in entry]
        self.assertTrue(named, "bundled actions must exercise the existing named-position handoff")
        for entry in named:
            name = entry.partition(":")[0]
            with self.subTest(name=name):
                scene = {"slot": 1, "subjects": {}, "position": {}, "actions": entry,
                         "space": "hall", "lighting": "lamps", "mood": "calm", "camera": "wide",
                         "extras": "none", "entry": entry}
                self.assertEqual(prompts.position_name(scene), name)
                self.assertIn(f"position name: {name}\n", prompts.scene_text(scene))
                scene["actions"] = "The people stand apart and examine a map."
                self.assertEqual(prompts.position_name(scene), "")
                self.assertNotIn("position name:", prompts.scene_text(scene))


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
        self.assertFalse(any(call.diagnostic_stage == "dataset_v2:entries" for call in self.calls))
        self.assertEqual(result["vocabulary"], {"selection": {"packs": []}})

    def test_an_entry_is_used_by_at_most_two_images_and_an_overused_one_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        first, second = self.romance[:2]
        self.entries = [first] * 3 + [second]
        result = self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual([scene["entry"] for scene in result["scenes"]],
                         [first, first, second])
        retry = self.composer()[1]
        self.assertIn(f'the entry "{first}" is already used by 2 images', retry.system_message)
        self.assertEqual(composer_user(retry.user_message)["already_used"]["entries"], {first: 2})
        self.assertIn("used by fewer than 2 images", self.composer()[0].system_message)

    def test_an_entry_that_is_not_in_the_vocabulary_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        expected = self.romance[2]
        self.entries = ["a made-up entry", expected]
        result = self.write(self.brief("A couple", pair, amount=1), ["Actions & Poses/Romance"])
        self.assertEqual(result["scenes"][0]["entry"], expected)
        self.assertIn('"entry_id" must be one of the IDs in action_entries', self.composer()[1].system_message)

    def test_only_entries_that_fit_the_request_are_offered_dealt_and_counted(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.fit = self.romance[:2]
        self.entries = self.fit * 2 + [self.fit[0]]
        result = self.write(self.brief("A couple dancing", pair, amount=5), ["Actions & Poses/Romance"])
        fitting = [call for call in self.calls if call.diagnostic_stage == "dataset_v2:entries"]
        self.assertEqual(len(fitting), 1)
        self.assertIn("A couple dancing", fitting[0].user_message)
        self.assertIn('"cast"', fitting[0].user_message)
        first = self.composer()[0]
        vocabulary = composer_user(first.user_message)["vocabulary"]
        for entry in self.fit:
            self.assertIn(entry, vocabulary)
        self.assertNotIn(self.romance[2], vocabulary, "an entry that does not fit is never offered")
        user = composer_user(first.user_message)
        self.assertEqual({user["action_entries"][image["entry_id"]] for image in user["images"]}, set(self.fit))
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

    def test_a_failed_fitting_call_keeps_no_unassessed_entry(self):
        self.assertEqual(scenes.fitting_entries(Mock(generate=Mock(return_value="not json")),
                                                {"_family": "qwen", "input": {"request": "x", "seed": 1}, "summary": "",
                                                 "fixed": "", "must": [], "avoid": [], "characters": []},
                                                 [{"category": "Spaces", "packs": [{"entries": ["a", "b"]}]}],
                                                 progress=lambda _: None), {})

    def relevance_catalog(self):
        packs = [
            {"id": "actions/team", "name": "Team", "category": "Actions & Poses", "entries": [
                "Three people brace a beam together.", "Three people carry a beam together.",
                "Three people lift a beam together.", "Three people lower a beam together."]},
            {"id": "actions/other", "name": "Other", "category": "Actions & Poses", "entries": [
                "One person checks a knot.", "One person polishes a medal.", "Five people race each other."]},
            {"id": "objects/other", "name": "Other", "category": "Objects & Props", "entries": [
                "a load-bearing rope", "a secure anchor", "a polished medal", "a ceremonial banner"]},
            {"id": "spaces/works", "name": "Works", "category": "Spaces", "entries": [
                "a damaged bridge", "a supported walkway", "a ballroom"]}]
        self.relevance = {
            ("Actions & Poses", "One person checks a knot."): "supporting",
            ("Actions & Poses", "One person polishes a medal."): "optional",
            ("Actions & Poses", "Five people race each other."): "conflict",
            ("Objects & Props", "a secure anchor"): "supporting",
            ("Objects & Props", "a polished medal"): "optional",
            ("Objects & Props", "a ceremonial banner"): "conflict",
            ("Spaces", "a ballroom"): "conflict"}
        return {**self.catalog, "packs": packs}

    def test_relevance_keeps_group_anchors_and_individual_support_separate(self):
        catalog = self.relevance_catalog()
        cast = [{"label": "worker", "gender": "", "custom": "", "pronoun": "", "count": 3}]
        brief = self.brief("Three workers stabilize a damaged bridge together", cast, amount=10)
        result = self.write(brief, [pack["id"] for pack in catalog["packs"]], catalog=catalog)
        user = composer_user(self.composer()[0].user_message)
        team = catalog["packs"][0]["entries"]
        self.assertEqual(set(user["action_entries"].values()), set(team))
        self.assertTrue(all(scene["entry"] in team for scene in result["scenes"]))
        self.assertEqual({label for scene in result["scenes"] for label in scene["subjects"]},
                         {"worker 1", "worker 2", "worker 3"})
        self.assertTrue(all(set(scene["subjects"]) == set(scene["position"]) for scene in result["scenes"]))
        self.assertTrue(all(not scenes.unnamed_people(scene, ["worker 1", "worker 2", "worker 3"])
                            for scene in result["scenes"]))
        sent = self.composer()[0].user_message
        for entry in ("Five people race each other.", "a ceremonial banner", "a ballroom"):
            self.assertNotIn(entry, sent)
        suggestions = [image.get("suggested", {}) for image in user["images"]]
        self.assertIn("One person checks a knot.", [entry for hand in suggestions for entry in hand.get("Actions & Poses", [])])
        self.assertIn("a secure anchor", [entry for hand in suggestions for entry in hand.get("Objects & Props", [])])
        self.assertEqual(len(set(scene["entry"] for scene in result["scenes"])), 4)

    def test_relevance_preferences_are_seeded_and_optional_does_not_dominate(self):
        import random
        entries = [f"entry {n}" for n in range(20)]
        levels = {entry: "direct" if n < 4 else "supporting" if n < 8 else "optional"
                  for n, entry in enumerate(entries)}
        dealt = scenes.deal_entries(entries, 10, random.Random(7), levels)
        self.assertEqual(dealt, scenes.deal_entries(entries, 10, random.Random(7), levels))
        self.assertNotEqual(dealt, scenes.deal_entries(entries, 10, random.Random(8), levels))
        self.assertGreaterEqual(sum(levels[entry] == "direct" for entry in dealt.values()), 5)
        self.assertLessEqual(sum(levels[entry] == "optional" for entry in dealt.values()), 2)
        self.assertGreaterEqual(len(set(dealt.values())), 6)

    def test_relevance_failure_omits_unassessed_vocabulary_without_losing_scenes(self):
        catalog = self.relevance_catalog()
        original = self.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset_v2:entries":
                self.calls.append(instruction)
                return "not json"
            return original(instruction)
        self.backend.generate.side_effect = generate
        result = self.write(self.brief("Workers stabilize a bridge", [
            {"label": "worker", "gender": "", "custom": "", "pronoun": "", "count": 3}], amount=2),
                            [pack["id"] for pack in catalog["packs"]], catalog=catalog)
        self.assertTrue(result["complete"])
        self.assertNotIn("SELECTED VOCABULARY", self.composer()[0].user_message)
        self.assertNotIn("entry_id", self.composer()[0].json_schema["properties"]["scenes"]["items"]["required"])
        self.assertTrue(all("entry" not in scene for scene in result["scenes"]))

    def test_fitting_covers_actual_entries_constraints_and_roles_not_pack_names(self):
        catalog = self.relevance_catalog()
        brief = self.brief("Three workers stabilize a damaged bridge together", [
            {"label": "worker", "gender": "", "custom": "", "pronoun": "", "count": 3}])
        brief.update(fixed="worker 1 steadies the beam", must=["worker 2 secures a rope"], avoid=["no racing"])
        brief["input"]["rules"] = ["worker 3 directs the lift"]
        brief["_family"] = "qwen"
        catalog["packs"][2]["description"] = "These objects can support practical work."
        groups = scenes.selected_vocabulary(catalog, {"packs": [pack["id"] for pack in catalog["packs"]]})
        fit = scenes.fitting_entries(self.backend, brief, groups, progress=lambda _: None)
        self.assertEqual(fit["Objects & Props"], {"a load-bearing rope": "direct", "a secure anchor": "supporting",
                                                   "a polished medal": "optional"})
        self.assertNotIn("Five people race each other.", fit["Actions & Poses"])
        data = json.loads(self.calls[0].user_message)
        self.assertEqual([person["label"] for person in data["cast"]], ["worker 1", "worker 2", "worker 3"])
        for field in ("fixed", "must", "avoid"):
            self.assertEqual(data[field], brief[field])
        self.assertEqual(data["rules"], brief["input"]["rules"])
        anchor = next(row for row in data["entries"].values() if row["text"] == "a secure anchor")
        self.assertEqual(anchor["notes"], [catalog["packs"][2]["description"]])
        self.assertNotIn("name", anchor, "pack titles are not a relevance proxy")

    def test_all_conflicts_generate_from_request_and_support_alone_never_binds_the_main_action(self):
        for level in ("conflict", "supporting", "optional"):
            with self.subTest(level=level):
                self.calls.clear()
                catalog = self.relevance_catalog()
                catalog["packs"] = [catalog["packs"][1]]
                self.relevance = {("Actions & Poses", entry): level for entry in catalog["packs"][0]["entries"]}
                brief = self.brief("A team braces a beam", [], amount=10)
                result = self.write(brief, ["actions/other"], catalog=catalog)
                user = composer_user(self.composer()[0].user_message)
                self.assertTrue(result["complete"])
                self.assertNotIn("action_entries", user)
                self.assertTrue(all("entry" not in scene for scene in result["scenes"]))
                if level == "conflict":
                    self.assertFalse(user["vocabulary"])
                    self.assertTrue(all("suggested" not in image for image in user["images"]))
                else:
                    self.assertTrue(any("suggested" in image for image in user["images"]))

    def test_optional_only_category_is_occasional_and_never_requires_every_pack(self):
        import random
        catalog = self.relevance_catalog()
        groups = scenes.selected_vocabulary(catalog, {"packs": ["objects/other"]})
        entries = catalog["packs"][2]["entries"]
        levels = {"Objects & Props": {entry: "optional" for entry in entries}}
        hands = scenes.deal_hands(groups, 10, random.Random(7), levels)
        self.assertEqual(set(hands), {4, 8})
        self.assertTrue(all(len(hand["Objects & Props"]) == 1 for hand in hands.values()))
        self.assertEqual(hands, scenes.deal_hands(groups, 10, random.Random(7), levels))

    def test_invalid_relevance_partitions_fail_closed(self):
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 1}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        groups = [{"category": "Spaces", "packs": [{"entries": ["one", "two"]}]}]
        for direct, supporting in (([1, 1, 2], []), ([1, 2, 3], []), ([1, 2], [1]), ([0, 1, 2], []),
                                   ([-1, 1, 2], []), ([True, 2], []), (["1", 2], [])):
            with self.subTest(direct=direct, supporting=supporting):
                response = json.dumps({"direct": direct, "supporting": supporting, "optional": [], "conflict": []})
                self.assertEqual(scenes.fitting_entries(Mock(generate=Mock(return_value=response)), brief, groups,
                                                       progress=lambda _: None), {})

    def test_captured_52_of_80_judgment_preserves_verified_entries_and_recovers_only_missing(self):
        # Exact numbered response from 20261021-161511; synthetic texts keep the regression independent of packs.
        response = {"direct": [21, 24], "supporting": [18, 30, 56, 57, 58],
                    "optional": [53, 54, 55, 59, 60, 65, 66],
                    "conflict": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
                                 19, 20, 22, 23, 25, 26, 27, 28, 29, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42]}
        classified = {number for numbers in response.values() for number in numbers}
        self.assertEqual(len(classified), 52)
        missing = [number for number in range(1, 81) if number not in classified]
        groups = [{"category": "Spaces", "packs": [{"entries": [f"place {n}" for n in range(1, 81)]}]}]
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 173}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        recovery = {"direct": [], "supporting": list(range(1, 29)), "optional": [], "conflict": []}
        backend = Mock(generate=Mock(side_effect=[json.dumps(response), json.dumps(recovery)]))
        with patch.object(scenes, "FIT_CHUNK", 80):
            fit = scenes.fitting_entries(backend, brief, groups, progress=lambda _: None)
        expected = {f"place {n}": level for level in scenes.RELEVANCE[:-1] for n in response[level]}
        expected.update({f"place {n}": "supporting" for n in missing})
        self.assertEqual(fit, {"Spaces": expected})
        self.assertEqual(backend.generate.call_count, 2)
        retry = json.loads(backend.generate.call_args_list[1].args[0].user_message)
        self.assertEqual([row["text"] for row in retry["entries"].values()], [f"place {n}" for n in missing])

    def test_incomplete_recovery_is_bounded_and_unassessed_entries_are_not_promoted(self):
        groups = [{"category": "Spaces", "packs": [{"entries": ["one", "two", "three", "four"]}]}]
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 1}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        backend = Mock(generate=Mock(side_effect=[
            json.dumps({"direct": [1], "supporting": [], "optional": [], "conflict": [2]}),
            json.dumps({"direct": [], "supporting": [1], "optional": [], "conflict": []})]))
        messages = []
        fit = scenes.fitting_entries(backend, brief, groups, progress=messages.append)
        self.assertEqual(fit, {"Spaces": {"one": "direct", "three": "supporting"}})
        self.assertEqual(backend.generate.call_count, 2)
        self.assertTrue(any("1" in message and "unassessed" in message for message in messages))

    def test_malformed_recovery_preserves_valid_judgments_without_extra_retries(self):
        groups = [{"category": "Spaces", "packs": [{"entries": ["one", "two"]}]}]
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 1}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        for recovery in ("not json", '{"direct":[1],"supporting":[1],"optional":[],"conflict":[]}'):
            with self.subTest(recovery=recovery):
                backend = Mock(generate=Mock(side_effect=[
                    '{"direct":[1],"supporting":[],"optional":[],"conflict":[]}', recovery]))
                self.assertEqual(scenes.fitting_entries(backend, brief, groups, progress=lambda _: None),
                                 {"Spaces": {"one": "direct"}})
                self.assertEqual(backend.generate.call_count, 2)

    def test_small_mixed_chunks_preserve_valid_packs_when_another_chunk_is_malformed(self):
        groups = [{"category": category, "packs": [
            {"entries": [f"{category} idea {pack}-{n}" for n in range(10)], "description": f"note {pack}"}
            for pack in range(2)]} for category in ("Spaces", "Objects & Props", "Actions & Poses")]
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 173}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        calls, expected = [], {}
        def generate(instruction):
            calls.append(instruction)
            rows = json.loads(instruction.user_message)["entries"]
            self.assertLessEqual(len(rows), 20)
            self.assertEqual(instruction.seed, 173)
            self.assertTrue(all(row.get("notes") for row in rows.values()))
            if len(calls) == 2:
                return "not json"
            result = {level: [] for level in scenes.RELEVANCE}
            for number, row in rows.items():
                level = scenes.RELEVANCE[(int(number) - 1) % 4]
                result[level].append(int(number))
                if level != "conflict":
                    expected.setdefault(row["category"], {})[row["text"]] = level
            return json.dumps(result)
        messages = []
        fit = scenes.fitting_entries(Mock(generate=Mock(side_effect=generate)), brief, groups, progress=messages.append)
        self.assertEqual(fit, expected)
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(fit), {"Spaces", "Actions & Poses"})
        self.assertEqual(sum(map(len, fit.values())), 30)
        self.assertIn("Vocabulary assessed: 40/60 entries; 30 compatible choices retained.", messages)

    def test_complete_small_chunk_needs_no_recovery_and_reports_full_coverage(self):
        catalog = self.relevance_catalog()
        brief = self.brief("A team stabilizes a bridge", [], amount=10)
        brief["_family"] = "qwen"
        groups = scenes.selected_vocabulary(catalog, {"packs": [pack["id"] for pack in catalog["packs"]]})
        messages = []
        fit = scenes.fitting_entries(self.backend, brief, groups, progress=messages.append)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(set(fit), {"Actions & Poses", "Spaces", "Objects & Props"})
        self.assertIn("Vocabulary assessed: 14/14 entries; 11 compatible choices retained.", messages)

    def test_failed_chunk_does_not_restore_conflicts_or_erase_successful_chunks(self):
        groups = [{"category": "Spaces", "packs": [{"entries": ["one", "two", "three", "four", "five"]}]}]
        brief = {"_family": "qwen", "input": {"request": "work", "seed": 1}, "summary": "",
                 "fixed": "", "must": [], "avoid": [], "characters": []}
        responses = [json.dumps({"direct": [1], "supporting": [], "optional": [], "conflict": [2]}), "not json",
                     json.dumps({"direct": [], "supporting": [1], "optional": [], "conflict": []})]
        backend = Mock(generate=Mock(side_effect=responses))
        with patch.object(scenes, "FIT_CHUNK", 2):
            fit = scenes.fitting_entries(backend, brief, groups, progress=lambda _: None)
        self.assertEqual(fit, {"Spaces": {"one": "direct", "five": "supporting"}})
        self.assertEqual(backend.generate.call_count, 3, "no extra retry stage")

    def test_request_aware_prompt_and_dealing_repeat_for_the_same_seed(self):
        catalog = self.relevance_catalog()
        brief = self.brief("A team stabilizes a damaged bridge", [], amount=10)
        packs = [pack["id"] for pack in catalog["packs"]]
        def run(seed):
            self.calls.clear()
            brief["input"]["seed"] = seed
            result = self.write(brief, packs, catalog=catalog)
            return self.composer()[0].user_message, result["scenes"]
        self.assertEqual(run(7), run(7))
        self.assertNotEqual(run(7), run(8))

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
                self.assertEqual(set(sent), set(user["images"][0]["suggested"]["Subjects"]),
                                 "the prompt offers the batch's request-aware suggestions")
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
