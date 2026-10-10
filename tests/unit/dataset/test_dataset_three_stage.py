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
from goated_prompter.features.dataset.ideas import COPIED_SCENE, DatasetIdeasService, ideas_instruction
from goated_prompter.features.dataset.prompting import anima_count_tags, dataset_instruction
from goated_prompter.features.dataset.understanding import (_expand_understanding, understanding_instruction,
    validate_understanding)
from goated_prompter.prompt_library import LIBRARY_DIR_ENV, library_path
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support.dataset import saved_scene, valid_draft

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

    def test_anima_writer_starts_with_count_and_named_character_tags(self):
        system = self.writer([NARUTO, character(name="Hinata Hyuga", sex="female")], target="Anima").system_message
        self.assertIn("Start the tag block with these count tags: 1girl, 1boy.", system)
        self.assertIn("Danbooru character tag and series tag", system)
        open_cast = self.writer([NARUTO, COMPANION], target="Anima").system_message
        self.assertIn("count tags that match the characters in this scene", open_cast)

    def test_a_locked_anima_trigger_keeps_ownership_of_character_tags(self):
        system = self.writer([NARUTO], target="Anima", trigger="1boy, uzumaki naruto", trigger_at_start=True,
                             trigger_connected=True, expand_trigger=False).system_message
        self.assertNotIn("ANIMA CAST TAGS", system)

    def test_other_targets_and_briefs_without_characters_get_no_tag_section(self):
        self.assertNotIn("ANIMA CAST TAGS", self.writer([NARUTO]).system_message)
        self.assertNotIn("CAST (", self.writer([]).system_message)
