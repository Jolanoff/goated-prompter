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


class SceneSpecGateTests(unittest.TestCase):
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
        for reason in ("described pose differs", "described location differs", "described support differs",
                       "Not every approved requirement", "Requirement hard:0 is not evidenced"):
            self.assertIn(reason, checked["failure_reason"])

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
        schema = instruction.json_schema["prefixItems"][0]["properties"]
        participant = schema["participants"]["prefixItems"][0]["properties"]
        for field, label in context["cast"][0]["normalization_labels"].items():
            self.assertEqual(set(participant[field]["enum"]), {label, "unknown", "conflict"})
        environment = schema["participants"]["prefixItems"][1]["properties"]
        self.assertEqual(environment["pose"].get("const"), "")
        self.assertEqual(environment["support"].get("const"), "")
        checks = schema["requirements"]
        self.assertEqual(checks["minItems"], len(context["checks"]))
        self.assertEqual(checks["maxItems"], len(context["checks"]))
        self.assertEqual([item["properties"]["id"]["const"] for item in checks["prefixItems"]],
            ["action", "concept", "subject:P1", "subject:P2", "hard:0"])

    def test_editable_mechanics_are_extracted_instead_of_constrained_to_the_old_labels(self):
        spec = replace(self.paired_spec(), locked=("hard",))
        row = saved_scene(scene="Alice now stands in the foreground; Bob sits on a chair behind her.",
            scene_spec=spec.to_dict(), edited_stage="scene")
        instruction = validation_instruction([row])
        context = json.loads(instruction.user_message)[0]
        self.assertEqual(context["cast"][0]["normalization_labels"],
                         dict.fromkeys(("role", "pose", "location", "support"), ""))
        participant = instruction.json_schema["prefixItems"][0]["properties"]["participants"]["prefixItems"][0]["properties"]
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
                             for key in ("action", "subject:A", "subject:B")],
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

    def test_missing_extracted_action_or_category_cannot_authorize_scene_or_prompt(self):
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
                    self.assertFalse(scene_eligibility(checked, {}).usable)
                    self.assertEqual(checked["scene_status"], "repair_required")

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

    def test_unresolved_entries_and_unknown_sections_have_diagnostics(self):
        catalog = parse_vocabulary("[couple positions]\nambiguous paired pose\n[unknown]\nignored entry\n")
        self.assertFalse(catalog.records)
        self.assertTrue(any(item["rule"] == "unresolved_structure" for item in catalog.diagnostics))
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


def greeting_observation(index, scene, *, supported=True):
    clauses = scene.split(".")
    return {"index": index, "participants": [
        {"id": "P1", "role": "participant", "pose": "seated", "location": "left", "support": "supported_by_chair", "evidence": clauses[0].strip()},
        {"id": "P2", "role": "participant", "pose": "standing", "location": "right", "support": "feet_on_floor" if supported else "unknown", "evidence": clauses[1].strip()}],
        "contacts": [{"source": "P1.left_hand", "target": "P2.shoulder", "evidence": clauses[2].strip()}],
        "requirements": [{"id": key, "status": "pass", "evidence": clauses[0].strip()}
                         for key in ("action", "concept", "subject:P1", "subject:P2")],
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
                             "scene": greeting_scene(index, supported=supported)})
            return json.dumps(rows)
        if instruction.diagnostic_stage.startswith("dataset:validation:"):
            return json.dumps([greeting_observation(item["index"], item["description"],
                supported="feet on the floor" in item["description"]) for item in context])
        index = int(instruction.diagnostic_stage.split(":")[1])
        return "ohwx_person " + greeting_scene(index)


