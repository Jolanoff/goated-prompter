"""Validate Caption inputs and folder-to-sidecar pairing."""

from pathlib import Path

from ...options.caption import IMAGE_TYPES, LENGTHS, LORA_TYPES, TARGETS
from ...workspace_store import text


def validated_folder(value):
    folder = Path(text(value.get("folder"), "Image folder", 4096).strip()).expanduser()
    if not folder.is_dir():
        raise ValueError("Choose an existing image folder on the app's computer.")
    return str(folder.resolve())


def validated_image(folder, name):
    """Resolve an image name to a supported image file directly inside an already validated folder."""
    name = text(name, "Image name", 1024).strip()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Choose an image directly inside the folder.")
    path = Path(folder) / name
    if path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
        raise ValueError("That image is not in this folder.")
    return path


def _single_image(value, folder):
    """Optional one-image run: its name, or "" for the whole folder."""
    return validated_image(folder, value["image"]).name if value.get("image") else ""


def _folder_and_trigger(value):
    trigger = text(value.get("trigger", ""), "Trigger phrase", 200, optional=True).strip()
    if "\n" in trigger or "\r" in trigger:
        raise ValueError("Trigger phrase must be on one line.")
    return validated_folder(value), trigger


def validate_caption_input(value):
    if not isinstance(value, dict) or set(value) - {"folder", "target", "description", "length", "lora_type", "trigger",
                                                    "image"}:
        raise ValueError("Expected Caption folder and caption settings.")
    result = {
        "description": text(value.get("description"), "Image description", 10000).strip(),
        "target": value.get("target", TARGETS[0]),
        "length": value.get("length", "detailed"),
        "lora_type": value.get("lora_type", "character"),
    }
    for key, choices in (("target", TARGETS), ("length", LENGTHS), ("lora_type", LORA_TYPES)):
        if result[key] not in choices:
            raise ValueError(f"Invalid Caption {key}.")
    result["folder"], result["trigger"] = _folder_and_trigger(value)
    result["image"] = _single_image(value, result["folder"])
    return result


def validate_metadata_input(value):
    if not isinstance(value, dict) or set(value) - {"folder", "trigger", "image"}:
        raise ValueError("Expected an image folder and an optional trigger phrase.")
    folder, trigger = _folder_and_trigger(value)
    return {"folder": folder, "trigger": trigger, "image": _single_image(value, folder)}


def run_images(data):
    """The images a run covers: one requested image (its caption is replaced), or the whole folder."""
    images = caption_images(data["folder"])
    return [image for image in images if image.name == data["image"]] if data.get("image") else images


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
