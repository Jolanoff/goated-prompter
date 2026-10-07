"""Understanding response-format regressions without inference or private storage."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.dataset_understanding import DatasetUnderstandingService, understanding_instruction, validate_understanding
from tests.helpers import dataset_understanding_fixture
from tests.test_dataset import valid_draft


class DatasetUnderstandingTests(unittest.TestCase):
    def test_multiple_character_source_survives_a_lossy_brief_before_review(self):
        trigger = "2 girls, mira, (blue hair:1.2), bat wings, bat wings, hana, blonde hair, crystal wings"
        data = valid_draft(trigger_type="Multiple characters", trigger=trigger,
            subject="Mira on the left reads with Hana on the right. Their appearance may be naturally hidden.")
        brief = dataset_understanding_fixture(character_count=2, identity_policy="fixed", hard=[
            {"scope": "all_outputs", "text": "Mira and Hana read together."}])
        before = deepcopy(brief)
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["hard"][:-1], before["hard"])
        requirement = result["hard"][-1]
        self.assertEqual(requirement["scope"], "all_outputs")
        self.assertEqual(requirement["text"].split("Supplied character trigger (verbatim):\n", 1)[1], trigger)
        self.assertIn("ownership", requirement["text"])
        self.assertIn("not a visibility requirement", requirement["text"])
        self.assertEqual(result["visible_evidence"], [])
        self.assertEqual(brief, before)
        self.assertEqual(set(result), set(brief))

    def test_source_requirement_preserves_identifier_only_mixed_and_local_identity_policies(self):
        data = valid_draft(trigger_type="Multiple characters", trigger="person_1, person_2",
            source_mode="guided", inputs="Mira with a different partner\nTwo strangers")
        brief = dataset_understanding_fixture(identity_policy="mixed", character_count=None,
            hard=[{"scope": "guided:1", "text": "Mira is fixed; her partner's identity is random."}],
            free=[{"scope": "guided:2", "text": "Random identities for both people."}])
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["identity_policy"], "mixed")
        self.assertIsNone(result["character_count"])
        self.assertEqual(result["hard"][0], brief["hard"][0])
        self.assertEqual(result["free"], brief["free"])
        self.assertEqual(result["fixed"], [])
        self.assertEqual(result["visible_evidence"], [])
        self.assertIn("identifiers alone invent neither appearance nor fixed identity", result["hard"][-1]["text"])

    def test_source_requirement_keeps_named_blocks_weights_and_the_full_trigger_boundary(self):
        trigger = "Mira: (blue hair:1.2), bat wings, bat wings\n\nHana: blonde hair, crystal wings, "
        trigger += "x" * (1000 - len(trigger))
        result = self.run_response(json.dumps(dataset_understanding_fixture()),
            valid_draft(trigger_type="Multiple characters", trigger=trigger))
        self.assertEqual(result["hard"][-1]["text"].split("Supplied character trigger (verbatim):\n", 1)[1], trigger)

    def test_source_requirement_does_not_duplicate_an_already_grounded_fresh_brief(self):
        data = valid_draft(trigger_type="Multiple characters", trigger="Mira, blue hair, Hana, blonde hair")
        grounded = self.run_response(json.dumps(dataset_understanding_fixture()), data)
        self.assertEqual(self.run_response(json.dumps(grounded), data), grounded)

    def test_source_requirement_preserves_other_types_and_never_drops_hard_entries_to_fit(self):
        brief = dataset_understanding_fixture(hard=[{"scope": "all_outputs", "text": f"Requirement {index}."}
            for index in range(24)])
        for subject_type in ("Character", "Animal", "Object / product", "Visual style", "Custom"):
            with self.subTest(subject_type=subject_type):
                self.assertEqual(self.run_response(json.dumps(brief), valid_draft(trigger_type=subject_type)), brief)
        data = valid_draft(trigger_type="Multiple characters", trigger="Mira, blue hair, Hana, blonde hair")
        with self.assertRaisesRegex(BackendGenerationError, "leave one HARD entry.*No generation started"):
            self.run_response(json.dumps(brief), data)
        brief["hard"].pop()
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["hard"][:-1], brief["hard"])
        self.assertEqual(len(result["hard"]), 24)

    def test_hard_soft_free_contract_is_validated_without_promoting_generated_choices(self):
        brief = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "One red ceramic cup; its base touching the table is visible."}],
            soft=[{"scope": "all_outputs", "text": "Prefer a close camera and warm lighting."}],
            free=[{"scope": "all_outputs", "text": "Background and exact camera angle."}])
        self.assertEqual(validate_understanding(brief, ("all_outputs", "dataset")), brief)
        instruction = understanding_instruction(valid_draft(subject="One red cup on a table."))
        self.assertIn("hard: user requirements", instruction.system_message)
        self.assertIn("soft: preferences", instruction.system_message)
        self.assertIn("free: unspecified", instruction.system_message)

    def test_contract_categories_require_explicit_scoped_bounded_arrays(self):
        for field in ("hard", "soft", "free"):
            for invalid in (None, "cup", ["cup"], [{"scope": "guided:99", "text": "Cup"}],
                    [{"scope": "all_outputs", "text": "Cup", "approved": True}],
                    [{"scope": "all_outputs", "text": ""}],
                    [{"scope": "all_outputs", "text": "x" * 2001}],
                    [{"scope": "all_outputs", "text": "Cup"}] * 25):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    validate_understanding(dataset_understanding_fixture(**{field: invalid}), ("all_outputs", "dataset"))
            legacy = dataset_understanding_fixture()
            del legacy[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_understanding(legacy, ("all_outputs", "dataset"))

    def test_shared_unspecified_choices_are_choose_once_not_per_image_freedom(self):
        data = valid_draft(subject="A crew working on one shared stunt setup. Choose the setup freely, but keep it the same throughout the dataset.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("keep that freedom dataset-scoped", rules)
        self.assertIn("may choose it once, but must not independently choose a different value per image", rules)
        self.assertIn("dataset-scoped free/may_vary", rules)
        self.assertIn("shared-consistency obligation in hard and fixed without inventing a value", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_fixed_and_unspecified_human_identities_explicitly_require_mixed_policy(self):
        data = valid_draft(subject="Alex is the same performer in every image; the two other crew members are random people.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("If some identities are explicitly fixed while other human identities remain unspecified/random, identity_policy is mixed, not fixed", rules)
        self.assertIn("Partial identity locks do not fix every other trait", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_naturally_hidden_fixed_traits_are_not_demanded_visible_evidence(self):
        data = valid_draft(subject="The same performer has a back tattoo and a shoulder scar; neither needs to be visible.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("visible_evidence contains only features the user actually requires to be visibly demonstrated", rules)
        self.assertIn("A fixed identity trait that may naturally be hidden is not demanded visible evidence", rules)
        self.assertIn("Keep it fixed without forcing later stages to expose it", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_selected_ui_styles_are_hard_unless_explicitly_optional(self):
        for style, custom, constraints in (("Photorealistic", "", ""),
                ("Custom", "Ink wash", ""),
                ("Photorealistic", "", "The selected style is optional.")):
            with self.subTest(style=style, optional=bool(constraints)):
                instruction = understanding_instruction(valid_draft(
                    visual_style=style, custom_style=custom, constraints=constraints))
                rules = " ".join(instruction.system_message.split())
                self.assertIn("An explicitly selected visual_style or custom_style is HARD unless the source explicitly marks that style as optional", rules)
                self.assertIn("do not classify it as SOFT merely because it came from a UI selection", rules)
                source = json.loads(instruction.user_message)["source"]
                self.assertEqual(source["visual_style"], style)
                self.assertEqual(source["custom_style"], custom)
                self.assertEqual(source["constraints"], constraints)

    def test_scoped_contract_and_user_conflicts_survive_one_understanding_call(self):
        brief = dataset_understanding_fixture(
            hard=[{"scope": "guided:1", "text": "Extreme close-up of only his eyes."},
                  {"scope": "guided:1", "text": "Show his shoes clearly in the same image."}],
            soft=[{"scope": "all_outputs", "text": "Warm lighting."}],
            free=[{"scope": "guided:2", "text": "Background."}],
            physical_conflicts=[{"scope": "guided:1", "conflict": "Eyes-only crop excludes shoes.",
                                 "compatible_resolution": None}],
            clarifications=["Should the crop show only eyes, or also the shoes?"])
        data = valid_draft(source_mode="guided", inputs="Eyes only, with shoes visible\nA cup")
        self.assertEqual(self.run_response(json.dumps(brief), data), brief)

    def run_response(self, raw, data=None):
        backend, session = Mock(), Mock()
        backend.generation_session.return_value = nullcontext(session)
        session.generate.return_value = raw
        service = DatasetUnderstandingService({"backend": "mock"}, lambda: None)
        with patch("goated_prompter.dataset_understanding.create_backend", return_value=backend):
            try:
                return service.run(GoatedPrompterRequest(idea="A synthetic cup"),
                                   valid_draft() if data is None else data, lambda _message: None)
            finally:
                session.generate.assert_called_once()

    def test_valid_brief_accepts_one_json_fence_without_another_model_call(self):
        brief = dataset_understanding_fixture()
        raw = json.dumps(brief)
        for value in (raw, "```json\n" + raw + "\n```", "```\n" + raw + "\n```", "\ufeff" + raw):
            with self.subTest(wrapper=value[:10]):
                self.assertEqual(self.run_response(value), brief)

    def test_richer_count_identity_and_scoped_action_options_survive_validation(self):
        brief = dataset_understanding_fixture(character_count=2, identity_policy="random_per_prompt",
            fixed=[{"scope": "all_outputs", "text": "Two adults; at least one has blond hair, not necessarily both."}],
            may_vary=[{"scope": "dataset", "text": "Different people across images; preserve each identity within its image."}],
            action_options=[{"scope": "guided:2", "text": "Punch or block; alternatives, not simultaneous actions."}])
        validated = validate_understanding(brief, ("all_outputs", "dataset", "guided:1", "guided:2"))
        self.assertEqual(validated, brief)
        self.assertEqual(validate_understanding(dataset_understanding_fixture(), ("all_outputs", "dataset")),
            dataset_understanding_fixture())

    def test_object_understanding_explicitly_uses_null_not_zero_characters(self):
        instruction = understanding_instruction(valid_draft(subject="A chipped blue ceramic cup.",
            trigger_type="Object / product"))
        self.assertIn('"character_count": null, "identity_policy": "not_applicable"', instruction.system_message)
        self.assertIn("Never use 0", instruction.system_message)
        source = json.loads(instruction.user_message)["source"]
        self.assertEqual(source["trigger_type"], "Object / product")
        self.assertEqual(source["subject"], "A chipped blue ceramic cup.")

    def test_trigger_label_is_not_image_lettering_or_a_negative_start_rule(self):
        instruction = understanding_instruction(valid_draft(trigger="eval_subject", trigger_at_start=False))
        self.assertIn("not visible image lettering", instruction.system_message)
        self.assertIn("trigger_at_start=false does not forbid", instruction.system_message)
        self.assertEqual(json.loads(instruction.user_message)["source"]["trigger"], "eval_subject")

    def test_richer_identity_and_action_metadata_still_rejects_invalid_types_and_scopes(self):
        for changes in ({"character_count": True}, {"character_count": 0}, {"character_count": 101},
                        {"identity_policy": []}, {"identity_policy": "same random person"},
                        {"action_options": "punch"}, {"action_options": [{"scope": "guided:9", "text": "Punch"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_understanding(dataset_understanding_fixture(**changes), ("all_outputs", "dataset"))

    def test_empty_prose_truncated_multiple_or_invalid_briefs_never_proceed(self):
        brief = json.dumps(dataset_understanding_fixture())
        invalid = ("", "  ", None, "Here is the brief:\n" + brief,
            brief + "\nAnother object: " + brief, "```json\n" + brief,
            "<think>Analyze the request.</think>\n" + brief, "[]", "{}",
            brief.replace('"fixed": []', '"fixed": [], "fixed": []'))
        for raw in invalid:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(BackendGenerationError):
                self.run_response(raw)

    def test_empty_response_has_a_specific_error_without_a_fabricated_brief(self):
        with self.assertRaisesRegex(BackendGenerationError, "empty.*No generation started"):
            self.run_response("  ")

    def test_object_response_canonicalizes_integer_zero_without_another_model_call(self):
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable",
            requested_generation="A chipped blue ceramic cup on a wooden table.")
        data = {**valid_draft(), "subject": "A chipped blue ceramic cup on a wooden table.",
                "trigger_type": "Object / product"}
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result, {**brief, "character_count": None})
        self.assertEqual(brief["character_count"], 0)

    def test_object_count_normalization_does_not_relax_invalid_counts_or_identity(self):
        data = {**valid_draft(), "trigger_type": "Object / product"}
        invalid = [(count, "not_applicable") for count in (False, 0.0, "0", -1, 101)]
        invalid.extend((0, policy) for policy in ("fixed", "random_per_prompt", "mixed"))
        for count, policy in invalid:
            with self.subTest(count=count, policy=policy), self.assertRaises(BackendGenerationError):
                self.run_response(json.dumps(dataset_understanding_fixture(
                    character_count=count, identity_policy=policy)), data)

    def test_non_object_response_still_rejects_zero_even_with_not_applicable_identity(self):
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable")
        with self.assertRaises(BackendGenerationError):
            self.run_response(json.dumps(brief), {**valid_draft(), "trigger_type": "Character"})

    def test_object_count_normalization_preserves_valid_counts_and_other_validation(self):
        data = {**valid_draft(), "trigger_type": "Object / product"}
        for count in (None, 1, 100):
            brief = dataset_understanding_fixture(character_count=count, identity_policy="not_applicable")
            with self.subTest(count=count):
                self.assertEqual(self.run_response(json.dumps(brief), data), brief)
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable",
            fixed=[{"scope": "guided:99", "text": "A cup."}])
        with self.assertRaises(BackendGenerationError):
            self.run_response(json.dumps(brief), data)

    def test_understanding_requests_llama_json_decoding_only_for_its_model_call(self):
        instruction = understanding_instruction(valid_draft())
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(dataset_understanding_fixture())}}]}).encode()
        for owned, json_output in ((True, True), (False, True), (True, False)):
            with self.subTest(owned_llama=owned, json_output=json_output):
                backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic",
                    "_is_llama_cpp": owned})
                with (patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send,
                      patch("goated_prompter.backends.openai_compatible.log_request"),
                      patch("goated_prompter.backends.openai_compatible.log_response")):
                    backend.generate(replace(instruction, json_output=json_output))
                send.assert_called_once()
                payload = json.loads(send.call_args.args[0].data)
                if owned and json_output:
                    self.assertEqual(payload.get("response_format"), {"type": "json_schema", "json_schema": {
                        "name": "response", "strict": True, "schema": instruction.json_schema}})
                else:
                    self.assertNotIn("response_format", payload)

    def test_understanding_schema_limits_complete_brief_scopes_and_reserved_source_slot(self):
        for subject_type, trigger, limit in (("Character", "token", 24),
                ("Multiple characters", "Mira, blue hair, Hana, blonde hair", 23),
                ("Multiple characters", "", 24)):
            with self.subTest(subject_type=subject_type, trigger=trigger):
                instruction = understanding_instruction(valid_draft(trigger_type=subject_type, trigger=trigger,
                    source_mode="guided", inputs="A handshake\n\nA portrait"))
                schema = instruction.json_schema
                self.assertIsNotNone(schema)
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                fields = set(dataset_understanding_fixture())
                self.assertEqual(set(schema["required"]), fields)
                self.assertEqual(set(schema["properties"]), fields)
                props = schema["properties"]
                self.assertEqual(props["character_count"], {"type": ["integer", "null"], "minimum": 1, "maximum": 100})
                self.assertEqual(set(props["identity_policy"]["enum"]), {"fixed", "random_per_prompt", "mixed", "not_applicable"})
                for field, value in dataset_understanding_fixture().items():
                    if isinstance(value, str) and field != "identity_policy":
                        self.assertEqual(props[field], {"type": "string", "minLength": 1, "maxLength": 2000})
                    if not isinstance(value, list):
                        continue
                    array = props[field]
                    self.assertEqual(array["type"], "array")
                    self.assertEqual(array["maxItems"], limit if field == "hard" else 24)
                    self.assertIsInstance(array["items"], dict)
                    item = array["items"]
                    if field == "clarifications":
                        self.assertEqual(item, {"type": "string", "minLength": 1, "maxLength": 2000})
                        continue
                    self.assertIs(item["additionalProperties"], False)
                    self.assertEqual(item["properties"]["scope"]["enum"], ["all_outputs", "dataset", "guided:1", "guided:2"])
                    expected = {"scope", "conflict", "compatible_resolution"} if field == "physical_conflicts" else {"scope", "text"}
                    self.assertEqual(set(item["required"]), expected)
                    self.assertEqual(set(item["properties"]), expected)
                    if field == "physical_conflicts":
                        self.assertEqual(item["properties"]["compatible_resolution"]["type"], ["string", "null"])

    def test_shape_valid_object_with_25_hard_entries_is_rejected_without_retry(self):
        brief = dataset_understanding_fixture(hard=[{"scope": "all_outputs", "text": f"Source requirement {index}."}
            for index in range(25)])
        with self.assertRaisesRegex(BackendGenerationError, "hard must be an array within the understanding limit.*No generation started"):
            self.run_response(json.dumps(brief), valid_draft(trigger_type="Multiple characters", trigger="Mira, Hana"))
