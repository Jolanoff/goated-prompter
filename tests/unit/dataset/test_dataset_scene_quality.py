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
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn("one physically possible arrangement", system)
        self.assertIn("a person with someone behind them has their back to that person and looks back only by turning "
                      "their head", system)
        self.assertNotIn("closed loop", system, "a loop is possible when every position reaches both partners")
        # One owner per fact: the act is written once, the positions place the people around it, the camera says what
        # is visible. Live scenes that repeated the act in the positions contradicted it.
        self.assertIn("Every fact of a scene is written once, in its own field", system)
        self.assertIn("A position never repeats the act", system)
        # A live party set gave three of six images the same four looks, which already_used listed.
        self.assertIn("never reuse a place, arrangement, camera or look listed in already_used", system)
        self.assertIn("Everything the request does not mention is chosen anew for each image.", system)
        self.assertIn("Give the people new looks (skin, build, hair, detail) in every image unless fixed keeps the same "
                      "people", system)
        # Live extras left the clothing out and repeated the act, a hand or the place; a kept place gave every image
        # the same spot once the scene was no longer asked for another part of it.
        # Once the scene owned the clothing, live scenes dressed a body part the act uses.
        self.assertIn("first what each person wears (garment, colour, material; nothing over a body part the act uses) "
                      "or that they are bare", system)
        self.assertIn("Never what another field already says (the act, a pose, a hand, the place or what is in it)", system)
        self.assertIn("(another part of the place when the request keeps it)", system)

    def test_each_person_has_an_expression_field_for_expression_vocabulary(self):
        self.write()
        person = self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]["man 1"]
        self.assertIn("expression", person["required"])
        self.assertIn("expression (what their eyes, brows and mouth do in this moment",
                      " ".join(self.composer()[0].system_message.split()))
        # Live expressions said "heavy breathing" or named a feeling, and the final prompt copied what no image shows.
        self.assertIn("never a feeling, a breath or a sound named as a word",
                      " ".join(self.composer()[0].system_message.split()))

    def test_an_adult_dataset_describes_each_persons_genitals_and_where_they_are(self):
        # Live runs named genitals only inside the action: most were never described, and some were drawn without
        # their owner or in place of a tongue.
        self.write()
        person = self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]["man 1"]
        adult = self.brief["path"] == "nsfw_character"
        (self.assertIn if adult else self.assertNotIn)("genitals", person["required"])
        system = " ".join(self.composer()[0].system_message.split())
        # Where genitals are is the act's: live scenes that also placed them in the positions gave them two places.
        (self.assertIn if adult else self.assertNotIn)("Where they are is the act's, so a position never places them",
                                                       system)
        self.assertNotIn("where that person's genitals are", system)
        # Verbs that hid the act ("takes his mouth") stood for acts that then never showed; the bound person stayed soft
        # in every image. The act is said the way people say it, with its verb and the position's name, which image
        # models know; rewritten into body mechanics it lost the name. Live genitals got a colour that did not match the
        # person's skin, so they get only size and state.
        for rule in ("only their size and state (aroused when the act uses them), never a colour",
                     'A vague verb such as "uses", "takes" or "has" never stands for the act',
                     "The actions say the act the way people say it, in everyday words",
                     "never rewritten into how the bodies fit together",
                     # Live scenes dressed everyone but the person the act centred on.
                     "Everyone who takes part in a sexual act is bare, so their extras say bare: a garment is "
                     "given only when the request, the entry or a selected Clothing entry names it",
                     "unless the request gives the roles the other way"):  # roles come from the request, adult sets only
            (self.assertIn if adult else self.assertNotIn)(rule, system)
        sfw = {**self.brief, "path": "character"}
        self.assertNotIn("genitals", scenes.subject_fields(sfw, "man 1"), "never outside an adult dataset")
        self.assertEqual(scenes.subject_fields({**self.brief, "path": "nsfw_character"}, "man 1")[-1], "genitals")

    def test_a_prop_copied_from_an_earlier_image_is_dropped(self):
        # A live writer put the prop suggested for one image into all twelve images.
        props = ["two matching candles", "a leather collar", "a silk scarf"]
        scene = {"extras": "two matching candles burn on the shelf, a leather collar, dark shadows"}
        earlier = ["two matching candles burn on the shelf, a leather collar, a belt on the floor"]
        self.assertEqual(scenes.checks.without_copied_props(scene, props, ["a leather collar"], earlier)["extras"],
                         "a leather collar, dark shadows", "the collar was suggested for this image")
        self.assertEqual(scenes.checks.without_copied_props(scene, props, [], [])["extras"], scene["extras"],
                         "the first image to use a prop keeps it")
        self.assertEqual(scenes.checks.without_copied_props(scene, props, ["two matching candles", "a leather collar"],
                                                            earlier), scene, "a prop suggested for every image stays")

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
        # A body part turned away or hidden by another body is never written as visible: the camera, written after the
        # positions, says what the image shows.
        self.write()
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn("inside the frame and visible (a part another body or a surface covers, or one turned away from "
                      "the viewpoint, is not)", system)
        self.assertIn("Describe a body part only when the scene's positions and camera let the camera see it",
                      " ".join(prompts.SCENE_RULES.split()))

    def test_every_act_is_reachable_and_the_positions_agree_with_the_actions(self):
        self.write()
        system = " ".join(self.composer()[0].system_message.split())
        self.assertIn("a person takes part in two acts at once only when their position reaches both partners", system)
        self.assertIn("the positions and the actions agree on who does what to whom", system)

    def test_the_requested_activity_is_every_images_action(self):
        self.write()
        system = " ".join(self.composer()[0].system_message.split())
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
        # A part the request mentions stays in every image, so it is never a copy; the parts it leaves open still are.
        labels = ["man 1", "man 2"]
        self.assertEqual(scenes.checks.repeated_parts(same, first, labels, kept=["place", "action"]), ["camera", "extras"])
        self.assertEqual(scenes.checks.repeated_parts(same, first, labels, kept=["camera", "objects"]), ["actions"])
        message = scenes.request.compose_message({**self.brief, "kept": ["place", "action"]}, [{"image": 1}])
        self.assertIn('"kept": [', message)
        self.assertNotIn('"kept"', scenes.request.compose_message({**self.brief, "kept": []}, [{"image": 1}]))
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


