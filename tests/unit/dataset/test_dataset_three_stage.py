"""Three-stage Dataset: character definitions, ideas that carry finished scenes, and the cast-aware writer."""

import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import creative_directions, ideas_instruction
from goated_prompter.features.dataset.plan import ScenePlanner
from goated_prompter.features.dataset.prompting import anima_count_tags, cast_error, dataset_instruction, geometry_error
from goated_prompter.features.dataset.understanding import (_expand_understanding, understanding_instruction,
    validate_understanding)
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, library_path
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from goated_prompter.features.dataset.brainstorm import (brainstorm_events, candidate_count, pick_events,
    validate_brainstorm)
from tests.support.dataset import CaptureBackend, brainstorm_fixture, saved_scene, valid_draft

SCOPES = ("all_outputs", "dataset")
NARUTO = {"name": "Naruto Uzumaki", "count": 1, "sex": "male", "kind": "human", "origin": "named",
          "series": "Naruto", "traits": ""}
COMPANION = {"name": "random companion", "count": 1, "sex": "unspecified", "kind": "human", "origin": "random",
             "series": "", "traits": ""}
LIKED = ("1girl, 1boy, kitchen, cooking, flour on face\n\n"
         "A flustered chef blows flour off a rolling pin straight into her sous-chef's face while dough "
         "slides off the counter behind them in a cramped noodle shop lit by one hanging bulb.")


def character(**changes):
    return {**NARUTO, **changes}


