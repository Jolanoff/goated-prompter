"""In-memory ComfyUI IMAGE conversion for multimodal backends."""

import base64
from dataclasses import dataclass
from io import BytesIO

from .backends.base import ImageEncodingError


@dataclass(frozen=True)
class EncodedImage:
    data: str
    media_type: str
    width: int
    height: int

    @property
    def data_url(self):
        return f"data:{self.media_type};base64,{self.data}"


def encode_comfy_image(image, max_dimension=1344):
    """Encode the first image in a ComfyUI IMAGE batch as a bounded PNG."""
    if isinstance(image, EncodedImage):
        return image
    if image is None:
        return None

    try:
        from PIL import Image
    except ImportError as exc:
        raise ImageEncodingError("Pillow is required to encode IMAGE input for Goated Prompter.") from exc

    try:
        pixels = image.detach()
    except (AttributeError, TypeError, RuntimeError) as exc:
        raise ImageEncodingError("Goated Prompter IMAGE input is not a valid ComfyUI image tensor.") from exc

    if pixels.ndim == 4:
        if pixels.shape[0] < 1:
            raise ImageEncodingError("Goated Prompter received an empty IMAGE batch.")
        pixels = pixels[0]
    if pixels.ndim != 3:
        raise ImageEncodingError("Goated Prompter IMAGE tensor must have shape [B,H,W,C] or [H,W,C].")

    try:
        pixels = pixels.to(device="cpu")
    except (TypeError, RuntimeError) as exc:
        raise ImageEncodingError("Goated Prompter IMAGE input is not a valid ComfyUI image tensor.") from exc

    if pixels.shape[-1] in {1, 3, 4}:
        pass
    elif pixels.shape[0] in {1, 3, 4}:
        pixels = pixels.permute(1, 2, 0)
    else:
        raise ImageEncodingError("Goated Prompter IMAGE tensor must contain 1, 3, or 4 channels.")

    channels = int(pixels.shape[-1])
    pixels = pixels.float().clamp(0.0, 1.0)
    if channels == 1:
        pixels = pixels.repeat(1, 1, 3)
    elif channels == 4:
        pixels = pixels[:, :, :3]

    try:
        array = (pixels * 255.0).round().byte().numpy()
        prepared = Image.fromarray(array)
    except Exception as exc:
        raise ImageEncodingError("Goated Prompter could not convert the IMAGE tensor to RGB pixels.") from exc

    try:
        limit = max(256, min(4096, int(max_dimension)))
    except (TypeError, ValueError):
        limit = 1344
    if max(prepared.size) > limit:
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        prepared.thumbnail((limit, limit), resampling)

    buffer = BytesIO()
    prepared.save(buffer, format="PNG", optimize=True)
    return EncodedImage(
        data=base64.b64encode(buffer.getvalue()).decode("ascii"),
        media_type="image/png",
        width=prepared.width,
        height=prepared.height,
    )
