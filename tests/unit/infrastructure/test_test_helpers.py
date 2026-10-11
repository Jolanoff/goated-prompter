"""Regression coverage for context cleanup without Python 3.11-only APIs."""

from contextlib import contextmanager
import unittest

from tests.helpers import enter_context


class ContextHelperTests(unittest.TestCase):
    def test_returns_entered_value_and_cleans_up_in_reverse_order(self):
        case = unittest.TestCase()
        events = []

        @contextmanager
        def context(name):
            events.append(f"enter:{name}")
            try:
                yield name
            finally:
                events.append(f"exit:{name}")

        self.assertEqual(enter_context(case, context("first")), "first")
        self.assertEqual(enter_context(case, context("second")), "second")
        case.doCleanups()
        self.assertEqual(events, ["enter:first", "enter:second", "exit:second", "exit:first"])

    def test_cleanup_runs_when_setup_fails(self):
        events = []

        @contextmanager
        def context():
            try:
                yield
            finally:
                events.append("closed")

        class BrokenSetup(unittest.TestCase):
            def setUp(self):
                enter_context(self, context())
                raise ValueError("setup failed")

            def runTest(self):
                raise AssertionError("test must not run")

        result = unittest.TestResult()
        BrokenSetup().run(result)
        self.assertEqual(events, ["closed"])
        self.assertEqual(len(result.errors), 1)

    def test_failed_entry_does_not_register_cleanup(self):
        case = unittest.TestCase()

        @contextmanager
        def context():
            raise ValueError("entry failed")
            yield

        with self.assertRaisesRegex(ValueError, "entry failed"):
            enter_context(case, context())
        self.assertEqual(case._cleanups, [])
