"""Preparation uses neutral synthetic prose, never the owner's vocabulary."""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.helpers import enter_context
from tests.support.safety import synthetic_storage
from tests.support.artifacts import task_paths
from tests.support.dataset import vocabulary_record
from goated_prompter.features.dataset.vocabulary_conversion import VocabularyConversion


class VocabularyConversionTests(unittest.TestCase):
    def setUp(self):
        _, scratch = task_paths("issue-108", "cpu")
        self.root = Path(enter_context(self, synthetic_storage(scratch)))
        self.source = self.root / "vocabulary.txt"
        self.original = b"[couple positions]\nTwo adults greet each other while seated.\n"
        self.source.write_bytes(self.original)
        self.tool = VocabularyConversion(self.source)

    def test_only_explicit_review_publishes_a_validated_catalog(self):
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        pending = self.tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
        self.assertFalse(self.tool.catalog_path.exists())
        self.assertEqual(pending["validated"], 1)
        review = self.tool.review()
        self.tool.approve(review["token"], [0])
        self.assertEqual(self.source.read_bytes(), self.original)
        with patch("goated_prompter.features.dataset.private_vocabulary.vocabulary_path", return_value=self.source):
            from goated_prompter.features.dataset.private_vocabulary import load_vocabulary
            catalog = load_vocabulary()
            self.assertEqual(len(catalog.records), 1)
            self.assertFalse(any(row["rule"] == "unresolved_structure" for row in catalog.diagnostics))

    def test_status_tracks_review_and_saved_catalog_without_exposing_records(self):
        self.assertEqual(self.tool.status()["state"], "not_prepared")
        self.assertEqual(self.tool.status()["catalog_path"], str(self.source) + ".catalog.json")
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        self.tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
        status = self.tool.status()
        self.assertEqual(status["state"], "awaiting_review")
        self.assertEqual(status["validated"], 1)
        self.assertNotIn("rows", status)
        self.assertNotIn("synthetic-greeting", json.dumps(status))
        self.tool.approve(self.tool.review()["token"], [0])
        self.assertEqual(self.tool.status()["state"], "saved")
        self.assertEqual(self.tool.status()["approved"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.source.write_bytes(self.original + b"# changed\n")
        self.assertEqual(self.tool.status()["state"], "stale_catalog")

    def test_invalid_and_unresolved_records_cannot_be_approved(self):
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        record["physicalConstraints"]["A"] = "unknown"
        self.tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
        review = self.tool.review()
        self.assertTrue(review["rows"][0]["reason"])
        with self.assertRaises(ValueError):
            self.tool.approve(review["token"], [0])
        self.assertFalse(self.tool.catalog_path.exists())

    def test_invalid_catalog_and_changed_review_are_reported_without_private_content(self):
        self.tool.catalog_path.write_text('{"version":1,"records":[]}', encoding="utf-8")
        self.assertEqual(self.tool.status()["state"], "stale_catalog")
        self.tool.prepare(lambda instruction: "not json", lambda: None)
        status = self.tool.status()
        self.assertEqual(status["state"], "awaiting_review")
        self.assertEqual((status["validated"], status["rejected"]), (0, 1))
        self.source.write_bytes(self.original + b"# changed\n")
        self.assertEqual(self.tool.status()["state"], "stale_review")
        self.assertNotIn("Two adults greet", json.dumps(self.tool.status()))

    def test_changed_source_and_stale_review_are_rejected(self):
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        self.tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
        review = self.tool.review()
        self.source.write_bytes(self.original + b"# changed\n")
        with self.assertRaises(ValueError):
            self.tool.approve(review["token"], [0])

    def test_conversion_requests_are_private_and_rejection_preserves_source(self):
        calls = []
        def generate(instruction):
            calls.append(instruction)
            return "not json"
        self.tool.prepare(generate, lambda: None)
        self.assertTrue(calls[0].diagnostic_context["private_content"])
        self.tool.reject(self.tool.review()["token"])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(self.tool.catalog_path.exists())

    def test_provider_failure_cannot_echo_private_source_into_job_errors(self):
        def generate(_instruction):
            raise ValueError("synthetic private source echoed by provider")
        with self.assertRaises(ValueError) as error:
            self.tool.prepare(generate, lambda: None)
        self.assertNotIn("synthetic private source", str(error.exception))
        self.assertFalse(self.tool.pending_path.exists())

    def test_duplicate_ids_and_section_count_mismatches_are_rejected(self):
        self.source.write_bytes(self.original + b"Another synthetic seated greeting.\n")
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        self.tool.prepare(lambda instruction: json.dumps([record, record]), lambda: None)
        self.assertIn("already defined", self.tool.review()["rows"][1]["reason"])
        record["participantCount"] = 1
        del record["participants"]["B"]
        del record["physicalConstraints"]["B"]
        self.tool.prepare(lambda instruction: json.dumps([record, record]), lambda: None)
        self.assertTrue(all("section" in row["reason"] for row in self.tool.review()["rows"]))

    def test_changed_original_invalidates_catalog_without_disabling_general_planning(self):
        record = vocabulary_record("synthetic-greeting", "paired_pose")
        self.tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
        self.tool.approve(self.tool.review()["token"], [0])
        self.source.write_bytes(self.original + b"# source changed\n")
        with patch("goated_prompter.features.dataset.private_vocabulary.vocabulary_path", return_value=self.source):
            from goated_prompter.features.dataset.private_vocabulary import load_vocabulary
            catalog = load_vocabulary()
        self.assertFalse(catalog.records)
        self.assertTrue(any("general planning" in row["reason"] for row in catalog.diagnostics))

    def test_remote_backend_is_rejected_before_reading_private_vocabulary(self):
        from goated_prompter.features.dataset.runner import run_vocabulary_preparation
        with patch("goated_prompter.features.dataset.runner.resolve_director_config",
                   return_value=({"backend": "openai_compatible"}, None)), \
                patch("goated_prompter.features.dataset.runner.VocabularyConversion") as tool:
            with self.assertRaisesRegex(ValueError, "local model"):
                run_vocabulary_preparation(Mock(), Mock(), Mock(), {}, {})
        tool.assert_not_called()

    def test_sidecar_names_cannot_overwrite_an_original_with_a_json_suffix(self):
        for name in ("source.catalog.json", "source.review.json"):
            with self.subTest(name=name):
                source = self.root / name
                source.write_bytes(self.original)
                tool = VocabularyConversion(source)
                record = vocabulary_record("synthetic-greeting", "paired_pose")
                tool.prepare(lambda instruction: json.dumps([record]), lambda: None)
                tool.approve(tool.review()["token"], [0])
                self.assertEqual(source.read_bytes(), self.original)
