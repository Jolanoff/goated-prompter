"""Bounded scene-only recovery, durable local errors and valid-only writing."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_planner import ScenePlanner, reusable_scene_plan
from tests.test_dataset_quality_planning import draft, run, saved, scene
from tests.test_scene_composer import rows


def rear_conflict(row):
    return {**row, "geometry": {**row["geometry"], "camera_view": "direct_rear",
                               "body_orientation": "direct_rear", "face_visibility": "full"}}


def replacement(index=1):
    return scene(index, "balancing a spoon on her nose", scene="She balances a spoon on her nose.")


class DatasetRecoveryTests(unittest.TestCase):
    def plan(self, data, outputs):
        session, partials = Mock(), []
        session.generate.side_effect = outputs
        result = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None, plan_update=partials.append)
        return result, session, partials

    def test_third_scene_repair_succeeds_without_replacing_idea(self):
        for mode in ("Fast", "Quality"):
            with self.subTest(mode=mode):
                expected, data = rows(2), draft(planning_mode=mode)
                bad = rear_conflict(expected[0])
                outputs = [json.dumps([bad, expected[1]]), json.dumps([bad]), json.dumps([bad]), json.dumps([expected[0]])]
                if mode == "Quality":
                    outputs.insert(0, json.dumps([{key: row[key] for key in ("index", "idea")} for row in expected]))
                result, session, _ = self.plan(data, outputs)
                self.assertEqual(result, expected)
                stages = [call.args[0].diagnostic_stage for call in session.generate.call_args_list]
                self.assertEqual(stages.count("dataset:scene_composer:repair"), 3)
                self.assertEqual(stages.count("dataset:idea_planner"), int(mode == "Quality"))

    def test_three_failed_scene_repairs_keep_idea_and_fail_only_bad_index(self):
        for mode in ("Fast", "Quality"):
            with self.subTest(mode=mode):
                expected, data = rows(2), draft(planning_mode=mode)
                bad = rear_conflict(expected[0])
                outputs = [json.dumps([bad, expected[1]]), *[json.dumps([bad])] * 3]
                if mode == "Quality":
                    outputs.insert(0, json.dumps([{key: row[key] for key in ("index", "idea")} for row in expected]))
                result, session, _ = self.plan(data, outputs)
                self.assertEqual(result[0]["idea"], expected[0]["idea"])
                self.assertEqual(result[0]["scene_status"], "failed")
                self.assertEqual(result[0]["failure_stage"], "scene")
                self.assertNotIn("replacement_attempted", result[0])
                self.assertEqual(result[1], expected[1])
                stages = [call.args[0].diagnostic_stage for call in session.generate.call_args_list]
                self.assertEqual(stages.count("dataset:idea_planner"), int(mode == "Quality"))
                self.assertEqual(session.generate.call_count, len(outputs))

    def test_failed_repair_skips_item_and_continues_later_composer_chunk(self):
        expected, data = rows(5), draft(amount=5, source_mode="guided", inputs="\n".join(row["idea"] for row in rows(5)))
        bad = rear_conflict(expected[0])
        result, session, partials = self.plan(data, [
            json.dumps([{key: row[key] for key in ("index", "idea")} for row in expected]),
            json.dumps([bad, *expected[1:4]]), *[json.dumps([bad])] * 3, json.dumps(expected[4:])])
        self.assertEqual(result[0]["scene_status"], "failed")
        self.assertEqual(result[0]["prompt_status"], "failed")
        self.assertEqual(result[0]["idea"], expected[0]["idea"])
        self.assertIn("Direct rear", result[0]["failure_reason"])
        self.assertNotIn("Replacement", result[0]["failure_reason"])
        self.assertEqual(result[1:], expected[1:])
        self.assertEqual(len(partials[-1]), 5)
        last_context = json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual(last_context["indexes"], [5])

    def test_failed_scene_is_visible_and_does_not_call_its_writer(self):
        good = rows(2)
        bad = rear_conflict(good[0])
        result, session, _ = run(draft(planning_mode="Fast"), [json.dumps([bad, good[1]]),
            *[json.dumps([bad])] * 3, "person_token examines exhibit 2."])
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["prompts"][0]["index"], 2)
        self.assertEqual(result["scene_plan"][0]["failure_stage"], "scene")
        self.assertIn("Direct rear", result["scene_plan"][0]["failure_reason"])
        self.assertEqual(result["scene_plan"][0]["idea"], good[0]["idea"])
        self.assertEqual(session.generate.call_count, 5)
        self.assertFalse(any(call.args[0].diagnostic_stage == "dataset:1" for call in session.generate.call_args_list))
        validate_dataset_draft({**draft(planning_mode="Fast"), "scene_plan": result["scene_plan"],
            "scene_plan_signature": result["scene_plan_signature"], "results": result["prompts"]})

    def test_writer_exhaustion_keeps_scene_and_skips_only_its_prompt(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        result, session, partials = run(data, [""] * 4 + ["person_token examines exhibit 2."])
        self.assertEqual(session.generate.call_count, 5)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        failed = result["scene_plan"][0]
        self.assertEqual(failed["scene_status"], "valid")
        self.assertEqual(failed["prompt_status"], "failed")
        self.assertEqual(failed["failure_stage"], "prompt")
        self.assertEqual(failed["idea"], data["scene_plan"][0]["idea"])
        self.assertEqual(failed["scene"], data["scene_plan"][0]["scene"])
        self.assertNotIn("replacement_attempted", failed)
        self.assertEqual([row["index"] for row in result["prompts"]], [2])
        self.assertEqual(partials[-1]["scene_plan"][0], failed)

    def test_failed_writer_can_retry_same_scene_without_touching_other_scene(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        data["scene_plan"][0].update(prompt_status="failed", failure_stage="prompt", failure_reason="Empty output")
        result, session, _ = run(data, ["person_token examines exhibit 1.", "person_token examines exhibit 2."])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["scene_plan"][0]["idea"], data["scene_plan"][0]["idea"])
        self.assertEqual(result["scene_plan"][1]["scene"], data["scene_plan"][1]["scene"])
        self.assertNotIn("failure_reason", result["scene_plan"][0])
        self.assertEqual(session.generate.call_count, 2)

    def test_scene_replacement_is_not_replaced_again_after_writer_failure(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        data["scene_plan"][0]["replacement_attempted"] = True
        result, session, _ = run(data, [""] * 4 + ["person_token examines exhibit 2."])
        self.assertEqual(session.generate.call_count, 5)
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "failed")
        self.assertEqual(result["scene_plan"][0]["scene_status"], "valid")
        self.assertTrue(all(call.args[0].diagnostic_stage.startswith("dataset:1") or call.args[0].diagnostic_stage == "dataset:2"
                            for call in session.generate.call_args_list))

    def test_transport_failure_gets_three_retries_without_replacement(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        result, session, _ = run(data, [BackendGenerationError("Engine timed out.")] * 4 + ["person_token examines exhibit 2."])
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["scene_plan"][0]["idea"], data["scene_plan"][0]["idea"])
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list[:4]],
            ["dataset:1", "dataset:1:transport_retry_1", "dataset:1:transport_retry_2", "dataset:1:transport_retry_3"])

    def test_manual_failed_idea_retry_records_new_error_without_touching_other_results(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        data["scene_plan"][0].update(scene_status="failed", prompt_status="failed", failure_reason="Old conflict", failure_stage="scene")
        result, session, _ = run(data, ["[]", "[]"], scene_action=("regenerate_idea", 1))
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(result["scene_plan"][0]["failure_stage"], "idea")
        self.assertIn("Requested new idea failed", result["scene_plan"][0]["failure_reason"])
        self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])
        self.assertEqual(result["prompts"], [data["results"][1]])

    def test_valid_only_writes_valid_indexes_without_replanning_failed_or_pending_items(self):
        data = saved(draft(amount=3), rows(3))
        data["scene_plan"][0].update(idea="", scene="", geometry={}, idea_status="failed", scene_status="failed",
            prompt_status="failed", failure_reason="Replacement idea was invalid.", failure_stage="idea", replacement_attempted=True)
        data["scene_plan"][2].update(idea="", scene="", geometry={}, idea_status="not_generated", scene_status="not_generated")
        originals = json.loads(json.dumps(data["scene_plan"]))
        result, session, _ = run(data, ["person_token examines exhibit 2."], valid_only=True)
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(session.generate.call_args.args[0].diagnostic_stage, "dataset:2")
        self.assertEqual([row["index"] for row in result["prompts"]], [2])
        self.assertEqual(result["scene_plan"][0], originals[0])
        self.assertEqual(result["scene_plan"][2], originals[2])

    def test_valid_only_requires_current_plan_and_at_least_one_valid_scene(self):
        for data in (draft(amount=1), {**saved(draft(amount=1), rows(1)), "scene_plan_signature": "stale"}):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "No valid scenes"):
                run(data, [], valid_only=True)

    def test_valid_only_checks_manual_scene_geometry_without_discarding_edited_idea(self):
        data = saved(draft(amount=1), rows(1))
        data["scene_plan"][0]["geometry"] = {}
        result, session, _ = run(data, [json.dumps(rows(1)), "person_token examines exhibit 1."], valid_only=True)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["scene_plan"][0]["idea"], data["scene_plan"][0]["idea"])
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list],
                         ["dataset:scene_composer:repair", "dataset:1"])

    def test_saved_replacement_marker_survives_pending_composition(self):
        data = saved(draft(amount=1), rows(1))
        data["scene_plan"][0].update(scene="", geometry={}, scene_status="not_generated", replacement_attempted=True)
        result, session, _ = run(data, [json.dumps(rows(1)), *[""] * 4])
        self.assertEqual(session.generate.call_count, 5)
        self.assertTrue(result["scene_plan"][0]["replacement_attempted"])
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "failed")
        self.assertFalse(any(call.args[0].diagnostic_stage == "dataset:idea_planner" for call in session.generate.call_args_list))

    def test_normal_generation_reuses_failed_plan_and_only_writes_good_scenes(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        data["scene_plan"][0].update(scene_status="failed", prompt_status="failed", failure_reason="Rear/face conflict.", failure_stage="scene")
        self.assertIsNotNone(reusable_scene_plan(data, dataset_assignments(data), require_scenes=False))
        self.assertIsNone(reusable_scene_plan(data, dataset_assignments(data)))
        result, session, _ = run(data, ["person_token examines exhibit 2."])
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(result["scene_plan"][0], data["scene_plan"][0])

    def test_failed_content_scene_preserves_plan_and_local_retry_keeps_fixed_idea(self):
        data = saved(draft(planning_mode="Fast"), rows(2))
        data["scene_plan"][0].update(scene="She examines exhibit 1, no other people.",
            scene_status="failed", prompt_status="failed", failure_stage="scene", failure_reason="Positive content needs repair.")
        self.assertIsNotNone(reusable_scene_plan(data, dataset_assignments(data), require_scenes=False))
        result, session, _ = run(data, [json.dumps(rows(1))], scene_action=("repair_scene", 1), scenes_only=True)
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(session.generate.call_args.args[0].diagnostic_stage, "dataset:scene_composer:repair")
        self.assertEqual(result["scene_plan"][0]["idea"], data["scene_plan"][0]["idea"])
        self.assertEqual(result["scene_plan"][0]["scene_status"], "valid")
        self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])
        self.assertNotIn("failure_reason", result["scene_plan"][0])

    def test_guided_scene_repair_keeps_idea_authoritative_input_and_constraints(self):
        data = draft(amount=1, source_mode="guided", inputs="posing on a park bench", constraints="Same jacket in every scene.")
        row = scene(idea="Relaxing on a park bench", scene="She relaxes on a park bench.")
        new = scene(idea=row["idea"], scene="She relaxes while seated on the park bench.")
        session = Mock()
        session.generate.side_effect = [json.dumps([new])]
        result = ScenePlanner(lambda: None).recover_scene(session=session, data=data,
            assignments=dataset_assignments(data), row=row, progress=lambda _: None, errors=["Camera conflict."])
        self.assertEqual(result["idea"], row["idea"])
        for call in session.generate.call_args_list:
            context = json.loads(call.args[0].user_message)
            self.assertEqual(context["constraints"], data["constraints"])
            self.assertEqual(context["assignments"][0]["input"], data["inputs"])

    def test_failure_metadata_is_bounded_and_typed(self):
        data = saved(draft(amount=1), rows(1))
        for metadata in ({"failure_reason": 1}, {"failure_reason": "x" * 2001}, {"failure_stage": []},
                         {"failure_stage": "unknown"}, {"replacement_attempted": "yes"}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                validate_dataset_draft({**data, "scene_plan": [{**data["scene_plan"][0], **metadata}]})

    def test_cancellation_during_repair_does_not_trigger_new_idea(self):
        class Cancelled(Exception):
            pass
        session = Mock()
        session.generate.side_effect = Cancelled()
        with self.assertRaises(Cancelled):
            ScenePlanner(lambda: None).recover_scene(session=session, data=draft(amount=1),
                assignments=dataset_assignments(draft(amount=1)), row=rear_conflict(rows(1)[0]), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
