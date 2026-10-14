"""SceneSpec is the writer's authority, not a remembered vocabulary label."""

import json
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from dataclasses import replace
import unittest
from unittest.mock import patch

from goated_prompter.features.dataset.eligibility import scene_eligibility
from goated_prompter.features.dataset.plan import ScenePlanner
from goated_prompter.features.dataset.prompting import dataset_instruction, geometry_error
from goated_prompter.features.dataset.private_vocabulary import parse_vocabulary
from goated_prompter.features.dataset.scene_spec import Contact, Participant, SceneSpec
from goated_prompter.features.dataset.validation import scene_spec_errors, text_signature, verify_scenes, validation_instruction
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.batch_planner import plan_scene_specs
from goated_prompter.features.dataset.compatibility import compatible_arrangements, vocabulary_diagnostics
from goated_prompter.features.dataset.routing import ContentRoute
from goated_prompter.features.dataset.routing import resolve_route
from goated_prompter.features.dataset.brainstorm import brainstorm_events, dataset_routing
from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.features.dataset.understanding import validate_understanding, _expand_understanding
from goated_prompter.features.dataset.service import DatasetService
from goated_prompter.features.dataset.plan import validate_saved_scene_plan
from goated_prompter.contracts import GoatedPrompterRequest
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import saved_scene, valid_draft



def inline_refs(schema, definitions=None):
    """Resolve local $defs references so tests inspect the effective constraint."""
    definitions = schema.get("$defs", {}) if definitions is None else definitions
    if isinstance(schema, dict):
        if "$ref" in schema:
            return inline_refs(definitions[schema["$ref"].rsplit("/", 1)[1]], definitions)
        return {key: inline_refs(value, definitions) for key, value in schema.items() if key != "$defs"}
    if isinstance(schema, list):
        return [inline_refs(value, definitions) for value in schema]
    return schema

