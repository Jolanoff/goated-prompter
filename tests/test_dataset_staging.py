"""Type profiles, generated schemas, modular rules and saved staging migration."""

import inspect
import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from goated_prompter.dataset import validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_quality import analyze_dataset_quality
from goated_prompter.dataset_staging import (
    FieldSpec, GEOMETRY_FIELDS, GeometryIssue, STAGING_PROFILES, geometry_errors, geometry_issues,
    geometry_prompt_schema, migrate_saved_geometry, resolve_framing_conflicts, validate_geometry,
)
from goated_prompter.dataset_staging.profiles import get_profile
from goated_prompter.dataset_staging.rules import COMMON_RULES, RULE_GROUPS, Rule, issue
from goated_prompter.dataset_staging.rules.prose import explicit_geometry_issues
from goated_prompter.dataset_staging.vocabulary import BODY_ORIENTATION_VALUES, CAMERA_AZIMUTH_VALUES
from goated_prompter.prompting.dataset import DATASET_TYPES
from goated_prompter.prompting.scene_planner import scene_planner_instruction, scene_composer_instruction
from goated_prompter.scene_planner import ScenePlanner, reusable_scene_plan
from tests.test_dataset_geometry import character_geometry
from tests.test_dataset_quality_planning import draft, saved, run


def staging(kind):
    if kind == "Character":
        return character_geometry(action_focus="displaying a ribbon")
    if kind == "Multiple characters":
        return {"framing": "full_subject", "camera_azimuth": "front", "composition": "layered",
                "primary_subject_count": 2, "action_visibility": "clear"}
    return {"framing": "wide", "composition": "environmental"}


