"""Migration regressions for the rebuilt Dataset path; no real generation."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.dataset.v2 import scenes, understanding
from goated_prompter.features.dataset.v2.prompts import write_prompts
from goated_prompter.backends.mock import MockBackend


class RebuildParityTests(unittest.TestCase):
    def setUp(self):
        self.data = {**default_dataset_draft(), "subject": "Two adults reading", "amount": 3,
                     "seed": 73, "seed_mode": "fixed", "source_mode": "guided",
                     "inputs": "Read on a bench\nRead beside a fountain"}
        self.value = {"path": "character", "summary": "Two adults reading", "fixed": "The readers",
                      "randomized": "Light and framing", "must": [], "avoid": [], "characters": [
                          {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                          {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]}
        self.brief = understanding.apply_rules(self.value, self.data, Mock())

    def test_guided_sources_reach_understanding_and_are_copied_into_brief(self):
        user = json.loads(understanding.instruction(self.data).user_message)
        self.assertEqual(user["guided_inputs"], ["Read on a bench", "Read beside a fountain"])
        self.assertEqual(self.brief["input"]["guided_inputs"], user["guided_inputs"])
        self.assertEqual(self.brief["input"]["seed"], 73)
        self.assertEqual(understanding.instruction(self.data).seed, 73)

    def test_concepts_keep_guided_assignment_order_when_a_chunk_is_retried(self):
        brief = {**self.brief, "_family": "qwen"}
        prompt = scenes.concept_instruction(brief, 2, [{"place": "first"}])
        user = json.loads(prompt.user_message)
        self.assertEqual(user["assignments"], [
            {"index": 2, "input": "Read beside a fountain"}, {"index": 3, "input": "Read on a bench"}])
        self.assertEqual(prompt.seed, 73)

    def test_sexual_planner_does_not_invent_anatomy_from_gender(self):
        brief = {**self.brief, "path": "nsfw_character", "_family": "qwen",
                 "must": ["The man has a vagina; the woman has a penis"]}
        for prompt in (scenes.concept_instruction(brief, 3, []), scenes.staging_instruction(brief, [])):
            user = json.loads(prompt.user_message)
            self.assertEqual(user["characters"], brief["characters"])
            self.assertEqual(user["must"], brief["must"])
            self.assertNotIn("no vagina", prompt.system_message + prompt.user_message)

    def test_guided_retry_keeps_sources_attached_through_staging_and_description(self):
        backend = MockBackend()
        calls = []
        def generate(prompt):
            calls.append(prompt)
            user = json.loads(prompt.user_message)
            labels = [person["label"] for person in user["characters"]]
            if prompt.diagnostic_stage.endswith(":concepts"):
                concepts = [{"place": f"location {row['index']}", "position_name": "reading",
                             "position": f"variation {row['index']}", "lighting": "daylight", "camera": "wide",
                             "looks": {label: "short hair" for label in labels}} for row in user["assignments"]]
                if len(calls) == 1:
                    concepts[1] = dict(concepts[0])  # Reject slot 2; do not consume slot 3's input.
                return json.dumps({"concepts": concepts})
            if prompt.diagnostic_stage.endswith(":stagings"):
                self.assertEqual([row["input"] for row in user["concepts"]],
                                 ["Read on a bench", "Read beside a fountain", "Read on a bench"])
                return json.dumps({"stagings": [{"reach": "The book is reachable", "actions": row["input"],
                    "position": {label: "seated" for label in labels}} for row in user["concepts"]]})
            self.assertEqual([row["concept"]["input"] for row in user["scenes"]],
                             ["Read on a bench", "Read beside a fountain", "Read on a bench"])
            return json.dumps({"scenes": [{"subjects": {label: {field: "visible" for field in scenes.SUBJECT_FIELDS}
                for label in labels}, "space": "library", "lighting": "daylight", "mood": "calm", "camera": "wide",
                "extras": "books"} for _row in user["scenes"]]})
        with patch.object(backend, "generate", side_effect=generate), patch.object(scenes, "create_backend", return_value=backend), \
                patch.object(scenes, "DebugTrace"):
            result = scenes.write_scenes({"backend": "mock", "dataset_vocabulary": False},
                GoatedPrompterRequest(idea="reading"), self.brief, progress=lambda _message: None)
        self.assertEqual([scene["actions"] for scene in result["scenes"]],
                         ["Read on a bench", "Read beside a fountain", "Read on a bench"])
        # Image 3's valid concept is kept at once in image 3; only image 2 is asked for again, with its own input.
        self.assertEqual(json.loads(calls[1].user_message)["assignments"], [{"index": 2, "input": "Read beside a fountain"}])
        self.assertEqual(json.loads(calls[1].user_message)["images"], [2])
        self.assertTrue(all(prompt.seed == 73 for prompt in calls))

    def test_random_source_does_not_apply_inactive_guided_inputs(self):
        data = {**self.data, "source_mode": "random"}
        self.assertEqual(understanding.copied_input(data)["guided_inputs"], [])
        self.assertNotIn("guided_inputs", json.loads(understanding.instruction(data).user_message))

    def test_scenes_only_runner_never_calls_prompt_writer(self):
        result = {"scenes": [{"actions": "reading"}], "written": 1, "requested": 1, "complete": True, "missing": []}
        job = Mock()
        job.commit.side_effect = lambda apply, **_kwargs: apply()
        job.lock = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        with patch.object(runner, "create_backend"), patch.object(runner, "write_scenes", return_value=result), \
                patch.object(runner, "write_prompts", return_value=[]) as writer:
            runner.run_dataset_v2_scenes(SimpleNamespace(), job, GoatedPrompterRequest(idea="reading"),
                {"backend": "mock"}, {"brief": self.brief, "scenes_only": True})
        writer.assert_not_called()

    def test_brief_rejects_inconsistent_content_switch(self):
        with self.assertRaisesRegex(ValueError, "NSFW|path"):
            understanding.validate_brief({**self.brief, "path": "nsfw_character"})

    def test_final_builder_instruction_keeps_dataset_seed(self):
        scene = {"subjects": {}, "position": {}, "actions": "reading", "space": "library", "lighting": "daylight",
                 "mood": "calm", "camera": "wide", "extras": "shelves"}
        backend = MockBackend()
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend), \
                patch.object(backend, "generate", return_value="Two adults reading in a library.") as generate, \
                patch("goated_prompter.features.dataset.v2.prompts.DebugTrace"):
            result = write_prompts({"backend": "mock"}, GoatedPrompterRequest(idea="reading", planning_mode="Direct"),
                                   self.brief, [scene], progress=lambda _message: None)
        self.assertEqual(len(result), 1)
        self.assertEqual(generate.call_args.args[0].seed, 73)

    def test_confirmation_rechecks_adults_and_animal_eligibility(self):
        for request, label in (("A nude 16-year-old", "person"), ("A dog in a sexual scene", "dog")):
            data = {**self.data, "subject": request, "nsfw": True}
            brief = {**self.brief, "path": "nsfw_character", "input": understanding.copied_input(data),
                     "characters": [{"label": label, "gender": "custom", "custom": label, "pronoun": "it"}], "people": 1}
            with self.subTest(request=request), patch.object(understanding, "DebugTrace"):
                with self.assertRaises(ValueError):
                    understanding.confirm(brief)
