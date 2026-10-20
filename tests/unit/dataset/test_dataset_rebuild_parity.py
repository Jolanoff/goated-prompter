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
from tests.support.dataset_scenes import composer_user


class RebuildParityTests(unittest.TestCase):
    def setUp(self):
        self.data = {**default_dataset_draft(), "subject": "Two adults reading", "amount": 3,
                     "seed": 73, "seed_mode": "fixed", "source_mode": "guided",
                     "inputs": "Read on a bench\nRead beside a fountain"}
        self.value = {"path": "character", "summary": "Two adults reading", "fixed": "The readers",
                      "randomized": "Light and framing", "must": [], "avoid": [], "characters": [
                          {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1},
                          {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]}
        self.brief = understanding.apply_rules(self.value, self.data)

    def test_guided_sources_reach_understanding_and_are_copied_into_brief(self):
        user = json.loads(understanding.instruction(self.data).user_message)
        self.assertEqual(user["guided_inputs"], ["Read on a bench", "Read beside a fountain"])
        self.assertEqual(self.brief["input"]["guided_inputs"], user["guided_inputs"])
        self.assertEqual(self.brief["input"]["seed"], 73)
        self.assertEqual(understanding.instruction(self.data).seed, 73)

    def test_the_composer_gets_each_images_guided_input_in_slot_order(self):
        self.assertEqual(scenes.slot_inputs(self.brief), {1: "Read on a bench", 2: "Read beside a fountain", 3: "Read on a bench"})
        brief = {**self.brief, "_family": "qwen"}
        prompt = scenes.compose_instruction(brief, [{"image": 2, "input": "Read beside a fountain"}])
        self.assertEqual(composer_user(prompt.user_message)["images"], [{"image": 2, "input": "Read beside a fountain"}])
        self.assertIn(scenes.GUIDED_RULE, prompt.system_message)
        self.assertEqual(prompt.seed, 73)

    def test_adult_composer_does_not_invent_bodies_from_gender(self):
        brief = {**self.brief, "path": "nsfw_character", "_family": "qwen",
                 "must": ["The man has long braided hair; the woman has a shaved head"]}
        prompt = scenes.compose_instruction(brief, [{"image": 1}])
        user = composer_user(prompt.user_message)
        self.assertEqual(user["understanding"]["characters"], brief["characters"])
        self.assertEqual(user["understanding"]["must"], brief["must"])
        self.assertNotIn("no braided", prompt.system_message + prompt.user_message)

    def test_guided_retry_asks_again_only_for_the_failed_image_with_its_own_input(self):
        backend = MockBackend()
        calls = []
        def generate(prompt):
            calls.append(prompt)
            user = composer_user(prompt.user_message)
            labels = [person["label"] for person in user["understanding"]["characters"]]
            out = []
            for row in user["images"]:
                cast = ["stranger"] if len(calls) == 1 and row["image"] == 2 else labels  # reject image 2 once
                out.append({"subjects": {label: {field: f"visible{row['image']}{label}{field}".replace(" ", "")
                                                 for field in scenes.SUBJECT_FIELDS} for label in cast},
                            "position": {label: "seated" for label in cast}, "actions": f"{' and '.join(cast)}: {row['input']}", "space": f"library {row['image']}",
                            "lighting": "daylight", "mood": "calm", "camera": "wide", "extras": f"books{row['image']}"})
            return json.dumps({"scenes": out})
        with patch.object(backend, "generate", side_effect=generate), patch.object(scenes, "create_backend", return_value=backend):
            result = scenes.write_scenes({"backend": "mock"}, GoatedPrompterRequest(idea="reading"), self.brief,
                                         progress=lambda _message: None)
        self.assertEqual([scene["actions"].split(": ", 1)[1] for scene in result["scenes"]],
                         ["Read on a bench", "Read beside a fountain", "Read on a bench"])
        self.assertEqual([row["input"] for row in composer_user(calls[0].user_message)["images"]],
                         ["Read on a bench", "Read beside a fountain", "Read on a bench"])
        self.assertEqual(composer_user(calls[1].user_message)["images"], [{"image": 2, "input": "Read beside a fountain"}])
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
                patch.object(backend, "generate", return_value="Two adults reading in a library.") as generate:
            result = write_prompts({"backend": "mock"}, GoatedPrompterRequest(idea="reading", planning_mode="Direct"),
                                   self.brief, [scene], progress=lambda _message: None)
        self.assertEqual(len(result), 1)
        self.assertEqual(generate.call_args.args[0].seed, 73)

    def test_confirmation_rechecks_adults_and_animal_eligibility(self):
        for request, label in (("A nude 16-year-old", "person"), ("A dog in a sexual scene", "dog")):
            data = {**self.data, "subject": request, "nsfw": True}
            brief = {**self.brief, "path": "nsfw_character", "input": understanding.copied_input(data),
                     "characters": [{"label": label, "gender": "custom", "custom": label, "pronoun": "it"}], "people": 1}
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    understanding.confirm(brief)
