"""One Dataset contract, with only applicable subject validators and optional vocabulary."""

import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.batch_planner import plan_scene_specs
from goated_prompter.features.dataset.routing import resolve_route
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import valid_draft
from goated_prompter.features.dataset.scene_spec import SceneSpec


class UniversalBackend:
    """Authored synthetic responses, with no model or private file access."""
    name = "synthetic-universal"

    def __init__(self):
        self.calls, self.specs, self.scenes = [], {}, {}

    @contextmanager
    def generation_session(self):
        yield self

    def validate_instruction(self, instruction):
        pass

    def emit_activity(self, *args, **kwargs):
        pass

    def generate(self, instruction):
        self.calls.append(instruction)
        stage = instruction.diagnostic_stage
        if stage == "dataset:ideas:brainstorm":
            context = json.loads(instruction.user_message)
            return json.dumps([{"index": spec["index"], "event": "A portrait or display of the approved subjects.",
                "typicality": .5} for spec in context["scene_specs"]])
        if stage == "dataset:planning":
            context = json.loads(instruction.user_message)
            rows = []
            for item in context["assignments"]:
                index = item["index"]
                subjects = []
                for participant in item["participants"]:
                    kind = participant["kind"]
                    subjects.append({"id": participant["id"], "role": participant["role"] or "subject",
                        "pose": participant["pose"] or ("resting" if kind == "animal" else "standing" if kind == "human" else ""),
                        "location": participant["location"] or "center",
                        "support": participant["support"] or ("four_paws_on_ground" if kind == "animal" else "feet_on_floor" if kind == "human" else "")})
                rows.append({"index": index, "action": item["action"] if "action" in item["locked"] else "Portrait or display of the subjects",
                             "participants": subjects, "setting": item["setting"] or "gallery", "contacts": item["contacts"]})
            return json.dumps(rows)
        if stage == "dataset:ideas":
            context = json.loads(instruction.user_message)
            rows = []
            for assignment in context["assignments"]:
                spec = assignment["scene_spec"]
                index = assignment["index"]
                self.specs[index] = spec
                descriptions = []
                for item in spec["participants"]:
                    state = "rests with all four paws on the ground" if item["kind"] == "animal" else "stands with feet on the floor" if item["kind"] == "human" else "is displayed"
                    descriptions.append(f"{item['name']} {state} at the center of the gallery, retaining {item['traits'] or 'its appearance'}")
                scene = ". ".join(descriptions) + f". {spec['action']} at station {index}."
                self.scenes[index] = scene
                rows.append({"index": index, "idea": f"A subject display at station {index}.", "scene": scene})
            return json.dumps(rows)
        if stage.startswith("dataset:validation:"):
            context = json.loads(instruction.user_message)
            rows = []
            for item in context:
                spec, scene = self.specs[item["index"]], item["description"]
                rows.append({"index": item["index"], "participants": [{"id": participant["id"],
                    **{key: participant[key] for key in ("role", "pose", "location", "support")}, "evidence": scene}
                    for participant in spec["participants"]], "contacts": [], "setting": "gallery", "setting_evidence": scene,
                    "action": spec["action"], "action_evidence": scene, "category": spec["category"],
                    "requirements": [{"id": check["id"], "status": "pass", "evidence": scene} for check in item["checks"]],
                    "conflicts": []})
            return json.dumps(rows)
        index = int(stage.split(":")[1])
        prose = "ohwx_person " + self.scenes[index]
        return "gallery, full body\n\n" + prose if "ANIMA" in instruction.system_message else prose


def subject_draft(subjects, **changes):
    return valid_draft(**{"amount": 1, "subject": "Portrait or display of the requested subjects.",
        "trigger_type": "Concept", "_confirmed_intent": dataset_understanding_fixture(character_count=None,
            subjects=[{"scope": "all_outputs", "name": name, "kind": kind, "count": count,
                       "sex": "unspecified" if kind in {"human", "animal"} else "none", "traits": traits}
                      for name, kind, count, traits in subjects]), **changes})