class CharacterTests(unittest.TestCase):
    def test_characters_are_validated_and_normalized_when_present(self):
        brief = dataset_understanding_fixture(characters=[character(name="  Naruto   Uzumaki "), COMPANION])
        result = validate_understanding(brief, SCOPES)
        self.assertEqual(result["characters"], [NARUTO, COMPANION])

    def test_briefs_saved_before_characters_existed_stay_valid_and_unchanged(self):
        brief = dataset_understanding_fixture()
        self.assertNotIn("characters", validate_understanding(brief, SCOPES))

    def test_invalid_characters_are_rejected(self):
        for changes in ({"sex": "woman"}, {"kind": "elf"}, {"origin": "canon"}, {"count": 0}, {"count": True},
                        {"name": " "}, {"traits": None}, {"extra": "field"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_understanding(dataset_understanding_fixture(characters=[character(**changes)]), SCOPES)
        with self.assertRaises(ValueError):
            validate_understanding(dataset_understanding_fixture(characters=[NARUTO] * 13), SCOPES)

    def test_compact_model_output_passes_characters_into_the_reviewed_brief(self):
        data = valid_draft()
        compact = {"requested_generation": "Naruto and a companion clown around.", "character_count": 2,
            "identity_policy": "mixed", "requirements": {"hard": [], "soft": [], "free": [], "context": []},
            "expansion_freedom": "Open.", "physical_conflicts": [], "clarifications": [],
            "characters": [NARUTO, COMPANION]}
        brief = validate_understanding(_expand_understanding(compact, data, SCOPES), SCOPES)
        self.assertEqual(brief["characters"], [NARUTO, COMPANION])

    def test_understanding_asks_for_each_characters_sex_kind_and_origin(self):
        instruction = understanding_instruction(valid_draft())
        rules = " ".join(instruction.system_message.split())
        self.assertIn("characters: who appears in each image", rules)
        self.assertIn("anthro (furry or anthropomorphic animal)", rules)
        self.assertIn("Naruto Uzumaki is a male human from Naruto", rules)
        schema = instruction.json_schema["properties"]["characters"]["items"]
        self.assertEqual(schema["properties"]["sex"]["enum"], ["female", "male", "mixed", "unspecified", "none"])
        self.assertIn("anthro", schema["properties"]["kind"]["enum"])


class IdeaSceneTests(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        patcher = patch.dict(os.environ, {LIBRARY_DIR_ENV: str(directory)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = valid_draft(amount=1, subject="A chef and her sous-chef cooking",
                                _confirmed_intent=dataset_understanding_fixture())

    def test_a_draft_saved_with_the_removed_library_source_plans_invented_scenes(self):
        from goated_prompter.features.dataset.service import validate_dataset_draft
        self.assertEqual(validate_dataset_draft({**self.data, "source_mode": "library"})["source_mode"], "random")

    def test_ideas_are_invented_without_the_library(self):
        library_path("Generic").write_text(LIKED, encoding="utf-8")
        for mode, extra in (("random", {}), ("guided", {"inputs": "She juggles oranges"})):
            data = {**self.data, "source_mode": mode, **extra}
            instruction = ideas_instruction(data, dataset_assignments(data))
            with self.subTest(mode=mode):
                self.assertNotIn("flour", instruction.user_message.casefold())
                self.assertNotIn("library_examples", json.loads(instruction.user_message))
                self.assertEqual(instruction.reference_prompts, ())

    def test_ideas_prompt_asks_for_finished_scenes_with_the_whole_cast_in_frame(self):
        rules = " ".join(ideas_instruction(self.data, dataset_assignments(self.data)).system_message.split())
        self.assertIn("idea, the core event in one sentence of at most 30 words, and scene", rules)
        self.assertIn("Put exactly that cast in every scene", rules)
        self.assertIn("keeps every character clearly in frame", rules)


class CastWriterTests(unittest.TestCase):
    def writer(self, characters, **changes):
        data = valid_draft(amount=1, **changes,
                           _confirmed_intent=dataset_understanding_fixture(characters=characters))
        return dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=saved_scene())

    def test_writer_lists_the_approved_cast(self):
        system = self.writer([NARUTO, character(name="guards", count=2, sex="female", kind="robot",
                                                origin="described", series="", traits="chrome armor")]).system_message
        self.assertIn("CAST (every image shows exactly these characters", system)
        self.assertIn("- Naruto Uzumaki: male human, existing character from Naruto", system)
        self.assertIn("- 2 x guards: female robot, as the user described; traits: chrome armor", system)

    def test_anima_count_tags_follow_the_cast(self):
        self.assertEqual(anima_count_tags([NARUTO, character(sex="female")]), ["1girl", "1boy"])
        self.assertEqual(anima_count_tags([character(count=3)]), ["3boys"])
        self.assertEqual(anima_count_tags([character(sex="female", count=7)]), ["6+girls"])
        self.assertEqual(anima_count_tags([character(sex="none", kind="robot")]), ["1other"])
        self.assertEqual(anima_count_tags([character(sex="none", kind="animal")]), ["no humans"])
        self.assertIsNone(anima_count_tags([NARUTO, COMPANION]), "An open sex is decided per scene.")
        pet = character(name="pet dragon", sex="unspecified", kind="animal", origin="random")
        robot = character(name="little robot", sex="none", kind="robot", origin="random")
        self.assertEqual(anima_count_tags([character(sex="female", origin="random"), pet, robot]), ["1girl", "1other"],
                         "An animal takes no count tag even when its sex is left open.")
        self.assertIsNone(anima_count_tags([]))

    def test_anima_writer_starts_with_count_and_named_character_tags(self):
        system = self.writer([NARUTO, character(name="Hinata Hyuga", sex="female")], target="Anima").system_message
        self.assertIn("Start the tag block with these count tags: 1girl, 1boy.", system)
        self.assertIn("Danbooru character tag and series tag", system)
        self.assertIn("give each one's basic appearance", system)
        open_cast = self.writer([NARUTO, COMPANION], target="Anima").system_message
        self.assertIn("count tags that match the characters in this scene", open_cast)

    def test_a_locked_anima_trigger_keeps_ownership_of_character_tags(self):
        system = self.writer([NARUTO], target="Anima", trigger="1boy, uzumaki naruto", trigger_at_start=True,
                             trigger_connected=True, expand_trigger=False).system_message
        self.assertNotIn("ANIMA CAST TAGS", system)

    def test_other_targets_and_briefs_without_characters_get_no_tag_section(self):
        self.assertNotIn("ANIMA CAST TAGS", self.writer([NARUTO]).system_message)
        self.assertNotIn("CAST (", self.writer([]).system_message)


class CastCheckTests(unittest.TestCase):
    def data(self, characters, **changes):
        return valid_draft(**changes, _confirmed_intent=dataset_understanding_fixture(characters=characters))

    def test_named_characters_must_survive_into_the_prompt(self):
        data = self.data([NARUTO, COMPANION])
        self.assertIsNone(cast_error("Naruto grins at his friend on a rooftop.", data))
        self.assertIsNone(cast_error("uzumaki naruto, 1boy\n\nA boy grins.", data))
        self.assertIn("Missing: Naruto Uzumaki", cast_error("Two friends grin on a rooftop.", data))

    def test_anima_count_tags_from_the_cast_must_lead_the_prompt(self):
        data = self.data([NARUTO, character(name="Hinata Hyuga", sex="female")], target="Anima")
        self.assertIsNone(cast_error("1girl, 1boy, uzumaki naruto, hyuuga hinata\n\nNaruto and Hinata share ramen.", data))
        self.assertIn("1girl", cast_error("1boy, uzumaki naruto, hinata\n\nNaruto and Hinata share ramen.", data))
        extra = cast_error("1girl, 1boy, uzumaki naruto, hinata, 3boys, 3girls\n\nNaruto and Hinata share ramen.", data)
        self.assertIn("remove 3boys, 3girls", extra)

    def test_open_sexes_locked_triggers_and_briefs_without_a_cast_are_not_checked_for_tags(self):
        self.assertIsNone(cast_error("Naruto and a friend.", self.data([NARUTO, COMPANION], target="Anima")))
        locked = self.data([NARUTO], target="Anima", trigger="1boy, uzumaki naruto", trigger_at_start=True,
                           trigger_connected=True, expand_trigger=False)
        self.assertIsNone(cast_error("rooftop, sunset\n\nNaruto waves.", locked))
        self.assertIsNone(cast_error("Anything at all.", valid_draft(target="Anima",
                                                                      _confirmed_intent=dataset_understanding_fixture())))


class ChunkedIdeasTests(unittest.TestCase):
    def test_batches_are_written_five_ideas_per_call_and_later_chunks_see_earlier_ideas(self):
        data = valid_draft(amount=7, _confirmed_intent=dataset_understanding_fixture())
        backend = CaptureBackend()
        with patch("goated_prompter.features.dataset.plan.secrets.randbits", return_value=11):
            rows = ScenePlanner(lambda: None).plan_ideas(session=backend, data=data,
                assignments=dataset_assignments(data), progress=lambda _message: None, allow_partial=True)
        self.assertEqual([row["index"] for row in rows], list(range(1, 8)))
        self.assertEqual([call.diagnostic_stage for call in backend.calls],
                         ["dataset:ideas:brainstorm", "dataset:ideas", "dataset:ideas"])
        first, second = [json.loads(call.user_message) for call in backend.calls[1:]]
        self.assertEqual(first["output_contract"]["indexes"], [1, 2, 3, 4, 5])
        self.assertEqual(second["output_contract"]["indexes"], [6, 7])
        self.assertEqual([row["index"] for row in second["existing_ideas"]], [1, 2, 3, 4, 5])
        # One salt for the whole batch keeps the creative directions spread across every chunk.
        directions = creative_directions(data, list(range(1, 8)), 11)
        sent = [row["creative_direction"] for context in (first, second) for row in context["assignments"]]
        seeded = {row["index"] for context in (first, second) for row in context["assignments"] if row.get("event_seed")}
        expected = [{axis: value for axis, value in directions[index].items()
                     if index not in seeded or axis not in ("moment", "interaction")} for index in range(1, 8)]
        self.assertEqual(sent, expected, "A seeded image keeps framing, light, mood and setting, not a moment label.")
        self.assertTrue(seeded)


class BrainstormTests(unittest.TestCase):
    def test_events_skip_recent_repeats_and_each_other(self):
        candidates = [("She juggles three oranges on a bus.", .9), ("She juggles oranges on a moving bus.", .8),
                      ("She rescues a kite from a tree.", .3), ("She teaches a goose to dance.", .1)]
        chosen = pick_events(candidates, 4, random.Random(1), avoid=["She juggles oranges on the bus."])
        self.assertEqual(sorted(chosen), ["She rescues a kite from a tree.", "She teaches a goose to dance."])
        picked = pick_events(candidates[:2], 2, random.Random(2))
        self.assertEqual(len(picked), 1, "Two near-identical candidates fill only one slot.")

    def test_unusual_events_are_favoured_but_obvious_ones_stay_possible(self):
        candidates = [("obvious event", 1.0), ("rare event", 0.0)]
        firsts = [pick_events(candidates, 1, random.Random(seed))[0] for seed in range(400)]
        self.assertGreater(firsts.count("rare event"), firsts.count("obvious event") * 2)
        self.assertGreater(firsts.count("obvious event"), 400 // 8, "A gentle pull, not a hunt for the strangest stunt.")

    def test_different_runs_pick_different_events_from_the_same_pool(self):
        pool = [(row["event"], row["typicality"]) for row in brainstorm_fixture(15)]
        batches = {tuple(pick_events(pool, 5, random.Random(seed))) for seed in range(10)}
        self.assertGreater(len(batches), 5)

    def test_parser_keeps_usable_rows_and_clamps_typicality(self):
        raw = json.dumps([{"event": " A  dog surfs. ", "typicality": 3}, {"event": "", "typicality": .2},
                          {"event": "A cat bakes.", "typicality": True}, "junk", {"event": "A fox paints.", "typicality": -1}])
        self.assertEqual(validate_brainstorm(raw, 10), [("A dog surfs.", 1.0), ("A fox paints.", 0.0)])
        with self.assertRaises(ValueError):
            validate_brainstorm("[]", 10)

    def test_seeds_reach_each_idea_and_an_unusable_brainstorm_falls_back(self):
        data = valid_draft(amount=3, _confirmed_intent=dataset_understanding_fixture())
        backend = CaptureBackend()
        ScenePlanner(lambda: None).plan_ideas(session=backend, data=data, assignments=dataset_assignments(data),
                                              progress=lambda _message: None, allow_partial=True)
        brainstorm, ideas = backend.calls
        self.assertEqual(json.loads(brainstorm.user_message)["requested_events"], candidate_count(3))
        self.assertGreaterEqual(brainstorm.temperature, 1.0)
        seeds = [row["event_seed"] for row in json.loads(ideas.user_message)["assignments"]]
        self.assertEqual(len(set(seeds)), 3)
        messages = []
        session = Mock()
        session.generate.return_value = "not json"
        self.assertEqual(brainstorm_events(session, data, 3, random.Random(1), progress=messages.append,
                                           checkpoint=lambda: None), [])
        self.assertIn("without event seeds", messages[-1])

    def test_guided_and_library_batches_do_not_brainstorm(self):
        for changes in ({"source_mode": "guided", "inputs": "a punch\na block"},):
            data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(), **changes)
            backend = CaptureBackend()
            ScenePlanner(lambda: None).plan_ideas(session=backend, data=data, assignments=dataset_assignments(data),
                                                  progress=lambda _message: None, allow_partial=True)
            self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:ideas"])

    def test_recent_ideas_and_current_siblings_are_avoided(self):
        from goated_prompter.features.dataset.idea_history import RecentIdeaHistory
        data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture())
        history = RecentIdeaHistory()
        history.remember(data, [{"idea": "An earlier event."}])
        backend = CaptureBackend()
        ScenePlanner(lambda: None, history).plan_ideas(session=backend, data=data, assignments=dataset_assignments(data),
            progress=lambda _message: None, indexes=[2], existing=[dataset_idea_fixture(1)], allow_partial=True)
        avoid = json.loads(backend.calls[0].user_message)["recently_used_ideas"]
        self.assertEqual(avoid, ["An earlier event.", dataset_idea_fixture(1)["idea"]])


class RandomLookTests(unittest.TestCase):
    def test_random_human_characters_get_a_different_look_in_each_image(self):
        brief = dataset_understanding_fixture(characters=[NARUTO, COMPANION])
        data = valid_draft(amount=4, _confirmed_intent=brief)
        directions = creative_directions(data, [1, 2, 3, 4], salt=5)
        looks = [direction["random_character_looks"] for direction in directions.values()]
        self.assertTrue(all(set(look) == {"random companion"} for look in looks), "Named characters keep their canon look.")
        self.assertEqual(len({look["random companion"] for look in looks}), 4)
        self.assertNotEqual(directions, creative_directions(data, [1, 2, 3, 4], salt=6))

    def test_non_human_or_defined_casts_get_no_drawn_look(self):
        for characters in ([NARUTO], [character(origin="random", kind="robot", name="a robot")], []):
            data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(characters=characters))
            self.assertTrue(all("random_character_looks" not in item
                                for item in creative_directions(data, [1, 2]).values()))


class GeometryTests(unittest.TestCase):
    def test_contradictory_camera_angles_are_rejected(self):
        for prompt in ("A high-angle shot of a dancer, low-angle hero framing.", "Seen from below in a top-down composition.",
                       "bird's-eye view with a worm's-eye perspective", "camera looks down at her; shot from below"):
            with self.subTest(prompt=prompt):
                self.assertIn("from above and from below", geometry_error(prompt))

    def test_light_and_gaze_directions_are_not_mistaken_for_the_camera(self):
        for prompt in ("Soft light from above while she looks down at her phone; low-angle shot.",
                       "Sunlight from below the clouds, eye-level medium shot.", "A high-angle view of a quiet street."):
            with self.subTest(prompt=prompt):
                self.assertIsNone(geometry_error(prompt))

    def test_creative_directions_never_ask_for_steep_angles(self):
        from goated_prompter.features.dataset.ideas import DIRECTION_AXES, GROUP_FRAMING
        steep = ("high-angle", "low-angle", "from above", "top-down", "bird", "worm")
        for framing in (*DIRECTION_AXES["framing"], *GROUP_FRAMING):
            self.assertFalse(any(word in framing for word in steep), framing)

    def test_ideas_and_writer_keep_one_camera_and_one_coherent_pose(self):
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        ideas = " ".join(ideas_instruction(data, dataset_assignments(data)).system_message.split())
        self.assertIn("exactly one camera angle and one shot size", ideas)
        self.assertIn("one simple, readable pose, described once from head to feet", ideas)
        writer = " ".join(dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
                                              plan_item=saved_scene()).system_message.split())
        self.assertIn("never add a second angle, viewpoint or lens perspective", writer)
        self.assertIn("add no pose details beyond the scene's", writer)
        self.assertIn("never on new limb positions, a new camera position", writer)


class PlausibilityTests(unittest.TestCase):
    def test_brainstorm_and_ideas_forbid_impossible_bodies(self):
        from goated_prompter.features.dataset.brainstorm import BRAINSTORM_SYSTEM
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        ideas = " ".join(ideas_instruction(data, dataset_assignments(data)).system_message.split())
        for rules in (" ".join(BRAINSTORM_SYSTEM.split()), ideas):
            self.assertIn("physically possible for real bodies", rules)
            self.assertIn("No one is airborne, mid-fall, mid-trip or mid-jump", rules)
            self.assertIn("never a tangle of limbs or limbs at odd angles", rules)
            self.assertIn("show the moment just before or just after it", rules)
            self.assertIn("No weight on hands or fingertips, no flips, cartwheels", rules)
            self.assertIn("not from twisted anatomy", rules)

    def test_random_people_with_an_open_sex_get_one_drawn_and_are_never_named_by_their_label(self):
        pair = [{**COMPANION, "name": "friend 1"}, {**COMPANION, "name": "friend 2"}]
        data = valid_draft(amount=6, _confirmed_intent=dataset_understanding_fixture(characters=pair))
        looks = [item["random_character_looks"] for item in creative_directions(data, range(1, 7), salt=3).values()]
        drawn = [look[name].split(", ")[0] for look in looks for name in ("friend 1", "friend 2")]
        self.assertTrue(set(drawn) <= {"woman", "man"})
        self.assertGreater(len(set(drawn)), 1)
        self.assertGreater(len({(look["friend 1"].split(", ")[0], look["friend 2"].split(", ")[0]) for look in looks}), 1,
                           "Pairs are not always one woman and one man.")
        self.assertEqual(looks, [item["random_character_looks"]
                                 for item in creative_directions(data, range(1, 7), salt=3).values()])
        group = {**COMPANION, "name": "dancers", "count": 3}
        decided = [character(name="random girl", sex="female", origin="random", series=""), group]
        looks = creative_directions(valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(
            characters=decided)), [1, 2])
        self.assertFalse(any(look.split(", ")[0] in ("woman", "man")
                             for item in looks.values() for look in item["random_character_looks"].values()))
        ideas = " ".join(ideas_instruction(data, dataset_assignments(data)).system_message.split())
        self.assertIn("A random character's name is only a role label (friend 1, the woman): never write it", ideas)
        from goated_prompter.features.dataset.prompting import cast_section
        self.assertIn("friend 1: sex open human, invented for this image; the name is only a label, so never write it",
                      cast_section(pair))

    def test_drawn_looks_keep_an_age_the_role_implies_and_leave_clothing_to_the_scene(self):
        girl = character(name="random girl", sex="female", origin="random", series="")
        data = valid_draft(amount=3, _confirmed_intent=dataset_understanding_fixture(characters=[NARUTO, girl]))
        looks = [item["random_character_looks"]["random girl"] for item in creative_directions(data, [1, 2, 3]).values()]
        from goated_prompter.features.dataset.ideas import LOOK_AXES
        self.assertFalse(any(age in look for look in looks for age in LOOK_AXES["age"]))
        self.assertTrue(all(look.count(",") == 1 for look in looks), "Only hair and build are drawn.")
        for stated in ({"name": "20 yo man"}, {"name": "man", "traits": "25 years old"}, {"name": "woman in her 30s"},
                       {"name": "a 40-year-old chef"}):
            person = {**COMPANION, "sex": "male", **stated}
            look = creative_directions(valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture(
                characters=[person])), [1])[1]["random_character_looks"][person["name"]]
            self.assertFalse(any(age in look for age in LOOK_AXES["age"]), (stated, look))
        adult = creative_directions(valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture(
            characters=[COMPANION])), [1])[1]["random_character_looks"]["random companion"]
        self.assertTrue(any(age in adult for age in LOOK_AXES["age"]))


