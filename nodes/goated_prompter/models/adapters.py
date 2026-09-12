"""Independent target-model adapters, kept conservative for v0.1."""

TARGET_MODEL_NAMES = (
    "Generic",
    "Krea 2",
    "FLUX.2 Klein",
    "Z-Image",
    "Qwen Image",
    "MiniMax",
    "LTX 2.5",
    "Ideogram4",
)

_MODEL_ADAPTERS = {
    "Generic": """Generic target: write clean, coherent natural-language visual description without model-specific syntax or tag chains.""",
    "Krea 2": """Krea 2 target: favor coherent natural-language visual direction. Make subject, composition, material detail, realistic lighting, and photographic character clear; add mood or color grading only when useful. Avoid tag-like keyword piles.""",
    "FLUX.2 Klein": """FLUX.2 Klein target: use concise, precise natural-language instructions. For editing or enhancement, distinguish requested changes from protected content explicitly. Avoid bloated keyword chains.""",
    "Z-Image": """Z-Image target: use conservative, direct natural-language description with clear visual relationships. Avoid speculative special syntax so this adapter remains easy to tune after testing.""",
    "Qwen Image": """Qwen Image target: use clear structured natural language. State relationships among subjects, environment, composition, and requested modifications explicitly, especially for image editing.""",
    "MiniMax": """MiniMax target: use direct cinematic natural language. In Video mode, prioritize visible action, temporal order, camera motion, environmental motion, spatial continuity, and a clear end state.""",
    "LTX 2.5": """LTX 2.5 target: describe a clear shot in natural language. In Video mode, make chronological motion, camera behavior, subject movement, beginning-to-end progression, continuity, and final framing explicit.""",
    "Ideogram4": """Ideogram4 target: output a detailed, valid Ideogram 4.0 JSON caption, not a prose prompt. Return exactly one JSON object with double-quoted keys and strings, no Markdown fences, comments, trailing commas, or surrounding commentary. Preserve the following key order and use only this schema:
1. "high_level_description": a string summarizing the complete image in one or two sentences.
2. "style_description": an object describing aesthetics, lighting, medium, and the appropriate photographic or artistic treatment. For photographs, use keys in this order: "aesthetics", "lighting", "photo", "medium", then optional "color_palette". For non-photographic work, use "aesthetics", "lighting", "medium", "art_style", then optional "color_palette". All fields except color_palette are descriptive strings. Include exactly one of photo or art_style, never both. Use photo for relevant framing, camera, lens, focus, and exposure details; use art_style for illustration, painting, 3D rendering, or graphic-design treatment. color_palette is an array of up to 16 uppercase #RRGGBB hex strings representing the intended dominant colors, including background, highlights, and shadows where useful.
3. "compositional_deconstruction": an object with "background" first (a detailed environment string), then "elements" (an array of individual subject, object, and in-image text objects).
Object element key order: "type": "obj", optional "bbox", "desc", optional "color_palette".
Text element key order: "type": "text", optional "bbox", "text", "desc", optional "color_palette". Put each distinct requested piece of visible text in its own text element; preserve its literal spelling and case in text, properly JSON-escaped. Describe typography, size, alignment, and styling in desc. Do not invent signage or captions.
Every desc is a detailed visual string: describe supported appearance, pose or action, materials, texture, colors, scale, spatial relationships, and lighting response where relevant. Separate meaningful elements without fragmenting every small detail into a new object.
Optional bbox is [y_min, x_min, y_max, x_max], four integers from 0 to 1000 with origin at top-left and minimums less than maximums. Include it when explicit layout or grounded reference placement matters; otherwise omit it to allow free placement. Optional per-element color_palette contains up to 5 uppercase #RRGGBB hex strings.
Use all three top-level fields. Write rich, concrete descriptions within the fields while respecting the user's concept, evidence, creativity, and preservation constraints. Length settings control descriptive density, never removal of the JSON structure. Any instructions to write fluent prose or natural language apply inside JSON string values only. Finish the complete JSON object within the available output budget.""",
}


def get_model_adapter(name):
    """Return the selected adapter, falling back to Generic."""
    return _MODEL_ADAPTERS.get(name, _MODEL_ADAPTERS["Generic"])
