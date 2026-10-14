"""Phase 6A: the production vocabulary (bundled core, vocabulary/packs/fantasy, vocabulary/packs/adult).

These tests load the real pack folders through the real loader, resolver and retrieval. They check
what the data knows, how it is found from ordinary words, its ratings, and that ordinary requests are
not given unrelated suggestions.
"""

import json
import unittest
from pathlib import Path

from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, build_registry, read_pack
from goated_prompter.features.vocabulary.resolver import candidate_bindings, resolve
from goated_prompter.features.vocabulary.retrieval import RetrievalConfig, RetrievalRequest, VocabularyIndex, retrieve
from goated_prompter.features.vocabulary.semantic import terms

ROOT = Path(__file__).resolve().parents[3]
PACKS = ROOT / "vocabulary" / "packs"
CORE = read_pack(BUNDLED_DIRS[0], bundled=True)
FANTASY = read_pack(PACKS / "fantasy", bundled=False)
ADULT = read_pack(PACKS / "adult", bundled=False)
REGISTRY = build_registry([CORE, FANTASY, ADULT])
INDEX = VocabularyIndex(REGISTRY)
GENERAL_DIRECTOR = ("Act as a disciplined general visual director. Convert the current task into one coherent, production-ready "
                    "prompt whose subject, action or state, environment, spatial relationships, composition, viewpoint, materials, "
                    "lighting, color behavior, depth, and medium agree with one another.")

WOMAN = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she"}
MAN = {"label": "man", "gender": "male", "custom": "", "pronoun": "he"}


def creature(label, custom):
    return {"label": label, "gender": "custom", "custom": custom, "pronoun": "it"}


def ask(text, characters=(WOMAN, MAN), nsfw=False, director=GENERAL_DIRECTOR, **extra):
    return retrieve(INDEX, RetrievalRequest(request=text, summary=text, characters=tuple(characters), nsfw=nsfw,
                                            director=director, **extra))


def ids(found):
    return [entry.id for entry in found.entries]


def status(found, entry_id):
    return next(entry.status for entry in found.entries if entry.id == entry_id)


def bodies(found):
    return [member["body"] for member in found.cast]


class Packs(unittest.TestCase):
    def test_three_packs_load_with_their_dependencies(self):
        self.assertEqual((CORE.manifest["version"], FANTASY.manifest["version"], ADULT.manifest["version"]),
                         ("1.1.0", "1.0.0", "1.0.0"))
        for pack in (FANTASY, ADULT):
            self.assertEqual(pack.manifest["requires"], {"core": ">=1.1.0 <2.0.0"})
        self.assertLessEqual(len(REGISTRY.ids()), 150, "a minimal set, not a catalogue")

    def test_ratings(self):
        for entry_id in REGISTRY.ids():
            rating = REGISTRY.resolved(entry_id).get("rating", "general")
            with self.subTest(entry=entry_id):
                if REGISTRY.owner(entry_id) == "adult" or entry_id == "core:position.from_behind":
                    self.assertEqual(rating, "adult")
                else:
                    self.assertEqual(rating, "general")

    def test_no_duplicate_names_or_aliases(self):
        seen = {}
        for entry_id in sorted(REGISTRY.ids()):
            if INDEX.kind[entry_id] == "concept":
                continue  # a capability shares the words of what provides it and is never offered
            entry = REGISTRY.entry(entry_id)
            for text in [entry["name"], *entry.get("aliases", [])]:
                key = tuple(terms(text))
                with self.subTest(entry=entry_id, text=text):
                    self.assertNotIn(key, seen, f"also {seen.get(key)}")
                    seen[key] = entry_id

    def test_entries_are_knowledge_not_scene_prompts(self):
        for entry_id in REGISTRY.ids():
            description = REGISTRY.entry(entry_id).get("description", "")
            with self.subTest(entry=entry_id):
                self.assertLessEqual(len(description), 200)
                self.assertNotIn("\n", description)


