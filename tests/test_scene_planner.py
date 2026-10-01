"""Dataset-only planning contracts, schema, retries, fallback and writer handoff."""

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.dataset_coverage import effective_coverage_plan
from goated_prompter.prompting import dataset as dataset_prompts
from goated_prompter.prompting.scene_planner import scene_planner_instruction
from goated_prompter.scene_planner import ScenePlanner, validate_scene_plan


def draft(**changes):
    return {**default_dataset_draft(), "amount": 2, "trigger": "person_token",
            "subject": "An adult character reading at home.", **changes}


def scene_rows(amount=2):
    return [{"index": index, "scene": f"Reading on a red couch beside window {index}, face visible in soft daylight."}
            for index in range(1, amount + 1)]


class ScenePlannerTests(unittest.TestCase):
    def test_whole_batch_context_preserves_guided_inputs_and_all_settings(self):
        data = draft(amount=3, source_mode="guided", inputs="sitting on a red couch reading a book\nlying on floor",
                     constraints="No outdoor scenes; only neutral expressions; same outfit in every image.",
                     coverage_enabled=True, variety="Wide", target="Ideogram4", visual_style="Custom",
                     custom_style="Ink drawing", trigger_type="Custom", custom_type="A recurring adult character")
        coverage = effective_coverage_plan(data)
        instruction = scene_planner_instruction(data, coverage, "gemma")
        context = json.loads(instruction.user_message)
        for key in ("amount", "subject", "source_mode", "trigger_type", "custom_type", "visual_style",
                    "custom_style", "variety", "constraints"):
            self.assertEqual(context[key], data[key])
        self.assertEqual(context["assignments"], coverage["plan"])
        self.assertEqual(context["assignments"][2]["input"], context["assignments"][0]["input"])
        self.assertEqual(context["target_context"], "Ideogram4")
        self.assertEqual(instruction.model_family, "gemma")
        self.assertIn("input is authoritative", instruction.system_message)
        self.assertIn("Do not generate finished image prompts", instruction.system_message)
        self.assertIn("constraints", instruction.system_message)
        for key in ("trigger_at_start", "trigger_connected", "director_preset", "results", "quality_report"):
            self.assertNotIn(key, context)
        self.assertNotIn("high_level_description", instruction.system_message)
        other = scene_planner_instruction({**data, "target": "Generic"}, coverage, "gemma")
        self.assertEqual(other.system_message, instruction.system_message)

    def test_disabled_coverage_has_no_hidden_facet_assignments(self):
        data = draft()
        coverage = effective_coverage_plan(data)
        coverage["plan"][0]["facets"] = {"setting": "urban street"}
        context = json.loads(scene_planner_instruction(data, coverage).user_message)
        self.assertTrue(all(row["facets"] == {} for row in context["assignments"]))

    def test_guidance_is_type_specific_and_variety_uses_existing_values(self):
        for kind in dataset_prompts.DATASET_TYPES:
            data = draft(trigger_type=kind)
            context = json.loads(scene_planner_instruction(data, effective_coverage_plan(data)).user_message)
            self.assertTrue(context["type_guidance"])
        data = draft(trigger_type="Object / product")
        instruction = scene_planner_instruction(data, effective_coverage_plan(data))
        self.assertIn("Do not impose human poses or expressions", json.loads(instruction.user_message)["type_guidance"])
        for variety in dataset_prompts.DATASET_VARIETY:
            self.assertIn(variety, instruction.system_message)

    def test_strict_schema_accepts_paragraphs_longer_than_old_limit(self):
        rows = [{"index": 1, "scene": " ".join(f"detail{index}" for index in range(60))}]
        self.assertGreater(len(rows[0]["scene"]), 200)
        self.assertEqual(validate_scene_plan(json.dumps(rows), 1), rows)

    def test_strict_schema_rejects_invalid_rows_and_containers(self):
        invalid = [None, "not json", "```json\n[]\n```", "{}", "[]",
                   '[{"index": 1, "index": 1, "scene": "Reading"}]',
                   json.dumps([{"index": True, "scene": "Reading"}]),
                   json.dumps([{"index": 2, "scene": "Reading"}]),
                   json.dumps([{"index": 1, "scene": "Reading", "extra": True}]),
                   json.dumps([{"index": 1, "scene": " "}]),
                   json.dumps([{"index": 1, "scene": None}]),
                   json.dumps([{"index": 1, "scene": "x" * 1601}]),
                   json.dumps([{"index": 1, "scene": "word " * 121}]),
                   json.dumps([{"index": 1, "scene": "Reading\nExplanation"}]),
                   json.dumps([{"index": 1, "scene": "```Reading```"}])]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                validate_scene_plan(raw, 1)
        for rows in ([{"index": 1, "scene": "A"}, {"index": 1, "scene": "B"}],
                     [{"index": 1, "scene": " Reading "}, {"index": 2, "scene": "reading"}]):
            with self.assertRaises(ValueError):
                validate_scene_plan(json.dumps(rows), 2)

    def test_one_repair_then_success(self):
        data, session, progress = draft(), Mock(), []
        session.generate.side_effect = ["invalid", json.dumps(scene_rows())]
        result = ScenePlanner(lambda: None).plan_batch(
            session=session, data=data, coverage=effective_coverage_plan(data), progress=progress.append)
        self.assertEqual(result, scene_rows())
        self.assertEqual(session.generate.call_count, 2)
        first, repair = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(first.user_message, repair.user_message)
        self.assertIn("FORMAT CORRECTION", repair.system_message)
        self.assertEqual(repair.diagnostic_stage, "dataset:scene_planner:repair")

    def test_fallback_preserves_input_after_format_or_transport_failure(self):
        for guided in (False, True):
            for error in ("[]", BackendGenerationError("engine transport failed")):
                data = draft(source_mode="guided" if guided else "random", inputs="lying on floor\nreading")
                session = Mock()
                if isinstance(error, Exception):
                    session.generate.side_effect = error
                else:
                    session.generate.return_value = error
                result = ScenePlanner(lambda: None).plan_batch(
                    session=session, data=data, coverage=effective_coverage_plan(data), progress=lambda _: None)
                self.assertEqual(session.generate.call_count, 2)
                self.assertEqual([row["scene"] for row in result],
                                 ["lying on floor", "reading"] if guided else [data["subject"]] * 2)

    def test_cancellation_is_not_swallowed_as_planner_failure(self):
        class Cancelled(Exception):
            pass
        checkpoint = Mock(side_effect=[None, Cancelled()])
        session, data = Mock(), draft()
        session.generate.return_value = json.dumps(scene_rows())
        with self.assertRaises(Cancelled):
            ScenePlanner(checkpoint).plan_batch(session=session, data=data,
                coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 1)

    def test_instruction_validation_failure_also_retries_then_falls_back(self):
        data, session = draft(), Mock()
        session.validate_instruction.side_effect = BackendGenerationError("unsupported planning response")
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(session.validate_instruction.call_count, 2)
        session.generate.assert_not_called()
        self.assertEqual([row["scene"] for row in rows], [data["subject"]] * 2)

    def test_no_second_planner_and_normal_builder_is_unchanged(self):
        self.assertFalse(hasattr(dataset_prompts, "dataset_plan_instruction"))
        self.assertFalse(hasattr(DatasetService, "_plan"))
        for mode in ("Enhance", "Character", "Photography", "Product", "Archviz", "Image Edit",
                     "Style Transfer", "Dataset Caption", "Video", "Custom"):
            with self.subTest(mode=mode):
                instruction = assemble_instruction(GoatedPrompterRequest(idea="A red bicycle", mode=mode), text_only=True)
                self.assertNotIn("Scene Planner", instruction.system_message)
                self.assertIn("Creativity — Balanced", instruction.system_message)

    def test_pipeline_hands_same_authoritative_scene_to_writer_and_format_retry(self):
        data = draft(amount=1, source_mode="guided", inputs="reading on a red couch", variety="Wide")
        planned = scene_rows(1)
        session = Mock()
        session.generate.side_effect = [json.dumps(planned), '{"prompt":',
                                       "An adult person_token reading on a red couch in soft daylight."]
        backend = Mock(name="scene-test")
        backend.name = "scene-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        request = GoatedPrompterRequest(idea=data["subject"], creativity="Dice")
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _: None, lambda _: None)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(len(calls), 3)
        for writer in calls[1:]:
            self.assertIn(planned[0]["scene"], writer.user_message)
            self.assertIn("SCENE PLANNER AUTHORITY", writer.system_message)
            self.assertIn("Creativity — Strict", writer.system_message)
            self.assertIn("Director supplies rendering technique", writer.system_message)
            self.assertIsNone(writer.stream_character_limit)
        self.assertEqual(calls[1].user_message, calls[2].user_message)
        self.assertEqual(result["prompts"][0]["input"], "reading on a red couch")

    def test_failed_planning_still_completes_dataset_with_original_guided_input(self):
        data = draft(amount=1, source_mode="guided", inputs="lying on floor", coverage_enabled=True)
        session = Mock()
        session.generate.side_effect = ["not json", "[]", "person_token lying on floor."]
        backend = Mock()
        backend.name = "scene-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 1)
        writer = session.generate.call_args_list[-1].args[0]
        self.assertIn("<scene>\nlying on floor\n</scene>", writer.user_message)
        self.assertIn("COVERAGE ASSIGNMENT", writer.user_message)
        self.assertEqual(result["prompts"][0]["input"], "lying on floor")

    def test_large_batch_can_stream_past_single_prompt_limit_but_remains_bounded(self):
        data = draft(amount=25)
        instruction = scene_planner_instruction(data, effective_coverage_plan(data))
        rows = [{"index": index, "scene": " ".join(f"detail{index}x{word}" for word in range(40))}
                for index in range(1, 26)]
        text = json.dumps(rows)
        self.assertGreater(len(text), 7000)
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.__iter__ = Mock(return_value=iter([
            ("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]}) + "\n").encode(),
            b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n',
        ]))
        transport = Mock()
        transport.__enter__ = Mock(return_value=response)
        transport.__exit__ = Mock(return_value=False)
        backend = OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "test",
                                           "_activity_callback": lambda _: None})
        with patch("goated_prompter.backends.openai_compatible.urlopen", return_value=transport):
            self.assertEqual(validate_scene_plan(backend.generate(instruction), 25), rows)
        chunk = {"choices": [{"delta": {"content": "x" * (instruction.stream_character_limit + 1)}, "finish_reason": None}]}
        with self.assertRaisesRegex(BackendGenerationError, "generated characters"):
            backend._stream_response([("data: " + json.dumps(chunk)).encode()], False,
                                     instruction.hard_max_tokens, instruction.stream_character_limit)


if __name__ == "__main__":
    unittest.main()
