"""Adult Dataset contract propagation with scripted responses, not model-quality evidence."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from tests.helpers import enter_context

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from tests.support.dataset_scenes import composer_user, without_places


class AdultDatasetTests(unittest.TestCase):
    def setUp(self):
        without_places(self)
        self.backend = MockBackend()
        self.calls = []
        self.understood = None
        self.scene = {}
        self.replies = {}
        self.final_text = "adult_token: The consenting adults keep their assigned positions and red ribbon."
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            enter_context(self, patch.object(module, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.config = {"backend": "mock"}
        self.request = GoatedPrompterRequest(idea="Consenting adults", director_preset="general_director", planning_mode="Direct")

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if self.replies.get(stage):
            return json.dumps(self.replies[stage].pop(0))
        if stage == "dataset_v2:understanding":
            return json.dumps(self.understood)
        if stage == "dataset_v2:scenes":
            return json.dumps({"scenes": [self.scene]})
        self.assertEqual(stage, "final", "No new generation or validation stages are expected")
        return self.final_text

    def scenario(self, cast, labels):
        data = {**default_dataset_draft(), "subject": "Consenting adults in an explicit pose together with a red ribbon.",
                "amount": 1, "nsfw": True, "seed": 73, "seed_mode": "fixed", "trigger": "adult_token",
                "trigger_at_start": True, "constraints": "Use a red ribbon.\nNo blindfold.\nNo collar."}
        self.understood = {"path": "character", "summary": "Consenting adults posing together",
            "characters": cast, "fixed": "The named adults retain their identities, roles and assigned support.",
            "randomized": "Lighting and camera", "must": ["Use a red ribbon"], "avoid": ["No blindfold", "No collar"]}
        self.scene = {"subjects": {label: {"skin": "warm brown", "build": "adult", "hair": "short dark hair",
            "eyes": f"{label}'s dark brown eyes", "expression": "a soft smile", "genitals": "average size, relaxed",
            "clothing": "no clothing"} for label in labels},
            "position": {label: f"{label} sits on the bench, feet on the floor, holding a red ribbon in the right hand."
                         for label in labels}, "actions": f"{' and '.join(labels)} display their red ribbons without changing places.",
            "space": "A studio with a wide bench", "lighting": "daylight", "mood": "calm", "camera": "wide shot",
            "extras": "A plain wall", "frame": {label: {"shows": "full body", "face": "visible"} for label in labels}}
        return data

    def understand(self, data):
        return understanding.understand(self.config, self.request, data, progress=lambda _message: None)

    def write(self, brief):
        return scenes.write_scenes(self.config, self.request, brief, progress=lambda _message: None)

    def users(self, stage):
        read = composer_user if stage == "scenes" else json.loads
        return [read(call.user_message) for call in self.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]

    def composer(self):
        return [call for call in self.calls if call.diagnostic_stage == "dataset_v2:scenes"]

    def test_solo_pair_and_group_keep_nsfw_route_identity_and_counts_through_builder(self):
        cases = [
            ([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"]),
            ([{"label": "Mara", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
              {"label": "Rowan", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Mara", "Rowan"]),
            ([{"label": "Kai", "gender": "custom", "custom": "nonbinary adult human", "pronoun": "it", "count": 1},
              {"label": "performer", "gender": "female", "custom": "", "pronoun": "she", "count": 2}],
             ["Kai", "performer 1", "performer 2"]),
        ]
        for cast, labels in cases:
            with self.subTest(labels=labels):
                self.calls.clear()
                data = self.scenario(cast, labels)
                brief = self.understand(data)
                self.assertEqual(brief["path"], "nsfw_character")
                self.assertEqual(brief["people"], len(labels))
                self.assertEqual([person["label"] for person in brief["characters"]], labels)
                self.assertEqual([person["gender"] for person in brief["characters"]],
                                 [person["gender"] for person in cast for _ in range(person["count"])])
                self.assertEqual(brief["input"]["request"], data["subject"])
                result = self.write(brief)
                scene = result["scenes"][0]
                self.assertEqual(set(scene["subjects"]), set(labels))
                self.assertEqual(scene["position"], self.scene["position"])
                self.assertEqual(scene["actions"], self.scene["actions"])
                user = self.users("scenes")[0]
                self.assertEqual(user["understanding"]["characters"], brief["characters"])
                self.assertEqual(user["understanding"]["fixed"], brief["fixed"])
                system = self.composer()[0].system_message
                self.assertIn("This dataset is adult content", system)
                self.assertIn("Never add nudity, acts or kinks the request does not call for", system, "the switch allows, the request decides")
                written = prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
                final = self.calls[-1]
                for label in labels:
                    self.assertIn(prompts.name_people(self.scene["position"][label], brief, scene), final.user_message)
                    self.assertIn(prompts.name_people(f"{label}'s dark brown eyes", brief, scene), final.user_message)
                self.assertNotIn("performer 1", final.user_message)
                self.assertIn(prompts.name_people(self.scene["actions"], brief, scene), final.user_message)
                self.assertTrue(written[0]["trigger_ok"])
                self.assertEqual(final.seed, 73)

    def test_step_one_repairs_a_non_character_answer_for_an_nsfw_request(self):
        data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
        invalid = {**self.understood, "path": "non_character", "characters": []}
        self.replies["dataset_v2:understanding"] = [invalid]
        brief = self.understand(data)
        self.assertEqual(brief["path"], "nsfw_character")
        self.assertEqual(brief["people"], 1)
        self.assertEqual(len(self.users("understanding")), 2)
        self.assertIn('path must be "character"', self.calls[1].system_message)

    def test_stated_bodies_roles_and_interaction_reach_the_composer_and_builder(self):
        data = self.scenario([
            {"label": "Mara", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
            {"label": "Rowan", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Mara", "Rowan"])
        anatomy = "Mara has a prosthetic left arm; Rowan has a tattooed back."
        roles = "Mara is the giver; Rowan is the receiver. Both are consenting adults."
        support = "Mara stands facing Rowan; Rowan lies on the bench with both feet supported."
        data.update(subject=f"{roles} {anatomy} An explicit scene between them.", constraints=support + "\nNo toys.")
        self.understood.update(summary=data["subject"], fixed=roles + " " + support, must=[anatomy], avoid=["No toys"])
        self.scene.update(position={"Mara": "Mara stands on the floor facing Rowan, whose hips are at the bench edge.",
                                    "Rowan": "Rowan lies on the bench facing Mara, feet supported on the bench."},
                          actions="Mara rests her prosthetic hand on Rowan's tattooed back.")
        # A body feature the request states is part of the build.
        self.scene["subjects"]["Mara"]["build"] = "Mara's prosthetic arm and slim build"
        self.scene["subjects"]["Rowan"]["build"] = "Rowan's tattooed back and broad build"
        brief = self.understand(data)
        result = self.write(brief)
        user = self.users("scenes")[0]
        self.assertEqual(user["understanding"]["must"], [anatomy])
        self.assertEqual(user["understanding"]["fixed"], roles + " " + support)
        self.assertEqual(user["rules"], [support, "No toys."])
        self.assertEqual(user["understanding"]["avoid"], ["No toys"])
        self.assertTrue(all("anatomy" not in person for person in user["understanding"]["characters"]))
        prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
        final = self.calls[-1]
        self.assertIn("Mara's prosthetic arm", final.user_message)
        self.assertIn("Rowan's tattooed back", final.user_message)
        self.assertIn(self.scene["actions"], final.user_message)
        self.assertNotIn("no prosthetic", final.system_message + final.user_message)

    def test_a_wrong_participant_is_asked_again_not_published(self):
        data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
        wrong_cast = {**deepcopy(self.scene), "position": {"Stranger": "standing"}}
        self.replies = {"dataset_v2:scenes": [{"scenes": [wrong_cast]}]}
        result = self.write(self.understand(data))
        self.assertEqual(len(self.users("scenes")), 2)
        self.assertEqual(result["scenes"][0]["position"], self.scene["position"])
        self.assertEqual(set(result["scenes"][0]["subjects"]), {"Alex"})
        self.assertNotIn("Stranger", json.dumps(result["scenes"]))

    def test_excluded_accessories_are_asked_again(self):
        data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
        self.replies = {"dataset_v2:scenes": [{"scenes": [{**self.scene, "actions": "Alex wears a blindfold."}]},
                                              {"scenes": [{**self.scene, "extras": "A leather COLLAR"}]}]}
        result = self.write(self.understand(data))
        self.assertEqual(len(self.users("scenes")), 3)
        self.assertIn('the user said "No blindfold"', self.composer()[1].system_message)
        scene = result["scenes"][0]
        self.assertNotIn("blindfold", json.dumps(scene).lower())
        self.assertNotIn("collar", json.dumps(scene).lower())
        self.assertIn("red ribbon", scene["position"]["Alex"])

    def test_builder_receives_confirmed_requirements_even_when_the_scene_does_not_repeat_them(self):
        for nsfw, requirement in ((True, "Alex has a prosthetic left arm"), (False, "Alex wears a blue shirt")):
            with self.subTest(nsfw=nsfw):
                data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
                if not nsfw:
                    data.update(nsfw=False, subject="An adult posing with a red ribbon.")
                    self.scene["subjects"]["Alex"]["clothing"] = "blue shirt"
                    self.scene["subjects"]["Alex"].pop("genitals")  # only adult datasets describe them
                self.understood["must"].append(requirement)
                self.understood["fixed"] = "Alex is the only participant and keeps the same identity."
                brief = self.understand(data)
                result = self.write(brief)
                prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
                final = self.calls[-1]
                for required in (requirement, "No blindfold", "No collar", "Use a red ribbon"):
                    self.assertIn(required, final.system_message + final.user_message)
                # The request and "fixed" are already in the scene; repeated, the model pastes them in as content.
                self.assertNotIn("Alex is the only participant and keeps the same identity.", final.system_message)
                self.assertNotIn('"request":', final.system_message)
                adult = "This is an adult dataset: word the act and the bodies exactly as the scene does, in its everyday words"
                (self.assertIn if nsfw else self.assertNotIn)(adult, final.system_message + final.user_message)
                visible = "they get their own short description in that person's description"
                (self.assertIn if nsfw else self.assertNotIn)(visible, " ".join(final.system_message.split()))
                self.assertIn("A body part the action uses is bare, so no garment covers it",
                              " ".join(final.system_message.split()), "clothing never covers what the action uses")
                # Live final prompts dressed people the adult scene left bare.
                bare = "Everyone who takes part in the act is bare unless the scene's extras dress them"
                (self.assertIn if nsfw else self.assertNotIn)(bare, " ".join(final.system_message.split()))
                # A live final prompt gave a body part a colour and a state its scene never said.
                (self.assertIn if nsfw else self.assertNotIn)("Every intimate body part gets only what the scene gives it",
                                                              " ".join(final.system_message.split()))