class SceneSpecGateTests(unittest.TestCase):
    def test_named_age_contradictions_cannot_be_hidden_by_a_checker_pass(self):
        from goated_prompter.features.dataset.validation import scene_spec_findings
        from tests.support.dataset import scene_observation
        spec = SceneSpec(1, 'general', 'Two adults pose.',
            (Participant('P1', 'Ada', '', '', '', '', traits='woman aged 47, silver hair'),
             Participant('P2', 'Ben', '', '', '', '', traits='man aged 52, red beard')), locked=('hard',))
        for text in ('Ada, a 42-year-old woman, poses. Ben is 52 years old.',
                     'Ada is 47 years old. Ben, a man aged 57, stands nearby.'):
            with self.subTest(text=text):
                proof = scene_observation(spec, text, essential=True)
                self.assertTrue(scene_spec_findings(text, spec, proof, essential=True)['hard'])
                self.assertTrue(scene_spec_findings(text, spec, None, essential=True)['hard'])
        for text in ('Ada, a 47-year-old woman, poses. Ben is 52 years old.',
                     'Ada holds a 42-year-old violin. Ben stands nearby.',
                     'Ada and Ben stand beside a plaque marked 42.',
                     'Adaline is 42 years old. Ada poses. Ben stands nearby.'):
            with self.subTest(text=text):
                proof = scene_observation(spec, text, essential=True)
                self.assertEqual(scene_spec_findings(text, spec, proof, essential=True)['hard'], [])
        for traits in ('woman about 47 years old', 'woman between 40 and 50 years old',
                       'woman aged 40-50', 'woman in her 40s'):
            relaxed = replace(spec, participants=(replace(spec.participants[0], traits=traits), spec.participants[1]))
            text = 'Ada is 42 years old. Ben stands nearby.'
            with self.subTest(traits=traits):
                proof = scene_observation(relaxed, text, essential=True)
                self.assertEqual(scene_spec_findings(text, relaxed, proof, essential=True)['hard'], [])

    def test_named_age_conflict_uses_the_existing_bounded_writer_repair(self):
        from unittest.mock import Mock
        from tests.support.dataset import checked_writer_responses
        spec = SceneSpec(1, 'general', 'Ada poses.',
            (Participant('P1', 'Ada', '', '', '', '', traits='woman aged 47, silver hair'),), locked=('hard',))
        row = saved_scene(scene='Ada poses.', scene_spec=spec.to_dict(), scene_status='unverified', self_check='')
        data = valid_draft(trigger='Ada', target='Krea 2')
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data['subject']), data, 1, plan_item=row)
        wrong = 'Ada, a 42-year-old woman with silver hair, poses.'
        right = 'Ada, a 47-year-old woman with silver hair, poses.'
        session = Mock()
        checked_writer_responses(session, [wrong, right], [row])
        result = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)
        self.assertEqual(result, right)
        self.assertEqual(row['prompt_status'], 'valid')
        writes = [call.args[0] for call in session.generate.call_args_list
                  if call.args[0].diagnostic_stage.startswith('dataset:1')]
        self.assertEqual(len(writes), 2)
        self.assertIn('supplied age 47', writes[1].system_message)
        checked_writer_responses(session, [wrong, wrong], [row])
        with self.assertRaises(BackendGenerationError):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, row)

    def test_checker_unavailability_does_not_hide_a_new_named_age_contradiction(self):
        from unittest.mock import Mock
        spec = SceneSpec(1, 'general', 'Ada poses.',
            (Participant('P1', 'Ada', '', '', '', '', traits='woman aged 47, silver hair'),), locked=('hard',))
        session = Mock()
        session.generate.side_effect = BackendGenerationError('Synthetic unavailable checker')
        for text, expected in (('Ada, a 42-year-old woman, poses.', 'failed'),
                               ('Ada, a 47-year-old woman, poses.', 'unverified')):
            with self.subTest(text=text):
                row = saved_scene(scene=text, scene_spec=spec.to_dict(), scene_status='unverified', self_check='')
                checked = verify_scenes(session, [row], lambda: None)[0]
                self.assertEqual(checked['scene_status'], expected)
                if expected == 'failed':
                    self.assertIn('supplied age 47', checked['failure_reason'])

    def test_writer_does_not_invent_elevation_from_a_shot_size_alone(self):
        data = valid_draft()
        row = saved_scene(scene="A full-body shot of an adult greeting a friend.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data['subject']), data, 1, plan_item=row)
        self.assertIn("A full-body or wide shot does not specify camera elevation", instruction.system_message)
        self.assertIn("omit high-angle and low-angle labels", instruction.system_message)
        self.assertIsNotNone(geometry_error("A low-angle full-body shot of an adult.", row['scene']))
        self.assertIsNone(geometry_error("A full-body shot of an adult.", row['scene']))
        lighting = ('Sun streams in from a high-angle source. The camera is at eye level.',
                    'The room has a low-angle source. The camera is at eye level.')
        for text in lighting:
            with self.subTest(text=text):
                self.assertIsNone(geometry_error(text, row['scene']))

    def test_camera_cannot_claim_full_body_and_an_upper_body_crop(self):
        for text in ('A full-body shot. The camera captures her from the waist up.',
                     'A full-body view with a waist-up shot.'):
            self.assertIsNotNone(geometry_error(text))
        for text in ('A full-body shot. She holds a waist-up portrait.',
                     'A full-body shot in which she holds a waist-up portrait.',
                     'The camera captures her from the waist up.', 'A full-body shot at eye level.'):
            self.assertIsNone(geometry_error(text))

    def test_unavailable_recheck_does_not_clear_a_known_violation_in_unchanged_text(self):
        from unittest.mock import Mock
        from tests.support.dataset import scene_observation
        spec = replace(self.paired_spec(), hard=("No additional people.",))
        scene = "Alice greets Bob and an additional guest."
        observation = scene_observation(spec, scene, essential=True)
        next(check for check in observation["requirements"] if check["id"] == "hard:0")["status"] = "fail"
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        failed = verify_scenes(session, [saved_scene(scene=scene, scene_spec=spec.to_dict())], lambda: None)[0]
        self.assertEqual(failed["scene_status"], "failed")
        session.generate.side_effect = BackendGenerationError("Synthetic checker unavailable")
        unavailable = verify_scenes(session, [failed], lambda: None)[0]
        self.assertEqual(unavailable["scene_status"], "failed")
        self.assertFalse(scene_eligibility(unavailable, {}).usable)

    def test_optional_generated_mechanics_and_semantic_setting_wording_are_not_constraints(self):
        from goated_prompter.features.dataset.validation import scene_spec_findings
        from tests.support.dataset import scene_observation
        spec = replace(self.paired_spec(), locked=("hard",), setting="old astronomical observatory")
        scene = "Alice and Bob work in the historic observatory."
        observation = scene_observation(spec, scene, essential=True)
        observation["participants"][0].update(pose="standing", location="foreground", support="unknown")
        observation["setting"] = "historic observatory interior"
        observation["contacts"] = []
        self.assertEqual(scene_spec_findings(scene, spec, observation, essential=True),
                         {"hard": [], "repairable": [], "warnings": []})
        observation["requirements"][0]["evidence"] = "A paraphrase, not an exact quotation."
        findings = scene_spec_findings(scene, spec, observation, essential=True)
        self.assertEqual(findings["hard"], [])
        self.assertEqual(findings["repairable"], [])
        self.assertTrue(findings["warnings"])

    def test_partial_malformed_observation_cannot_hide_known_identity_route_or_exclusion_failure(self):
        from goated_prompter.features.dataset.validation import scene_spec_findings
        from tests.support.dataset import scene_observation
        spec = replace(self.paired_spec(), hard=("Exclude hats.",))
        for check_id in ("cast", "subject:A", "route", "hard:0"):
            with self.subTest(check_id=check_id):
                scene = "Alice greets Bob."
                observation = scene_observation(spec, scene, essential=True)
                next(check for check in observation["requirements"] if check["id"] == check_id)["status"] = "fail"
                observation.pop("action_evidence")
                findings = scene_spec_findings(scene, spec, observation, essential=True)
                self.assertTrue(findings["hard"])
                self.assertTrue(findings["warnings"])

    def test_approved_contact_lock_does_not_promote_added_creative_contacts_to_requirements(self):
        from goated_prompter.features.dataset.validation import scene_spec_findings, specification_checks
        from tests.support.dataset import scene_observation
        required = self.paired_spec().contacts[0]
        optional = Contact("B.left_hand", "A.shoulder")
        spec = replace(self.paired_spec(), contacts=(required, optional),
                       locked=("hard", f"contact:{required.source}->{required.target}"))
        scene = "Alice's left hand rests on Bob's shoulder as they greet each other."
        observation = scene_observation(spec, scene, essential=True)
        observation["contacts"] = observation["contacts"][:1]
        self.assertEqual(spec.required_contacts, (required,))
        self.assertEqual(scene_spec_findings(scene, spec, observation, essential=True)["hard"], [])
        self.assertEqual(scene_spec_findings(scene, spec, observation, essential=True)["repairable"], [])
        checks = [check["id"] for check in specification_checks(spec, essential=True)]
        self.assertNotIn(f"contact:{optional.source}->{optional.target}", checks)
        next(check for check in observation["requirements"] if check["id"].startswith("contact:"))["status"] = "fail"
        self.assertTrue(scene_spec_findings(scene, spec, observation, essential=True)["hard"])

    def test_essential_findings_distinguish_user_violations_repairs_and_uncertainty(self):
        from goated_prompter.features.dataset.validation import scene_spec_findings
        from tests.support.dataset import scene_observation
        spec = replace(self.paired_spec(), locked=("hard",), hard=("Both adults remain visible.",))
        scene = "Alice sits on the left and greets Bob in the studio. Both adults remain visible."
        observed = scene_observation(spec, scene)
        observed["setting"] = "the same studio interior"
        observed["participants"][0]["support"] = "unknown"
        observed["requirements"][-1]["evidence"] = "A paraphrase of the source."
        findings = scene_spec_findings(scene, spec, observed)
        self.assertEqual(findings["hard"], [])
        self.assertTrue(findings["warnings"])
        observed["participants"][0]["pose"] = "standing"
        self.assertTrue(scene_spec_findings(scene, spec, observed)["repairable"])
        observed["requirements"][-1]["status"] = "fail"
        self.assertTrue(scene_spec_findings(scene, spec, observed)["hard"])
        observed["requirements"][-1]["status"] = "pass"
        observed["participants"].pop()
        self.assertTrue(scene_spec_findings(scene, spec, observed)["hard"])

    def test_unknown_validation_is_unverified_not_a_hard_failure_or_a_pass(self):
        from unittest.mock import Mock
        from tests.support.dataset import scene_observation
        spec = self.paired_spec()
        scene = "Alice greets Bob in the studio."
        observation = scene_observation(spec, scene)
        observation["requirements"][0]["status"] = "unknown"
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        row = verify_scenes(session, [saved_scene(scene=scene, scene_spec=spec.to_dict())], lambda: None)[0]
        self.assertEqual(row["scene_status"], "unverified")
        self.assertNotEqual(row["self_check"], "PASS")
        self.assertTrue(row["quality_warnings"])
        self.assertTrue(scene_eligibility(row, {}).usable)

    def test_validation_budget_accounts_for_cast_contacts_and_required_evidence(self):
        sparse = self.paired_spec()
        complex_spec = replace(sparse, hard=tuple(f"Preserve distinct supplied fact {index}." for index in range(20)))
        scene = "Alice greets Bob while both retain their supplied attributes."
        simple = validation_instruction([saved_scene(scene=scene, scene_spec=sparse.to_dict())])
        complex_instruction = validation_instruction([saved_scene(scene=scene, scene_spec=complex_spec.to_dict())])
        self.assertGreater(complex_instruction.max_tokens, simple.max_tokens)
        self.assertEqual(complex_instruction.hard_max_tokens, complex_instruction.max_tokens)
        self.assertLessEqual(complex_instruction.max_tokens, 16384)
        checks = json.loads(complex_instruction.user_message)[0]["checks"]
        self.assertEqual(len(checks), 25)  # Action, two subjects, two locked supports and twenty hard facts.

    def test_scene_repair_compares_canonical_specs_not_serialized_whitespace(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.ideas import DatasetIdeasService
        spec = replace(self.paired_spec(), index=1, hard=("Both adults remain visible.",))
        raw = spec.to_dict()
        raw["hard"] = ["Both adults\n remain visible."]
        row = saved_scene(idea="Alice greets Bob.", scene="Alice greets Bob in the studio.",
            scene_spec=raw, failure_stage="scene", failure_reason="Scene validation unavailable.",
            scene_status="repair_required")
        session = Mock()
        session.generate.return_value = json.dumps([{key: row[key] for key in ("index", "idea", "scene")}])
        repaired = DatasetIdeasService(lambda: None).run(session=session, data=valid_draft(amount=1),
            assignments=dataset_assignments(valid_draft(amount=1)), progress=lambda _: None,
            existing=[row], allow_partial=True, scene_specs={1: spec})
        self.assertNotEqual(repaired[0].get("idea_status"), "failed", repaired[0].get("failure_reason"))
        self.assertEqual(repaired[0]["scene"], row["scene"])
        self.assertEqual(SceneSpec.from_dict(repaired[0]["scene_spec"]).signature, spec.signature)
        changed = DatasetIdeasService(lambda: None).run(session=session, data=valid_draft(amount=1),
            assignments=dataset_assignments(valid_draft(amount=1)), progress=lambda _: None,
            existing=[row], allow_partial=True, scene_specs={1: replace(spec, setting="another studio")})
        self.assertEqual(changed[0]["idea_status"], "failed")

    def test_frozen_setting_uses_canonical_label_without_accepting_unknown_or_conflict(self):
        from tests.support.dataset import scene_observation
        for setting in ("mossy fantasy forest", "old astronomical observatory"):
            with self.subTest(setting=setting):
                spec = replace(self.paired_spec(), setting=setting)
                scene = f"Alice greets Bob inside the {setting}."
                row = saved_scene(scene=scene, scene_spec=spec.to_dict())
                fields = inline_refs(validation_instruction([row]).json_schema)["prefixItems"][0]["properties"]
                self.assertEqual(set(fields["setting"]["enum"]), {setting, "unknown", "conflict"})
                for value in ("unknown", "conflict"):
                    observation = scene_observation(spec, scene)
                    observation["setting"] = value
                    self.assertIn("The described environment differs from the selected setting.",
                                  scene_spec_errors(scene, spec, observation))
                observation = scene_observation(spec, scene)
                observation["setting_evidence"] = "Invented quotation."
                self.assertIn("The planned setting has no grounded evidence.", scene_spec_errors(scene, spec, observation))

    def test_only_explicit_scene_edits_can_extract_an_unlocked_setting(self):
        spec = replace(self.paired_spec(), setting="observatory")
        row = saved_scene(scene="Alice greets Bob on a beach.", scene_spec=spec.to_dict(), edited_stage="scene")
        for kind, locked, normalized in (("scene", spec.locked, False),
                                         ("prompt", spec.locked, True),
                                         ("scene", (*spec.locked, "setting"), True)):
            with self.subTest(kind=kind, locked=locked):
                row["scene_spec"] = replace(spec, locked=locked).to_dict()
                instruction = validation_instruction([row], kind=kind)
                field = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]["setting"]
                self.assertEqual("enum" in field, normalized)
                self.assertEqual(json.loads(instruction.user_message)[0]["setting_to_identify"],
                                 "observatory" if normalized else "")

    def test_validation_evidence_is_constrained_to_description_quotes_and_owned_contact_labels(self):
        spec = self.paired_spec()
        scene = "Alice sits on a chair on the left and greets Bob. Bob stands on the right with feet on the floor. Alice's left hand rests on Bob's shoulder."
        instruction = validation_instruction([saved_scene(scene=scene, scene_spec=spec.to_dict())])
        fields = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]
        evidence = fields["participants"]["prefixItems"][0]["properties"]["evidence"]
        self.assertIn("enum", evidence)
        self.assertTrue(all(not quote or quote in scene for quote in evidence["enum"]))
        self.assertIn("Alice sits on a chair on the left and greets Bob.", evidence["enum"])
        for field in ("setting_evidence", "action_evidence"):
            self.assertEqual(fields[field], evidence)
        contact = fields["contacts"]["items"]["properties"]
        self.assertIn("A.left_hand", contact["source"]["enum"])
        self.assertIn("B.shoulder", contact["target"]["enum"])
        self.assertEqual(contact["evidence"], evidence)

    def test_each_quote_list_is_defined_once_and_final_prompts_get_no_open_critique(self):
        scene = " ".join(f"Sentence {index} describes the room in detail." for index in range(12))
        for kind, critique in (("scene", 24), ("prompt", 0)):
            with self.subTest(kind=kind):
                instruction = validation_instruction([saved_scene(scene=scene)], kind=kind, essential=True)
                encoded = json.dumps(instruction.json_schema, ensure_ascii=False)
                quote = json.loads(instruction.user_message)[0]["evidence_quotes"][0]
                # Once with the empty "unknown" choice, once as a claimed quote.
                self.assertEqual(encoded.count(json.dumps(quote, ensure_ascii=False)), 2)
                conflicts = instruction.json_schema["prefixItems"][0]["properties"]["conflicts"]
                self.assertEqual(conflicts["maxItems"], critique)

    def test_long_validation_quotes_are_bounded_exact_overlapping_excerpts(self):
        scene = " ".join(f"word{index}" for index in range(250)) + "."
        instruction = validation_instruction([saved_scene(scene=scene)])
        quotes = json.loads(instruction.user_message)[0]["evidence_quotes"]
        self.assertTrue(all(quote in scene and len(quote) <= 240 for quote in quotes))
        self.assertTrue(all(any(f"word{index}" in quote.split() for quote in quotes) for index in range(249)))

    def test_claimed_requirement_pass_or_fail_requires_nonempty_exact_evidence(self):
        scene = "Alice greets Bob. Both adults wear coats."
        for essential in (False, True):
            instruction = validation_instruction([saved_scene(scene=scene)], essential=essential)
            checks = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]["requirements"]["prefixItems"]
            for check in checks:
                claimed, uncertain = check["anyOf"]
                self.assertEqual(claimed["properties"]["status"]["enum"], ["pass", "fail"])
                quotes = claimed["properties"]["evidence"]["enum"]
                self.assertTrue(quotes)
                self.assertTrue(all(quote and quote in scene for quote in quotes))
                self.assertEqual(uncertain["properties"]["status"]["enum"], ["unknown"])
                self.assertIn("", uncertain["properties"]["evidence"]["enum"])
        empty = validation_instruction([saved_scene(scene="")], essential=True)
        checks = inline_refs(empty.json_schema)["prefixItems"][0]["properties"]["requirements"]["prefixItems"]
        self.assertTrue(all(len(check["anyOf"]) == 1 for check in checks))
        self.assertTrue(all(check["anyOf"][0]["properties"]["status"]["enum"] == ["unknown"] for check in checks))

    def test_essential_prompt_evidence_uses_exact_quotes_without_locking_open_mechanics(self):
        spec = replace(self.paired_spec(), locked=("hard",))
        scene = "Alice sits beside Bob. Alice's left hand rests on Bob's shoulder."
        instruction = validation_instruction([saved_scene(scene=scene, scene_spec=spec.to_dict())],
                                             kind="prompt", essential=True)
        fields = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]
        evidence = fields["participants"]["prefixItems"][0]["properties"]["evidence"]
        self.assertIn("enum", evidence)
        self.assertIn("", evidence["enum"])
        self.assertTrue(all(not quote or quote in scene for quote in evidence["enum"]))
        for field in ("setting_evidence", "action_evidence"):
            self.assertEqual(fields[field], evidence)
        for check in fields["requirements"]["prefixItems"]:
            claimed, uncertain = check["anyOf"]
            self.assertEqual(claimed["properties"]["evidence"]["enum"], evidence["enum"][1:])
            self.assertEqual(uncertain["properties"]["evidence"], evidence)
            self.assertEqual(claimed["properties"]["status"]["enum"], ["pass", "fail"])
            self.assertEqual(uncertain["properties"]["status"]["enum"], ["unknown"])
        self.assertEqual(fields["contacts"]["items"]["properties"]["evidence"], evidence)
        participant = fields["participants"]["prefixItems"][0]["properties"]
        self.assertNotIn("enum", participant["pose"])

    def test_forest_observation_with_place_names_missing_checks_and_invented_quotes_stays_blocked(self):
        from unittest.mock import Mock
        spec = SceneSpec(3, "general", "The explorer explores a mossy forest", (
            Participant("P1", "the explorer", "explorer", "standing_observing", "center", "ground"),
            Participant("P2", "the forest", "environment", "", "background", "", kind="environment", sex="none")),
            setting="mossy forest", hard=("The explorer is the central subject.",), concept="exploring a forest")
        scene = "The explorer stands still in a mossy forest and observes the trees."
        observation = {"index": 3, "participants": [
            {"id": "P1", "role": "explorer", "pose": "standing", "location": "mossy forest", "support": "unknown",
             "evidence": "The explorer stands still in a mossy forest"},
            {"id": "P2", "role": "environment", "pose": "", "location": "mossy forest", "support": "",
             "evidence": "a mossy forest"}], "contacts": [], "requirements": [
                 {"id": "subject:P1", "status": "pass", "evidence": "The explorer"},
                 {"id": "subject:P2", "status": "pass", "evidence": "a mossy forest"},
                 {"id": "hard:0", "status": "pass", "evidence": "The explorer is the central subject."}],
            "setting": "mossy forest", "setting_evidence": "a mossy forest", "action": "observes the trees",
            "action_evidence": "observes the trees", "category": "general", "conflicts": []}
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        row = saved_scene(3, scene=scene, scene_spec=spec.to_dict())
        checked = verify_scenes(session, [row], lambda: None)[0]
        self.assertFalse(scene_eligibility(checked, {}).usable)
        self.assertEqual(checked["scene"], scene)
        for reason in ("described pose differs", "described location differs"):
            self.assertIn(reason, checked["failure_reason"])
        self.assertTrue(checked["quality_warnings"])

    def test_compound_forest_labels_require_grounded_qualifiers_and_complete_checks(self):
        from tests.support.dataset import scene_observation
        spec = SceneSpec(3, "general", "The explorer observes the forest", (
            Participant("P1", "the explorer", "explorer", "standing_observing", "center", "ground"),
            Participant("P2", "the forest", "environment", "", "background", "", kind="environment", sex="none")),
            setting="mossy forest", hard=("The explorer is the central subject.",), concept="exploring a forest")
        scene = ("The explorer is the central subject, standing in the center with boots planted on mossy ground, "
                 "observing the mossy forest in the background.")
        observation = scene_observation(spec, scene)
        self.assertEqual(scene_spec_errors(scene, spec, observation), [])
        for field in ("pose", "location", "support"):
            for value in ("unknown", "conflict"):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(observation)
                    changed["participants"][0][field] = value
                    self.assertTrue(scene_spec_errors(scene, spec, changed))
        for check in ("action", "concept"):
            changed = deepcopy(observation)
            changed["requirements"] = [item for item in changed["requirements"] if item["id"] != check]
            self.assertIn("Not every approved requirement was checked exactly once.", scene_spec_errors(scene, spec, changed))

    def test_validation_wire_uses_the_frozen_labels_and_layout_not_generic_pose_names(self):
        spec = SceneSpec(1, "general", "The explorer observes a mossy forest", (
            Participant("P1", "the explorer", "explorer", "standing_observing", "center", "ground"),
            Participant("P2", "the forest", "environment", "", "background", "", kind="environment", sex="none")),
            setting="mossy forest", hard=("The explorer is the central subject.",), concept="exploring a forest")
        row = saved_scene(scene="The explorer stands at the center, boots on mossy ground, observing the forest behind her.",
                          scene_spec=spec.to_dict())
        instruction = validation_instruction([row])
        context = json.loads(instruction.user_message)[0]
        self.assertEqual(context["cast"][0]["normalization_labels"],
            {"role": "explorer", "pose": "standing_observing", "location": "center", "support": "ground"})
        schema = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]
        participant = schema["participants"]["prefixItems"][0]["properties"]
        for field, label in context["cast"][0]["normalization_labels"].items():
            self.assertEqual(set(participant[field]["enum"]), {label, "unknown", "conflict"})
        environment = schema["participants"]["prefixItems"][1]["properties"]
        self.assertEqual(environment["pose"].get("const"), "")
        self.assertEqual(environment["support"].get("const"), "")
        checks = schema["requirements"]
        self.assertEqual(checks["minItems"], len(context["checks"]))
        self.assertEqual(checks["maxItems"], len(context["checks"]))
        self.assertEqual([item["anyOf"][0]["properties"]["id"]["const"] for item in checks["prefixItems"]],
            ["action", "concept", "subject:P1", "subject:P2", "support:P1.body->setting.ground", "hard:0"])

    def test_editable_mechanics_are_extracted_instead_of_constrained_to_the_old_labels(self):
        spec = replace(self.paired_spec(), locked=("hard",))
        row = saved_scene(scene="Alice now stands in the foreground; Bob sits on a chair behind her.",
            scene_spec=spec.to_dict(), edited_stage="scene")
        instruction = validation_instruction([row])
        context = json.loads(instruction.user_message)[0]
        self.assertEqual(context["cast"][0]["normalization_labels"],
                         dict.fromkeys(("role", "pose", "location", "support"), ""))
        participant = inline_refs(instruction.json_schema)["prefixItems"][0]["properties"]["participants"]["prefixItems"][0]["properties"]
        self.assertNotIn("enum", participant["pose"])
        self.assertIn("foreground", participant["location"]["enum"])

    def paired_spec(self):
        return SceneSpec(1, "general", "Alice greets Bob", (
            Participant("A", "Alice", "participant", "seated", "left", "supported_by_chair"),
            Participant("B", "Bob", "participant", "standing", "right", "feet_on_floor")),
            (Contact("A.left_hand", "B.shoulder"),))

    def paired_observation(self, scene):
        return {"index": 1, "participants": [
            {"id": "A", "role": "participant", "pose": "seated", "location": "left", "support": "supported_by_chair", "evidence": scene.split(".")[0]},
            {"id": "B", "role": "participant", "pose": "standing", "location": "right", "support": "feet_on_floor", "evidence": scene.split(".")[1].strip()}],
            "contacts": [{"source": "A.left_hand", "target": "B.shoulder", "evidence": scene.split(".")[2].strip()}],
            "requirements": [{"id": key, "status": "pass", "evidence": scene.split(".")[0]}
                             for key in ("action", "subject:A", "subject:B", "support:A.body->setting.chair", "support:B.feet->setting.floor")],
            "setting": "unknown", "setting_evidence": "", "action": "Alice greets Bob",
            "action_evidence": scene.split(".")[0], "category": "general", "conflicts": []}

    def test_owned_pose_contact_and_support_pass_without_the_catalog_label(self):
        scene = ("Alice sits on a chair on the left and greets Bob. Bob stands on the right with feet on the floor. "
                 "Alice's left hand rests on Bob's shoulder.")
        self.assertEqual(scene_spec_errors(scene, self.paired_spec(), self.paired_observation(scene)), [])

    def test_swapped_owners_missing_support_and_negated_contact_fail(self):
        scene = "Alice sits on a chair on the left and greets Bob. Bob stands on the right with feet on the floor. Alice's left hand rests on Bob's shoulder."
        for field, value in (("pose", "standing"), ("support", "unknown"), ("location", "right")):
            observation = self.paired_observation(scene)
            observation["participants"][0][field] = value
            with self.subTest(field=field):
                self.assertTrue(scene_spec_errors(scene, self.paired_spec(), observation))
        observation = self.paired_observation(scene)
        observation["contacts"][0].update(source="B.left_hand", target="A.shoulder")
        self.assertTrue(scene_spec_errors(scene, self.paired_spec(), observation))
        observation = self.paired_observation(scene)
        observation["contacts"] = []
        self.assertTrue(scene_spec_errors(scene, self.paired_spec(), observation))

    def test_invalid_body_part_and_incompatible_support_are_rejected_before_generation(self):
        value = self.paired_spec().to_dict()
        value["participants"][0]["support"] = "feet_on_floor"
        with self.assertRaisesRegex(ValueError, "support"):
            SceneSpec.from_dict(value)
        value = self.paired_spec().to_dict()
        value["contacts"][0]["target"] = "unknown.shoulder"
        with self.assertRaisesRegex(ValueError, "owner"):
            SceneSpec.from_dict(value)

    def test_missing_invented_and_uncertain_evidence_cannot_authorize_a_scene(self):
        scene = "Alice sits on a chair on the left and greets Bob. Bob stands on the right with feet on the floor. Alice's left hand rests on Bob's shoulder."
        for status in ("fail", "unknown"):
            observation = self.paired_observation(scene)
            observation["requirements"][0]["status"] = status
            self.assertTrue(scene_spec_errors(scene, self.paired_spec(), observation))
        observation = self.paired_observation(scene)
        observation["participants"][0]["evidence"] = "This quote was not in the scene."
        self.assertTrue(scene_spec_errors(scene, self.paired_spec(), observation))

    def test_missing_optional_extraction_keeps_scene_or_prompt_unverified(self):
        from unittest.mock import Mock
        from tests.support.dataset import scene_observation
        spec = self.paired_spec()
        scene = "Alice sits on the left and greets Bob, standing on the right, with her left hand on his shoulder."
        for fields in (("action",), ("action_evidence",), ("category",), ("action", "action_evidence")):
            for kind in ("scene", "prompt"):
                with self.subTest(fields=fields, kind=kind):
                    observation = {**scene_observation(spec, scene), "action": "Alice greets Bob",
                                   "action_evidence": scene, "category": "general"}
                    for field in fields:
                        observation.pop(field)
                    session = Mock()
                    session.generate.return_value = json.dumps([observation])
                    row = saved_scene(scene=scene, scene_spec=spec.to_dict())
                    checked = verify_scenes(session, [row], lambda: None, kind=kind)[0]
                    self.assertTrue(scene_eligibility(checked, {}).usable)
                    self.assertEqual(checked["scene_status"], "unverified")
                    self.assertNotEqual(checked["self_check"], "PASS")

    def test_unknown_extracted_action_cannot_authorize_an_otherwise_grounded_scene(self):
        from tests.support.dataset import scene_observation
        spec = self.paired_spec()
        scene = "Alice greets Bob."
        for action in ("", " ", "unknown"):
            with self.subTest(action=action):
                observation = {**scene_observation(spec, scene), "action": action,
                               "action_evidence": scene, "category": "general"}
                self.assertTrue(scene_spec_errors(scene, spec, observation))

    def test_cached_validation_is_bound_to_both_scene_text_and_specification(self):
        scene = "Alice sits on a chair on the left and greets Bob. Bob stands on the right with feet on the floor. Alice's left hand rests on Bob's shoulder."
        spec = self.paired_spec()
        row = saved_scene(scene=scene, scene_spec=spec.to_dict(), scene_validation={
            "text_signature": text_signature(scene), "spec_signature": spec.signature,
            "observation": self.paired_observation(scene)})
        self.assertTrue(scene_eligibility(row, valid_draft()).usable)
        changed = deepcopy(row)
        changed["scene_spec"]["participants"][0]["location"] = "right"
        self.assertFalse(scene_eligibility(changed, valid_draft()).usable)
        self.assertFalse(scene_eligibility({**row, "scene": "Generic rewritten scene."}, valid_draft()).usable)
    def test_generic_scene_with_a_position_label_is_not_proof_of_the_arrangement(self):
        row = saved_scene(scene="Two adults smile in a room.", selected_position="supported paired pose", scene_spec=None)
        self.assertFalse(scene_eligibility(row, valid_draft()).usable)

    def test_composing_an_unverified_scene_does_not_stamp_pass(self):
        row = saved_scene(scene="Two adults smile in a room.", self_check="",
                          selected_position="supported paired pose", scene_spec=None)
        composed = ScenePlanner.compose([row])[0]
        self.assertNotEqual(composed["self_check"], "PASS")

    def test_structured_vocabulary_retains_owned_roles_and_contacts(self):
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({
            "id": "supported-pair-01", "category": "paired_pose", "participantCount": 2,
            "participants": {"A": {"pose": "seated", "location": "left"},
                             "B": {"pose": "standing", "location": "right"}},
            "contacts": [{"from": "A.left_hand", "to": "B.shoulder"}],
            "physicalConstraints": {"A": "supported_by_chair", "B": "feet_on_floor"}}))
        self.assertEqual(len(catalog.records), 1)
        record = catalog.records[0]
        self.assertEqual(record.participants[0].support, "supported_by_chair")
        self.assertEqual(record.contacts[0].target, "B.shoulder")

    def test_plain_entries_need_no_structure_but_unknown_sections_have_diagnostics(self):
        catalog = parse_vocabulary("[couple positions]\nambiguous paired pose\n[unknown]\nignored entry\n")
        self.assertFalse(catalog.records)
        self.assertEqual(catalog["couple positions"], ("ambiguous paired pose",))
        self.assertFalse(any(item["rule"] == "unresolved_structure" for item in catalog.diagnostics))
        self.assertTrue(any(item["rule"] == "unknown_section" for item in catalog.diagnostics))


