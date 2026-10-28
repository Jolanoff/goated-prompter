"""Cameras dealt to every image (v2/scenes/camera.py): whole cameras that suit the image's body positions and shape,
show what the request asks to show, keep the request's own camera words and give known characters their frame.
Scripted models only."""

import random
import unittest

from goated_prompter.features.dataset.v2.scenes import camera
from goated_prompter.features.dataset.v2.scenes.settings import AT_LEAST_HIPS, SHOWS
from goated_prompter.features.vocabulary.catalog import load_catalog
from goated_prompter.features.vocabulary.retrieval import content_words, entry_parts
from tests.support.dataset_scenes import composer_user
from tests.unit.dataset.test_dataset_scene_quality import Harness

GROUPS = camera.camera_groups(load_catalog(user_root=False))
GROUP = {entry: group["name"] for group in GROUPS for entry in group["entries"]}


def brief(action="", camera_words="", aspect="Auto", level="free", known=False, subject="", request="", framing=(),
          characters=None):
    words = {part: text for part, text in (("action", action), ("camera", camera_words), ("subject", subject)) if text}
    return {"input": {"request": request or " ".join(filter(None, (subject, action, camera_words)))}, "must": [],
            "avoid": [], "kept_words": words, "consistency": {"camera": level}, "settings": {"aspect": aspect},
            "characters": [{"label": "woman", "known": known}] if characters is None else characters,
            "framing": dict(zip(("tightest", "widest", "facing"), (*framing, "", "", "")[:3]))}


def deal(request, total=6, seed=1, poses=None):
    return camera.deal_cameras(request, GROUPS, total, random.Random(seed), poses)


def part(entry, facet):
    return dict(entry_parts(entry))[facet]


class BuiltInCameras(unittest.TestCase):
    def test_every_camera_is_a_whole_shot_angle_and_view(self):
        self.assertTrue(GROUPS)
        for entry in GROUP:
            self.assertEqual([facet for facet, _ in entry_parts(entry)], ["shot", "angl", "view"], entry)
            self.assertIn(camera.shot_frame(entry), SHOWS, entry)
        self.assertTrue(all(group["shapes"] is None or set(group["shapes"]) < {"tall", "square", "wide"}
                            for group in GROUPS))
        self.assertTrue(all(len(group["entries"]) >= 10 and sum(camera.shot_frame(entry) == "full body"
                                                                for entry in group["entries"]) >= 4
                            for group in GROUPS), "ten images rarely repeat a camera, also when the feet must show")
        # Only the shot names a body part: a live writer read a "chest-level angle" as a frame cut at the chest.
        shot_words = {word for entry in GROUP for word in content_words(part(entry, "shot"))}
        others = {word for entry in GROUP for facet in ("angl", "view") for word in content_words(part(entry, facet))}
        self.assertFalse(others & (shot_words | {"waist", "chest", "knee", "hip", "feet", "foot", "leg", "neck"}))
        # A group word is never a camera word: "side by side" once made "side view" in a request fix nothing.
        said = {word for entry in GROUP for word in content_words(entry)}
        self.assertFalse(said & {word for group in GROUPS for text in group["words"] for word in content_words(text)})

    def test_a_set_spreads_over_cameras_and_shot_sizes(self):
        dealt = deal(brief(action="cooking"), total=4)
        self.assertEqual(len(set(dealt.values())), 4)
        self.assertGreaterEqual(len({camera.shot_frame(entry) for entry in dealt.values()}), 3)
        self.assertEqual({GROUP[entry] for entry in dealt.values()}, {"any pose"}, "no position named: any pose")
        ten = deal(brief(action="relaxing", subject="two friends", aspect="9:16"), total=10)
        self.assertEqual({GROUP[entry] for entry in ten.values()}, {"any pose"},
                         "two friends are two people, not a group lined up or gathered in depth")
        self.assertEqual(len(set(ten.values())), 10, "a live set of ten cycled three cameras")
        feet = deal(brief(action="dancing", camera_words="feet visible", level="themed"), total=10)
        self.assertGreaterEqual(len(set(feet.values())), 5)


