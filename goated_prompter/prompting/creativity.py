"""Creativity controls for prompt generation."""

# Creativity and prompt length
CREATIVITY_NAMES = ("Strict", "Balanced", "Creative", "Dice")
CREATIVITY_ADAPTERS = {
    "Strict": "Creativity — Strict: preserve the user's concept closely. Add only information required for clarity and coherence; do not invent important content or change the camera.",
    "Balanced": "Creativity — Balanced: fill reasonable missing visual information while preserving the concept and avoiding conspicuous invention.",
    "Creative": "Creativity — Creative: add tasteful, coherent visual direction where unspecified, but respect every active preservation constraint.",
    "Dice": "Creativity — Dice (v0.1 soft level): invent one coherent visual concept from minimal input. Make decisive but internally consistent choices while respecting explicit preservation constraints. This adapter is structured for future Soft, Wild, and Total Chaos levels.",
}
