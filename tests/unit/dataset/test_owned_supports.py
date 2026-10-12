"""Owned mechanics reject structural conflicts without claiming image correctness."""

from dataclasses import replace
import unittest

from goated_prompter.features.dataset.batch_planner import freeze_scene_spec
from goated_prompter.features.dataset.scene_spec import Contact, Participant, SceneSpec, resolve_supports


class OwnedSupportTests(unittest.TestCase):
    def candidate(self, support="ground", supports=None):
        subjects = (Participant("P1", "person", "subject", "walking", "center", support),
                    Participant("P2", "platform", "prop", "", "foreground", "", kind="object"))
        spec = SceneSpec(1, "general", "Walk beside a platform", subjects, state="provisional")
        candidate = {"index": 1, "action": spec.action, "participants": [
            {key: getattr(item, key) for key in ("id", "role", "pose", "location", "support")} for item in subjects],
            "setting": "", "contacts": []}
        if supports is not None:
            candidate["supports"] = supports
        return spec, candidate

    def test_arbitrary_pose_needs_resolved_support_ownership(self):
        for unresolved in ("", "some unspecified surface"):
            with self.subTest(unresolved=unresolved), self.assertRaises(ValueError):
                freeze_scene_spec(*self.candidate(unresolved))

    def test_known_ground_support_freezes_as_an_owned_relationship(self):
        frozen = freeze_scene_spec(*self.candidate())
        self.assertEqual(frozen.to_dict()["supports"], [{"source": "P1.body", "target": "setting.ground"}])

    def test_explicit_object_surface_is_owned_and_round_trips(self):
        frozen = freeze_scene_spec(*self.candidate("P2.top", [{"source": "P1.feet", "target": "P2.top"}]))
        self.assertEqual(SceneSpec.from_dict(frozen.to_dict()), frozen)

    def test_unknown_owner_self_support_and_nonphysical_support_are_rejected(self):
        for target in ("P9.top", "P1.hand", "unknown"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                freeze_scene_spec(*self.candidate(target, [{"source": "P1.feet", "target": target}]))

    def test_human_pose_rules_do_not_reject_animal_support(self):
        spec, candidate = self.candidate("four_paws_on_ground")
        spec = replace(spec, participants=(replace(spec.participants[0], kind="animal", pose="resting"), spec.participants[1]))
        candidate["participants"][0]["pose"] = "resting"
        frozen = freeze_scene_spec(spec, candidate)
        self.assertEqual(frozen.to_dict()["supports"][0]["source"], "P1.paws")

    def test_mutual_support_cannot_resolve_its_own_load_bearing_cycle(self):
        participants = (Participant("P1", "first", "subject", "lifted", "left", "P2.hands"),
                        Participant("P2", "second", "subject", "lifted", "right", "P1.hands"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            resolve_supports(participants, require_resolved=True)

    def test_only_physical_subjects_can_bear_support(self):
        spec, candidate = self.candidate("P2.top", [{"source": "P1.feet", "target": "P2.top"}])
        spec = replace(spec, participants=(spec.participants[0], replace(spec.participants[1], kind="concept")))
        with self.assertRaisesRegex(ValueError, "Nonphysical"):
            freeze_scene_spec(spec, candidate)

    def test_explicit_support_must_agree_with_a_selected_human_pose(self):
        participants = (Participant("P1", "person", "subject", "standing", "center", "feet_on_floor"),)
        with self.assertRaisesRegex(ValueError, "feet"):
            resolve_supports(participants, (Contact("P1.head", "setting.floor"),), require_resolved=True)
