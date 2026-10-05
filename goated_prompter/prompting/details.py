"""Prompt-length, preservation, and reference detail controls."""

# Prompt length and preservation/reference detail controls.

PROMPT_LENGTH_NAMES = ("Short", "Medium", "Detailed", "Maximum Detail")
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

# Dataset's semantic overlay controls WHAT; the normal length controls HOW MUCH.
DATASET_DETAIL_DISCIPLINE = """DATASET DETAIL DISCIPLINE
Spend detail on information that improves the rendering of this exact planned scene.
Prioritize action readability, subject interaction, pose mechanics, required visibility,
composition, scene-relevant clothing/material behavior, environment, lighting, depth and
target-appropriate visual treatment. Richness is allowed when it supports the scene.
Keep ordinary description economical, but preserve all information needed to
reconstruct actions, complex poses, contacts, overlap/depth, framing and required
visible anatomy. Functional pose geometry is not decorative verbosity, even at Short.
Use specific surfaces, textures, fabric tension, shadows, reflections, atmospheric separation
and color relationships where useful; preserve the requested medium and all supplied facts.
Avoid unrelated biography, arbitrary decorative objects, accessory inventories, irrelevant
microtexture, changing the event to add detail, repeated facts and synonymous filler.
Maximum Detail should be scene-dense, not filler-dense. Do not stop merely because the basic
event is understandable: satisfy the selected normal Length with useful, non-redundant visual
information within the target envelope. Detailed and Maximum Detail should develop the scene's
physical relationships, material/light response, environment and spatial depth more fully than
Medium, without requiring every category or turning geometry into a checklist.
At Maximum Detail, go beyond a Detailed restatement of staging: develop the richest useful
scene-specific material response, light direction/quality and shadow/reflection behavior,
environmental surfaces and foreground/background separation that this target can use.
Prefer concrete visible information over vague claims of a focused atmosphere, realistic
texture or coherent lighting. The planned mechanics are the starting point, not the entire
detail budget; add new compatible rendering information instead of rephrasing those mechanics.
Short remains concise and Medium balanced. The normal target envelope always wins."""
# Compatibility export for old callers and finite-output loop recovery. There is
# deliberately no weaker Dataset meaning of Detailed or Maximum Detail.
DATASET_LENGTH_ADAPTERS = dict(LENGTH_ADAPTERS)

# Preserve (legacy booleans and linked reference-map output)
REFERENCE_ROLE_NAMES = ("Auto", "Subject", "Scene", "Style", "Pose", "Composition", "Lighting")
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
REFERENCE_ATTRIBUTES = (
    ("subject", "Subject"),
    ("face", "Face / Identity"),
    ("outfit", "Outfit"),
    ("pose", "Pose"),
    ("composition", "Composition"),
    ("camera", "Camera"),
    ("scene", "Scene / Environment"),
    ("lighting", "Lighting"),
    ("colors", "Colors"),
    ("mood", "Mood / Style"),
    ("materials", "Materials"),
)
REFERENCE_SOURCE_NAMES = ("Auto", "Image 1", "Image 2", "Blend", "Off", "Image 3", "Image 4")
REFERENCE_IMAGE_SLOTS = (
    ("image", "Image 1"), ("image_2", "Image 2"),
    ("image_3", "Image 3"), ("image_4", "Image 4"),
)
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

