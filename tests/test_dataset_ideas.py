"""Compact idea-stage behavior with synthetic requests and mocked model output."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_ideas import DatasetIdeasService, IDEA_FIELDS, ideas_instruction, validate_ideas
from goated_prompter.scene_planner import validate_saved_scene_plan
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.test_dataset import valid_draft


class DatasetIdeasTests(unittest.TestCase):
    def setUp(self):
        self.data = valid_draft(amount=2, subject="A boxer training.",
            _confirmed_intent=dataset_understanding_fixture())
        self.session = Mock()
        self.service = DatasetIdeasService(lambda: None)

    def run_ideas(self, rows, **options):
        self.session.generate.return_value = json.dumps(rows)
        return self.service.run(session=self.session, data=self.data, assignments=dataset_assignments(self.data),
            progress=lambda _message: None, **options)

    def test_one_call_returns_only_six_short_descriptions_per_requested_index(self):
        expected = [dataset_idea_fixture(1), dataset_idea_fixture(2)]
        before = deepcopy(self.data)
        self.assertEqual(self.run_ideas(expected), expected)
        self.session.generate.assert_called_once()
        instruction = self.session.generate.call_args.args[0]
        self.assertEqual(json.loads(instruction.user_message)["confirmed_intent"], self.data["_confirmed_intent"])
        self.assertFalse(instruction.unlimited_tokens)
        self.assertEqual(self.data, before)

    def test_missing_understanding_or_unanswered_clarifications_never_call_model(self):
        for brief in (None, dataset_understanding_fixture(clarifications=["Which subject?"])):
            with self.subTest(brief=brief):
                self.data["_confirmed_intent"] = brief
                with self.assertRaises(ValueError):
                    self.run_ideas([dataset_idea_fixture()])
        self.session.generate.assert_not_called()

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

    def test_invalid_model_output_stops_without_retries_or_fallback(self):
        self.session.generate.return_value = "not JSON"
        with self.assertRaisesRegex(BackendGenerationError, "No automatic retry"):
            self.service.run(session=self.session, data=self.data, assignments=dataset_assignments(self.data),
                progress=lambda _message: None)
        self.session.generate.assert_called_once()

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