class RepeatedInventoryTests(unittest.TestCase):
    def test_an_anima_prompt_that_prints_its_tag_list_twice_keeps_one_copy(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.service import DatasetService
        data = valid_draft(amount=1, target="Anima", trigger="naruto", trigger_type="Character", expand_trigger=True,
                           _confirmed_intent=dataset_understanding_fixture(characters=[NARUTO]))
        row = saved_scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        tags = "1boy, uzumaki naruto, naruto (series), snow, courtyard, evening"
        session = Mock()
        session.generate.return_value = f"{tags}, {tags}\n\nUzumaki Naruto packs snow onto a snowman in a quiet courtyard."
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result.split("\n\n")[0], tags)

    def test_an_anima_prompt_with_several_characters_drops_a_contradictory_solo_tag(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.service import DatasetService
        cast = [character(name="knight girl", sex="female", origin="random", series=""),
                character(name="little robot", sex="none", kind="robot", origin="random", series="")]
        data = valid_draft(amount=1, target="Anima", trigger="knight girl, robot", trigger_type="Multiple characters",
                           expand_trigger=True, _confirmed_intent=dataset_understanding_fixture(characters=cast))
        row = saved_scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = ("1girl, 1other, solo, knight, robot, campfire\n\n"
                                         "A knight girl warms her hands while a little robot sits by the fire.")
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result.split("\n\n")[0], "1girl, 1other, knight, robot, campfire")


