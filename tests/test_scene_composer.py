"""Strict Composer JSON, bounded chunk-local retry and durable resume contracts."""

import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_coverage import effective_coverage_plan
from goated_prompter.prompting.scene_planner import scene_composer_instruction, idea_planner_instruction
from goated_prompter.scene_planner import SCENE_COMPOSER_CHUNK_SIZE, ScenePlanner, validate_scene_plan, reusable_scene_plan
from tests.test_dataset_geometry import character_geometry
from tests.test_dataset_quality_planning import draft, run, saved


def rows(amount=10):
    return [{"index": index, "idea": f"Exploring exhibit {index}", "scene": f"She examines exhibit {index} from a front three-quarter viewpoint.",
             "geometry": character_geometry(action_focus=f"examining exhibit {index}")}
            for index in range(1, amount + 1)]


class SceneComposerTests(unittest.TestCase):
    def compose(self, outputs, amount=10, update=None):
        session = Mock()
        session.generate.side_effect = outputs
        data = draft(amount=amount)
        result = ScenePlanner(lambda: None).compose(session=session, data=data, coverage=effective_coverage_plan(data),
            ideas=[{"index": row["index"], "idea": row["idea"]} for row in rows(amount)], progress=lambda _: None, plan_update=update)
        return result, session

    def test_valid_json_count_indexes_exact_ideas_and_canonical_geometry(self):
        expected = rows(4)
        result, session = self.compose([json.dumps(expected)], amount=4)
        self.assertEqual(result, expected)
        self.assertEqual(validate_scene_plan(json.dumps(expected), 4, require_geometry=True), expected)
        context = json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual([item["index"] for item in context["assignments"]], [1, 2, 3, 4])

    def test_output_contract_is_explicit_and_example_does_not_anchor_creativity(self):
        data = draft(amount=1)
        system = scene_composer_instruction(data, effective_coverage_plan(data), rows(1)).system_message
        for phrase in ("Return ONLY one valid JSON array", "character must be [", "character must be ]", "double-quoted keys",
                       "no YAML", "no numbered sections", "no trailing commas", "GAZE_DIRECTION", "not put emotions",
                       "EXPRESSION", 'pose_type="custom"', "pose_detail", "relative"):
            self.assertIn(phrase, system)
        self.assertIn("IDEA SPATIAL CLARITY", idea_planner_instruction(data, effective_coverage_plan(data)).system_message)

    def test_yaml_failure_has_json_specific_repair_not_python_exception(self):
        bad = "1\nscene: A woman examines an exhibit\ngeometry:\n  framing: full body"
        with self.assertLogs("goated_prompter.scene_planner", level="WARNING") as logs:
            result, session = self.compose([bad, json.dumps(rows(1))], amount=1)
        self.assertEqual(result, rows(1))
        repair = session.generate.call_args_list[1].args[0]
        for phrase in ("SCENE OUTPUT FORMAT CORRECTION", "valid JSON array", "begin with [", "end with ]", "Do not output YAML", "Do not brainstorm again"):
            self.assertIn(phrase, repair.system_message)
        self.assertNotIn("Extra data:", repair.system_message)
        self.assertEqual(json.loads(repair.user_message)["previous_response"], bad)
        self.assertTrue(any("Extra data:" in log for log in logs.output))
        self.assertEqual(repair.diagnostic_stage, "dataset:scene_composer:repair")

    def test_chunks_4_4_2_and_middle_retry_does_not_repeat_valid_chunks(self):
        self.assertEqual(SCENE_COMPOSER_CHUNK_SIZE, 4)
        all_rows = rows()
        snapshots = []
        result, session = self.compose([json.dumps(all_rows[:4]), "1\nscene: broken", json.dumps(all_rows[4:8]),
                                        json.dumps(all_rows[8:])], update=lambda state: snapshots.append(json.loads(json.dumps(state))))
        self.assertEqual(result, all_rows)
        assignments = [json.loads(call.args[0].user_message)["assignments"] for call in session.generate.call_args_list]
        self.assertEqual([[row["index"] for row in batch] for batch in assignments],
                         [[1, 2, 3, 4], [5, 6, 7, 8], [5, 6, 7, 8], [9, 10]])
        self.assertEqual([row["scene_status"] for row in snapshots[0]], ["valid"] * 4 + ["not_generated"] * 6)
        self.assertEqual([row["scene_status"] for row in snapshots[1]], ["valid"] * 8 + ["not_generated"] * 2)
        self.assertEqual([row["scene_status"] for row in snapshots[2]], ["valid"] * 10)

    def test_twenty_five_scenes_use_seven_small_chunks(self):
        expected = rows(25)
        result, session = self.compose([json.dumps(expected[start:start + 4]) for start in range(0, 25, 4)], amount=25)
        self.assertEqual(result, expected)
        self.assertEqual([json.loads(call.args[0].user_message)["amount"] for call in session.generate.call_args_list], [4] * 6 + [1])

    def test_duplicate_scene_across_chunks_is_repaired_only_at_its_index(self):
        expected = rows(5)
        duplicate = {**expected[4], "scene": expected[0]["scene"]}
        result, session = self.compose([json.dumps(expected[:4]), json.dumps([duplicate]), json.dumps([expected[4]])], amount=5)
        self.assertEqual(result, expected)
        self.assertEqual([json.loads(call.args[0].user_message)["assignments"][0]["index"]
                          for call in session.generate.call_args_list], [1, 5, 5])
        self.assertIn("duplicates", session.generate.call_args.args[0].system_message)

    def test_exact_fixed_idea_whitespace_is_not_paraphrased_by_parser(self):
        expected = rows(1)[0]
        expected["idea"] = "  Examining exhibit 1  "
        self.assertEqual(validate_scene_plan(json.dumps([expected]), 1)[0]["idea"], expected["idea"])

    def test_failed_chunk_preserves_fixed_ideas_and_validated_first_chunk_then_resumes(self):
        expected = rows()
        outputs = [json.dumps([{key: row[key] for key in ("index", "idea")} for row in expected]),
                   json.dumps(expected[:4]), "1\nscene: broken", "1\nscene: broken"]
        # Test the actual service's partial callback, not just a private planner snapshot.
        partials = []
        from contextlib import contextmanager
        from goated_prompter.dataset import DatasetService
        from goated_prompter.core import GoatedPrompterRequest
        session, backend = Mock(), Mock()
        session.generate.side_effect = outputs
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        data = draft(amount=10, source_mode="guided", inputs="\n".join(row["idea"] for row in expected))
        with patch("goated_prompter.dataset.create_backend", return_value=backend), self.assertRaises(BackendGenerationError):
            DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"]), data,
                                                lambda _: None, partials.append)
        restored = validate_dataset_draft({**data, "scene_plan": partials[-1]["scene_plan"],
                                         "scene_plan_signature": partials[-1]["scene_plan_signature"]})
        self.assertEqual([row["idea"] for row in restored["scene_plan"]], [row["idea"] for row in expected])
        self.assertEqual([row["scene_status"] for row in restored["scene_plan"]], ["valid"] * 4 + ["not_generated"] * 6)
        result, resumed, _ = run(restored, [json.dumps(expected[4:8]), json.dumps(expected[8:])], scenes_only=True)
        self.assertEqual([json.loads(call.args[0].user_message)["assignments"][0]["index"] for call in resumed.generate.call_args_list], [5, 9])
        self.assertEqual(result["scene_plan"][:4], restored["scene_plan"][:4])

    def test_geometry_only_repair_preserves_exact_idea_and_other_scene(self):
        expected = rows(2)
        expected[0]["idea"] = "Woman arguing with pigeons in Central Park using a megaphone."
        expected[0]["scene"] = "She argues with pigeons in Central Park through a megaphone."
        expected[0]["geometry"]["action_focus"] = "arguing with pigeons through a megaphone"
        bad = {**expected[0], "geometry": {**expected[0]["geometry"], "gaze_direction": "frustrated"}}
        data, session = draft(), Mock()
        session.generate.side_effect = [json.dumps([bad, expected[1]]), json.dumps([expected[0]])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data, coverage=effective_coverage_plan(data),
            ideas=[{key: row[key] for key in ("index", "idea")} for row in expected], progress=lambda _: None)
        self.assertEqual(result, expected)
        repair = session.generate.call_args_list[1].args[0]
        self.assertIn("not emotion", repair.system_message)
        self.assertNotIn("Expected one of", repair.system_message)
        self.assertEqual(json.loads(repair.user_message)["assignments"][0]["idea"], expected[0]["idea"])
        self.assertEqual(session.generate.call_count, 2)

    def test_geometry_repair_yaml_failure_still_uses_format_specific_heading(self):
        expected = rows(1)[0]
        session = Mock()
        session.generate.side_effect = ["1\nscene: repaired", json.dumps([expected])]
        data = draft(amount=1)
        repaired = ScenePlanner(lambda: None).repair_scene(session=session, data=data, coverage=effective_coverage_plan(data),
            row=expected, errors=["Choose coherent staging."], progress=lambda _: None)
        self.assertEqual(repaired, expected)
        self.assertIn("SCENE OUTPUT FORMAT CORRECTION", session.generate.call_args.args[0].system_message)

    def test_canonical_shoe_crop_gets_framing_specific_repair_with_idea_unchanged(self):
        expected = rows(1)[0]
        expected.update(idea="walking in oversized shoes", scene="She walks through an exhibit wearing oversized shoes.")
        expected["geometry"] = character_geometry(action_focus="walking in oversized shoes", visibility_focus=["face", "shoes"])
        bad = {**expected, "geometry": {**expected["geometry"], "framing": "face_close_up"}}
        data, session = draft(amount=1), Mock()
        session.generate.side_effect = [json.dumps([bad]), json.dumps([expected])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data, coverage=effective_coverage_plan(data),
            ideas=[{"index": 1, "idea": expected["idea"]}], progress=lambda _: None)
        self.assertEqual(result, [expected])
        self.assertIn("wider crop", session.generate.call_args.args[0].system_message)
        self.assertEqual(json.loads(session.generate.call_args.args[0].user_message)["assignments"][0]["idea"], expected["idea"])

    def test_custom_pose_survives_composition_and_validated_writer_handoff(self):
        expected = rows(1)[0]
        expected["geometry"].update(pose_type="custom", pose_detail="one-foot balance while leaning sideways",
                                    expression="custom", expression_detail="cheeks puffed and one eyebrow raised")
        ideas = [{"index": 1, "idea": expected["idea"]}]
        result, session, _ = run(draft(amount=1), [json.dumps(ideas), json.dumps([expected]), "person_token examines exhibit 1."])
        self.assertEqual(session.generate.call_count, 3)
        self.assertEqual(result["scene_plan"][0]["geometry"], expected["geometry"])
        writer = session.generate.call_args.args[0]
        self.assertIn(json.dumps(expected["geometry"]), writer.user_message)
        self.assertIn("Preserve custom pose_detail and expression_detail", writer.user_message)

    def test_no_silent_yaml_fences_or_multi_array_salvage(self):
        for response in ("Here is the result:\n" + json.dumps(rows(1)), "```json\n" + json.dumps(rows(1)) + "\n```",
                         json.dumps(rows(1)) + json.dumps(rows(1))):
            with self.subTest(response=response), self.assertRaises(ValueError):
                validate_scene_plan(response, 1)

    def test_saved_legacy_geometry_preserves_ideas_and_requires_local_repair(self):
        expected = rows(1)[0]
        legacy = {**expected, "geometry": {"framing": "full body", "gaze": "shocked", "pose": "strange balance"}}
        data = validate_dataset_draft(saved(draft(amount=1), [legacy]))
        self.assertEqual(data["scene_plan"][0]["idea"], expected["idea"])
        self.assertEqual(data["scene_plan"][0]["scene"], expected["scene"])
        self.assertEqual(data["scene_plan"][0]["geometry"], {"framing": "full_body", "expression": "shocked"})
        self.assertEqual(data["scene_plan"][0]["scene_status"], "geometry_warning")
        self.assertIsNotNone(reusable_scene_plan(data, effective_coverage_plan(data), require_scenes=False))
        result, session, _ = run(data, [json.dumps([expected]), "person_token examines exhibit 1."])
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(session.generate.call_args_list[0].args[0].diagnostic_stage, "dataset:scene_composer:repair")
        self.assertEqual(result["scene_plan"][0]["idea"], expected["idea"])


if __name__ == "__main__":
    unittest.main()
