"""Understanding v10: structured intent from the same call, checked, reported and safely editable.

Scripted model answers only: these tests check the contract, never model quality.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.service import default_dataset_draft
from goated_prompter.features.dataset.v2 import intent, runs, understanding
from goated_prompter.features.vocabulary.retrieval import RetrievalRequest

MAN = {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}
WOMAN = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}


def draft(subject, **extra):
    return {**default_dataset_draft(), "subject": subject, "amount": 2, "seed": 7, "seed_mode": "fixed", **extra}


def answer(characters, parts, relations=(), *, must=(), avoid=(), unresolved=(), truncated=None, **fields):
    value = {"path": "character" if characters else "non_character", "summary": "A scene", "characters": list(characters),
             "fixed": "The people and the action", "randomized": "Lighting and camera", "must": list(must), "avoid": list(avoid),
             "intent": {"elements": list(parts), "relations": list(relations), "unresolved": list(unresolved)}}
    if truncated is not None:
        value["intent"]["truncated"] = truncated
    return {**value, **fields}


def part(ident, kind, text, status="fixed", source="request", **links):
    return {"id": ident, "kind": kind, "text": text, "status": status, "source": source, **links}


NECK = [part("s1", "subject", "woman", character="woman"), part("s2", "subject", "man", character="man"),
        part("b1", "body_part", "neck", of="s2"), part("a1", "action", "kisses", by=["s1"], to=["b1"], terms=["kiss"]),
        part("a2", "action", "reads", by=["s2"]), part("e1", "environment", "location", "randomized"),
        part("k1", "aspect", "lighting", "randomized", "suggested")]


def brief_of(value, data):
    return understanding.apply_rules(value, data, Mock())


class Contract(unittest.TestCase):
    """The intent contract, shared by analysis and confirmation."""

    def errors(self, parts, relations=(), characters=(WOMAN, MAN), guided=0, **extra):
        value = {"elements": list(parts), "relations": list(relations), **extra}
        return intent.check(value, {item["label"]: item["count"] for item in characters}, guided)

    def test_a_correct_answer_has_no_errors_and_keeps_every_link(self):
        self.assertEqual(self.errors(NECK, [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}]), [])
        data = draft("A woman kisses a man's neck while he reads, in different locations")
        brief = brief_of(answer([WOMAN, MAN], NECK, [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}]), data)
        parts = {item["id"]: item for item in brief["intent"]["elements"]}
        self.assertEqual((parts["a1"]["by"], parts["a1"]["to"], parts["b1"]["of"], parts["a2"]["by"]), (["s1"], ["b1"], "s2", ["s2"]))
        self.assertEqual((parts["s1"]["cast"], parts["s2"]["cast"]), (["woman"], ["man"]))
        self.assertEqual(brief["intent"]["relations"], [{"id": "r1", "a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}])
        self.assertEqual(brief["version"], 10)
        understanding.validate_brief(brief)

    def test_empty_optional_fields_are_the_same_as_leaving_them_out(self):
        empties = {"character": "", "of": "", "by": [], "to": [], "input": 0, "terms": []}
        filled = [{**empties, **item} for item in NECK]
        self.assertEqual(self.errors(filled), [])
        data = draft("A woman kisses a man's neck while he reads, in different locations")
        self.assertEqual(brief_of(answer([WOMAN, MAN], filled), data), brief_of(answer([WOMAN, MAN], NECK), data))
        wrong = {"subject with by": {**filled[0], "by": ["s2"]}, "part with a character": {**filled[2], "character": "man"},
                 "unknown character": {**filled[0], "character": "nobody"}, "input without guided inputs": {**filled[4], "input": 1}}
        for name, item in wrong.items():
            with self.subTest(name):
                self.assertTrue(self.errors([item if part["id"] == item["id"] else part for part in filled]))

    def test_invalid_references_are_contract_errors(self):
        cases = {
            "by must list subjects": [*NECK[:4], part("a9", "action", "reads", by=["b1"])],
            "of must be the id": [part("s1", "subject", "woman"), part("t1", "attribute", "red", of="k9")],
            "to cannot be an attribute": [part("s1", "subject", "woman"), part("t1", "attribute", "red", of="s1"),
                                          part("a1", "action", "touches", by=["s1"], to=["t1"])],
            "short unique id": [part("s1", "subject", "woman"), part("s1", "subject", "man")],
            "must list ids of other parts": [part("s1", "subject", "woman"), part("a1", "action", "hugs", by=["s1"], to=["a1"])],
            "belongs to itself": [part("s1", "subject", "woman"), part("b1", "body_part", "hand", of="b2"),
                                  part("b2", "body_part", "finger", of="b1")],
            "one of the characters labels": [part("s1", "subject", "elf", character="elf")],
            "is only for an object, body part or attribute": [part("s1", "subject", "woman", of="s1")],
            "a suggested part may only be a dimension": [part("o1", "object", "hat", "optional", "suggested")],
        }
        for expected, parts in cases.items():
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in error for error in self.errors(parts)), self.errors(parts))
        self.assertTrue(self.errors(NECK, [{"a": "s1", "rel": "on", "b": "zz", "status": "fixed"}]))
        self.assertTrue(self.errors(NECK, [{"a": "s1", "rel": "on", "b": "s1", "status": "fixed"}]))
        self.assertTrue(self.errors(NECK, [{"a": "s1", "rel": "on", "b": "s2", "status": "randomized"}]))

    def test_guided_parts_stay_with_their_own_input(self):
        guided = [part("s1", "subject", "reader"), part("a1", "action", "reads", by=["s1"], input=1),
                  part("o1", "object", "bench", input=1), part("o2", "object", "fountain", input=2)]
        self.assertEqual(self.errors(guided, [{"a": "a1", "rel": "on", "b": "o1", "status": "fixed"}], characters=(), guided=2), [])
        crossing = [*guided, part("a2", "action", "sits", by=["s1"], to=["o2"], input=1)]
        self.assertIn("links to a part of another guided input", " ".join(self.errors(crossing, characters=(), guided=2)))
        global_to_scoped = [*guided, part("a3", "action", "faces", by=["s1"], to=["o2"])]
        self.assertIn("another guided input", " ".join(self.errors(global_to_scoped, characters=(), guided=2)))
        across = [{"a": "o1", "rel": "near", "b": "o2", "status": "fixed"}]
        self.assertIn("two different guided inputs", " ".join(self.errors(guided, across, characters=(), guided=2)))
        self.assertIn("only for guided inputs", " ".join(self.errors([part("o1", "object", "bench", input=1)], characters=())))
        self.assertIn("one of the 2 guided inputs", " ".join(self.errors([part("o1", "object", "bench", input=3)], characters=(), guided=2)))

    def test_limits_ask_for_truncated_instead_of_silently_dropping(self):
        many = [part(f"o{number}", "object", f"thing {number}") for number in range(25)]
        self.assertIn("set truncated", self.errors(many)[0])
        data = draft("A shelf")
        brief = brief_of(answer([], many[:24], truncated=True), data)
        self.assertTrue(brief["intent"]["truncated"])
        self.assertTrue(any("more parts than fit" in note for note in brief["intent"]["warnings"]))


class Groups(unittest.TestCase):

    def test_identical_people_expand_with_stable_labels_and_the_subject_keeps_them_all(self):
        data = draft("Three men and a woman on a beach")
        men = {"label": "men", "gender": "male", "custom": "", "pronoun": "he", "count": 3}
        parts = [part("s1", "subject", "men", character="men"), part("s2", "subject", "woman", character="woman"),
                 part("e1", "environment", "beach")]
        brief = brief_of(answer([men, WOMAN], parts), data)
        self.assertEqual([person["label"] for person in brief["characters"]], ["man 1", "man 2", "man 3", "woman"])
        subjects = {item["id"]: item for item in brief["intent"]["elements"]}
        self.assertEqual((subjects["s1"]["character"], subjects["s1"]["cast"]), ("man", ["man 1", "man 2", "man 3"]))
        self.assertEqual(subjects["s2"]["cast"], ["woman"])
        understanding.validate_brief(brief)

    def test_five_subjects_with_overlapping_attributes_keep_their_owners(self):
        cast = [{"label": name, "gender": "female", "custom": "", "pronoun": "she", "count": 1}
                for name in ("Ana", "Bea", "Cleo", "Dina", "Eva")]
        data = draft("Ana and Bea in red dresses, Cleo and Dina in red hats, Eva with red hair")
        parts = [part(f"s{number}", "subject", name, character=name) for number, name in enumerate(("Ana", "Bea", "Cleo", "Dina", "Eva"), 1)]
        parts += [part("o1", "object", "dresses", of="s1") if False else part("o1", "object", "dresses"),
                  part("t1", "attribute", "red", of="o1"), part("o2", "object", "hats"), part("t2", "attribute", "red", of="o2"),
                  part("b1", "body_part", "hair", of="s5"), part("t3", "attribute", "red", of="b1")]
        relations = [{"a": "s1", "rel": "in", "b": "o1", "status": "fixed"}, {"a": "s2", "rel": "in", "b": "o1", "status": "fixed"},
                     {"a": "s3", "rel": "in", "b": "o2", "status": "fixed"}, {"a": "s4", "rel": "in", "b": "o2", "status": "fixed"}]
        brief = brief_of(answer(cast, parts, relations), data)
        owners = {item["id"]: item["of"] for item in brief["intent"]["elements"]}
        self.assertEqual((owners["t1"], owners["t2"], owners["t3"], owners["b1"]), ("o1", "o2", "b1", "s5"))
        self.assertEqual([(item["a"], item["b"]) for item in brief["intent"]["relations"]],
                         [("s1", "o1"), ("s2", "o1"), ("s3", "o2"), ("s4", "o2")])
        self.assertEqual(brief["intent"]["warnings"], [])

    def test_an_ambiguous_pronoun_stays_unresolved_instead_of_guessed(self):
        data = draft("Two women; she holds her hand")
        women = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 2}
        parts = [part("s1", "subject", "women", character="woman"), part("b1", "body_part", "hand"),
                 part("a1", "action", "holds", to=["b1"])]
        brief = brief_of(answer([women], parts, unresolved=['who "she" and "her" are']), data)
        held = brief["intent"]["elements"][2]
        self.assertEqual((held["by"], brief["intent"]["unresolved"]), ([], ['who "she" and "her" are']))
        self.assertTrue(brief["intent"]["available"])


MEN = {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}
WOMEN = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 2}


class People(unittest.TestCase):
    """Who each part is: one person, or a whole group of identical people; never every part bound to the group."""

    def people(self, brief):
        return {item["id"]: (item["member"], item["cast"]) for item in brief["intent"]["elements"] if item["kind"] == "subject"}

    def test_two_men_as_the_model_answered_are_two_distinct_people(self):
        # The model's actual answer for "2 men having sex" (debug trace), with the action's participants as now asked.
        parts = [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man"),
                 part("sex", "action", "having sex", by=["m1", "m2"])]
        data = draft("2 men having sex", nsfw=True)
        brief = understanding.confirm(brief_of(answer([MEN], parts, [{"a": "m1", "rel": "having sex with", "b": "m2",
                                                                      "status": "fixed"}]), data), data)
        self.assertEqual(self.people(brief), {"m1": (1, ["man 1"]), "m2": (2, ["man 2"])})
        self.assertEqual(brief["intent"]["warnings"], [], "an ordinary request confirms without any correction")
        self.assertEqual([item["label"] for item in brief["characters"]], ["man 1", "man 2"])

    def test_distinct_roles_keep_their_own_actions_and_belongings(self):
        parts = [part("w1", "subject", "woman", character="woman", member=1), part("w2", "subject", "woman", character="woman", member=2),
                 part("a1", "action", "paints", by=["w1"], to=["o1"]), part("o1", "object", "canvas"),
                 part("a2", "action", "sings", by=["w2"]), part("b1", "body_part", "hair", of="w2"), part("t1", "attribute", "red", of="b1")]
        brief = brief_of(answer([WOMEN], parts), draft("Two women: one paints a canvas, the other, with red hair, sings"))
        items = {item["id"]: item for item in brief["intent"]["elements"]}
        self.assertEqual(self.people(brief), {"w1": (1, ["woman 1"]), "w2": (2, ["woman 2"])})
        self.assertEqual((items["a1"]["by"], items["a2"]["by"], items["b1"]["of"], items["t1"]["of"]), (["w1"], ["w2"], "w2", "b1"))
        self.assertEqual(brief["intent"]["warnings"], [])

    def test_unnumbered_parts_get_the_remaining_people_in_order(self):
        parts = [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man", member=1)]
        brief = brief_of(answer([MEN], parts), draft("Two men"))
        self.assertEqual(self.people(brief), {"m1": (2, ["man 2"]), "m2": (1, ["man 1"])})

    def test_a_group_part_stands_for_everyone_and_raises_nothing(self):
        three = {**MEN, "count": 3}
        parts = [part("g1", "subject", "men", character="man"), part("a1", "action", "cheering", by=["g1"])]
        brief = brief_of(answer([three], parts), draft("Three men cheering"))
        self.assertEqual(self.people(brief), {"g1": (0, ["man 1", "man 2", "man 3"])})
        self.assertEqual(brief["intent"]["warnings"], [])

    def test_fewer_unnumbered_parts_than_people_are_reported_not_guessed(self):
        three = {**MEN, "count": 3}
        parts = [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man"),
                 part("a1", "action", "lifts", by=["m1"])]
        brief = brief_of(answer([three], parts), draft("Three men; one lifts weights"))
        self.assertEqual({ident: member for ident, (member, _cast) in self.people(brief).items()}, {"m1": 0, "m2": 0})
        self.assertTrue(any('2 parts refer to "man"' in note and "unclear" in note for note in brief["intent"]["warnings"]))

    def test_impossible_people_are_contract_errors(self):
        counts = {"man": 2, "woman": 1}
        cases = {
            "is 2 people but has 3 subject parts": [part(f"m{n}", "subject", "man", character="man") for n in (1, 2, 3)],
            "same person": [part("m1", "subject", "man", character="man", member=1), part("m2", "subject", "man", character="man", member=1)],
            "member must number": [part("m1", "subject", "man", character="man", member=3)],
            "member must number one": [part("o1", "object", "cup", member=1)],
            "is 1 person but has 2": [part("w1", "subject", "woman", character="woman"), part("w2", "subject", "her", character="woman")]}
        for expected, parts in cases.items():
            with self.subTest(expected):
                self.assertIn(expected, " ".join(intent.check({"elements": parts, "relations": []}, counts, 0)))

    def test_people_without_a_part_get_one_but_never_a_duplicate(self):
        brief = brief_of(answer([MEN, WOMAN], [part("a1", "action", "dancing")]), draft("Two men and a woman dancing"))
        self.assertEqual({item["text"]: item["cast"] for item in brief["intent"]["elements"] if item["kind"] == "subject"},
                         {"man": ["man 1", "man 2"], "woman": ["woman"]})
        self.assertEqual(brief["intent"]["elements"][-1]["id"], "a1", "the model's parts are all kept, in order")
        unbound = brief_of(answer([MEN], [part("s1", "subject", "couple"), part("a1", "action", "dancing", by=["s1"])]),
                           draft("A couple of men dancing"))
        self.assertEqual([item["id"] for item in unbound["intent"]["elements"]], ["s1", "a1"])

    def test_requested_details_and_links_are_kept_without_repeating_suggested_dimensions(self):
        relations = [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}]
        value = answer([WOMAN, MAN], NECK, relations, unresolved=["which room"])
        brief = brief_of(deepcopy(value), draft("A woman kisses a man's neck while he reads, in different locations"))
        kept = {item["id"]: item for item in brief["intent"]["elements"]}
        for item in value["intent"]["elements"]:
            if item["source"] == "suggested":
                self.assertNotIn(item["id"], kept)
                continue
            for key, field in item.items():
                self.assertEqual(kept[item["id"]][key], field.strip() if isinstance(field, str) else field, (item["id"], key))
        self.assertEqual([(item["a"], item["b"]) for item in brief["intent"]["relations"]], [("s1", "s2")])
        self.assertEqual(brief["intent"]["unresolved"], ["which room"])

    def test_identities_survive_review_confirmation_and_storage(self):
        parts = [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man"),
                 part("a1", "action", "carries", by=["m1"], to=["m2"])]
        data = draft("Two men; one carries the other")
        brief = brief_of(answer([MEN], parts), data)
        submitted = deepcopy(brief)
        for item in submitted["intent"]["elements"]:
            if item["kind"] == "subject":
                item["member"] = 3 - item["member"]  # the reviewer swaps who is who
        swapped = understanding.reviewed_brief(brief, submitted)
        self.assertEqual(self.people(swapped), {"m1": (2, ["man 2"]), "m2": (1, ["man 1"])})
        stored = json.loads(json.dumps(understanding.confirm(swapped, data)))
        self.assertEqual(self.people(understanding.validate_brief(stored)), self.people(swapped))
        submitted["intent"]["elements"][1]["member"] = submitted["intent"]["elements"][0]["member"]
        with self.assertRaisesRegex(ValueError, "same person"):
            understanding.reviewed_brief(brief, submitted)

    def test_a_brief_stored_before_member_existed_still_loads(self):
        brief = brief_of(answer([MEN], [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man")]),
                         draft("Two men"))
        for item in brief["intent"]["elements"]:
            del item["member"]
            item["cast"] = ["man 1", "man 2"]  # how the first v10 briefs stored every part of a group
        understanding.validate_brief(brief)
        self.assertTrue(any("without saying which person" in note for note in
                            intent.warnings(brief["intent"], [], ["Two men"])))


class Reporting(unittest.TestCase):
    """Wording and clashes are reported, never rewritten: words cannot tell a paraphrase from an invention."""

    def test_a_required_part_sharing_no_word_with_the_request_is_reported_and_kept(self):
        data = draft("A couple kissing at sunset")
        parts = [part("s1", "subject", "couple"), part("a1", "action", "smooching", by=["s1"]), part("k1", "aspect", "sunset")]
        brief = brief_of(answer([], parts), data)
        kiss = brief["intent"]["elements"][1]
        self.assertEqual((kiss["status"], kiss["source"]), ("fixed", "request"), "a paraphrase keeps its status")
        self.assertEqual(brief["intent"]["warnings"], ['"smooching" is required in every image, but the request does not '
                                                       "seem to say it; check the analysis did not add it."])

    def test_word_forms_numbers_and_people_are_not_wording_problems(self):
        men = {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}
        cases = {
            "2 men having sex": [part("m1", "subject", "man", character="man"), part("m2", "subject", "man", character="man"),
                                 part("a1", "action", "having sex", by=["m1", "m2"])],
            "Two men kiss, with feet in the water": [part("m1", "subject", "men", character="man"),
                                                     part("a1", "action", "kissing", by=["m1"]), part("b1", "body_part", "foot", of="m1"),
                                                     part("e1", "environment", "water")],
            "The man dances": [part("m1", "subject", "man", character="man"), part("a1", "action", "dancing", by=["m1"]),
                               part("k1", "aspect", "lighting", "randomized", "suggested"),
                               part("e1", "environment", "studio", "randomized")]}
        for request, parts in cases.items():
            with self.subTest(request):
                people = [men] if request != "The man dances" else [MAN]
                brief = brief_of(answer(people, parts), draft(request, nsfw="sex" in request))
                self.assertEqual(brief["intent"]["warnings"], [])

    def test_an_invented_exclusion_is_reported_too(self):
        brief = brief_of(answer([WOMAN], [part("s1", "subject", "woman", character="woman"),
                                          part("x1", "object", "umbrella", "excluded")], avoid=["no umbrella"]),
                         draft("A woman walking in the rain"))
        self.assertIn('"umbrella" is ruled out, but the request does not seem to say it', " ".join(brief["intent"]["warnings"]))

    def test_an_unsupported_fact_is_reported_and_an_invented_optional_detail_is_refused(self):
        data = draft("A woman reading")
        parts = [part("s1", "subject", "woman", character="woman"), part("a1", "action", "reading", by=["s1"]),
                 part("o1", "object", "whip")]
        brief = brief_of(answer([WOMAN], parts), data)
        self.assertTrue(any('"whip" is required in every image, but the request does not seem to say it' in note
                            for note in brief["intent"]["warnings"]))
        self.assertEqual(brief["fixed"], "The people and the action", "the authoritative fields are untouched")
        invented = [*parts[:2], part("o2", "object", "cup", "optional", "suggested")]
        self.assertTrue(intent.check({"elements": invented, "relations": []}, {"woman": 1}, 0))

    def test_clashes_with_avoid_and_contradictory_statuses_are_reported(self):
        data = draft("Two adults, no oral, kissing is fine", nsfw=True)
        parts = [part("s1", "subject", "adults"), part("a1", "action", "oral"), part("a2", "action", "kissing", terms=["oral kiss"]),
                 part("x1", "attribute", "tattoos", "excluded"), part("a3", "action", "kissing", "excluded")]
        brief = brief_of(answer([WOMAN, MAN], parts, avoid=["no oral"]), data)
        notes = " | ".join(brief["intent"]["warnings"])
        self.assertIn('"oral" is fixed here, but the request rules out "no oral"', notes)
        self.assertIn('"tattoos" is excluded here but not listed under avoid', notes)
        self.assertIn('"kissing" is both fixed and excluded', notes)
        self.assertIn('search word "oral kiss"', notes)
        self.assertEqual(brief["avoid"], ["no oral"])
        self.assertEqual([item["status"] for item in brief["intent"]["elements"]], ["fixed", "fixed", "fixed", "excluded", "excluded"])


class Calls(unittest.TestCase):
    """Only brief errors may retry; optional intent defects never regenerate the interpretation."""

    def setUp(self):
        self.backend, self.replies, self.prompts = MockBackend(), [], []
        self.enterContext(patch.object(self.backend, "generate", side_effect=self.generate))
        self.enterContext(patch.object(understanding, "create_backend", return_value=self.backend))
        self.trace = Mock()
        self.enterContext(patch.object(understanding, "DebugTrace", return_value=self.trace))
        self.config = {"backend": "mock"}
        self.request = GoatedPrompterRequest(idea="x", director_preset="general_director", planning_mode="Direct")
        self.data = draft("A woman kisses a man's neck while he reads, in different locations")

    def generate(self, instruction):
        self.prompts.append(instruction)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)

    def understand(self):
        return understanding.understand(self.config, self.request, self.data, progress=lambda _message: None)

    def test_the_one_call_asks_for_intent_with_room_for_it(self):
        self.replies = [answer([WOMAN, MAN], NECK)]
        brief = self.understand()
        self.assertEqual(len(self.prompts), 1)
        prompt = self.prompts[0]
        self.assertEqual((prompt.max_tokens, prompt.hard_max_tokens), (3072, 3072))
        self.assertIn("intent", prompt.json_schema["required"])
        self.assertIn("Never add objects, actions, details or\n      links because they are plausible", prompt.system_message)
        self.assertTrue(brief["intent"]["available"])

    def test_an_invalid_optional_binding_is_unavailable_without_changing_the_rest(self):
        broken = answer([WOMAN, MAN], [*NECK, part("a9", "action", "reads", by=["e1"])])
        self.replies = [broken, answer([WOMAN, MAN], NECK)]
        brief = self.understand()
        self.assertEqual(len(self.prompts), 1)
        items = {item["id"]: item for item in brief["intent"]["elements"]}
        self.assertEqual(items["a9"]["by"], [])
        self.assertEqual((items["a1"]["by"], items["a1"]["to"], items["b1"]["of"]), (["s1"], ["b1"], "s2"))
        self.assertTrue(any("a9.by" in note and "unavailable" in note.lower() for note in brief["intent"]["warnings"]))
        self.assertTrue(brief["intent"]["available"])

    def test_unusable_core_intent_leaves_the_first_brief_without_details_and_without_retry(self):
        broken = answer([WOMAN, MAN], [*NECK, part("a9", "unknown", "reads")])
        self.replies = [broken, deepcopy(broken)]
        brief = self.understand()
        self.assertEqual(len(self.prompts), 1, "no model repair of optional intent")
        self.assertFalse(brief["intent"]["available"])
        self.assertIn("Structured details are unavailable", brief["intent"]["warnings"][0])
        self.assertEqual((brief["summary"], brief["fixed"], brief["must"], brief["avoid"]),
                         ("A scene", "The people and the action", [], []), "the rest of the brief is intact")
        self.assertEqual([person["label"] for person in brief["characters"]], ["woman", "man"])
        understanding.validate_brief(brief)

    def test_an_answer_without_intent_keeps_the_brief_without_another_call(self):
        old = answer([WOMAN, MAN], NECK)
        del old["intent"]
        self.replies = [old, deepcopy(old)]
        brief = self.understand()
        self.assertEqual(len(self.prompts), 1)
        self.assertFalse(brief["intent"]["available"])

    def test_a_reply_cut_off_by_the_token_limit_is_repaired_and_two_fail_as_before(self):
        whole = json.dumps(answer([WOMAN, MAN], NECK))
        self.replies = [whole[:len(whole) // 2], whole]
        self.assertTrue(self.understand()["intent"]["available"])
        self.assertIn("complete and compact", self.prompts[1].system_message)
        self.prompts, self.replies = [], [whole[:400], whole[:900]]
        with self.assertRaisesRegex(ValueError, "invalid answer twice"):
            self.understand()

    def test_a_brief_error_still_fails_as_before_whatever_the_intent(self):
        bad = answer([], NECK, path="nonsense")
        self.replies = [bad, deepcopy(bad)]
        with self.assertRaisesRegex(ValueError, "invalid answer twice"):
            self.understand()


class Compatibility(unittest.TestCase):

    def v9(self):
        brief = brief_of(answer([WOMAN, MAN], NECK), draft("A woman kisses a man's neck while he reads"))
        old = {key: value for key, value in brief.items() if key != "intent"}
        old["version"] = 9
        return brief, old

    def test_both_versions_validate_and_mixing_them_does_not(self):
        brief, old = self.v9()
        understanding.validate_brief(old)
        understanding.validate_brief(brief)
        with self.assertRaises(ValueError):
            understanding.validate_brief({**old, "intent": brief["intent"]})
        with self.assertRaises(ValueError):
            understanding.validate_brief({key: value for key, value in brief.items() if key != "intent"})
        with self.assertRaises(ValueError):
            understanding.validate_brief({**brief, "version": 11})

    def test_retrieval_reads_v9_and_v10_briefs_the_same_way(self):
        brief, old = self.v9()
        self.assertEqual(RetrievalRequest.from_brief(brief), RetrievalRequest.from_brief({**old, "version": 9}))

    def test_saved_runs_with_v9_briefs_stay_readable_and_are_not_rewritten(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        store = runs.DatasetRunStore(root)
        _brief, old = self.v9()
        record = store.create("job-1", old, packs={"version": 1, "enabled": False, "selected": [], "packs": []})
        path = root / f"{record['run_id']}.json"
        before = path.read_bytes()
        self.assertEqual(store.get(record["run_id"])["brief"]["version"], 9)
        legacy = {key: value for key, value in json.loads(before).items() if key != "packs"}
        legacy.update(schema=1, run_id="4" * 32)
        (root / f"{'4' * 32}.json").write_text(json.dumps(legacy), encoding="utf-8")
        self.assertEqual(store.get("4" * 32)["brief"]["version"], 9)
        self.assertEqual(path.read_bytes(), before)

    def test_adults_only_checks_also_read_the_structured_details(self):
        data = draft("Two adults on a sofa", nsfw=True)
        for parts in ([part("s1", "subject", "adults", terms=["schoolgirl"])],
                      [part("s1", "subject", "adults"), part("o1", "object", "teen magazine", "optional", terms=["comic"])]):
            with self.subTest(parts=parts), self.assertRaises(ValueError) as caught:
                brief_of(answer([WOMAN, MAN], parts), data)
            self.assertIn("only show adults", str(caught.exception))
            self.assertIn("is in the structured details", str(caught.exception))
            self.assertIn("not in your own wording", str(caught.exception))

    def test_a_flagged_word_in_the_request_keeps_the_request_message(self):
        data = draft("Two adults dressed as a schoolgirl and a teacher", nsfw=True)
        parts = [part("s1", "subject", "adults", terms=["schoolgirl"])]
        with self.assertRaises(ValueError) as caught:
            brief_of(answer([WOMAN, MAN], parts), data)
        self.assertIn("only show adults", str(caught.exception))
        self.assertNotIn("structured details", str(caught.exception))

    def test_a_search_word_added_at_confirmation_is_blocked_too(self):
        data = draft("Two adults on a sofa", nsfw=True)
        brief = brief_of(answer([WOMAN, MAN], [part("s1", "subject", "adults")]), data)
        brief["intent"]["elements"][0]["terms"] = ["schoolgirl"]
        with self.assertRaisesRegex(ValueError, "is in the structured details"):
            understanding.confirm(brief, data)

    def test_structured_details_never_make_a_request_adult(self):
        data = draft("Two people on a sofa")
        parts = [part("s1", "subject", "people", terms=["nude", "sex"]),
                 part("a1", "action", "lying down", "randomized", "suggested", terms=["sex", "erotic"])]
        brief = brief_of(answer([WOMAN, MAN], parts), data)
        self.assertFalse(brief["input"]["nsfw"])
        self.assertNotEqual(brief["path"], "nsfw_character")
        self.assertFalse(RetrievalRequest.from_brief(brief).nsfw)
        self.assertEqual(understanding.confirm(brief, data), brief)
        without = brief_of(answer([WOMAN, MAN], [part("s1", "subject", "people")]), data)
        self.assertEqual(brief["path"], without["path"])


class Review(unittest.TestCase):
    """Corrections at confirmation: checked again on the server, never trusted, never rewritten."""

    def setUp(self):
        self.data = draft("A woman kisses a man's neck while he reads; she is behind him, in different locations")
        relations = [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}]
        self.brief = brief_of(answer([WOMAN, MAN], NECK, relations, unresolved=["which room"]), self.data)

    def edit(self, change):
        submitted = deepcopy(self.brief)
        change(submitted["intent"])
        return understanding.reviewed_brief(self.brief, submitted)

    def element(self, intent_value, ident):
        return next(item for item in intent_value["elements"] if item["id"] == ident)

    def test_unchanged_is_the_approved_brief(self):
        self.assertIs(understanding.reviewed_brief(self.brief, deepcopy(self.brief)), self.brief)

    def test_search_terms_links_suggestions_and_notes_can_be_corrected(self):
        def change(value):
            self.element(value, "a1")["terms"] = ["kiss", "neck kiss", "peck"]
            self.element(value, "a2")["by"] = ["s1"]
            value["elements"] = [item for item in value["elements"] if item["id"] != "k1"]
            value["relations"][0].update(a="s2", b="s1")
            value["unresolved"] = []
        reviewed = self.edit(change)
        self.assertEqual(self.element(reviewed["intent"], "a1")["terms"], ["kiss", "neck kiss", "peck"])
        self.assertEqual(self.element(reviewed["intent"], "a2")["by"], ["s1"])
        self.assertNotIn("k1", [item["id"] for item in reviewed["intent"]["elements"]])
        self.assertEqual((reviewed["intent"]["relations"][0]["a"], reviewed["intent"]["unresolved"]), ("s2", []))
        self.assertEqual({key: value for key, value in reviewed.items() if key != "intent"},
                         {key: value for key, value in self.brief.items() if key != "intent"}, "the authoritative brief is unchanged")
        understanding.validate_brief(reviewed)

    def test_what_the_request_states_cannot_be_changed_here(self):
        refused = {
            "set by your request": lambda value: self.element(value, "a1").update(status="optional"),
            "The text of": lambda value: self.element(value, "a1").update(text="hugs"),
            "The kind of": lambda value: self.element(value, "e1").update(kind="aspect"),
            "comes from your request, so it stays": lambda value: value.update(
                elements=[item for item in value["elements"] if item["id"] != "a2"]),
            "not added": lambda value: value["elements"].append({**self.element(value, "a2"), "id": "a9"}),
            "not added or removed": lambda value: value.update(relations=[]),
            "wording and status of the link": lambda value: value["relations"][0].update(rel="beside"),
            "not written": lambda value: value.update(unresolved=["a new note"]),
            "decided by the analysis": lambda value: value.update(truncated=True),
        }
        for expected, change in refused.items():
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    self.edit(change)

    def test_edits_cannot_contradict_avoid_or_break_links(self):
        self.brief = brief_of(answer([WOMAN, MAN], NECK, avoid=["no biting"]), self.data)
        with self.assertRaisesRegex(ValueError, 'matches "no biting"'):
            self.edit(lambda value: self.element(value, "a1").update(terms=["biting"]))
        with self.assertRaisesRegex(ValueError, "by must list subjects"):
            self.edit(lambda value: self.element(value, "a2").update(by=["b1"]))
        with self.assertRaisesRegex(ValueError, "one of the characters labels"):
            self.edit(lambda value: self.element(value, "s1").update(character="elf"))

    def test_the_server_recomputes_casts_and_warnings_from_the_browser_edit(self):
        def change(value):
            value["warnings"] = []
            self.element(value, "s1")["cast"] = ["woman", "intruder"]
            self.element(value, "a1")["terms"] = ["kiss"]
        reviewed = self.edit(change)
        self.assertEqual(self.element(reviewed["intent"], "s1")["cast"], ["woman"])
        self.assertEqual(reviewed["intent"]["warnings"], self.brief["intent"]["warnings"])
        with self.assertRaisesRegex(ValueError, '"man" is 1 person but has 2 subject parts'):
            self.edit(lambda value: self.element(value, "s1").update(character="man"))

    def test_any_other_change_to_the_brief_is_refused_as_before(self):
        submitted = deepcopy(self.brief)
        submitted["must"] = ["something new"]
        with self.assertRaisesRegex(ValueError, "The brief changed after analysis"):
            understanding.reviewed_brief(self.brief, submitted)

    def test_an_unavailable_intent_cannot_be_edited(self):
        old = answer([WOMAN, MAN], NECK)
        del old["intent"]
        self.brief = brief_of(old, self.data)
        with self.assertRaisesRegex(ValueError, "nothing to edit"):
            self.edit(lambda value: value["warnings"].append("forged"))


class Budget(unittest.TestCase):
    """Rough output sizes against the 3,072-token cap (about 3 characters per token for compact JSON)."""

    @staticmethod
    def tokens(value):
        return len(json.dumps(value, separators=(",", ":"))) / 3

    def test_typical_and_complex_answers_fit_the_cap_and_a_maximal_one_does_not(self):
        typical = answer([WOMAN, MAN], NECK, [{"a": "s1", "rel": "behind", "b": "s2", "status": "fixed"}])
        worst = answer([{"label": f"person {number}", "gender": "custom", "custom": "x" * 40, "pronoun": "it", "count": 1}
                        for number in range(5)],
                       [part(f"p{number}", "action", "w" * 60, by=["p0"], to=["p1"], input=1, terms=["t" * 30] * 3)
                        for number in range(24)],
                       [{"a": "p0", "rel": "r" * 60, "b": "p1", "status": "fixed"}] * 12,
                       unresolved=["n" * 150] * 6, summary="s" * 600, fixed="f" * 1200, randomized="r" * 600,
                       must=["m" * 80] * 10, avoid=["a" * 80] * 10)
        complex_ = answer([{"label": f"person {number}", "gender": "female", "custom": "", "pronoun": "she", "count": 1}
                           for number in range(5)],
                          [part(f"p{number}", "action", "holds the red ribbon", by=["p0"], to=["p1"], terms=["grip", "hold"])
                           for number in range(20)],
                          [{"a": "p0", "rel": "next to", "b": "p1", "status": "fixed"}] * 8,
                          unresolved=['who "she" is in the second sentence'] * 2, summary="s" * 200, fixed="f" * 400,
                          randomized="r" * 200, must=["m" * 40] * 4, avoid=["a" * 30] * 4)
        self.assertLess(self.tokens(typical), 600)
        self.assertLess(self.tokens(complex_), 3072)
        # Every field at its limit would not fit: such a reply is cut off, and the repair asks for a compact intent
        # with truncated set (Calls.test_a_reply_cut_off_by_the_token_limit_is_repaired_and_two_fail_as_before).
        self.assertGreater(self.tokens(worst), 3072)