def greeting_draft(amount=3):
    characters = [{"name": name, "count": 1, "sex": "unspecified", "kind": "human", "origin": "named",
                   "series": "", "traits": ""} for name in ("Alice", "Bob")]
    constraint = {"scope": "all_outputs", "action": "Alice greets Bob", "setting": "studio",
        "participants": [{"id": "P1", "role": None, "pose": "seated", "location": "left", "support": "supported_by_chair"},
                         {"id": "P2", "role": None, "pose": "standing", "location": "right", "support": "feet_on_floor"}],
        "contacts": [{"source": "P1.left_hand", "target": "P2.shoulder"}]}
    return valid_draft(amount=amount, subject="Alice greets Bob in a studio.", _confirmed_intent=dataset_understanding_fixture(
        requested_generation="Alice greets Bob", character_count=2, identity_policy="fixed", characters=characters,
        planning_constraints=[constraint]))


def greeting_scene(index, *, supported=True):
    return (f"Alice sits on a chair on the left and greets Bob in a studio at station {index}. "
            + ("Bob stands on the right with feet on the floor. " if supported else "Bob stands on the right. ")
            + "Alice's left hand rests on Bob's shoulder.")


def greeting_observation(index, scene, *, supported=True, spec=None):
    clauses = scene.split(".")
    return {"index": index, "participants": [
        {"id": "P1", "role": "participant", "pose": "seated", "location": "left", "support": "supported_by_chair", "evidence": clauses[0].strip()},
        {"id": "P2", "role": "participant", "pose": "standing", "location": "right", "support": "feet_on_floor" if supported else "unknown", "evidence": clauses[1].strip()}],
        "contacts": [{"source": "P1.left_hand", "target": "P2.shoulder", "evidence": clauses[2].strip()}],
        "requirements": [{"id": key, "status": "pass", "evidence": clauses[0].strip()}
                         for key in ("action", "concept", "subject:P1", "subject:P2")]
            + [{"id": f"support:{edge['source']}->{edge['target']}", "status": "pass" if supported or number == 0 else "unknown",
                "evidence": clauses[min(number, 1)].strip()} for number, edge in enumerate((spec or {}).get("supports", []))
                if "participants" in spec["locked"] or f"participant:{edge['source'].split('.')[0]}:support" in spec["locked"]],
        "setting": "studio", "setting_evidence": clauses[0].strip(), "action": "Alice greets Bob",
        "action_evidence": clauses[0].strip(), "category": "general", "conflicts": []}


