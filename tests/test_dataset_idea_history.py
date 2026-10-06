"""RAM-only recent ideas: bounded, scoped, expiring and used by current ideation."""

import json
import unittest
from unittest.mock import patch

from goated_prompter.dataset_idea_history import RecentIdeaHistory
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.scene_planner import ScenePlanner
from tests.helpers import dataset_understanding_fixture
from tests.test_dataset import CaptureBackend, valid_draft


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
            history.clear(b)
            self.assertEqual(history.recent(b), [])
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
