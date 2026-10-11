"""Prompt-length, preservation, and reference detail controls."""

# Prompt length and preservation/reference detail controls.

DATASET_OUTPUT_TOKEN_LIMITS = {
    "Short": 384,
    "Medium": 768,
    "Detailed": 1536,
    "Maximum Detail": 3072,
    "Maximum": 3072,
}
MAXIMUM_DETAIL_GUIDANCE = """Prompt length — Maximum Detail: use the richest useful descriptive density within the target's practical envelope. Clarify supported subject/action, spatial relationships, composition, relevant materials and lighting without exhaustive unrelated inventories. After the core scene is covered, spend remaining detail on previously unstated useful facts: defining contact/support mechanics, spatial relationships, material behavior at contact surfaces, motivated light/shadow/reflection behavior, environmental surfaces and foreground/background separation. Each addition should help render this exact scene, not repeat an existing fact with adjectives. Do not change mechanics to create detail. If applicable coverage is saturated, stop rather than force filler or unrelated categories. Preserve the central concept, reference evidence and locks. Omit irrelevant or unavailable facts; do not repeat details, stack synonyms, invent evidence or pad with filler. Target structure and density limits take priority."""
LENGTH_ADAPTERS = {
    "Short": "Prompt length — Short: one compact prompt focused on the most consequential visual information.",
    "Medium": "Prompt length — Medium: a balanced prompt with enough detail to direct subject, composition, lighting, and materials without bloat.",
    "Detailed": "Prompt length — Detailed: a rich but disciplined prompt covering relevant visual, spatial, material, camera, lighting, and temporal details.",
    "Maximum Detail": MAXIMUM_DETAIL_GUIDANCE,
    # Saved workflows from the pre-release Maximum label remain executable.
    "Maximum": MAXIMUM_DETAIL_GUIDANCE,
}

# Preserve (legacy booleans and linked reference-map output)
PRESERVATION_ADAPTERS = {
    "subject": "Preserve subject: do not change subject identity, type, count, key attributes, clothing, or defining features unless explicitly requested.",
    "composition": "Preserve composition: do not rearrange the scene, layout, spatial relationships, crop, or framing unless explicitly requested.",
    "camera": "Preserve camera: do not invent a different viewpoint, camera height, angle, framing, focal length, or camera movement unless explicitly requested.",
    "materials": "Preserve materials: do not replace specified materials, finishes, texture character, roughness, or surface response.",
    "lighting": "Preserve lighting: do not replace the stated light sources, direction, time-of-day character, contrast, or exposure intent.",
    "colors": "Preserve colors: do not replace the stated palette, object colors, material colors, or color-grading intent.",
}
PRESERVATION_NO_LINKED_LOCKS = "PRESERVATION CONSTRAINTS\nNo attribute-level Preserve locks are enabled."
PRESERVATION_LINKED_LOCK = "Preserve {label} from {source} strictly. This lock controls strictness only and does not change any other attribute's resolved source."
PRESERVATION_NONE = "PRESERVATION CONSTRAINTS\nNone beyond the selected mode and the user's explicit wording."

# Reference-map Preserve controls used by the website and node. These labels,
# sources, and emitted instructions are static prompt content; reference_map.py
# owns only the deterministic source-resolution behavior.
REFERENCE_MANUAL_CONSTRAINTS = {
    "subject": "Use the subject from {source}. Do not use a conflicting subject from {other}.",
    "face": "Use face and identity from {source}. Do not use conflicting identity features from {other}.",
    "outfit": "Use clothing/outfit from {source}. Do not use conflicting clothing from {other}.",
    "pose": "Use pose and action from {source}. Do not use the conflicting pose or action from {other}.",
    "composition": "Use composition and framing from {source}. Do not use conflicting composition or framing from {other}.",
    "camera": "Use camera viewpoint and perspective from {source}. Do not use a conflicting camera setup from {other}.",
    "scene": "Use environment/background from {source}. Do not retain the conflicting environment from {other}.",
    "lighting": "Use lighting from {source}. Do not use the conflicting lighting treatment from {other}.",
    "colors": "Use the dominant color treatment/palette from {source}. Do not use the conflicting palette from {other}.",
    "mood": "Use mood/style from {source}. Do not use the conflicting mood/style treatment from {other}.",
    "materials": "Use materials and surface treatment from {source}. Do not use conflicting materials from {other}.",
}