class FitsTheImage(unittest.TestCase):
    def test_the_pose_chooses_the_cameras_that_show_it(self):
        lying = deal(brief(action="lying on a beach", aspect="16:9"), total=8)
        self.assertTrue({GROUP[entry] for entry in lying.values()} <= {"lying along the frame",
                                                                      "lying seen from above"})
        per_image = deal(brief(), total=2, poses={1: "sitting on a bench", 2: "two people hugging"})
        self.assertEqual((GROUP[per_image[1]], GROUP[per_image[2]]), ("sitting", "facing each other"))

    def test_a_tall_image_never_shows_a_lying_body_from_the_side_at_full_length(self):
        tall = deal(brief(action="lying on a beach", aspect="9:16"), total=8)
        self.assertEqual({GROUP[entry] for entry in tall.values()}, {"lying seen from above"})
        wide = deal(brief(action="a group of friends", aspect="16:9"), total=8)
        self.assertIn("lined up across the frame", {GROUP[entry] for entry in wide.values()})
        self.assertNotIn("lined up across the frame", {GROUP[entry] for entry in deal(brief(action="a group of friends",
                                                                             aspect="2:3"), total=8).values()})

    def test_every_shot_shows_what_the_request_asks_to_show(self):
        feet = deal(brief(action="cooking", camera_words="feet visible", level="themed"))
        self.assertEqual({camera.shot_frame(entry) for entry in feet.values()}, {"full body"})
        known = deal(brief(action="cooking", known=True), total=8)
        self.assertTrue({camera.shot_frame(entry) for entry in known.values()} <= set(AT_LEAST_HIPS))
        self.assertEqual(camera.camera_frames(known), {number: camera.shot_frame(entry) for number, entry in known.items()},
                         "a known character's frame is the dealt shot's")


class KeepsWhatTheRequestNeeds(unittest.TestCase):
    def framings(self, dealt):
        return {camera.shot_size(entry)[0] for entry in dealt.values()}

    def test_every_shot_stays_inside_the_framing_range_the_request_needs(self):
        # A live set dealt a close-up to two people whose act it then left below the frame, a head-to-knees shot to two
        # people standing either side of a long table, and an extreme wide shot to an act between two people.
        self.assertEqual(self.framings(deal(brief(action="talking", framing=("surroundings",)), total=8)),
                         {"surroundings"})
        self.assertNotIn("close", self.framings(deal(brief(action="hugging", framing=("partial",)), total=10)))
        self.assertIn("close", self.framings(deal(brief(action="kissing", framing=("close",)), total=10)),
                      "a close-up stays when faces carry the request, whoever is in it")
        act = deal(brief(action="dancing", framing=("partial", "whole")), total=10)
        self.assertEqual(self.framings(act), {"whole", "partial"}, "never so far that the act gets small")
        feet = deal(brief(action="dancing", camera_words="feet visible", level="themed", framing=("partial", "whole")))
        self.assertEqual({dict(entry_parts(entry))["shot"] for entry in feet.values()}, {"full shot"},
                         "the feet need a whole body, and nothing farther than the range")

    def test_what_must_stay_in_view_narrows_the_range(self):
        # A live request for visible footwear got no camera at all: footwear was no body part, so its words fixed nothing.
        shoes = deal(brief(action="lacing her boots", camera_words="her boots clearly visible", level="themed",
                           framing=("partial", "whole")))
        self.assertEqual({dict(entry_parts(entry))["shot"] for entry in shoes.values()}, {"full shot"},
                         "what is worn on the feet shows only with them")
        anchored = {**brief(action="reading", framing=("partial", "partial")),
                    "places": {"relations": [{"subject": "a cat", "relation": "under", "anchor": "a table",
                                              "within": False}]}}
        self.assertEqual(self.framings(deal(anchored, total=8)), {"whole"},
                         "an anchor the subjects are outside of stands whole in the image")
        things = {**brief(action="sewing", framing=("close",)), "kept_words": {"action": "sewing", "objects": "a quilt"}}
        self.assertNotIn("head and shoulders", {camera.shot_frame(entry) for entry in deal(things, total=10).values()},
                         "the things the request uses stay in view")

    def test_one_camera_suits_every_act_of_an_image(self):
        lying, sitting = "A lying on a blanket", "A sitting on a bench"
        alone = {group["name"] for group in camera.suiting(GROUPS, lying)}
        both = {group["name"] for group in camera.suiting(GROUPS, [lying, sitting])}
        self.assertTrue(alone and alone != both, "one act: its own groups")
        self.assertTrue(all(len(group["words"]) <= 1 for group in GROUPS if group["name"] in both),
                        "acts with no group in common: the cameras for any pose")
        self.assertEqual({group["name"] for group in camera.suiting(GROUPS, [lying, lying])}, alone)

    def test_the_view_sees_the_subjects_from_the_side_they_face(self):
        # A live team photo was seen from the side, along the row of people posing for it.
        photo = deal(brief(action="standing in a row", subject="a team", aspect="3:2", framing=("whole", "", "viewer")),
                     total=10)
        self.assertTrue(photo and not {part(entry, "view") for entry in photo.values()} & {"side view", "end-on view"})
        pair = deal(brief(action="talking", framing=("partial", "whole", "each other")), total=10)
        self.assertNotIn("front view", {part(entry, "view") for entry in pair.values()})
        self.assertGreater(len({part(entry, "view") for entry in deal(brief(action="talking"), total=10).values()}), 1)

    def test_a_range_no_camera_fits_opens_its_far_side_first(self):
        lying_tall = deal(brief(action="lying", aspect="9:16", framing=("whole", "whole", "one way")), total=4)
        self.assertTrue(lying_tall, "no camera is lost to the range")

    def test_any_subject_gets_cameras_named_for_it(self):
        # A live set of ten objects was dealt a head-and-shoulders shot.
        objects = deal(brief(subject="ten different objects", framing=("whole",), characters=[]), total=6)
        self.assertEqual(len(objects), 6)
        self.assertTrue(all(camera.shot_size(entry)[0] in ("surroundings", "whole") for entry in objects.values()))
        words = {word for entry in GROUP for word in content_words(part(entry, "shot"))}
        self.assertFalse(words & {"head", "knee", "hip", "shoulder", "body", "feet", "foot"}, words)

    def test_the_requests_own_camera_words_come_before_the_framing(self):
        close = deal(brief(action="smiling", camera_words="close-up", level="themed", framing=("whole", "surroundings")))
        self.assertEqual(self.framings(close), {"close"})
        side = deal(brief(action="posing", camera_words="side view", level="themed", framing=("whole", "", "viewer")))
        self.assertEqual({part(entry, "view") for entry in side.values()}, {"side view"})