class RenderabilityGateTests(unittest.TestCase):
    def test_prompts_that_list_rules_or_settings_or_loop_are_rejected(self):
        from goated_prompter.features.dataset.prompting import instruction_leak_error
        scene = "A woman kneels on a wet sidewalk beside a torn grocery bag."
        for prompt in ("woman kneeling, wet sidewalk, no supernatural elements, physically plausible stunt",
                       "photograph of a woman, balanced creativity, general director, dataset of 4 images",
                       "A woman kneels on the sidewalk. Maximum detail, randomized identity."):
            with self.subTest(prompt=prompt):
                self.assertIn("lists instructions or settings", instruction_leak_error(prompt, scene))
        looping = "woman, torn bag, " + "wet pavement, primary focus, " * 4
        self.assertIn('repeats "wet pavement" 4 times', instruction_leak_error(looping, scene))
        self.assertIsNone(instruction_leak_error("A film director reads the instructions on a dataset poster.",
                                                 "A film director reads the instructions on a dataset poster."))
        self.assertIsNone(instruction_leak_error("1girl, 1boy, 1boy, 1boy, kitchen\n\nThey cook.", scene))

    def test_ideas_with_bodies_in_the_air_or_acrobatics_are_rejected_unless_asked(self):
        from goated_prompter.features.dataset.ideas import unrenderable_pose
        for text in ("Two friends perform synchronized cartwheels on cobblestones.",
                     "She leaps over a puddle, both feet off the ground.",
                     "A man and woman hold a synchronized freeze on their knees and elbows.",
                     "He hangs upside down from a lamp post.", "She is mid-stumble over the curb."):
            with self.subTest(text=text):
                self.assertIsNotNone(unrenderable_pose(text, "two friends dancing at a festival"))
        for text in ("She is about to jump over the puddle, knees bent.", "Her slipper flies through the air.",
                     "Dust motes drift in the air above the desk.", "He sits on the curb after the jump.",
                     "They freeze in surprise as a small animal jumps between them."):
            with self.subTest(text=text):
                self.assertIsNone(unrenderable_pose(text, "a woman doing stunts"))
        self.assertIsNone(unrenderable_pose("She lands a backflip on the beach.", "a gymnast doing backflips"))

    def test_an_acrobatic_idea_is_queued_for_repair_and_library_recasts_keep_their_pose(self):
        from goated_prompter.features.dataset.ideas import _reject_unrenderable_pose
        row = {"index": 1, "idea": "Two friends cartwheel down the street.", "scene": "They cartwheel side by side.",
               "idea_status": "valid"}
        data = valid_draft(amount=1, subject="Two friends dancing")
        failed = _reject_unrenderable_pose(row, data, allow_partial=True)
        self.assertEqual((failed["idea_status"], failed["failure_stage"]), ("failed", "idea"))
        self.assertIn('"cartwheel"', failed["failure_reason"])
        with self.assertRaises(ValueError):
            _reject_unrenderable_pose(row, data, allow_partial=False)


