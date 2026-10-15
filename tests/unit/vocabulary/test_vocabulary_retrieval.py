"""Phase 4: vocabulary retrieval. Real core, fixture packs, and a temporary "studio" pack per test run."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, build_registry, read_pack
from goated_prompter.features.vocabulary.retrieval import (
    RetrievalConfig, RetrievalRequest, VocabularyIndex, retrieve)
from goated_prompter.features.vocabulary.semantic import split_negated, stem

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "packs"
ROOT = Path(__file__).resolve().parents[3]


def being(count=1):
    return {"count": count, "kind": "being"}


def standing(**extra):
    return {"posture": "core:posture.standing", **extra}


STUDIO = [
    {"id": "studio:body.person", "category": "body", "name": "Person", "aliases": ["person", "human", "man", "woman"],
     "description": "An ordinary adult human.", "extends": ["core:body.humanoid"],
     "components": {"body": {"complete_for": ["core:locomotion"]}}},
    {"id": "studio:action.embrace", "category": "action", "name": "Embrace", "aliases": ["hug", "cuddle"],
     "description": "Two people with their arms wrapped around each other.", "components": {
         "participants": {"slots": {"a": being(), "b": being()}},
         "requirements": {"participants": {"a": {"all_of": ["core:limb.arm"]}, "b": {"all_of": ["core:limb.arm"]}}},
         "spatial": {"participants": {"a": standing(facing={"toward": "b"}, anchors=[{"relation": "in_front", "of": "b", "distance": "contact"}]),
                                      "b": standing(facing={"toward": "a"})},
                     "access": [{"from": "a", "using": "core:limb.hand", "to": "b", "regions": ["core:anatomy.back"], "kind": "touch"}]}}},
    {"id": "studio:gesture.wave", "category": "gesture", "name": "Wave hello", "aliases": ["greeting wave"],
     "description": "Raises one hand and waves it from side to side.", "components": {
         "participants": {"slots": {"actor": being()}},
         "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "shared", "purpose": "use"}]}}},
    {"id": "studio:gesture.wave_greeting", "category": "gesture", "name": "Wave a greeting",
     "description": "Raises one hand and waves it from side to side as a greeting.", "components": {
         "participants": {"slots": {"actor": being()}},
         "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "shared", "purpose": "use"}]}}},
    {"id": "studio:gesture.bow", "category": "gesture", "name": "Bow", "description": "Bends forward at the waist to show respect.",
     "components": {"participants": {"slots": {"actor": being()}}, "spatial": {"participants": {"actor": standing()}}}},
    {"id": "studio:gesture.deep_bow", "category": "gesture", "name": "Deep bow", "extends": ["studio:gesture.bow"],
     "description": "Bows low with one hand pressed over the heart.", "components": {
         "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "contact"}]}}},
    {"id": "studio:item.handbag", "category": "item", "name": "Handbag", "aliases": ["purse"],
     "description": "A small bag carried by its strap.", "components": {"object": {"provides": ["core:item.handheld"], "hands": 1}}},
    {"id": "studio:position.lap_sit", "category": "position", "name": "Sitting on a lap", "aliases": ["lap sitting"],
     "description": "One person sits across the other's thighs, facing them.", "components": {
         "participants": {"slots": {"seated": being(), "base": being()}},
         "spatial": {"participants": {"seated": {"posture": "core:posture.sitting", "facing": {"toward": "base"},
                                                 "anchors": [{"relation": "on", "of": "base", "distance": "contact"}]},
                                      "base": {"posture": "core:posture.sitting"}}}}},
    {"id": "studio:position.lap_sit_reverse", "category": "position", "name": "Reverse lap sit",
     "description": "Sitting on a lap, facing away.", "extends": ["studio:position.lap_sit"], "components": {}},
    {"id": "studio:position.aerial_carry", "category": "position", "name": "Aerial carry",
     "description": "One flies while holding the other in their arms.", "components": {
         "participants": {"slots": {"carrier": being(), "carried": being()}},
         "requirements": {"participants": {"carrier": {"all_of": ["core:locomotion.flight"]}}}}},
    {"id": "studio:space.sofa", "category": "space", "name": "Sofa", "aliases": ["couch", "settee"],
     "description": "A padded seat for two or three people.", "components": {"environment": {"provides": ["core:surface.wide"]}}},
    {"id": "studio:action.duel", "category": "action", "name": "Sword duel", "rating": "mature",
     "description": "Two fighters cross blades.", "components": {
         "participants": {"slots": {"a": being(), "b": being()}},
         "requirements": {"participants": {"a": {"all_of": ["core:limb.hand"]}, "b": {"all_of": ["core:limb.hand"]}}}}},
    {"id": "studio:item.wand_toy", "category": "item", "name": "Wand toy", "aliases": ["wand"],
     "extends": ["adult:item.dildo"], "components": {}},
]


def studio_folder(root):
    folder = root / "studio"
    folder.mkdir()
    manifest = {"spec": 1, "id": "studio", "name": "Studio", "version": "1.0.0", "rating": "general",
                "requires": {"core": ">=1.0.0", "fantasy": ">=0.1.0", "adult": ">=0.1.0"},
                "categories": [{"id": "gesture", "name": "Gestures"}], "files": ["entries.json"]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "entries.json").write_text(json.dumps({"spec": 1, "entries": STUDIO}), encoding="utf-8")
    return folder


def registry(*names, order=None):
    """core plus the named packs (fantasy, adult, studio), optionally read in another order."""
    root = Path(tempfile.mkdtemp())
    try:
        folders = {"fantasy": FIXTURES / "fantasy", "adult": FIXTURES / "adult", "studio": studio_folder(root)}
        packs = [read_pack(folders[name], bundled=False) for name in (order or names)]
        return build_registry([read_pack(BUNDLED_DIRS[0], bundled=True), *packs])
    finally:
        shutil.rmtree(root, ignore_errors=True)


ALL = VocabularyIndex(registry("fantasy", "adult", "studio"))
PEOPLE = ({"label": "Woman 1", "gender": "female", "custom": "woman", "pronoun": "she"},
          {"label": "Man 1", "gender": "male", "custom": "man", "pronoun": "he"})


def ask(text, index=ALL, config=None, **extra):
    extra.setdefault("characters", PEOPLE)
    return retrieve(index, RetrievalRequest(request=text, **extra), config)


def ids(found):
    return [entry.id for entry in found.entries]


def brief(request, **changes):
    value = {"version": 9, "path": "sfw_character", "summary": request, "people": 2, "characters": list(PEOPLE),
             "fixed": "", "randomized": "", "must": [], "avoid": [],
             "input": {"request": request, "trigger": "", "trigger_at_start": False, "rules": [], "amount": 4, "nsfw": False},
             "settings": {"style": "", "target": "", "director": "", "length": "", "creativity": "Balanced"}}
    value.update(changes)
    return value


class SemanticRelevance(unittest.TestCase):
    def test_aliases_and_word_forms(self):
        self.assertEqual(ids(ask("two friends hugging after a long trip"))[0], "studio:action.embrace")
        self.assertEqual(ids(ask("they embraced"))[0], "studio:action.embrace")
        found = ask("cuddling on the couch")
        self.assertEqual(set(ids(found)) >= {"studio:action.embrace", "studio:space.sofa"}, True, ids(found))
        sofa = next(entry for entry in found.entries if entry.id == "studio:space.sofa")
        self.assertTrue(any('"couch"' in reason for reason in sofa.why), sofa.why)

    def test_descriptions_are_weak_evidence(self):
        # Part C: words shared with a description name nothing; the match is reported, never used as a request.
        found = ask("arms wrapped around each other")
        self.assertNotIn("studio:action.embrace", ids(found))
        self.assertIn("studio:action.embrace", [item["id"] for item in found.intent["rejected"]])
        self.assertEqual(ids(ask("two friends hugging"))[0], "studio:action.embrace", "its declared alias still names it")

    def test_capability_links_alone_name_nothing(self):
        # Part C: what an entry provides decides compatibility, not what the request asks for.
        found = ask("somewhere wide to lie on")
        self.assertNotIn("studio:space.sofa", ids(found), "the sofa provides a wide surface, but nothing names it")
        self.assertEqual(found.intent["fixed"], {})

    def test_partial_names_and_shared_capabilities_name_nothing(self):
        # Part C: "casting a spell" is part of "Cast a spell on someone", not the whole name; the full name names it.
        cast = ({"label": "Mage", "gender": "custom", "custom": "spellcaster"}, {"label": "Foe", "gender": "custom", "custom": "dragon"})
        self.assertNotIn("fantasy:action.cast_on", ids(ask("a mage casting a spell", characters=cast)))
        self.assertEqual(ids(ask("a mage, cast a spell on someone", characters=cast))[0], "fantasy:action.cast_on")
        toys = ask("a woman using a dildo on her partner", nsfw=True)
        self.assertIn("adult:item.dildo", ids(toys))
        self.assertNotIn("adult:action.toy_insert", ids(toys), "an object is no requested action")

    def test_morphology(self):
        self.assertEqual({stem(word) for word in ("kneel", "kneels", "kneeling", "kneeled")}, {"kneel"})
        self.assertEqual({stem(word) for word in ("use", "uses", "using", "used")}, {"use"})
        self.assertEqual(split_negated("hugging, no toys or rope, and a sofa"), (["hug", "sofa"], ["toy", stem("rope")]))

    def test_irregular_word_forms(self):
        self.assertEqual({stem(word) for word in ("lie", "lies", "lying")}, {stem("lie")})
        self.assertEqual({stem(word) for word in ("tie", "ties", "tied", "tying")}, {stem("tie")})
        self.assertEqual({stem(word) for word in ("speed", "speeds", "speeding")}, {stem("speed")})
        self.assertEqual({stem(word) for word in ("bleed", "bleeds", "bleeding")}, {stem("bleed")})
        self.assertEqual(stem("seated"), stem("seat"))
        self.assertIn("studio:space.sofa", ids(ask("lying on a settee")), "an alias in another word form names it")

    def test_negation_scope_ends_at_a_new_verb(self):
        self.assertEqual(split_negated("a man with no shirt cuddling a woman"), (["man", "cuddl", "woman"], ["shirt"]))
        self.assertEqual(split_negated("no kneeling"), ([], [stem("kneeling")]))
        self.assertEqual(split_negated("no toys or kneeling"), ([], ["toy", stem("kneeling")]))
        self.assertEqual(ids(ask("a woman without shoes hugging a man"))[0], "studio:action.embrace")
        self.assertNotIn("core:position.from_behind", ids(ask("two people hugging, no toys or kneeling from behind")))


class CrossPack(unittest.TestCase):
    def test_one_request_draws_on_several_packs(self):
        found = ask("a winged woman in an aerial carry of a man, then they hug",
                    characters=({"label": "Woman 1", "gender": "female", "custom": "winged woman"}, PEOPLE[1]))
        packs = {entry.pack for entry in found.entries}
        self.assertIn("studio", packs)
        self.assertIn("studio:position.aerial_carry", ids(found))
        self.assertEqual(found.cast[0]["body"], "studio:body.person")
        self.assertIn("fantasy:trait.wings", found.cast[0]["traits"], "body and trait come from different packs")

    def test_a_category_the_code_never_heard_of(self):
        found = ask("she waves hello")
        self.assertIn(ids(found)[0], ("studio:gesture.wave", "studio:gesture.wave_greeting"))
        self.assertEqual(found.entries[0].category, "gesture")

    def test_disabled_packs_are_not_searched(self):
        without = VocabularyIndex(registry("fantasy", "adult"))
        self.assertNotIn("studio", {entry.pack for entry in ask("two friends hugging", index=without).entries})
        self.assertNotIn("studio", {entry.pack for entry in ask("a mage casting a spell", index=without).entries})


class Ratings(unittest.TestCase):
    def test_nsfw_off_allows_general_and_mature_only(self):
        found = ask("a sword duel")
        self.assertIn("studio:action.duel", ids(found), "mature is allowed with NSFW off")
        sfw = ask("a woman using a dildo on her partner")
        self.assertFalse([entry for entry in sfw.entries if entry.rating == "adult"])
        self.assertIn("adult:item.dildo", {item["id"] for item in sfw.excluded})
        self.assertEqual(sfw.render(), "")

    def test_inherited_rating_is_respected(self):
        sfw = ask("a wand toy")
        self.assertNotIn("studio:item.wand_toy", ids(sfw), "the studio pack is general, but the entry inherits adult")
        nsfw = ask("a wand toy", nsfw=True)
        self.assertIn("studio:item.wand_toy", ids(nsfw))

    def test_explicit_allowed_ratings_override_the_switch(self):
        found = ask("a sword duel", config=RetrievalConfig(allowed_ratings=("general",)))
        self.assertNotIn("studio:action.duel", ids(found))

    def test_brief_switch_decides(self):
        request = RetrievalRequest.from_brief(brief("a woman using a dildo", path="nsfw_character",
                                                    input={**brief("x")["input"], "request": "a woman using a dildo", "nsfw": True}))
        self.assertTrue(request.nsfw)
        self.assertIn("adult:item.dildo", ids(retrieve(ALL, request)))


class Compatibility(unittest.TestCase):
    CARRY = "a woman doing an aerial carry of a man in her arms"

    def test_confirmed_conflicts_are_excluded(self):
        found = ask(self.CARRY)
        self.assertNotIn("studio:position.aerial_carry", ids(found))
        reason = next(item["reason"] for item in found.excluded if item["id"] == "studio:position.aerial_carry")
        self.assertIn("conflict", reason)
        self.assertIn("Woman 1", reason, "messages name characters as the brief does")

    def test_a_capable_cast_keeps_the_entry(self):
        found = ask(self.CARRY, characters=({"label": "Woman 1", "gender": "female", "custom": "winged woman"}, PEOPLE[1]))
        carry = next(entry for entry in found.entries if entry.id == "studio:position.aerial_carry")
        self.assertEqual(carry.binding, {"carried": ["Man 1"], "carrier": ["Woman 1"]})
        self.assertEqual(carry.status, "eligible", "requirements hold; placement is not declared")

    def test_feasible_carries_the_not_proof_note(self):
        hug = ask("two friends hugging").entries[0]
        self.assertEqual(hug.status, "feasible")
        self.assertIn("not proof", hug.note)
        self.assertIn("never that it is proven possible", ask("two friends hugging").render())

    def test_no_cast_means_no_positions(self):
        found = ask("two friends hugging", characters=())
        self.assertEqual(ids(found), [])
        self.assertIn("studio:action.embrace", {item["id"] for item in found.excluded})

    def test_spaces_are_checked_with_retrieved_positions(self):
        found = ask("two people sitting on a lap on the couch")
        sofa = next(entry for entry in found.entries if entry.id == "studio:space.sofa")
        self.assertEqual(sofa.status, "unknown", sofa.warnings)
        alone = ask("a couch")
        self.assertEqual(alone.entries[0].warnings, ["no retrieved position or action uses it, so it is not checked"])

    def test_unchosen_space_is_a_need_not_an_unknown_about_the_cast(self):
        found = ask("two people kneeling, one on all fours from behind", nsfw=True)
        behind = next(entry for entry in found.entries if entry.id == "core:position.from_behind")
        self.assertNotIn("core:position.from_behind", ids(ask("two people kneeling, one on all fours from behind")),
                         "the position is rated adult")
        self.assertEqual(behind.status, "feasible", behind.warnings)
        self.assertEqual(behind.needs, ["a space with: wide surface to kneel or lie on"])


class UnknownEntries(unittest.TestCase):
    # Custom characters no pack describes (plain male and female characters are humans; see CastFromTheBrief).
    UNDESCRIBED = ({"label": "Unit 1", "gender": "custom", "custom": "robot"}, {"label": "Unit 2", "gender": "custom", "custom": "robot"})

    def test_incomplete_vocabulary_keeps_the_entry_as_unknown(self):
        found = ask("two friends hugging", characters=self.UNDESCRIBED)
        hug = found.entries[0]
        self.assertEqual((hug.id, hug.status), ("studio:action.embrace", "unknown"))
        self.assertTrue(any("Unit 1" in warning or "Unit 2" in warning for warning in hug.warnings), hug.warnings)
        self.assertTrue(any("no vocabulary body matches" in warning for warning in found.warnings))
        self.assertEqual([member["body"] for member in found.cast], [None, None])

    def test_unknown_ranks_below_feasible_and_can_be_switched_off(self):
        people = ({"id": "ann", "body": "studio:body.person"}, {"id": "ben", "body": "studio:body.person"})
        blanks = ({"id": "ann", "body": None}, {"id": "ben", "body": None})
        known = ask("two friends hugging", characters=(), cast=people).entries[0]
        unknown = ask("two friends hugging", characters=(), cast=blanks).entries[0]
        self.assertEqual((known.status, unknown.status), ("feasible", "unknown"))
        self.assertAlmostEqual(known.relevance, unknown.relevance, places=6)
        self.assertLess(unknown.score, known.score)
        strict = ask("two friends hugging", characters=self.UNDESCRIBED, config=RetrievalConfig(include_unknown=False))
        self.assertEqual(ids(strict), [])


class Duplicates(unittest.TestCase):
    def test_aliases_never_duplicate_an_entry(self):
        found = ask("a hug, a cuddle, an embrace")
        self.assertEqual(ids(found).count("studio:action.embrace"), 1)

    def test_inherited_duplicates_are_suppressed(self):
        found = ask("sitting on a lap, reverse lap sit")
        chosen = [entry_id for entry_id in ids(found) if entry_id.startswith("studio:position.lap_sit")]
        self.assertEqual(len(chosen), 1, ids(found))
        self.assertTrue(any("inherited duplicate" in item["because"] for item in found.suppressed), found.suppressed)

    def test_equivalent_descendants_keep_the_better_match(self):
        # The reverse lap sit declares nothing beyond its parent: one of the two, whichever the request names.
        found = ask("sitting on a lap")
        self.assertIn("studio:position.lap_sit", ids(found))
        self.assertNotIn("studio:position.lap_sit_reverse", ids(found))
        # Part C: one word of "Reverse lap sit" names nothing; it extends the named entry, so it is related, not named.
        self.assertIn({"id": "studio:position.lap_sit_reverse", "why": "it extends Sitting on a lap, which the request names"},
                      found.intent["related"])
        both = ask("sitting on a lap, then a reverse lap sit")
        self.assertEqual(len([entry_id for entry_id in ids(both) if entry_id.startswith("studio:position.lap_sit")]), 1,
                         "naming both still keeps one of two equivalents")
        self.assertTrue(any("inherited duplicate" in item["because"] for item in both.suppressed), both.suppressed)

    def test_a_more_specific_descendant_is_not_suppressed_by_its_parent(self):
        # The deep bow extends the bow and declares more (a hand on the heart).
        found = ask("a polite bow to show respect, bending forward at the waist, then a deep bow")
        self.assertLess(ids(found).index("studio:gesture.bow"), ids(found).index("studio:gesture.deep_bow"), "the parent ranks first")
        self.assertFalse([item for item in found.suppressed if "bow" in item["id"]], found.suppressed)
        generic = ask("a bow")
        self.assertEqual([entry_id for entry_id in ids(generic) if "bow" in entry_id], ["studio:gesture.bow"])
        self.assertIn({"id": "studio:gesture.deep_bow", "why": "it extends Bow, which the request names"}, generic.intent["related"],
                      "the deeper variant is related to the named bow, not named itself")

    def test_a_generic_request_ranks_the_parent_first(self):
        def bows(text):
            return [entry_id for entry_id in ids(ask(text)) if entry_id.startswith("studio:gesture.") and "bow" in entry_id]
        self.assertEqual(bows("a bow"), ["studio:gesture.bow"], "one word of Deep bow names only the bow")
        self.assertEqual(bows("a deep bow"), ["studio:gesture.deep_bow"])
        self.assertEqual(set(bows("a polite bow and a deep bow")), {"studio:gesture.bow", "studio:gesture.deep_bow"},
                         "the request names the bow on its own as well")

    def test_a_better_matching_descendant_replaces_its_parent(self):
        found = ask("a deep bow")
        self.assertIn("studio:gesture.deep_bow", ids(found))
        self.assertNotIn("studio:gesture.bow", ids(found))
        reason = next(item["because"] for item in found.suppressed if item["id"] == "studio:gesture.bow")
        self.assertTrue(reason.startswith("covered by its more specific studio:gesture.deep_bow"), reason)

    def test_semantically_repetitive_entries_are_suppressed(self):
        found = ask("waving a greeting, wave hello")
        waves = [entry_id for entry_id in ids(found) if entry_id.startswith("studio:gesture.wave")]
        self.assertEqual(len(waves), 1, ids(found))
        self.assertTrue(any(item["because"].startswith("repeats") for item in found.suppressed), found.suppressed)


class Determinism(unittest.TestCase):
    TEXT = "two people hugging on a couch, then one kneels from behind; a sword duel; a mage casting a spell"

    def test_same_input_same_output(self):
        first = ask(self.TEXT).to_dict()
        self.assertEqual(ask(self.TEXT).to_dict(), first)
        rebuilt = VocabularyIndex(registry("studio", "adult", "fantasy", order=["fantasy", "adult", "studio"]))
        self.assertEqual(ask(self.TEXT, index=rebuilt).to_dict(), first)

    def test_hash_seed_does_not_change_the_ranking(self):
        script = ("import json, sys; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                  "import test_vocabulary_retrieval as t\n"
                  "print(json.dumps(t.ask(t.Determinism.TEXT).to_dict(), sort_keys=True))") % (str(ROOT), str(Path(__file__).parent))
        outputs = set()
        for seed in ("0", "1", "12345"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            outputs.add(subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(len(outputs), 1)


class SmallContext(unittest.TestCase):
    def test_limits_are_respected(self):
        config = RetrievalConfig(max_results=2, max_chars=300)
        found = ask(Determinism.TEXT, config=config)
        self.assertLessEqual(len(found.entries), 2)
        self.assertLessEqual(len(found.render()), 300)
        self.assertLessEqual(len(ask(Determinism.TEXT).entries), RetrievalConfig().max_results)
        self.assertLessEqual(len(ask(Determinism.TEXT).render(max_chars=200)), 200)

    def test_the_prompt_block_never_assigns_roles(self):
        text = ask("a winged woman flies while carrying a man",
                   characters=({"label": "Woman 1", "gender": "female", "custom": "winged woman"}, PEOPLE[1])).render()
        self.assertNotIn("carrier:", text)

    def test_variety_across_categories(self):
        found = ask("waving hello, a bow, a greeting wave, a polite bow", config=RetrievalConfig(max_per_category=1))
        self.assertEqual(len([entry for entry in found.entries if entry.category == "gesture"]), 1)


class Guidance(unittest.TestCase):
    def test_director_guidance_changes_the_ranking(self):
        def score(found, entry_id):
            return next(entry.score for entry in found.entries if entry.id == entry_id)
        text = "two people together, a hug or a sword duel"
        plain, guided = ask(text), ask(text, director="Favour tender moments: hugs and cuddles.")
        self.assertGreater(score(guided, "studio:action.embrace"), score(plain, "studio:action.embrace"))
        self.assertEqual(score(guided, "studio:action.duel"), score(plain, "studio:action.duel"))
        self.assertNotIn("studio:action.embrace", ids(ask("two companions at a party")))
        self.assertIn("studio:action.embrace", ids(ask("two companions at a party", director="Favour hugs.")))

    def test_director_boilerplate_never_brings_in_entries(self):
        # General words of a director's instructions match descriptions and categories of everything.
        director = "Describe the subject, the action and the composition, with one clear position for each person."
        self.assertEqual(ids(ask("a quiet afternoon", director=director)), [])
        self.assertEqual(set(ids(ask("two friends hugging", director=director))), {"studio:action.embrace", "core:action.hug"},
                         "only what the request names")
        self.assertIn("studio:action.embrace", ids(ask("two companions at a party", director="Favour hugs.")),
                      "a director that names an entry still guides retrieval")

    def test_the_request_outweighs_the_director(self):
        found = ask("a sword duel", director="Favour hugs.")
        self.assertEqual(ids(found)[0], "studio:action.duel")

    def test_avoid_rules_entries_out(self):
        # "cuddling" finds the embrace through an alias; the avoided "hugging" names it through another.
        found = retrieve(ALL, RetrievalRequest.from_brief(brief("two friends cuddling on a couch", avoid=["no hugging"])))
        self.assertNotIn("studio:action.embrace", ids(found))
        self.assertTrue(any(item["id"] == "studio:action.embrace" and "ruled out" in item["reason"] for item in found.excluded))
        negated = ask("two friends cuddling on a couch, no hugging")
        self.assertNotIn("studio:action.embrace", ids(negated))

    def test_negation_matches_whole_words_and_aliases_only(self):
        # "hand" is a prefix of "handbag"; ruling out hands must not rule out the bag.
        found = ask("a woman carrying a handbag, no hands visible")
        self.assertIn("studio:item.handbag", ids(found))
        self.assertNotIn("studio:item.handbag", {item["id"] for item in found.excluded})
        for text in ("a woman carrying a purse, no handbag", "a woman with a handbag, no purses"):
            with self.subTest(text=text):  # the name, and an alias in another word form
                reason = next(item["reason"] for item in ask(text).excluded if item["id"] == "studio:item.handbag")
                self.assertIn("ruled out by the request", reason)

    def test_director_negations_rule_nothing_out(self):
        # A director's standing "never"/"do not" instructions are not this request's exclusions.
        found = ask("a sword duel", director="Never add a duel or fight the user did not ask for.")
        self.assertEqual(ids(found)[0], "studio:action.duel")
        self.assertFalse(found.excluded)
        self.assertIn("studio:action.embrace", ids(ask("two friends hugging", style="no exaggerated hugs")))
        self.assertNotIn("studio:action.duel", ids(ask("two people together, no sword duel", director="Favour duels.")))


class EmptyFallback(unittest.TestCase):
    def test_no_packs(self):
        found = retrieve(None, RetrievalRequest(request="two friends hugging"))
        self.assertEqual((found.entries, found.render()), ([], ""))
        self.assertEqual(found.warnings, ["no vocabulary packs are enabled"])

    def test_nothing_relevant(self):
        for text in ("a red sports car on a mountain road at dusk", "", "the and of"):
            with self.subTest(text=text):
                found = ask(text, characters=())
                self.assertEqual((found.entries, found.render()), ([], ""))

    def test_core_only_and_non_character_briefs(self):
        core = VocabularyIndex(build_registry([read_pack(BUNDLED_DIRS[0], bundled=True)]))
        found = retrieve(core, RetrievalRequest.from_brief(brief("a perfume bottle on marble", path="non_character", characters=[], people=0)))
        self.assertEqual(found.render(), "")

    def test_matching_characters_alone_pull_in_nothing(self):
        found = ask("a quiet afternoon")
        self.assertEqual(ids(found), [], "the cast matches the person body; that alone is not scene vocabulary")
        self.assertEqual([member["body"] for member in found.cast], ["studio:body.person", "studio:body.person"])

    def test_malformed_brief_is_reported(self):
        with self.assertRaises(ValueError):
            RetrievalRequest.from_brief({"summary": "x"})


if __name__ == "__main__":
    unittest.main()