class StagingProfileTests(unittest.TestCase):
    def test_profiles_cover_every_dataset_type_and_use_only_registered_fields(self):
        self.assertEqual(set(STAGING_PROFILES), set(DATASET_TYPES))
        for kind, profile in STAGING_PROFILES.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(profile.required | profile.recommended, profile.allowed)
                self.assertLessEqual(profile.allowed, GEOMETRY_FIELDS.keys())
                self.assertLessEqual(set(profile.rule_groups), RULE_GROUPS.keys())
                self.assertEqual(validate_geometry(staging(kind), dataset_type=kind), staging(kind))

    def test_multi_character_has_no_global_human_direction_or_face(self):
        geometry = staging("Multiple characters")
        self.assertEqual(validate_geometry(geometry, dataset_type="Multiple characters"), geometry)
        self.assertFalse(geometry_errors({"geometry": geometry, "scene": "Two people face in different directions."}, dataset_type="Multiple characters"))
        for field in ("head_direction", "gaze_direction", "face_visibility", "body_orientation"):
            self.assertNotIn(field, STAGING_PROFILES["Multiple characters"].allowed)
        for missing in STAGING_PROFILES["Multiple characters"].required:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "missing"):
                validate_geometry({key: value for key, value in geometry.items() if key != missing}, dataset_type="Multiple characters")

    def test_multi_character_recommended_contact_state_is_allowed_and_advertised(self):
        kind = "Multiple characters"
        geometry = {**staging(kind), "contact_state": "touching"}
        self.assertIn("contact_state", STAGING_PROFILES[kind].recommended)
        self.assertIn("contact_state", STAGING_PROFILES[kind].allowed)
        self.assertEqual(validate_geometry(geometry, dataset_type=kind), geometry)
        self.assertIn("contact_state:", geometry_prompt_schema(kind))
        self.assertFalse(geometry_errors({"geometry": geometry}, dataset_type=kind))

    def test_added_body_state_fields_validate_and_migrate_for_selected_profiles(self):
        body_state = {"leg_position": "knees_bent", "pelvis_tilt": "tilted_up", "back_arch": "slight"}
        for kind in ("Character", "Custom"):
            with self.subTest(kind=kind):
                geometry = {**staging(kind), **body_state}
                self.assertEqual(validate_geometry(geometry, dataset_type=kind), geometry)
                self.assertEqual(migrate_saved_geometry(geometry, dataset_type=kind), (geometry, False))
                for name in body_state:
                    self.assertIn(name + ":", geometry_prompt_schema(kind))
        for kind in set(DATASET_TYPES) - {"Character", "Custom"}:
            for name, value in body_state.items():
                with self.subTest(kind=kind, field=name), self.assertRaisesRegex(ValueError, "not applicable"):
                    validate_geometry({**staging(kind), name: value}, dataset_type=kind)

    def test_animal_staging_never_requires_human_anatomy(self):
        geometry = {"framing": "full_subject", "camera_azimuth": "profile_left", "subject_orientation": "profile_left",
                    "movement": "active", "pose_detail": "a dog bounding through shallow water"}
        self.assertEqual(validate_geometry(geometry, dataset_type="Animal"), geometry)
        self.assertFalse(geometry_errors({"geometry": geometry, "scene": "A dog bounds through a stream."}, dataset_type="Animal"))
        for field in ("expression", "hand_visibility", "feet_visibility", "face_visibility", "pose_type"):
            self.assertNotIn(field, STAGING_PROFILES["Animal"].allowed)

    def test_product_example_validates_without_any_human_fields(self):
        geometry = {"framing": "full_body_with_environment", "camera_azimuth": "front_three_quarter_left",
                    "camera_elevation": "eye_level", "subject_scale": "large", "composition": "centered"}
        self.assertEqual(validate_geometry(geometry, dataset_type="Object / product"), geometry)
        self.assertFalse(geometry_errors({"geometry": geometry}, dataset_type="Object / product"))

    def test_environment_style_brand_text_concept_and_custom_can_be_minimal(self):
        for kind in ("Location / environment", "Visual style", "Brand / logo", "Typography / text", "Concept", "Custom"):
            with self.subTest(kind=kind):
                self.assertEqual(validate_geometry({}, dataset_type=kind), {})
                self.assertFalse(geometry_errors({"geometry": {}, "scene": "A layered composition."}, dataset_type=kind))
                self.assertNotIn("character", get_profile(kind).rule_groups)

    def test_nonhuman_types_reject_inapplicable_human_fields_not_missing_human_facts(self):
        for kind in set(DATASET_TYPES) - {"Character"}:
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "not applicable"):
                validate_geometry({**staging(kind), "gaze_direction": "toward_camera"}, dataset_type=kind)

    def test_required_character_schema_is_the_same_in_fast_and_quality(self):
        for mode in ("Fast", "Quality"):
            data, session = draft(amount=1, planning_mode=mode), Mock()
            row = {"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon.", "geometry": character_geometry()}
            bad = {**row, "geometry": {key: value for key, value in row["geometry"].items() if key != "gaze_direction"}}
            outputs = [json.dumps([bad]), json.dumps([row])]
            if mode == "Quality":
                outputs.insert(0, json.dumps([{"index": 1, "idea": row["idea"]}]))
            session.generate.side_effect = outputs
            result = ScenePlanner(lambda: None).plan_batch(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _: None)
            self.assertEqual(result, [row])
            self.assertEqual(session.generate.call_args.args[0].diagnostic_stage, "dataset:scene_composer:repair")
            self.assertEqual(session.generate.call_count, len(outputs))

    def test_all_types_compose_in_both_modes_without_human_schema_repairs(self):
        for kind in DATASET_TYPES:
            for mode in ("Fast", "Quality"):
                with self.subTest(kind=kind, mode=mode):
                    data, session = draft(amount=1, trigger_type=kind, planning_mode=mode), Mock()
                    row = {"index": 1, "idea": "Displaying a ribbon", "scene": "A clear ribbon presentation.", "geometry": staging(kind)}
                    outputs = [json.dumps([row])]
                    if mode == "Quality":
                        outputs.insert(0, json.dumps([{"index": 1, "idea": row["idea"]}]))
                    session.generate.side_effect = outputs
                    planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                        assignments=dataset_assignments(data), progress=lambda _: None)
                    self.assertEqual(planned, [row])
                    self.assertEqual(session.generate.call_count, len(outputs))
                    self.assertTrue(all(":repair" not in call.args[0].diagnostic_stage for call in session.generate.call_args_list))

    def test_old_character_flag_is_gone_and_unknown_types_do_not_assume_character(self):
        for function in (validate_geometry, geometry_errors, resolve_framing_conflicts):
            self.assertNotIn("character", inspect.signature(function).parameters)
        with self.assertRaisesRegex(ValueError, "Unsupported Dataset"):
            validate_geometry({}, dataset_type="Unsupported")


