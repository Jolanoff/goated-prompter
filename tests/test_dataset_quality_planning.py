"""Two-pass Dataset planning, deterministic staging and downstream-only repair."""

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft, validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_quality import analyze_dataset_quality, analyze_idea_diversity
from goated_prompter.dataset_staging import geometry_errors as staging_geometry_errors, validate_geometry
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.details import MAXIMUM_DETAIL_GUIDANCE, DATASET_DETAIL_DISCIPLINE
from goated_prompter.prompting.scene_planner import (idea_planner_instruction, scene_planner_instruction,
                                                    scene_composer_instruction)
from goated_prompter.scene_planner import (ScenePlanner, scene_plan_signature, reusable_scene_plan,
                                         validate_idea_plan, validate_scene_plan)


def geometry_errors(row):
    return staging_geometry_errors(row, dataset_type="Character", require_fields=False)


def draft(**changes):
    return {**default_dataset_draft(), "planning_mode": "Quality", "amount": 2,
            "trigger": "person_token", "subject": "A woman doing funny stuff", **changes}


def scene(index=1, idea="trying to juggle and failing", **changes):
    return {"index": index, "idea": idea,
            "scene": "She unsuccessfully juggles oranges, hands beneath the falling fruit and gaze tracking it.",
            "geometry": {"framing": "full_body", "camera_azimuth": "front_three_quarter_left",
                         "body_orientation": "front_three_quarter_left", "head_direction": "toward_action",
                         "gaze_direction": "toward_action", "pose_type": "standing_dynamic", "face_visibility": "three_quarter",
                         "action_focus": idea, "hand_visibility": "both_visible",
                         "visibility_focus": ["face", "hands", "falling objects"]}, **changes}


def saved(data, rows):
    data = {**data, "scene_plan": [{**row, "input": "", "idea_status": "valid", "scene_status": "valid",
                                  "prompt_status": "valid"} for row in rows]}
    data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
    data["results"] = [{**{key: value for key, value in row.items() if key not in {"idea_status", "scene_status", "prompt_status"}},
                        "input": "", "prompt": "person_token. " + row["scene"]} for row in rows]
    return data


def run(data, outputs, **kwargs):
    session = Mock()
    session.generate.side_effect = outputs
    backend = Mock()
    backend.name = "quality-test"
    @contextmanager
    def generation_session():
        yield session
    backend.generation_session = generation_session
    partials = []
    with patch("goated_prompter.dataset.create_backend", return_value=backend):
        result = DatasetService({"backend": "mock"}, lambda: None).run(
            GoatedPrompterRequest(idea=data["subject"], target_model=data["target"]),
            data, lambda _: None, partials.append, **kwargs)
    return result, session, partials


