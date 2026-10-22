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
LOOK = {"skin": "tan", "build": "athletic", "hair": "short dark hair", "detail": "stubble", "expression": "a soft smile",
        "genitals": "average size, relaxed", "clothing": "no clothing"}


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
        # Every image has new people (a look repeated from an earlier image is asked again).
        look = lambda who: {**LOOK, **{field: f"{who}{place}{camera}{field}".replace(" ", "") for field in ("skin", "build", "hair", "detail")}}
        return {"subjects": {"man 1": look("a"), "man 2": look("b")},
                "position": {"man 1": "standing behind his partner", "man 2": "bent over the bed, facing away"},
                "actions": action if "man 2" in action else f"man 1 and man 2: {action}", "space": place,
                "lighting": "lamp light", "mood": "intense",
                "camera": camera, "extras": f"sheets{place}{camera}".replace(" ", ""),
                "frame": {label: {"shows": "full body", "face": "visible"} for label in ("man 1", "man 2")}}

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

    def test_an_adult_dataset_describes_each_persons_genitals_and_where_they_are(self):
        # Live runs named genitals only inside the action: most were never described, and some were drawn without
        # their owner or in place of a tongue.
        self.write()
        person = self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]["man 1"]
        adult = self.brief["path"] == "nsfw_character"
        (self.assertIn if adult else self.assertNotIn)("genitals", person["required"])
        system = " ".join(self.composer()[0].system_message.split())
        (self.assertIn if adult else self.assertNotIn)("Each position also says where that person's genitals are", system)
        sfw = {**self.brief, "path": "character"}
        self.assertNotIn("genitals", scenes.subject_fields(sfw, "man 1"), "never outside an adult dataset")
        self.assertEqual(scenes.subject_fields({**self.brief, "path": "nsfw_character"}, "man 1")[-1], "genitals")

    def test_every_person_has_a_frame_and_nobody_needed_drops_out(self):
        # Live runs kept the action and cropped a character to the upper body or dropped their body around the genitals.
        frame = lambda shows, face="visible": {"shows": shows, "face": face}
        tight = {**self.scene("bedroom"), "frame": {"man 1": frame("head and shoulders"), "man 2": frame("full body")}}
        self.assertEqual(scenes.checks.framing_problems(tight), [], "only known characters have a minimum in code")
        hidden = {**tight, "frame": {"man 1": frame("full body", "hidden"), "man 2": frame("head to knees")}}
        self.assertIn("man 1 is a known character", scenes.checks.framing_problems(hidden, frozenset({"man 1"}))[0])
        self.assertEqual(scenes.checks.framing_problems(hidden, frozenset({"man 2"})), [])
        self.assertIn("this image shows man 1 full body", scenes.checks.framing_problems(
            {**tight, "frame": {"man 1": frame("head to knees"), "man 2": frame("full body")}}, frozenset({"man 1"}),
            "full body")[0], "a known character gets the frame dealt to the image, or wider")
        self.assertEqual(scenes.checks.framing_problems(
            {**tight, "frame": {"man 1": frame("full body"), "man 2": frame("head and shoulders")}}, frozenset({"man 1"}),
            "head to hips"), [])
        # Without known characters there is no frame to fill.
        self.write()
        self.assertNotIn("frame", self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"])
        self.assertNotIn("FRAMES", self.composer()[0].system_message)
        # With one, every image is dealt a frame, the writer is asked again below it and the next answer is kept.
        self.calls.clear()
        self.brief["input"]["amount"] = 3
        self.brief["characters"][0]["known"] = True  # man 1 as a known character
        known = lambda shows: {**self.scene(f"room {shows}"), "frame": {"man 1": frame(shows), "man 2": frame("full body")},
                               "subjects": {**self.scene("x")["subjects"], "man 1": {"expression": "a smile"}}}
        self.replies = [known("head and shoulders"), known("full body"), known("full body"), known("full body")]
        result = self.write()
        first = self.composer()[0]
        self.assertEqual(sorted(image["frame"] for image in composer_user(first.user_message)["images"]),
                         sorted(scenes.settings.AT_LEAST_HIPS), "the set spreads over the three frames")
        self.assertIn("FRAMES", first.system_message)
        self.assertIn("this image shows man 1", " ".join(self.composer()[1].system_message.split()))
        self.assertTrue(all(scene["frame"]["man 1"]["shows"] == "full body" for scene in result["scenes"]))
        schema = first.json_schema["properties"]["scenes"]["items"]["properties"]["frame"]
        self.assertEqual(schema["properties"]["man 1"]["properties"]["shows"]["enum"], list(scenes.settings.SHOWS))

    def test_the_final_prompt_gets_each_frame_and_its_tag(self):
        from goated_prompter.features.dataset.v2 import prompts
        scene = {"slot": 1, **self.scene("bedroom"),
                 "frame": {"man 1": {"shows": "head to knees", "face": "visible"},
                           "man 2": {"shows": "full body", "face": "hidden"}}}
        text = prompts.scene_text(scene)
        self.assertIn("frame of man 1: shows head to knees (tag: cowboy shot), face visible", text)
        self.assertIn("frame of man 2: shows full body (tag: full body), face hidden", text)
        old = {key: value for key, value in scene.items() if key != "frame"}
        self.assertNotIn("frame of", prompts.scene_text(old), "a scene saved before frames still reads")

    def test_only_what_the_camera_can_see_is_described(self):
        # A body part turned away, hidden by another body or inside someone is never written as visible.
        self.write()
        self.assertIn("which of their\n  body parts the camera can see", self.composer()[0].system_message)
        self.assertIn("Describe a body part only when the scene's positions and camera let the camera see it",
                      " ".join(prompts.SCENE_RULES.split()))

    def test_every_act_is_reachable_and_the_positions_agree_with_the_actions(self):
        self.write()
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn("a person takes part in two acts at once only when their position reaches both partners", system)
        self.assertIn("The positions and the actions agree on who does what to whom", system)

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
        self.assertEqual(set(used), {"places", "arrangements", "cameras", "extras", "looks"})
        self.assertEqual(len(used["extras"]), 10, "props and signs are not repeated either")
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
        self.assertIn("image 6: it repeats image 1's place together with its camera and extras; write a different scene",
                      retry.system_message)
        self.assertEqual(result["scenes"][5]["space"], "new place 6")

    def test_the_character_labels_never_make_two_cameras_a_repeat(self):
        labels = ["man 1", "man 2"]
        first = self.scene("hotel room", "low angle, man 1's head and man 2's torso are in frame", "man 1 kneels")
        second = self.scene("hotel room", "high angle, man 1's back and man 2's face are in frame", "man 2 sits")
        self.assertEqual(scenes.checks.repeated_parts(second, first, labels), [])
        copy = self.scene("hotel room", "low angle, man 1's head and man 2's torso are in view", "man 2 sits")
        self.assertIn("camera", scenes.checks.repeated_parts(copy, first, labels), "the same viewpoint is still a repeat")

    def test_the_character_labels_never_make_two_places_the_same(self):
        # A live run read these two rooms as one place: the labels were most of their words.
        labels = ["man 1", "man 2", "man 3"]
        first = self.scene("bedroom, man 1, man 2, and man 3 lie on a soft mattress, a wooden headboard is behind man 1",
                           "side view, eye level, man 1 is framed head to hips", "man 1 kneels")
        second = self.scene("bedroom, man 1, man 2, and man 3 lie on a soft mattress, a bookshelf is against the wall",
                            "side view, eye level, man 1 is framed head to hips", "man 1 kneels")
        self.assertEqual(scenes.checks.repeated_parts(second, first, labels), [])
        self.assertEqual(scenes.checks._without("2 chairs by man 2", labels).split(), ["2", "chairs", "by"])

    def test_the_same_viewpoint_is_a_repeat_only_with_the_same_arrangement(self):
        labels = ["man 1", "man 2"]
        first = self.scene("hotel room", "side view, eye level, man 1's head and man 2's hips are in frame", "man 1 kneels")
        moved = {**self.scene("hotel room", "side view, eye level, man 2's back is in frame", "man 2 sits"),
                 "position": {"man 1": "lying on the couch", "man 2": "sitting on the armrest"}}
        self.assertEqual(scenes.checks.repeated_parts(moved, first, labels), [], "same room and angle, new arrangement")
        same = self.scene("hotel room", "side view, eye level, man 2's back is in frame", "man 2 sits")
        self.assertEqual(scenes.checks.repeated_parts(same, first, labels), ["camera"])

    def test_the_first_request_lists_this_runs_labels(self):
        # A live run's first answers wrote "one man" and "the others" for numbered people and were all asked again.
        self.write()
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn("In every image, the actions name each of man 1 and man 2 by that label", system)
        self.assertTrue(system.endswith('even when the entry says so.'), "last, where the retries put it")

    def test_the_log_says_why_an_image_is_asked_again_and_what_it_said(self):
        from goated_prompter.features.dataset.v2.scenes.writer import rejected_note
        scene = {**self.scene("bedroom"), "actions": "the first man   kneels"}
        self.assertEqual(rejected_note(3, "its actions do not name man 2", scene),
                         'Image 3 is asked again: its actions do not name man 2. Its actions were: "the first man kneels"')
        self.assertEqual(rejected_note(4, "an answer was missing", None), "Image 4 is asked again: an answer was missing.")
        long = {**scene, "actions": "x" * 400}
        self.assertTrue(rejected_note(5, "reason", long).endswith('..."'))

    def test_a_repeat_names_the_image_and_the_parts_it_reuses(self):
        first = self.scene("bedroom", "wide shot", "man 2 rides man 1")
        same = self.scene("bedroom", "wide shot", "man 2 rides man 1")
        other = self.scene("kitchen", "wide shot", "man 2 rides man 1")
        self.assertEqual(scenes.checks.repeated_parts(same, first, ["man 1", "man 2"]), ["camera", "actions", "extras"])
        self.assertEqual(scenes.checks.repeated_parts(other, first, ["man 1", "man 2"]), [], "another place is no repeat")
        self.assertEqual(scenes.checks.repeat_reason({**first, "slot": 4}, ["camera", "extras"]),
                         "it repeats image 4's place together with its camera and extras; write a different scene")
        self.assertIn("an earlier image", scenes.checks.repeat_reason(first, ["camera"]))

    def test_an_image_asked_again_may_not_copy_an_earlier_images_place_and_signs(self):
        self.brief["input"]["amount"] = 2
        first, copy, fresh = (self.scene(*parts) for parts in (("bedroom", "wide shot", "man 2 rides man 1"),
                                                                ("bedroom", "close-up from above", "man 1 kneels"),
                                                                ("garden", "low angle", "man 1 kneels")))
        copy["extras"] = first["extras"] = "a brass bell, a ledger of names"
        self.replies = [first, copy, fresh]
        result = self.write()
        self.assertEqual([scene["space"] for scene in result["scenes"]], ["bedroom", "garden"])

    def test_the_same_place_with_a_new_camera_and_arrangement_is_allowed(self):
        self.brief["input"]["amount"] = 2
        self.replies = [self.scene("bedroom", "wide shot", "man 2 rides man 1"),
                        self.scene("bedroom", "close-up from above", "man 1 takes man 2 from behind")]
        result = self.write()
        self.assertEqual((result["written"], len(self.composer())), (2, 1))

    def test_repeated_looks_are_kept_and_earlier_looks_are_shown_field_by_field(self):
        # Asking again for new looks made the writer copy an accepted image; looks only tell the people apart.
        self.brief["input"]["amount"] = 2
        same = self.scene("bedroom")
        self.replies = [same, {**self.scene("kitchen", "wide shot", "man 2 rides man 1"), "subjects": same["subjects"]}]
        result = self.write()
        self.assertEqual(([scene["space"] for scene in result["scenes"]], len(self.composer())), (["bedroom", "kitchen"], 1))
        looks = scenes._summary(result["scenes"][0])["looks"]["man 1"]
        self.assertEqual(looks, {"skin": same["subjects"]["man 1"]["skin"], "hair": same["subjects"]["man 1"]["hair"]})
        named = {**self.brief, "characters": [{**person, "label": person["label"].title()} for person in self.brief["characters"]]}
        self.assertEqual(scenes.varied_labels(named), frozenset())
        self.assertEqual(scenes.varied_labels({"characters": [{"label": "man 1", "known": True}, {"label": "man 2", "triggers": [1]},
                                                              {"label": "man 3"}]}), {"man 3"})

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

    def test_the_writer_sees_each_person_by_their_own_look_not_a_number_or_order(self):
        self.write(["The taller man kneels behind his partner."])
        final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
        text = final.system_message + final.user_message
        first, second = prompts.anchors({"subjects": self.scene("kitchen")["subjects"]}, self.brief).values()
        self.assertIn(f"{first}:", text)
        self.assertIn(f"position of {second}:", text)
        self.assertNotRegex(text, r"\bman [12]\b")
        self.assertNotIn("first man", text)
        named = {**self.brief, "characters": [{**person, "triggers": [1]} for person in self.brief["characters"]]}
        self.assertEqual(prompts.anchors({"subjects": self.scene("kitchen")["subjects"]}, named), {},
                         "a triggered person keeps the label its trigger is placed by")
        self.assertEqual(prompts.name_people("man 1 waves", named, {}), "the first man waves")

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
        for text in ("The second man", "a man 10 feet away", "Alex smiles", "a woman reads", "batman 1", "at first, a man"):
            self.assertIsNone(prompts.label_problem(text, brief), text)
        for text in ("man 1 stands", "Man1 stands", "MAN-1 stands", "man_1 stands", "The first man stands"):
            self.assertIsNotNone(prompts.label_problem(text, brief), text)


if __name__ == "__main__":
    unittest.main()