class LabelAndTriggerTidyTests(unittest.TestCase):
    PAIR = [{**COMPANION, "name": "Friend 1"}, {**COMPANION, "name": "Friend 2"}]

    def test_numbered_labels_are_replaced_with_visible_descriptions_never_rejected(self):
        from goated_prompter.features.dataset.understanding import label_replacements, replace_labels
        from goated_prompter.features.dataset.ideas import _relabel
        self.assertEqual(replace_labels("Friend 1 holds the cake. friend 2 laughs at Friend 1’s hat.",
                                        label_replacements(self.PAIR)),
                         "The first friend holds the cake. The second friend laughs at the first friend’s hat.")
        roles = [{**COMPANION, "name": "old man"}, {**COMPANION, "name": "grandson"}, NARUTO]
        self.assertEqual(label_replacements(roles), {}, "Plain roles and named characters stay as written.")
        facts = [{**COMPANION, "name": "20 yo man"}, {**COMPANION, "name": "agent 47"}, {**COMPANION, "name": "2 girls"},
                 {**COMPANION, "name": "a man in his 30s"}]
        self.assertEqual(label_replacements(facts), {}, "A number that states a fact is a description, not a label.")
        self.assertEqual(replace_labels("A 20 yo man waves.", label_replacements(facts)), "A 20 yo man waves.")
        self.assertEqual(label_replacements([{**COMPANION, "name": "coworker #3"}, *self.PAIR, COMPANION])["coworker #3"],
                         "the third coworker")
        row = {"index": 1, "idea": "Friend 1 slips.", "scene": "Friend 1 slips beside Friend 2.", "idea_status": "valid"}
        looks = {"Friend 1": "woman, mid twenties, long braids, slim", "Friend 2": "early thirties, a buzz cut, stocky"}
        relabelled = _relabel(row, self.PAIR, looks)
        self.assertEqual((relabelled["idea_status"], relabelled["idea"]), ("valid", "The woman with long braids slips."))
        self.assertEqual(relabelled["scene"], "The woman with long braids slips beside the friend with a buzz cut.")
        self.assertEqual(_relabel(row, self.PAIR, None)["scene"], "The first friend slips beside the second friend.")

    def test_a_prompt_that_still_uses_labels_is_relabelled_not_retried(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.service import DatasetService
        data = valid_draft(amount=1, target="Krea 2", trigger="two friends", trigger_type="Multiple characters",
                           expand_trigger=True, _confirmed_intent=dataset_understanding_fixture(characters=self.PAIR))
        row = saved_scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        session = Mock()
        session.generate.return_value = "Two friends at a festival: Friend 1 dances while Friend 2 claps under string lights."
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result, "Two friends at a festival: the first friend dances while the second friend claps "
                                 "under string lights.")
        session.generate.assert_called_once()

    def test_an_expanded_trigger_is_never_quoted_or_left_alone_at_the_end(self):
        from goated_prompter.features.dataset.triggers import tidy_expanded_trigger
        body = "Five people crowd a karaoke booth, holding a lopsided cake under purple neon light."
        self.assertEqual(tidy_expanded_trigger(body + "\n\nfive friends", "five friends", "Krea 2"), body)
        self.assertEqual(tidy_expanded_trigger(body + ", five friends", "five friends", "Krea 2"), body)
        self.assertEqual(tidy_expanded_trigger('photograph, "five friends"\n\n' + body, "five friends", "Krea 2"),
                         "photograph, five friends\n\n" + body)
        lettering = 'A banner reads "five friends" over the booth.'
        self.assertEqual(tidy_expanded_trigger(lettering, "five friends", "Krea 2", lettering), lettering)
        self.assertEqual(tidy_expanded_trigger("Five friends laugh, five friends", "five friends", "Krea 2"),
                         "Five friends laugh, five friends", "A short prompt keeps its only copy.")
        self.assertEqual(tidy_expanded_trigger(body + ", five friends", "five friends", "Anima"), body + ", five friends")


