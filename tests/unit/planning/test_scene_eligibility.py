import unittest
from goated_prompter.features.dataset.eligibility import scene_eligibility
from goated_prompter.features.dataset.plan import scene_is_usable, scene_unusable_reason
from tests.support.dataset import saved_scene


class SceneEligibilityTests(unittest.TestCase):
    def test_current_grounded_scene_spec_evidence_is_the_writer_gate(self):
        row = saved_scene(scene="A person reads on a bench.")
        for patch, usable in (({}, True), ({"self_check": ""}, True), ({"scene_status": "not_generated"}, True),
                              ({"scene": ""}, False), ({"scene": "   "}, False), ({"scene_status": "failed"}, False),
                              ({"scene_spec": None}, False), ({"scene_validation": None}, False),
                              ({"scene": "A person sleeps on a bench."}, False),
                              ({"self_check": "REPAIR:\nRequired hands hidden.\nMove them outward."}, False)):
            candidate = {**row, **patch}
            eligibility = scene_eligibility(candidate, {})
            self.assertEqual(eligibility.usable, usable)
            self.assertEqual(scene_is_usable(candidate, {}), usable)
            self.assertEqual(scene_unusable_reason(candidate, {}), eligibility.reason)
