"""Arbitrary pose representation, independent crop/visibility and repair locks.

Mock writer tests establish data flow, not real-model geometry quality.
"""
import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import (geometry_errors, geometry_issues, validate_geometry,
    validate_planned_geometry, normalize_staging, migrate_saved_geometry, resolve_framing_conflicts)
from goated_prompter.dataset_staging.schema import GEOMETRY_FIELDS
from goated_prompter.dataset_staging.vocabulary import BODY_PART_VALUES
from goated_prompter.prompting.scene_planner import scene_planner_instruction, scene_composer_instruction
from goated_prompter.scene_planner import ScenePlanner, reusable_scene_plan
from goated_prompter.scene_planner import validate_scene_plan, SceneFormatError
from tests.test_dataset_geometry import character_geometry
from tests.test_dataset_quality_planning import draft, run, saved


CASES = (
    ("feet_behind_neck", "upper body, character with both feet behind her neck, feet visible", "waist_up",
     "Compact seated contortion; hips supported on the floor; torso upright with a forward curl; both knees rise beside the shoulders; both lower legs fold upward behind the head; both ankles pass behind the neck; both feet remain clearly visible beside the head.", ["face", "torso", "feet"]),
    ("closeup_hands", "close-up, both hands framing her face", "face_close_up",
     "Both arms bend upward; both hands frame the cheeks with fingertips beside the temples and palms facing inward.", ["face", "hands"]),
    ("knees_near_face", "waist-up curled pose, both knees pulled beside her face", "waist_up",
     "Hips supported on floor; torso curls forward; both hips and knees flex deeply; knees rise beside the face with thighs alongside the chest.", ["face", "torso", "knees"]),
    ("foreshortened_feet", "waist-up reclining pose with feet extending toward the camera", "waist_up",
     "Back and hips supported by bench; torso reclines; both legs lift toward the camera; ankles extend toward the lens; foreshortened feet overlap the upper torso in the foreground.", ["face", "torso", "feet"]),
    ("shoulder_inversion", "shoulder-supported inverted pose with legs folded around the upper body", "waist_up",
     "Shoulders and upper arms bear weight on the mat; torso tilts upward above the shoulders; hips rise above the chest; both knees bend beside the shoulders; lower legs fold around the upper torso; feet remain near the head.", ["head", "shoulders", "torso", "knees", "feet"]),
    ("asymmetric_balance", "one-arm acrobatic balance, one knee near shoulder, opposite leg extended", "full_body",
     "Left palm supports the body on the floor; left elbow stays bent; torso tilts diagonally above that hand; right arm reaches sideways; left knee tucks beside the left shoulder; the opposite leg extends horizontally behind the hips.", ["torso", "hands", "knees", "feet"]),
)


def pose_row(case):
    name, request, crop, detail, parts = case
    return {"index":1, "idea":request, "scene":f"A character in a {crop.replace('_', '-')} composition. {detail}",
            "geometry":character_geometry(framing=crop, camera_distance="medium", pose_type="custom",
                pose_detail=detail, body_visibility="custom", required_visible_parts=list(parts),
                action_focus=name.replace('_', ' '), visibility_focus=parts,
                feet_visibility="both_visible" if "feet" in parts else "none_visible")}