class AnimaGroupTagTests(unittest.TestCase):
    TEAM = [NARUTO, character(name="Hinata Hyuga", sex="female"), character(name="Sakura Haruno", sex="female")]

    def data(self):
        return valid_draft(target="Anima", trigger="naruto, hinata, sakura", expand_trigger=True,
                           _confirmed_intent=dataset_understanding_fixture(characters=self.TEAM))

    def test_count_tags_the_cast_does_not_have_are_dropped_not_sent_back(self):
        from goated_prompter.features.dataset.prompting import drop_wrong_count_tags
        tags = "2girls, 1boy, uzumaki naruto, hyuga hinata, haruno sakura, naruto (series)"
        for prose in ("\n\nThey cook dinner together.", "", "\nThey cook dinner together."):
            with self.subTest(prose=prose):
                fixed = drop_wrong_count_tags(f"{tags}, 3boys, 3girls, kitchen{prose}", self.data())
                self.assertEqual(fixed, f"{tags}, kitchen{prose}")
                self.assertIsNone(cast_error(fixed, self.data()))
        prose_only = "Naruto counts 3boys and 3girls in a sign."
        self.assertEqual(drop_wrong_count_tags(prose_only, self.data()), prose_only)

    def test_a_series_tag_per_character_is_not_a_loop(self):
        from goated_prompter.features.dataset.prompting import instruction_leak_error
        prompt = ("2girls, 1boy, uzumaki naruto, naruto (series), hyuga hinata, naruto (series), haruno sakura, "
                  "naruto (series), kitchen\n\nNaruto, Hinata and Sakura cook dinner in warm light.")
        self.assertIsNone(instruction_leak_error(prompt, "They cook dinner."))
        self.assertIsNone(instruction_leak_error("high contrast, kitchen, high contrast, high contrast", "x"),
                          "Three mentions are emphasis, not a loop.")


