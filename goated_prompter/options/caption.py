"""Caption training targets, choices, limits, and supported image formats."""

TARGETS = ("Krea 2",)
LENGTHS = ("focused", "detailed")
LORA_TYPES = ("character", "style", "action")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
# Longest side, in pixels, of the previews shown in the caption editor.
PREVIEW_MAX_DIMENSION = 512

# A dropped engine connection is retried once on a fresh engine session for the same image.
# After this many images in a row fail that way the run stops instead of trying every image.
CONNECTION_ATTEMPTS_PER_IMAGE = 2
CONNECTION_FAILURES_BEFORE_STOP = 2

# Prompt metadata: graph input names that hold prompt text in saved generation graphs.
METADATA_TEXT_INPUTS = ("text", "text_g", "text_l", "t5xxl", "clip_l", "prompt", "positive",
                        "text_positive", "populated_text", "string", "value")
# Tracing starts at a node that takes a model plus a linked positive or conditioning input (a sampler or
# guider) and follows only conditioning links. Inputs whose name contains the excluded word are never followed.
METADATA_START_INPUTS = ("positive", "conditioning")
METADATA_MODEL_INPUT = "model"
METADATA_CONDITIONING_WORDS = ("conditioning", "positive")
METADATA_EXCLUDED_WORD = "negative"
# Saved editor workflows have unnamed widgets; text is read only from node types containing these words.
METADATA_TEXT_NODE_WORDS = ("textencode", "text", "prompt", "string", "primitive")
# Inline network tags (for example <lora:name:0.8>) are generation settings, not caption text.
METADATA_TAG_PATTERN = r"<(?:lora|lyco|lycoris|hypernet|embedding):[^>]*>"
