"""Fixes from a live run review (issue 106): repeated scenes, impossible arrangements and labels left in the final
prompt. Scripted models only: these check what is asked and checked, not how well a live model complies."""

import json
import unittest
from unittest.mock import Mock, patch
from tests.helpers import enter_context

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from tests.support.dataset_scenes import composer_user

MEN = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}]
LOOK = {"skin": "tan", "build": "athletic", "hair": "short dark hair", "detail": "stubble", "expression": "a soft smile", "clothing": "no clothing"}


class Harness(unittest.TestCase):
    def setUp(self):
        self.calls, self.replies = [], []
        self.backend = MockBackend()
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        enter_context(self, patch.object(scenes, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.pick_references", return_value=()))
        self.request = GoatedPrompterRequest(idea="dataset", planning_mode="Direct", director_preset="general_director")
        data = {**default_dataset_draft(), "subject": "2 adult men in an explicit scene", "amount": 10, "nsfw": True, "seed": 3,
                "seed_mode": "fixed"}
        self.brief = understanding.apply_rules({"path": "character", "summary": "Two men in an explicit scene", "fixed": "two men",
                                                "randomized": "", "must": [], "avoid": [], "characters": MEN}, data)

    @staticmethod
    def scene(place, camera="medium shot", action="man 1 embraces man 2 from behind"):
        return {"subjects": {"man 1": dict(LOOK), "man 2": dict(LOOK)},
                "position": {"man 1": "standing behind his partner", "man 2": "bent over the bed, facing away"},
                "actions": action, "space": place, "lighting": "lamp light", "mood": "intense",
                "camera": camera, "extras": "sheets"}

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage == "dataset_v2:scenes":
            user = composer_user(instruction.user_message)
            return json.dumps({"scenes": [self.replies.pop(0) if self.replies else self.scene(f"room {row['image']}")
                                          for row in user["images"]]})
        return self.final.pop(0)

    def composer(self):
        return [call for call in self.calls if call.diagnostic_stage == "dataset_v2:scenes"]


class SceneVariety(Harness):
    def write(self):
        return scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)

    def test_the_writer_is_told_to_vary_every_image_and_keep_one_possible_arrangement(self):
        self.write()
        system = self.composer()[0].system_message
        self.assertIn("one\n  physically possible arrangement", system)
        self.assertIn("if one person is behind another, that person faces away from them", system)
        self.assertIn("Unless fixed keeps it, never reuse a place, arrangement or camera listed in already_used", " ".join(system.split()))
        self.assertIn("Give the people new looks (skin, build, hair, detail) in every image unless fixed keeps the same people", system)

    def test_each_person_has_an_expression_field_for_expression_vocabulary(self):
        self.write()
        person = self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]["man 1"]
        self.assertIn("expression", person["required"])
        self.assertIn("expression (their face in this moment)", self.composer()[0].system_message)

    def test_the_requested_activity_is_every_images_action(self):
        self.write()
        system = self.composer()[0].system_message
        self.assertIn("never replace it with a lesser, earlier or different activity, and vocabulary never changes it", system)
        self.assertIn("kissing, touching, undressing or foreplay alone never stand in for it", system)

    def test_ten_images_are_written_in_one_answer(self):
        self.write()
        self.assertEqual([len(composer_user(call.user_message)["images"]) for call in self.composer()], [10])

    def test_later_batches_get_a_list_of_what_is_already_used_not_scenes_to_copy(self):
        self.brief["input"]["amount"] = 12
        self.write()
        first, second = (composer_user(call.user_message) for call in self.composer())
        self.assertNotIn("already_used", first)
        used = second["already_used"]
        self.assertEqual(set(used), {"places", "arrangements", "cameras", "looks"})
        self.assertEqual(used["places"], [f"room {n}" for n in range(1, 11)])

    def test_the_live_runs_copied_scenes_are_asked_again(self):
        # the live run: images 6-10 reused the place of images 1-5 with a near-identical camera
        first = [self.scene("A modern, minimalist bedroom with large windows overlooking a city at night.",
                            "Side view, medium shot, eye-level, 35mm lens to capture both bodies.", "man 1 thrusts"),
                 *[self.scene(f"place {n}", f"camera {n}", f"action {n}") for n in range(2, 6)]]
        copies = [self.scene("A modern, minimalist bedroom with large windows overlooking a city at night.",
                             "Side view, medium shot, eye-level, 35mm lens.", "something else entirely"),
                  *[self.scene(f"place {n}", f"camera {n} again", f"other {n}") for n in range(2, 6)]]
        fresh = [self.scene(f"new place {n}", f"new camera {n}", f"new action {n}") for n in range(6, 11)]
        self.replies = first + copies + fresh
        result = self.write()
        self.assertTrue(result["complete"])
        retry = self.composer()[1]
        self.assertEqual([row["image"] for row in composer_user(retry.user_message)["images"]], [6, 7, 8, 9, 10])
        self.assertIn("repeats the place and the camera or arrangement of an earlier image", retry.system_message)
        self.assertEqual(result["scenes"][5]["space"], "new place 6")

    def test_the_same_place_with_a_new_camera_and_arrangement_is_allowed(self):
        self.brief["input"]["amount"] = 2
        self.replies = [self.scene("bedroom", "wide shot", "man 2 rides man 1"),
                        self.scene("bedroom", "close-up from above", "man 1 takes man 2 from behind")]
        result = self.write()
        self.assertEqual((result["written"], len(self.composer())), (2, 1))

    def test_the_last_round_keeps_a_repeat_rather_than_lose_the_image(self):
        self.brief["input"]["amount"] = 2
        self.replies = [self.scene("bedroom"), *[self.scene("bedroom")] * scenes.ROUNDS]
        result = self.write()
        self.assertEqual(result["written"], 2)
        self.assertEqual(len(self.composer()), scenes.ROUNDS)