class RequestedCamera(unittest.TestCase):
    def test_what_the_request_asks_of_a_part_holds_and_the_rest_varies(self):
        low = deal(brief(action="cooking", camera_words="low angle", level="themed"))
        self.assertTrue(all("low" in part(entry, "angl") for entry in low.values()), low)
        self.assertGreater(len({part(entry, "shot") for entry in low.values()}), 1, "the shot still varies")
        side = deal(brief(action="lying on a bed", camera_words="side view", level="themed", aspect="16:9"))
        self.assertEqual({part(entry, "view") for entry in side.values()}, {"side view"})

    def test_a_part_no_whole_camera_holds_is_put_into_the_dealt_ones(self):
        dealt = deal(brief(action="standing", camera_words="top-down view", level="themed"))
        self.assertEqual({part(entry, "view") for entry in dealt.values()}, {"top-down view"})

    def test_a_locked_camera_is_one_camera_and_the_requests_own_camera_is_never_replaced(self):
        locked = deal(brief(action="cooking", camera_words="a low angle", level="locked"))
        self.assertEqual(len(set(locked.values())), 1)
        self.assertEqual(deal(brief(action="cooking", camera_words="from behind", level="themed")), {},
                         "words no part holds: the request decides the camera")


class DealtCameras(Harness):
    def setUp(self):
        super().setUp()
        self.brief["input"]["amount"] = 2

    def write(self, vocabulary=None):
        from goated_prompter.features.dataset.v2 import scenes
        return scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None,
                                   vocabulary=vocabulary)

    def test_every_image_names_its_camera(self):
        self.write()
        first = self.composer()[0]
        images = composer_user(first.user_message)["images"]
        self.assertTrue(all(image["camera"] in GROUP for image in images), images)
        self.assertIn("CAMERAS\nEvery image in IMAGES names its camera", first.system_message)
        self.assertIn("The shot alone decides how much of each subject shows", " ".join(first.system_message.split()))
        self.assertIn("each person in the image keeps their head and upper body in view, so everyone stays recognizable",
                      " ".join(first.system_message.split()), "a live medium shot cut one participant to their torso")
        self.assertEqual(len(self.composer()), 1, "no check asks a scene again for its camera")

    def test_the_users_own_camera_packs_stay_suggestions(self):
        mine = [pack["id"] for pack in load_catalog(user_root=False)["packs"]
                if pack["category"] == camera.CAMERA and not pack.get("always")][:1]
        self.assertTrue(mine)
        self.write({"packs": mine})
        first = self.composer()[0]
        self.assertFalse([image for image in composer_user(first.user_message)["images"] if "camera" in image])
        self.assertNotIn("CAMERAS\n", first.system_message)


if __name__ == "__main__":
    unittest.main()
