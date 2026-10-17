"""Selected vocabulary in the existing Dataset scene writer: only what the user picked, grouped under its Core
instruction, as optional material. The scene writer is scripted, so this checks what it receives, not how a live
model uses it."""

import json
import unittest
from unittest.mock import Mock, patch

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
        self.catalog = load_catalog()
        self.calls = []
        self.backend = MockBackend()
        self.enterContext(patch.object(self.backend, "generate", side_effect=self.generate))
        self.enterContext(patch.object(scenes, "create_backend", return_value=self.backend))
        for module in (scenes, prompts, understanding):
            self.enterContext(patch.object(module, "DebugTrace", return_value=Mock()))
        self.enterContext(patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.request = GoatedPrompterRequest(idea="dataset", planning_mode="Direct", director_preset="general_director")

    def brief(self, subject, cast, *, nsfw=False, amount=2):
        data = {**default_dataset_draft(), "subject": subject, "amount": amount, "nsfw": nsfw, "seed": 7, "seed_mode": "fixed"}
        value = {"path": "character" if cast else "non_character", "summary": subject, "fixed": "", "randomized": "",
                 "must": [], "avoid": [], "characters": cast}
        return understanding.apply_rules(value, data, Mock())

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage != "dataset_v2:scenes":
            return "A finished prompt."
        user = composer_user(instruction.user_message)
        labels = [person["label"] for person in user["understanding"]["characters"]]
        return json.dumps({"scenes": [{
            "subjects": {label: dict(SCENE) for label in labels}, "position": {label: "standing" for label in labels},
            "actions": user["request"], "space": f"clearing {row['image']}", "lighting": "moonlight", "mood": "calm",
            "camera": "wide shot", "extras": "none"} for row in user["images"]]})

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
        for unselected in ("Subjects\n", "Clothing\n", "Actions\n", "foggy graveyard", "athletic woman"):
            self.assertNotIn(unselected, vocabulary)
        self.assertIn("Treat vocabulary entries as creative possibilities, not mandatory instructions.", call.system_message)
        self.assertIn("Do not create missing subjects merely to satisfy vocabulary entries.", call.system_message)

    def test_example_c_adult_packs_are_optional_material_beside_the_request(self):
        cast = [{"label": "model", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        packs = ["Positions & Poses/Seductive-Solo-Poses", "Expressions/Seductive-Expressions",
                 "Clothing/Seductive-Clothing", "Objects/Sex-Toys"]
        result = self.write(self.brief("A seductive adult character posing with a prop", cast, nsfw=True), packs)
        vocabulary = composer_user(self.composer()[0].user_message)["vocabulary"]
        self.assertEqual([line for line in vocabulary.split("\n") if line in {"Positions & Poses", "Expressions", "Clothing", "Objects"}],
                         ["Objects", "Positions & Poses", "Expressions", "Clothing"], "registry order")
        self.assertEqual(len(result["vocabulary"]["selection"]["packs"]), 4)

    def test_example_d_a_group_keeps_its_cast_from_understanding(self):
        group = [{"label": "adult", "gender": "", "custom": "", "pronoun": "", "count": 3}]
        result = self.write(self.brief("A group of adults in an intimate scene", group, nsfw=True),
                            ["Positions & Poses/Group-Poses", "Mood & Tone/Romantic"])
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


if __name__ == "__main__":
    unittest.main()
