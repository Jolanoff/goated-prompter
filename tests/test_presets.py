"""Director library mutations always use an isolated temporary library."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter import presets


class DirectorLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.enterContext(patch.dict(os.environ, {presets.USER_DIRECTOR_DIR_ENV: temporary}))

    def test_update_preserves_id_filename_mode_and_atomic_failure(self):
        director, path = presets.save_user_director("Original", "Instructions", "Video")
        updated, destination = presets.update_director(director.id, "Renamed", "Edited")
        self.assertEqual(destination, path)
        self.assertEqual(updated.id, director.id)
        self.assertEqual(updated.recommended_mode, "Video")
        original = path.read_bytes()
        with patch.object(presets.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(presets.DirectorLibraryError):
                presets.update_director(director.id, "Other", "Lost")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_malformed_override_warns_refuses_update_and_resets_only_override(self):
        user, user_path = presets.save_user_director("Keep me", "Unchanged")
        builtin = presets.DIRECTOR_PRESETS[0]
        edited, path = presets.update_director(builtin.id, builtin.label, "Override")
        self.assertEqual(path, self.root / ".overrides" / (builtin.id + ".json"))
        self.assertTrue(edited.modified)
        listed, warnings = presets.list_director_presets()
        self.assertFalse(warnings)
        self.assertTrue(next(item for item in listed if item["id"] == builtin.id)["modified"])
        path.write_bytes(b"invalid JSON")
        listed, warnings = presets.list_director_presets()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(presets.get_director_preset(builtin.id), builtin)
        with self.assertRaises(presets.DirectorLibraryError):
            presets.update_director(builtin.id, builtin.label, "Replacement")
        self.assertEqual(path.read_bytes(), b"invalid JSON")
        reset, reset_path = presets.reset_director(builtin.id)
        self.assertEqual(reset, builtin)
        self.assertEqual(reset_path, path)
        self.assertFalse(path.exists())
        self.assertTrue(user_path.exists())
        self.assertEqual(presets.get_director_preset(user.id), user)

    def test_validation_and_protection(self):
        director, _ = presets.save_user_director("Original", "Instructions")
        presets.save_user_director("Taken", "Instructions")
        for name in ("", " " * 2, "x" * 81, "Taken", "General Director", "general_director", "creative enhancement"):
            with self.subTest(name=name), self.assertRaises(presets.DirectorLibraryError):
                presets.update_director(director.id, name, "Instructions")
        for instructions in ("", " ", "x" * 100001, None, 123):
            with self.subTest(instructions=str(instructions)[:20]):
                with self.assertRaises(presets.DirectorLibraryError):
                    presets.update_director(director.id, "Original", instructions)
                with self.assertRaises(presets.DirectorLibraryError):
                    presets.save_user_director("New", instructions)
        with self.assertRaises(presets.DirectorLibraryError):
            presets.update_director("general_director", "Renamed", "Instructions")
        with self.assertRaises(presets.DirectorLibraryError):
            presets.delete_user_director("general_director")
        with self.assertRaises(presets.DirectorLibraryError):
            presets.reset_director(director.id)
        self.assertEqual(presets.get_director_preset(director.id).recommended_mode, "")