class FinalLabels(Harness):
    def write(self, final):
        self.final = list(final)
        scene = {"slot": 1, **self.scene("kitchen")}
        self.brief["input"]["amount"] = 1
        return prompts.write_prompts({"backend": "mock"}, self.request, self.brief, [scene], progress=lambda _: None)

    def test_a_prompt_naming_man_1_is_rewritten_once(self):
        written = self.write(["man 1, olive skin, kneeling behind man 2", "The taller man kneels behind his partner."])
        self.assertEqual(written[0]["prompt"], "The taller man kneels behind his partner.")
        builder = [call for call in self.calls if call.diagnostic_stage == "final"]
        self.assertEqual(len(builder), 2)
        self.assertIn('calls a person "man 1"', builder[1].system_message)

    def test_the_writer_sees_ordinals_instead_of_numbered_labels(self):
        self.write(["The taller man kneels behind his partner."])
        final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
        text = final.system_message + final.user_message
        self.assertIn("the first man:", text)
        self.assertIn("position of the second man:", text)
        self.assertNotRegex(text, r"\bman [12]\b")

    def test_a_label_left_after_the_retry_keeps_the_prompt(self):
        written = self.write(["Man1 kneels.", "man_2 leans back."])
        self.assertEqual(written[0]["prompt"], "man_2 leans back.")
        self.assertFalse(written[0].get("error"))

    def test_the_runs_director_shapes_the_final_prompt_but_never_the_scene(self):
        from dataclasses import replace
        self.request = replace(self.request, director_preset="nsfw_director")
        self.write(["The taller man kneels behind his partner."])
        final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
        self.assertIn("DIRECTOR BEHAVIOR — Explicit Adult", final.system_message + final.user_message)
        self.calls.clear()
        self.brief["input"]["amount"] = 1
        scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)
        composer = self.composer()[0]
        self.assertNotIn("Director", composer.system_message + composer.user_message)

    def test_names_and_plain_words_are_not_labels(self):
        brief = {"characters": [{"label": "man 1"}, {"label": "Alex"}, {"label": "woman"}]}
        for text in ("The first man", "a man 10 feet away", "Alex smiles", "a woman reads", "batman 1"):
            self.assertIsNone(prompts.label_problem(text, brief), text)
        for text in ("man 1 stands", "Man1 stands", "MAN-1 stands", "man_1 stands"):
            self.assertIsNotNone(prompts.label_problem(text, brief), text)


if __name__ == "__main__":
    unittest.main()