class StagingSchemaTests(unittest.TestCase):
    def test_every_type_prompt_schema_matches_its_profile_and_registry(self):
        for kind, profile in STAGING_PROFILES.items():
            schema = geometry_prompt_schema(kind)
            with self.subTest(kind=kind):
                for name in GEOMETRY_FIELDS:
                    self.assertEqual(any(line.startswith(name + ":") for line in schema.splitlines()), name in profile.allowed)
                for name in profile.required:
                    self.assertIn(name, schema.splitlines()[1])
                for name in profile.recommended:
                    self.assertIn(name, schema.splitlines()[2])

    def test_nonhuman_planner_and_composer_do_not_advertise_human_fields(self):
        forbidden = {"body_orientation", "head_direction", "gaze_direction", "face_visibility", "feet_visibility", "hand_visibility", "expression"}
        for kind in set(DATASET_TYPES) - {"Character"}:
            data = draft(trigger_type=kind)
            for instruction in (scene_planner_instruction(data, dataset_assignments(data)),
                                scene_composer_instruction(data, dataset_assignments(data), [{"index": 1, "idea": "Display"}])):
                with self.subTest(kind=kind, stage=instruction.diagnostic_stage):
                    for field in forbidden:
                        # Ordinary prose may discuss expressions; it must not
                        # advertise expression as a structured output field.
                        self.assertNotIn(field if "_" in field else field + ":", instruction.system_message)
                    values = json.loads(instruction.user_message).get("optional_geometry_values", {})
                    self.assertFalse(forbidden & values.keys())
                    self.assertLessEqual(values.keys(), STAGING_PROFILES[kind].allowed)

    def test_camera_axes_and_orientation_do_not_contain_pose_states(self):
        for forbidden in ("overhead", "high_angle", "low_angle", "ground_level", "between_legs"):
            self.assertNotIn(forbidden, CAMERA_AZIMUTH_VALUES)
        for forbidden in ("lying_face_up", "kneeling", "bent_forward", "arched_back", "on_all_fours", "missionary"):
            self.assertNotIn(forbidden, BODY_ORIENTATION_VALUES)
        for field in ("body_orientation", "torso_orientation", "hip_orientation"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_geometry({field: "bent_forward"})
        valid = {"camera_azimuth": "profile_right", "camera_elevation": "overhead", "camera_distance": "close",
                 "view_detail": "a tilted view through a narrow opening"}
        self.assertEqual(validate_geometry(valid, dataset_type="Custom"), valid)

    def test_field_extension_needs_registry_profile_and_optional_rule_not_planner_edits(self):
        profile = STAGING_PROFILES["Custom"]
        with patch.dict(GEOMETRY_FIELDS, {"test_staging_detail": FieldSpec("test_staging_detail", free_text=True)}), \
             patch.dict(STAGING_PROFILES, {"Custom": replace(profile, allowed=profile.allowed | {"test_staging_detail"})}):
            self.assertEqual(validate_geometry({"test_staging_detail": "supported detail"}, dataset_type="Custom"), {"test_staging_detail": "supported detail"})
            self.assertIn("test_staging_detail:", geometry_prompt_schema("Custom"))


class StagingRuleTests(unittest.TestCase):
    def test_registered_rules_return_structured_actionable_issues(self):
        row = {"geometry": character_geometry(camera_azimuth="direct_rear", body_orientation="direct_rear", face_visibility="full")}
        problems = geometry_issues(row, "Character")
        self.assertTrue(problems)
        self.assertTrue(all(isinstance(problem, GeometryIssue) and problem.fields and problem.code and problem.repair for problem in problems))
        self.assertEqual(geometry_errors(row, dataset_type="Character"), list(dict.fromkeys(problem.message for problem in problems)))
        self.assertTrue(all(isinstance(rule, Rule) for rule in COMMON_RULES))

    def test_new_rule_group_can_be_registered_without_engine_branches(self):
        new_rule = Rule("test_rule", lambda context: [issue("test_issue", ("framing",), "Test issue")])
        profile = replace(STAGING_PROFILES["Custom"], rule_groups=("test_group",))
        with patch.dict(RULE_GROUPS, {"test_group": (new_rule,)}), patch.dict(STAGING_PROFILES, {"Custom": profile}):
            self.assertEqual([problem.code for problem in geometry_issues({"geometry": {}}, "Custom")], ["test_issue"])

    def test_character_prose_rules_do_not_leak_into_other_types_or_groups(self):
        text = "Direct rear view, full frontal face toward the camera."
        self.assertTrue(explicit_geometry_issues(text, "Character"))
        for kind in set(DATASET_TYPES) - {"Character"}:
            with self.subTest(kind=kind):
                self.assertFalse(explicit_geometry_issues(text, kind))
                geometry = {**staging(kind), "camera_azimuth": "direct_rear"}
                self.assertFalse(geometry_errors({"geometry": geometry, "scene": text}, dataset_type=kind))
        for kind in DATASET_TYPES:
            self.assertTrue(explicit_geometry_issues("Camera is directly in front; camera is directly behind.", kind))

    def test_products_check_presentation_whole_product_and_required_features(self):
        kind = "Object / product"
        opposed = {"geometry": {"camera_azimuth": "front", "subject_orientation": "direct_rear"}}
        self.assertIn("opposed_presentation", {problem.code for problem in geometry_issues(opposed, kind)})
        cropped = {"idea": "Show the entire product", "scene": "The entire product in a close-up shot.", "geometry": {"framing": "detail_close_up"}}
        self.assertIn("required_detail_crop", {problem.code for problem in geometry_issues(cropped, kind)})
        widened = resolve_framing_conflicts(cropped, dataset_type=kind)
        self.assertEqual(widened["geometry"]["framing"], "full_subject")
        self.assertEqual(widened["idea"], cropped["idea"])
        self.assertFalse(geometry_errors(widened, dataset_type=kind))
        hidden = {"idea": "Entire readable product", "geometry": {"occlusion": "major", "visibility_focus": ["brand panel"]},
                  "scene": "The brand panel is completely obscured."}
        self.assertTrue({"required_feature_hidden", "required_readability_occluded"} <= {problem.code for problem in geometry_issues(hidden, kind)})

    def test_brand_text_and_environment_visibility_never_check_literal_spelling(self):
        for kind, feature in (("Brand / logo", "logo"), ("Typography / text", "lettering"), ("Location / environment", "landmark")):
            row = {"geometry": {"visibility_focus": [feature]}, "scene": f"The {feature} is outside the frame."}
            with self.subTest(kind=kind):
                self.assertIn("required_feature_hidden", {problem.code for problem in geometry_issues(row, kind)})
                self.assertFalse(geometry_errors({"geometry": {}, "scene": 'A sign reads "hello".'}, dataset_type=kind))

    def test_quality_reports_use_selected_type_and_do_not_import_back_into_rules(self):
        row = {"index": 1, "input": "", "prompt": "item_token. Camera directly behind, full frontal face visible.",
               "scene": "Camera directly behind, full frontal face visible.", "geometry": {"framing": "wide"}}
        product = analyze_dataset_quality(draft(trigger_type="Object / product", trigger="item_token"), [row])
        codes = {problem["code"] for problem in product["prompts"][0]["issues"]}
        self.assertNotIn("scene_rear_front_conflict", codes)
        human = analyze_dataset_quality(draft(trigger_type="Character", trigger="item_token"), [row])
        self.assertIn("scene_rear_front_conflict", {problem["code"] for problem in human["prompts"][0]["issues"]})


class StagingMigrationTests(unittest.TestCase):
    def test_safe_camera_rename_preserves_current_plan_signature_and_prompts(self):
        geometry = character_geometry()
        legacy = {key: value for key, value in geometry.items() if key != "camera_azimuth"}
        legacy.update(camera_view="front three-quarter left", camera_height="eye-level")
        data = saved(draft(amount=1), [{"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon.", "geometry": legacy}])
        restored = validate_dataset_draft(data)
        self.assertEqual(restored["scene_plan_signature"], data["scene_plan_signature"])
        self.assertIsNotNone(reusable_scene_plan(restored, dataset_assignments(restored)))
        row = restored["scene_plan"][0]
        self.assertEqual(row["geometry"]["camera_azimuth"], "front_three_quarter_left")
        self.assertEqual(row["geometry"]["camera_elevation"], "eye_level")
        self.assertNotIn("camera_view", row["geometry"])
        self.assertEqual(restored["results"][0]["prompt"], data["results"][0]["prompt"])
        result, writer, _ = run(restored, ["person_token displays a ribbon."])
        self.assertEqual(writer.generate.call_count, 1)
        self.assertEqual(result["scene_plan"][0]["scene"], data["scene_plan"][0]["scene"])

    def test_geometry_less_manual_or_legacy_scene_is_not_rewritten_to_fill_metadata(self):
        for mode in ("Fast", "Quality"):
            for valid_only in (False, True):
                with self.subTest(mode=mode, valid_only=valid_only):
                    row = {"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon beside a blue window.", "geometry": {}}
                    data = validate_dataset_draft(saved(draft(amount=1, planning_mode=mode), [row]))
                    result, session, _ = run(data, ["person_token displays a ribbon beside a blue window."], valid_only=valid_only)
                    self.assertEqual(session.generate.call_count, 1)
                    self.assertEqual(session.generate.call_args.args[0].diagnostic_stage, "dataset:1")
                    self.assertEqual(result["prompts"][0]["scene"], row["scene"])
                    self.assertEqual(result["scene_plan"][0]["geometry"], {})

    def test_elevation_migration_never_invents_an_azimuth(self):
        for old, new in (("overhead", "overhead"), ("high-angle", "high"), ("low_angle", "low"), ("birds eye", "overhead")):
            with self.subTest(old=old):
                geometry, warning = migrate_saved_geometry({"camera_view": old}, dataset_type="Object / product")
                self.assertEqual(geometry, {"camera_elevation": new})
                self.assertFalse(warning)
                self.assertNotIn("camera_azimuth", geometry)

    def test_unsided_three_quarter_and_specific_height_never_guess_new_facts(self):
        geometry, warning = migrate_saved_geometry({"camera_view": "front three-quarter", "camera_height": "knee_level"})
        self.assertEqual(geometry["camera_azimuth"], "front_three_quarter")
        self.assertNotIn("camera_elevation", geometry)
        self.assertIn("knee level", geometry["view_detail"])
        self.assertFalse(warning)

    def test_pose_values_move_out_of_orientation_without_guessing_viewing_side(self):
        for old in ("lying_face_up", "lying_on_right_side", "bent_forward", "on_all_fours_arched", "missionary"):
            with self.subTest(old=old):
                geometry, warning = migrate_saved_geometry({"body_orientation": old})
                self.assertNotIn("body_orientation", geometry)
                self.assertIn(old.replace("_", " "), geometry["pose_detail"])
                self.assertIn(geometry["pose_type"], GEOMETRY_FIELDS["pose_type"].values)
                self.assertTrue(warning)

    def test_user_added_unusual_camera_pose_and_head_values_are_preserved_as_details(self):
        geometry, warning = migrate_saved_geometry({"camera_view": "through_legs", "pose_type": "unlisted_balanced_state",
            "hip_orientation": "thrust_forward", "head_direction": "unlisted_head_state"})
        self.assertIn("through legs", geometry["view_detail"])
        self.assertEqual(geometry["pose_type"], "custom")
        self.assertIn("unlisted balanced state", geometry["pose_detail"])
        self.assertIn("hip thrust forward", geometry["pose_detail"])
        self.assertIn("head unlisted head state", geometry["pose_detail"])
        self.assertTrue(warning)

    def test_user_requested_expanded_pose_and_head_vocabulary_stays_canonical(self):
        geometry = {"pose_type": "against_wall_lifted", "head_direction": "head_thrown_back"}
        self.assertEqual(validate_geometry(geometry), geometry)
        self.assertEqual(migrate_saved_geometry(geometry), (geometry, False))

    def test_ambiguous_or_invalid_saved_fields_are_row_local_and_siblings_survive(self):
        good = {"index": 1, "idea": "Displaying a ribbon", "scene": "She displays a ribbon.", "geometry": character_geometry()}
        bad = {**good, "index": 2, "geometry": {"camera_view": "side", "framing": "full_body", "unsupported": "value", "gaze_direction": []}}
        data = saved(draft(), [good, bad])
        restored = validate_dataset_draft(data)
        self.assertEqual(restored["scene_plan"][0], data["scene_plan"][0])
        self.assertEqual(restored["scene_plan"][1]["scene_status"], "geometry_warning")
        self.assertEqual(restored["scene_plan"][1]["geometry"], {"framing": "full_body", "view_detail": "side"})
        self.assertEqual([row["prompt"] for row in restored["results"]], [row["prompt"] for row in data["results"]])
        self.assertEqual(migrate_saved_geometry(None), ({}, True))
        self.assertEqual(migrate_saved_geometry({"camera_view": []}), ({}, True))

    def test_current_fields_win_over_conflicting_legacy_axes(self):
        geometry, warning = migrate_saved_geometry({"camera_azimuth": "front", "camera_view": "direct_rear"})
        self.assertEqual(geometry["camera_azimuth"], "front")
        self.assertTrue(warning)

    def test_ambiguous_saved_row_repairs_locally_without_regenerating_valid_sibling_or_ideas(self):
        rows = [{"index": index, "idea": f"Displaying a ribbon {index}",
                 "scene": f"She displays ribbon {index}.", "geometry": character_geometry(action_focus="displaying a ribbon")}
                for index in (1, 2)]
        legacy = {**rows[1]["geometry"], "camera_view": "side"}
        legacy.pop("camera_azimuth")
        data = validate_dataset_draft(saved(draft(), [rows[0], {**rows[1], "geometry": legacy}]))
        self.assertEqual(data["scene_plan"][1]["scene_status"], "geometry_warning")
        result, session, _ = run(data, [json.dumps([rows[1]]), "person_token displays ribbon 1.", "person_token displays ribbon 2."])
        self.assertEqual([call.args[0].diagnostic_stage for call in session.generate.call_args_list],
                         ["dataset:scene_composer:repair", "dataset:1", "dataset:2"])
        context = json.loads(session.generate.call_args_list[0].args[0].user_message)
        self.assertEqual([row["index"] for row in context["assignments"]], [2])
        self.assertEqual(context["assignments"][0]["idea"], rows[1]["idea"])
        self.assertEqual(result["scene_plan"][0]["geometry"], rows[0]["geometry"])
        self.assertEqual(result["scene_plan"][0]["scene"], rows[0]["scene"])
        self.assertEqual(result["completed"], 2)

    def test_saved_nonhuman_geometry_drops_human_helpers_without_requiring_them(self):
        geometry, warning = migrate_saved_geometry({"framing": "full_subject", "camera_view": "front",
            "body_orientation": "front", "head_direction": "toward_camera", "gaze_direction": "toward_camera",
            "hand_visibility": "both_visible"}, dataset_type="Object / product")
        self.assertEqual(geometry, {"framing": "full_subject", "camera_azimuth": "front", "subject_orientation": "front"})
        self.assertFalse(warning)


if __name__ == "__main__":
    unittest.main()
