"""Caption editor listing, previews and saving use synthetic images only."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from goated_prompter.features.caption.files import image_preview, list_captions, save_caption_text
from tests.helpers import enter_context
from tests.support.artifacts import task_paths
from tests.support.safety import synthetic_storage


class CaptionEditorFileTests(unittest.TestCase):
    def setUp(self):
        _, scratch = task_paths("issue-118", "unit")
        storage = enter_context(self, synthetic_storage(scratch))
        self.folder = Path(enter_context(self, tempfile.TemporaryDirectory(dir=storage)))
        Image.new("RGBA", (1600, 800), (0, 0, 255, 128)).save(self.folder / "b.png")
        Image.new("RGB", (40, 30), "red").save(self.folder / "a.jpg")
        (self.folder / "a.txt").write_text("A red rectangle.\n", encoding="utf-8")
        (self.folder / "notes.md").write_text("not an image", encoding="utf-8")

    def test_lists_images_in_order_with_caption_or_none(self):
        result = list_captions({"folder": str(self.folder)})
        self.assertEqual([(row["image"], row["caption"]) for row in result["files"]],
                         [("a.jpg", "A red rectangle."), ("b.png", None)])

    def test_preview_is_small_jpeg(self):
        with Image.open(BytesIO(image_preview(str(self.folder), "b.png"))) as preview:
            self.assertEqual(preview.format, "JPEG")
            self.assertLessEqual(max(preview.size), 512)

    def test_save_creates_and_overwrites_caption_file(self):
        save_caption_text({"folder": str(self.folder), "image": "b.png", "caption": "  A blue rectangle.  "})
        self.assertEqual((self.folder / "b.txt").read_text(encoding="utf-8"), "A blue rectangle.\n")
        save_caption_text({"folder": str(self.folder), "image": "a.jpg", "caption": "Edited caption"})
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), "Edited caption\n")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir() if path.name.startswith(".")), [])

    def test_rejects_paths_outside_folder_other_files_and_empty_text(self):
        outside = self.folder.parent / "outside.png"
        Image.new("RGB", (4, 4)).save(outside)
        self.addCleanup(outside.unlink)
        for name in ("../outside.png", str(outside), "notes.md", "missing.png", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                image_preview(str(self.folder), name)
            with self.subTest(save=name), self.assertRaises(ValueError):
                save_caption_text({"folder": str(self.folder), "image": name, "caption": "x"})
        with self.assertRaisesRegex(ValueError, "empty"):
            save_caption_text({"folder": str(self.folder), "image": "a.jpg", "caption": "   "})
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), "A red rectangle.\n")
        with self.assertRaises(ValueError):
            list_captions({"folder": str(self.folder), "extra": 1})


if __name__ == "__main__":
    unittest.main()