class QualityPlanningTests(unittest.TestCase):
    def test_idea_json_repair_receives_previous_candidate_before_direct_writing(self):
        data = draft(amount=1)
        expected = scene()
        malformed = '[{"index":1,"idea" "trying to juggle and failing"}]'
        result, session, _ = run(data, [malformed,
            json.dumps([{"index": 1, "idea": expected["idea"]}]),
            json.dumps([expected]), "person_token tries to juggle oranges and fails."])
        self.assertEqual(result["completed"], 1)
        repair = session.generate.call_args_list[1].args[0]
        context = json.loads(repair.user_message)
        self.assertEqual(context.get("previous_response"), malformed)
        self.assertIn("Preserve", repair.system_message)
        self.assertIn("previous_response", repair.system_message)
        self.assertEqual(repair.diagnostic_stage, "dataset:idea_planner:repair")
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list[2:]],
                         ["dataset:scene_composer", "dataset:1"])

    def test_malformed_ideas_block_both_generation_paths_before_writer(self):
        malformed = '[{"index":1,"idea" "trying to juggle and failing"}]'
        for scenes_only in (False, True):
            with self.subTest(scenes_only=scenes_only):
                session, backend = Mock(), Mock()
                session.generate.return_value = malformed
                @contextmanager
                def generation_session():
                    yield session
                backend.generation_session = generation_session
                data = draft(amount=1)
                with patch("goated_prompter.dataset.create_backend", return_value=backend), self.assertRaises(BackendGenerationError):
                    DatasetService({"backend": "mock"}, lambda: None).run(
                        GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None,
                        scenes_only=scenes_only)
                self.assertEqual(session.generate.call_count, 2)
                self.assertTrue(all(call.args[0].diagnostic_stage.startswith("dataset:idea_planner")
                                    for call in session.generate.call_args_list))

    def test_direct_and_plan_first_recover_same_malformed_ideas_into_same_writer_input(self):
        data = draft(amount=1)
        expected = scene()
        malformed = '[{"index":1,"idea" "trying to juggle and failing"}]'
        planning = [malformed, json.dumps([{"index": 1, "idea": expected["idea"]}]), json.dumps([expected])]
        output = "person_token tries to juggle oranges and fails."
        direct, direct_session, _ = run(data, planning + [output])
        plan, plan_session, _ = run(data, planning, scenes_only=True)
        restored = validate_dataset_draft({**data, "scene_plan": plan["scene_plan"],
                                          "scene_plan_signature": plan["scene_plan_signature"]})
        staged, staged_session, _ = run(restored, [output])
        self.assertEqual(direct["prompts"], staged["prompts"])
        self.assertEqual(direct["completed"], 1)
        self.assertEqual(direct_session.generate.call_args.args[0], staged_session.generate.call_args.args[0])
        for session in (direct_session, plan_session):
            self.assertNotIn("previous_response", json.loads(session.generate.call_args_list[0].args[0].user_message))
            self.assertEqual(json.loads(session.generate.call_args_list[1].args[0].user_message)["previous_response"], malformed)

    def test_idea_format_repair_retains_candidate_when_transport_fails(self):
        data, session = draft(amount=1), Mock()
        malformed = '[{"index":1,"idea" "trying to juggle and failing"}]'
        session.generate.side_effect = [malformed, BackendGenerationError("temporary transport failure")]
        with self.assertRaises(BackendGenerationError):
            ScenePlanner(lambda: None).plan_ideas(session=session, data=data,
                assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 2)
        retry = session.generate.call_args.args[0]
        self.assertEqual(json.loads(retry.user_message)["previous_response"], malformed)
        self.assertIn("IDEA OUTPUT FORMAT CORRECTION", retry.system_message)

    def test_ten_prompts_use_full_batch_ideas_then_three_composer_chunks_plus_ten_writers(self):
        ideas = ["trying to juggle and failing", "walking in giant shoes", "making a funny face",
                 "getting tangled in a bedsheet", "catching popcorn in her mouth", "taking a ridiculous selfie",
                 "wearing a sweater backwards", "sitting in a tiny chair", "balancing a spoon on her nose",
                 "carrying too many grocery bags"]
        rows = [scene(i, idea, scene="A woman " + idea + ", with her necessary props visible in one coherent image.")
                for i, idea in enumerate(ideas, 1)]
        result, session, _ = run(draft(amount=10), [json.dumps([{"index": row["index"], "idea": row["idea"]} for row in rows]),
            *[json.dumps(rows[start:start + 4]) for start in range(0, 10, 4)]] + ["person_token. " + row["scene"] for row in rows])
        stages = [call.args[0].diagnostic_stage for call in session.generate.call_args_list]
        self.assertEqual(stages, ["dataset:idea_planner"] + ["dataset:scene_composer"] * 3 + [f"dataset:{i}" for i in range(1, 11)])
        self.assertEqual(result["completed"], 10)
        self.assertTrue(all(row["prompt_status"] == "valid" for row in result["scene_plan"]))
        for row, call in zip(rows, session.generate.call_args_list[4:]):
            self.assertIn(row["idea"], call.args[0].user_message)
            self.assertIn(json.dumps(row["geometry"]), call.args[0].user_message)

    def test_fast_single_scene_keeps_one_combined_planning_call(self):
        rows = [scene()]
        result, session, _ = run(draft(amount=1, planning_mode="Fast"),
                                [json.dumps(rows), "person_token attempts to juggle and drops an orange."])
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(session.generate.call_args_list[0].args[0].diagnostic_stage, "dataset:scene_planner")
        self.assertEqual(result["prompts"][0]["geometry"], rows[0]["geometry"])

    def test_planner_system_prompts_have_abstract_diversity_not_concept_answers(self):
        data = draft()
        assignments = dataset_assignments(data)
        for instruction in (scene_planner_instruction(data, assignments), idea_planner_instruction(data, assignments),
                            scene_composer_instruction(data, assignments, [scene()])):
            for answer in ("clown", "juggling", "oversized shoes", "bedsheet", "popcorn", "funny stuff"):
                self.assertNotIn(answer, instruction.system_message.casefold())
        first = idea_planner_instruction(data, assignments)
        context = json.loads(first.user_message)
        for key in ("camera", "lighting", "facets", "target", "visual_style", "director_preset"):
            self.assertNotIn(key, context)
        self.assertEqual([row["index"] for row in context["assignments"]], [1, 2])
        self.assertTrue(all(set(row) == {"index", "input"} for row in context["assignments"]))

    def test_idea_schema_is_strict_bounded_and_index_specific(self):
        self.assertEqual(validate_idea_plan('[{"index":3,"idea":"Reading a book"}]', [3])[0]["index"], 3)
        invalid = ["[]", "{}", "```json\n[]\n```", '[{"index":true,"idea":"Reading"}]',
                   '[{"index":1,"idea":"Reading","scene":"Extra"}]', '[{"index":1,"idea":""}]',
                   '[{"index":1,"idea":"Reading","idea":"Writing"}]', '[{"index":1,"idea":"no other people"}]',
                   json.dumps([{"index": 1, "idea": "word " * 81}])]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_idea_plan(raw, [1])

    def test_new_settings_and_stage_metadata_are_validated(self):
        data = saved(draft(amount=1), [scene()])
        for mode in ("unknown", None, [], True):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_dataset_draft({**data, "planning_mode": mode})
        for patch_data in ({"idea_status": "unknown"}, {"scene_status": True},
                           {"failure_stage": "invalid"}):
            with self.subTest(patch_data=patch_data), self.assertRaises(ValueError):
                validate_dataset_draft({**data, "scene_plan": [{**data["scene_plan"][0], **patch_data}]})

    def test_composer_cannot_replace_fixed_idea_and_repairs_only_bad_index(self):
        data = draft()
        ideas = [{"index": 1, "idea": "trying to juggle and failing"}, {"index": 2, "idea": "wearing giant shoes"}]
        wrong = scene(idea="wearing clown clothes", scene="She poses in clown clothes.")
        good = scene(2, ideas[1]["idea"], scene="She presents her giant shoes in a full-body pose.")
        session = Mock()
        session.generate.side_effect = [json.dumps(ideas), json.dumps([wrong, good]), json.dumps([scene()])]
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(rows[0]["idea"], ideas[0]["idea"])
        self.assertEqual(rows[1], good)
        repair = session.generate.call_args_list[-1].args[0]
        context = json.loads(repair.user_message)
        self.assertEqual(len(context["assignments"]), 1)
        self.assertEqual(context["assignments"][0]["idea"], ideas[0]["idea"])
        self.assertIn("required props", repair.system_message)
        self.assertEqual(session.generate.call_count, 3)

    def test_bad_geometry_repairs_composer_not_idea_planner(self):
        bad = scene(geometry={"camera_view": "direct rear", "body_orientation": "facing away",
                              "face_visibility": "fully frontal", "gaze": "camera"})
        result, session, _ = run(draft(amount=1), [json.dumps([{"index": 1, "idea": bad["idea"]}]),
            json.dumps([bad]), json.dumps([scene()]), "person_token unsuccessfully juggles oranges."])
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list],
                         ["dataset:idea_planner", "dataset:scene_composer", "dataset:scene_composer:repair", "dataset:1"])
        self.assertEqual(result["prompts"][0]["idea"], bad["idea"])
        self.assertFalse(geometry_errors(result["scene_plan"][0]))
        repair_context = json.loads(session.generate.call_args_list[2].args[0].user_message)
        self.assertEqual(repair_context["previous_scene"]["geometry"], bad["geometry"])

    def test_repair_refuses_idea_drift_and_fails_boundedly(self):
        session = Mock()
        session.generate.return_value = json.dumps([scene(idea="wearing clown clothes")])
        with self.assertRaisesRegex(BackendGenerationError, "fixed idea"):
            ScenePlanner(lambda: None).repair_scene(session=session, data=draft(amount=1),
                assignments=dataset_assignments(draft(amount=1)), row=scene(), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 3)

    def test_malformed_geometry_is_repaired_only_at_its_index(self):
        data = draft()
        bad = scene(geometry={"camera": "direct rear"})
        good = scene(2, "wearing giant shoes", scene="She poses in giant shoes.")
        session = Mock()
        session.generate.side_effect = [json.dumps([bad, good]), json.dumps([scene()])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data, assignments=dataset_assignments(data),
            ideas=[{"index": row["index"], "idea": row["idea"]} for row in (bad, good)], progress=lambda _: None)
        self.assertEqual(result, [scene(), good])
        repair = json.loads(session.generate.call_args_list[1].args[0].user_message)
        self.assertEqual([row["index"] for row in repair["assignments"]], [1])
        self.assertEqual(session.generate.call_count, 2)

    def test_failed_scene_repair_keeps_valid_ideas_and_stage_state_for_recovery(self):
        data = draft(amount=1)
        bad = scene(geometry={"camera_view": "direct rear", "face_visibility": "full frontal"})
        session, backend, partials = Mock(), Mock(), []
        session.generate.side_effect = [json.dumps([{"index": 1, "idea": bad["idea"]}]),
                                       json.dumps([bad]), json.dumps([bad]), json.dumps([bad]),
                                       json.dumps([bad])]
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"]),
                data, lambda _: None, partials.append)
        self.assertEqual(partials[0]["scene_plan"][0]["idea"], bad["idea"])
        self.assertEqual(partials[0]["scene_plan"][0]["scene_status"], "not_generated")
        self.assertEqual(partials[-1]["scene_plan"][0]["scene_status"], "failed")
        self.assertEqual(partials[-1]["scene_plan"][0]["prompt_status"], "failed")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(partials[-1]["prompts"], [])
        restored = {**data, "scene_plan": partials[-1]["scene_plan"],
                    "scene_plan_signature": partials[-1]["scene_plan_signature"]}
        self.assertEqual(validate_dataset_draft(restored), restored)
        self.assertEqual(session.generate.call_count, 5)

    def test_regenerate_idea_does_not_accept_same_idea_as_new(self):
        data = saved(draft(amount=1), [scene()])
        new = scene(idea="balancing a spoon on her nose", scene="She balances a spoon on her nose.")
        result, session, _ = run(data, [json.dumps([{"index": 1, "idea": scene()["idea"]}]),
            json.dumps([{"index": 1, "idea": new["idea"]}]), json.dumps([new]), "person_token balances a spoon on her nose."],
            scene_action=("regenerate_idea", 1))
        self.assertEqual(result["scene_plan"][0]["idea"], new["idea"])
        self.assertEqual(session.generate.call_count, 4)
        self.assertIn("genuinely new idea", session.generate.call_args_list[1].args[0].system_message)

    def test_exact_duplicate_idea_replaced_locally_before_composition(self):
        data = draft(amount=3)
        ideas = [{"index": 1, "idea": "trying to juggle oranges and failing"},
                 {"index": 2, "idea": "trying to juggle oranges and failing"},
                 {"index": 3, "idea": "wearing oversized shoes"}]
        replacement = {"index": 2, "idea": "balancing a spoon on her nose"}
        rows = [scene(row["index"], row["idea"], scene="She " + row["idea"] + ", necessary props visible.")
                for row in [ideas[0], replacement, ideas[2]]]
        session = Mock()
        session.generate.side_effect = [json.dumps(ideas), json.dumps([replacement]), json.dumps(rows)]
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        context = json.loads(session.generate.call_args_list[1].args[0].user_message)
        self.assertEqual(context["amount"], 1)
        self.assertEqual([row["index"] for row in context["assignments"]], [2])
        self.assertEqual(context["existing_ideas"], [ideas[0], ideas[2]])
        self.assertEqual(planned, rows)

    def test_final_writer_retries_only_prompt_if_action_disappears(self):
        data = saved(draft(amount=1), [scene()])
        result, session, _ = run(data, ["person_token stands motionless in a studio.",
                                      "person_token tries to juggle oranges and fails."])
        self.assertEqual(session.generate.call_count, 2)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertTrue(calls[1].user_message.startswith(calls[0].user_message))
        self.assertIn("LOCAL REPAIR CONTRACT", calls[1].user_message)
        self.assertIn("SCENE FIDELITY CORRECTION", calls[1].system_message)
        self.assertIn("juggle", result["prompts"][0]["prompt"])
        self.assertEqual(result["scene_plan"], data["scene_plan"])

    def test_ideogram_action_fidelity_checks_element_descriptions_too(self):
        data = saved(draft(amount=1, target="Ideogram4"), [scene()])
        caption = {"high_level_description": "person_token amid oranges.",
                   "style_description": {"aesthetics": "Clean illustration", "lighting": "Soft daylight",
                                         "medium": "Illustration", "art_style": "Crisp linework"},
                   "compositional_deconstruction": {"background": "A quiet interior.",
                       "elements": [{"type": "obj", "desc": "She unsuccessfully juggles oranges, eyes tracking falling fruit."}]}}
        result, session, _ = run(data, [json.dumps(caption)])
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(json.loads(result["prompts"][0]["prompt"]), caption)

    def test_scene_action_repair_preserves_other_rows_and_calls_composer_then_writer(self):
        rows = [scene(), scene(2, "wearing giant shoes", scene="She poses in giant shoes.")]
        data = saved(draft(), rows)
        repaired = scene(scene="She unsuccessfully juggles oranges in a wider frame, gaze following falling fruit.")
        result, session, partials = run(data, [json.dumps([repaired]), "person_token fails to juggle oranges."],
                                        scene_action=("repair_scene", 1))
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list],
                         ["dataset:scene_composer:repair", "dataset:1"])
        self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])
        self.assertEqual(result["prompts"][1], data["results"][1])
        self.assertEqual(result["scene_plan"][0]["idea"], rows[0]["idea"])
        self.assertEqual(partials[0]["scene_plan"][0]["scene_status"], "not_generated")
        self.assertEqual(partials[0]["scene_plan"][0]["prompt_status"], "not_generated")

    def test_scene_action_new_idea_invalidates_only_its_downstream_stages(self):
        data = saved(draft(), [scene(), scene(2, "wearing giant shoes", scene="She poses in giant shoes.")])
        new = scene(idea="balancing a spoon on her nose", scene="She balances a spoon on her nose.")
        result, session, partials = run(data, [json.dumps([{"index": 1, "idea": new["idea"]}]),
            json.dumps([new]), "person_token balances a spoon on her nose."], scene_action=("regenerate_idea", 1))
        self.assertEqual(session.generate.call_count, 3)
        self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])
        self.assertEqual(result["prompts"][1], data["results"][1])
        self.assertEqual(partials[0]["scene_plan"][0]["scene"], "")
        self.assertEqual(partials[0]["scene_plan"][0]["geometry"], {})
        self.assertEqual(partials[0]["prompts"], [data["results"][1]])
        self.assertEqual(json.loads(session.generate.call_args_list[0].args[0].user_message)["existing_ideas"],
                         [{"index": row["index"], "idea": row["idea"]} for row in data["scene_plan"]])

    def test_scene_action_prompt_only_keeps_idea_scene_geometry(self):
        data = saved(draft(), [scene(), scene(2, "wearing giant shoes", scene="She poses in giant shoes.")])
        result, session, _ = run(data, ["person_token unsuccessfully juggles oranges."],
                                 scene_action=("regenerate_prompt", 1))
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(session.generate.call_args.args[0].diagnostic_stage, "dataset:1")
        self.assertEqual(result["scene_plan"], data["scene_plan"])
        self.assertEqual(result["prompts"][1], data["results"][1])

    def test_blank_scene_edit_composes_fixed_idea_without_replanning_other_items(self):
        data = saved(draft(), [scene(), scene(2, "wearing giant shoes", scene="She poses in giant shoes.")])
        data["scene_plan"][0].update(scene="", geometry={}, scene_status="not_generated", prompt_status="not_generated")
        result, session, _ = run(data, [json.dumps([scene()]), "person_token unsuccessfully juggles oranges.",
                                      "person_token poses in giant shoes."])
        self.assertEqual(session.generate.call_count, 3)
        self.assertEqual(session.generate.call_args_list[0].args[0].diagnostic_stage, "dataset:scene_composer")
        self.assertEqual(json.loads(session.generate.call_args_list[0].args[0].user_message)["amount"], 1)
        self.assertEqual(result["scene_plan"][1], data["scene_plan"][1])

    def test_output_settings_reuse_plan_but_semantic_changes_do_not(self):
        data = saved(draft(amount=1), [scene()])
        for patch_data in ({"target": "Qwen Image"}, {"length": "Maximum Detail"}, {"director_preset": "photography_director"}):
            changed = {**data, **patch_data}
            self.assertEqual(reusable_scene_plan(changed, dataset_assignments(changed)), data["scene_plan"])
        for patch_data in ({"subject": "different"}, {"constraints": "only indoors"}, {"inputs": "new input"}, {"planning_mode": "Fast"}):
            changed = {**data, **patch_data}
            self.assertIsNone(reusable_scene_plan(changed, dataset_assignments(changed)))
        self.assertEqual(validate_dataset_draft(json.loads(json.dumps(data))), data)

    def test_automatic_planning_failure_never_calls_writer(self):
        for mode in ("Fast", "Quality"):
            with self.subTest(mode=mode):
                if mode == "Quality":
                    with self.assertRaisesRegex(BackendGenerationError, "planning failed"):
                        run(draft(planning_mode=mode), ["[]", "[]"])
                else:
                    result, session, _ = run(draft(planning_mode=mode), ["[]"] * 12)
                    self.assertEqual(result["completed"], 0)
                    self.assertTrue(all(row["scene_status"] == "failed" for row in result["scene_plan"]))
                    self.assertFalse(any(call.args[0].diagnostic_stage in {"dataset:1", "dataset:2"} for call in session.generate.call_args_list))

    def test_quality_guided_fallback_retains_each_supplied_line(self):
        data = draft(source_mode="guided", inputs="reading a book\nwearing a hat")
        result, session, _ = run(data, ["bad", "bad", "person_token reading a book.", "person_token wearing a hat."])
        self.assertEqual([row["scene"] for row in result["scene_plan"]], ["reading a book", "wearing a hat"])
        self.assertEqual(session.generate.call_count, 4)


