"""Recorded Gemma smoke replies replayed on CPU; no inference or private storage."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import intent, understanding
from tests.gpu import dataset_understanding_eval as evaluation
from tests.unit.dataset.test_dataset_understanding_v10 import MAN, WOMAN, answer, brief_of, draft, part

FIXTURE = Path(__file__).with_name("fixtures") / "understanding_gemma_smoke.json"


class GemmaSmokeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def replay(self, case_id, responses=None):
        case = self.cases[case_id]
        backend = MockBackend()
        responses = deepcopy(responses if responses is not None else case["responses"])
        with patch.object(backend, "generate", side_effect=[json.dumps(value) for value in responses]) as generate, \
                patch.object(understanding, "create_backend", return_value=backend), \
                patch.object(understanding, "DebugTrace"):
            result = understanding.understand({"backend": "mock"}, GoatedPrompterRequest(idea=case["request"]),
                                             draft(case["request"]), progress=lambda _message: None)
        return result, generate

    def test_model_schema_blocks_nonempty_object_participants_in_both_real_simple_replies(self):
        schema = Draft202012Validator(intent.model_schema())
        for value in self.cases["simple"]["responses"]:
            with self.subTest(value=value["randomized"]):
                self.assertFalse(schema.is_valid(value["intent"]), "schema must prevent by on a book")

    def test_recorded_greeting_self_relationship_is_rejected_without_changing_valid_bindings(self):
        original = deepcopy(self.cases["friends-greeting"]["responses"][0])
        errors = understanding.intent_errors(original, draft(self.cases["friends-greeting"]["request"]))
        self.assertTrue(any("two different parts" in error for error in errors))
        result, generate = self.replay("friends-greeting")
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        self.assertEqual(result["intent"]["relations"], [])
        for before, after in zip(original["intent"]["elements"], result["intent"]["elements"]):
            for field, value in before.items():
                self.assertEqual(after[field], value, field)
        self.assertEqual(result["intent"]["elements"][0]["cast"], ["friend 1", "friend 2"])
        self.assertTrue(any("relationship 1" in note for note in result["intent"]["warnings"]))
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(result[key], original[key])
        understanding.validate_brief(result)
        invalid = deepcopy(result)
        invalid["intent"]["relations"] = [{"id": "r1", **original["intent"]["relations"][0]}]
        with self.assertRaisesRegex(ValueError, "two different parts"):
            understanding.validate_brief(invalid)
        self.assertEqual(self.cases["friends-greeting"]["responses"][0], original)

    def test_scripted_neutral_greeting_needs_no_guessed_attributes_or_optional_detail_question(self):
        # A corrected contract example, not a claim that replay rewrites the old model's choices.
        corrected = deepcopy(self.cases["friends-greeting"]["responses"][0])
        corrected["characters"][0].update(gender="", pronoun="")
        corrected["intent"].update(relations=[], unresolved=[])
        Draft202012Validator(understanding._schema()).validate(corrected)
        self.assertEqual(understanding.model_errors(corrected, False), [])
        result, generate = self.replay("friends-greeting", [corrected])
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["characters"], [
            {"label": label, "gender": "", "custom": "", "pronoun": ""} for label in ("friend 1", "friend 2")])
        self.assertEqual(result["intent"]["unresolved"], [])
        self.assertEqual(result["intent"]["warnings"], [])
        self.assertEqual(result["intent"]["elements"][1]["by"], ["f1"])
        self.assertEqual(result["intent"]["elements"][1]["to"], ["f1"])
        understanding.validate_brief(result)

    def test_neutral_named_character_and_requested_attributes_round_trip_without_schema_redesign(self):
        for person in ({"label": "Alex", "gender": "", "custom": "", "pronoun": "", "count": 1},
                       {**WOMAN, "pronoun": ""}, {**MAN, "pronoun": ""}):
            with self.subTest(person=person):
                value = answer([person], [part("s", "subject", person["label"], character=person["label"])])
                Draft202012Validator(understanding._schema()).validate(value)
                self.assertEqual(understanding.model_errors(value, False), [])
                result = brief_of(value, draft(f'{person["label"]} waits'))
                self.assertEqual(result["characters"][0]["gender"], person["gender"])
                self.assertEqual(result["characters"][0]["pronoun"], {"male": "he", "female": "she"}.get(person["gender"], ""))
                understanding.validate_brief(result)
                legacy = {key: field for key, field in result.items() if key != "intent"}
                legacy["version"] = 9
                understanding.validate_brief(legacy)

    def test_self_relationship_rejection_keeps_other_relations_ownership_and_reflexive_actions(self):
        parts = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
                 part("a", "action", "washes herself", by=["s1"], to=["s1"]), part("o", "object", "hat", of="s2")]
        relation = {"a": "s1", "rel": "beside", "b": "s2", "status": "fixed"}
        for index in (0, 1):
            with self.subTest(index=index):
                relations = [relation.copy()]
                relations.insert(index, {"a": "s2", "rel": "beside", "b": "s2", "status": "fixed"})
                result = brief_of(answer([WOMAN, MAN], parts, relations), draft("A woman washes herself beside a man with his hat"))
                self.assertEqual(result["intent"]["relations"], [{"id": "r1", **relation}])
                self.assertEqual((result["intent"]["elements"][2]["by"], result["intent"]["elements"][2]["to"]), (["s1"], ["s1"]))
                self.assertEqual(result["intent"]["elements"][3]["of"], "s2")
                understanding.validate_brief(result)

    def test_real_simple_replies_mark_invalid_annotations_unavailable_without_a_new_interpretation(self):
        originals = deepcopy(self.cases["simple"]["responses"])
        for value in originals:
            errors = understanding.intent_errors(value, draft(self.cases["simple"]["request"]))
            self.assertTrue(any("by is only for action or pose" in error for error in errors))
        result, generate = self.replay("simple")
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        self.assertEqual(result["summary"], originals[0]["summary"])
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["b1"]["by"], items["b1"]["of"]), ([], ""), "no inferred role or owner")
        self.assertEqual(items["a1"]["by"], ["w1"])
        self.assertTrue(any("b1.by" in note and "unavailable" in note.lower() for note in result["intent"]["warnings"]))
        self.assertEqual(self.cases["simple"]["responses"], originals)

    def test_real_two_men_reply_keeps_valid_object_ownership_and_distinct_action_bindings(self):
        value = self.cases["two-men-roles"]["responses"][0]
        before = deepcopy(value)
        self.assertEqual(understanding.intent_errors(value, draft(self.cases["two-men-roles"]["request"])), [])
        result, generate = self.replay("two-men-roles")
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["g1"]["of"], items["c1"]["of"]), ("m1", "m2"))
        self.assertEqual((items["m1"]["cast"], items["m2"]["cast"]), (["man 1"], ["man 2"]))
        self.assertEqual((items["p1"]["by"], items["p1"]["to"], items["a1"]["by"], items["a1"]["to"]),
                         (["m1"], ["g1"], ["m2"], ["m1"]))
        for original in value["intent"]["elements"]:
            for field in ("kind", "text", "status", "source", "character", "of", "by", "to", "terms"):
                if field in original:
                    self.assertEqual(items[original["id"]][field], original[field], (original["id"], field))
        self.assertEqual(result["intent"]["relations"], [], "only the provably duplicate action relation is redundant")
        self.assertTrue(any('"camera" is required in every image' in note for note in result["intent"]["warnings"]))
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(result[key], value[key], "authoritative brief is not rewritten")
        self.assertEqual(value, before)
        understanding.validate_brief(result)

    def test_recorded_intent_errors_never_use_the_semantically_damaging_second_answer(self):
        for case_id in ("simple-varied", "two-men-varied"):
            with self.subTest(case=case_id):
                original = deepcopy(self.cases[case_id]["responses"][0])
                result, generate = self.replay(case_id)
                self.assertEqual(generate.call_count, 1, "intent-only errors cannot regenerate the answer")
                for key in ("summary", "fixed", "randomized", "must", "avoid"):
                    self.assertEqual(result[key], original[key])
                self.assertTrue(result["intent"]["available"])
                items = {item["id"]: item for item in result["intent"]["elements"]}
                self.assertEqual((items["a1"]["by"], items["a1"]["to"]), (["s1"], ["o1"]))
                if case_id == "simple-varied":
                    self.assertEqual(items["o1"]["of"], "", "invalid self-ownership cannot become inferred ownership")
                else:
                    self.assertEqual((items["a2"]["by"], items["a2"]["to"]), (["s2"], ["s1"]))
                    self.assertEqual((items["s1"]["cast"], items["s2"]["cast"]), (["man 1"], ["man 2"]))
                    self.assertNotIn("o2", items, "the model's unsupported suggestion cannot become mandatory")
                    checks = evaluation.score(next(c for c in json.loads(evaluation.CASES.read_text(encoding="utf-8"))["cases"]
                                                   if c["id"] == "two-men-roles"), result)
                    self.assertTrue(next(c for c in checks if c["check"].endswith(": to guitar"))["ok"])
                self.assertTrue(any("unavailable" in note.lower() for note in result["intent"]["warnings"]))
                understanding.validate_brief(result)
                self.assertEqual(self.cases[case_id]["responses"][0], original)

    def test_intent_error_cannot_change_other_relations_constraints_or_add_mandatory_facts(self):
        original = answer([WOMAN, MAN], [
            part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
            part("a", "action", "repairs", by=["s1"], to=["o"], terms=["restoration"]),
            part("o", "object", "clock", of="o"), part("e", "environment", "locations", "randomized"),
            part("x", "object", "gloves", "excluded"), part("v", "aspect", "lighting", "randomized", "suggested")],
            [{"a": "s2", "rel": "behind", "b": "s1", "status": "fixed"}],
            fixed="The woman repairs a clock while the man stands behind her", randomized="Locations and lighting",
            must=["Keep the clock brass"], avoid=["No gloves"])
        replacement = deepcopy(original)
        replacement["must"].append("A mandatory toolbox")
        replacement["intent"]["relations"][0]["a"] = "s1"
        replacement["intent"]["elements"][-1].update(source="request", status="fixed")
        result, generate = self.replay("simple", [original, replacement])
        self.assertEqual(generate.call_count, 1)
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(result[key], original[key])
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["a"]["by"], items["a"]["to"], items["a"]["terms"]), (["s1"], ["o"], ["restoration"]))
        self.assertEqual((items["e"]["status"], items["x"]["status"]), ("randomized", "excluded"))
        self.assertNotIn("v", items, "variation dimensions are already in the brief, not additional facts")
        self.assertEqual([(r["a"], r["rel"], r["b"]) for r in result["intent"]["relations"]], [("s2", "behind", "s1")])
        understanding.validate_brief(result)

    def test_recorded_bad_repair_fails_the_new_playing_target_expectation(self):
        case = next(c for c in json.loads(evaluation.CASES.read_text(encoding="utf-8"))["cases"] if c["id"] == "two-men-roles")
        broken = self.cases["two-men-varied"]["responses"][1]
        result = brief_of(deepcopy(broken), draft(case["request"]))
        checks = evaluation.score(case, result)
        self.assertFalse(next(c for c in checks if c["check"].endswith(": to guitar"))["ok"],
                         "the scorer must catch a structurally valid but wrong target")
        self.assertEqual(result["intent"]["relations"], [], "the passive relation only duplicates photographing")

    def test_retest_redundant_suggested_attribute_is_not_an_independent_requirement(self):
        value = deepcopy(self.cases["simple-retest"]["responses"][0])
        result, generate = self.replay("simple-retest")
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(result[key], value[key])
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["e1"]["text"], items["e1"]["status"]), ("cozy cafe", "fixed"))
        self.assertEqual(value["intent"]["elements"][-1]["status"], "randomized")
        self.assertNotIn("as1", items)
        self.assertEqual(result["intent"]["warnings"], [])
        self.assertTrue(all(not item["terms"] for item in items.values()), "no invented search hints")
        understanding.validate_brief(result)

    def test_legacy_v10_suggestion_conflict_is_still_recomputed_after_review(self):
        repaired = deepcopy(self.cases["simple"]["responses"][-1])
        del repaired["intent"]["elements"][2]["by"]
        result = brief_of(repaired, draft(self.cases["simple"]["request"]))
        result["intent"] = intent.normalize(repaired["intent"], result["characters"], result["avoid"],
                                            understanding.user_texts(result["input"]))
        self.assertTrue(any("fixed" in note and "randomized" in note for note in result["intent"]["warnings"]))
        submitted = deepcopy(result)
        submitted["intent"]["elements"] = [item for item in submitted["intent"]["elements"] if item["id"] != "m1"]
        reviewed = understanding.reviewed_brief(result, submitted)
        self.assertFalse(any("fixed" in note and "randomized" in note for note in reviewed["intent"]["warnings"]))
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(reviewed[key], result[key])

    def test_harmless_empty_fields_normalize_without_guessing_an_action_target(self):
        value = deepcopy(self.cases["simple"]["responses"][0])
        for item in value["intent"]["elements"]:
            for key in ("character", "member", "of", "by", "to", "input", "terms"):
                item.setdefault(key, None)
        value["intent"]["elements"][2]["by"] = None
        value["intent"]["elements"][0]["of"] = "  "
        before = deepcopy(value)
        result, generate = self.replay("simple", [value])
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["a1"]["by"], items["a1"]["to"]), (["w1"], []), "no inferred book target")
        self.assertEqual((items["b1"]["by"], items["b1"]["of"]), ([], ""), "no guessed ownership")
        self.assertEqual(value, before)
        understanding.validate_brief(result)

    def test_scripted_repair_is_not_called_and_all_requested_parts_and_hints_remain(self):
        first, repaired = deepcopy(self.cases["simple"]["responses"])
        del repaired["intent"]["elements"][2]["by"]  # the scripted model repair, never a production normalization
        result, generate = self.replay("simple", [first, repaired])
        self.assertEqual(generate.call_count, 1)
        self.assertTrue(result["intent"]["available"])
        self.assertEqual(len(result["intent"]["elements"]), 4)
        self.assertTrue(any("b1.by" in note for note in result["intent"]["warnings"]))
        self.assertEqual(result["intent"]["elements"][1]["terms"], first["intent"]["elements"][1]["terms"])
        for key in ("summary", "fixed", "randomized", "must", "avoid"):
            self.assertEqual(result[key], first[key])


class FieldAndConflictBoundaryTests(unittest.TestCase):
    def errors(self, parts, guided=0):
        return intent.check({"elements": parts, "relations": []}, {"man": 1, "woman": 1}, guided)

    def test_schema_kind_variants_and_runtime_rules_agree_on_meaningful_fields(self):
        schema = Draft202012Validator(intent.model_schema())
        Draft202012Validator.check_schema(intent.model_schema())
        allowed = {"subject": {"character", "member"}, "action": {"by", "to"}, "pose": {"by"},
                   "object": {"of"}, "body_part": {"of"}, "attribute": {"of"}, "environment": set(), "aspect": set()}
        fields = {"character": "man", "member": 1, "by": ["s"], "to": ["s"], "of": "s"}
        for kind, permitted in allowed.items():
            for field, field_value in fields.items():
                with self.subTest(kind=kind, field=field):
                    item = part("x", kind, "detail", **{field: field_value})
                    if field == "member":
                        item["character"] = "man"
                    value = {"elements": [part("s", "subject", "woman", character="woman"), item], "relations": []}
                    self.assertEqual(schema.is_valid(value), field in permitted)
                    self.assertEqual(not self.errors(value["elements"]), field in permitted)

    def test_object_ownership_still_rejects_invalid_reference_kind_cycles_and_cross_scope(self):
        subject = part("s", "subject", "man", character="man")
        self.assertEqual(self.errors([subject, part("o", "object", "hat", of="s")]), [])
        self.assertEqual(self.errors([subject, part("o", "object", "hat", of="p"), part("p", "object", "box", of="s")]), [])
        bad = [
            [subject, part("o", "object", "hat", of="missing")],
            [subject, part("o", "object", "hat", of="o")],
            [subject, part("a", "action", "holds", by=["s"]), part("o", "object", "hat", of="a")],
            [subject, part("o", "object", "hat", of="p"), part("p", "object", "box", of="o")],
            [subject, part("o", "object", "hat", input=1), part("p", "object", "box", of="o", input=2)],
            [subject, part("o", "object", "hat", by=["s"])],
            [subject, part("o", "object", "hat", to=["s"])],
        ]
        for parts in bad:
            with self.subTest(parts=parts):
                self.assertTrue(self.errors(parts, guided=2))

    def test_empty_normalization_never_hides_unknown_fields_or_nonempty_bad_references(self):
        for fields in ({"by": ["s"]}, {"to": ["s"]}, {"of": "missing"}, {"of": ["s"]}, {"confidence": None}):
            with self.subTest(fields=fields):
                value = answer([MAN], [part("s", "subject", "man", character="man"), part("o", "object", "hat", **fields)])
                before = deepcopy(value)
                self.assertTrue(understanding.intent_errors(value, draft("A man with a hat")))
                self.assertEqual(value, before)

    def test_model_empty_tolerance_does_not_weaken_the_stored_contract(self):
        parts = [part("s", "subject", "man", character="man"), part("o", "object", "hat", of="s"),
                 part("a", "action", "holds", by=["s"], to=["o"])]
        brief = brief_of(answer([MAN], parts), draft("A man holds his hat"))
        for index, field in [(0, "character"), (1, "of"), (2, "by"), (2, "to"), (2, "terms")]:
            with self.subTest(field=field):
                invalid = deepcopy(brief)
                invalid["intent"]["elements"][index][field] = None
                with self.assertRaises(ValueError):
                    understanding.validate_brief(invalid)

    def test_unavailable_annotations_preserve_unrelated_owners_hints_and_relationships(self):
        parts = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
                 part("a", "action", "mends", by=["s1"], to=["o"], terms=["restoration"]),
                 part("o", "object", "scarf", of="p"), part("p", "object", "box", of="o"),
                 part("b", "body_part", "hand", of="s2"), part("v", "aspect", "lighting", "randomized", "suggested")]
        value = answer([WOMAN, MAN], parts, [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"},
                                           {"a": "s1", "rel": "near", "b": "missing", "status": "fixed"},
                                           {"a": [], "rel": "near", "b": "s2", "status": "fixed"}])
        before = deepcopy(value)
        data = draft("A woman mends a scarf behind a man with his hand raised")
        result = brief_of(value, data)
        items = {item["id"]: item for item in result["intent"]["elements"]}
        self.assertEqual((items["o"]["of"], items["p"]["of"]), ("", ""), "do not pick a winner in an ownership cycle")
        self.assertEqual(items["b"]["of"], "s2")
        self.assertEqual((items["a"]["by"], items["a"]["to"], items["a"]["terms"]), (["s1"], ["o"], ["restoration"]))
        self.assertEqual([(r["a"], r["rel"], r["b"]) for r in result["intent"]["relations"]], [("s1", "behind", "s2")])
        self.assertEqual(value, before)
        submitted = deepcopy(result)
        submitted["intent"]["warnings"] = ["forged notice"]
        submitted["intent"]["elements"][2]["terms"] = ["repair"]
        reviewed = understanding.reviewed_brief(result, submitted)
        self.assertEqual(reviewed["intent"]["warnings"], result["intent"]["warnings"], "only server notices survive edits")
        understanding.validate_brief(reviewed)

    def test_cross_scope_action_targets_become_unavailable_without_globalizing_or_guessing(self):
        data = draft("A woman reads", source_mode="guided", inputs="She holds a parcel\nShe opens a box")
        parts = [part("s", "subject", "woman", character="woman"), part("a", "action", "holds", by=["s"], to=["o"], input=1),
                 part("o", "object", "box", input=2)]
        result = brief_of(answer([WOMAN], parts), data)
        action = next(item for item in result["intent"]["elements"] if item["id"] == "a")
        self.assertEqual((action["by"], action["to"], action["input"]), (["s"], [], 1))
        self.assertTrue(any("a.to" in note for note in result["intent"]["warnings"]))
        understanding.validate_brief(result)

    def test_only_identical_action_relations_are_redundant(self):
        parts = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
                 part("a", "action", "photographs", by=["s1"], to=["s2"])]
        for rel, status, remaining in [("is photographing", "fixed", 0), ("not photographing", "fixed", 1),
                                       ("is photographing outdoors", "fixed", 1), ("behind", "fixed", 1),
                                       ("is photographing", "excluded", 1)]:
            with self.subTest(rel=rel, status=status):
                value = answer([WOMAN, MAN], parts, [{"a": "s1", "rel": rel, "b": "s2", "status": status}])
                result = brief_of(value, draft("A woman photographs a man"))
                self.assertEqual(len(result["intent"]["relations"]), remaining)
                self.assertEqual(result["intent"]["elements"][2]["by"], ["s1"])
        unbound = deepcopy(parts)
        unbound[-1]["by"] = []
        result = brief_of(answer([WOMAN, MAN], unbound, [{"a": "s1", "rel": "photographs", "b": "s2", "status": "fixed"}]),
                          draft("A woman photographs a man"))
        self.assertEqual(result["intent"]["elements"][2]["by"], [])
        self.assertEqual(len(result["intent"]["relations"]), 1, "relation does not invent an action binding")

    def test_passive_deduplication_preserves_modifiers_negation_scope_and_direction(self):
        parts = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
                 part("a", "action", "kisses", by=["s1"], to=["s2"])]
        for wording, first, second, status, count in [
            ("is being kissed by", "s2", "s1", "fixed", 0),
            ("is being kissed by", "s1", "s2", "fixed", 1),
            ("is being gently kissed by", "s2", "s1", "fixed", 1),
            ("is being not kissed by", "s2", "s1", "fixed", 1),
            ("is being kissed by", "s2", "s1", "excluded", 1),
        ]:
            with self.subTest(wording=wording, first=first, status=status):
                value = answer([WOMAN, MAN], parts, [{"a": first, "rel": wording, "b": second, "status": status}])
                result = brief_of(value, draft("A woman kisses a man"))
                self.assertEqual(len(result["intent"]["relations"]), count)
                self.assertEqual((result["intent"]["elements"][2]["by"], result["intent"]["elements"][2]["to"]), (["s1"], ["s2"]))

    def test_relations_with_missing_targets_group_actors_or_different_scope_are_preserved(self):
        for fields in ({"to": []}, {"by": ["s1", "s2"]}, {"input": 1}):
            with self.subTest(fields=fields):
                action = part("a", "action", "photographs", by=["s1"], to=["s2"])
                action.update(fields)
                parts = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"), action]
                data = draft("A woman photographs a man", source_mode="guided", inputs="First\nSecond")
                result = brief_of(answer([WOMAN, MAN], parts, [{"a": "s1", "rel": "photographs", "b": "s2", "status": "fixed"}]), data)
                self.assertEqual(len(result["intent"]["relations"]), 1)
                self.assertEqual(result["intent"]["elements"][2]["by"], action["by"])
                self.assertEqual(result["intent"]["elements"][2]["to"], action["to"])

    def test_conflict_detection_respects_owner_and_guided_scope(self):
        base = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man")]
        for owner, fixed_input, varied_input, conflict in [("s1", 0, 0, True), ("s2", 0, 0, False),
                                                          ("s1", 1, 2, False), ("s1", 0, 2, True)]:
            with self.subTest(owner=owner, fixed_input=fixed_input, varied_input=varied_input):
                parts = [*base, part("f", "attribute", "red", of="s1", input=fixed_input),
                         part("v", "attribute", "red", "randomized", of=owner, input=varied_input)]
                data = draft("A woman and a man, red", source_mode="guided", inputs="First\nSecond")
                result = brief_of(answer([WOMAN, MAN], parts), data)
                notes = result["intent"]["warnings"]
                self.assertEqual(any("fixed" in note and "randomized" in note for note in notes), conflict)

    def test_embedded_attribute_conflicts_do_not_guess_synonyms_or_ignore_negation(self):
        for text, conflict in [("quiet garden", False), ("not cozy", False), ("cozy garden", True)]:
            with self.subTest(text=text):
                parts = [part("e", "environment", text), part("v", "aspect", "cozy", "randomized")]
                result = brief_of(answer([], list(reversed(parts))), draft(f"A {text}"))
                self.assertEqual(any("fixed" in note and "randomized" in note for note in result["intent"]["warnings"]), conflict)

    def test_prompt_explains_ownership_and_reliable_search_alternatives_without_forcing_terms(self):
        prompt = understanding.instruction(draft("A person with a scarf"), "gemma")
        self.assertIn("Objects must not have by or to", prompt.system_message)
        self.assertIn("Do not duplicate actions", prompt.system_message)
        self.assertIn("0 to 3", prompt.system_message)
        self.assertIn("Do not invent synonyms", prompt.system_message)

    def test_prompt_keeps_unspecified_attributes_open_and_only_real_binding_ambiguity_unresolved(self):
        for family in ("gemma", "qwen"):
            with self.subTest(family=family):
                system = " ".join(understanding.instruction(draft("Two friends greet each other"), family).system_message.split())
                self.assertIn('Use "" for an unspecified gender or pronoun', system)
                self.assertIn("Do not infer gender from a name, role or group", system)
                self.assertIn("Never turn an unspecified attribute into a requested fact", system)
                self.assertIn("Missing optional details (gender, appearance, clothing, setting) are not unresolved", system)
                self.assertIn('Keep genuine ambiguity about stated facts or who acts on whom', system)
                self.assertIn("a and b must be different part ids", system)

    def test_prompt_uses_one_status_authority_for_required_attributes_and_allowed_variation(self):
        cases = [
            ("A woman reading a book in a cozy cafe.", ""),
            ("A brass telescope in a quiet observatory.", "Keep the brass finish."),
            ("A bicycle, red or blue; its color may vary.", "The location may vary too."),
        ]
        for request, rules in cases:
            for family in ("gemma", "qwen"):
                with self.subTest(request=request, family=family):
                    prompt = understanding.instruction(draft(request, constraints=rules), family)
                    system = " ".join(prompt.system_message.split())
                    self.assertIn("Preserve explicitly requested attributes unless the user allows them to vary.", system)
                    self.assertIn("Derive status from fixed, randomized, must and avoid, not a second interpretation", system)
                    self.assertIn("A variable dimension does not make its fixed attributes variable.", system)
                    self.assertIn("suggested dimensions stay in randomized, not in elements", system)
                    self.assertEqual(json.loads(prompt.user_message), {"request": request, "rules": [rules] if rules else []})

    def test_explicit_variation_is_not_promoted_to_fixed_just_because_its_words_are_requested(self):
        value = answer([], [part("o", "object", "bicycle"), part("v", "attribute", "red or blue", "randomized", of="o")],
                       fixed="A bicycle", randomized="Bicycle color: red or blue")
        before = deepcopy(value)
        result = brief_of(value, draft("A bicycle, red or blue; its color may vary."))
        self.assertEqual(result["intent"]["elements"][1]["status"], "randomized")
        self.assertEqual(result["intent"]["warnings"], [])
        self.assertEqual(value, before)
        understanding.validate_brief(result)


if __name__ == "__main__":
    unittest.main()
