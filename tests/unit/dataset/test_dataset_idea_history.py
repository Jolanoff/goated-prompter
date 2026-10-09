"""RAM-only recent ideas: bounded, scoped, expiring and used by current ideation."""

import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.dataset_idea_history import RecentIdeaHistory
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_ideas import DatasetIdeasService
from goated_prompter.scene_planner import ScenePlanner
from tests.helpers import dataset_idea_fixture, dataset_understanding_fixture
from tests.support.dataset import CaptureBackend, valid_draft


class DatasetIdeaHistoryTests(unittest.TestCase):
    def test_deduplication_bounds_and_failed_ideas(self):
        history, data = RecentIdeaHistory(limit=2), valid_draft()
        history.remember(data, [{"idea": " First   event "}, {"idea": "first event"},
            {"idea": "Failed event", "idea_status": "failed"}, {"idea": "Second event"}, {"idea": "Third event"}])
        self.assertEqual(history.recent(data), ["Second event", "Third event"])
        copy = history.recent(data)
        copy.clear()
        self.assertEqual(history.recent(data), ["Second event", "Third event"])

    def test_current_600_character_ideas_are_not_truncated_to_legacy_limit(self):
        history, data = RecentIdeaHistory(), valid_draft()
        idea = "A specific action " + "detail " * 70
        history.remember(data, [{"idea": idea}])
        self.assertEqual(history.recent(data), [idea.strip()])

    def test_scope_expiry_and_concept_eviction(self):
        history = RecentIdeaHistory(concepts=2, ttl=10)
        a, b, c = [valid_draft(subject=subject) for subject in ("One", "Two", "Three")]
        with patch("goated_prompter.dataset_idea_history.time.monotonic", return_value=0):
            for data in (a, b, c):
                history.remember(data, [{"idea": data["subject"]}])
            self.assertEqual(history.recent(a), [])
            self.assertEqual(history.recent(b), ["Two"])
            self.assertEqual(history.recent(c), ["Three"])
        with patch("goated_prompter.dataset_idea_history.time.monotonic", return_value=11):
            self.assertEqual(history.recent(c), [])

    def test_current_ideas_receive_history_and_remember_only_accepted_output(self):
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        history, session = RecentIdeaHistory(), CaptureBackend()
        history.remember(data, [{"idea": "A previous event"}])
        rows = ScenePlanner(lambda: None, history).plan_ideas(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        context = json.loads(session.calls[0].user_message)
        self.assertEqual(context["recently_used_ideas"], ["A previous event"])
        self.assertEqual(history.recent(data), ["A previous event", rows[0]["idea"]])

    def test_recent_repeat_is_rejected_without_retry_or_history_update(self):
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        history = RecentIdeaHistory()
        previous = dataset_idea_fixture()
        history.remember(data, [previous])
        session = Mock()
        session.generate.return_value = json.dumps([{**previous, "idea": previous["idea"].upper(),
            "camera": "A new camera angle.", "context": "A different location."}])
        with self.assertRaisesRegex(BackendGenerationError, "recently generated event") as caught:
            ScenePlanner(lambda: None, history).plan_ideas(session=session, data=data,
                assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertNotIn(previous["idea"], str(caught.exception))
        session.generate.assert_called_once()
        self.assertEqual(history.recent(data), [previous["idea"]])

    def test_partial_ideas_keep_fresh_siblings_and_remember_only_accepted_events(self):
        data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture())
        history, session = RecentIdeaHistory(), Mock()
        previous = dataset_idea_fixture()
        fresh = dataset_idea_fixture(2, idea="A boxer adjusts a training bag chain.")
        history.remember(data, [previous])
        session.generate.return_value = json.dumps([previous, fresh])
        rows = DatasetIdeasService(lambda: None, history).run(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None, allow_partial=True)
        self.assertEqual(rows[0]["idea_status"], "failed")
        self.assertEqual(rows[0]["failure_stage"], "idea")
        self.assertEqual(rows[1], fresh)
        self.assertEqual(history.recent(data), [previous["idea"], fresh["idea"]])
        session.generate.assert_called_once()

    def test_explicit_guided_event_can_repeat_across_runs(self):
        previous = dataset_idea_fixture()
        data = valid_draft(amount=1, source_mode="guided", inputs=previous["idea"],
            _confirmed_intent=dataset_understanding_fixture())
        history, session = RecentIdeaHistory(), Mock()
        history.remember(data, [previous])
        session.generate.return_value = json.dumps([previous])
        rows = DatasetIdeasService(lambda: None, history).run(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(rows, [previous])
        self.assertEqual(history.recent(data), [previous["idea"]])

    def test_scene_composition_follows_accepted_idea_without_consulting_history(self):
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        history, session = RecentIdeaHistory(), CaptureBackend()
        idea = dataset_idea_fixture()
        history.remember(data, [idea])
        with patch.object(history, "recent", side_effect=AssertionError("Only Ideas reads recent history")), \
                patch.object(history, "remember", side_effect=AssertionError("Only Ideas writes recent history")):
            rows = ScenePlanner(lambda: None, history).compose(session=session, data=data,
                assignments=dataset_assignments(data), ideas=[idea], progress=lambda _: None)
        self.assertEqual(rows[0]["scene"], idea["idea"])
        context = json.loads(session.calls[0].user_message)
        self.assertNotIn("recently_used_ideas", context)
        self.assertEqual(len(session.calls), 1)
