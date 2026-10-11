"""Target image/video models users can select, and accepted aliases."""

TARGET_MODEL_NAMES = ("Generic", "Anima", "Krea 2", "FLUX.2 Klein", "Z-Image Base", "Z-Image Turbo", "Qwen Image (original)", "Qwen Image 2.1", "MiniMax H3", "LTX 2.5", "Ideogram4")
TARGET_ALIASES = {"Z-Image": "Z-Image Base", "Qwen Image": "Qwen Image (original)",
                  "Qwen2.1": "Qwen Image 2.1", "MiniMax": "MiniMax H3"}


def canonical_target(name):
    return TARGET_ALIASES.get(name, name) if isinstance(name, str) else name
