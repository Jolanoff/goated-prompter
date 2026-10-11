import unittest
from goated_prompter.features.dataset.eligibility import scene_eligibility
from goated_prompter.features.dataset.plan import scene_is_usable, scene_unusable_reason


class SceneEligibilityTests(unittest.TestCase):
    def test_a_written_scene_that_has_not_failed_is_the_writer_gate(self):
        row = {"scene": "A person reads on a bench.", "self_check": "PASS", "scene_status": "valid"}
        # Ideas arrive as finished scenes and user edits are used as written.
        for patch, usable in (({}, True), ({"self_check": ""}, True), ({"scene_status": "not_generated"}, True),
                              ({"scene": ""}, False), ({"scene": "   "}, False), ({"scene_status": "failed"}, False),
                              ({"self_check": "REPAIR:\nRequired hands hidden.\nMove them outward."}, False)):
            candidate = {**row, **patch}
            eligibility = scene_eligibility(candidate, {})
            self.assertEqual(eligibility.usable, usable)
            self.assertEqual(scene_is_usable(candidate, {}), usable)
            self.assertEqual(scene_unusable_reason(candidate, {}), eligibility.reason)
