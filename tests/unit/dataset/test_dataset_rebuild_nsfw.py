"""Adult Dataset contract propagation with scripted responses, not model-quality evidence."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import default_dataset_draft
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding


class AdultDatasetTests(unittest.TestCase):
    def setUp(self):
        self.backend = MockBackend()
        self.calls = []
        self.understood = None
        self.concepts = []
        self.staging = {}
        self.description = {}
        self.replies = {}
        self.final_text = "adult_token: The consenting adults keep their assigned positions and red ribbon."
        self.enterContext(patch.object(self.backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            self.enterContext(patch.object(module, "create_backend", return_value=self.backend))
            self.enterContext(patch.object(module, "DebugTrace"))
        self.enterContext(patch.object(prompts, "DebugTrace"))
        self.enterContext(patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.config = {"backend": "mock", "dataset_vocabulary": False}
        self.request = GoatedPrompterRequest(idea="Consenting adults", director_preset="general_director", planning_mode="Direct")

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if self.replies.get(stage):
            return json.dumps(self.replies[stage].pop(0))
        if stage == "dataset_v2:understanding":
            return json.dumps(self.understood)
        if stage == "dataset_v2:concepts":
            return json.dumps({"concepts": self.concepts})
        if stage == "dataset_v2:stagings":
            return json.dumps({"stagings": [self.staging]})
        if stage == "dataset_v2:scenes":
            return json.dumps({"scenes": [self.description]})
        self.assertEqual(stage, "final", "No new generation or validation stages are expected")
        return self.final_text

    def scenario(self, cast, labels):
        data = {**default_dataset_draft(), "subject": "Consenting nude adults posing together with a red ribbon.",
                "amount": 1, "nsfw": True, "seed": 73, "seed_mode": "fixed", "trigger": "adult_token",
                "trigger_at_start": True, "constraints": "Use a red ribbon.\nNo blindfold.\nNo collar."}
        self.understood = {"path": "character", "summary": "Consenting adults posing together",
            "characters": cast, "fixed": "The named adults retain their identities, roles and assigned support.",
            "randomized": "Lighting and camera", "must": ["Use a red ribbon"], "avoid": ["No blindfold", "No collar"]}
        self.concepts = [{"place": "sunlit studio", "position_name": "seated pose", "position": "Supported on a wide bench",
            "looks": {label: "short dark hair" for label in labels}, "lighting": "daylight", "camera": "wide shot"}]
        self.staging = {"reach": "Each person has a separate place on the wide bench and can reach their own ribbon.",
            "position": {label: f"{label} sits on the bench, feet on the floor, holding a red ribbon in the right hand."
                         for label in labels}, "actions": "The adults display their red ribbons without changing places."}
        self.description = {"subjects": {label: {"skin": "warm brown", "build": "adult", "hair": "short dark hair",
            "detail": f"{label}'s recognizable face", "clothing": "nude"} for label in labels},
            "space": "A studio with a wide bench", "lighting": "daylight", "mood": "calm", "camera": "wide shot",
            "extras": "A plain wall"}
        return data

    def understand(self, data):
        return understanding.understand(self.config, self.request, data, progress=lambda _message: None)

    def write(self, brief):
        return scenes.write_scenes(self.config, self.request, brief, progress=lambda _message: None)

    def users(self, stage):
        return [json.loads(call.user_message) for call in self.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]

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
                self.assertEqual(scene["position"], self.staging["position"])
                self.assertEqual(scene["actions"], self.staging["actions"])
                for stage in ("concepts", "stagings", "scenes"):
                    self.assertEqual(self.users(stage)[0]["characters"], brief["characters"])
                    self.assertEqual(self.users(stage)[0]["fixed"], brief["fixed"])
                written = prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
                final = self.calls[-1]
                for label in labels:
                    self.assertIn(self.staging["position"][label], final.user_message)
                    self.assertIn(f"{label}'s recognizable face", final.user_message)
                self.assertIn(self.staging["actions"], final.user_message)
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

    def test_explicit_anatomy_roles_and_interaction_survive_all_scene_requests(self):
        data = self.scenario([
            {"label": "Mara", "gender": "female", "custom": "", "pronoun": "she", "count": 1},
            {"label": "Rowan", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Mara", "Rowan"])
        anatomy = "Mara has a penis; Rowan has a vagina."
        roles = "Mara is the giver; Rowan is the receiver. Both are consenting adults."
        support = "Mara stands facing Rowan; Rowan lies on the bench with both feet supported."
        data.update(subject=f"{roles} {anatomy} Consensual vaginal intercourse.", constraints=support + "\nNo toys.")
        self.understood.update(summary=data["subject"], fixed=roles + " " + support, must=[anatomy], avoid=["No toys"])
        self.staging.update(position={"Mara": "Mara stands on the floor facing Rowan, whose hips are at the bench edge.",
                                      "Rowan": "Rowan lies on the bench facing Mara, feet supported on the bench."},
                            actions="Mara penetrates Rowan's vagina with her penis.")
        self.description["subjects"]["Mara"]["detail"] = "Mara's penis and recognizable face"
        self.description["subjects"]["Rowan"]["detail"] = "Rowan's vagina and recognizable face"
        brief = self.understand(data)
        result = self.write(brief)
        for stage in ("concepts", "stagings", "scenes"):
            user = self.users(stage)[0]
            self.assertEqual(user["must"], [anatomy])
            self.assertEqual(user["fixed"], roles + " " + support)
            self.assertEqual(user["rules"], [support, "No toys."])
            self.assertEqual(user["avoid"], ["No toys"])
            self.assertTrue(all("anatomy" not in person for person in user["characters"]))
        self.assertEqual(self.users("scenes")[0]["scenes"][0]["staging"], self.staging)
        prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
        final = self.calls[-1]
        self.assertIn("Mara's penis", final.user_message)
        self.assertIn("Rowan's vagina", final.user_message)
        self.assertIn(self.staging["actions"], final.user_message)
        self.assertNotIn("no vagina and no pussy", final.system_message + final.user_message)

    def test_wrong_participant_and_description_placement_are_retried_not_published(self):
        data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
        wrong_cast = deepcopy(self.staging)
        wrong_cast["position"] = {"Stranger": "standing"}
        moved_body = {**deepcopy(self.description), "position": {"Alex": "stands on the ceiling"}}
        self.replies = {"dataset_v2:stagings": [{"stagings": [wrong_cast]}], "dataset_v2:scenes": [{"scenes": [moved_body]}]}
        result = self.write(self.understand(data))
        self.assertEqual(len(self.users("stagings")), 2)
        self.assertEqual(len(self.users("scenes")), 2)
        self.assertEqual(result["scenes"][0]["position"], self.staging["position"])
        self.assertEqual(set(result["scenes"][0]["subjects"]), {"Alex"})
        self.assertNotIn("ceiling", json.dumps(result))

    def test_excluded_accessories_are_retried_in_staging_and_description(self):
        data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
        forbidden_action = {**self.staging, "actions": "Alex wears a blindfold."}
        forbidden_detail = {**self.description, "extras": "A leather COLLAR"}
        self.replies = {"dataset_v2:stagings": [{"stagings": [forbidden_action]}],
                        "dataset_v2:scenes": [{"scenes": [forbidden_detail]}]}
        result = self.write(self.understand(data))
        self.assertEqual(len(self.users("stagings")), 2)
        self.assertEqual(len(self.users("scenes")), 2)
        scene = result["scenes"][0]
        self.assertNotIn("blindfold", json.dumps(scene).lower())
        self.assertNotIn("collar", json.dumps(scene).lower())
        self.assertIn("red ribbon", scene["position"]["Alex"])

    def test_builder_receives_confirmed_requirements_even_when_the_scene_does_not_repeat_them(self):
        for nsfw, requirement in ((True, "Alex has a vagina"), (False, "Alex wears a blue shirt")):
            with self.subTest(nsfw=nsfw):
                data = self.scenario([{"label": "Alex", "gender": "male", "custom": "", "pronoun": "he", "count": 1}], ["Alex"])
                if not nsfw:
                    data.update(nsfw=False, subject="An adult posing with a red ribbon.")
                    self.description["subjects"]["Alex"]["clothing"] = "blue shirt"
                self.understood["must"].append(requirement)
                self.understood["fixed"] = "Alex is the only participant and keeps the same identity."
                brief = self.understand(data)
                result = self.write(brief)
                prompts.write_prompts(self.config, self.request, brief, result["scenes"], progress=lambda _message: None)
                final = self.calls[-1]
                for required in (requirement, "No blindfold", "No collar", "Use a red ribbon",
                                 "Alex is the only participant and keeps the same identity."):
                    self.assertIn(required, final.system_message + final.user_message)