class UniversalPipelineTests(unittest.TestCase):
    def test_whitespace_equivalent_approved_requirements_do_not_trigger_an_extra_scene_check(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.features.dataset.plan import scene_plan_signature
        from goated_prompter.contracts import GoatedPrompterRequest
        from tests.support.dataset import CaptureBackend, planned_scene
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "Preserve the\n original outfit."}]))
        data["scene_plan"] = [planned_scene(data)]
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        backend = CaptureBackend(scenes=data["scene_plan"])
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 1)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:1", "dataset:validation:prompt"])

    def test_final_validation_has_one_targeted_repair_and_retains_uncertainty(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        for finding in ("unknown", "repairable", "hard"):
            with self.subTest(finding=finding):
                data = subject_draft([("Alice", "human", 1, "red jacket")], amount=3)
                class FindingBackend(UniversalBackend):
                    def generate(self, instruction):
                        raw = super().generate(instruction)
                        if instruction.diagnostic_stage == "dataset:validation:prompt":
                            observed = json.loads(raw)
                            for item in observed:
                                if item["index"] == 2:
                                    if finding == "repairable":
                                        item["conflicts"] = ["The reaching arm has an unclear contact with the work surface."]
                                    else:
                                        next(check for check in item["requirements"] if check["id"] == "subject:P1")["status"] = (
                                            "fail" if finding == "hard" else "unknown")
                            raw = json.dumps(observed)
                        return raw
                backend = FindingBackend()
                with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
                    result = DatasetService({"backend": "mock"}, lambda: None).run(
                        GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
                writes = [call for call in backend.calls if call.diagnostic_stage.startswith("dataset:2")]
                self.assertEqual(len(writes), 1 if finding == "unknown" else 2)
                self.assertEqual(sum(call.diagnostic_stage == "dataset:ideas" for call in backend.calls), 1)
                self.assertFalse(any(call.diagnostic_stage == "dataset:validation:scene" for call in backend.calls))
                row = result["scene_plan"][1]
                if finding == "hard":
                    self.assertEqual([item["index"] for item in result["prompts"]], [1, 3])
                    self.assertEqual(row["prompt_status"], "failed")
                    self.assertIn("approved requirement", row["failure_reason"])
                else:
                    self.assertEqual(result["completed"], 3)
                    self.assertEqual(row["prompt_status"], "unverified")
                    self.assertTrue(row["quality_warnings"])
                self.assertEqual([result["scene_plan"][index]["prompt_status"] for index in (0, 2)], ["valid", "valid"])

    def test_failed_final_prompt_coverage_retains_individually_valid_outputs_but_returns_batch_failure(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        data = subject_draft([("kettle", "product", 1, "red finish")], amount=2)
        data["_confirmed_intent"]["hard"] = [{"scope": "dataset", "text": "At least one gallery scene."}]
        class CoverageBackend(UniversalBackend):
            reject_final = True
            def generate(self, instruction):
                if instruction.diagnostic_stage.startswith("dataset:validation:batch:"):
                    self.calls.append(instruction)
                    context = json.loads(instruction.user_message)
                    final = instruction.diagnostic_stage.endswith(":prompt") and self.reject_final
                    return json.dumps([{"id": "batch:0", "status": "fail" if final else "pass",
                        "evidence": [{"index": 1, "quote": context["descriptions"][0]["text"]}]}])
                return super().generate(instruction)
        backend, snapshots = CoverageBackend(), []
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, snapshots.append)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["prompts"]), 2)
        self.assertIn("dataset-wide", result["error"])
        self.assertEqual(result["failed"], 0)
        self.assertTrue(all(row["prompt_status"] == "valid" and "failure_stage" not in row for row in result["scene_plan"]))
        self.assertTrue(all(row["batch_validation"]["valid"] is False for row in result["scene_plan"]))
        self.assertEqual(snapshots[-1]["prompts"], result["prompts"])
        data.update(scene_plan=result["scene_plan"], scene_plan_signature=result["scene_plan_signature"],
                    results=result["prompts"])
        backend.reject_final = False
        backend.calls.clear()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            repaired = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                lambda _: None, lambda _: None, scene_action=("regenerate_prompt", 1))
        self.assertTrue(repaired["ok"])
        self.assertEqual(repaired["failed"], 0)
        self.assertEqual(len(repaired["prompts"]), 2)
        self.assertFalse(any(call.diagnostic_stage in {"dataset:ideas", "dataset:planning", "dataset:2"}
                             for call in backend.calls))

    def test_no_usable_scenes_or_prompts_returns_failure_with_retained_slot_diagnostics(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        class FailedPlanningBackend(UniversalBackend):
            def generate(self, instruction):
                if instruction.diagnostic_stage == "dataset:planning":
                    self.calls.append(instruction)
                    return "[]"
                return super().generate(instruction)
        for scenes_only in (False, True):
            with self.subTest(scenes_only=scenes_only):
                data = subject_draft([("valley", "environment", 1, "green hills")], amount=10)
                backend, snapshots = FailedPlanningBackend(), []
                with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
                    result = DatasetService({"backend": "mock"}, lambda: None).run(
                        GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                        lambda _: None, snapshots.append, scenes_only=scenes_only)
                self.assertFalse(result["ok"])
                self.assertIn("No usable Dataset", result["error"])
                self.assertEqual(len(result["scene_plan"]), 10)
                self.assertEqual(snapshots[-1]["scene_plan"], result["scene_plan"])
                self.assertTrue(all(row["scene_status"] == "failed" and row["failure_reason"] for row in result["scene_plan"]))
                self.assertFalse(any(call.diagnostic_stage == "dataset:ideas" or call.diagnostic_stage == "dataset:1"
                                     for call in backend.calls))

    def test_uncertain_dataset_coverage_does_not_block_individually_valid_prompts(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        data = subject_draft([("kettle", "product", 1, "red finish")], amount=2)
        data["_confirmed_intent"]["hard"] = [{"scope": "dataset", "text": "At least one outdoor scene."}]
        class CoverageBackend(UniversalBackend):
            def generate(self, instruction):
                if instruction.diagnostic_stage.startswith("dataset:validation:batch:"):
                    self.calls.append(instruction)
                    return json.dumps([{"id": "batch:0", "status": "unknown", "evidence": []}])
                return super().generate(instruction)
        backend = CoverageBackend()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"],
                prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(result["ok"])
        self.assertTrue(all(row["prompt_status"] == "valid" for row in result["scene_plan"]))
        self.assertTrue(all(row["batch_validation"]["valid"] is False for row in result["scene_plan"]))
        self.assertEqual(sum(call.diagnostic_stage in {"dataset:1", "dataset:2"} for call in backend.calls), 2)

    def test_dataset_coverage_is_checked_only_once_after_final_prompts(self):
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        data = subject_draft([("kettle", "product", 1, "red finish")], amount=2)
        data["_confirmed_intent"]["hard"] = [{"scope": "dataset", "text": "At least one gallery scene."}]
        class CoverageBackend(UniversalBackend):
            def generate(self, instruction):
                if instruction.diagnostic_stage.startswith("dataset:validation:batch:"):
                    self.calls.append(instruction)
                    context = json.loads(instruction.user_message)
                    return json.dumps([{"id": "batch:0", "status": "pass", "evidence": [
                        {"index": 1, "quote": context["descriptions"][0]["text"]}]}])
                return super().generate(instruction)
        backend = CoverageBackend()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"],
                prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual((result["completed"], result["failed"]), (2, 0))
        stages = [call.diagnostic_stage for call in backend.calls]
        self.assertEqual(stages.count("dataset:validation:batch:scene"), 0)
        self.assertEqual(stages.count("dataset:validation:batch:prompt"), 1)
        self.assertLess(stages.index("dataset:2"), stages.index("dataset:validation:batch:prompt"))

    def test_cached_scene_is_rechecked_against_the_current_approved_hard_requirements(self):
        from goated_prompter.features.dataset.plan import scene_plan_signature
        from goated_prompter.features.dataset.service import DatasetService
        from goated_prompter.contracts import GoatedPrompterRequest
        from tests.support.dataset import CaptureBackend, saved_scene
        data = valid_draft(amount=1, scene_plan=[saved_scene()], _confirmed_intent=dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "A visible red ceramic cup."}]))
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        class MissingRequirementBackend(CaptureBackend):
            def generate(self, instruction):
                if instruction.diagnostic_stage == "dataset:validation:prompt":
                    self.calls.append(instruction)
                    context = json.loads(instruction.user_message)
                    from tests.support.dataset import scene_observation
                    spec = SceneSpec.from_dict(data["scene_plan"][0]["scene_spec"])
                    observation = scene_observation(spec, context[0]["description"])
                    observation["requirements"] = [{"id": check["id"], "status": "fail" if check["id"] == "hard:0" else "pass",
                        "evidence": "" if check["id"] == "hard:0" else context[0]["description"]} for check in context[0]["checks"]]
                    return json.dumps([observation])
                return super().generate(instruction)
        backend = MissingRequirementBackend(scenes=data["scene_plan"])
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"),
                data, lambda _: None, lambda _: None, valid_only=True)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["scene_plan"][0]["scene"], data["scene_plan"][0]["scene"])
        self.assertEqual(sum(call.diagnostic_stage.startswith("dataset:1") for call in backend.calls), 2)
        self.assertEqual(result["scene_plan"][0]["prompt_status"], "failed")
        self.assertFalse(any(call.diagnostic_stage == "dataset:validation:scene" for call in backend.calls))

    def run_dataset(self, data):
        from goated_prompter.contracts import GoatedPrompterRequest
        from goated_prompter.features.dataset.service import DatasetService
        backend = UniversalBackend()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend), patch(
                "goated_prompter.features.dataset.batch_planner.load_vocabulary", side_effect=AssertionError("SFW catalog access")):
            result = DatasetService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"],
                prompt_model="Custom"), data, lambda _: None, lambda _: None)
        return result, backend

    def test_all_subject_types_use_the_same_contract_and_only_applicable_validators(self):
        cases = [[("Alice", "human", 1, "red jacket")], [("friends", "human", 2, "red jackets")],
                 [("spaniel", "animal", 1, "brown fur")], [("kettle", "product", 1, "red finish")],
                 [("stone", "object", 1, "rough surface")], [("valley", "environment", 1, "green hills")],
                 [("Alice", "human", 1, "red jacket"), ("spaniel", "animal", 1, "brown fur"), ("kettle", "product", 1, "red finish")]]
        for subjects in cases:
            with self.subTest(subjects=subjects):
                result, backend = self.run_dataset(subject_draft(subjects))
                self.assertEqual(result["completed"], 1)
                spec = result["scene_plan"][0]["scene_spec"]
                self.assertEqual(spec["state"], "frozen")
                self.assertEqual(len(spec["participants"]), sum(item[2] for item in subjects))
                checks = [json.loads(call.user_message)[0] for call in backend.calls if call.diagnostic_stage == "dataset:validation:prompt"]
                self.assertEqual(checks[0]["applicable_validators"]["anatomy_subjects"], [])
                expected = [item["id"] for item in spec["participants"] if item["kind"] in {"human", "animal"}]
                self.assertEqual(checks[0]["applicable_validators"]["position_subjects"], expected)

    def test_complete_25_image_batch_preserves_guided_subject_scopes_in_five_item_chunks(self):
        data = subject_draft([])
        data.update(amount=25, source_mode="guided", inputs="A solo person\nTwo people\nAn animal\nA product\nAn environment")
        data["_confirmed_intent"]["subjects"] = [{"scope": f"guided:{index}", "name": name, "kind": kind,
            "count": count, "sex": "unspecified" if kind in {"human", "animal"} else "none", "traits": traits}
            for index, (name, kind, count, traits) in enumerate([
                ("Alice", "human", 1, "red jacket"), ("friends", "human", 2, "red jackets"),
                ("spaniel", "animal", 1, "brown fur"), ("kettle", "product", 1, "red finish"),
                ("valley", "environment", 1, "green hills")], 1)]
        result, backend = self.run_dataset(data)
        self.assertEqual((result["completed"], result["failed"]), (25, 0))
        self.assertEqual([item["index"] for item in result["prompts"]], list(range(1, 26)))
        for stage in ("dataset:planning", "dataset:ideas"):
            calls = [call for call in backend.calls if call.diagnostic_stage == stage]
            self.assertEqual(len(calls), 5)
            self.assertTrue(all(len(json.loads(call.user_message)["assignments"] if stage != "dataset:validation:scene"
                else json.loads(call.user_message)) == 5 for call in calls))
        kinds = [row["scene_spec"]["participants"][0]["kind"] for row in result["scene_plan"]]
        self.assertEqual(sum(call.diagnostic_stage == "dataset:validation:prompt" for call in backend.calls), 25)
        self.assertFalse(any(call.diagnostic_stage == "dataset:validation:scene" for call in backend.calls))
        self.assertEqual(kinds, ["human", "human", "animal", "product", "environment"] * 5)

    def test_target_and_style_changes_preserve_the_same_subject_specification(self):
        for target, style in (("Generic", "Auto"), ("Qwen Image", "Realistic"), ("Anima", "Anime")):
            with self.subTest(target=target, style=style):
                data = subject_draft([("kettle", "product", 1, "red finish")], target=target, style=style)
                result, backend = self.run_dataset(data)
                self.assertEqual(result["completed"], 1)
                self.assertEqual(result["target"], target)
                self.assertEqual(result["scene_plan"][0]["scene_spec"]["participants"][0]["kind"], "product")

    def test_adult_solo_without_vocabulary_uses_scoped_anatomy_validation(self):
        data = subject_draft([("adult man", "human", 1, "adult")], subject="A solo nude adult portrait.")
        result, backend = self.run_dataset(data)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["scene_plan"][0]["scene_spec"]["route"], "adult")
        check = json.loads(next(call for call in backend.calls if call.diagnostic_stage == "dataset:validation:prompt").user_message)[0]
        self.assertEqual(check["applicable_validators"]["anatomy_subjects"], ["P1"])


