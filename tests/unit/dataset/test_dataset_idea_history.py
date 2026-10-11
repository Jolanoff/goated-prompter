"""Recent ideas: text bounded in RAM, private fingerprints across restarts, used by current ideation."""

import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.features.dataset.idea_history import RecentIdeaHistory
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import MAX_IDEA_CHARACTERS, DatasetIdeasService
from goated_prompter.features.dataset.plan import ScenePlanner
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

    def test_full_length_ideas_are_remembered_without_truncation(self):
        history, data = RecentIdeaHistory(), valid_draft()
        idea = "A specific action " + "detail " * 30
        self.assertLessEqual(len(idea.strip()), MAX_IDEA_CHARACTERS)
        history.remember(data, [{"idea": idea}])
        self.assertEqual(history.recent(data), [idea.strip()])

    def test_scope_expiry_and_concept_eviction(self):
        history = RecentIdeaHistory(concepts=2, ttl=10)
        a, b, c = [valid_draft(subject=subject) for subject in ("One", "Two", "Three")]
        with patch("goated_prompter.features.dataset.idea_history.time.monotonic", return_value=0):
            for data in (a, b, c):
                history.remember(data, [{"idea": data["subject"]}])
            self.assertEqual(history.recent(a), [])
            self.assertEqual(history.recent(b), ["Two"])
            self.assertEqual(history.recent(c), ["Three"])
        with patch("goated_prompter.features.dataset.idea_history.time.monotonic", return_value=11):
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
            "scene": "The same punch from a new camera angle in a different location."}])
        with self.assertRaisesRegex(BackendGenerationError, "recently generated event") as caught:
            DatasetIdeasService(lambda: None, history).run(session=session, data=data,
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

    def test_accepting_scenes_neither_reads_history_nor_calls_the_model(self):
        data = valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        history = RecentIdeaHistory()
        idea = dataset_idea_fixture()
        history.remember(data, [idea])
        with patch.object(history, "recent", side_effect=AssertionError("Only Ideas reads recent history")), \
                patch.object(history, "remember", side_effect=AssertionError("Only Ideas writes recent history")):
            rows = ScenePlanner(lambda: None, history).compose([idea])
        self.assertEqual((rows[0]["scene"], rows[0]["self_check"], rows[0]["scene_status"]), (idea["scene"], "PASS", "valid"))


class IdeaFingerprintTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from goated_prompter.json_store import atomic_json, read_store
        self.path = Path(tempfile.mkdtemp()) / "idea_fingerprints.json"
        self.make = lambda: RecentIdeaHistory(fingerprint_path=self.path, read=lambda path: read_store(path, {}, dict),
                                              write=atomic_json)
        self.data = valid_draft()

    def test_fingerprints_survive_a_restart_without_storing_any_idea_text(self):
        self.make().remember(self.data, [{"idea": "The boxer repairs a torn punching bag with duct tape."}])
        raw = self.path.read_text(encoding="utf-8").casefold()
        for word in ("boxer", "repairs", "punching", "duct", "tape"):
            self.assertNotIn(word, raw)
        restarted = self.make()
        self.assertEqual(restarted.recent(self.data), [], "Idea text stays in memory only.")
        self.assertTrue(restarted.seen_before(self.data, "A boxer repairs the torn punching bag with duct tape."))
        self.assertFalse(restarted.seen_before(self.data, "The boxer skips rope on a rooftop at dawn."))
        self.assertFalse(restarted.seen_before({**self.data, "subject": "A chef cooking."},
                                               "The boxer repairs a torn punching bag with duct tape."))

    def test_old_fingerprints_expire_and_a_broken_store_starts_fresh(self):
        from goated_prompter.features.dataset import idea_history
        history = self.make()
        history.remember(self.data, [{"idea": "The boxer repairs a torn punching bag."}])
        with patch.object(idea_history.time, "time", return_value=idea_history.time.time() + idea_history.FINGERPRINT_TTL + 60):
            self.assertFalse(self.make().seen_before(self.data, "The boxer repairs a torn punching bag."))
        self.path.write_text("not json", encoding="utf-8")
        self.assertFalse(self.make().seen_before(self.data, "The boxer repairs a torn punching bag."))
        self.make().remember(self.data, [{"idea": "The boxer wraps his hands."}])
        self.assertTrue(self.make().seen_before(self.data, "The boxer wraps his hands."))

    def test_the_brainstorm_prefers_candidates_unlike_recent_runs(self):
        import random
        from goated_prompter.features.dataset.brainstorm import brainstorm_events
        events = [{"event": f"The boxer {action}.", "typicality": .5} for action in
                  ("repairs a torn bag", "skips rope on a roof", "spars with a robot", "shadowboxes in rain")]
        session = Mock()
        session.generate.return_value = json.dumps(events)
        data = valid_draft(amount=2, _confirmed_intent=dataset_understanding_fixture())
        seen = lambda text: "repairs" in text or "robot" in text
        picked = brainstorm_events(session, data, 2, random.Random(1), seen=seen, progress=lambda _m: None,
                                   checkpoint=lambda: None)
        self.assertEqual(set(picked), {"The boxer skips rope on a roof.", "The boxer shadowboxes in rain."})
        everything = brainstorm_events(session, data, 4, random.Random(1), seen=lambda _text: True,
                                       progress=lambda _m: None, checkpoint=lambda: None)
        self.assertEqual(len(everything), 4, "Too few fresh candidates never shrinks the batch.")


class HistoryRepairTests(unittest.TestCase):
    def test_a_repair_that_repeats_history_again_is_kept_instead_of_failing(self):
        from goated_prompter.features.dataset.ideas import HISTORY_REPEAT
        history, data = RecentIdeaHistory(), valid_draft(amount=1, _confirmed_intent=dataset_understanding_fixture())
        old = dataset_idea_fixture(1, idea="The boxer tapes his hands.")
        history.remember(data, [old])
        session = Mock()
        session.generate.return_value = json.dumps([old])
        service = DatasetIdeasService(lambda: None, history)
        first = service.run(session=session, data=data, assignments=dataset_assignments(data),
                            progress=lambda _m: None, allow_partial=True)
        self.assertEqual(first[0]["failure_reason"], HISTORY_REPEAT)
        repaired = service.run(session=session, data=data, assignments=dataset_assignments(data), indexes=[1],
                               existing=first, progress=lambda _m: None, allow_partial=True)
        self.assertNotEqual(repaired[0].get("idea_status"), "failed")
