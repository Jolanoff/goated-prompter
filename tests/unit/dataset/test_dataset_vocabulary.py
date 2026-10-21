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
            from itertools import zip_longest
            categories = {}
            for number, row in entries.items():
                if self.fit is None or row["category"] != scenes.ACTIONS_CATEGORY or row["text"] in self.fit:
                    categories.setdefault(row["category"], []).append(int(number))
            selected = [number for row in zip_longest(*categories.values()) for number in row if number is not None]
            return json.dumps({"entries": selected[:json.loads(instruction.user_message)["limit"]]})
        if instruction.diagnostic_stage != "dataset_v2:scenes":
            return "A finished prompt."
        user = composer_user(instruction.user_message)
        labels = [person["label"] for person in user["understanding"]["characters"]]
        wants_entry = "entry_id" in instruction.json_schema["properties"]["scenes"]["items"]["required"]
        def entry_id(row):
            if not self.entries:
                hand = row.get("suggested", {}).get(scenes.ACTIONS_CATEGORY, [])
                return next((key for entry in hand for key, text in user["action_entries"].items() if text == entry), None)
            selected = self.entries.pop(0)
            if selected is None:
                return None
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
        fantasy = next(pack["entries"] for pack in self.catalog["packs"] if pack["id"] == "Spaces/Fantasy")
        self.assertIn('Pack "Fantasy"', vocabulary)
        images = composer_user(call.user_message)["images"]
        self.assertTrue(any(entry in fantasy for image in images for entry in image.get("suggested", {}).get("Spaces", [])))
        self.assertFalse(any(entry in vocabulary for entry in fantasy), "spatial entries belong to individual images")
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
                              offered)
        self.assertEqual(sum(call.diagnostic_stage == "dataset_v2:entries" for call in self.calls), 1,
                          "one shortlist is reused across batches")

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
            selected = next(p for p in self.catalog["packs"] if p["id"] == pack)["entries"]
            self.assertTrue(set(dealt).issubset(selected))
            self.assertGreater(len(set(dealt)), 1)
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
        self.assertTrue(any(entry in vocabulary for entry in self.romance))
        for rule in ("If it does, that pose is\n   decided", "If it defines only an\n   action, choose a pose",
                     "correct gender", "Objects, furniture and surfaces named in an entry", "keeping the pose physically the same"):
            self.assertIn(rule, call.system_message)
        for rule in ("replace those placeholders with the actual subject names",
                     "A group arrangement uses exactly the requested number of people"):
            self.assertIn(rule, vocabulary)

    def test_action_suggestions_are_seeded_but_never_prebind_an_image(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        self.fit = self.romance[:3]
        self.entries = self.fit.copy()
        self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        images = composer_user(self.composer()[0].user_message)["images"]
        self.assertTrue(all("entry_id" not in image for image in images))
        self.assertTrue(all(set(image["suggested"][scenes.ACTIONS_CATEGORY]) == set(self.fit) for image in images))
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
        self.assertEqual(set(item["properties"]["entry_id"]["enum"]), {None, *choices})
        self.assertEqual(item["properties"]["entry_id"]["type"], ["string", "null"])
        self.assertTrue(set(choices.values()).issubset(self.romance))
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
            self.assertNotIn("entry_id", user["images"][0], "no candidate is pre-bound")
            scene = json.loads(response)["scenes"][0]
            chosen = next(key for key, text in user["action_entries"].items() if text == alternative)
            scene.update(entry_id=chosen, actions=action, position=positions)
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
        self.fit = [first, second, self.romance[2]]
        self.entries = [first] * 3 + [second]
        result = self.write(self.brief("A couple", pair, amount=3), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual([scene["entry"] for scene in result["scenes"]],
                         [first, first, second])
        retry = self.composer()[1]
        self.assertIn(f'the entry "{first}" is already used by 2 images', retry.system_message)
        self.assertEqual(composer_user(retry.user_message)["already_used"]["entries"], {first: 2})
        self.assertIn("at most 2 images", self.composer()[0].system_message)

    def test_an_entry_that_is_not_in_the_vocabulary_is_asked_again(self):
        pair = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        expected = self.romance[2]
        self.fit = [expected]
        self.entries = ["a made-up entry", expected]
        result = self.write(self.brief("A couple", pair, amount=1), ["Actions & Poses/Romance"])
        self.assertEqual(result["scenes"][0]["entry"], expected)
        self.assertIn('"entry_id" must be null or one of the IDs in action_entries', self.composer()[1].system_message)

    def test_only_shortlisted_actions_are_offered_and_available_for_binding(self):
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
        self.assertEqual(set(user["action_entries"].values()), set(self.fit))
        self.assertTrue(all("entry_id" not in image for image in user["images"]))
        self.assertIn("at most 3 images", first.system_message, "five images share two fitting entries")
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

    def test_fewer_entries_than_images_raise_the_cap(self):
        self.assertEqual(scenes.entry_cap(["a", "b", "c"], 10), 4)
        self.assertEqual(scenes.entry_cap(["a"] * 20, 10), 2)
        self.assertIsNone(scenes.entry_cap([], 10))

    def map_catalog(self):
        # Entries and request retained from the 20261021-164227 failure; no live model is used here.
        seated = ("One person seated while the other person stands beside them, leaning slightly toward the same "
                  "open page and pointing to a detail on it.")
        walking = ("Two people walking side by side in the same direction, one turning their head toward the other "
                   "while both keep space for their strides.")
        return {**self.catalog, "packs": [
            {"id": "actions/page", "name": "Page", "category": scenes.ACTIONS_CATEGORY, "entries": [seated]},
            {"id": "actions/travel", "name": "Travel", "category": scenes.ACTIONS_CATEGORY, "entries": [walking]},
            {"id": "objects/map", "name": "Map", "category": "Objects & Props", "entries": ["a folded paper map"]},
            {"id": "spaces/city", "name": "City", "category": "Spaces", "entries": ["a covered market"]}]}

    def map_brief(self, amount=10):
        request = ("Two adult companions walk side by side through a city while consulting the same paper map. "
                   "One holds the open map and the other points out their route while both keep walking. "
                   "Keep exactly two people and preserve the walking and map-reading activity in every scene.")
        brief = self.brief(request, [{"label": "companion", "count": 2, "gender": "", "custom": "", "pronoun": ""}],
                           amount=amount)
        brief.update(fixed="two people walking side by side, one holds the map, the other points out their route",
                     must=["exactly two people", "preserve the walking and map-reading activity"])
        brief["input"]["seed"] = 173
        return brief

    def test_captured_incompatible_candidate_can_be_declined_without_losing_other_vocabulary(self):
        catalog = self.map_catalog()
        self.fit = catalog["packs"][0]["entries"]
        self.entries = [None] * 10
        messages = []
        result = scenes.write_scenes({"backend": "mock"}, self.request, self.map_brief(), progress=messages.append,
                                     vocabulary={"packs": [p["id"] for p in catalog["packs"]]}, catalog=catalog)
        self.assertTrue(result["complete"])
        user = composer_user(self.composer()[0].user_message)
        self.assertEqual(list(user["action_entries"].values()), self.fit)
        self.assertTrue(all("entry_id" not in image for image in user["images"]))
        self.assertTrue(all("entry" not in scene for scene in result["scenes"]), "null must never fall back to a candidate")
        self.assertTrue(all("both keep walking" in scene["actions"] for scene in result["scenes"]))
        for image in user["images"]:
            self.assertEqual(image["suggested"]["Objects & Props"], ["a folded paper map"])
        self.assertEqual([entry for image in user["images"] for entry in image["suggested"].get("Spaces", [])],
                         ["a covered market"], "one spatial offer, not ten recycled offers")
        self.assertIn('Pack "City"', user["vocabulary"])
        self.assertTrue(any("0/10 scenes bound; 10 without" in message for message in messages))
        text = prompts.scene_text(result["scenes"][0])
        self.assertNotIn(self.fit[0], text)
        self.assertIn("both keep walking", text)

    def test_captured_walking_candidate_keeps_exact_reference_when_composer_chooses_it(self):
        catalog = self.map_catalog()
        walking = catalog["packs"][1]["entries"][0]
        self.entries = [walking]
        original = self.generate
        positions = {"companion 1": "left, striding forward holding the open map in both hands",
                     "companion 2": "right, striding alongside companion 1 and pointing to the route on the map"}
        def generate(instruction):
            response = original(instruction)
            if instruction.diagnostic_stage != "dataset_v2:scenes":
                return response
            scene = json.loads(response)["scenes"][0]
            scene.update(position=positions, actions="companion 1 and companion 2 walk side by side; companion 1 holds "
                         "the open map while companion 2 points out their route", extras="a folded paper map")
            return json.dumps({"scenes": [scene]})
        self.backend.generate.side_effect = generate
        result = self.write(self.map_brief(amount=1), [p["id"] for p in catalog["packs"]], catalog)
        self.assertTrue(result["complete"])
        scene = result["scenes"][0]
        self.assertEqual(scene["entry"], walking)
        self.assertEqual(scene["position"], positions)
        self.assertNotIn("entry_id", scene)
        self.assertIn("companion 2 points out their route", prompts.scene_text(scene))

    def test_anchor_exhaustion_can_repair_to_abstention(self):
        self.fit = self.romance[:3]
        self.entries = [self.fit[0]] * 3 + [None]
        result = self.write(self.brief("Two guides", [{"label": "guide", "count": 2, "gender": "", "custom": "", "pronoun": ""}], amount=3),
                            ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual(sum("entry" in scene for scene in result["scenes"]), 2)
        self.assertNotIn("entry", result["scenes"][2])
        self.assertIn("or return null", self.composer()[1].system_message)

    def retrieval(self, groups, response):
        brief = self.map_brief()
        brief["_family"] = "qwen"
        backend = Mock(generate=Mock(return_value=response))
        result = scenes.shortlist_entries(backend, brief, groups, progress=lambda _: None)
        return result, backend

    def test_positive_ids_from_original_incomplete_80_entry_case_need_no_coverage_or_recovery(self):
        groups = [{"category": "Spaces", "packs": [{"entries": [f"place {n}" for n in range(1, 81)]}]}]
        # The two direct IDs in the original 52/80 response are sufficient in a positive retrieval contract.
        result, backend = self.retrieval(groups, '{"entries":[21,24]}')
        self.assertEqual(result, {"Spaces": ["place 21", "place 24"]})
        self.assertEqual(backend.generate.call_count, 1)
        instruction = backend.generate.call_args.args[0]
        self.assertEqual(len(json.loads(instruction.user_message)["entries"]), 80)
        self.assertEqual(instruction.json_schema["properties"]["entries"]["maxItems"], 20)
        self.assertEqual(instruction.max_tokens, 224)

    def test_malformed_ids_do_not_discard_independent_valid_shortlist_choices(self):
        groups = [{"category": "Actions & Poses", "packs": [{"entries": ["one", "two", "three"]}]}]
        for bad in (0, -1, 4, True, False, "1", 1.5, None, {}, []):
            with self.subTest(bad=bad):
                result, backend = self.retrieval(groups, json.dumps({"entries": [3, bad, 1, 3]}))
                self.assertEqual(result, {"Actions & Poses": ["one", "three"]})
                self.assertEqual(backend.generate.call_count, 1)

    def test_empty_shortlist_is_valid_and_never_refilled(self):
        groups = [{"category": category, "packs": [{"entries": ["one", "two"]}]}
                  for category in ("Actions & Poses", "Spaces")]
        result, backend = self.retrieval(groups, '{"entries":[]}')
        self.assertEqual(result, {})
        self.assertEqual(backend.generate.call_count, 1)

    def test_malformed_shortlist_envelopes_never_restore_action_candidates(self):
        groups = [{"category": category, "packs": [{"entries": ["one"]}]}
                  for category in ("Actions & Poses", "Spaces")]
        for response in ('[]', 'null', '{}', '{"entries":null}', '{"entries":"1"}', '{"entries":[1],"other":[]}'):
            with self.subTest(response=response):
                result, backend = self.retrieval(groups, response)
                self.assertEqual(result, {"Spaces": ["one"]})
                self.assertEqual(backend.generate.call_count, 1)

    def test_oversized_shortlist_is_bounded_and_empty_catalog_needs_no_call(self):
        groups = [{"category": "Spaces", "packs": [{"entries": [f"place {n}" for n in range(1, 81)]}]}]
        result, _ = self.retrieval(groups, json.dumps({"entries": list(range(1, 81))}))
        self.assertEqual(result, {"Spaces": [f"place {n}" for n in range(1, 21)]})
        result, backend = self.retrieval([], '{"entries":[]}')
        self.assertEqual(result, {})
        backend.generate.assert_not_called()

    def test_duplicate_entries_merge_author_notes_without_duplicating_retrieval_ids(self):
        groups = [{"category": "Spaces", "packs": [{"entries": ["one"], "description": "first note"},
                                                    {"entries": ["one"], "description": "second note"}]}]
        result, backend = self.retrieval(groups, '{"entries":[1]}')
        self.assertEqual(result, {"Spaces": ["one"]})
        data = json.loads(backend.generate.call_args.args[0].user_message)
        self.assertEqual(data["entries"], {"1": {"category": "Spaces", "text": "one",
                                                  "notes": ["first note", "second note"]}})

    def test_abstention_does_not_bypass_existing_scene_validation(self):
        self.entries = [None, None]
        original = self.generate
        emitted = []
        def generate(instruction):
            response = original(instruction)
            if instruction.diagnostic_stage != "dataset_v2:scenes":
                return response
            scene = json.loads(response)["scenes"][0]
            if not emitted:
                scene["position"] = {}
            emitted.append(scene)
            return json.dumps({"scenes": [scene]})
        self.backend.generate.side_effect = generate
        result = self.write(self.map_brief(amount=1), ["Actions & Poses/Romance"])
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.composer()), 2)
        self.assertNotIn("entry", result["scenes"][0])
        self.assertEqual(set(result["scenes"][0]["position"]), {"companion 1", "companion 2"})

    def test_failed_window_preserves_other_results_and_only_falls_back_to_non_actions(self):
        groups = [{"category": category, "packs": [{"entries": ["one", "two"]}]}
                  for category in ("Actions & Poses", "Spaces")]
        brief = self.map_brief()
        brief["_family"] = "qwen"
        backend = Mock(generate=Mock(side_effect=['{"entries":[1]}', 'not json', '{"entries":[]}', 'not json']))
        messages = []
        with patch.object(scenes, "SHORTLIST_WINDOW", 1):
            result = scenes.shortlist_entries(backend, brief, groups, progress=messages.append)
        self.assertEqual(result, {"Actions & Poses": ["one"], "Spaces": ["two"]})
        self.assertEqual(backend.generate.call_count, 4, "one call per window, no recovery stage")
        self.assertTrue(any("unassessed non-action" in message for message in messages))

    def test_malformed_retrieval_retains_non_action_influence_without_canonical_candidates(self):
        catalog = self.map_catalog()
        original = self.generate
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset_v2:entries":
                self.calls.append(instruction)
                return "not json"
            return original(instruction)
        self.backend.generate.side_effect = generate
        result = self.write(self.map_brief(), [p["id"] for p in catalog["packs"]], catalog)
        self.assertTrue(result["complete"])
        user = composer_user(self.composer()[0].user_message)
        self.assertNotIn("action_entries", user)
        self.assertNotIn("Actions & Poses", user["vocabulary"])
        self.assertEqual([entry for image in user["images"] for entry in image.get("suggested", {}).get("Spaces", [])],
                         ["a covered market"])
        self.assertIn('Pack "City"', user["vocabulary"])
        self.assertIn("a folded paper map", user["vocabulary"])
        self.assertTrue(all("entry" not in scene for scene in result["scenes"]))

    def test_retrieval_uses_actual_entries_notes_constraints_and_roles_not_pack_titles(self):
        catalog = self.map_catalog()
        catalog["packs"][2]["description"] = "Useful for navigation."
        brief = self.map_brief()
        brief.update(avoid=["no racing"], _family="qwen")
        brief["input"]["rules"] = ["keep the map open"]
        groups = scenes.selected_vocabulary(catalog, {"packs": [p["id"] for p in catalog["packs"]]})
        scenes.shortlist_entries(self.backend, brief, groups, progress=lambda _: None)
        data = json.loads(self.calls[0].user_message)
        for field in ("fixed", "must", "avoid"):
            self.assertEqual(data[field], brief[field])
        self.assertEqual(data["rules"], brief["input"]["rules"])
        self.assertEqual([person["label"] for person in data["cast"]], ["companion 1", "companion 2"])
        row = next(row for row in data["entries"].values() if row["text"] == "a folded paper map")
        self.assertEqual(row["notes"], ["Useful for navigation."])
        self.assertTrue(all("name" not in row for row in data["entries"].values()))

    def test_multiple_packs_keep_seeded_suggestions_without_repetition_until_deck_exhaustion(self):
        import random
        groups = [{"category": "Actions & Poses", "packs": [{"entries": [f"idea {n}" for n in range(4)]},
                                                             {"entries": [f"idea {n}" for n in range(4, 8)]}]}]
        hands = scenes.deal_hands(groups, 10, random.Random(7))
        self.assertEqual(hands, scenes.deal_hands(groups, 10, random.Random(7)))
        self.assertNotEqual(hands, scenes.deal_hands(groups, 10, random.Random(8)))
        first_six = [entry for number in (1, 2) for entry in hands[number]["Actions & Poses"]]
        self.assertEqual(len(set(first_six)), 6)
        self.assertEqual({entry for hand in hands.values() for entry in hand["Actions & Poses"]},
                         {f"idea {n}" for n in range(8)})

    def test_three_spatial_entries_are_offered_once_instead_of_recycled_across_ten_images(self):
        import random
        from collections import Counter
        groups = [{"category": "Spaces", "packs": [{"entries": ["market", "courtyard", "canal"]}]}]
        for total in (1, 10, 25):
            with self.subTest(total=total):
                hands = scenes.deal_hands(groups, total, random.Random(173))
                dealt = [entry for hand in hands.values() for entry in hand.get("Spaces", [])]
                self.assertEqual(len(dealt), min(total, 3))
                self.assertTrue(all(count == 1 for count in Counter(dealt).values()))
                self.assertTrue(all(len(hand.get("Spaces", [])) <= 1 for hand in hands.values()))
                self.assertEqual(hands, scenes.deal_hands(groups, total, random.Random(173)))
        self.assertNotEqual(scenes.deal_hands(groups, 10, random.Random(173)),
                            scenes.deal_hands(groups, 10, random.Random(271)))

    def test_spatial_dealing_preserves_other_categories_and_their_random_stream(self):
        import random
        groups = [{"category": category, "packs": [{"entries": [f"{category} {n}" for n in range(4)]}]}
                  for category in ("Actions & Poses", "Spaces", "Objects & Props", "Lighting")]
        expected, rng = {}, random.Random(173)
        for group in groups:
            dealt = list(scenes.deal_entries(group["packs"][0]["entries"], 30, rng).values())
            if group["category"] != "Spaces":
                for number in range(1, 11):
                    expected.setdefault(number, {})[group["category"]] = list(dict.fromkeys(dealt[(number - 1) * 3:number * 3]))
        actual_rng = random.Random(173)
        actual = scenes.deal_hands(groups, 10, actual_rng)
        self.assertEqual({number: {category: hand for category, hand in hands.items() if category != "Spaces"}
                          for number, hands in actual.items()}, expected)
        self.assertEqual(actual_rng.getstate(), rng.getstate())

    def test_spatial_suggestions_and_theme_only_shared_prompt_allow_new_locations_without_changing_binding(self):
        catalog = self.map_catalog()
        places = ["covered market", "public courtyard", "urban canal path"]
        catalog["packs"][-1]["entries"] = places
        walking = catalog["packs"][1]["entries"][0]
        self.entries = [walking, None] * 5
        original = self.generate

        def generate(instruction):
            response = original(instruction)
            if instruction.diagnostic_stage != "dataset_v2:scenes":
                return response
            user = composer_user(instruction.user_message)
            rows = json.loads(response)["scenes"]
            for image, scene in zip(user["images"], rows):
                suggestions = image.get("suggested", {}).get("Spaces", [])
                scene["space"] = suggestions[0] if suggestions else f"city garden sector{image['image']}"
            return json.dumps({"scenes": rows})

        self.backend.generate.side_effect = generate
        result = self.write(self.map_brief(), [pack["id"] for pack in catalog["packs"]], catalog)
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.composer()), 1)
        self.assertEqual(sum(call.diagnostic_stage == "dataset_v2:entries" for call in self.calls), 1)
        call = self.composer()[0]
        user = composer_user(call.user_message)
        self.assertEqual(sum(bool(image.get("suggested", {}).get("Spaces")) for image in user["images"]), 3)
        self.assertEqual(sum(scene["space"] in places for scene in result["scenes"]), 3)
        self.assertEqual(sum(scene["space"].startswith("city garden") for scene in result["scenes"]), 7)
        for place in places:
            self.assertNotIn(place, user["vocabulary"], "shared entries must not bypass per-image dealing")
        self.assertIn('City', user["vocabulary"])
        self.assertIn("choose a new compatible location", call.system_message)
        self.assertIn("selected spatial pack themes", call.system_message)
        self.assertEqual([scene.get("entry") for scene in result["scenes"]], [walking, None] * 5)
        self.assertTrue(all("both keep walking" in scene["actions"] for scene in result["scenes"]))

    def test_all_selected_spatial_pack_themes_survive_empty_shortlists_and_later_batches(self):
        catalog = {**self.catalog, "packs": [
            {"id": "spaces/orbital", "name": "Orbital", "category": "Spaces",
             "description": "Science-fiction habitats in orbit.", "entries": ["rotating station concourse"]},
            {"id": "spaces/planetary", "name": "Planetary", "category": "Spaces",
             "description": "Science-fiction settlements on distant planets.", "entries": ["sealed crater plaza"]}]}
        original = self.generate
        for selected in ([], ["rotating station concourse"], ["rotating station concourse", "sealed crater plaza"]):
            with self.subTest(selected=selected):
                self.calls.clear()

                def generate(instruction):
                    if instruction.diagnostic_stage == "dataset_v2:entries":
                        self.calls.append(instruction)
                        rows = json.loads(instruction.user_message)["entries"]
                        return json.dumps({"entries": [int(number) for number, row in rows.items() if row["text"] in selected]})
                    return original(instruction)

                self.backend.generate.side_effect = generate
                result = self.write(self.brief("Two explorers crossing a settlement", [], amount=25),
                                    [pack["id"] for pack in catalog["packs"]], catalog)
                self.assertTrue(result["complete"])
                self.assertEqual(len(self.composer()), 3)
                offered = []
                for call in self.composer():
                    user = composer_user(call.user_message)
                    for name in ("Orbital", "Planetary", "Science-fiction habitats in orbit.",
                                 "Science-fiction settlements on distant planets."):
                        self.assertIn(name, user["vocabulary"])
                    for entry in ("rotating station concourse", "sealed crater plaza"):
                        self.assertNotIn(entry, user["vocabulary"])
                    offered.extend(entry for image in user["images"] for entry in image.get("suggested", {}).get("Spaces", []))
                    self.assertIn("choose a new compatible location", call.system_message)
                    self.assertIn("not a closed list of locations", call.system_message)
                self.assertCountEqual(offered, selected)

    def test_same_seed_repeats_retrieval_input_suggestions_and_scene_reference_mapping(self):
        catalog = self.map_catalog()
        brief = self.map_brief()
        brief["input"]["request"] = "Two companions exploring a city"
        brief.update(fixed="", must=[])
        def run(seed):
            self.calls.clear()
            brief["input"]["seed"] = seed
            result = self.write(brief, [p["id"] for p in catalog["packs"]], catalog)
            return [call.user_message for call in self.calls], result["scenes"]
        self.assertEqual(run(7), run(7))
        self.assertNotEqual(run(7), run(8))

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
