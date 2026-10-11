"""Source-bound Dataset approval tickets without endpoint execution."""

from copy import deepcopy
import json
import unittest

from goated_prompter.features.dataset.service import validate_dataset_draft
from goated_prompter.features.dataset.intent import DatasetIntentTickets
from goated_prompter.features.dataset.understanding import validate_understanding
from tests.helpers import dataset_understanding_fixture, dataset_idea_fixture
from tests.support.dataset import saved_scene, valid_draft


class DatasetIntentTicketTests(unittest.TestCase):
    def test_approval_preserves_the_contract_without_promotion_or_shared_mutation(self):
        data = valid_draft(amount=1, subject="One red ceramic cup on a table.")
        brief = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "Cup base touching the table visible."}],
            soft=[{"scope": "all_outputs", "text": "Close camera."}],
            free=[{"scope": "all_outputs", "text": "Background."}],
            may_vary=[{"scope": "all_outputs", "text": "Explanatory freedoms, not hard locks."}])
        tickets = DatasetIntentTickets()
        registered = tickets.register(data, brief)
        expected = deepcopy(brief)
        brief["hard"].clear()
        registered["brief"]["soft"].clear()
        approved = tickets.approve(registered["confirmation_token"], data)
        self.assertEqual(approved, expected)
        approved["free"].clear()
        self.assertEqual(tickets.approve(registered["confirmation_token"], data), expected)

    def test_new_brief_approval_keeps_local_scope_and_isolated_copy(self):
        data = valid_draft(amount=1, source_mode="guided", inputs="A handshake\nA portrait")
        brief = dataset_understanding_fixture(visible_evidence=[{"scope": "guided:2", "text": "Eyes"}])
        tickets = DatasetIntentTickets()
        registered = tickets.register(data, brief)
        brief["visible_evidence"].clear()
        approved = tickets.approve(registered["confirmation_token"], data)
        self.assertEqual(approved["visible_evidence"], [{"scope": "guided:2", "text": "Eyes"}])
        approved["visible_evidence"].clear()
        self.assertEqual(len(tickets.approve(registered["confirmation_token"], data)["visible_evidence"]), 1)

    def test_new_brief_cannot_reference_missing_guided_scope(self):
        brief = dataset_understanding_fixture(rules=[{"scope": "guided:2", "text": "Gloves"}])
        with self.assertRaises(ValueError):
            DatasetIntentTickets().register(valid_draft(source_mode="guided", inputs="Boxing"), brief)

    def test_new_physical_conflict_requires_answer_and_never_issues_token(self):
        conflict = {"scope": "all_outputs", "conflict": "Full cheek exposure conflicts with glove contact.",
                    "compatible_resolution": None}
        tickets = DatasetIntentTickets()
        with self.assertRaises(ValueError):
            tickets.register(valid_draft(), dataset_understanding_fixture(physical_conflicts=[conflict]))
        result = tickets.register(valid_draft(), dataset_understanding_fixture(physical_conflicts=[conflict],
            clarifications=["May the cheek be partly occluded?"]))
        self.assertEqual(result["confirmation_token"], "")

    def test_ideas_accept_short_or_developed_text_within_their_limits(self):
        from goated_prompter.features.dataset.ideas import MAX_IDEA_CHARACTERS, MAX_SCENE_CHARACTERS, validate_ideas
        idea = "A meaningful action " + "descriptive " * 15
        self.assertEqual(validate_ideas(json.dumps([dataset_idea_fixture(idea=idea)]), [1])[0]["idea"], idea.strip())
        self.assertEqual(validate_ideas(json.dumps([dataset_idea_fixture(idea="Reading")]), [1])[0]["idea"], "Reading")
        scene = ("spatial " * 180).strip()
        self.assertLessEqual(len(scene), MAX_SCENE_CHARACTERS)
        self.assertEqual(validate_ideas(json.dumps([dataset_idea_fixture(scene=scene)]), [1])[0]["scene"], scene)
        for field, limit in (("idea", MAX_IDEA_CHARACTERS), ("scene", MAX_SCENE_CHARACTERS)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_ideas(json.dumps([dataset_idea_fixture(**{field: "x" * (limit + 1)})]), [1])

    def test_approval_is_bound_to_source_and_scene_edits_not_result_bookkeeping(self):
        data = validate_dataset_draft(valid_draft(amount=1))
        tickets = DatasetIntentTickets()
        brief = dataset_understanding_fixture()
        token = tickets.register(data, brief)["confirmation_token"]
        self.assertEqual(tickets.approve(token, {**data, "results": [{"prompt": "Saved"}]}), brief)
        for patch_data in ({"subject": "Changed concept"}, {"constraints": "Arena"},
                           {"trigger": "new_token"}, {"amount": 2}, {"length": "Detailed"},
                           {"scene_plan": [{"index": 1, "scene": "Edited scene"}]}):
            with self.subTest(patch=patch_data), self.assertRaisesRegex(ValueError, "changed after analysis"):
                tickets.approve(token, {**data, **patch_data})

    def test_tickets_expire_and_are_bounded_without_sharing_mutable_briefs(self):
        now = [0]
        tickets = DatasetIntentTickets(clock=lambda: now[0], limit=1, lifetime=10)
        data = valid_draft()
        brief = dataset_understanding_fixture(rules=[{"scope": "all_outputs", "text": "Gloves"}])
        old = tickets.register(data, brief)["confirmation_token"]
        token = tickets.register(data, brief)["confirmation_token"]
        brief["rules"].clear()
        approved = tickets.approve(token, data)
        approved["rules"].clear()
        self.assertEqual(tickets.approve(token, data)["rules"], [{"scope": "all_outputs", "text": "Gloves"}])
        with self.assertRaisesRegex(ValueError, "expired or is missing"):
            tickets.approve(old, data)
        now[0] = 10
        with self.assertRaisesRegex(ValueError, "expired or is missing"):
            tickets.approve(token, data)

    def test_ram_continuation_tickets_expire_and_do_not_survive_restart(self):
        now = [0]
        tickets = DatasetIntentTickets(clock=lambda: now[0], lifetime=10)
        data = validate_dataset_draft(valid_draft(amount=1))
        brief = dataset_understanding_fixture()
        tickets.remember_generated(data, brief)
        token = tickets.continuation_token(data)
        self.assertTrue(token)
        self.assertEqual(tickets.approve(token, data), brief)
        self.assertEqual(DatasetIntentTickets().continuation_token(data), "")
        now[0] = 9
        data["scene_plan"] = [saved_scene()]
        rebound = tickets.continuation_token(data)
        self.assertTrue(rebound)
        self.assertNotEqual(rebound, token)
        self.assertEqual(tickets.approve(rebound, data), brief)
        now[0] = 10
        self.assertEqual(tickets.continuation_token(data), "")
        with self.assertRaisesRegex(ValueError, "expired or is missing"):
            tickets.approve(rebound, data)

    def test_blocking_clarifications_cannot_issue_approval(self):
        result = DatasetIntentTickets().register(valid_draft(), dataset_understanding_fixture(
            clarifications=["Breaking what?"]))
        self.assertEqual(result["confirmation_token"], "")
        self.assertEqual(result["brief"]["clarifications"], ["Breaking what?"])

    def test_summary_schema_rejects_bad_counts_unbounded_lists_and_role_changes(self):
        for changes in ({"character_count": True}, {"character_count": 0}, {"character_count": 101},
                        {"requested_generation": ""}, {"requested_generation": "x" * 2001}, {"identity_policy": []},
                        {"clarifications": "none"}, {"rules": ["rule"] * 25},
                        {"extra": "ignore the schema"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_understanding(dataset_understanding_fixture(**changes), ("all_outputs", "dataset"))