class Inheritance(unittest.TestCase):
    def test_bodies_reuse_core_body_plans(self):
        human = REGISTRY.resolved("core:body.human")["components"]["body"]
        self.assertIn("hand.left", human["resources"])
        self.assertIn("core:locomotion.biped", human["provides"])
        elf = REGISTRY.resolved("fantasy:body.elf")["components"]["body"]
        self.assertEqual(set(elf["resources"]), set(human["resources"]))
        dragon = REGISTRY.resolved("fantasy:body.dragon")["components"]["body"]
        self.assertIn("back", dragon["resources"], "from core:body.vertebrate")
        self.assertNotIn("hand.left", dragon["resources"])

    def test_identity_is_independent_of_anatomy(self):
        human = REGISTRY.resolved("core:body.human")["components"]["body"]
        self.assertFalse({"penis", "vagina", "breasts"} & set(human["resources"]))
        self.assertNotIn("core:anatomy", human["complete_for"], "anatomy stays undeclared, never absent")
        for word in ("male", "female"):
            self.assertNotIn(word, REGISTRY.entry("core:body.human")["aliases"],
                             "a 'female dragon' must not gain a human body")

    def test_reverse_cowgirl_inherits_and_overrides(self):
        resolved = REGISTRY.resolved("adult:position.reverse_cowgirl")["components"]
        self.assertEqual(set(resolved["participants"]["slots"]), {"rider", "partner"})
        rider = resolved["spatial"]["participants"]["rider"]
        self.assertEqual(rider["posture"], "core:posture.straddling")
        self.assertEqual(rider["facing"], {"away_from": "partner"})
        self.assertEqual(REGISTRY.resolved("adult:position.reverse_cowgirl")["rating"], "adult")


class Compatibility(unittest.TestCase):
    """What the data lets the resolver say, and what it deliberately leaves unknown."""

    def test_a_human_rides_a_dragon(self):
        cast = [{"id": "knight", "body": "core:body.human"}, {"id": "dragon", "body": "fantasy:body.dragon"}]
        found = list(candidate_bindings(REGISTRY, "core:position.riding", cast))
        verdicts = {bind["rider"]: result.status for bind, result in found}
        self.assertEqual(verdicts["knight"], "feasible")
        self.assertEqual(verdicts["dragon"], "conflict", "a human is not a mount")

    def test_humans_do_not_fly_but_winged_ones_do(self):
        human = ask("a man flying over the city", characters=(MAN,))
        self.assertNotIn("core:posture.flying", ids(human))
        self.assertTrue(any(item["id"] == "core:posture.flying" and "conflict" in item["reason"] for item in human.excluded))
        winged = ask("a winged elf flying over the city", characters=(creature("elf", "winged elf"),))
        self.assertEqual(status(winged, "core:posture.flying"), "feasible")

    def test_unstated_anatomy_is_unknown_never_conflict(self):
        found = ask("a woman giving a blowjob", nsfw=True)
        self.assertEqual(status(found, "adult:action.oral"), "unknown")
        found = ask("a dragon holding a sword", characters=(creature("dragon", "dragon"),))
        self.assertEqual(status(found, "core:action.hold"), "unknown", "claws are undeclared, not handless")

    def test_restrained_hands_cannot_hold(self):
        cast = [{"id": "a", "body": "core:body.human"}]
        objects = [{"id": "cuffs", "item": "adult:item.handcuffs"}, {"id": "toy", "item": "adult:item.vibrator"}]
        both = resolve(REGISTRY, {"cast": cast, "objects": objects, "use": [
            {"entry": "adult:action.restrained", "bind": {"bound": "a", "restraint": "cuffs"}},
            {"entry": "adult:action.toy_play", "bind": {"user": "a", "toy": "toy"}}]})
        self.assertEqual(both.status, "conflict")
        shared = resolve(REGISTRY, {"cast": cast, "objects": objects[1:], "use": [
            {"entry": "core:action.hold", "bind": {"holder": "a", "item": "toy"}},
            {"entry": "adult:action.toy_play", "bind": {"user": "a", "toy": "toy"}}]})
        self.assertNotEqual(shared.status, "conflict", "holding the toy and using it share one hand")

    def test_a_spell_needs_a_caster(self):
        mage = ask("a wizard casting a spell", characters=(creature("wizard", "human wizard"),))
        self.assertIn(status(mage, "fantasy:action.cast_spell"), ("eligible", "feasible"))
        elf = ask("an elf casting a spell", characters=(creature("elf", "elf"),))
        self.assertEqual(status(elf, "fantasy:action.cast_spell"), "unknown", "not every elf is declared a caster")


