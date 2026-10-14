"""Owned mechanics reject structural conflicts without claiming image correctness."""

from dataclasses import replace
import unittest

from goated_prompter.features.dataset.batch_planner import freeze_scene_spec
from goated_prompter.features.dataset.scene_spec import Contact, Participant, SceneSpec, resolve_supports


class OwnedSupportTests(unittest.TestCase):
    def test_saved_legacy_spec_is_readable_but_unresolved_support_still_blocks_builder(self):
        from goated_prompter.features.dataset.validation import scene_spec_errors
        spec, _ = self.candidate("supported by some unnamed surface")
        legacy = spec.to_dict()
        legacy.update(state="frozen")
        legacy.pop("supports", None)
        parsed = SceneSpec.from_dict(legacy)
        self.assertEqual(parsed.participants[0].support, "supported by some unnamed surface")
        errors = scene_spec_errors("The traveller walks along a path.", parsed, {})
        self.assertTrue(any("resolved owned support" in error for error in errors), errors)

    def test_legacy_semantic_errors_are_readable_but_do_not_pass_generation_validation(self):
        from goated_prompter.features.dataset.validation import scene_spec_errors
        for support, contacts in (("four_paws_on_ground", []),
                ("ground", [{"source": "P1.paw", "target": "P2.top"}])):
            with self.subTest(support=support, contacts=contacts):
                spec, _ = self.candidate("ground")
                legacy = spec.to_dict()
                legacy.update(state="frozen", contacts=contacts)
                legacy["participants"][0]["support"] = support
                legacy.pop("supports", None)
                parsed = SceneSpec.from_dict(legacy)
                self.assertTrue(any("nonhuman" in error for error in scene_spec_errors("A person walks.", parsed, {})))

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

    def test_explicit_airborne_scene_freezes_without_inventing_surface_support(self):
        participants = (Participant("P1", "first man", "participant", "floating", "left", ""),
                        Participant("P2", "second man", "participant", "floating", "right", ""))
        spec = SceneSpec(1, "adult", "Two adult men having sex in the air", participants,
                         state="provisional")
        candidate = {"index": 1, "action": spec.action, "participants": [
            {key: getattr(item, key) if key != "support" else "airborne"
             for key in ("id", "role", "pose", "location", "support")} for item in participants],
            "setting": "", "contacts": [{"source": "P1.hand", "target": "P2.waist"}], "supports": []}
        frozen = freeze_scene_spec(spec, candidate)
        self.assertEqual(frozen.supports, ())
        self.assertEqual(frozen.contacts, (Contact("P1.hand", "P2.waist"),))
        self.assertEqual([item.support for item in frozen.participants], ["airborne", "airborne"])
        self.assertEqual(SceneSpec.from_dict(frozen.to_dict()), frozen)

    def test_airborne_participant_can_coexist_with_owned_grounded_support(self):
        participants = (Participant("P1", "goalkeeper", "subject", "diving", "left", "airborne"),
                        Participant("P2", "spectator", "subject", "standing", "right", "feet_on_floor"))
        self.assertEqual(resolve_supports(participants, require_resolved=True),
                         (Contact("P2.feet", "setting.floor"),))

    def test_airborne_label_does_not_bypass_support_ownership_checks(self):
        participants = (Participant("P1", "performer", "subject", "floating", "center", "airborne"),)
        for target, error in (("P9.hands", "unknown supporting owner"), ("P1.hand", "own weight-bearing"),
                              ("setting.hand", "physical surface")):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, error):
                resolve_supports(participants, (Contact("P1.body", target),), require_resolved=True)

    def test_airborne_pose_alone_does_not_excuse_unresolved_support(self):
        for support in ("", "unspecified", "some unspecified surface"):
            with self.subTest(support=support), self.assertRaisesRegex(ValueError, "resolved owned support"):
                resolve_supports((Participant("P1", "performer", "subject", "floating", "center", support),),
                                 require_resolved=True)

    def test_rope_suspension_freezes_when_planner_also_labels_body_airborne(self):
        spec, candidate = self.candidate("airborne", [{"source": "P1.wrists", "target": "setting.ropes"}])
        spec = replace(spec, action="An adult man suspended in ropes beside another adult man",
                       participants=(replace(spec.participants[0], pose="suspended"),
                                     replace(spec.participants[1], kind="human", role="partner")))
        candidate["action"] = spec.action
        candidate["participants"][0]["pose"] = "suspended"
        candidate["participants"][1]["role"] = "partner"
        frozen = freeze_scene_spec(spec, candidate)
        self.assertEqual(frozen.supports, (Contact("P1.wrists", "setting.ropes"),))
        self.assertEqual(SceneSpec.from_dict(frozen.to_dict()), frozen)

    def test_rope_wall_and_owned_partner_support_labels_resolve(self):
        for label, target in (("supported_by_rope", "setting.rope"),
                              ("supported_by_ropes", "setting.ropes"),
                              ("supported_by_wall", "setting.wall"),
                              ("supported_by_P2", "P2.body")):
            with self.subTest(label=label):
                spec, candidate = self.candidate(label)
                expected = (Contact("P1.body", target),)
                if label == "supported_by_P2":
                    spec = replace(spec, participants=(spec.participants[0],
                        replace(spec.participants[1], kind="human", pose="standing", support="feet_on_floor")))
                    candidate["participants"][1].update(pose="standing", support="feet_on_floor")
                    expected += (Contact("P2.feet", "setting.floor"),)
                frozen = freeze_scene_spec(spec, candidate)
                self.assertEqual(frozen.supports, expected)

    def test_airborne_owned_supports_still_reject_cycles(self):
        participants = (Participant("P1", "first", "subject", "floating", "left", "airborne"),
                        Participant("P2", "second", "subject", "floating", "right", "airborne"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            resolve_supports(participants, (Contact("P1.body", "P2.hands"), Contact("P2.body", "P1.hands")),
                             require_resolved=True)

    def test_supported_by_owner_does_not_guess_a_missing_partner(self):
        for label in ("supported_by_P9", "supported_by_partner"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                freeze_scene_spec(*self.candidate(label))

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

    def test_additional_owned_supports_do_not_contradict_the_support_label(self):
        rail = Participant("P2", "railing", "prop", "", "right", "", kind="object")
        cases = (
            ((Participant("P1", "person", "subject", "standing", "center", "feet_on_floor"), rail),
             (Contact("P1.hand", "P2.rail"),), Contact("P1.feet", "setting.floor")),
            ((Participant("P1", "person", "subject", "seated", "center", "supported_by_chair"),),
             (Contact("P1.feet", "setting.floor"),), Contact("P1.body", "setting.chair")),
            ((Participant("P1", "first", "subject", "seated", "left", "supported_at_hips_by_P2"),
              Participant("P2", "second", "subject", "seated", "right", "supported_by_chair")),
             (Contact("P1.hips", "P2.lap"),), None),
            ((Participant("P1", "person", "subject", "standing", "center", "feet_on_floor"),),
             (Contact("P1.feet", "setting.ground"),), None),
        )
        for participants, supplied, added in cases:
            with self.subTest(supplied=supplied):
                resolved = resolve_supports(participants, supplied, require_resolved=True)
                self.assertTrue(set(supplied) <= set(resolved))
                if added:
                    self.assertIn(added, resolved)

    def test_label_part_on_a_different_surface_still_contradicts_the_label(self):
        participants = (Participant("P1", "person", "subject", "kneeling", "center", "knees_on_floor"),)
        with self.assertRaisesRegex(ValueError, "contradicts"):
            resolve_supports(participants, (Contact("P1.knees", "setting.bed"),), require_resolved=True)

    def test_standing_person_may_lean_but_feet_bear_the_weight(self):
        participants = (Participant("P1", "person", "subject", "standing", "center", "P2.rail"),
                        Participant("P2", "railing", "prop", "", "right", "", kind="object"))
        with self.assertRaisesRegex(ValueError, "feet"):
            resolve_supports(participants, (Contact("P1.hand", "P2.rail"),), require_resolved=True)

    def test_explicit_support_must_agree_with_a_selected_human_pose(self):
        participants = (Participant("P1", "person", "subject", "standing", "center", "feet_on_floor"),)
        with self.assertRaisesRegex(ValueError, "feet"):
            resolve_supports(participants, (Contact("P1.head", "setting.floor"),), require_resolved=True)


class SupportLabelGrammarTests(unittest.TestCase):
    def test_open_planner_support_is_bounded_without_an_unbounded_pattern(self):
        from goated_prompter.features.dataset.batch_planner import planning_instruction
        from goated_prompter.features.dataset.scene_spec import PARTICIPANT_TEXT_LIMIT
        spec = SceneSpec(1, "general", "An adult repairs a boot.",
            (Participant("P1", "repairer", "", "", "", ""),), state="provisional")
        instruction = planning_instruction({}, [spec])
        support = instruction.json_schema["prefixItems"][0]["properties"]["participants"]["prefixItems"][0]["properties"]["support"]
        self.assertEqual(support, {"type": "string", "maxLength": PARTICIPANT_TEXT_LIMIT})

    def test_unconstrained_wire_text_still_needs_valid_owned_support_when_freezing(self):
        spec = SceneSpec(1, "general", "An adult repairs a boot.",
            (Participant("P1", "repairer", "", "", "", ""),), state="provisional")
        for label in ("stool_support_surface_is_not_allowed_" * 20, "some unspecified surface", "P9.seat"):
            candidate = {"index": 1, "action": spec.action, "setting": "workshop", "contacts": [], "supports": [],
                "participants": [{"id": "P1", "role": "repairer", "pose": "seated", "location": "center", "support": label}]}
            with self.subTest(label=label), self.assertRaises(ValueError):
                freeze_scene_spec(spec, candidate)

    def test_restraint_furniture_and_partner_labels_resolve_to_owned_supports(self):
        import re
        from goated_prompter.features.dataset.scene_spec import SUPPORT_LABEL_PATTERN
        partner = Participant("P2", "partner", "", "standing", "right", "feet_on_floor")
        for label, expected in (("tied_to_bed", Contact("P1.body", "setting.bed")),
                                ("knees_on_bench", Contact("P1.knees", "setting.bench")),
                                ("suspended_from_ceiling_beam", Contact("P1.body", "setting.ceiling_beam")),
                                ("held_by_P2", Contact("P1.body", "P2.body"))):
            with self.subTest(label=label):
                bound = Participant("P1", "bound man", "", "bound", "left", label)
                self.assertIn(expected, resolve_supports((bound, partner), require_resolved=True))
                self.assertTrue(re.fullmatch(SUPPORT_LABEL_PATTERN, label))
        self.assertFalse(re.fullmatch(SUPPORT_LABEL_PATTERN, "wrists tied overhead"))