class UniversalValidationTests(unittest.TestCase):
    def test_arrangement_cannot_invent_anatomy_for_an_incompatible_cast(self):
        from goated_prompter.features.dataset.private_vocabulary import parse_vocabulary
        from goated_prompter.features.dataset.compatibility import compatible_arrangements
        catalog = parse_vocabulary("[couple positions]\n" + json.dumps({"id": "private-template", "category": "vaginal",
            "participantCount": 2, "participants": {"A": {"pose": "standing", "location": "left"},
                "B": {"pose": "standing", "location": "right"}}, "contacts": [{"from": "A.penis", "to": "B.vagina"}],
            "physicalConstraints": {"A": "feet_on_floor", "B": "feet_on_floor"}}))
        data = subject_draft([("adult men", "human", 2, "adult")], subject="Two adult men in sexual scenes.")
        data["_confirmed_intent"]["subjects"][0]["sex"] = "male"
        eligible, rejected = compatible_arrangements(catalog, resolve_route(data))
        self.assertEqual(eligible, [])
        self.assertEqual(rejected[0]["rule"], "participant_anatomy")

    def test_batch_requirement_can_be_evidenced_by_one_image_not_every_image(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.validation import verify_batch_requirements
        data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(
            hard=[{"scope": "dataset", "text": "At least one rainy scene."}]))
        session = Mock()
        session.generate.return_value = json.dumps([{"id": "batch:0", "status": "pass", "evidence": [
            {"index": 2, "quote": "Rain falls on the red jacket."}]}])
        proof = verify_batch_requirements(session, data, [{"index": 1, "scene": "A dry street."},
            {"index": 2, "scene": "Rain falls on the red jacket."}], lambda: None)
        self.assertTrue(proof["valid"])
        sent = json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual(len(sent["descriptions"]), 2)
        self.assertEqual(sent["checks"][0]["text"], "At least one rainy scene.")

    def test_unknown_or_fabricated_batch_evidence_blocks_acceptance(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.validation import verify_batch_requirements
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture(
            hard=[{"scope": "dataset", "text": "A rainy scene."}]))
        for status, quote in (("unknown", "A dry street."), ("pass", "Invented rain")):
            session = Mock()
            session.generate.return_value = json.dumps([{"id": "batch:0", "status": status,
                "evidence": [{"index": 1, "quote": quote}]}])
            self.assertFalse(verify_batch_requirements(session, data, [{"index": 1, "scene": "A dry street."}],
                                                      lambda: None)["valid"])

    def test_nonbodied_validation_has_identity_checks_but_no_physical_validators(self):
        from goated_prompter.features.dataset.scene_spec import Participant, SceneSpec
        from goated_prompter.features.dataset.validation import validation_instruction
        spec = SceneSpec(1, "general", "A red kettle on display", (
            Participant("P1", "red kettle", "", "", "center", "", sex="none", traits="red", kind="product"),))
        sent = json.loads(validation_instruction([{"scene_spec": spec.to_dict(), "scene": "A red kettle on display."}]).user_message)[0]
        self.assertEqual(sent["applicable_validators"]["position_subjects"], [])
        self.assertEqual(sent["applicable_validators"]["anatomy_subjects"], [])
        self.assertFalse(sent["applicable_validators"]["contacts"])
        self.assertIn("subject:P1", [check["id"] for check in sent["checks"]])

    def test_vocabulary_diagnostics_expose_counts_and_rules_not_private_entries(self):
        from goated_prompter.features.dataset.private_vocabulary import parse_vocabulary
        from goated_prompter.features.dataset.compatibility import vocabulary_diagnostics
        catalog = parse_vocabulary("[couple positions]\nPRIVATE_SENTINEL_INVALID_ENTRY\n")
        data = valid_draft(subject="Two adults in sexual scenes.", _confirmed_intent=dataset_understanding_fixture(character_count=2))
        diagnostics = vocabulary_diagnostics(catalog, resolve_route(data))
        self.assertEqual(diagnostics["loaded"], 1)
        self.assertEqual(diagnostics["rejected"], 1)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(diagnostics))