class IdeaQualityTests(unittest.TestCase):
    def test_ideas_and_brainstorm_ask_for_something_happening_not_sightseeing(self):
        from goated_prompter.features.dataset.brainstorm import BRAINSTORM_SYSTEM
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        ideas = " ".join(ideas_instruction(data, dataset_assignments(data)).system_message.split())
        self.assertIn("Each idea is a moment where something is happening", ideas)
        self.assertIn("Never fall back on sightseeing or stock poses", ideas)
        self.assertIn("At most one event may be people simply watching, admiring or walking past something",
                      " ".join(BRAINSTORM_SYSTEM.split()))

    def test_several_characters_get_an_interaction_and_settings_skip_scenic_views(self):
        from goated_prompter.features.dataset.ideas import DIRECTION_AXES
        couple = [{**COMPANION, "name": "man", "sex": "male"}, {**COMPANION, "name": "wife", "sex": "female"}]
        data = valid_draft(amount=8, trigger_type="Multiple characters",
                           _confirmed_intent=dataset_understanding_fixture(characters=couple))
        directions = creative_directions(data, range(1, 9))
        self.assertEqual({item["interaction"] for item in directions.values()}, set(DIRECTION_AXES["interaction"]))
        self.assertFalse(any("view" in setting for setting in DIRECTION_AXES["setting"]))

    def test_drawn_hair_and_build_fit_each_persons_sex_and_a_stated_age_is_kept(self):
        from goated_prompter.features.dataset.ideas import LOOKS_BY_SEX, LOOK_AXES
        couple = [{**COMPANION, "name": "man", "sex": "male"}, {**COMPANION, "name": "wife", "sex": "female"}]
        data = valid_draft(amount=10, trigger_type="Multiple characters", subject="a man and his wife exploring japan",
                           trigger="40 yo man", _confirmed_intent=dataset_understanding_fixture(characters=couple))
        for item in creative_directions(data, range(1, 11)).values():
            man, wife = item["random_character_looks"]["man"], item["random_character_looks"]["wife"]
            self.assertTrue(any(hair in man for hair in LOOKS_BY_SEX["man"]["hair"]), man)
            self.assertFalse(any(hair in man for hair in ("pixie", "bob", "braids", "bun", "ponytail")), man)
            self.assertTrue(any(hair in wife for hair in LOOKS_BY_SEX["woman"]["hair"]), wife)
            self.assertFalse(any(hair in wife for hair in ("crew cut", "buzz cut", "shaved", "undercut")), wife)
            self.assertFalse(any(age in look for look in (man, wife) for age in LOOK_AXES["age"]),
                             "The user gave an age, so the app draws none.")