def person(label, gender):
    return {"label": label, "gender": gender, "custom": "", "pronoun": "he" if gender == "male" else "she"}


class CastFromTheBrief(unittest.TestCase):
    """Step 1 says male or female for a human man or woman and custom for anything else."""

    def cast(self, *characters):
        return [(member["body"], member["traits"]) for member in ask("a scene", characters=characters).cast]

    def test_a_human_named_by_role_or_name_gets_the_human_body(self):
        self.assertEqual(self.cast(person("knight", "male"), person("Ana", "female")),
                         [("core:body.human", []), ("core:body.human", [])])

    def test_explicit_species_and_traits_come_first(self):
        self.assertEqual(self.cast(person("winged knight", "male")), [("core:body.human", ["fantasy:trait.wings"])])
        self.assertEqual(self.cast(person("wizard", "male")), [("core:body.human", ["fantasy:trait.spellcaster"])])
        self.assertEqual(self.cast(person("elf", "female")), [("fantasy:body.elf", [])], "the named species wins")

    def test_gender_never_makes_a_nonhuman_human(self):
        self.assertEqual(self.cast(creature("dragon", "female dragon")), [("fantasy:body.dragon", [])])
        self.assertEqual(self.cast(creature("robot", "robot")), [(None, [])], "undescribed, not human")
        self.assertEqual(self.cast(creature("elf", "male elf")), [("fantasy:body.elf", [])])

    def test_gender_is_independent_of_anatomy(self):
        for gender in ("male", "female"):
            body, traits = self.cast(person("Sam", gender))[0]
            self.assertEqual((body, traits), ("core:body.human", []), "no anatomy trait from gender")
        found = ask("a woman giving a blowjob", characters=(person("Ana", "female"), person("Ben", "male")), nsfw=True)
        self.assertEqual(status(found, "adult:action.oral"), "unknown", "anatomy stays undeclared")


class IsolatedWords(unittest.TestCase):
    """One word of a longer name counts only when the request also names something linked to the entry."""

    def test_an_isolated_word_does_not_retrieve_an_entry(self):
        self.assertNotIn("fantasy:item.staff", ids(ask("hotel staff at the reception desk")))
        self.assertNotIn("core:posture.lying_side", ids(ask("a man standing by the side of a road", characters=(MAN,))))

    def test_exact_names_and_aliases_still_retrieve(self):
        self.assertIn("fantasy:item.staff", ids(ask("a mage with a magic staff", characters=(creature("mage", "human mage"),))))
        self.assertIn("core:posture.lying_side", ids(ask("a woman lying on the side", characters=(WOMAN,))))
        self.assertIn("core:action.hold", ids(ask("a woman holding a lantern", characters=(WOMAN,))))
        self.assertIn("core:position.riding", ids(ask("a knight riding a dragon",
                                                      characters=(person("knight", "male"), creature("dragon", "dragon")))))

    def test_a_linked_entry_keeps_its_isolated_word(self):
        found = ask("a mage casting a spell with a staff", characters=(creature("mage", "human mage"),))
        self.assertIn("fantasy:item.staff", ids(found), "the spell that uses a focus is named")
        found = ask("a couple spooning on the side of the bed")
        self.assertIn("core:posture.lying_side", ids(found), "the spooning that takes the posture is named")
        cowgirl = [entry_id for entry_id in ids(ask("cowgirl", nsfw=True)) if "cowgirl" in entry_id]
        self.assertEqual(cowgirl, ["adult:position.cowgirl", "adult:position.reverse_cowgirl"], "a named parent")