class EntryCopy(unittest.TestCase):
    labels = ["22 yo male", "man 1", "man 2"]

    def clean(self, actions):
        return scenes.checks.without_entry_copy({"actions": actions}, self.labels)["actions"]

    def test_a_copied_entry_head_with_placeholder_people_is_dropped(self):
        rest = "man 1's penis is inside 22 yo male's anus while man 2 holds 22 yo male"
        for head in ("two tops: one person held in [Restraint Gear] between two men", "two tops: one person bound"):
            self.assertEqual(self.clean(f"{head}, {rest}"), rest)
            self.assertEqual(self.clean(f"{rest}; {head}"), rest)
            self.assertEqual(self.clean(f"{rest}; {head}, {rest}"), f"{rest}; {rest}")

    def test_a_name_with_people_or_an_act_that_would_lose_someone_stays(self):
        for kept in ("hogtie: man 1 binds 22 yo male while man 2 watches",
                     "man 1 and man 2: they take turns with 22 yo male",
                     # Dropping this head would leave man 2 out of the act.
                     "two tops: one person bound, man 1's penis is in 22 yo male's mouth"):
            self.assertEqual(self.clean(kept), kept)


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

    def test_the_runs_director_shapes_the_scene_and_the_final_prompt_writes_it_as_decided(self):
        # A live final writer given the Director's emphasis added states and acts the decided scene did not have, so
        # the Director decides each scene's emphasis once and the final prompt writes the scene as decided.
        from dataclasses import replace
        self.request = replace(self.request, director_preset="nsfw_director")
        self.brief["settings"] = {**self.brief["settings"], "director": "nsfw_director"}
        self.write(["The taller man kneels behind his partner."])
        final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
        self.assertNotIn("DIRECTOR BEHAVIOR", final.system_message)
        for layer in ("PRIORITY AND CONFLICT RESOLUTION", "FRAME COMPLETENESS DEFAULT", "MODE ADAPTER",
                      "PRESERVATION CONSTRAINTS", "Creativity —"):
            self.assertNotIn(layer, final.system_message, "a decided scene is not designed again")
        self.assertIn("The idea is one image whose scene is already decided", final.system_message)
        self.assertIn("TARGET MODEL ADAPTER", final.system_message)
        self.calls.clear()
        self.brief["input"]["amount"] = 1
        scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)
        composer = self.composer()[0]
        self.assertIn("DIRECTOR EMPHASIS — Explicit Adult", composer.system_message)

    def test_names_and_plain_words_are_not_labels(self):
        brief = {"characters": [{"label": "man 1"}, {"label": "Alex"}, {"label": "woman"}]}
        for text in ("The second man", "a man 10 feet away", "Alex smiles", "a woman reads", "batman 1", "at first, a man"):
            self.assertIsNone(prompts.label_problem(text, brief), text)
        for text in ("man 1 stands", "Man1 stands", "MAN-1 stands", "man_1 stands", "The first man stands"):
            self.assertIsNotNone(prompts.label_problem(text, brief), text)


class RequestedProps(unittest.TestCase):
    def test_a_count_in_the_request_never_names_a_prop(self):
        # A request about "two men" was read as asking for a prop named "two ...", suggested for every image.
        from goated_prompter.features.dataset.v2.scenes import entries
        props = ["two matching candles", "a silk scarf", "soft rope", "a leather collar", "a wooden chair"]
        brief = {"input": {"request": "the 22 yo with 2 men"}, "fixed": "a man with two men", "must": []}
        self.assertEqual(entries.requested_entries(props, entries.requested_words(brief)), [])
        named = {**brief, "input": {"request": "a man with two men, wearing a silk scarf"}}
        self.assertEqual(entries.requested_entries(props, entries.requested_words(named)), ["a silk scarf"])


