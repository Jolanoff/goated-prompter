"""The quality check's own logic: audit, checks, blind review and verdict, with synthetic data (no model)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import enter_context
from tests.quality import audit, checks, judge, report, worker

ROOT = Path(__file__).resolve().parents[3]


class Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "audit.json"
            subprocess.run([sys.executable, str(ROOT / "tests/quality/worker.py"), "audit", "--code-root", str(ROOT),
                            "--main-root", str(ROOT), "--out", str(out)], check=True, cwd=ROOT, capture_output=True)
            cls.dump = json.loads(out.read_text(encoding="utf-8"))

    def test_the_current_code_has_no_unaccepted_collision_and_every_setting_builds(self):
        self.assertEqual(audit.collisions(self.dump), [])
        self.assertEqual(audit.duplicates(self.dump), [])
        self.assertEqual(audit.summary(self.dump)["errors"], {})
        for owner in ("creativity", "length", "director", "target", "style", "dataset_scenes", "nsfw"):
            self.assertIn(owner, self.dump["owners"])
        self.assertIn("director Explicit Adult", self.dump["assembled"])

    def test_a_guide_speaking_for_another_setting_is_flagged_unless_accepted(self):
        dump = {"owners": {"director": {"X": "Direct the bodies. Keep it concise and never invent props."},
                           "length": {"Short": "Keep it concise."}}, "assembled": {}}
        found = {(item["decision"], item["word"]) for item in audit.collisions(dump)}
        self.assertEqual(found, {("length", "concise"), ("invention", "invent")})
        owners, _ = audit.load_rules()
        allowed = [{"owner": "director", "decision": "invention", "phrase": "never invent props", "reason": "test"}]
        self.assertEqual([item["decision"] for item in audit.collisions(dump, (owners, allowed))], ["length"])

    def test_the_same_rule_in_two_guides_is_a_duplicate(self):
        rule = "Describe each person one after another with their own place in the frame always."
        dump = {"owners": {"target": {"A": rule}, "director": {"B": rule}}, "assembled": {}}
        self.assertEqual(len(audit.duplicates(dump)), 1)

    def test_changes_list_added_and_removed_sentences(self):
        old = {"owners": {"length": {"Short": "One. Two."}}, "assembled": {"default": "x"}}
        new = {"owners": {"length": {"Short": "One. Three."}}, "assembled": {"default": "y"}}
        rows, assembled = audit.changes(old, new)
        self.assertEqual(rows, [{"where": "length / Short", "added": ["Three."], "removed": ["Two."]}])
        self.assertEqual(assembled, ["default"])
        new_found, fixed, _ = audit.compare_findings([{"owner": "a", "sentence": "s"}], [])
        self.assertEqual((new_found, len(fixed)), ([], 1))


def dataset_row(scenes, prompts, *, characters=None, avoid=(), ok=True):
    characters = characters or [{"label": "man 1"}, {"label": "man 2"}]
    return {"id": "d", "kind": "dataset", "seed": 1, "ok": ok, "case": {"target": "Generic", "amount": len(scenes)},
            "output": {"brief": {"characters": characters, "avoid": list(avoid), "input": {"amount": len(scenes)}},
                       "scenes": scenes, "prompts": [{"slot": n, "prompt": p} for n, p in enumerate(prompts, 1)]}}


def scene(look, space, extras="a lamp"):
    return {"subjects": {"man 1": {"skin": look, "hair": "dark"}, "man 2": {"skin": "tan", "hair": "blond"}},
            "space": space, "extras": extras, "actions": "they talk"}


class Checks(unittest.TestCase):
    def test_repeats_labels_and_ruled_out_words_are_counted(self):
        row = dataset_row([scene("fair", "a quiet kitchen"), scene("fair", "a quiet kitchen"), scene("olive", "a pier")],
                          ["The first man smiles beside a red car.", "Two men talk.", "man 2 laughs."], avoid=["no car"])
        values = checks.case_checks(row)
        self.assertEqual(values["label_leaks"], round(2 / 3, 3))
        self.assertEqual(values["avoid_hits"], 1)
        self.assertEqual(values["repeated_looks"], round(1 / 3, 3))
        self.assertEqual(values["repeated_places"], round(1 / 3, 3))
        self.assertEqual(values["written"], 1.0)
        self.assertEqual(values["cast_ok"], 1.0)
        self.assertEqual(values["actions_named"], 0.0, "\"they talk\" names nobody")

    def test_every_requested_image_counts_once_and_wrong_slots_are_counted(self):
        # written once counted the prompts that came back, so an extra one hid a missing one.
        row = dataset_row([{**scene("fair", "a hall"), "slot": n} for n in (1, 1, 4)], ["One.", "Two.", "Three."])
        row["case"]["amount"] = 3
        row["output"]["prompts"] = [{"slot": 1, "prompt": "One."}, {"slot": 1, "prompt": "Again."},
                                    {"slot": 4, "prompt": "Extra."}]
        values = checks.case_checks(row)
        self.assertEqual(values["written"], round(1 / 3, 3), "slots 2 and 3 have no prompt")
        self.assertEqual(values["slot_problems"], 6, "two doubles, two unrequested slots, two images without a scene")
        row["case"].pop("amount")
        row["output"]["brief"]["input"].pop("amount")
        self.assertIsNone(checks.case_checks(row)["written"], "never derived from what came back")

    def test_the_format_check_wants_the_final_form(self):
        normalize = lambda prompt, target, mode=None: prompt.strip().removeprefix("Prompt: ")
        self.assertTrue(checks._format_ok("A knight kneels.", "Generic", normalize))
        self.assertFalse(checks._format_ok("Prompt: A knight kneels.", "Generic", normalize), "it had to unwrap it")
        self.assertTrue(checks._format_ok('{"a": 1}', "Generic", lambda prompt, target, mode=None: '{"a":1}'))

    def test_ruled_out_words_count_only_when_described(self):
        prompts = ["A man in a hat, no cars on the street.", "A red car waits.", "A carpet."]
        self.assertEqual(checks._avoid_hits(prompts, ["car"]), 1, "negated and longer words are not hits")

    def test_known_characters_keep_their_looks_and_safe_sets_stay_safe(self):
        cast = [{"label": "knight", "known": True}, {"label": "squire"}]
        mine = {"subjects": {"knight": {"expression": "calm"}, "squire": {"skin": "fair", "hair": "red"}},
                "space": "a hall", "actions": "the knight talks to the squire"}
        given = {**mine, "subjects": {**mine["subjects"], "knight": {"expression": "calm", "hair": "long white hair"}}}
        row = dataset_row([mine, given], ["A knight talks.", "A knight talks."], characters=cast)
        values = checks.case_checks(row)
        self.assertEqual(values["known_changed"], 0.5)
        self.assertEqual(values["repeated_looks"], 1.0, "the squire repeats; the knight is left out")
        row["output"]["brief"]["input"]["nsfw"] = False
        row["output"]["prompts"][1]["prompt"] = "A nude knight talks."
        self.assertEqual(checks.case_checks(row)["sfw_leaks"], 0.5)

    def test_a_kept_part_repeats_on_purpose(self):
        # The request kept one place and one action, so the same place and act in every image are asked for.
        first = {**scene("fair", "a library, a long oak table, shelves behind"), "entry": "A reads",
                 "position": {"man 1": "sitting at the table", "man 2": "standing by the shelf"}}
        second = {**scene("olive", "a library, a reading lamp, a window behind"), "entry": "A reads",
                  "position": {"man 1": "standing at the window", "man 2": "sitting on the steps"}}
        row = dataset_row([first, second], ["One.", "Two."])
        self.assertEqual((checks.case_checks(row)["repeated_acts"]), 1.0, "the same entry")
        row["output"]["brief"]["kept"] = ["place", "action"]
        values = checks.case_checks(row)
        self.assertEqual((values["repeated_acts"], values["repeated_places"]), (0.0, 0.0),
                         "a different pose and spot of the kept place and act")
        row["output"]["scenes"][1] = {**first, "subjects": second["subjects"]}
        self.assertEqual(checks.case_checks(row)["repeated_acts"], 1.0, "the same pose again is still a repeat")

    def test_first_pass_counts_the_images_never_asked_again(self):
        row = dataset_row([scene("fair", "a hall"), scene("olive", "a pier")], ["One.", "Two."])
        row["log"] = ["Image 2 is asked again: it repeats image 1.", "Image 2 is asked again: still a repeat."]
        values = checks.case_checks(row)
        self.assertEqual((values["redone"], values["first_pass"]), (2, 0.5))

    def test_anima_count_tags_and_bad_tags(self):
        cast = [{"label": "knight", "gender": "male"}, {"label": "queen", "gender": "female"}]
        good = "score_9, score_8_up, 1boy, 1girl, knight, throne room\n\nA knight kneels."
        bad = "low_quality, 2girls, 1boy, knight_is_pet\n\nA knight kneels."
        row = dataset_row([scene("fair", "a hall")], [good, bad], characters=cast)
        row["case"]["target"] = "Anima"
        values = checks.case_checks(row)
        self.assertEqual((values["count_tags_ok"], values["bad_tags"]), (0.5, 0.5))
        # A couple of open genders that the scenes wrote as a woman and a man is counted as the scene gives them.
        couple = [{"label": "person 1"}, {"label": "person 2"}]
        lines = ["masterpiece, 1boy, 1girl, walking\n\nThey walk.", "masterpiece, 2others, walking\n\nThey walk.",
                 "masterpiece, 2boys, 1girl, walking\n\nThey walk."]
        row = dataset_row([scene("fair", "a street")], lines, characters=couple)
        row["case"]["target"] = "Anima"
        self.assertEqual(checks.case_checks(row)["count_tags_ok"], round(2 / 3, 3), "three people for two is wrong")

    def test_framing_hints_count_shot_names_and_shown_extents(self):
        named = "A medium shot of two people talking in a kitchen."
        shown = "Two people stand with their feet on the tiled floor, a table in the foreground and a window behind."
        values = checks.case_checks(dataset_row([scene("fair", "a hall")], [named, shown]))
        self.assertEqual((values["shot_named"], values["extent_shown"]), (0.5, 0.5))

    def test_images_asked_again_are_counted_from_the_log(self):
        row = {**dataset_row([scene("fair", "a hall")], ["A prompt."]),
               "log": ["  3.1s Composing scenes", " 40.2s Image 6 is asked again: it repeats image 1's place",
                       " 40.2s Image 9 is asked again: its actions do not name man 2"]}
        self.assertEqual(checks.case_checks(row)["redone"], 2)

    def test_a_mouth_on_a_rear_with_genitals_in_the_same_sentence_is_counted(self):
        mixed = "His mouth is around the man's anus, his large, semi-erect penis resting against the floor."
        apart = "His tongue presses against the man's anus. His penis hangs between his thighs."
        both_acts = "His penis is in the mouth of the man in front, while his anus is entered from behind."
        self.assertEqual([checks._mouth_mixed(text) for text in (mixed, apart, both_acts)], [True, False, False])

    def test_genitals_that_hang_free_while_the_act_uses_them_are_counted(self):
        used = {"actions": "man 2 has man 1's penis in his mouth", "position": {"man 1": "sitting, his genitals are hanging free",
                                                             "man 2": "kneeling, his mouth around man 1's penis"}}
        placed = {**used, "position": {**used["position"], "man 1": "sitting, his penis in man 2's mouth, aroused"}}
        self.assertEqual([checks._genitals_conflict(scene) for scene in (used, placed)], [True, False])

    def test_genitals_given_two_places_are_counted(self):
        actions = "man 2's penis in man 1's body, man 1 sitting on man 2's lap"
        twice = {"actions": actions, "position": {"man 1": "his genitals are pressed against man 2's, his penis is "
                                                            "tucked under him", "man 2": "sitting, hands on man 1's hips"}}
        tucked = {"actions": actions, "position": {"man 1": "sitting on man 2's lap, his penis resting on man 2's belly",
                                                   "man 2": "his penis is tucked under him"}}
        one = {"actions": actions, "position": {"man 1": "sitting on man 2's lap, his penis is hanging free",
                                                "man 2": "his genitals are pressed against man 1's back"}}
        self.assertEqual([checks._genitals_conflict(scene) for scene in (twice, tucked, one)], [True, True, False])

    def test_a_person_being_entered_meets_the_other_at_the_hips(self):
        # The check reads the act's anatomical words, so this one case needs them.
        labels = ["man 1", "man 2"]
        act = "man 2's penis in man 1's anus"
        chest = {"actions": act, "position": {"man 1": "lying on his back, his hips are pressed against man 2's chest",
                                              "man 2": "kneeling"}}
        hips = {"actions": act, "position": {"man 1": "lying down", "man 2": "kneeling, man 1's hips pressed against his hips"}}
        touch = {"actions": "man 2's hand on man 1's back", "position": {
            "man 1": "lying down, his hips against man 2's chest", "man 2": "kneeling"}}
        self.assertEqual([checks._contact_misplaced(scene, labels) for scene in (chest, hips, touch)],
                         [True, False, False])

    def test_anima_tags_for_an_act_the_scene_does_not_show_or_beside_their_opposite_are_counted(self):
        entered = {"actions": "man 2's penis in man 1's anus", "position": {}}
        touched = {"actions": "man 2's hand on man 1's back", "position": {}}
        self.assertEqual([checks._tags_misfit(prompt, scene) for prompt, scene in (
            ("masterpiece, 2boys, penetration, kneeling\n\nProse.", entered),
            ("masterpiece, 2boys, penetration, kneeling\n\nProse.", touched),
            ("masterpiece, 2boys, tired, untired\n\nProse.", entered),
            ("masterpiece, 2boys, kneeling\n\nProse.", touched))], [False, True, True, False])

    def test_template_text_left_in_a_scene_is_counted(self):
        labels = ["man 1", "man 2"]
        slot = {"actions": "man 1 holds man 2 in [Restraint Gear]", "space": "a room"}
        copied = {"actions": "two tops: one person bound, man 1's penis is in man 2's mouth"}
        fine = {"actions": "man 1 and man 2: they embrace; man 1 kisses man 2", "space": "a room"}
        named = {"actions": "hogtie: man 1 is hogtied face down while man 2 watches"}
        self.assertEqual([checks._template_leak(scene, labels) for scene in (slot, copied, fine, named)],
                         [True, True, False, False])

    def test_a_scene_that_contradicts_itself_about_an_opening_is_counted(self):
        labels = ["man 1", "man 2", "man 3"]
        swapped = {"actions": "man 1's penis is in man 3's mouth and man 2's penis is inside man 3's anus", "position": {
            "man 1": "sitting, his penis is inside man 3's anus", "man 2": "standing, his penis is in man 3's mouth",
            "man 3": "on man 1's lap"}}
        gagged = {"actions": "man 1's penis is in man 3's mouth", "position": {
            "man 1": "standing, his penis is in man 3's mouth", "man 2": "watching", "man 3": "kneeling, wearing a ball gag"}}
        ring = {**gagged, "position": {**gagged["position"], "man 3": "kneeling, a ring gag holds his mouth open"}}
        # Two people in one mouth is an act the request may ask for: never counted on its own.
        shared = {"actions": "man 1's penis and man 2's penis are both in man 3's mouth", "position": {
            "man 1": "standing, his penis in man 3's mouth", "man 2": "standing, his penis in man 3's mouth",
            "man 3": "kneeling between them"}}
        self.assertEqual([checks._opening_conflict(scene, labels) for scene in (swapped, gagged, ring, shared)],
                         [True, True, False, False])

    def test_people_the_act_joins_must_be_named_in_a_position(self):
        labels = ["man 1", "man 2"]
        joined = {"actions": "man 1's penis is in man 2's mouth", "position": {"man 1": "standing, his penis in man 2's mouth",
                                                                              "man 2": "kneeling"}}
        loose = {**joined, "position": {"man 1": "standing, facing the wall", "man 2": "kneeling, looking up"}}
        two_acts = {"actions": "man 1 grips man 2's hair, and man 2's hand holds the bed", "position": {
            "man 1": "standing, his hand in man 2's hair", "man 2": "kneeling"}}
        self.assertEqual([checks._pose_act_gap(scene, labels) for scene in (joined, loose, two_acts)], [False, True, False])
        three = ["man 1", "man 2", "man 3"]
        sharing = {"actions": "man 2 and man 3 are holding man 1's arms", "position": {
            "man 1": "kneeling", "man 2": "standing, holding man 1's left arm", "man 3": "standing, holding man 1's right arm"}}
        waiting = {"actions": "man 1's hand is on man 2's shoulder, man 3 and man 2 are waiting", "position": {
            "man 1": "standing", "man 2": "kneeling at man 1's hips", "man 3": "sitting nearby"}}
        apart = {**sharing, "position": {**sharing["position"], "man 3": "standing at the door"}}
        both = {"actions": "man 1's hands are holding man 2's and man 3's wrists", "position": {
            "man 1": "kneeling between man 2 and man 3", "man 2": "standing", "man 3": "standing"}}
        during = {"actions": "man 2's hand is on man 1's cheek as man 1 sits on man 3's lap", "position": {
            "man 1": "sitting on man 3's lap", "man 2": "standing in front of man 1, hand on man 1's cheek", "man 3": "sitting on a chair"}}
        self.assertEqual([checks._pose_act_gap(scene, three) for scene in (sharing, waiting, apart, both, during)],
                         [False, False, True, False, False],
                         "people who share a role are not joined; each must still reach whoever they act on")

    def test_a_lower_body_part_the_visible_parts_leave_out_is_counted(self):
        labels = ["man 1", "man 2"]
        base = {"actions": "man 1's penis is inside man 2's anus"}
        hidden = {**base, "position": {"man 1": "standing; his torso and arms are visible", "man 2": "bent over; his back and buttocks are visible"}}
        shown = {**base, "position": {"man 1": "standing; his torso and hips are visible", "man 2": "bent over; his back and buttocks are visible"}}
        unlisted = {**base, "position": {"man 1": "standing behind", "man 2": "bent over"}}
        self.assertEqual([checks._out_of_frame(scene, labels) for scene in (hidden, shown, unlisted)], [True, False, False])
        # The camera is read too: its clauses about a person, the whole body or the knees, and a lower-body focus.
        framed = {**unlisted, "camera": "side view, man 1's head and torso are in frame, man 2's hips are in frame"}
        knees = {**unlisted, "camera": "side view, man 1's knees reach the bottom edge, man 2's hips are in frame"}
        focus = {**framed, "camera": framed["camera"] + ", the contact at man 2's buttocks is the focus"}
        self.assertEqual([checks._out_of_frame(scene, labels) for scene in (framed, knees, focus)], [True, False, False])

    def test_the_shape_hint_needs_a_ratio_and_reads_the_arrangement(self):
        labels = ["man 1", "man 2", "man 3"]
        row = {"position": {"man 1": "left, standing", "man 2": "centre, standing", "man 3": "right, standing"}}
        stacked = {"position": {"man 1": "left, standing", "man 2": "centre, above man 1", "man 3": "right, standing"}}
        self.assertEqual([checks._shape_misfit(row, labels, ratio) for ratio in ("3:4", "16:9", "Auto")], [True, False, False])
        self.assertFalse(checks._shape_misfit(stacked, labels, "3:4"))
        # Standing people in a wide frame are often right, so the hint no longer counts them.
        standing = {"position": {"man 1": "standing, entire body visible", "man 2": "standing"}}
        self.assertEqual([checks._shape_misfit(standing, labels[:2], ratio) for ratio in ("16:9", "3:4")], [False, False])

    def test_body_parts_the_request_names_but_no_scene_shows_are_counted(self):
        scenes = [{"actions": "man 1's penis is in man 2's mouth", "position": {"man 1": "standing", "man 2": "kneeling"}}]
        self.assertEqual(checks._parts_missing("oral sex on the penis and on the anus", scenes), 0.5)
        self.assertIsNone(checks._parts_missing("two men talk", scenes))
        # A part the request names belongs in every image: shown in one of two, it is missing from the other.
        hands = [{"actions": "man 1 holds man 2's hand", "position": {}}, {"actions": "man 1 waves", "position": {}}]
        self.assertEqual(checks._parts_missing("two men holding hands", hands), None, "hands are not a listed part")
        two = [scenes[0], {"actions": "man 1 kneels", "position": {"man 1": "kneeling"}}]
        self.assertEqual(checks._parts_missing("a scene about the penis", two), 0.5)

    def test_the_same_act_is_the_same_entry_or_the_same_words(self):
        same = "man 1's penis is inside man 2's anus while man 1 grips man 2's hair"
        by_words = [{**scene("fair", f"room {n}"), "actions": act} for n, act in
                    enumerate([same, same.replace("grips", "grips"), "man 2 kneels and sucks man 1's penis"])]
        self.assertEqual(checks.case_checks(dataset_row(by_words, ["a", "b", "c"]))["repeated_acts"], round(1 / 3, 3))
        # Two different entries with the same few words are different acts; the same entry twice is one.
        by_entry = [{**scene("fair", f"room {n}"), "actions": "man 1's penis is in man 2's mouth", "entry": entry}
                    for n, entry in enumerate(["kneeling: one person kneels", "chair tied: one person tied", "kneeling: one person kneels"])]
        self.assertEqual(checks.case_checks(dataset_row(by_entry, ["a", "b", "c"]))["repeated_acts"], round(1 / 3, 3))

    def test_the_new_checks_reach_the_case_and_the_shape_one_needs_a_ratio(self):
        row = dataset_row([{**scene("fair", "a room"), "actions": "man 1 holds man 2 in [Gear]"}], ["A prompt."])
        values = checks.case_checks(row)
        self.assertEqual((values["template_leaks"], values["shape_misfit"]), (1.0, None))
        row["case"]["aspect"] = "3:4"
        self.assertEqual(checks.case_checks(row)["shape_misfit"], 0.0)

    def test_a_failed_case_counts_as_nothing_written(self):
        self.assertEqual(checks.case_checks(dataset_row([], [], ok=False))["written"], 0.0)

    def test_old_and_new_totals_are_compared_by_direction(self):
        old = {"totals": {"written": 1.0, "label_leaks": 0, "repeated_looks": .8}}
        new = {"totals": {"written": 0.9, "label_leaks": 0, "repeated_looks": .1}}
        rows = {row["check"]: row["change"] for row in checks.compare(old, new)}
        self.assertEqual((rows["written"], rows["label_leaks"], rows["repeated_looks"]), ("worse", "same", "better"))


class BlindReview(unittest.TestCase):
    def pair_sides(self):
        side = lambda text: {"cases": [{"id": "b", "kind": "builder", "seed": 1, "ok": True, "case": {"idea": "a cat"},
                                         "output": {"prompt": text}}]}
        return side("old prompt"), side("new prompt")

    def test_the_reviewer_cannot_tell_which_side_is_new_and_the_key_unblinds_it(self):
        old, new = self.pair_sides()
        packet, key = judge.build_packet(old, new, seed=3)
        self.assertNotIn("candidate", json.dumps(packet))
        self.assertNotIn("baseline", json.dumps(packet))
        new_letter = "A" if key["b / seed 1"]["A"] == "candidate" else "B"
        self.assertIn("new prompt", packet["pairs"][0]["a" if new_letter == "A" else "b"])
        review = {"reviewer": "me", "review_kind": "human", "pairs": {"b / seed 1": {"fidelity": new_letter, "physics": "tie"}}}
        result = judge.unblind(review, key)
        self.assertTrue(result["counts"])
        self.assertEqual(result["dimensions"]["fidelity"], {"wins": 1, "losses": 0, "ties": 0})
        self.assertFalse(judge.unblind({**review, "review_kind": "self_review"}, key)["counts"])

    def test_a_dimension_needs_a_clear_majority(self):
        self.assertEqual(judge.leaning({"wins": 1, "losses": 0, "ties": 0}), "same")
        self.assertEqual(judge.leaning({"wins": 4, "losses": 1, "ties": 1}), "better")
        self.assertEqual(judge.leaning({"wins": 0, "losses": 3, "ties": 2}), "worse")


class Verdict(unittest.TestCase):
    audit_ok = {"new": [], "fixed": [], "remaining": [], "errors": {}}

    def test_a_guard_regression_or_new_collision_is_worse_whatever_else_improved(self):
        rows = [{"check": "written", "kind": "guard", "change": "worse", "baseline": 1, "candidate": .9},
                {"check": "repeated_looks", "kind": "aim", "change": "better", "baseline": .8, "candidate": .1}]
        self.assertEqual(report.verdict(self.audit_ok, rows, None)[0], "Worse")
        self.assertEqual(report.verdict({**self.audit_ok, "new": [{}]}, [], None)[0], "Worse")

    def test_improvements_without_regressions_are_better_and_tiny_moves_are_no_difference(self):
        rows = [{"check": "repeated_looks", "kind": "aim", "change": "better", "baseline": .8, "candidate": .1}]
        self.assertEqual(report.verdict(self.audit_ok, rows, None)[0], "Better")
        tiny = checks.compare({"totals": {"repeated_looks": .30}}, {"totals": {"repeated_looks": .28}})
        self.assertEqual(report.verdict(self.audit_ok, tiny, None)[0], "No real difference")

    def test_a_difference_within_the_seed_noise_is_chance_but_a_guard_change_never_is(self):
        old = {"totals": {"repeated_looks": .3, "label_leaks": .3}, "noise": {"repeated_looks": .1, "label_leaks": .1}}
        new = {"totals": {"repeated_looks": .45, "label_leaks": .45}, "noise": {}}
        rows = {row["check"]: row for row in checks.compare(old, new)}
        self.assertEqual((rows["repeated_looks"]["change"], rows["repeated_looks"]["noise"]), ("same", .2))
        notes = report.verdict(self.audit_ok, list(rows.values()), None)[3]
        self.assertTrue(any("repeated_looks may have got worse" in note for note in notes), notes)
        self.assertEqual(rows["label_leaks"]["change"], "worse", "a leftover label is a fact, not a sample")
        rows = {row["check"]: row for row in checks.compare(old, {**new, "totals": {"repeated_looks": .6}})}
        self.assertEqual(rows["repeated_looks"]["change"], "worse")

    def test_the_noise_comes_from_paired_runs_and_info_changes_show(self):
        # Both sides run the same cases and seeds: the spread of the per-run differences is the noise.
        old = {"cases": {"a / seed 1": {"repeated_looks": 0.0, "seconds": 100}, "b / seed 1": {"repeated_looks": 0.0,
                                                                                               "seconds": 100}},
               "totals": {"repeated_looks": 0.0, "seconds": 100}, "noise": {}}
        new = {"cases": {"a / seed 1": {"repeated_looks": 0.5, "seconds": 50}, "b / seed 1": {"repeated_looks": 0.0,
                                                                                             "seconds": 50}},
               "totals": {"repeated_looks": 0.25, "seconds": 50}, "noise": {}}
        rows = {row["check"]: row for row in checks.compare(old, new)}
        self.assertEqual((rows["repeated_looks"]["noise"], rows["repeated_looks"]["change"]), (0.5, "same"),
                         "one run of two moved: within the paired noise")
        self.assertEqual(rows["seconds"]["change"], "better", "half the time is a real change, shown")
        notes = report.verdict(self.audit_ok, list(rows.values()), None)
        self.assertEqual(notes[0], "No real difference", "info never decides the verdict")
        self.assertTrue(any("seconds (info) went down (100 -> 50)" in note for note in notes[3]), notes[3])

    def test_a_case_and_seed_run_twice_keep_both_runs(self):
        rows = [dataset_row([scene("fair", "a kitchen")], ["Two men talk."]) | {"seed": 1} for _ in range(2)]
        self.assertEqual(list(checks.side_checks({"cases": rows})["cases"]), ["d / seed 1", "d / seed 1 (run 2)"])

    def test_seed_noise_and_per_request_averages(self):
        row = lambda seed, looks: dataset_row([scene(looks, "a kitchen"), scene("fair", f"a pier {seed}")],
                                              ["Two men talk.", "Two men walk."]) | {"seed": seed}
        side = checks.side_checks({"cases": [row(1, "fair"), row(2, "olive")]})
        self.assertEqual(side["noise"]["repeated_looks"], 0.5, "seeds disagree: 0 and 1, standard error 0.5")
        self.assertEqual(checks.per_request(side, side)["d"]["candidate"]["repeated_looks"], 0.5)

    def test_identical_instructions_are_reported(self):
        notes = report.verdict({**self.audit_ok, "changes": [], "assembled": []}, [], None)[3]
        self.assertTrue(any("same instructions" in note for note in notes))

    def test_reviewers_preferring_the_old_output_on_fidelity_make_it_worse(self):
        review = {"counts": True, "reviewer": "me", "kind": "human",
                  "dimensions": {"fidelity": {"wins": 0, "losses": 3, "ties": 0}, "creativity": {"wins": 3, "losses": 0, "ties": 0}}}
        self.assertEqual(report.verdict(self.audit_ok, [], review)[0], "Worse")
        page, markdown = report.render({"label": "x", "verdict": report.verdict(self.audit_ok, [], review),
                                        "audit": {**self.audit_ok, "duplicates": [], "changes": [], "assembled": []},
                                        "checks": [], "review": review, "packet": None})
        self.assertIn("Quality report", page)
        self.assertIn("Worse", markdown)


class ModelChoice(unittest.TestCase):
    def test_the_model_is_chosen_like_the_app_chooses_it(self):
        from types import SimpleNamespace
        ready = lambda name, ok=True: SimpleNamespace(profile_id=name.casefold(), label=name, vision_ready=ok)
        found = SimpleNamespace(profiles=(ready("Broken", False), ready("Qwen 9B"), ready("Qwen 27B")))
        with tempfile.TemporaryDirectory() as folder, \
                patch("goated_prompter.director_profiles.discover_director_profiles", return_value=found):
            Path(folder, "config.json").write_text('{"backend": "local_llama_cpp"}', encoding="utf-8")
            Path(folder, "settings.json").write_text('{"selected_profile": "qwen 27b"}', encoding="utf-8")
            base = {"model_config": "config.json", "app_settings": "settings.json"}
            pick = lambda **extra: worker._engine({**base, **extra}, Path(folder))[1]
            self.assertEqual(pick(), "qwen 27b", "the app's selection")
            self.assertEqual(pick(model_profile="Qwen 9B"), "qwen 9b", "quality.json wins")
            self.assertEqual(pick(app_settings=""), "qwen 9b", "else the first ready model")


class LivePipeline(unittest.TestCase):
    """The worker drives the app's real Dataset pipeline (scripted model answers, so this checks wiring only)."""

    def generate(self, instruction):
        stage = instruction.diagnostic_stage
        if stage == "dataset_v2:understanding":
            return json.dumps({"path": "character", "summary": "Two dancers rehearse.", "fixed": "", "randomized": "place",
                               "must": [], "avoid": [], "characters": [
                                   {"label": "dancer", "gender": "", "custom": "", "pronoun": "", "count": 2}]})
        if stage == "dataset_v2:scenes":
            images = json.loads(instruction.user_message.rsplit("IMAGES:\n", 1)[1])["images"]
            person = {"skin": "fair", "build": "slim", "hair": "dark", "detail": "a scar", "expression": "calm"}
            return json.dumps({"scenes": [{"subjects": {"dancer 1": person, "dancer 2": person},
                                           "position": {"dancer 1": "left", "dancer 2": "right"},
                                           "actions": "dancer 1 lifts dancer 2", "space": f"studio {row['image']}",
                                           "camera": "wide", "extras": "a mirror",
                                           "frame": {label: {"shows": "full body", "face": "visible"}
                                                     for label in ("dancer 1", "dancer 2")}} for row in images]})
        return "Two dancers rehearse a lift in a bright studio."

    def test_a_dataset_case_returns_the_brief_scenes_and_prompts(self):
        from goated_prompter.backends.mock import MockBackend
        from goated_prompter.features.dataset.v2 import scenes, understanding
        backend = MockBackend()
        enter_context(self, patch.object(backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            enter_context(self, patch.object(module, "create_backend", return_value=backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=backend))
        case = {"id": "d", "kind": "dataset", "subject": "two dancers rehearse a lift", "amount": 2}
        output = worker._dataset_case(case, 5, {"backend": "mock"}, "", lambda _message: None)
        self.assertEqual(len(output["scenes"]), 2)
        self.assertEqual([item["prompt"] for item in output["prompts"]], ["Two dancers rehearse a lift in a bright studio."] * 2)
        values = checks.case_checks({"id": "d", "kind": "dataset", "seed": 5, "ok": True, "case": case, "output": output})
        self.assertEqual(values["repeated_looks"], 1.0, "both images have the same two people")


if __name__ == "__main__":
    unittest.main()