class BatchVarietyTests(unittest.TestCase):
    def test_passive_ideas_are_recognised_by_their_main_action(self):
        from goated_prompter.features.dataset.quality import passive_idea
        for idea in ("The couple leans close to watch sumo warm-up practice.",
                     "They hold hands tightly while watching a street performer.",
                     "They sit in a tatami room, watching a chef prepare dinner.",
                     "They sit on a bench overlooking the bamboo grove.",
                     "Couple standing in awe before a massive ancient temple gate.",
                     "Man shows wife a beautiful view from a mountain lookout.",
                     "They marvel at the intricate architecture of a temple roof.",
                     "They react with surprise at a sudden street performance.",
                     "They react with excitement as they see a massive temple gate.",
                     "They share a quiet moment, looking out at a misty mountain view.",
                     "They sit on a park bench, sharing a quiet moment amidst city life."):
            with self.subTest(idea=idea):
                self.assertTrue(passive_idea(idea))
        for idea in ("Naruto paints a door while a skeptical girl watches from below.",
                     "He shields his wife from a wind gust at a busy crossing.",
                     "She tries to feed a koi without splashing his shirt.",
                     "They react to a spilled drink by scrambling for napkins.",
                     "The pair pause to haggle with a vendor over a broken fan."):
            with self.subTest(idea=idea):
                self.assertFalse(passive_idea(idea))

    def test_a_distinctive_word_shared_by_two_ideas_cannot_appear_in_a_third(self):
        from goated_prompter.features.dataset.quality import repeated_motif
        earlier = ["A woman tries to balance a pizza box on her head.", "A woman balances donuts on her palm."]
        self.assertEqual(repeated_motif("A woman balancing a teacup while walking.", earlier), "balancing")
        self.assertIsNone(repeated_motif("A woman chases her hat down the sidewalk.", earlier))
        self.assertIsNone(repeated_motif("A woman balances a feather.", earlier, ignore={"balancing"}))
        self.assertIsNone(repeated_motif("A woman tries a street trick.", ["A woman tries to wave on a street.",
                                                                         "A woman tries to skip on a street."],
                                         ignore={"woman"}))

    def test_a_place_or_prop_shared_by_two_ideas_cannot_appear_in_a_third(self):
        from goated_prompter.features.dataset.quality import repeated_motif
        earlier = ["They stand at a vending machine comparing drinks.", "They pick drinks from a vending machine in the rain."]
        self.assertEqual(repeated_motif("They argue at a vending machine in a station.", earlier), "vending machine")
        self.assertIsNone(repeated_motif("They argue at a vending machine in a station.", earlier[:1]))
        self.assertIsNone(repeated_motif("A 40-year-old man laughs.", ["A 40-year-old man waves.", "A 40-year-old man runs."]))
        self.assertIsNone(repeated_motif("Naruto eats ramen.", ["Naruto eats ramen at home.", "Naruto eats ramen outside."],
                                         ignore={"naruto", "eats", "ramen"}))

    def test_a_second_passive_idea_and_a_third_repeat_are_queued_for_repair(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.ideas import DatasetIdeasService, PASSIVE_REPEAT
        couple = [{**COMPANION, "name": "man", "sex": "male"}, {**COMPANION, "name": "wife", "sex": "female"}]
        data = valid_draft(amount=5, subject="a man and his wife exploring japan", trigger_type="Multiple characters",
                           _confirmed_intent=dataset_understanding_fixture(characters=couple))
        ideas = ["The couple leans close to watch sumo practice.", "They sit at a counter, watching a chef slice fish.",
                 "They compare drinks at a vending machine.", "They share one umbrella at a vending machine.",
                 "They argue over coins at a vending machine."]
        session = Mock()
        session.generate.return_value = json.dumps([{"index": index, "idea": idea, "scene": f"Scene {index}: {idea}"}
                                                    for index, idea in enumerate(ideas, 1)])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=data, assignments=dataset_assignments(data),
                                                     progress=lambda _message: None, allow_partial=True)
        reasons = {row["index"]: row.get("failure_reason") for row in rows}
        self.assertEqual(reasons[2], PASSIVE_REPEAT)
        self.assertIn('"vending machine"', reasons[5])
        self.assertEqual([index for index, reason in reasons.items() if reason], [2, 5])


class ClarificationTests(unittest.TestCase):
    def test_a_remark_is_not_a_clarification_question(self):
        from goated_prompter.features.dataset.understanding import validate_understanding
        brief = dataset_understanding_fixture(clarifications=[
            "Be aware that 'funny stunts' is a broad category; each image will differ."])
        self.assertEqual(validate_understanding(brief, ("all_outputs", "dataset"))["clarifications"], [])
        asked = dataset_understanding_fixture(clarifications=["Should the stunts be dangerous?"])
        self.assertEqual(validate_understanding(asked, ("all_outputs", "dataset"))["clarifications"],
                         ["Should the stunts be dangerous?"])

    def test_a_none_placeholder_is_not_an_unresolved_physical_conflict(self):
        from goated_prompter.features.dataset.understanding import validate_understanding
        for text in ("None", "N/A", "No physical conflicts."):
            with self.subTest(text=text):
                brief = dataset_understanding_fixture(physical_conflicts=[
                    {"scope": "all_outputs", "conflict": text, "compatible_resolution": None}])
                self.assertEqual(validate_understanding(brief, ("all_outputs", "dataset"))["physical_conflicts"], [])
        real = dataset_understanding_fixture(physical_conflicts=[
            {"scope": "all_outputs", "conflict": "He holds two cups and waves with both hands.", "compatible_resolution": None}])
        with self.assertRaisesRegex(ValueError, "Unresolved physical conflicts"):
            validate_understanding(real, ("all_outputs", "dataset"))


class GemmaRobustnessTests(unittest.TestCase):
    def test_strolling_counts_as_passive_unless_the_user_asked_for_it(self):
        from goated_prompter.features.dataset.quality import passive_idea, passive_request
        self.assertTrue(passive_idea("The couple walks through a field of blooming cherry blossoms."))
        self.assertFalse(passive_idea("The wife guides the man through a crowded marketplace."))
        self.assertTrue(passive_request({"subject": "a couple watching fireworks", "constraints": ""}))
        self.assertFalse(passive_request({"subject": "a man and his wife exploring japan", "constraints": ""}))

    def test_brainstorm_picks_at_most_one_passive_event(self):
        candidates = [("The couple marvels at a neon sign.", .2), ("They stand in awe before a temple gate.", .2),
                      ("They walk through red torii gates.", .2), ("He drops his ice cream on her shoe.", .9),
                      ("She haggles with a fish vendor.", .9)]
        for seed in range(20):
            chosen = pick_events(candidates, 4, random.Random(seed))
            from goated_prompter.features.dataset.quality import passive_idea
            self.assertLessEqual(sum(passive_idea(event) for event in chosen), 1, chosen)
        everything = pick_events(candidates, 5, random.Random(1), limit_passive=False)
        self.assertEqual(len(everything), 5, "A request for watching keeps every candidate.")