class SceneSpecPipelineTests(unittest.TestCase):
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

    def test_unknown_scene_validation_keeps_the_scene_but_blocks_builder(self):
        from unittest.mock import Mock
        data = greeting_draft(1)
        spec = replace(plan_scene_specs(data, dataset_assignments(data), directions={})[1], state="frozen")
        row = saved_scene(scene=greeting_scene(1), scene_spec=spec.to_dict())
        session = Mock()
        observation = greeting_observation(1, row["scene"])
        observation["requirements"][0]["status"] = "unknown"
        session.generate.return_value = json.dumps([observation])
        checked = verify_scenes(session, [row], lambda: None)[0]
        self.assertEqual(checked["scene"], row["scene"])
        self.assertFalse(scene_eligibility(checked, data).usable)
        self.assertEqual(checked["scene_status"], "repair_required")

    def test_edit_to_an_open_pose_updates_the_spec_but_a_locked_pose_conflict_is_shown(self):
        from unittest.mock import Mock
        data = greeting_draft(1)
        spec = replace(plan_scene_specs(data, dataset_assignments(data), directions={})[1], state="frozen").to_dict()
        scene = greeting_scene(1).replace("Alice sits on a chair", "Alice kneels with knees on the floor")
        observation = greeting_observation(1, scene)
        observation["participants"][0].update(pose="kneeling", support="knees_on_floor")
        session = Mock()
        session.generate.return_value = json.dumps([observation])
        row = saved_scene(scene=scene, scene_spec=spec, edited_stage="scene", self_check="")
        locked = verify_scenes(session, [row], lambda: None)[0]
        self.assertFalse(scene_eligibility(locked, data).usable)
        self.assertEqual(locked["scene_spec"]["participants"][0]["pose"], "seated")
        self.assertEqual(locked["scene"], scene)
        spec["locked"] = [value for value in spec["locked"] if not value.startswith("participant:P1:")]
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
                self.assertEqual(session.generate.call_count, 2)

    def test_an_added_interaction_remains_blocked_when_its_fresh_category_check_is_missing(self):
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
        self.assertFalse(scene_eligibility(checked, {}).usable)
        self.assertEqual(checked["scene_status"], "repair_required")
        self.assertEqual(checked["edited_stage"], "scene")
        self.assertEqual(session.generate.call_count, 2)
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

    def test_broad_records_cannot_satisfy_a_requested_act_category(self):
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({
            "id": "broad", "category": "paired_pose", "participantCount": 2,
            "participants": {"A": {"pose": "seated", "location": "left"}, "B": {"pose": "standing", "location": "right"}},
            "contacts": [], "physicalConstraints": {"A": "supported_by_chair", "B": "feet_on_floor"}}))
        route = ContentRoute("adult", 2, ("male", "male"), frozenset({"oral"}), frozenset(), "all_outputs", False, False)
        eligible, rejected = compatible_arrangements(catalog, route)
        self.assertEqual(eligible, [])
        self.assertEqual(rejected[0]["rule"], "requested_category")
        self.assertEqual(vocabulary_diagnostics(catalog, route)["rejected"], 1)

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
        self.assertIn("General guidance for assignment indexes: 1, 3.", guidance)
        self.assertIn("Ownership guidance for assignment indexes: 1, 3.", guidance)
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
        self.assertEqual(sum(call.diagnostic_stage == "dataset:validation:scene" for call in backend.calls), 1)
        self.assertEqual(sum(call.diagnostic_stage == "dataset:validation:prompt" for call in backend.calls), 2)

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

    def test_malformed_edit_observation_blocks_its_slot_without_crashing_siblings(self):
        from unittest.mock import Mock
        data = greeting_draft(2)
        specs = {index: replace(spec, state="frozen") for index, spec in plan_scene_specs(data, dataset_assignments(data), directions={}).items()}
        rows = [saved_scene(index, scene=greeting_scene(index), scene_spec=specs[index].to_dict(), edited_stage="scene")
                for index in (1, 2)]
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "participants": None}, greeting_observation(2, rows[1]["scene"])])
        result = verify_scenes(session, rows, lambda: None)
        self.assertFalse(scene_eligibility(result[0], data).usable)
        self.assertTrue(scene_eligibility(result[1], data).usable)

    def test_missing_validation_slot_preserves_grounded_siblings_and_persists_the_pending_slot(self):
        from unittest.mock import Mock
        data = greeting_draft(2)
        specs = {index: replace(spec, state="frozen") for index, spec in plan_scene_specs(data, dataset_assignments(data), directions={}).items()}
        rows = [saved_scene(index, scene=greeting_scene(index), scene_spec=specs[index].to_dict()) for index in (1, 2)]
        session = Mock()
        session.generate.return_value = json.dumps([greeting_observation(1, rows[0]["scene"])])
        result = verify_scenes(session, rows, lambda: None)
        self.assertTrue(scene_eligibility(result[0], data).usable)
        self.assertFalse(scene_eligibility(result[1], data).usable)
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

    def test_ambiguous_vocabulary_is_diagnosed_instead_of_used_for_planning(self):
        data = greeting_draft(1)
        data["subject"] = "Two adults in sexual scenes."
        catalog = parse_vocabulary("[couple positions]\nambiguous unsupported pose\n")
        diagnostics = vocabulary_diagnostics(catalog, resolve_route(data))
        self.assertEqual((diagnostics["loaded"], diagnostics["eligible"], diagnostics["rejected"]), (1, 0, 1))
        self.assertTrue(diagnostics["unresolved_constraints"])
        self.assertTrue(diagnostics["filtering_rules"])
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, catalog=catalog)
        self.assertEqual(specs[1].state, "provisional")
        self.assertEqual(specs[1].catalog_id, "")

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
        self.assertFalse(scene_eligibility(checked, data).usable)

    def test_routing_preview_scopes_guided_diagnostics_without_additional_model_calls(self):
        data = greeting_draft(2)
        self.assertEqual(dataset_routing(data)[0]["scope"], "all_outputs")
        data.update(source_mode="guided", inputs="An adult oral scene\nA greeting")
        catalog = parse_vocabulary("[couple positions]\nambiguous paired pose\n")
        with patch("goated_prompter.features.dataset.brainstorm.load_vocabulary", return_value=catalog):
            routes = dataset_routing(data)
        self.assertEqual([item["scope"] for item in routes], ["guided:1", "guided:2"])
        self.assertEqual([item["nsfw"] for item in routes], [True, False])
        self.assertEqual(routes[0]["vocabulary"]["rejected"], 1)
        self.assertEqual(routes[1]["private_position_count"], 0)


if __name__ == "__main__":
    unittest.main()
