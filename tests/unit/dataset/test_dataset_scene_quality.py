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
from tests.support.dataset_scenes import composer_user, without_looks, without_places

MEN = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}]
LOOK = {"skin": "tan", "build": "athletic", "hair": "short dark hair", "eyes": "brown", "expression": "a soft smile",
        "genitals": "average size, relaxed", "clothing": "no clothing"}


class Harness(unittest.TestCase):
    def setUp(self):
        without_places(self)
        without_looks(self)
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
        look = lambda who: {**LOOK, **{field: f"{who}{place}{camera}{field}".replace(" ", "") for field in ("skin", "build", "hair", "eyes")}}
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
        self.assertIn("Every other part is chosen anew for each image.", system)
        self.assertIn("Give the people new looks (skin, build, hair, eyes) in every image unless fixed keeps the same "
                      "people", system)
        # Live extras left the clothing out and repeated the act, a hand or the place; a kept place gave every image
        # the same spot once the scene was no longer asked for another part of it.
        # Once the scene owned the clothing, live scenes dressed a body part the act uses.
        self.assertIn("first what each person wears (garment, colour, material; nothing over a body part the act uses) "
                      "or that they are bare", system)
        self.assertIn("Never what another field already says (the act, a pose, a hand, the place or what is in it)", system)
        # Local models added wounds and blood as "marks" for a request's abstract words, and dressed animals.
        self.assertIn("a mark on someone's body (a tattoo, a scar, a wound, blood) only when the request asks for it",
                      system)
        # A live set tagged Pikachu "bare": a character that wears no clothes by nature gets no clothing words.
        self.assertIn("a character that wears no clothes by nature (an animal, most creatures) gets no clothing words "
                      "at all, neither a garment nor bare, only what the request gives it", system)
        self.assertIn("(another part of the place when the place is themed; the same spot and background in every image when it is locked)", system)

    def test_each_person_has_an_expression_field_for_expression_vocabulary(self):
        self.write()
        person = self.composer()[0].json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]["man 1"]
        self.assertIn("expression", person["required"])
        self.assertIn("expression (visible facial expression described through the eyes, eyebrows and mouth)",
                      " ".join(self.composer()[0].system_message.split()))
        # Almost every person got a scar, a wound or a tattoo as their one distinguishing detail; the eyes replace it.
        self.assertIn("eyes", person["required"])
        self.assertNotIn("detail", person["required"])

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
        # The frame dealt to an image only spreads the set: a live known character framed narrower than the dealt full
        # body was asked again, though the image was fine.
        self.assertEqual(scenes.checks.framing_problems(
            {**tight, "frame": {"man 1": frame("head to knees"), "man 2": frame("full body")}}, frozenset({"man 1"})), [])
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
        # A live request asked for the feet and six of ten frames stopped at the hips or knees.
        written = " ".join(first.system_message.split())
        self.assertIn("Every body part the action uses or the request asks to show is inside each person's frame", written)
        self.assertIn("wider only when the action or the request needs it", written)
        self.assertIn("and every body part the request asks to show in every image", written)
        self.assertIn("man 1 is a known character: show them at least head to hips",
                      " ".join(self.composer()[1].system_message.split()), "too tight to show who they are")
        self.assertTrue(all(scene["frame"]["man 1"]["shows"] == "full body" for scene in result["scenes"]))
        schema = first.json_schema["properties"]["scenes"]["items"]["properties"]["frame"]
        self.assertEqual(schema["properties"]["man 1"]["properties"]["shows"]["enum"], list(scenes.settings.SHOWS))

    def test_a_request_that_keeps_the_camera_is_dealt_no_frames(self):
        # A live request asked for the feet; the frames dealt to a third of the images stopped at the hips, and the
        # writer followed the deal over the request. A camera the request keeps in words no camera part holds decides
        # the camera and the framing on its own (scenes/camera.py; test_dataset_camera.py covers the dealt ones).
        self.brief["characters"][0]["known"] = True
        self.brief["consistency"] = {**self.brief["consistency"], "action": "themed", "camera": "themed"}
        self.brief["kept_words"] = {**(self.brief.get("kept_words") or {}), "camera": "from behind"}
        known = {**self.scene("bedroom"), "frame": {"man 1": {"shows": "full body", "face": "visible"},
                                                     "man 2": {"shows": "full body", "face": "visible"}},
                 "subjects": {**self.scene("x")["subjects"], "man 1": {"expression": "a smile"}}}
        self.replies = [known]
        self.brief["input"]["amount"] = 1
        self.write()
        first = self.composer()[0]
        self.assertNotIn("frame", composer_user(first.user_message)["images"][0], "the request decides the framing")
        written = " ".join(first.system_message.split())
        self.assertIn("FRAMES", written, "known characters still fill the frame field")
        self.assertIn("Each known character (man 1) is shown at least head to hips", written)
        self.assertNotIn("Each image in IMAGES names the frame", written)
        self.assertFalse(scenes.deals_frames(self.brief))
        self.assertTrue(scenes.deals_frames({**self.brief, "consistency": {**self.brief["consistency"], "camera": "free"}}))
        self.assertFalse(scenes.deals_frames({**self.brief, "characters": [{"label": "man 1"}]}), "no known character")

    def test_a_frame_narrower_than_its_own_camera_is_widened(self):
        # A live set framed a known character head to knees in every image while each camera showed the feet; the
        # final tag followed the frame and cropped them.
        frame = lambda shows: {"shows": shows, "face": "visible"}
        scene = {"camera": "front view, man 1's head, torso, and feet, man 2's chest; man 1's feet rest on the floor",
                 "frame": {"man 1": frame("head to knees"), "man 2": frame("head to hips")}}
        self.assertEqual(scenes.checks.framed_to_camera(scene)["frame"],
                         {"man 1": frame("full body"), "man 2": frame("head to hips")}, "only whose feet show")
        hidden = {**scene, "camera": "side view, man 1 from head to hips, his feet are out of frame"}
        self.assertIs(scenes.checks.framed_to_camera(hidden), hidden, "a part the camera says is hidden")
        legs = {**scene, "camera": "man 2's legs spread, man 1 head to hips"}
        self.assertEqual(scenes.checks.framed_to_camera(legs)["frame"]["man 2"], frame("head to knees"))
        no_frames = {"camera": "man 1's feet"}
        self.assertIs(scenes.checks.framed_to_camera(no_frames), no_frames, "no frame field, nothing to widen")
        # Through the writer: the accepted scene keeps its camera and gets the wider frame.
        self.brief["characters"][0]["known"] = True
        self.brief["input"]["amount"] = 1
        self.replies = [{**self.scene("bedroom", "front view, man 1's head, torso and feet"),
                         "frame": {"man 1": frame("head to knees"), "man 2": frame("full body")},
                         "subjects": {**self.scene("x")["subjects"], "man 1": {"expression": "a smile"}}}]
        result = self.write()
        self.assertEqual(result["scenes"][0]["frame"]["man 1"]["shows"], "full body")
        self.assertEqual(len(self.composer()), 1, "widened, never asked again")

    def test_no_frame_tighter_than_the_request_asks_for_is_dealt(self):
        # A live request for the feet was dealt hips-up and knees-up frames, and the writer followed the deal.
        import random
        from goated_prompter.features.dataset.v2.scenes import entries
        feet = {"input": {"request": "a knight in a hall"}, "must": ["feet visible"], "kept_words": {}}
        self.assertEqual(entries.required_frame(feet), "full body")
        self.assertEqual(set(entries.deal_frames(6, random.Random(1), "full body").values()), {"full body"})
        legs = {"input": {"request": "a knight with legs crossed; his feet out of frame"}, "must": [], "kept_words": {}}
        self.assertEqual(entries.required_frame(legs), "head to knees", "a hidden part asks for nothing")
        self.assertEqual(set(entries.deal_frames(6, random.Random(1), "head to knees").values()),
                         {"full body", "head to knees"})
        camera = {"input": {"request": "a knight"}, "must": [], "kept_words": {"camera": "his boots and feet in frame"}}
        self.assertEqual(entries.required_frame(camera), "full body", "the camera words count too")
        self.assertIsNone(entries.required_frame({"input": {"request": "a knight"}, "must": []}))
        self.assertEqual(entries.deal_frames(6, random.Random(1)), entries.deal_frames(6, random.Random(1), None),
                         "a request naming no body part deals as before")

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
        self.brief["input"]["amount"] = scenes.BATCH + 2
        self.write()
        first, second = (composer_user(call.user_message) for call in self.composer())
        self.assertNotIn("already_used", first)
        used = second["already_used"]
        self.assertEqual(set(used), {"places", "arrangements", "cameras", "extras", "looks"})
        self.assertEqual(len(used["extras"]), scenes.BATCH, "props and signs are not repeated either")
        self.assertEqual(used["places"], [f"room {n}" for n in range(1, scenes.BATCH + 1)])

    def test_a_copy_of_an_earlier_image_is_kept_without_asking_again(self):
        # A live run asked seven of ten images again for repeating a place and camera the request itself kept; asking
        # whole copies again later cost a third more time, came back as copies and dropped part of the act. Variety is
        # the prompt's and the vocabulary's job, never a redo.
        first = [self.scene("bathroom", "front view, eye level", "man 1 kneels"),
                 *[self.scene(f"place {n}", f"camera {n}", f"action {n}") for n in range(2, 6)]]
        copies = [self.scene("bathroom", "front view, eye level", "man 1 kneels"),
                  *[self.scene(f"place {n}", f"camera {n}", f"action {n}") for n in range(2, 6)]]
        self.replies = first + copies
        result = self.write()
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.composer()), 1, "nobody is asked again for a copy")
        self.assertEqual(result["scenes"][5]["space"], "bathroom")
        self.assertIn("never reuse a place, arrangement, camera or look listed in already_used",
                      " ".join(self.composer()[0].system_message.split()), "the writer is still asked for variety")

    def test_a_locked_subject_holds_only_the_people_its_words_name(self):
        # A live set that locked one named character also froze the looks of everyone around him.
        locked = {**self.brief, "consistency": {**self.brief["consistency"], "subject": "locked"},
                  "kept_words": {"subject": "the same man 1"}}
        self.assertEqual(scenes.request.locked_people(locked), {"man 1"})
        self.assertEqual(scenes.request.varied_labels(locked), {"man 2"})
        everyone = {**locked, "kept_words": {"subject": "the same two men"}}
        self.assertEqual(scenes.request.locked_people(everyone), {"man 1", "man 2"}, "nobody in particular: everyone")
        self.assertEqual(scenes.request.varied_labels(everyone), frozenset())
        self.assertEqual(scenes.request.locked_people(self.brief), frozenset(), "a subject that is not locked")
        earlier = [{"space": "a", "camera": "b", "actions": "c", "extras": "d",
                    "looks": {"man 1": {"skin": "tan", "hair": "black"}, "man 2": {"skin": "pale", "hair": "red"}}}]
        message = scenes.compose_message(locked, [{"image": 2}], earlier)
        images = json.loads(message.split("IMAGES:\n", 1)[1])
        self.assertEqual(images["same_as_image_1"]["looks"], {"man 1": {"skin": "tan", "hair": "black"}})
        self.assertEqual(images["already_used"]["looks"], [{"man 2": {"skin": "pale", "hair": "red"}}])

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

    def test_the_writer_is_told_each_held_part_with_its_level_and_the_users_words(self):
        held = {**{part: "free" for part in self.brief["consistency"]}, "place": "locked", "action": "themed"}
        brief = {**self.brief, "consistency": held, "kept_words": {"place": "in a library"}}
        message = composer_user(scenes.request.compose_message(brief, [{"image": 1}]))
        self.assertEqual(message["understanding"]["consistency"],
                         {"action": {"level": "themed"}, "place": {"level": "locked", "words": "in a library"}})
        self.assertIn("CONSISTENCY\nunderstanding.consistency lists", scenes.request._system(brief, ()))
        free = {**self.brief, "consistency": {part: "free" for part in held}, "kept_words": {}}
        self.assertNotIn("consistency", composer_user(scenes.request.compose_message(free, [{"image": 1}]))["understanding"])
        self.assertNotIn("CONSISTENCY\n", scenes.request._system(free, ()))
        # A locked part is copied from the first image and never listed as something to avoid.
        earlier = [scenes._summary({**self.scene("reading room"), "slot": 1})]
        message = composer_user(scenes.request.compose_message(brief, [{"image": 2}], earlier))
        self.assertEqual(message["same_as_image_1"], {"space": "reading room"})
        self.assertNotIn("places", message["already_used"])
        self.assertIn("arrangements", message["already_used"], "a themed act still varies")
    def test_a_locked_part_is_never_a_reason_to_ask_again(self):
        # A live check that wanted every word of a locked part in the scene asked every correct image again: scenes
        # say the part in their own words. The quality tool measures drift instead (locked_drift).
        self.brief["consistency"] = {**self.brief["consistency"], "place": "locked"}
        self.brief["kept_words"] = {"place": "in front of the same red brick wall"}
        self.brief["input"]["amount"] = 1
        self.replies = [self.scene("a red brick wall")]
        self.write()
        self.assertEqual(len(self.composer()), 1)

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

    def test_the_last_round_keeps_a_flawed_scene_rather_than_lose_the_image(self):
        self.brief["input"]["amount"] = 2
        unnamed = {**self.scene("garden", "low angle"), "actions": "man 1 kneels"}  # man 2 is never named
        self.replies = [self.scene("bedroom"), *[unnamed] * scenes.ROUNDS]
        result = self.write()
        self.assertEqual(result["written"], 2)
        self.assertEqual(len(self.composer()), scenes.ROUNDS)
        self.assertIn("its actions do not name man 2", self.composer()[1].system_message)


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
