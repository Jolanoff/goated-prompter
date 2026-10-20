"""Caption training targets, choices, and supported image formats."""

TARGETS = ("Krea 2",)
LENGTHS = ("focused", "detailed")
LORA_TYPES = ("character", "style", "action")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