class GeometryAndQualityTests(unittest.TestCase):
    def test_clear_geometry_contradictions(self):
        cases = [
            {"camera_view": "direct rear", "face_visibility": "full frontal"},
            {"body_orientation": "fully facing away", "head_direction": "fully frontal toward camera"},
            {"camera_view": "profile", "face_visibility": "both sides of face equally visible"},
            {"camera_view": "direct rear", "gaze": "looking straight into camera"},
        ]
        for geometry in cases:
            with self.subTest(geometry=geometry):
                self.assertTrue(geometry_errors(scene(geometry=geometry)))
        for text in ("Direct rear view, looking straight into camera.",
                     "Profile view with both sides of face equally visible.",
                     "Body fully facing away, head fully frontal toward camera."):
            with self.subTest(text=text):
                self.assertTrue(geometry_errors(scene(geometry={}, scene=text)))

    def test_unusual_rear_shoulder_turn_is_valid(self):
        geometry = {"camera_azimuth": "rear_three_quarter_right", "body_orientation": "rear_three_quarter_right",
                    "head_direction": "over_left_shoulder", "gaze_direction": "toward_camera",
                    "face_visibility": "three_quarter"}
        self.assertFalse(geometry_errors(scene(idea="Looking back over her shoulder", geometry=geometry)))
        self.assertFalse(geometry_errors(scene(geometry={}, scene="Not a direct rear view; full frontal face clearly visible.")))
        self.assertFalse(geometry_errors(scene(geometry={}, scene="Direct rear view with a fully frontal face in a mirror reflection.")))

    def test_scene_prose_and_geometry_cannot_disagree(self):
        row = scene(scene="Direct rear view, full frontal face visible.")
        self.assertTrue(geometry_errors(row))
        session = Mock()
        session.generate.side_effect = [json.dumps([row]), json.dumps([scene()])]
        data = draft(amount=1, planning_mode="Fast")
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(planned[0]["idea"], row["idea"])
        self.assertEqual(session.generate.call_count, 2)

    def test_optional_geometry_fields_and_schema_leakage_checks(self):
        self.assertEqual(validate_geometry({}), {})
        self.assertEqual(validate_scene_plan(json.dumps([scene(geometry={})]), 1, require_geometry=True)[0]["geometry"], {})
        for invalid in ([], {"camera": "rear"}, {"gaze": "no extra people"}, {"visibility_focus": "shoes"},
                        {"pose": "x" * 161}, {"framing": None}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_geometry(invalid)

    def test_composer_chooses_action_compatible_framing_without_coverage(self):
        for idea, framing, focus in (("trying to catch popcorn in mouth", "face close-up", ["face", "popcorn"]),
                                     ("walking in giant shoes", "full body", ["face", "shoes"])):
            data = draft(amount=1)
            assignments = dataset_assignments(data)
            row = scene(idea=idea, scene="A woman " + idea + ".",
                         geometry={**scene(idea=idea)["geometry"], "framing": framing.replace(" ", "_").replace("-", "_"), "visibility_focus": focus})
            session = Mock()
            session.generate.return_value = json.dumps([row])
            planned = ScenePlanner(lambda: None).compose(session=session, data=data, assignments=assignments,
                ideas=[{"index": 1, "idea": idea}], progress=lambda _: None)[0]
            self.assertNotIn("coverage_conflicts", planned)
            writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
                                         plan_item={**assignments[0], **planned})
            self.assertNotIn("COVERAGE ASSIGNMENT", writer.user_message)
            self.assertEqual(planned["geometry"]["framing"], framing.replace(" ", "_").replace("-", "_"))
            self.assertEqual(session.generate.call_count, 1)

    def test_missing_required_metadata_repairs_without_widening_crop(self):
        data = draft(amount=1)
        bad = scene(idea="walking in giant shoes", scene="She walks in giant shoes.", geometry={"framing": "face close-up"})
        good = {**bad, "geometry": {**scene(idea=bad["idea"])["geometry"], "framing": "full_body", "visibility_focus": ["shoes"]}}
        session = Mock()
        session.generate.side_effect = [json.dumps([bad]), json.dumps([good])]
        result = ScenePlanner(lambda: None).compose(session=session, data=data, assignments=dataset_assignments(data),
            ideas=[{"index": 1, "idea": bad["idea"]}], progress=lambda _: None)
        self.assertEqual(result[0], {**good, "geometry": {**good["geometry"], "framing": "face_close_up"}})
        self.assertEqual(session.generate.call_count, 2)

    def test_explicit_lexical_duplicates_cluster_but_nuanced_paraphrases_defer_to_review(self):
        rows = [{"index": i, "idea": idea} for i, idea in enumerate(("trying to juggle oranges and failing",
                "dropping fruit while attempting to juggle", "losing control of three airborne oranges"), 1)]
        self.assertEqual(analyze_idea_diversity(draft(), rows)["uniqueness"], 50)
        self.assertFalse(analyze_idea_diversity(draft(), rows)["ideas"][2]["issues"])
        for constrained in ({"source_mode": "guided"}, {"variety": "Focused"}):
            self.assertEqual(analyze_idea_diversity(draft(**constrained), rows)["uniqueness"], 100)
        exact = [rows[0], {**rows[0], "index": 2}]
        self.assertEqual(analyze_idea_diversity(draft(variety="Focused"), exact)["uniqueness"], 0)

    def test_repetitive_ideas_and_scenes_cannot_get_high_score_from_valid_prompts(self):
        data = draft(amount=10)
        rows = [{"index": i, "idea": "trying to juggle and failing", "scene": "She juggles oranges and drops one.",
                 "input": "", "prompt": f"person_token in unique setup {i} " + " ".join(f"detail{i}x{j}" for j in range(12))}
                for i in range(1, 11)]
        quality = analyze_dataset_quality(data, rows)
        self.assertEqual(quality["metrics"]["format"], 100)
        self.assertEqual(quality["metrics"]["trigger"], 100)
        self.assertEqual(quality["metrics"]["uniqueness"], 100)
        self.assertEqual(quality["metrics"]["idea_uniqueness"], 0)
        self.assertEqual(quality["metrics"]["scene_uniqueness"], 0)
        self.assertLess(quality["score"], 50)

    def test_normal_maximum_length_is_retained_with_scene_detail_discipline(self):
        data = draft(length="Maximum Detail", amount=1)
        request = GoatedPrompterRequest(idea=data["subject"], prompt_length=data["length"])
        writer = dataset_instruction(request, data, 1, plan_item=scene())
        self.assertIn(MAXIMUM_DETAIL_GUIDANCE, writer.system_message)
        self.assertIn(DATASET_DETAIL_DISCIPLINE, writer.system_message)
        self.assertIn("non-redundant visual", writer.system_message)
        self.assertIn(MAXIMUM_DETAIL_GUIDANCE, assemble_instruction(request, text_only=True).system_message)

    def test_krea_preserves_anime_and_photographic_styles(self):
        for style in ("Anime / manga", "Photorealistic"):
            data = draft(amount=1, target="Krea 2", visual_style=style)
            instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"], target_model="Krea 2"),
                                              data, 1, plan_item=scene())
            for phrase in ("photographic realism", "realistic skin", "photographic character"):
                self.assertNotIn(phrase, instruction.system_message.casefold())
            if style == "Anime / manga":
                self.assertIn("Render the planned scene as anime/manga", instruction.system_message)
                self.assertIn("do not force photographic rendering", instruction.system_message)
            else:
                self.assertIn("Use believable photography", instruction.system_message)


if __name__ == "__main__":
    unittest.main()
