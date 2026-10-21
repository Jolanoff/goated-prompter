"""Caption editor: list a folder's images with their caption files, preview one image, save one caption."""

from io import BytesIO

from PIL import Image, ImageOps

from ...options.caption import PREVIEW_MAX_DIMENSION
from ...workspace_store import text
from .contract import caption_images, validated_folder, validated_image
from .runner import replace_caption


def _read_caption(sidecar):
    try:
        return sidecar.read_text(encoding="utf-8").rstrip("\r\n")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        return sidecar.read_text(encoding="utf-8", errors="replace").rstrip("\r\n")


def list_captions(value):
    """Every supported image in the folder, in caption order, with its caption text (None when missing)."""
    if not isinstance(value, dict) or set(value) - {"folder"}:
        raise ValueError("Expected an image folder.")
    folder = validated_folder(value)
    files = []
    for image in caption_images(folder):
        sidecar = image.with_suffix(".txt")
        files.append({"image": image.name, "caption_file": sidecar.name, "caption": _read_caption(sidecar),
                      "modified": image.stat().st_mtime_ns})
    return {"folder": folder, "files": files}


def folder_image(folder, name):
    """Resolve an image name to a supported image file directly inside the folder."""
    return validated_image(validated_folder({"folder": folder}), name)


def image_preview(folder, name):
    """A small JPEG preview so a folder of large images stays fast to browse."""
    path = folder_image(folder, name)
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((PREVIEW_MAX_DIMENSION, PREVIEW_MAX_DIMENSION))
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            background.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
            image = background
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def save_caption_text(value):
    """Replace one image's caption file with the edited text."""
    if not isinstance(value, dict) or set(value) - {"folder", "image", "caption"}:
        raise ValueError("Expected a folder, an image name and caption text.")
    image = folder_image(value.get("folder"), value.get("image"))
    caption = text(value.get("caption"), "Caption", 20000, optional=True).strip()
    if not caption:
        raise ValueError("The caption is empty. Write a caption before saving.")
    sidecar = image.with_suffix(".txt")
    replace_caption(sidecar, caption)
    return {"image": image.name, "caption_file": sidecar.name, "caption": caption}
