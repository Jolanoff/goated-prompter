"""Job persistence must not block state reads or cancellation."""

import threading
import unittest

from goated_prompter.local_jobs import Job, JobCancelled


class JobPersistenceTests(unittest.TestCase):
    def test_blocked_callback_keeps_snapshots_and_cancellation_responsive(self):
        for finish in (False, True):
            with self.subTest(finish=finish):
                job = Job()
                entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
                results, errors, calls = [], [], []

                def persist():
                    calls.append(1)
                    entered.set()
                    if not release.wait(4):
                        raise RuntimeError("Test persistence barrier timed out")
                    return {"persisted": True}

                def commit():
                    try:
                        results.append(job.commit(persist, finish=finish))
                    except Exception as exc:
                        errors.append(exc)

                def cancel():
                    self.assertIsNone(job.snapshot()["result"])
                    job.cancel()
                    cancelled.set()

                worker = threading.Thread(target=commit, daemon=True)
                canceller = threading.Thread(target=cancel, daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    canceller.start()
                    self.assertTrue(cancelled.wait(1), "Persistence held the job state lock")
                finally:
                    release.set()
                    worker.join(2)
                    if canceller.ident is not None:
                        canceller.join(2)
                self.assertFalse(worker.is_alive())
                self.assertFalse(canceller.is_alive())
                self.assertEqual(calls, [1])
                self.assertEqual(results, [])
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], JobCancelled)
                self.assertNotEqual(job.snapshot()["status"], "succeeded")

    def test_pause_during_persistence_does_not_repeat_callback_on_resume(self):
        job = Job()
        persisted, finished = threading.Event(), threading.Event()
        calls, errors = [], []

        def persist():
            calls.append(1)
            job.gate.clear()
            persisted.set()
            return {"saved": True}

        def deliver():
            try:
                job.deliver(persist)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        worker = threading.Thread(target=deliver, daemon=True)
        worker.start()
        try:
            self.assertTrue(persisted.wait(2))
            self.assertNotEqual(job.snapshot()["status"], "succeeded")
        finally:
            job.gate.set()
            worker.join(2)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(calls, [1])
        self.assertEqual(job.snapshot()["result"], {"saved": True})
        self.assertEqual(job.snapshot()["status"], "succeeded")

    def test_cancelled_job_never_starts_persistence(self):
        job = Job()
        job.cancel()
        calls = []
        with self.assertRaises(JobCancelled):
            job.commit(lambda: calls.append(1), finish=True)
        self.assertEqual(calls, [])