class CaptureLine(Harness):
    def test_the_final_writer_reads_the_capture_as_part_of_the_scene(self):
        # A live run's final writer left "black-and-white" out of 5 of 12 prompts when the capture was only a rule.
        self.final = ["A prompt about two men.", "Another prompt."]
        for capture, expected in (("Black-and-white film", True), ("Auto", False)):
            self.calls.clear()
            brief = {**self.brief, "settings": {**self.brief["settings"], "style": "Realistic", "capture": capture},
                     "input": {**self.brief["input"], "amount": 1}}
            prompts.write_prompts({"backend": "mock"}, self.request, brief, [{"slot": 1, **self.scene("kitchen")}],
                                  progress=lambda _: None)
            final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
            (self.assertIn if expected else self.assertNotIn)("capture: Black-and-white film", final.user_message)


class NoColor(Harness):
    """A style or capture without colour tells the scene writer to write looks as tones, and nothing else does."""

    def test_only_a_colourless_choice_adds_the_rule(self):
        for style, capture, expected in (("Realistic", "Black-and-white film", True), ("Manga / Shojo", "Auto", True),
                                         ("Sketch", "Auto", True), ("Realistic", "Analog film", False),
                                         ("Anime", "Auto", False), ("Auto", "Auto", False)):
            self.calls.clear()
            brief = {**self.brief, "settings": {**self.brief["settings"], "style": style, "capture": capture},
                     "input": {**self.brief["input"], "amount": 1}}
            scenes.write_scenes({"backend": "mock"}, self.request, brief, progress=lambda _: None)
            (self.assertIn if expected else self.assertNotIn)("NO COLOUR", self.composer()[0].system_message, (style, capture))


class AspectRatio(Harness):
    """The Aspect ratio setting reaches both writers as one rule, only when a ratio is chosen."""

    def run_with(self, ratio):
        brief = {**self.brief, "settings": {**self.brief["settings"], **({"aspect": ratio} if ratio else {})}, "input": {**self.brief["input"], "amount": 1}}
        scenes.write_scenes({"backend": "mock"}, self.request, brief, progress=lambda _: None)
        self.final = ["A prompt about two men."]
        prompts.write_prompts({"backend": "mock"}, self.request, brief, [{"slot": 1, **self.scene("kitchen")}], progress=lambda _: None)
        writer = " ".join(self.composer()[0].system_message.split())
        final = " ".join([call for call in self.calls if call.diagnostic_stage == "final"][0].system_message.split())
        return writer, final

    def test_the_shape_comes_from_the_numbers(self):
        from goated_prompter.features.dataset.v2.aspect import aspect_shape
        self.assertEqual(aspect_shape("3:4")[0], "tall")
        self.assertEqual(aspect_shape("16:9")[0], "wide")
        self.assertEqual(aspect_shape("1:1")[0], "square")
        for ratio in ("Auto", "", None, "3x4", "0:4", "-3:4"):
            self.assertIsNone(aspect_shape(ratio), ratio)

    def test_no_ratio_adds_nothing_to_either_writer(self):
        for ratio in (None, "Auto"):
            self.calls.clear()
            for text in self.run_with(ratio):
                self.assertNotIn("IMAGE SHAPE", text)

    def test_a_chosen_ratio_is_told_to_both_writers_with_its_shape(self):
        writer, final = self.run_with("3:4")
        self.assertIn("Every image is 3:4, a tall frame", writer)
        # The frame never overrides a pose the request or the entry decides (people side by side in a tall frame).
        self.assertIn("change a pose only when neither the request nor the image's entry decides it", " ".join(writer.split()))
        self.assertIn("spread the people and the action over its height", writer)
        # A live tall image showed a level body from the side across the short side and the image model broke the bodies.
        self.assertIn("The arrangement's longest line runs along the frame's long side", writer)
        self.assertIn("never from the side at full length", writer)
        self.assertIn("IMAGE SHAPE: the image is 3:4, a tall frame", final)
        self.calls.clear()
        writer, final = self.run_with("16:9")
        self.assertIn("a wide frame", writer)
        self.assertIn("over its width, from left to right", final)

    def test_the_draft_accepts_the_listed_ratios_and_nothing_else(self):
        from goated_prompter.features.dataset.v2.draft import validate_dataset_draft
        from goated_prompter.options.dataset import ASPECT_RATIO_NAMES
        for ratio in ASPECT_RATIO_NAMES:
            self.assertEqual(validate_dataset_draft({**default_dataset_draft(), "aspect": ratio})["aspect"], ratio)
        self.assertEqual(default_dataset_draft()["aspect"], "Auto")
        with self.assertRaises(ValueError):
            validate_dataset_draft({**default_dataset_draft(), "aspect": "7:5"})
        self.assertEqual(understanding.copied_settings({**default_dataset_draft(), "aspect": "2:3"})["aspect"], "2:3")


if __name__ == "__main__":
    unittest.main()
