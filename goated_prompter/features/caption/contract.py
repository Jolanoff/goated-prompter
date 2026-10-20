"""Validate Caption inputs and folder-to-sidecar pairing."""

from pathlib import Path

from ...options.caption import IMAGE_TYPES, LENGTHS, LORA_TYPES, TARGETS
from ...workspace_store import text


def validate_caption_input(value):
    if not isinstance(value, dict) or set(value) - {"folder", "target", "description", "length", "lora_type", "trigger"}:
        raise ValueError("Expected Caption folder and caption settings.")
    result = {
        "folder": text(value.get("folder"), "Image folder", 4096).strip(),
        "description": text(value.get("description"), "Image description", 10000).strip(),
        "trigger": text(value.get("trigger", ""), "Trigger phrase", 200, optional=True).strip(),
        "target": value.get("target", TARGETS[0]),
        "length": value.get("length", "detailed"),
        "lora_type": value.get("lora_type", "character"),
    }
    for key, choices in (("target", TARGETS), ("length", LENGTHS), ("lora_type", LORA_TYPES)):
        if result[key] not in choices:
            raise ValueError(f"Invalid Caption {key}.")
    if "\n" in result["trigger"] or "\r" in result["trigger"]:
        raise ValueError("Trigger phrase must be on one line.")
    folder = Path(result["folder"]).expanduser()
    if not folder.is_dir():
        raise ValueError("Choose an existing image folder on the app's computer.")
    result["folder"] = str(folder.resolve())
    return result


def caption_images(folder):
    images = sorted((path for path in Path(folder).iterdir()
                     if path.is_file() and path.suffix.lower() in IMAGE_TYPES), key=lambda path: path.name.casefold())
    if not images:
        raise ValueError("No supported images in this folder. Use PNG, JPG, JPEG, or WebP files.")
    stems = set()
    for image in images:
        stem = image.stem.casefold()
        if stem in stems:
            raise ValueError("Several images would use the same caption file. Give each image a unique filename stem.")
        stems.add(stem)
    return images
