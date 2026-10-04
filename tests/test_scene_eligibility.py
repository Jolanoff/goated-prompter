import unittest
from goated_prompter.scene_eligibility import scene_eligibility
from goated_prompter.scene_planner import scene_is_usable, scene_unusable_reason


class SceneEligibilityTests(unittest.TestCase):
    def test_one_policy_for_manual_legacy_and_invalid_structured(self):
        data = {"trigger_type": "Character"}
        cases = [
            ({"idea": "Read", "scene": "A person reads on a bench.", "geometry": {}}, True, "manual_prose"),
            ({"scene": "A person reads on a bench."}, True, "legacy_scene"),
            ({"idea": "Read", "scene": "A person reads.", "geometry": {"framing": "full_body"}}, False, "structured_scene"),
            ({"idea": "", "scene": "A person reads."}, False, "manual_prose"),
            ({"idea": "Read", "scene": "A person reads.", "scene_status": "failed"}, False, "manual_prose")]
        for row, usable, source in cases:
            with self.subTest(row=row):
                eligibility = scene_eligibility(row, data)
                self.assertEqual(eligibility.usable, usable)
                self.assertEqual(eligibility.source_kind, source)
                self.assertEqual(scene_is_usable(row, data), usable)
                self.assertEqual(scene_unusable_reason(row, data), eligibility.reason)
