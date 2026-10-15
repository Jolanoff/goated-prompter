"""CPU-only checks of the real-model evaluation scorer, not model quality."""

from copy import deepcopy
import json
import unittest

from tests.gpu import dataset_understanding_eval as evaluation


def part(ident, kind, text, **fields):
    return {"id": ident, "kind": kind, "text": text, "status": "fixed", "source": "request",
            "character": "", "cast": [], "of": "", "by": [], "to": [], "input": 0, "terms": [], **fields}


class UnderstandingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {"request": "Two men dance", "expect": {"path": "character", "people": [2, 2]}}
        self.brief = {"path": "sfw_character", "characters": [{"label": "man 1"}, {"label": "man 2"}],
                      "intent": {"available": True, "elements": [
                          part("s1", "subject", "man", cast=["man 1"]),
                          part("s2", "subject", "man", cast=["man 2"]),
                          part("a", "action", "dance", by=["s1", "s2"], terms=["rhythm", "movement"])],
                          "relations": [], "unresolved": []}}

    def check(self, name, brief=None):
        return next(row for row in evaluation.score(self.case, brief or self.brief) if row["check"] == name)

    def test_each_person_has_exactly_one_subject_binding_including_valid_groups(self):
        self.assertTrue(self.check("each person bound once")["ok"])
        subjects = self.brief["intent"]["elements"][:2]
        subjects[0]["cast"] = ["man 1", "man 2"]
        self.assertFalse(self.check("each person bound once")["ok"], "overlapping identity must fail")
        self.brief["intent"]["elements"].remove(subjects[1])
        self.brief["intent"]["elements"][-1]["by"] = ["s1"]
        self.assertTrue(self.check("each person bound once")["ok"], "one group is valid")
        subjects[0]["cast"] = ["man 1"]
        self.assertFalse(self.check("each person bound once")["ok"], "a missing person must fail")
        subjects[0]["cast"] = ["man 1", "man 2", "stranger"]
        self.assertFalse(self.check("each person bound once")["ok"], "an invented binding must fail")

    def test_action_bindings_require_subjects_and_count_mutual_participants(self):
        self.case["expect"]["elements"] = [{"kind": "action", "text": ["dance"], "by_people": 2}]
        self.assertTrue(self.check("dance: by people 2")["ok"])
        action = self.brief["intent"]["elements"][-1]
        action["by"] = ["s1"]
        self.assertFalse(self.check("dance: by people 2")["ok"])
        for by in ([], ["missing"], ["a"]):
            with self.subTest(by=by):
                action["by"] = by
                self.assertFalse(self.check("a: action has bound actors")["ok"])

    def test_different_roles_and_pronoun_target_cannot_share_the_same_actor(self):
        self.case["expect"].update(elements=[{"kind": "action", "text": ["photographs"], "to_actor_of": ["dance"]}],
                                   different_actors=[["dance"], ["photographs"]])
        photo = part("p", "action", "photographs", by=["s2"], to=["s1"], terms=["camera"])
        self.brief["intent"]["elements"][-1]["by"] = ["s1"]
        self.brief["intent"]["elements"].append(photo)
        self.assertTrue(self.check("distinct action roles")["ok"])
        self.assertTrue(self.check("photographs: targets actor of dance")["ok"])
        photo["by"] = ["s1"]
        self.assertFalse(self.check("distinct action roles")["ok"])
        photo["to"] = ["s2"]
        self.assertFalse(self.check("photographs: targets actor of dance")["ok"])

    def test_term_coverage_threshold_counts_non_subject_parts_including_missing_terms(self):
        self.brief["intent"]["elements"] += [part(f"o{i}", "object", f"object {i}", terms=["material"]) for i in range(9)]
        parts = self.brief["intent"]["elements"]
        parts[-1]["terms"] = []
        self.assertTrue(self.check("related ideas coverage >= 90%")["ok"], "9 of 10 passes")
        self.assertTrue(all(row["ok"] for row in evaluation.score(self.case, self.brief) if row["group"] == "terms"))
        parts[-2]["terms"] = []
        self.assertFalse(self.check("related ideas coverage >= 90%")["ok"], "8 of 10 fails")
        self.assertEqual(len(evaluation.review_rows(self.case, self.brief)), 10, "missing terms still need review")

    def test_echo_terms_fail_even_with_case_inflection_or_extra_function_words(self):
        action = self.brief["intent"]["elements"][-1]
        action["text"] = "kisses a neck"
        for terms in (["KISSES A NECK"], ["kiss"], ["the neck"], ["neck-kiss"], ["rhythm", "kiss"]):
            with self.subTest(terms=terms):
                action["terms"] = terms
                self.assertFalse(self.check("a: related ideas add words")["ok"])
        action["terms"] = ["affection", "intimacy"]
        self.assertTrue(self.check("a: related ideas add words")["ok"])
        row = evaluation.review_rows(self.case, self.brief)[0]
        self.assertIsNone(row["term_quality_1_to_5"], "novelty is not semantic relevance")

    def test_empty_non_character_intent_has_no_artificial_identity_or_term_failures(self):
        self.case["expect"].update(path="non_character", people=[0, 0])
        brief = {**deepcopy(self.brief), "path": "non_character", "characters": []}
        brief["intent"]["elements"] = []
        self.assertTrue(all(row["ok"] for row in evaluation.score(self.case, brief)))

    def test_summary_fails_when_any_quality_check_or_run_fails(self):
        def row(brief, checks):
            value = {"case": "synthetic", "seed": 1, "brief": brief, "calls": [], "checks": checks}
            value["summary"] = evaluation.run_summary(value)
            return value

        passing = row(self.brief, evaluation.score(self.case, self.brief))
        self.assertTrue(evaluation.totals([passing])["passed"])
        bad = deepcopy(passing)
        bad["checks"][0]["ok"] = False
        self.assertFalse(evaluation.totals([bad])["passed"])
        self.assertFalse(evaluation.totals([passing, row(None, [])])["passed"])
        self.assertFalse(evaluation.totals([])["passed"])

    def test_grounding_uses_production_warnings_not_an_exact_word_match(self):
        self.brief["intent"]["elements"][0]["text"] = "participant one"
        self.assertTrue(self.check("no ungrounded required parts")["ok"])
        self.brief["intent"]["warnings"] = ['"castle" is required in every image, but the request does not seem to say it; check the analysis did not add it.']
        self.assertFalse(self.check("no ungrounded required parts")["ok"])

    def test_requested_identity_cases_are_in_the_plan_without_silently_enlarging_smoke(self):
        fixture = json.loads(evaluation.CASES.read_text(encoding="utf-8"))
        cases = {case["id"]: case for case in fixture["cases"]}
        for ident in ("two-men-mutual", "three-women-dancing", "two-men-roles", "couple-pronouns", "crowd-singer"):
            self.assertIn(ident, cases)
        self.assertTrue(cases["two-men-mutual"]["nsfw"])
        self.assertEqual(cases["two-men-mutual"]["request"], "2 men having sex")
        self.assertEqual(len(evaluation.plan(fixture, "smoke")), 3)
        self.assertEqual(len(evaluation.plan(fixture, "all")), len(fixture["cases"]) + len(fixture["reseeded"]))


if __name__ == "__main__":
    unittest.main()
