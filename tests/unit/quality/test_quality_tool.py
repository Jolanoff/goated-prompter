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

    def test_anima_count_tags_and_bad_tags(self):
        cast = [{"label": "knight", "gender": "male"}, {"label": "queen", "gender": "female"}]
        good = "score_9, score_8_up, 1boy, 1girl, knight, throne room\n\nA knight kneels."
        bad = "low_quality, 2girls, 1boy, knight_is_pet\n\nA knight kneels."
        row = dataset_row([scene("fair", "a hall")], [good, bad], characters=cast)
        row["case"]["target"] = "Anima"
        values = checks.case_checks(row)
        self.assertEqual((values["count_tags_ok"], values["bad_tags"]), (0.5, 0.5))

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

    def test_a_difference_within_the_seed_noise_is_chance(self):
        old = {"totals": {"label_leaks": .3}, "noise": {"label_leaks": .1}}
        rows = {row["check"]: row for row in checks.compare(old, {"totals": {"label_leaks": .45}, "noise": {}})}
        self.assertEqual((rows["label_leaks"]["change"], rows["label_leaks"]["noise"]), ("same", .2))
        notes = report.verdict(self.audit_ok, list(rows.values()), None)[3]
        self.assertTrue(any("label_leaks may have got worse" in note for note in notes), notes)
        rows = {row["check"]: row for row in checks.compare(old, {"totals": {"label_leaks": .6}, "noise": {}})}
        self.assertEqual(rows["label_leaks"]["change"], "worse")

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
