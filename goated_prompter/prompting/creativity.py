"""Creativity controls for prompt generation."""

# Creativity and prompt length
CREATIVITY_ADAPTERS = {
    "Strict": "Creativity — Strict: preserve the user's concept closely. Do not invent a new primary subject, action, location or camera concept. Add only information required for coherence.",
    "Balanced": "Creativity — Balanced: fill secondary visual specifics such as environment details, lighting, material behavior and minor staging. Preserve the concept; do not introduce a new central event.",
    "Creative": "Creativity — Creative: make meaningful unspecified creative decisions about supporting props, styling, atmosphere, environment and composition while preserving the central subject, action and concept and all preservation constraints.",
    "Dice": "Creativity — Dice: decide major unspecified visual choices from minimal input while explicit subjects, relationships, actions, text and preservation constraints remain fixed.",
}