class Retrieval(unittest.TestCase):
    REQUESTS = [  # request, characters, nsfw, entries that must be offered
        ("A woman and a man hugging goodbye on a train platform", (WOMAN, MAN), False, {"core:action.hug"}),
        ("A couple kissing on a park bench", (WOMAN, MAN), False, {"core:action.kiss", "core:space.bench"}),
        ("Two friends sitting side by side on a sofa", (WOMAN, MAN), False, {"core:position.side_by_side", "core:space.sofa"}),
        ("A man and a woman holding hands on the beach", (WOMAN, MAN), False, {"core:action.hold_hands"}),
        ("A woman sitting on a man's lap in an armchair", (WOMAN, MAN), False, {"core:position.lap_sit", "core:space.chair"}),
        ("A couple spooning in bed", (WOMAN, MAN), False, {"core:position.spooning", "core:space.bed"}),
        ("A woman holding a lantern while walking through a dark forest", (WOMAN,), False, {"core:action.hold", "core:item.lantern"}),
        ("A dragon resting on a cliff above a stormy sea", (creature("dragon", "dragon"),), False, {"core:space.cliff"}),
        ("A dragon breathing fire", (creature("dragon", "dragon"),), False, {"fantasy:action.breathe_fire"}),
        ("A knight riding a dragon", (MAN, creature("dragon", "dragon")), False, {"core:position.riding"}),
        ("A female elf mage casting a spell with a staff in an enchanted forest", (creature("elf", "female elf mage"),), False,
         {"fantasy:action.cast_spell", "fantasy:item.staff", "fantasy:space.enchanted_woods"}),
        ("A winged elf flying", (creature("elf", "winged elf"),), False, {"core:posture.flying"}),
        ("Missionary on a bed", (WOMAN, MAN), True, {"adult:position.missionary", "core:space.bed"}),
        ("Cowgirl", (WOMAN, MAN), True, {"adult:position.cowgirl"}),
        ("Doggy style", (WOMAN, MAN), True, {"core:position.from_behind"}),
        ("A woman giving a blowjob", (WOMAN, MAN), True, {"adult:action.oral"}),
        ("A woman using a vibrator", (WOMAN,), True, {"adult:item.vibrator"}),
        ("A man handcuffed to the bed", (WOMAN, MAN), True, {"adult:action.restrained", "adult:item.handcuffs"}),
        ("Standing from behind against a wall", (WOMAN, MAN), True, {"adult:position.standing_behind", "core:space.wall"}),
        ("Sixty-nine", (WOMAN, MAN), True, {"adult:position.sixty_nine"}),
        ("Two women fingering each other", (WOMAN, {**WOMAN, "label": "woman 2"}), True, {"adult:action.manual"}),
    ]

    def test_ordinary_words_find_the_entries(self):
        for text, characters, nsfw, expected in self.REQUESTS:
            with self.subTest(request=text):
                found = ask(text, characters, nsfw=nsfw)
                self.assertEqual(expected - set(ids(found)), set(), ids(found))

    def test_casts_resolve_to_pack_bodies(self):
        self.assertEqual(bodies(ask("two friends hugging")), ["core:body.human", "core:body.human"])
        self.assertEqual(bodies(ask("a dragon", characters=(creature("dragon", "female dragon"),))), ["fantasy:body.dragon"])
        mage = ask("a mage", characters=(creature("elf", "female elf mage"),)).cast[0]
        self.assertEqual((mage["body"], mage["traits"]), ("fantasy:body.elf", ["fantasy:trait.spellcaster"]))

    def test_sfw_never_offers_adult_entries(self):
        for text in ("doggy style", "a woman giving a blowjob", "a woman using a vibrator", "missionary", "cowgirl"):
            with self.subTest(request=text):
                found = ask(text)
                self.assertFalse([entry.id for entry in found.entries if entry.rating == "adult"])
                self.assertTrue(any("rating adult" in item["reason"] for item in found.excluded))

    def test_a_specific_child_replaces_its_parent_only_when_named(self):
        reverse = ask("reverse cowgirl", nsfw=True)
        self.assertIn("adult:position.reverse_cowgirl", ids(reverse))
        self.assertNotIn("adult:position.cowgirl", ids(reverse))
        plain = [entry_id for entry_id in ids(ask("cowgirl", nsfw=True)) if "cowgirl" in entry_id]
        self.assertEqual(plain, ["adult:position.cowgirl", "adult:position.reverse_cowgirl"])

    def test_actions_that_only_share_a_body_part_are_not_related(self):
        found = ask("sixty-nine", nsfw=True)
        self.assertNotIn("fantasy:action.breathe_fire", ids(found))
        self.assertNotIn("core:action.kiss", ids(found))

    def test_spaces_that_only_share_a_surface_are_not_related(self):
        found = ask("a dragon breathing fire over a great hall", characters=(creature("dragon", "dragon"),))
        self.assertIn("fantasy:space.great_hall", ids(found))
        self.assertNotIn("fantasy:space.lair", ids(found))
        self.assertIn(("fantasy:action.cast_spell", "shares"), INDEX.neighbours["fantasy:item.staff"],
                      "an item and the action that uses what it provides stay related")
        self.assertNotIn(("fantasy:space.lair", "shares"), INDEX.neighbours["fantasy:space.great_hall"])

    def test_director_wording_brings_in_nothing(self):
        nsfw_director = ("Describe anatomy, pose, contact, weight distribution and spatial relationships so bodies remain "
                         "credible; keep face, body and genitals logically positioned; one person per attribute block.")
        for text, cast, director, allowed in (
                ("a woman in lingerie posing on a bed", (WOMAN,), nsfw_director, {"core:space.bed"}),
                ("a couple making out on the couch", (WOMAN, MAN), nsfw_director, {"core:space.sofa"}),
                ("a quiet afternoon", (WOMAN,), GENERAL_DIRECTOR, set())):
            with self.subTest(request=text):
                found = ask(text, characters=cast, nsfw=True, director=director)
                self.assertEqual(set(ids(found)) - allowed, set(), "'face' is one word of 'Facing each other at a distance'")

    def test_ordinary_requests_get_no_unrelated_suggestions(self):
        cases = [  # request, characters, nsfw, what may be offered
            ("A portrait of a woman in a red dress", (WOMAN,), False, set()),
            ("A woman walking through a dark forest", (WOMAN,), False, set()),
            ("A man drinking coffee in a cafe", (MAN,), False, set()),
            ("A woman laughing at a dinner party with friends", (WOMAN,), False, set()),
            ("A man playing guitar on stage", (MAN,), False, set()),
            ("Hotel staff at the reception desk", (WOMAN, MAN), False, {"core:space.table"}),
            ("A man standing by the side of a road", (MAN,), False, {"core:posture.standing", "core:position.standing_alone"}),
            ("A woman in a tank top doing yoga", (WOMAN,), False, set()),
            ("A man carrying a box up the stairs", (MAN,), False, set()),
            ("A couple drinking wine in their living room", (WOMAN, MAN), False, set()),
            ("A woman facing the camera with a smile", (WOMAN,), False, set()),
            ("A red sports car on a mountain road at dusk", (), False, set()),
            ("A castle on a hill under a starry sky", (), False, set()),
            ("Two friends hugging after a long trip", (WOMAN, MAN), False, {"core:action.hug"}),
            ("A woman in lingerie posing on a bed", (WOMAN,), True, {"core:space.bed"}),
            ("A naked man taking a shower", (MAN,), True, set()),
            ("A couple making out on the couch", (WOMAN, MAN), True, {"core:space.sofa"}),
        ]
        for text, characters, nsfw, allowed in cases:
            with self.subTest(request=text):
                found = ask(text, characters, nsfw=nsfw)
                self.assertEqual(set(ids(found)) - allowed, set())

    def test_same_request_same_result(self):
        text = "a knight riding a dragon past a castle, then hugging a woman on a bench"
        first = ask(text, characters=(MAN, creature("dragon", "dragon"), WOMAN)).to_dict()
        self.assertEqual(ask(text, characters=(MAN, creature("dragon", "dragon"), WOMAN)).to_dict(), first)


if __name__ == "__main__":
    unittest.main()
