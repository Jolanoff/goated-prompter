"""Independent, intentionally tunable task-mode adapters."""

MODE_NAMES = (
    "Enhance",
    "Archviz",
    "Photography",
    "Character",
    "Product",
    "Image Edit",
    "Style Transfer",
    "Dataset Caption",
    "Video",
    "Custom",
)

_MODE_ADAPTERS = {
    "Enhance": """Enhance mode: improve clarity, visual specificity, and coherence while preserving the original meaning. Under Strict creativity, make only minimal necessary changes.""",
    "Archviz": """Archviz mode: act as an architectural visual director and architectural photographer. Describe spatial relationships, furniture, believable scale, camera height, useful focal-length implications, controlled verticals, composition, window and practical lighting, and physically plausible materials including surface response, roughness, texture, and natural imperfections. Treat wood, stone, plaster, concrete, glass, metal, and textiles precisely when present. Do not arbitrarily redesign architecture, geometry, layout, furniture, or specified finishes.""",
    "Photography": """Photography mode: use photographic composition, camera position, focal length only where useful, depth of field, exposure character, lighting direction and quality, color response, and restrained realistic imperfections. Prefer credible editorial, commercial, or documentary language appropriate to the idea.""",
    "Character": """Character mode: prioritize subject identity and description, coherent pose and anatomy, expression, clothing, framing, environment, lighting, and camera language. Keep all character details mutually consistent.""",
    "Product": """Product mode: preserve and clearly describe product geometry, materials, finish, surface response, scale, studio or environmental setup, lighting, background, composition, and credible commercial-photography treatment.""",
    "Image Edit": """Image Edit mode: state the requested change precisely and protect everything not explicitly requested to change. Preserve identity, geometry, layout, composition, viewpoint, materials, lighting, colors, background, and unaffected details unless the user explicitly asks to alter them. Make the change-versus-preserve boundary unambiguous in the final prompt.""",
    "Style Transfer": """Style Transfer mode: describe the requested visual treatment, medium, rendering language, palette behavior, texture, and finish while preserving subject identity and composition whenever the settings request it. Change content only when the idea explicitly requires it.""",
    "Dataset Caption": """Dataset Caption mode: produce one factual, concrete caption suitable for an image or LoRA dataset. Describe visible subject, attributes, action, environment, composition, and relevant style without promotional language, invented context, or artistic filler.""",
    "Video": """Video mode: construct a temporal shot, not a static image prompt. Establish the initial framing, chronological subject action, environmental movement, camera movement, timing or progression, continuity, transitions when requested, and the final framing. Keep movement physically and spatially coherent from beginning to end.""",
    "Custom": """Custom mode: treat the user's Custom instructions as the primary task modifier while retaining the Goated Prompter output contract and any explicit preservation constraints.""",
}

_VISION_MODE_ADAPTERS = {
    "Archviz": """Archviz image grounding: analyze the visible architecture, geometry, room layout, composition, camera height, perspective, furniture, spatial relationships, materials, surface response, lighting, and palette. Treat visible geometry and layout as ground truth and preserve them unless the user explicitly requests a redesign.""",
    "Image Edit": """Image Edit grounding: treat the image as the source state. Separate observed content from the requested change, describe that change precisely, and strongly preserve every visible element not requested to change.""",
    "Photography": """Photography image grounding: use the actual subject, composition, framing, viewpoint, lighting, and environment as the starting truth. Improve the prompt without arbitrarily replacing or restaging the visible scene.""",
    "Video": """Video image grounding: treat the connected image as the exact initial frame. Begin action and camera movement from what is visibly present, maintain spatial continuity, describe subject and environmental motion chronologically, and end with a coherent final framing.""",
    "Dataset Caption": """Dataset Caption image grounding: caption visible content factually. Do not infer unsupported identity, context, events, materials, or artistic intent, and avoid decorative prose.""",
}

_DEFAULT_VISION_ADAPTER = """Image grounding: distinguish OBSERVED IMAGE CONTENT from USER REQUESTED CHANGES. Treat visible subject, environment, geometry, layout, composition, framing, camera, perspective, materials, objects, people, clothing, lighting, colors, surfaces, and style cues as ground truth. Do not hallucinate changes to visible content unless the user requests them or the selected mode requires them."""


def get_mode_adapter(name):
    """Return the selected adapter, falling back conservatively to Enhance."""
    return _MODE_ADAPTERS.get(name, _MODE_ADAPTERS["Enhance"])


def get_vision_mode_adapter(name):
    """Return general visual grounding plus any mode-specific constraints."""
    specific = _VISION_MODE_ADAPTERS.get(name)
    return f"{_DEFAULT_VISION_ADAPTER}\n\n{specific}" if specific else _DEFAULT_VISION_ADAPTER