class ComplexPoseStagingTests(unittest.TestCase):
    def test_six_pose_configurations_validate_without_rewriting(self):
        for case in CASES:
            row = pose_row(case)
            with self.subTest(case=case[0]):
                self.assertEqual(validate_geometry(row["geometry"],dataset_type="Character"),row["geometry"])
                self.assertFalse(geometry_errors(row,dataset_type="Character"))
                self.assertEqual(resolve_framing_conflicts(row,dataset_type="Character"),row)
                self.assertEqual(validate_planned_geometry(row["geometry"],dataset_type="Character"),row["geometry"])

    def test_every_anatomical_part_can_be_required_inside_any_character_crop(self):
        for crop in ("face_close_up", "waist_up", "three_quarter_body", "full_body"):
            for part in BODY_PART_VALUES:
                g=character_geometry(framing=crop,required_visible_parts=[part])
                self.assertFalse(geometry_errors({"geometry":g,"scene":"A compact folded pose."},dataset_type="Character"))

    def test_fast_and_quality_preserve_all_six_without_repairs(self):
        for mode in ("Fast", "Quality"):
            for case in CASES:
                with self.subTest(mode=mode,case=case[0]):
                    row=pose_row(case)
                    data=draft(amount=1,planning_mode=mode,source_mode="guided",inputs=case[1],subject="A character demonstrating a fixed pose")
                    session=Mock()
                    responses=[json.dumps([row])]
                    if mode=="Quality": responses.insert(0,json.dumps([{key:row[key] for key in ("index","idea")}]))
                    session.generate.side_effect=responses
                    planned=ScenePlanner(lambda:None).plan_batch(session=session,data=data,
                        assignments=dataset_assignments(data),progress=lambda _:None)
                    self.assertEqual(planned,[row])
                    self.assertEqual(session.generate.call_count,len(responses))

    def test_aliases_only_change_vocabulary_not_pose_or_crop(self):
        original=pose_row(CASES[0])["geometry"]
        g={**original,"framing":"upper body","required_visible_parts":["face","torso","foot","both_feet","feet_visible"]}
        self.assertEqual(normalize_staging(g,dataset_type="Character"),original)
        self.assertEqual(normalize_staging({"framing":"medium_shot","required_visible_parts":["hand","both_hands"]}),
            {"framing":"waist_up","required_visible_parts":["hands"]})
        g={**original,"pose_type":"some_unknown_complex_pose"}
        self.assertEqual(validate_geometry(g,dataset_type="Character"),original)
        self.assertEqual(migrate_saved_geometry(g,dataset_type="Character"),(original,False))
        self.assertEqual(g["pose_detail"],original["pose_detail"])
        self.assertEqual(validate_geometry({**original,"leg_position":"custom"}),original)
        with self.assertRaises(ValueError):validate_geometry({"leg_position":"custom"})

    def test_structural_errors_are_not_unusual_geometry(self):
        for invalid in ("feet",["wings"],[True],[{}],[None]):
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                validate_geometry({"required_visible_parts":invalid})
        for detail in (None,"dynamic pose","custom contortion","advanced yoga pose"):
            g={"pose_type":"custom"}
            if detail is not None:g["pose_detail"]=detail
            with self.assertRaises(ValueError): validate_geometry(g)
        with self.assertRaises(ValueError):validate_geometry({"body_visibility":"custom"})
        with self.assertRaises(ValueError):validate_geometry({"body_visibility":"custom","required_visible_parts":[]})
        row=pose_row(CASES[0]);row["geometry"]["feet_visibility"]="none_visible"
        issues=geometry_issues(row,"Character")
        self.assertIn("required_anatomy_hidden",{issue.code for issue in issues})
        self.assertFalse(any("framing" in issue.fields for issue in issues))
        row["geometry"]["required_visible_parts"]=["lower_legs"]
        row["geometry"]["feet_visibility"]="both_visible"
        row["scene"]="The lower legs are completely obscured."
        issues=geometry_issues(row,"Character")
        self.assertIn("required_feature_hidden",{issue.code for issue in issues})
        self.assertFalse(any("framing" in issue.fields for issue in issues))

    def test_long_pose_detail_survives_live_validation_and_saved_migration(self):
        g=pose_row(CASES[0])["geometry"]
        self.assertGreater(len(g["pose_detail"]),160)
        self.assertEqual(validate_geometry(g),g)
        self.assertEqual(migrate_saved_geometry(g),(g,False))
        with self.assertRaises(ValueError):validate_geometry({"pose_detail":"x"*(GEOMETRY_FIELDS["pose_detail"].max_length+1)})

    def test_custom_detail_does_not_inherit_conventional_torso_head_rotation_assumptions(self):
        row=pose_row(CASES[4])
        row["geometry"].update(camera_azimuth="direct_rear",body_orientation="direct_rear",
            torso_orientation="front",hip_orientation="direct_rear",head_direction="toward_camera",
            gaze_direction="toward_camera",face_visibility="full")
        row["scene"]="The curled body presents its back; its folded torso and head turn toward the camera. " + row["geometry"]["pose_detail"]
        self.assertFalse(geometry_errors(row,dataset_type="Character"))
        row["geometry"]["gaze_direction"]="eyes_closed"
        row["scene"]="Looking directly at the camera with eyes closed."
        self.assertTrue(geometry_errors(row,dataset_type="Character"))

    def test_unrelated_schema_repair_cannot_destroy_pose_or_scene(self):
        original=pose_row(CASES[0]);original["geometry"]["camera_elevation"]="invalid_elevation"
        snapshot=deepcopy(original)
        changed=pose_row(CASES[0]);changed["scene"]="A full-body character in a generic seated yoga pose."
        changed["geometry"].update(framing="full_body",pose_type="sitting_upright",pose_detail="Sitting upright with hands on lap",
            body_visibility="full_body",required_visible_parts=["face"],camera_elevation="eye_level")
        session=Mock();session.generate.return_value=json.dumps([changed])
        data=draft(amount=1)
        result=ScenePlanner(lambda:None).repair_scene(session=session,data=data,assignments=dataset_assignments(data),
            row=original,errors=["Invalid camera_elevation"],progress=lambda _:None)
        self.assertEqual(original,snapshot)
        self.assertEqual(result["scene"],original["scene"])
        self.assertEqual(result["geometry"],{**original["geometry"],"camera_elevation":"eye_level"})
        context=json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual(context["locked_geometry"]["required_visible_parts"],["face","torso","feet"])
        self.assertNotIn("camera_elevation",context["locked_geometry"])

    def test_missing_pose_detail_can_be_repaired_without_changing_crop(self):
        original=pose_row(CASES[0]);original["geometry"].pop("pose_detail")
        repaired=pose_row(CASES[0]);repaired["geometry"]["framing"]="full_body"
        session=Mock();session.generate.return_value=json.dumps([repaired]);data=draft(amount=1)
        result=ScenePlanner(lambda:None).repair_scene(session=session,data=data,assignments=dataset_assignments(data),row=original,
            errors=["Missing pose_detail"],progress=lambda _:None)
        self.assertEqual(result["geometry"]["framing"],"waist_up")
        self.assertEqual(result["geometry"]["pose_detail"],CASES[0][3])

    def test_pose_locks_survive_multiple_repair_retries(self):
        original=pose_row(CASES[0]);original["geometry"]["camera_elevation"]="invalid_elevation"
        changed=pose_row(CASES[0]);changed["geometry"].update(framing="full_body",camera_elevation="still_invalid")
        good=deepcopy(changed);good["geometry"]["camera_elevation"]="eye_level"
        session=Mock();session.generate.side_effect=[json.dumps([changed]),json.dumps([good])]
        data=draft(amount=1)
        result=ScenePlanner(lambda:None).repair_scene(session=session,data=data,assignments=dataset_assignments(data),
            row=original,errors=["Invalid camera_elevation"],progress=lambda _:None)
        self.assertEqual(session.generate.call_count,2)
        self.assertEqual(result["geometry"],{**original["geometry"],"camera_elevation":"eye_level"})
        for call in session.generate.call_args_list:
            self.assertEqual(json.loads(call.args[0].user_message)["locked_geometry"]["framing"],"waist_up")

    def test_visibility_contradiction_repairs_visibility_not_requested_crop(self):
        original=pose_row(CASES[0]);original["geometry"]["feet_visibility"]="none_visible"
        changed=pose_row(CASES[0]);changed["geometry"]["framing"]="full_body"
        session=Mock();session.generate.return_value=json.dumps([changed]);data=draft(amount=1)
        result=ScenePlanner(lambda:None).repair_scene(session=session,data=data,assignments=dataset_assignments(data),row=original,
            errors=["Required feet cannot also be none_visible"],progress=lambda _:None)
        self.assertEqual(result["geometry"]["framing"],"waist_up")
        self.assertEqual(result["geometry"]["feet_visibility"],"both_visible")
        self.assertEqual(result["geometry"]["pose_detail"],CASES[0][3])

    def test_schema_repair_does_not_lock_forbidden_scene_content(self):
        original=pose_row(CASES[0]);original["geometry"]["camera_elevation"]="invalid_elevation"
        original["scene"] += " She wears a hat."
        changed=pose_row(CASES[0]);changed["geometry"]["camera_elevation"]="eye_level"
        session=Mock();session.generate.return_value=json.dumps([changed]);data=draft(amount=1,constraints="no hat")
        result=ScenePlanner(lambda:None).repair_scene(session=session,data=data,assignments=dataset_assignments(data),row=original,
            errors=["Invalid camera elevation", "Forbidden hat"],progress=lambda _:None)
        self.assertEqual(result["scene"],changed["scene"])
        self.assertEqual(result["geometry"]["framing"],"waist_up")

    def test_saved_old_scenes_load_without_inferred_parts_or_changed_signatures(self):
        row=pose_row(CASES[0]);row["geometry"].pop("required_visible_parts");row["geometry"]["body_visibility"]="upper_body"
        data=saved(draft(amount=1),[row]);restored=validate_dataset_draft(data)
        self.assertEqual(restored["scene_plan_signature"],data["scene_plan_signature"])
        self.assertIsNotNone(reusable_scene_plan(restored,dataset_assignments(restored)))
        self.assertEqual(restored["scene_plan"][0]["geometry"]["framing"],"waist_up")
        self.assertEqual(restored["scene_plan"][0]["geometry"].get("required_visible_parts",[]),[])
        self.assertEqual(restored["results"][0]["prompt"],data["results"][0]["prompt"])

    def test_writer_receives_unflattened_geometry_and_returns_specific_positive_prompt(self):
        row=pose_row(CASES[0]);data=saved(draft(amount=1),[row])
        output="person_token in a tight waist-up composition, head and torso dominating the frame, hips supported on floor, knees raised beside shoulders, lower legs folded behind head, ankles behind neck, both feet visible beside head."
        result,session,_=run(data,[output])
        self.assertEqual(result["prompts"][0]["prompt"],output)
        self.assertEqual(result["prompts"][0]["geometry"],row["geometry"])
        instruction=session.generate.call_args.args[0]
        self.assertIn(json.dumps(row["geometry"]),instruction.user_message)
        self.assertIn("Framing is crop/composition, independent of anatomical visibility",instruction.system_message)
        self.assertNotIn("full-body",output)
        self.assertNotIn("yoga pose",output)
        self.assertNotIn("dynamic pose",output)

    def test_generated_schema_and_both_scene_prompts_teach_principle(self):
        data=draft(amount=1)
        for instruction in (scene_planner_instruction(data,dataset_assignments(data)),
                            scene_composer_instruction(data,dataset_assignments(data),[pose_row(CASES[0])])):
            self.assertIn("FRAMING AND BODY VISIBILITY ARE INDEPENDENT",instruction.system_message)
            self.assertIn("waist_up",instruction.system_message)
            self.assertIn("required_visible_parts",instruction.system_message)
            self.assertNotIn("a concise pose_detail",instruction.system_message)

    def test_geometry_is_drafted_before_scene_with_one_shared_load_path(self):
        from goated_prompter.prompting.scene_planner import MECHANICS_FIRST_DRAFT
        data = draft(amount=1, source_mode="guided", inputs="An unfamiliar apparatus-supported folded configuration")
        for instruction in (scene_planner_instruction(data, dataset_assignments(data)),
                            scene_composer_instruction(data, dataset_assignments(data), [pose_row(CASES[0])])):
            self.assertIn(MECHANICS_FIRST_DRAFT, instruction.system_message)
            self.assertIn("Write geometry BEFORE scene", instruction.system_message)
            self.assertIn("Repeat this SAME contact relationship", instruction.system_message)
            self.assertNotIn("INPUT: upper body, both feet behind neck", instruction.system_message)
            self.assertNotIn("Compact seated contortion; hips supported on floor", instruction.system_message)

    def test_planner_keeps_sampling_with_expanded_idea_budget(self):
        data = draft(amount=1)
        fast = scene_planner_instruction(data, dataset_assignments(data))
        quality = scene_composer_instruction(data, dataset_assignments(data), [pose_row(CASES[0])])
        self.assertEqual((fast.max_tokens, fast.hard_max_tokens), (1536, 1536))
        self.assertEqual((quality.max_tokens, quality.hard_max_tokens), (1280, 1280))
        self.assertEqual((quality.temperature, quality.top_p), (.25, .85))

    def test_writer_reads_original_source_and_geometry_before_scene_narrative(self):
        from goated_prompter.prompting.dataset import dataset_instruction
        from goated_prompter.core import GoatedPrompterRequest
        row = {**pose_row(CASES[5]), "input": CASES[5][1]}
        data = draft(amount=1, source_mode="guided", inputs=CASES[5][1])
        instruction = dataset_instruction(GoatedPrompterRequest(idea=CASES[5][1]), data, 1, plan_item=row)
        text = instruction.user_message
        self.assertLess(text.index("GUIDED INPUT"), text.index("PLANNED IDEA"))
        self.assertLess(text.index("PLANNED GEOMETRY"), text.index("PLANNED SCENE / CURRENT SCENE"))
        self.assertIn(json.dumps(row["geometry"]), text)
        self.assertIn("Reuse the established support/contact clause", instruction.system_message)

    def test_missing_index_uses_output_envelope_correction_not_creative_replanning(self):
        row=pose_row(CASES[2]);row.pop("index")
        with self.assertRaises(SceneFormatError) as caught:
            validate_scene_plan(json.dumps([row]),1)
        self.assertIn("SCENE OUTPUT FORMAT CORRECTION",caught.exception.correction)
        self.assertIn("Requested indexes in order: [1]",caught.exception.correction)

    def test_deep_review_sees_required_anatomy_and_actual_pose_detail(self):
        from goated_prompter.prompting.dataset import deep_review_instruction
        row={**pose_row(CASES[0]),"prompt":"pose_subject in a waist-up contortion."}
        instruction=deep_review_instruction(draft(amount=1),[row])
        self.assertIn(json.dumps(row["geometry"]),instruction.user_message)
        self.assertIn("Framing is independent of anatomical visibility",instruction.system_message)
        self.assertNotIn("tight face close-up plus clearly visible shoes",instruction.system_message)

    def test_exact_frozen_real_scene_normalizes_without_replacing_hand_support(self):
        fixture=Path(__file__).parent/"eval/fixtures/model_outputs/complex_pose_scene.json"
        raw=json.loads(fixture.read_text(encoding="utf-8"))["raw"]
        original=json.loads(raw)[0]
        row=validate_scene_plan(raw,1,dataset_type="Character")[0]
        self.assertFalse(geometry_errors(row,dataset_type="Character"))
        self.assertNotIn("leg_position",row["geometry"])
        self.assertIn("legs",row["geometry"]["required_visible_parts"])
        self.assertEqual(row["geometry"]["pose_detail"],original["geometry"]["pose_detail"])
        self.assertEqual(row["scene"],original["scene"])