class GreetingBackend:
    name = "synthetic-scenespec"

    def __init__(self, *, fail_slot=None):
        self.calls, self.specs, self.idea_counts = [], {}, {}
        self.fail_slot = fail_slot

    @contextmanager
    def generation_session(self):
        yield self

    def validate_instruction(self, _instruction):
        pass

    def emit_activity(self, *_args, **_kwargs):
        pass

    def generate(self, instruction):
        self.calls.append(instruction)
        context = json.loads(instruction.user_message) if instruction.json_output else None
        if instruction.diagnostic_stage == "dataset:ideas:brainstorm":
            self.specs = {item["index"]: item for item in context["scene_specs"]}
            return json.dumps([{"index": item["index"], "event": f"A greeting at station {item['index']}.", "typicality": .5}
                               for item in context["scene_specs"]])
        if instruction.diagnostic_stage == "dataset:planning":
            return json.dumps([{"index": item["index"], "action": item["action"], "setting": item["setting"],
                "participants": [{key: participant[key] or ("participant" if key == "role" else "")
                    for key in ("id", "role", "pose", "location", "support")} for participant in item["participants"]],
                "contacts": item["contacts"]} for item in context["assignments"]])
        if instruction.diagnostic_stage == "dataset:ideas":
            rows = []
            for item in context["assignments"]:
                index = item["index"]
                self.specs[index] = item["scene_spec"]
                self.idea_counts[index] = self.idea_counts.get(index, 0) + 1
                supported = index != self.fail_slot or self.idea_counts[index] > 1
                rows.append({"index": index, "idea": f"Alice greets Bob at station {index}.",
                              "scene": greeting_scene(index) if supported else ""})
            return json.dumps(rows)
        if instruction.diagnostic_stage.startswith("dataset:validation:"):
            observations = []
            for item in context:
                observation = greeting_observation(item["index"], item["description"],
                    supported="feet on the floor" in item["description"], spec=self.specs[item["index"]])
                observation["requirements"] = [{"id": check["id"],
                    "status": "fail" if check["id"].startswith("support:P2.") and "feet on the floor" not in item["description"] else "pass",
                    "evidence": item["description"]} for check in item["checks"]]
                observations.append(observation)
            return json.dumps(observations)
        index = int(instruction.diagnostic_stage.split(":")[1])
        return "ohwx_person " + greeting_scene(index)