class UniversalPlanningTests(unittest.TestCase):
    def test_planning_schema_binds_each_mixed_subject_and_excludes_nonbodied_mechanics(self):
        from goated_prompter.features.dataset.batch_planner import planning_instruction
        data = subject_draft([("ranger", "human", 1, ""), ("goat", "animal", 1, ""),
                              ("cargo bicycle", "object", 1, "")], amount=2)
        specs = list(plan_scene_specs(data, dataset_assignments(data), directions={}).values())
        schema = planning_instruction(data, specs).json_schema
        self.assertEqual(len(schema["prefixItems"]), 2)
        for slot, spec in zip(schema["prefixItems"], specs):
            self.assertEqual(slot["properties"]["index"]["const"], spec.index)
            participants = slot["properties"]["participants"]
            self.assertEqual(participants["minItems"], 3)
            self.assertEqual(participants["maxItems"], 3)
            for fields, subject in zip(participants["prefixItems"], spec.participants):
                fields = fields["properties"]
                self.assertEqual(fields["id"]["const"], subject.id)
                for field in ("pose", "support"):
                    if subject.bodied:
                        self.assertEqual(fields[field]["maxLength"], 240)
                    else:
                        self.assertEqual(fields[field], {"type": "string", "const": ""})

    def test_multiple_required_place_descriptions_are_retained_not_last_write_wins(self):
        from goated_prompter.features.dataset.batch_planner import planning_instruction
        data = subject_draft([("teapot", "product", 1, "blue ceramic")])
        data["_confirmed_intent"]["planning_constraints"] = [
            {"scope": "all_outputs", "action": None, "setting": setting, "participants": [], "contacts": []}
            for setting in ("old astronomical observatory", "wooden worktable", "old astronomical observatory")]
        spec = plan_scene_specs(data, dataset_assignments(data), directions={})[1]
        self.assertEqual(spec.setting, "old astronomical observatory; wooden worktable")
        self.assertIn("setting", spec.locked)
        field = planning_instruction(data, [spec]).json_schema["prefixItems"][0]["properties"]["setting"]
        self.assertEqual(field["const"], spec.setting)

    def test_schema_constrained_forest_and_animal_candidates_reach_frozen_plans(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.batch_planner import propose_scene_specs
        cases = [([("blonde explorer", "human", 1, "fair skin, long tousled blonde hair"),
                   ("mossy fantasy forest", "environment", 1, "lush moss")], "Exploring a mossy fantasy forest", "forest floor"),
                 ([("spaniel", "animal", 1, "brown fur"), ("bench", "object", 1, "wooden")],
                  "A spaniel resting beside a bench", "beside the bench")]
        for subjects, action, location in cases:
            with self.subTest(action=action):
                data = subject_draft(subjects, amount=10, subject=action)
                data["_confirmed_intent"]["requested_generation"] = action
                provisional = list(plan_scene_specs(data, dataset_assignments(data), directions={}).values())
                session = Mock()
                def generate(instruction):
                    context = json.loads(instruction.user_message)
                    fields = instruction.json_schema["prefixItems"][0]["properties"]["participants"]["prefixItems"][0]["properties"]
                    # Replay an allowed natural-language location unless the wire contract rules it out.
                    layout = "center" if "enum" in fields["location"] else location
                    return json.dumps([{"index": item["index"], "action": action, "setting": "woodland",
                        "participants": [{"id": participant["id"], "role": "subject", "pose": "",
                                          "location": layout, "support": ""} for participant in item["participants"]],
                        "contacts": []} for item in context["assignments"]])
                session.generate.side_effect = generate
                frozen, errors = propose_scene_specs(session, data, provisional, lambda: None)
                self.assertEqual(errors, {})
                self.assertEqual(set(frozen), set(range(1, 11)))
                self.assertEqual(session.generate.call_count, 2)
                self.assertTrue(all(spec.state == "frozen" for spec in frozen.values()))

    def test_planning_wire_contract_matches_subject_and_contact_validation_limits(self):
        from goated_prompter.features.dataset.batch_planner import planning_instruction
        data = subject_draft([("spaniel", "animal", 1, "brown fur"), ("bench", "object", 1, "wooden")])
        specs = list(plan_scene_specs(data, dataset_assignments(data), directions={}).values())
        instruction = planning_instruction(data, specs)
        fields = instruction.json_schema["prefixItems"][0]["properties"]["participants"]["prefixItems"][0]["properties"]
        self.assertEqual(set(fields["location"].get("enum", [])), {"", "left", "right", "center", "foreground", "background"})
        for field in ("role", "pose", "support"):
            self.assertEqual(fields[field]["maxLength"], 240)
        self.assertEqual(fields["id"].get("const"), "P1")
        endpoints = instruction.json_schema["prefixItems"][0]["properties"]["contacts"]["items"]["properties"]
        for field in ("source", "target"):
            self.assertRegex("P1.paw", endpoints[field].get("pattern", r"(?!)"))
            self.assertNotRegex("spaniel's paw", endpoints[field].get("pattern", ""))
        self.assertIn("forest floor", instruction.system_message)
        self.assertIn("P1.hand", instruction.system_message)

    def test_rejected_candidates_report_the_invalid_contract_field_without_model_text(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.batch_planner import propose_scene_specs
        data = subject_draft([("spaniel", "animal", 1, "brown fur")])
        specs = list(plan_scene_specs(data, dataset_assignments(data), directions={}).values())
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "action": "Dog rests", "setting": "garden",
            "participants": [{"id": "P1", "role": "subject", "pose": "", "location": "PRIVATE_LOCATION",
                              "support": ""}], "contacts": []}])
        frozen, errors = propose_scene_specs(session, data, specs, lambda: None)
        self.assertEqual(frozen, {})
        self.assertIn("location", errors[1])
        self.assertNotIn("PRIVATE_LOCATION", errors[1])

    def test_all_planning_failures_never_announce_empty_idea_ranges(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.plan import ScenePlanner
        data = subject_draft([("valley", "environment", 1, "green hills")], amount=10)
        session = Mock()
        session.generate.return_value = "[]"
        progress = []
        rows = ScenePlanner(lambda: None).plan_ideas(session=session, data=data, assignments=dataset_assignments(data),
            progress=progress.append, allow_partial=True)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["scene_status"] == "failed" for row in rows))
        self.assertFalse(any(message.startswith("Creating ideas") for message in progress), progress)

    def test_anima_count_tags_count_characters_without_counting_animals_products_or_environments(self):
        from goated_prompter.features.dataset.prompting import anima_count_tags
        character = {"kind": "human", "sex": "female", "count": 1}
        noncharacters = [{"kind": "animal", "sex": "male", "count": 2},
                         {"kind": "product", "sex": "none", "count": 3},
                         {"kind": "environment", "sex": "none", "count": 1}]
        self.assertEqual(anima_count_tags([character, *noncharacters]), ["1girl"])
        self.assertEqual(anima_count_tags(noncharacters), ["no humans"])

    def test_vocabulary_roles_bind_to_owned_subjects_regardless_of_inventory_order(self):
        from tests.support.dataset import vocabulary_record, vocabulary_text
        from goated_prompter.features.dataset.private_vocabulary import parse_vocabulary
        for count in (2, 3):
            data = subject_draft([("woman", "human", 1, ""), ("men", "human", count - 1, "")], subject="Adults having vaginal sex")
            data["_confirmed_intent"]["subjects"][0]["sex"] = "female"
            data["_confirmed_intent"]["subjects"][1]["sex"] = "male"
            catalog = parse_vocabulary(vocabulary_text(("vaginal positions", vocabulary_record("synthetic role ordering", "vaginal",
                sexes=("male", "female", *("male",) * (count - 2)), contacts=[{"from": "A.penis", "to": "B.vagina"}]))))
            with self.subTest(count=count):
                spec = plan_scene_specs(data, dataset_assignments(data), directions={}, catalog=catalog)[1]
                self.assertTrue(spec.private_vocabulary)
                self.assertEqual(spec.participants[0].name, "woman")
                self.assertEqual(spec.participants[0].role, "receiver")
                self.assertEqual(spec.participants[1].role, "performer")
                self.assertEqual([(item.source, item.target) for item in spec.contacts], [("P2.penis", "P1.vagina")])

    def test_specific_foot_interactions_activate_only_relevant_approved_routing(self):
        for action in ("Two adult men licking feet", "Two adult men in foot worship"):
            data = subject_draft([("adult men", "human", 2, "adult")], subject=action)
            data["_confirmed_intent"]["subjects"][0]["sex"] = "male"
            with self.subTest(action=action):
                route = resolve_route(data)
                self.assertEqual(route.profile, "adult")
                self.assertEqual(route.categories, frozenset({"feet"}))
                self.assertTrue(route.vocabulary_applicable)
        data = subject_draft([("table", "product", 1, "four feet")], subject="A table with four feet")
        self.assertFalse(resolve_route(data).vocabulary_applicable)

    def test_a_mixed_source_without_owned_sexes_does_not_make_every_subject_male(self):
        data = valid_draft(subject="Two men and one woman sightseeing", trigger="", trigger_type="Multiple characters",
            _confirmed_intent=dataset_understanding_fixture(character_count=3))
        self.assertEqual(resolve_route(data).sexes, ("unspecified",) * 3)

    def test_animal_contact_endpoints_cannot_be_silently_treated_as_human_hands(self):
        from goated_prompter.features.dataset.scene_spec import Contact, Participant
        from goated_prompter.features.dataset.validation import validation_instruction, scene_spec_errors
        spec = SceneSpec(1, "general", "A dog beside a bench", (
            Participant("P1", "dog", "", "", "", "", kind="animal"),
            Participant("P2", "bench", "", "", "", "", kind="object")),
            (Contact("P1.left_hand", "P2.surface"),))
        scene = "The dog's left hand rests on the bench surface."
        instruction = validation_instruction([{"scene": scene, "scene_spec": spec.to_dict()}])
        context = json.loads(instruction.user_message)[0]
        self.assertEqual(context["applicable_validators"]["anatomy_subjects"], ["P1"])
        self.assertEqual(context["cast"][0]["kind"], "animal")
        from tests.support.dataset import scene_observation
        observation = scene_observation(spec, scene)
        observation["conflicts"] = ["The described dog has paws, not a human hand."]
        self.assertTrue(scene_spec_errors(scene, spec, observation))

    def test_contacts_support_owned_animal_parts_and_product_components_without_human_poses(self):
        from goated_prompter.features.dataset.scene_spec import Contact, Participant
        spec = SceneSpec(1, "general", "A dog beside a connected product", (
            Participant("P1", "dog", "", "", "", "", kind="animal"),
            Participant("P2", "hub", "", "", "", "", kind="product"),
            Participant("P3", "cable", "", "", "", "", kind="object")),
            (Contact("P1.nose", "P2.surface"), Contact("P3.connector", "P2.usb_socket")))
        self.assertEqual(SceneSpec.from_dict(spec.to_dict()), spec)

    def test_partial_candidate_planning_freezes_only_the_returned_slot(self):
        from unittest.mock import Mock
        from goated_prompter.features.dataset.batch_planner import propose_scene_specs
        data = subject_draft([("kettle", "product", 1, "red finish")], amount=2)
        provisional = plan_scene_specs(data, dataset_assignments(data), directions={})
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 2, "action": "Kettle on a garden table", "setting": "garden",
            "participants": [{"id": "P1", "role": "subject", "pose": "", "location": "center", "support": ""}], "contacts": []}])
        frozen, errors = propose_scene_specs(session, data, list(provisional.values()), lambda: None)
        self.assertEqual(set(frozen), {2})
        self.assertEqual(set(errors), {1})
        self.assertEqual(frozen[2].state, "frozen")

    def test_uncertain_candidate_fields_do_not_freeze_or_discard_a_resolved_sibling(self):
        from copy import deepcopy
        from unittest.mock import Mock
        from goated_prompter.features.dataset.batch_planner import propose_scene_specs
        data = subject_draft([("Alice", "human", 1, "red jacket")], amount=2)
        provisional = list(plan_scene_specs(data, dataset_assignments(data), directions={}).values())
        candidate = {"index": 1, "action": "Alice stands for a portrait", "setting": "gallery",
            "participants": [{"id": "P1", "role": "subject", "pose": "standing", "location": "center",
                              "support": "feet_on_floor"}], "contacts": []}
        sibling = {**deepcopy(candidate), "index": 2}
        for field in ("action", "setting", "role", "pose", "support"):
            with self.subTest(field=field):
                uncertain = deepcopy(candidate)
                if field in {"action", "setting"}:
                    uncertain[field] = "unknown"
                else:
                    uncertain["participants"][0][field] = "unknown"
                session = Mock()
                session.generate.return_value = json.dumps([uncertain, sibling])
                frozen, errors = propose_scene_specs(session, data, provisional, lambda: None)
                self.assertEqual(set(frozen), {2})
                self.assertEqual(set(errors), {1})
                self.assertEqual(frozen[2].participants[0].support, "feet_on_floor")

    def test_a_guided_subject_anchor_allows_a_specific_candidate_event_before_freezing(self):
        from goated_prompter.features.dataset.batch_planner import freeze_scene_spec
        data = subject_draft([("kettle", "product", 1, "red finish")], source_mode="guided", inputs="A red kettle outdoors")
        provisional = plan_scene_specs(data, dataset_assignments(data), directions={})[1]
        candidate = {"index": 1, "action": "The red kettle is displayed on a garden table", "setting": "garden",
            "participants": [{"id": "P1", "role": "subject", "pose": "", "location": "center", "support": ""}], "contacts": []}
        frozen = freeze_scene_spec(provisional, candidate)
        self.assertEqual(frozen.action, candidate["action"])
        self.assertEqual(frozen.concept, "A red kettle outdoors")

    def test_an_explicit_edit_drops_stale_creative_suggestions_but_keeps_approved_locks(self):
        from goated_prompter.features.dataset.scene_spec import Participant
        from goated_prompter.features.dataset.validation import reconcile_scene_spec
        spec = SceneSpec(1, "general", "Kettle display", (Participant("P1", "kettle", "subject", "", "center", "", kind="product"),),
            setting="gallery", choices=(("lighting", "night light"),), locked=("hard",))
        observation = {"participants": [{"id": "P1", "role": "subject", "pose": "", "location": "center", "support": ""}],
            "action": "Kettle display", "contacts": [], "setting": "garden"}
        reconciled = reconcile_scene_spec(spec.to_dict(), observation)
        self.assertEqual(reconciled.setting, "garden")
        self.assertEqual(reconciled.choices, ())
        self.assertEqual(reconciled.locked, ("hard",))

    def test_animal_mechanics_and_mixed_object_contacts_survive_approval_without_human_pose_rules(self):
        from goated_prompter.features.dataset.understanding import validate_understanding
        data = subject_draft([("spaniel", "animal", 1, "brown fur"), ("bench", "object", 1, "wooden")])
        constraint = {"scope": "all_outputs", "action": "The spaniel rests a paw on the bench", "setting": None,
            "participants": [{"id": "P1", "role": None, "pose": "standing", "location": None,
                              "support": "three_paws_on_ground"}], "contacts": [{"source": "P1.paw", "target": "P2.surface"}]}
        data["_confirmed_intent"]["planning_constraints"] = [constraint]
        approved = validate_understanding(data["_confirmed_intent"], ("all_outputs", "dataset"))
        data["_confirmed_intent"] = approved
        spec = plan_scene_specs(data, dataset_assignments(data), directions={})[1]
        self.assertEqual(spec.participants[0].support, "three_paws_on_ground")
        self.assertEqual(spec.participants[1].pose, "")
        self.assertEqual(spec.contacts[0].target, "P2.surface")

    def test_products_have_subject_identity_but_no_invented_human_pose_or_anatomy(self):
        data = valid_draft(amount=1, trigger_type="Object / product", subject="A red kettle.",
            _confirmed_intent=dataset_understanding_fixture(character_count=None, identity_policy="not_applicable",
                                                          requested_generation="A red kettle."))
        with patch("goated_prompter.features.dataset.batch_planner.load_vocabulary", side_effect=AssertionError("Irrelevant vocabulary")):
            spec = plan_scene_specs(data, dataset_assignments(data), directions={})[1]
        self.assertEqual(len(spec.participants), 1)
        self.assertEqual(spec.participants[0].kind, "product")
        self.assertEqual(spec.participants[0].pose, "")
        self.assertEqual(spec.participants[0].support, "")

    def test_an_optional_missing_catalog_does_not_block_an_adult_request(self):
        cast = [{"name": "adult", "kind": "human", "sex": "male", "count": 1,
                 "origin": "described", "series": "", "traits": "adult"}]
        data = valid_draft(amount=1, subject="A solo adult sexual scene.",
            _confirmed_intent=dataset_understanding_fixture(character_count=1, characters=cast))
        from goated_prompter.features.dataset.private_vocabulary import Vocabulary
        spec = plan_scene_specs(data, dataset_assignments(data), directions={}, catalog=Vocabulary())[1]
        self.assertEqual(spec.route, "adult")
        self.assertFalse(spec.catalog_id)
        self.assertEqual(spec.state, "provisional")

    def test_dataset_hard_requirements_are_not_copied_into_each_image(self):
        data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture(
            hard=[{"scope": "dataset", "text": "At least one scene uses rain."},
                  {"scope": "all_outputs", "text": "Red jacket."}]))
        specs = plan_scene_specs(data, dataset_assignments(data), directions={})
        for spec in specs.values():
            self.assertEqual(spec.hard, ("Red jacket.",))

    def test_guided_subjects_do_not_activate_another_lines_adult_strategy(self):
        data = valid_draft(amount=2, source_mode="guided", inputs="Solo adult sexual scene\nA red kettle", subject="Various subjects",
            _confirmed_intent=dataset_understanding_fixture(character_count=None, subjects=[
                {"scope": "guided:1", "name": "adult man", "kind": "human", "count": 1, "sex": "male", "traits": "adult"},
                {"scope": "guided:2", "name": "red kettle", "kind": "product", "count": 1, "sex": "none", "traits": "red"}]))
        self.assertEqual(resolve_route(data, "guided:1").profile, "adult")
        self.assertEqual(resolve_route(data, "guided:2").profile, "general")


if __name__ == "__main__":
    unittest.main()
