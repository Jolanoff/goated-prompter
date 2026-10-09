"""Image-upload decoding and size contracts without HTTP execution."""

import base64
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

import local_app as local
from goated_prompter import uploaded_images


class UploadTests(unittest.TestCase):
    def test_declared_format_must_match_content_and_invalid_dimension_uses_default(self):
        buffer = BytesIO()
        Image.new("RGB", (1600, 800)).save(buffer, "PNG")
        raw = base64.b64encode(buffer.getvalue()).decode()
        with self.assertRaisesRegex(ValueError, "does not match"):
            local.decode_image("data:image/jpeg;base64," + raw)
        encoded = local.decode_image("data:image/png;base64," + raw, "invalid")
        self.assertEqual((encoded.width, encoded.height), (1344, 672))
        self.assertIsNone(local.decode_image(None))

    def test_formats_and_limits(self):
        for fmt, mime in (("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")):
            buffer = BytesIO()
            Image.new("RGB", (500, 300)).save(buffer, fmt)
            data = f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode()
            encoded = local.decode_image(data, 256)
            self.assertEqual((encoded.width, encoded.height, encoded.media_type), (256, 154, "image/png"))
            with patch.object(uploaded_images, "MAX_IMAGE_PIXELS", 100):
                with self.assertRaisesRegex(ValueError, "pixels"):
                    local.decode_image(data)
            with patch.object(uploaded_images, "MAX_IMAGE_BYTES", 1):
                with self.assertRaises(ValueError):
                    local.decode_image(data)
        with self.assertRaises(ValueError):
            local.decode_image("data:image/png;base64,!!!!")