class SceneSpecPipelineTests(unittest.TestCase):
    def test_planning_repair_receives_the_failed_slots_validation_reason(self):
        for failure in ("duplicate_contacts", "self_support"):
            with self.subTest(failure=failure):
                data, backend = greeting_draft(), GreetingBackend()
                generate = backend.generate
                planning_calls = []
                def respond(instruction):
                    raw = generate(instruction)
                    if instruction.diagnostic_stage == "dataset:planning":
                        planning_calls.append(json.loads(instruction.user_message))
                        if len(planning_calls) == 1:
                            candidates = json.loads(raw)
                            bad = next(row for row in candidates if row["index"] == 2)
                            if failure == "duplicate_contacts":
                                bad["contacts"] = [*bad["contacts"], bad["contacts"][0]]
                            else:
                                bad["supports"] = [{"source": "P1.body", "target": "P1.hand"}]
                            return json.dumps(candidates)
                    return raw
                backend.generate = respond
                with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
                    result = DatasetService({"backend": "mock"}, lambda: None).run(
                        GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None)
                self.assertEqual(result["completed"], 3)
                self.assertEqual(len(planning_calls), 2)
                self.assertEqual([row["index"] for row in planning_calls[1]["assignments"]], [2])
                corrections = planning_calls[1]["planning_corrections"]
                self.assertEqual(set(corrections), {"2"})
                self.assertEqual(corrections["2"], "Scene planning failed: " + (
                    "SceneSpec contacts must be distinct." if failure == "duplicate_contacts"
                    else "Owned support contradicts the participant support label."))

    def test_all_25_specs_are_provisional_before_brainstorm_and_frozen_before_five_idea_batches(self):
        data, backend, snapshots = greeting_draft(25), GreetingBackend(), []
        rows = ScenePlanner(lambda: None).plan_batch(session=backend, data=data, assignments=dataset_assignments(data),
            progress=lambda _: None, seed=7, plan_update=lambda value: snapshots.append(deepcopy(value)))
        self.assertEqual(len(snapshots[0]), 25)
        self.assertTrue(all(row["scene_spec"] and not row["scene"] for row in snapshots[0]))
        brainstorm = json.loads(backend.calls[0].user_message)
        self.assertEqual(len(brainstorm["scene_specs"]), 25)
        self.assertTrue(all(item["state"] == "provisional" for item in brainstorm["scene_specs"]))
        ideas = [json.loads(call.user_message) for call in backend.calls if call.diagnostic_stage == "dataset:ideas"]
        self.assertEqual([item["output_contract"]["record_count"] for item in ideas], [5] * 5)
        for item in ideas:
            for assignment in item["assignments"]:
                spec = assignment["scene_spec"]
                self.assertEqual(spec["state"], "frozen")
                self.assertEqual(spec["action"], brainstorm["scene_specs"][assignment["index"] - 1]["action"])
                self.assertEqual([item["pose"] for item in spec["participants"]], ["seated", "standing"])
        self.assertTrue(all(scene_eligibility(row, data).usable for row in rows))
        spec = SceneSpec.from_dict(rows[0]["scene_spec"])
        with self.assertRaises(FrozenInstanceError):
            spec.action = "A different action"

    def test_structural_failure_repairs_only_that_slot_after_passing_prompts(self):
        data, backend = greeting_draft(), GreetingBackend(fail_slot=2)
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 3)
        ideas = [json.loads(call.user_message) for call in backend.calls if call.diagnostic_stage == "dataset:ideas"]
        self.assertEqual([item["output_contract"]["indexes"] for item in ideas], [[1, 2, 3], [2]])
        self.assertEqual(ideas[0]["assignments"][1]["scene_spec"], ideas[1]["assignments"][0]["scene_spec"])
        writes = [call.diagnostic_stage for call in backend.calls if call.diagnostic_stage in {"dataset:1", "dataset:2", "dataset:3"}]
        self.assertEqual(writes, ["dataset:1", "dataset:3", "dataset:2"])

    def test_unknown_scene_validation_keeps_the_scene_eligible_but_unverified(self):
        from unittest.mock import Mock
        data = greeting_draft(1)
        spec = replace(plan_scene_specs(data, dataset_assignments(data), directions={})[1], state="frozen")
        row = saved_scene(scene=greeting_scene(1), scene_spec=spec.to_dict())
        session = Mock()
        observation = greeting_observation(1, row["scene"], spec=row["scene_spec"])
        observation["requirements"][0]["status"] = "unknown"
        session.generate.return_value = json.dumps([observation])
        checked = verify_scenes(session, [row], lambda: None)[0]
        self.assertEqual(checked["scene"], row["scene"])
        self.assertTrue(scene_eligibility(checked, data).usable)
        self.assertEqual(checked["scene_status"], "unverified")
        self.assertNotEqual(checked["self_check"], "PASS")

    def test_edit_to_an_open_pose_updates_the_spec_but_a_locked_pose_conflict_is_shown(self):
        from unittest.mock import Mock
        data = greeting_draft(1)
        spec = replace(plan_scene_specs(data, dataset_assignments(data), directions={})[1], state="frozen").to_dict()
        scene = greeting_scene(1).replace("Alice sits on a chair", "Alice kneels with knees on the floor")
        observation = greeting_observation(1, scene, spec=spec)
        observation["participants"][0].update(pose="kneeling", support="knees_on_floor")
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        row = saved_scene(scene=scene, scene_spec=spec, edited_stage="scene", self_check="")
        locked = verify_scenes(session, [row], lambda: None)[0]
        self.assertFalse(scene_eligibility(locked, data).usable)
        self.assertEqual(locked["scene_spec"]["participants"][0]["pose"], "seated")
        self.assertEqual(locked["scene"], scene)
        spec["locked"] = [value for value in spec["locked"] if not value.startswith("participant:P1:")]
        observation["requirements"] = [check for check in observation["requirements"] if check["id"] != "support:P1.body->setting.chair"]
        session.generate.return_value = json.dumps([observation])
        opened = verify_scenes(session, [{**row, "scene_spec": spec}], lambda: None)[0]
        self.assertTrue(scene_eligibility(opened, data).usable)
        self.assertEqual(opened["scene_spec"]["participants"][0]["pose"], "kneeling")
        self.assertEqual(opened["scene_spec"]["catalog_id"], "")

    def test_open_edits_reconcile_added_and_removed_interactions_with_fresh_category_evidence(self):
        from unittest.mock import Mock
        from tests.support.dataset import scene_observation
        cast = (Participant("P1", "Alice", "participant", "seated", "left", "supported_by_chair"),
                Participant("P2", "Bob", "participant", "seated", "right", "supported_by_chair"))
        contact = (Contact("P1.mouth", "P2.genitals"),)
        for old_category, new_category, contacts, action in (
                ("oral", "general", (), "The adults converse"),
                ("paired_pose", "oral", contact, "The adults share oral contact")):
            with self.subTest(old=old_category, new=new_category):
                old = SceneSpec(1, "adult", "An approved adult scene", cast,
                    contact if old_category == "oral" else (), hard=("Both adults remain visible.",),
                    locked=("hard",), category=old_category, private_vocabulary=True, catalog_id="synthetic-id",
                    concept="Adults in social or sexual scenes, with the interaction freely chosen per image")
                new = replace(old, action=action, category=new_category, contacts=contacts,
                              private_vocabulary=False, catalog_id="")
                scene = f"Alice sits on a chair on the left. Bob sits on a chair on the right. {action}, with both adults visible."
                observation = scene_observation(new, scene)
                session = Mock()
                def extract(instruction):
                    context = json.loads(instruction.user_message)[0]
                    return json.dumps([{**observation, "requirements": [
                        {"id": check["id"], "status": "pass", "evidence": scene} for check in context["checks"]]}])
                session.generate.side_effect = extract
                checked = verify_scenes(session, [saved_scene(scene=scene, scene_spec=old.to_dict(),
                    edited_stage="scene", self_check="")], lambda: None)[0]
                self.assertTrue(scene_eligibility(checked, {}).usable, checked.get("failure_reason"))
                self.assertEqual(checked["scene_spec"]["category"], new_category)
                self.assertEqual(checked["scene_spec"]["contacts"], new.to_dict()["contacts"])
                self.assertEqual(checked["scene_spec"]["action"], action)
                self.assertFalse(checked["scene_spec"]["private_vocabulary"])
                self.assertEqual(checked["scene_spec"]["catalog_id"], "")
                self.assertEqual(session.generate.call_count, 1)

    def test_an_open_interaction_does_not_add_a_new_mandatory_category_check(self):
        from unittest.mock import Mock
        from tests.support.dataset import scene_observation
        old = SceneSpec(1, "adult", "Adults converse", (Participant("P1", "adult", "", "", "", ""),),
                        locked=("hard",), category="solo")
        scene = "The adult describes a solo oral interaction."
        new = replace(old, action="A solo oral interaction", category="oral")
        observation = scene_observation(new, scene)
        observation["requirements"] = [check for check in observation["requirements"] if check["id"] != "category"]
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        checked = verify_scenes(session, [saved_scene(scene=scene, scene_spec=old.to_dict(),
            edited_stage="scene", self_check="")], lambda: None)[0]
        self.assertTrue(scene_eligibility(checked, {}).usable)
        self.assertEqual(checked["scene_status"], "unverified")
        self.assertNotIn("edited_stage", checked)
        self.assertEqual(session.generate.call_count, 1)
        self.assertNotIn("category", [check["id"] for check in checked["scene_validation"]["observation"]["requirements"]])

    def test_saved_edits_drop_stale_proof_and_metadata_without_rewriting_prose(self):
        data = greeting_draft(1)
        spec = plan_scene_specs(data, dataset_assignments(data), directions={})[1]
        row = saved_scene(scene=greeting_scene(1), scene_spec=spec.to_dict(), edited_stage="scene",
                          selected_position="old pose", selected_setting="old room")
        cleaned = validate_saved_scene_plan([row])[0]
        self.assertEqual(cleaned["scene"], row["scene"])
        self.assertNotIn("selected_position", cleaned)
        self.assertNotIn("selected_setting", cleaned)
        self.assertEqual(cleaned["scene_status"], "not_generated")

    def test_broad_records_stay_eligible_behind_entries_with_the_requested_act(self):
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({
            "id": "broad", "category": "paired_pose", "participantCount": 2,
            "participants": {"A": {"pose": "seated", "location": "left"}, "B": {"pose": "standing", "location": "right"}},
            "contacts": [], "physicalConstraints": {"A": "supported_by_chair", "B": "feet_on_floor"}}))
        route = ContentRoute("adult", 2, ("male", "male"), frozenset({"oral"}), frozenset(), "all_outputs", False, False,
                             required=frozenset({"oral"}))
        eligible, rejected = compatible_arrangements(catalog, route)
        # A requested act is required in the scene (enforced at freeze), not a filter on broad poses.
        self.assertEqual([record.id for record in eligible], ["broad"])
        self.assertEqual(vocabulary_diagnostics(catalog, route)["rejected"], 0)
        from goated_prompter.features.dataset.batch_planner import position_tiers
        import random
        named, extras, preferred, rest = position_tiers(eligible, route, random.Random(0))
        self.assertEqual((named, extras, preferred, [record.id for record in rest]), ([], [], [], ["broad"]))

    def test_director_does_not_reroute_a_general_request_or_replace_frozen_geometry(self):
        data = greeting_draft(1)
        with patch("goated_prompter.features.dataset.quality._director_text", return_value="oral sex, kneeling in a bedroom"):
            self.assertEqual(resolve_route(data).profile, "general")
            specs = plan_scene_specs(data, dataset_assignments(data), directions={})
        self.assertEqual(specs[1].participants[0].pose, "seated")
        self.assertEqual(specs[1].setting, "studio")

    def test_director_style_reaches_both_candidate_and_scene_writers_below_frozen_authority(self):
        from goated_prompter.features.dataset.brainstorm import brainstorm_instruction
        from goated_prompter.features.dataset.ideas import ideas_instruction
        data = greeting_draft(1)
        data["director_preset"] = "Mirror Selfie"
        provisional = plan_scene_specs(data, dataset_assignments(data), directions={})
        frozen = {index: replace(spec, state="frozen") for index, spec in provisional.items()}
        instructions = [brainstorm_instruction(data, 6, scene_specs=provisional),
            ideas_instruction(data, dataset_assignments(data), scene_specs=frozen)]
        for instruction in instructions:
            with self.subTest(stage=instruction.diagnostic_stage):
                self.assertIn("Mirror Selfie", instruction.system_message)
                self.assertIn("Approved hard requirements and SceneSpec take precedence", instruction.system_message)
                self.assertNotIn("DIRECTOR (MANDATORY)", instruction.system_message)
        self.assertEqual(frozen[1].participants[0].pose, "seated")
        self.assertEqual(frozen[1].setting, "studio")

    def test_fixed_shot_director_does_not_receive_an_unrelated_random_framing(self):
        from goated_prompter.features.dataset.ideas import creative_directions
        data = greeting_draft(2)
        data["director_preset"] = "Mirror Selfie"
        directions = creative_directions(data, [1, 2], vocabulary={})
        self.assertTrue(all("framing" not in row for row in directions.values()))
        self.assertTrue(all("light" in row for row in directions.values()))

    def test_optional_vocabulary_rules_do_not_leak_from_another_guided_assignment(self):
        from goated_prompter.features.dataset.brainstorm import brainstorm_instruction
        from goated_prompter.features.dataset.batch_planner import planning_instruction
        from goated_prompter.features.dataset.ideas import ideas_instruction
        from goated_prompter.features.dataset.prompting import dataset_instruction
        from tests.support.dataset import checked_scene, frozen_specs
        data = valid_draft(amount=2, subject="Two consenting adult men in sexual scenes.", source_mode="guided",
            inputs="Two adult men having anal sex, one owned by the other\nTwo adult men sharing oral contact",
            _confirmed_intent=dataset_understanding_fixture(character_count=2,
                requested_generation="Two consenting adult men in sexual scenes."))
        frozen = frozen_specs(data)
        provisional = replace(frozen[2], state="provisional")
        catalog = {"rules": ("SYNTHETIC_GENERAL_GUIDANCE",), "ownership rules": ("SYNTHETIC_OWNERSHIP_GUIDANCE",)}
        with patch("goated_prompter.features.dataset.private_vocabulary.load_vocabulary", return_value=catalog):
            instructions = [
                brainstorm_instruction(data, 6, scene_specs={2: provisional}),
                planning_instruction(data, [provisional]),
                ideas_instruction(data, dataset_assignments(data), indexes=[2], scene_specs=frozen),
                dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 2,
                    plan_item=checked_scene(saved_scene(2), spec=frozen[2])),
            ]
            for instruction in instructions:
                with self.subTest(stage=instruction.diagnostic_stage):
                    self.assertIn("SYNTHETIC_GENERAL_GUIDANCE", instruction.system_message)
                    self.assertNotIn("SYNTHETIC_OWNERSHIP_GUIDANCE", instruction.system_message)
            owned = ideas_instruction(data, dataset_assignments(data), indexes=[1], scene_specs=frozen)
            self.assertIn("SYNTHETIC_OWNERSHIP_GUIDANCE", owned.system_message)

    def test_mixed_guided_batch_limits_private_guidance_to_its_cycled_assignments(self):
        from goated_prompter.features.dataset.private_vocabulary import private_rules
        data = valid_draft(amount=4, subject="Two consenting adult men.", source_mode="guided",
            inputs="Two adult men having anal sex, one owned by the other\nTwo adult men cooking dinner")
        catalog = {"rules": ("SYNTHETIC_GENERAL_GUIDANCE",), "ownership rules": ("SYNTHETIC_OWNERSHIP_GUIDANCE",)}
        with patch("goated_prompter.features.dataset.private_vocabulary.load_vocabulary", return_value=catalog):
            guidance = private_rules(data)
        self.assertIn("SYNTHETIC_GENERAL_GUIDANCE (assignment indexes: 1, 3)", guidance)
        self.assertIn("SYNTHETIC_OWNERSHIP_GUIDANCE (assignment indexes: 1, 3)", guidance)
        self.assertNotIn("indexes: 1, 2, 3, 4", guidance)

    def test_private_vocabulary_run_marks_every_engine_instruction_without_redacting_model_inputs(self):
        from tests.support.dataset import CaptureBackend
        data = valid_draft(amount=1, subject="Two consenting adult men in sexual scenes.",
            _confirmed_intent=dataset_understanding_fixture(character_count=2,
                requested_generation="Two consenting adult men in sexual scenes."))
        catalog = parse_vocabulary("[rules]\nSYNTHETIC_PRIVATE_RULE_LINE")
        backend = CaptureBackend()
        with patch("goated_prompter.features.dataset.private_vocabulary.load_vocabulary", return_value=catalog), \
             patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 1)
        self.assertTrue(all((call.diagnostic_context or {}).get("private_content") is True for call in backend.calls))
        for stage in ("dataset:planning", "dataset:ideas", "dataset:1"):
            instruction = next(call for call in backend.calls if call.diagnostic_stage == stage)
            self.assertIn("SYNTHETIC_PRIVATE_RULE_LINE", instruction.system_message)

    def test_saved_private_spec_keeps_diagnostics_private_after_the_vocabulary_file_is_removed(self):
        from tests.support.dataset import CaptureBackend, checked_scene
        from goated_prompter.features.dataset.plan import scene_plan_signature
        from goated_prompter.features.dataset.private_vocabulary import Vocabulary
        spec = SceneSpec(1, "adult", "Adults greet", (Participant("P1", "adult", "", "", "", ""),),
                         locked=("hard",), private_vocabulary=True)
        data = valid_draft(amount=1, subject="An adult in sexual scenes.",
            scene_plan=[checked_scene(saved_scene(scene="The adult waves a greeting.", scene_spec=spec.to_dict()), spec=spec)])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        backend = CaptureBackend()
        backend.specs[1] = spec
        backend.scenes[1] = data["scene_plan"][0]["scene"]
        with patch("goated_prompter.features.dataset.private_vocabulary.load_vocabulary", return_value=Vocabulary()), \
             patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                lambda _: None, lambda _: None, scene_action=("regenerate_prompt", 1))
        self.assertEqual(result["completed"], 1)
        self.assertTrue(all((call.diagnostic_context or {}).get("private_content") is True for call in backend.calls))

    def test_partial_brainstorm_retains_indexed_seeds_without_changing_specs(self):
        import random
        from unittest.mock import Mock
        data = greeting_draft(2)
        specs = {index: replace(spec, state="frozen") for index, spec in plan_scene_specs(data, dataset_assignments(data), directions={}).items()}
        before = {index: value.to_dict() for index, value in specs.items()}
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 2, "event": "Alice greets Bob with a surprised expression.", "typicality": .5}])
        seeds = brainstorm_events(session, data, 2, random.Random(1), progress=lambda _: None,
                                  checkpoint=lambda: None, scene_specs=specs)
        self.assertEqual(set(seeds), {2})
        self.assertEqual({index: value.to_dict() for index, value in specs.items()}, before)

    def test_transport_failure_in_a_later_chunk_keeps_prior_work_and_all_specs(self):
        class InterruptedBackend(GreetingBackend):
            def generate(self, instruction):
                if instruction.diagnostic_stage == "dataset:ideas" and json.loads(instruction.user_message)["output_contract"]["indexes"] == [6, 7]:
                    raise BackendGenerationError("Synthetic transport failure")
                return super().generate(instruction)
        data, backend, snapshots = greeting_draft(7), InterruptedBackend(), []
        rows = ScenePlanner(lambda: None).plan_batch(session=backend, data=data, assignments=dataset_assignments(data),
            progress=lambda _: None, seed=5, plan_update=lambda value: snapshots.append(deepcopy(value)))
        self.assertTrue(all(scene_eligibility(row, data).usable for row in rows[:5]))
        self.assertTrue(all(row["failure_stage"] == "idea" and row["scene_spec"] for row in rows[5:]))
        self.assertTrue(any(all(row["scene"] for row in snapshot[:5]) and all(not row["scene"] for row in snapshot[5:])
                            for snapshot in snapshots))

    def test_final_prompt_fidelity_failure_retries_only_the_writer(self):
        class WrongPromptBackend(GreetingBackend):
            def __init__(self):
                super().__init__()
                self.writes = 0
            def generate(self, instruction):
                if instruction.diagnostic_stage.startswith("dataset:1"):
                    self.calls.append(instruction)
                    self.writes += 1
                    return "ohwx_person " + greeting_scene(1, supported=self.writes > 1)
                return super().generate(instruction)
        data, backend = greeting_draft(1), WrongPromptBackend()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(backend.writes, 2)
        self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in backend.calls), 1)
        self.assertEqual(sum(call.diagnostic_stage == "dataset:validation:scene" for call in backend.calls), 0)
        self.assertEqual(sum(call.diagnostic_stage == "dataset:validation:prompt" for call in backend.calls), 2)

    def test_pre_setting_split_plans_are_not_reused_as_current_plans(self):
        from goated_prompter.features.dataset.plan import scene_plan_signature, reusable_scene_plan
        data, backend = greeting_draft(1), GreetingBackend()
        assignments = dataset_assignments(data)
        data['scene_plan'] = ScenePlanner(lambda: None).plan_batch(session=backend, data=data,
            assignments=assignments, progress=lambda _: None, seed=5)
        with patch('goated_prompter.features.dataset.plan.SCENE_PLAN_VERSION', 16):
            data['scene_plan_signature'] = scene_plan_signature(data, assignments)
        self.assertIsNone(reusable_scene_plan(data, assignments))

    def test_check_edit_updates_only_the_selected_row_and_keeps_passing_siblings(self):
        from goated_prompter.features.dataset.plan import scene_plan_signature
        data, backend = greeting_draft(2), GreetingBackend()
        scenes = ScenePlanner(lambda: None).plan_batch(session=backend, data=data, assignments=dataset_assignments(data),
            progress=lambda _: None, seed=5)
        data.update(scene_plan=scenes, scene_plan_signature=scene_plan_signature(data, dataset_assignments(data)))
        data["scene_plan"][0].update(scene=greeting_scene(1).replace("greets", "warmly greets"),
                                     self_check="", scene_status="not_generated", edited_stage="scene")
        data["scene_plan"][0].pop("scene_validation")
        sibling = deepcopy(data["scene_plan"][1])
        backend.calls.clear()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                lambda _: None, lambda _: None, scene_action=("validate_scene", 1))
        self.assertEqual(result["scene_plan"][1], sibling)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:validation:scene"])
        self.assertNotIn("edited_stage", result["scene_plan"][0])
        self.assertTrue(scene_eligibility(validate_saved_scene_plan(result["scene_plan"])[0], data).usable)

    def test_malformed_edit_observation_is_unverified_without_crashing_siblings(self):
        from unittest.mock import Mock
        data = greeting_draft(2)
        specs = {index: replace(spec, state="frozen") for index, spec in plan_scene_specs(data, dataset_assignments(data), directions={}).items()}
        rows = [saved_scene(index, scene=greeting_scene(index), scene_spec=specs[index].to_dict(), edited_stage="scene")
                for index in (1, 2)]
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "participants": None}, greeting_observation(2, rows[1]["scene"], spec=rows[1]["scene_spec"])])
        result = verify_scenes(session, rows, lambda: None)
        self.assertTrue(scene_eligibility(result[0], data).usable)
        self.assertEqual(result[0]["scene_status"], "unverified")
        self.assertTrue(scene_eligibility(result[1], data).usable)

    def test_missing_validation_slot_preserves_grounded_siblings_and_persists_the_pending_slot(self):
        from unittest.mock import Mock
        data = greeting_draft(2)
        specs = {index: replace(spec, state="frozen") for index, spec in plan_scene_specs(data, dataset_assignments(data), directions={}).items()}
        rows = [saved_scene(index, scene=greeting_scene(index), scene_spec=specs[index].to_dict()) for index in (1, 2)]
        session = Mock()
        session.generate.return_value = json.dumps([greeting_observation(1, rows[0]["scene"], spec=rows[0]["scene_spec"])])
        result = verify_scenes(session, rows, lambda: None)
        self.assertTrue(scene_eligibility(result[0], data).usable)
        self.assertTrue(scene_eligibility(result[1], data).usable)
        self.assertEqual(result[1]["scene_status"], "unverified")
        self.assertNotIn("scene_validation", result[1])
        self.assertEqual(validate_saved_scene_plan(result)[1]["scene"], rows[1]["scene"])

    def test_compiled_record_is_selected_once_and_its_owners_are_bound_to_the_approved_cast(self):
        data = greeting_draft(2)
        data["subject"] = "Two adults in sexual scenes."
        data["_confirmed_intent"]["planning_constraints"] = []
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({
            "id": "supported-pair", "category": "paired_pose", "participantCount": 2,
            "participants": {"A": {"pose": "seated", "location": "left"}, "B": {"pose": "standing", "location": "right"}},
            "contacts": [{"from": "A.left_hand", "to": "B.shoulder"}],
            "physicalConstraints": {"A": "supported_by_chair", "B": "feet_on_floor"}}))
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, catalog=catalog, seed=8)
        self.assertTrue(specs[1].private_vocabulary)
        self.assertNotEqual(specs[1].catalog_id, "supported-pair")
        self.assertEqual([item.id for item in specs[1].participants], ["P1", "P2"])
        self.assertEqual([item.name for item in specs[1].participants], ["Alice", "Bob"])
        self.assertEqual(specs[1].contacts, (Contact("P1.left_hand", "P2.shoulder"),))
        from goated_prompter.features.dataset.ideas import ideas_instruction
        with patch("goated_prompter.features.dataset.ideas.load_vocabulary", side_effect=AssertionError("Must not reselect")):
            instruction = ideas_instruction(data, dataset_assignments(data), scene_specs={index: replace(spec, state="frozen") for index, spec in specs.items()})
        sent = json.loads(instruction.user_message)["assignments"][0]["scene_spec"]
        self.assertEqual(sent, replace(specs[1], state="frozen").to_dict())

    def test_plain_vocabulary_guides_planning_without_replacing_approved_mechanics(self):
        data = greeting_draft(1)
        data["subject"] = "Two adults in sexual scenes."
        catalog = parse_vocabulary("[couple positions]\nambiguous unsupported pose\n")
        diagnostics = vocabulary_diagnostics(catalog, resolve_route(data))
        self.assertEqual((diagnostics["loaded"], diagnostics["eligible"], diagnostics["rejected"]), (1, 1, 0))
        self.assertFalse(diagnostics["unresolved_constraints"])
        self.assertTrue(diagnostics["filtering_rules"])
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, catalog=catalog)
        self.assertEqual(specs[1].state, "provisional")
        self.assertTrue(specs[1].catalog_id)
        self.assertEqual(specs[1].participants[0].pose, "seated")
        self.assertIn("participant:P1:pose", specs[1].locked)

    def test_approved_mechanical_constraints_filter_a_conflicting_record_with_a_reason(self):
        data = greeting_draft(1)
        data["subject"] = "Two adults in sexual scenes."
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({
            "id": "swapped", "category": "paired_pose", "participantCount": 2,
            "participants": {"A": {"pose": "standing", "location": "right"}, "B": {"pose": "seated", "location": "left"}},
            "contacts": [], "physicalConstraints": {"A": "feet_on_floor", "B": "supported_by_chair"}}))
        constraints = data["_confirmed_intent"]["planning_constraints"]
        eligible, rejected = compatible_arrangements(catalog, resolve_route(data), constraints=constraints)
        self.assertEqual(eligible, [])
        self.assertEqual(rejected[0]["rule"], "approved_mechanics")

    def test_guided_mechanics_are_applied_only_to_their_cycled_assignments(self):
        data = greeting_draft(3)
        data.update(source_mode="guided", inputs="A greeting\nA wave")
        first = data["_confirmed_intent"]["planning_constraints"][0]
        first["scope"] = "guided:1"
        second = {"scope": "guided:2", "action": "Bob waves to Alice", "setting": "courtyard",
                  "participants": [], "contacts": []}
        data["_confirmed_intent"]["planning_constraints"].append(second)
        specs = plan_scene_specs(data, dataset_assignments(data), directions={})
        self.assertEqual([specs[index].action for index in (1, 2, 3)], ["Alice greets Bob", "Bob waves to Alice", "Alice greets Bob"])
        self.assertEqual([specs[index].setting for index in (1, 2, 3)], ["studio", "courtyard", "studio"])
        self.assertEqual(specs[1].contacts, specs[3].contacts)
        self.assertEqual(specs[2].contacts, ())

    def test_supplied_mechanics_survive_understanding_and_approval_without_scene_invention(self):
        data = greeting_draft(1)
        brief = data["_confirmed_intent"]
        validated = validate_understanding(brief, ("all_outputs", "dataset"))
        self.assertEqual(validated["planning_constraints"], brief["planning_constraints"])
        compact = {"requested_generation": brief["requested_generation"], "expansion_freedom": "Open lighting.",
                   "character_count": 2, "identity_policy": "fixed", "requirements": {"hard": [], "soft": [], "free": [], "context": []},
                   "physical_conflicts": [], "clarifications": [], "characters": brief["characters"],
                   "planning_constraints": brief["planning_constraints"]}
        self.assertEqual(_expand_understanding(compact, data, ("all_outputs", "dataset"))["planning_constraints"], brief["planning_constraints"])
        invalid = deepcopy(brief)
        invalid["planning_constraints"][0]["participants"][0]["support"] = "feet_on_floor"
        with self.assertRaisesRegex(ValueError, "support"):
            validate_understanding(invalid, ("all_outputs", "dataset"))

    def test_failed_recheck_drops_prior_proof_instead_of_reusing_it_as_pass(self):
        from unittest.mock import Mock
        data = greeting_draft(1)
        backend = GreetingBackend()
        row = ScenePlanner(lambda: None).plan_batch(session=backend, data=data, assignments=dataset_assignments(data),
            progress=lambda _: None, seed=5)[0]
        self.assertTrue(scene_eligibility(row, data).usable)
        session = Mock()
        session.generate.side_effect = BackendGenerationError("Synthetic checker unavailable")
        checked = verify_scenes(session, [row], lambda: None)[0]
        self.assertNotIn("scene_validation", checked)
        self.assertEqual(checked["scene"], row["scene"])
        self.assertTrue(scene_eligibility(checked, data).usable)
        self.assertEqual(checked["scene_status"], "unverified")
        self.assertNotEqual(checked["self_check"], "PASS")

    def test_routing_preview_scopes_guided_diagnostics_without_additional_model_calls(self):
        data = greeting_draft(2)
        self.assertEqual(dataset_routing(data)[0]["scope"], "all_outputs")
        data.update(source_mode="guided", inputs="An adult oral scene\nA greeting")
        catalog = parse_vocabulary("[couple positions]\nambiguous paired pose\n")
        with patch("goated_prompter.features.dataset.brainstorm.load_vocabulary", return_value=catalog):
            routes = dataset_routing(data)
        self.assertEqual([item["scope"] for item in routes], ["guided:1", "guided:2"])
        self.assertEqual([item["nsfw"] for item in routes], [True, False])
        self.assertEqual(routes[0]["vocabulary"]["eligible"], 1)
        self.assertEqual(routes[0]["vocabulary"]["rejected"], 0)
        self.assertEqual(routes[1]["private_position_count"], 0)


if __name__ == "__main__":
    unittest.main()
