"""Compact idea-stage behavior with synthetic requests and mocked model output."""

from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import (ACTION_SAFE_AXES, DIRECTION_AXES, DatasetIdeasService, IDEA_FIELDS, IDEAS_SYSTEM,
    creative_directions, ideas_instruction, validate_ideas)
from goated_prompter.features.dataset.plan import validate_saved_scene_plan
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support.dataset import valid_draft


class DatasetIdeasTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=2, subject="A boxer training.",
            _confirmed_intent=dataset_understanding_fixture())
        self.session = Mock()
        self.service = DatasetIdeasService(lambda: None)

    def test_creative_directions_spread_the_batch_and_are_reproducible(self):
        data = valid_draft(amount=16, subject="A boxer training.", _confirmed_intent=dataset_understanding_fixture())
        directions = creative_directions(data, range(1, 17))
        self.assertEqual(directions, creative_directions(deepcopy(data), range(1, 17)))
        self.assertEqual(creative_directions(data, [5]), {5: directions[5]}, "A replacement keeps its direction.")
        for axis, values in DIRECTION_AXES.items():
            used = [directions[index][axis] for index in range(1, 17)]
            self.assertEqual(set(used[:len(values)]), set(values), f"Every {axis} is used before any repeats.")
        self.assertGreater(len({tuple(item.values()) for item in directions.values()}), 15)
        other = creative_directions({**data, "subject": "A chef plating dessert."}, range(1, 17))
        self.assertNotEqual(directions, other)

    def test_required_actions_only_vary_framing_and_light(self):
        # Reported regressions: rest, water-break and ladder-climbing directions replaced "both kids visibly working".
        action = {"scope": "all_outputs", "text": "both kids are visibly working on the treehouse"}
        data = valid_draft(amount=10, subject="Two kids building a treehouse together",
            _confirmed_intent=dataset_understanding_fixture(hard=[action], interactions=[action], action_options=[action]))
        directions = creative_directions(data, range(1, 11))
        self.assertTrue(all(set(direction) == set(ACTION_SAFE_AXES) for direction in directions.values()))
        self.assertGreater(len({tuple(direction.values()) for direction in directions.values()}), 6)
        local = {"scope": "guided:2", "text": "punches the bag"}
        guided = valid_draft(amount=4, source_mode="guided", inputs="rests between rounds\npunches the bag",
            _confirmed_intent=dataset_understanding_fixture(interactions=[local]))
        local_directions = creative_directions(guided, range(1, 5))
        self.assertTrue(all(set(local_directions[index]) == set(ACTION_SAFE_AXES) for index in (2, 4)))
        self.assertTrue(all("mood" in local_directions[index] for index in (1, 3)))
        open_brief = creative_directions(self.data, [1, 2])
        self.assertTrue(all("moment" in item for item in open_brief.values()))

    def test_directions_stay_inside_the_subjects_world(self):
        values = " ".join(value for axis in DIRECTION_AXES.values() for value in axis).casefold()
        for genre_shift in ("fantastical", "neon", "city street"):
            self.assertNotIn(genre_shift, values)

    def test_guided_items_get_no_moment_and_the_prompt_ranks_directions_last(self):
        data = valid_draft(amount=2, source_mode="guided", inputs="punches a bag\nskips rope",
            _confirmed_intent=dataset_understanding_fixture())
        self.assertTrue(all("moment" not in item for item in creative_directions(data, [1, 2]).values()))
        context = json.loads(ideas_instruction(self.data, dataset_assignments(self.data)).user_message)
        self.assertEqual([row["creative_direction"] for row in context["assignments"]],
                         list(creative_directions(self.data, [1, 2]).values()))
        self.assertIn("WHAT MAKES A STRONG IDEA", IDEAS_SYSTEM)
        self.assertIn("drop only the conflicting part of a direction, never the requirement", IDEAS_SYSTEM)

    def run_ideas(self, rows, **options):
        self.session.generate.return_value = json.dumps(rows)
        return self.service.run(session=self.session, data=self.data, assignments=dataset_assignments(self.data),
            progress=lambda _message: None, **options)

    def festival_ideas(self, amount):
        actions = ["raises a tent pole", "ties a banner to a railing", "unloads chairs from a cart",
            "unrolls a tablecloth", "places flowers in a vase", "hands a ticket to a visitor",
            "guides a delivery van", "carries a crate of cups", "tests a microphone",
            "adjusts a stage light", "marks a queue lane with tape", "arranges books on a stall",
            "fills a water dispenser", "stacks clean trays", "sorts recycling",
            "folds a program leaflet", "demonstrates a paper craft", "serves soup into a bowl",
            "collects used dishes", "fastens a cable cover", "helps a visitor read a map",
            "weighs produce at a stall", "secures a balloon string", "sweeps the entrance",
            "rolls up a finished display"]
        return [dataset_idea_fixture(index, idea=f"A festival volunteer {action}.",
            placement="Volunteer beside the relevant festival station.", visibility="Hands and task remain readable.",
            camera="Eye-level three-quarter view.", framing="Medium-full view.", context="Community festival grounds.")
            for index, action in enumerate(actions[:amount], 1)]

    def test_ideas_request_minified_generation_and_compact_input_without_changing_contract(self):
        self.data.update(amount=25, subject='Volunteers hold signs reading "Bienvenue, caf\u00e9!".')
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        rules = " ".join(instruction.system_message.split())
        self.assertTrue("Return ONLY a minified JSON array on a single line" in rules)
        self.assertTrue("No indentation or optional whitespace outside string values" in rules)
        self.assertTrue("Formatting compaction must not omit facts or change qualifiers" in rules)
        self.assertTrue("Resolve generated repeats within this same call" in rules)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["source"]["subject"], self.data["subject"])
        self.assertEqual(instruction.user_message, json.dumps(context, ensure_ascii=False, separators=(",", ":")))
        self.assertEqual(context["output_contract"], {"record_count": 25, "indexes": list(range(1, 26))})
        self.assertEqual(instruction.json_schema["maxItems"], 25)
        self.assertEqual(instruction.hard_max_tokens, 13312)
        self.assertEqual((instruction.temperature, instruction.top_p), (.7, .92))

    def test_distinct_large_batches_accept_minified_and_pretty_json_without_additional_calls(self):
        for amount in (20, 21, 25):
            self.data.update(amount=amount, subject="Community volunteers preparing and running a neighborhood festival")
            rows = self.festival_ideas(amount)
            for formatting in ({"indent": 2}, {"separators": (",", ":")}):
                with self.subTest(amount=amount, formatting=formatting):
                    self.session.reset_mock()
                    self.session.generate.return_value = json.dumps(rows, ensure_ascii=False, **formatting)
                    result = self.service.run(session=self.session, data=self.data,
                        assignments=dataset_assignments(self.data), progress=lambda _message: None)
                    self.assertEqual(result, rows)
                    self.session.generate.assert_called_once()

    def test_large_batch_duplicate_error_identifies_indexes_without_echoing_content_or_retrying(self):
        self.data.update(amount=25)
        rows = self.festival_ideas(25)
        rows[20]["idea"] = rows[4]["idea"].upper()
        rows[24]["idea"] = rows[4]["idea"]
        with self.assertRaisesRegex(BackendGenerationError, "Duplicate idea indexes: 5, 21, 25") as caught:
            self.run_ideas(rows)
        self.assertIn("same core event", str(caught.exception))
        self.assertNotIn(rows[4]["idea"], str(caught.exception))
        self.assertIn("No automatic retry", str(caught.exception))
        self.session.generate.assert_called_once()

    def test_replacement_reports_only_duplicates_involving_the_requested_index(self):
        self.data.update(amount=25)
        existing = self.festival_ideas(25)
        existing[1]["idea"] = existing[0]["idea"]
        replacement = {**existing[20], "idea": existing[4]["idea"]}
        with self.assertRaisesRegex(BackendGenerationError, "Duplicate idea indexes: 5, 21\\.") as caught:
            self.run_ideas([replacement], indexes=[21], existing=existing)
        self.assertNotIn("indexes: 1,", str(caught.exception))
        self.session.generate.assert_called_once()

    def test_large_guided_repeats_remain_valid_when_the_user_requires_the_same_event(self):
        self.data.update(amount=25, source_mode="guided", inputs="A volunteer hands a ticket to a visitor.")
        first = self.festival_ideas(1)[0]
        first["idea"] = "A volunteer hands a ticket to a visitor."
        rows = [{**first, "index": index} for index in range(1, 26)]
        self.assertEqual(self.run_ideas(rows), rows)
        self.session.generate.assert_called_once()

    def test_partial_guided_repeats_remain_valid_without_failed_slots(self):
        self.data.update(amount=25, source_mode="guided", inputs="A volunteer hands a ticket to a visitor.")
        first = self.festival_ideas(1)[0]
        first["idea"] = "A volunteer hands a ticket to a visitor."
        rows = [{**first, "index": index} for index in range(1, 26)]
        result = self.run_ideas(rows, allow_partial=True)
        self.assertEqual(result, rows)
        self.session.generate.assert_called_once()

    def test_similar_large_batch_events_with_reversed_roles_are_not_exact_duplicates(self):
        self.data.update(amount=25)
        rows = self.festival_ideas(25)
        rows[0]["idea"] = "Volunteer A hands flowers to volunteer B."
        rows[1]["idea"] = "Volunteer B hands flowers to volunteer A."
        self.assertEqual(self.run_ideas(rows), rows)
        self.session.generate.assert_called_once()

    def test_one_call_returns_only_six_short_descriptions_per_requested_index(self):
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        before = deepcopy(self.data)
        self.assertEqual(self.run_ideas(expected), expected)
        self.session.generate.assert_called_once()
        instruction = self.session.generate.call_args.args[0]
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"], self.data["_confirmed_intent"])
        self.assertFalse(instruction.unlimited_tokens)
        self.assertEqual(self.data, before)

    def test_idea_choices_are_suggestions_under_the_approved_contract(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "Cup base touching the table must be visible."}],
            soft=[{"scope": "all_outputs", "text": "Close camera."}],
            free=[{"scope": "all_outputs", "text": "Exact angle."}])
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        self.assertIn("creative suggestions, not immutable requirements", instruction.system_message)
        self.assertIn("SCENE may", instruction.system_message)
        self.assertIn("adjust any generated choice that conflicts with HARD", instruction.system_message)
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"], self.data["_confirmed_intent"])

    def test_fight_variations_must_keep_visible_combat_not_hiding_alone(self):
        self.data.update(subject="A duck fighting a Stegosaurus.",
            _confirmed_intent=dataset_understanding_fixture(hard=[
                {"scope": "all_outputs", "text": "The duck and dinosaur must be depicted in a fighting interaction with visible combat cues."}]))
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        self.assertIn("Every proposed moment must visibly show the required interaction", instruction.system_message)
        self.assertIn("hiding or peeking alone does not satisfy fighting", instruction.system_message)
        self.assertIn("retreating while the dinosaur attacks", instruction.system_message)
        self.assertNotIn("both subjects facing off before the next attack", instruction.system_message)
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"]["hard"],
            self.data["_confirmed_intent"]["hard"])

    def test_missing_understanding_or_unanswered_clarifications_never_call_model(self):
        for brief in (None, dataset_understanding_fixture(clarifications=["Which subject?"])):
            with self.subTest(brief=brief):
                self.data["_confirmed_intent"] = brief
                with self.assertRaises(ValueError):
                    self.run_ideas([dataset_idea_fixture()])
        self.session.generate.assert_not_called()

    def test_all_outputs_roles_require_actions_without_borrowing_another_roles_equipment(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(hard=[
            {"scope": "all_outputs", "text": "The safety coordinator manages the crash mat."},
            {"scope": "all_outputs", "text": "The lighting assistant controls the reflector."}])
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        rules = " ".join(instruction.system_message.split())
        self.assertIn("each all_outputs role obligation must have a compatible action in that frozen moment", rules)
        self.assertIn("Merely including or naming the character does not satisfy a required responsibility", rules)
        self.assertIn("Do not assign another role's tools, equipment or responsibility just to keep everyone busy", rules)
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"]["hard"],
            self.data["_confirmed_intent"]["hard"])

    def test_replacement_ideas_preserve_shared_batch_choices_from_existing_ideas(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(
            hard=[{"scope": "dataset", "text": "Use one shared stunt setup throughout the batch."}],
            free=[{"scope": "dataset", "text": "Choose the shared setup once."}])
        existing = [dataset_idea_fixture(1, context="A cable-assisted leap onto a single crash mat.")]
        before = deepcopy(existing)
        instruction = ideas_instruction(self.data, dataset_assignments(self.data), indexes=[2], existing=existing)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Preserve any dataset-shared choice already established for the batch", rules)
        self.assertIn("Vary the stage or interaction around that shared choice rather than replacing the choice", rules)
        self.assertIn("choose it once for the batch and keep it consistent across all proposed ideas, not independently per image", rules)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["existing_ideas"], before)
        self.assertEqual(context["confirmed_intent"], self.data["_confirmed_intent"])
        self.assertEqual([row["index"] for row in context["assignments"]], [2])
        self.assertEqual(existing, before)

    def test_ideas_do_not_deliberately_expose_optional_identity_traits(self):
        self.data["_confirmed_intent"] = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "The performer has a back tattoo; visibility is optional."}],
            fixed=[{"scope": "all_outputs", "text": "The performer's back tattoo."}])
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Do not deliberately expose identity traits whose visibility is optional", rules)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["confirmed_intent"]["hard"], self.data["_confirmed_intent"]["hard"])
        self.assertEqual(context["confirmed_intent"]["visible_evidence"], [])

    def test_supplied_character_groups_keep_trait_ownership_not_forced_visibility(self):
        self.data.update(trigger_type="Multiple characters", trigger="Mira, blue hair, bat wings, Hana, blonde hair, crystal wings")
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Supplied character groups in HARD retain their own attributes", rules)
        self.assertIn("A trait omitted from a shorter paraphrase is not permission to transfer it", rules)
        self.assertIn("use only traits belonging to that subject", rules)
        self.assertIn("Ownership does not require exposure", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["trigger"], self.data["trigger"])

    def test_guided_scopes_follow_original_nonempty_lines_when_assignments_cycle(self):
        self.data.update(amount=4, source_mode="guided", inputs="A glove punch\n\nA defensive stance",
            _confirmed_intent=dataset_understanding_fixture(rules=[{"scope": "guided:2", "text": "At the ropes"}]),
            scene_plan=[{"idea": "Old scene must not become a source rule"}], results=[{"prompt": "Old output"}])
        instruction = ideas_instruction(self.data, dataset_assignments(self.data))
        context = json.loads(instruction.user_message)
        self.assertEqual([row["guided_scope"] for row in context["assignments"]],
            ["guided:1", "guided:2", "guided:1", "guided:2"])
        self.assertNotIn("scene_plan", context["source"])
        self.assertNotIn("results", context["source"])
        self.assertNotIn("Old scene", instruction.user_message)
        self.assertEqual(context["confirmed_intent"]["rules"], [{"scope": "guided:2", "text": "At the ropes"}])

    def test_regeneration_requests_only_selected_index_and_preserves_siblings_in_context(self):
        existing = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        before = deepcopy(existing)
        replacement = dataset_idea_fixture(2, idea="A boxer slips a punch and counters.")
        self.assertEqual(self.run_ideas([replacement], indexes=[2], existing=existing), [replacement])
        context = json.loads(self.session.generate.call_args.args[0].user_message)
        self.assertEqual([row["index"] for row in context["assignments"]], [2])
        self.assertEqual(context["existing_ideas"], before)
        self.assertEqual(existing, before)

    def test_requested_indexes_reject_empty_duplicates_missing_assignments_and_nonintegers(self):
        for indexes in ([], [1, 1], [0], [3], [True], ["1"], [[]]):
            with self.subTest(indexes=indexes), self.assertRaises(ValueError):
                ideas_instruction(self.data, dataset_assignments(self.data), indexes=indexes)

    def test_one_assignment_still_requests_an_outer_array_not_a_bare_object(self):
        instruction = ideas_instruction(self.data, dataset_assignments(self.data), indexes=[1])
        self.assertIn("Even for a single requested assignment", instruction.system_message)
        self.assertIn("never return a bare object", instruction.system_message)
        self.assertEqual(len(json.loads(instruction.user_message)["assignments"]), 1)
        with self.assertRaises(ValueError):
            validate_ideas(json.dumps(dataset_idea_fixture()), [1])

    def test_ideas_schema_binds_exact_count_order_indexes_and_six_bounded_fields(self):
        for amount, indexes in ((1, None), (2, None), (25, None), (3, [3, 1]), (3, [2])):
            with self.subTest(amount=amount, indexes=indexes):
                data = {**self.data, "amount": amount}
                instruction = ideas_instruction(data, dataset_assignments(data), indexes=indexes)
                expected = list(range(1, amount + 1)) if indexes is None else indexes
                self.assertTrue(instruction.json_output)
                schema = instruction.json_schema
                self.assertEqual(schema["type"], "array")
                self.assertEqual(schema["minItems"], len(expected))
                self.assertEqual(schema["maxItems"], len(expected))
                self.assertNotIn("items", schema)
                self.assertEqual(len(schema["prefixItems"]), len(expected))
                for record, index in zip(schema["prefixItems"], expected):
                    self.assertEqual(record["type"], "object")
                    self.assertIs(record["additionalProperties"], False)
                    self.assertEqual(set(record["required"]), {"index", *IDEA_FIELDS})
                    self.assertEqual(set(record["properties"]), {"index", *IDEA_FIELDS})
                    self.assertEqual(record["properties"]["index"], {"type": "integer", "const": index})
                    for field in IDEA_FIELDS:
                        self.assertEqual(record["properties"][field],
                            {"type": "string", "minLength": 1, "maxLength": 600})
                context = json.loads(instruction.user_message)
                self.assertEqual(context["output_contract"], {"record_count": len(expected), "indexes": expected})
                self.assertEqual([row["index"] for row in context["assignments"]], expected)
                self.assertEqual(context["source"]["amount"], amount)

    def test_owned_llama_receives_ideas_schema_in_its_existing_model_call(self):
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(expected)}}]}).encode()
        for owned in (True, False):
            with self.subTest(owned_llama=owned):
                backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1",
                    "model": "synthetic", "_is_llama_cpp": owned})
                with patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send, \
                        patch("goated_prompter.backends.openai_compatible.log_request"), \
                        patch("goated_prompter.backends.openai_compatible.log_response"):
                    rows = self.service.run(session=backend, data=self.data, assignments=dataset_assignments(self.data),
                        progress=lambda _message: None)
                send.assert_called_once()
                payload = json.loads(send.call_args.args[0].data)
                if owned:
                    self.assertEqual(payload.get("response_format"), {"type": "json_schema", "json_schema": {
                        "name": "response", "strict": True,
                        "schema": ideas_instruction(self.data, dataset_assignments(self.data)).json_schema}})
                else:
                    self.assertNotIn("response_format", payload)
                self.assertEqual(payload["max_tokens"], 1536)
                self.assertEqual(rows, expected)

    def test_ideas_schema_does_not_trigger_llama_boolean_items_conversion_error(self):
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(expected)}}]}).encode()

        def convert_schema(request, **_options):
            schema = json.loads(request.data)["response_format"]["json_schema"]["schema"]
            if "items" in schema and not isinstance(schema["items"], dict):
                body = json.dumps({"error": {"message": "JSON schema error at #/items: schema must be an object"}}).encode()
                raise HTTPError(request.full_url, 500, "Internal Server Error", {}, BytesIO(body))
            return response

        backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1",
            "model": "synthetic", "_is_llama_cpp": True})
        with patch("goated_prompter.backends.openai_compatible.urlopen", side_effect=convert_schema) as send, \
                patch("goated_prompter.backends.openai_compatible.log_request"), \
                patch("goated_prompter.backends.openai_compatible.log_response"):
            rows = self.service.run(session=backend, data=self.data, assignments=dataset_assignments(self.data),
                progress=lambda _message: None)
        send.assert_called_once()
        self.assertEqual(rows, expected)

    def test_ideas_count_error_reports_expected_and_received_without_response_content(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                self.session.reset_mock()
                rows = [dataset_idea_fixture(index, idea="Synthetic content must not be included in the error.")
                    for index in range(1, count + 1)]
                with self.assertRaisesRegex(BackendGenerationError,
                        rf"Ideas returned {count} records; expected exactly 2 for requested indexes \[1, 2\]") as caught:
                    self.run_ideas(rows)
                self.assertNotIn("Synthetic content", str(caught.exception))
                self.assertIn("One format correction was tried", str(caught.exception))
                self.assertEqual(self.session.generate.call_count, 2)

    def test_ideas_wrong_container_is_distinct_from_a_count_mismatch(self):
        rows = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        for payload in ({"ideas": rows}, rows[0], None, "Synthetic content"):
            with self.subTest(container=type(payload).__name__):
                self.session.reset_mock()
                with self.assertRaisesRegex(BackendGenerationError, "Ideas must return a JSON array of 2 records") as caught:
                    self.run_ideas(payload)
                self.assertNotIn("Synthetic content", str(caught.exception))
                self.assertEqual(self.session.generate.call_count, 2)

    def test_camera_and_context_changes_do_not_make_identical_events_distinct(self):
        first = dataset_idea_fixture(1)
        second = dataset_idea_fixture(2, idea=first["idea"], camera="Side view", context="Different arena")
        with self.assertRaisesRegex(BackendGenerationError, "same core event"):
            self.run_ideas([first, second])
        self.session.generate.assert_called_once()

    def test_regeneration_cannot_return_an_unchanged_idea_record(self):
        original = dataset_idea_fixture(2)
        with self.assertRaisesRegex(BackendGenerationError, "unchanged idea"):
            self.run_ideas([original], indexes=[2], existing=[dataset_idea_fixture(1), original])
        self.session.generate.assert_called_once()

    def test_authoritative_guided_repeats_do_not_force_a_different_action(self):
        self.data.update(source_mode="guided", inputs="A boxer punching the bag.")
        first = dataset_idea_fixture(1)
        second = {**first, "index": 2}
        self.assertEqual(self.run_ideas([first, second]), [first, second])

    def test_invalid_model_output_gets_one_format_correction_then_stops(self):
        self.session.generate.return_value = "not JSON"
        with self.assertRaisesRegex(BackendGenerationError, "malformed at character 0 .*One format correction was tried"):
            self.service.run(session=self.session, data=self.data, assignments=dataset_assignments(self.data),
                progress=lambda _message: None)
        self.assertEqual(self.session.generate.call_count, 2)

    def test_malformed_json_recovers_with_one_low_temperature_correction(self):
        # Reported failure: the engine intermittently returned a broken array ("Expecting ':' delimiter").
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        broken = json.dumps(expected)[:120] + '"framing" "Full body."}]'
        self.session.generate.side_effect = [broken, json.dumps(expected)]
        messages = []
        result = self.service.run(session=self.session, data=self.data, assignments=dataset_assignments(self.data),
            progress=messages.append)
        self.assertEqual(result, expected)
        first, retry = [call.args[0] for call in self.session.generate.call_args_list]
        self.assertEqual((retry.temperature, retry.top_p, retry.diagnostic_stage), (.25, .85, "dataset:ideas:format_retry"))
        self.assertEqual(retry.user_message, first.user_message)
        self.assertIn("FORMAT CORRECTION", retry.system_message)
        self.assertIn("malformed at character", retry.system_message)
        self.assertTrue(any("corrected response" in message for message in messages))

    def test_complete_json_fence_is_accepted_in_one_idea_call(self):
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        for label in ("", "json", "JSON"):
            with self.subTest(label=label):
                self.session.reset_mock()
                self.session.generate.return_value = f"```{label}\n{json.dumps(expected)}\n```"
                rows = self.service.run(session=self.session, data=self.data,
                    assignments=dataset_assignments(self.data), progress=lambda _message: None)
                self.assertEqual(rows, expected)
                self.session.generate.assert_called_once()

    def test_json_fences_do_not_hide_prose_multiple_values_or_invalid_ideas(self):
        good = json.dumps([dataset_idea_fixture()])
        duplicate = good.replace('"camera":', '"camera":"Front", "camera":')
        invalid = [f"```json\n{good}", f"```text\n{good}\n```",
            f"Explanation\n```json\n{good}\n```", f"```json\n{good}\n```\nExplanation",
            f"```json\n{good}\n{good}\n```", f"```json\n{duplicate}\n```",
            f"```json\n{json.dumps([{**dataset_idea_fixture(), 'index': True}])}\n```"]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_ideas(raw, [1])

    def test_backend_failure_is_not_retried(self):
        self.session.generate.side_effect = BackendGenerationError("Synthetic engine failure")
        with self.assertRaisesRegex(BackendGenerationError, "Synthetic engine failure"):
            self.run_ideas([dataset_idea_fixture(1), dataset_idea_fixture(2)])
        self.session.generate.assert_called_once()

    def test_parser_rejects_extra_fields_bad_indexes_missing_values_and_unbounded_text(self):
        good = dataset_idea_fixture()
        invalid = ["not JSON", '{}', '[]', json.dumps([good, good]),
            json.dumps([{**good, "index": True}]), json.dumps([{**good, "index": 2}]),
            json.dumps([{**good, "geometry": {}}]), json.dumps([{key: value for key, value in good.items() if key != "camera"}]),
            '{"index":1,"index":1}', json.dumps([{**good, "idea": "```"}])]
        for field in IDEA_FIELDS:
            invalid.extend(json.dumps([{**good, field: value}]) for value in (None, [], {}, " ", "x" * 601))
        invalid.append(json.dumps([good]).replace('"camera":', '"camera":"Front", "camera":'))
        for raw in invalid:
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                validate_ideas(raw, [1])

    def test_parser_accepts_short_descriptions_and_normalizes_whitespace_without_padding(self):
        good = dataset_idea_fixture(idea="  Boxer\n punches.  ")
        result = validate_ideas(json.dumps([good]), [1])[0]
        self.assertEqual(result["idea"], "Boxer punches.")
        self.assertEqual(set(result), {"index", *IDEA_FIELDS})

    def test_saved_plan_roundtrip_keeps_compact_details_but_rejects_partial_or_invalid_details(self):
        row = {**dataset_idea_fixture(), "input": "", "scene": "A boxer at the bag.", "self_check": "PASS"}
        self.assertEqual(validate_saved_scene_plan([row]), [row])
        for changes in ({"visibility": None}, {"camera": "x" * 601}, {"context": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_saved_scene_plan([{**row, **changes}])
        with self.assertRaises(ValueError):
            validate_saved_scene_plan([{key: value for key, value in row.items() if key != "camera"}])

    def test_cancelled_generation_cannot_publish_a_late_idea_response(self):
        checkpoint = Mock(side_effect=[None, RuntimeError("Cancelled")])
        self.service = DatasetIdeasService(checkpoint)
        with self.assertRaisesRegex(RuntimeError, "Cancelled"):
            self.run_ideas([dataset_idea_fixture(1), dataset_idea_fixture(2)])
        self.session.generate.assert_called_once()
