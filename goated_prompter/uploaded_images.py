"""Validate untrusted data URLs and prepare bounded RGB reference images."""

import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .image_utils import EncodedImage

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


def decode_image(value, max_dimension=1344):
    if value is None:
        return None
    formats = {"data:image/png;base64": "PNG", "data:image/jpeg;base64": "JPEG",
               "data:image/webp;base64": "WEBP"}
    if not isinstance(value, str) or "," not in value:
        raise ValueError("Images must be PNG, JPEG, or WEBP base64 data URLs, or null.")
    header, data = value.split(",", 1)
    if header not in formats or len(data) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Each image must be PNG, JPEG, or WEBP and at most 20 MiB.")
    try:
        raw = base64.b64decode(data, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Each image must be at most 20 MiB.")
        with Image.open(BytesIO(raw)) as image:
            if image.format != formats[header]:
                raise ValueError("Image content does not match its data URL type.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Each image must be at most 40 million pixels.")
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            prepared = image.convert("RGB")
        try:
            limit = max(256, min(4096, int(max_dimension)))
        except (TypeError, ValueError):
            limit = 1344
        if max(prepared.size) > limit:
            prepared.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        prepared.save(buffer, format="PNG", optimize=True)
        return EncodedImage(base64.b64encode(buffer.getvalue()).decode("ascii"),
                            "image/png", prepared.width, prepared.height)
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Image could not be decoded. Upload a valid PNG, JPEG, or WEBP.") from exc
