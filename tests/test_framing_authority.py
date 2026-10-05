"""Explicit crops survive staging, repair, saved eligibility and final writing."""

import json
import unittest
from unittest.mock import Mock

from goated_prompter.dataset import DatasetService, default_dataset_draft, dataset_instruction
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_staging import resolve_framing_conflicts
from goated_prompter.scene_planner import ScenePlanner
from goated_prompter.scene_eligibility import scene_eligibility
from tests.test_dataset_geometry import character_geometry


class FramingAuthorityTests(unittest.TestCase):
    def test_concept_crop_is_not_overridden_by_planner_in_random_mode(self):
        data = {**default_dataset_draft(), "amount": 1, "subject": "waist-up, a performer juggling"}
        row = {"index": 1, "idea": "Juggling", "scene": "A performer juggling.", "geometry": character_geometry()}
        self.assertFalse(scene_eligibility(row, data).usable)
        session = Mock()
        session.generate.return_value = json.dumps([row])
        result = ScenePlanner(lambda: None)._check_scenes(session, data, dataset_assignments(data),
            [row], "qwen", lambda _message: None)[0]
        self.assertEqual(result["geometry"]["framing"], "waist_up")
        self.assertEqual(session.generate.call_count, 1)

    def test_explicit_crop_in_prose_is_respected_without_geometry(self):
        data = {**default_dataset_draft(), "amount": 1, "subject": "A waist-up shot of a performer juggling"}
        row = {"index": 1, "idea": "Juggling", "scene": "A full-body shot of a performer juggling."}
        self.assertFalse(scene_eligibility(row, data).usable)

    def test_product_whole_subject_requirement_cannot_silently_widen_explicit_crop(self):
        row = {"index": 1, "idea": "Display the whole product", "scene": "A detail close-up of the whole product.",
               "geometry": {"framing": "detail_close_up"}}
        from goated_prompter.dataset_staging.rules.framing import framing_intent
        data = {**default_dataset_draft(), "trigger_type": "Object / product", "subject": "detail close-up, display the whole product"}
        resolved = resolve_framing_conflicts(row, dataset_type=data["trigger_type"], intent=framing_intent(data, row))
        self.assertEqual(resolved, row)
        self.assertFalse(scene_eligibility(resolved, data).usable)

    def test_provenance_distinguishes_user_guided_and_planner_crop(self):
        from goated_prompter.dataset_staging.rules.framing import framing_intent
        row = {"index": 1, "input": "", "geometry": character_geometry()}
        data = {**default_dataset_draft(), "subject": "A performer"}
        self.assertEqual(framing_intent(data, row).source, "planner")
        self.assertEqual(framing_intent({**data, "subject": "waist-up, a performer"}, row).source, "user")
        self.assertEqual(framing_intent({**data, "source_mode": "guided"}, {**row, "input": "close-up, a performer"}).source, "guided")

    def test_conflicting_crops_in_one_source_cannot_fall_back_to_planner_authority(self):
        from goated_prompter.dataset_staging.rules.framing import framing_intent
        row = {"index": 1, "idea": "Juggling", "scene": "A performer juggling.", "geometry": character_geometry()}
        data = {**default_dataset_draft(), "subject": "waist-up, full-body, a performer juggling"}
        intent = framing_intent(data, row)
        self.assertTrue(intent.locked)
        self.assertTrue(intent.conflicts)
        self.assertFalse(scene_eligibility(row, data).usable)

    def test_crop_words_in_literals_or_camera_distance_do_not_lock_composition(self):
        from goated_prompter.dataset_staging.rules.framing import framing_intent
        row = {"index": 1, "geometry": character_geometry()}
        for subject in ('A sign reading "close-up"', "A close-up camera distance to a performer", "Avoid a close-up shot of the performer"):
            intent = framing_intent({**default_dataset_draft(), "subject": subject}, row)
            self.assertEqual(intent.source, "planner")

    def test_nonhuman_framing_maps_only_equivalent_extents(self):
        from goated_prompter.dataset_staging.rules.framing import framing_intent
        data = {**default_dataset_draft(), "trigger_type": "Object / product", "subject": "full-body, a cup"}
        self.assertEqual(framing_intent(data, {"index": 1}).crop, "full_subject")

    def test_writer_rejects_explicit_crop_drift_in_manual_scene(self):
        data = {**default_dataset_draft(), "amount": 1, "trigger": "person_token", "subject": "waist-up, a performer"}
        plan = {"index": 1, "input": "", "idea": "Juggling", "scene": "A performer juggling."}
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=plan)
        session = Mock()
        session.generate.side_effect = ["A full-body shot of person_token juggling.", "A waist-up shot of person_token juggling."]
        result = DatasetService({"backend": "mock"}, lambda: None)._generate(session, instruction, data, 1,
            lambda _message: None, plan)
        self.assertEqual(result, "A waist-up shot of person_token juggling.")
        self.assertEqual(session.generate.call_count, 2)
