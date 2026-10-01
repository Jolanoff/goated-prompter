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
MAXIMUM_DETAIL_GUIDANCE = """Prompt length — Maximum Detail: produce a substantially longer, densely descriptive natural-language prompt. Exhaustively cover every relevant, supported visual decision: subject identity, count, age presentation when visually relevant, overall appearance, facial structure, eyes, expression, gaze, hair, skin, anatomy, body shape, pose, limbs, hands, gesture, and action; garment construction, seams, folds, fit, styling, accessories, fabrics, textures, finishes, roughness, reflectivity, translucency, and other material response; foreground, midground, background, meaningful objects, spatial relationships, scale, overlap, and occlusion; composition, framing, camera height, angle, perspective, lens behavior, depth, focus plane, and focus hierarchy; key, fill, rim, and practical light where supported, including direction, softness, contrast, shadows, highlights, reflections, and exposure; palette, color relationships, grading, atmosphere, mood, and the relevant photographic, commercial, editorial, cinematic, rendered, or artistic character. Clearly distinguish observable or user-specified facts from coherent creative additions, and keep every addition compatible with the central concept and active Reference Map and Preserve constraints. Do not repeat details, stack synonyms, use generic quality slogans, invent unsupported evidence, or pad with filler. Omit irrelevant or unavailable categories instead of hallucinating them; never force 35mm, film grain, or ControlNet terminology when it was not requested or observed."""
LENGTH_ADAPTERS = {
    "Short": "Prompt length — Short: one compact prompt focused on the most consequential visual information.",
    "Medium": "Prompt length — Medium: a balanced prompt with enough detail to direct subject, composition, lighting, and materials without bloat.",
    "Detailed": "Prompt length — Detailed: a rich but disciplined prompt covering relevant visual, spatial, material, camera, lighting, and temporal details.",
    "Maximum Detail": MAXIMUM_DETAIL_GUIDANCE,
    # Saved workflows from the pre-release Maximum label remain executable.
    "Maximum": MAXIMUM_DETAIL_GUIDANCE,
}

# Dataset overrides are applied only by its final writer, never the Builder.
DATASET_DETAIL_DISCIPLINE = """DATASET DETAIL DISCIPLINE
Expand the planned scene only until its important visible relationships are clear and useful for
the target model. Prompt length controls useful scene-specific richness, not an exhaustive inventory.
Do not spend detail budget inventing unrelated garment construction, arbitrary clothing colors,
background decoration, material microdetail, cinematic atmosphere, accessories or environmental
objects unless they support the planned scene. Maximum Detail should be scene-dense, not filler-dense.
State each important semantic fact once. Use additional words for new visual information rather
than synonymous emphasis. Preserve the requested medium rather than adding stylistic defaults."""
DATASET_LENGTH_ADAPTERS = {
    "Short": LENGTH_ADAPTERS["Short"],
    "Medium": LENGTH_ADAPTERS["Medium"],
    "Detailed": "Prompt length — Detailed: enrich this scene's important visible action, relationships and composition with supported scene-specific detail. Stop when it is clearly described.",
    "Maximum Detail": "Prompt length — Maximum Detail: give the planned scene dense, useful visual specificity. Clarify action, pose, contacts, spatial relationships, crop and scene-relevant rendering; do not expand irrelevant categories or repeat semantic facts.",
}

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

