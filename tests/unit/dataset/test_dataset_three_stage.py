"""Three-stage Dataset: character definitions, ideas that carry finished scenes, and the cast-aware writer."""

import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import COPIED_SCENE, DatasetIdeasService, creative_directions, ideas_instruction
from goated_prompter.features.dataset.plan import ScenePlanner
from goated_prompter.features.dataset.prompting import anima_count_tags, cast_error, dataset_instruction
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

    def test_matching_library_prompts_reach_ideas_as_quality_examples(self):
        library_path("Generic").write_text(LIKED, encoding="utf-8")
        instruction = ideas_instruction(self.data, dataset_assignments(self.data), rng=random.Random(1))
        self.assertEqual(json.loads(instruction.user_message)["library_examples"], [LIKED])
        self.assertEqual(instruction.reference_prompts, (LIKED,))
        self.assertIn("LIBRARY EXAMPLES", instruction.system_message)

    def test_without_a_matching_library_no_examples_are_sent(self):
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        self.assertNotIn("library_examples", json.loads(instruction.user_message))
        self.assertEqual(instruction.reference_prompts, ())

    def test_a_scene_that_copies_a_library_example_is_rejected(self):
        library_path("Generic").write_text(LIKED, encoding="utf-8")
        copied = dataset_idea_fixture(idea="Flour mishap", scene=LIKED.split("\n\n", 1)[1])
        session = Mock()
        session.generate.return_value = json.dumps([copied])
        service = DatasetIdeasService(lambda: None)
        with self.assertRaisesRegex(BackendGenerationError, "copied wording from a saved library prompt"):
            service.run(session=session, data=self.data, assignments=dataset_assignments(self.data),
                        progress=lambda _message: None)
        rows = service.run(session=session, data=self.data, assignments=dataset_assignments(self.data),
                           progress=lambda _message: None, allow_partial=True)
        self.assertEqual((rows[0]["idea_status"], rows[0]["failure_reason"]), ("failed", COPIED_SCENE))

    def test_an_original_scene_passes_alongside_library_examples(self):
        library_path("Generic").write_text(LIKED, encoding="utf-8")
        session = Mock()
        session.generate.return_value = json.dumps([dataset_idea_fixture()])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=self.data,
            assignments=dataset_assignments(self.data), progress=lambda _message: None)
        self.assertEqual(rows[0]["scene"], dataset_idea_fixture()["scene"])

    def test_ideas_prompt_asks_for_finished_scenes_with_the_whole_cast_in_frame(self):
        rules = " ".join(ideas_instruction(self.data, dataset_assignments(self.data)).system_message.split())
        self.assertIn("idea, the core event in one line, and scene", rules)
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
        self.assertEqual(sent, [directions[index] for index in range(1, 8)])

    def test_library_chunks_share_one_scenario_order_without_repeats(self):
        directory = Path(tempfile.mkdtemp())
        with patch.dict(os.environ, {LIBRARY_DIR_ENV: str(directory)}):
            prompts = [f"1girl, 1boy, place {name}\n\nA couple visits the {name}." for name in
                       ("harbor", "museum", "arcade", "bakery", "observatory", "greenhouse", "ferry")]
            library_path("Anima").write_text("\n---\n".join(prompts), encoding="utf-8")
            data = valid_draft(amount=7, target="Anima", source_mode="library",
                               _confirmed_intent=dataset_understanding_fixture(character_count=2))
            backend = CaptureBackend()
            ScenePlanner(lambda: None).plan_ideas(session=backend, data=data, assignments=dataset_assignments(data),
                                                  progress=lambda _message: None, allow_partial=True)
        scenarios = [row["library_scenario"] for call in backend.calls
                     for row in json.loads(call.user_message)["assignments"]]
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(sorted(scenarios), sorted(prompts))


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
        self.assertGreater(firsts.count("rare event"), firsts.count("obvious event") * 4)
        self.assertIn("obvious event", firsts)

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
