"""Target-model names and output adapters."""

from dataclasses import dataclass

from .details import LENGTH_ADAPTERS
from ..options.targets import canonical_target


@dataclass(frozen=True)
class TargetCapabilities:
    output_format: str = "text"
    prompt_style: str = "natural_language"
    supports_negative_prompt: bool = False
    supports_image_edit: bool = False
    supports_visible_text: bool = True
    supports_structured_output: bool = False
    supports_audio: bool = False
    supports_multishot: bool = False
    positive_description_only: bool = False
    supports_cfg: bool | None = None
    detail_envelope: str = "Use relevant description without filler; preserve required target structure."

    def resolve_length(self, user_length):
        rules = LENGTH_ADAPTERS
        length = "Maximum Detail" if user_length == "Maximum" else user_length
        return rules.get(length, rules["Medium"]) + "\nTARGET DETAIL ENVELOPE: " + self.detail_envelope


TARGET_CAPABILITIES = {
    "Generic": TargetCapabilities(),
    "Anima": TargetCapabilities(prompt_style="tags_and_scene", supports_negative_prompt=True,
        detail_envelope="Keep useful lowercase-style tags, subject counts and scene prose. Density changes prose, never tag/block structure."),
    "Krea 2": TargetCapabilities(supports_image_edit=True,
        detail_envelope="Long, exhaustive natural-language description in the requested medium; more length adds concrete visible detail (pose, fabric, light falloff, background positions, camera), never filler."),
    "FLUX.2 Klein": TargetCapabilities(supports_image_edit=True, positive_description_only=True,
        detail_envelope="Moderately detailed, focused natural-language prose at every length; avoid extreme verbosity and keyword piles."),
    "Z-Image Base": TargetCapabilities(supports_negative_prompt=True, supports_cfg=True),
    "Z-Image Turbo": TargetCapabilities(positive_description_only=True, supports_cfg=False),
    "Qwen Image (original)": TargetCapabilities(supports_negative_prompt=True, positive_description_only=False),
    "Qwen Image 2.1": TargetCapabilities(supports_image_edit=True, prompt_style="observer_description",
        detail_envelope="Preserve the observer-description structure and whole-frame closing sentence at every length; extra length enriches supported positional, material and lighting descriptions."),
    "MiniMax H3": TargetCapabilities(output_format="minimax_fields", prompt_style="temporal_sections",
        supports_image_edit=True, supports_structured_output=True, supports_audio=True, supports_multishot=True,
        detail_envelope="Keep H3 required sections, reference roles and requested timeline complete at every length; enrich shot staging, not repeated static inventories."),
    "LTX 2.5": TargetCapabilities(prompt_style="flowing_video_paragraph", supports_audio=True,
        detail_envelope="One focused flowing paragraph at every length, never an oversized essay. Preserve chronological concrete motion; never invent dialogue, camera movement or cuts."),
    "Ideogram4": TargetCapabilities(output_format="json", prompt_style="structured_caption", supports_structured_output=True,
        detail_envelope="All required JSON keys and their order remain intact at every length. Density changes descriptive string values only."),
}


def get_target_capabilities(name):
    return TARGET_CAPABILITIES.get(canonical_target(name), TARGET_CAPABILITIES["Generic"])


def resolve_target_length(name, length):
    return get_target_capabilities(name).resolve_length(length)

QWEN21_EDIT_ADAPTER = """Qwen Image 2.1 image-editing rewrite: an input image or selected image evidence is present. Return only the complete plain prompt text. No JSON object, metadata fields, commentary or Markdown fences.

Write a precise, affirmative editing instruction, leading with the requested operation rather than describing a finished picture. Edit exactly the named attributes to a strong, unmistakable degree while preserving all untargeted content at input fidelity. Avoid both leakage into unrelated attributes and under-editing. For a local edit, constrain the change with one blanket preservation clause rather than repainting unchanged details. For a requested new scene built from references, construct that scene with appropriate composition, staging and lighting, retaining the assigned identity and reference roles. Never invent uncertain evidence, clean up unrequested defects or weaken the requested operation. Identity, personal accessories, product design/markings/count and rendering medium remain invariant unless explicitly targeted. Reference identity by source rather than regenerating a verbal feature inventory.

For multiple selected input images, use their supplied <imageN> tags individually, state each source's role and identify the canvas whose composition survives. Never use image A, the first image or grouped ranges instead of tags. For a single selected image, refer naturally to "the image" without a tag. Keep source numbering stable.

Use the user's explicit format only when it is part of the creative request. Do not emit size metadata; the user sets dimensions in the image generator.

Without a requested format, ordinary single-image editing retains the source framing. For multi-image editing choose composition from the edit purpose: destination scene for compositing, body for face swaps, person for clothing swaps, content for style transfer, foreground subject for background replacement, original edited image for local object replacement. For a new scene using references only for identity, design a composition appropriate to the requested subject. Outpainting explicitly names the extension and its direction rather than blindly retaining the original framing. Multi-view/grid compositions derive from subject proportions and panel arrangement, not a fixed wide default.

Write a continuous editing directive, without ellipses or truncation. Be decisive, precise and affirmative, with no unresolved alternatives. The selected prompt length controls the amount of useful description.

Descriptive prose is Chinese for a Chinese instruction, otherwise English. Visible image text is a separate language decision: exact user-provided text or requested language first, otherwise the image's dominant text language, otherwise the user's instruction language. Preserve exact readable strings in straight double quotes. Each rendered string is monolingual unless bilingual text was explicitly requested; genre does not change its language. Do not quote descriptive prose as if it were rendered text. Never guess unreadable source text."""

MODEL_ADAPTERS = {
    "Generic": """Generic target: write clean, coherent natural-language visual description without model-specific syntax or tag chains.""",
    "Anima": """Anima target: use a hybrid of Danbooru/Gelbooru-style tags and concise natural-language scene prose. Start with one comma-separated sequence of relevant lowercase tags, including the correct subject-count tags (for example 3boys, or 1boy, 1girl); use solo only when exactly one character appears, never with several. Follow the tags with fluent prose describing the composition, actions, expressions, spatial relationships and interactions. Use recognizable tags for character appearance, clothing, poses, objects, environment and visual style. Quality and score tags such as masterpiece, best quality and score_7 are allowed where appropriate. Preserve each character's supplied identity and attributes, keeping them correctly assigned in multi-character scenes. Avoid redundant tags, excessive tag counts, negative prompt terms and repeating the tag inventory in prose. Preserve supplied tag wording, order, weights, repetitions and locked trigger prefixes when required. Keep the result visually specific, coherent and focused on the requested image.""",
    "Krea 2": """Krea 2 target: its large language-model text encoder rewards long, exhaustive natural-language description, so describe everything visible rather than summarizing. Cover the subject's apparent age, look, hair styling, makeup and exact expression; clothing with fabric, fit and how it falls or moves; the pose as one coherent body, described once from head to feet; background elements with their positions; light with its source, direction and what it falls on (face, shoulders, fabric) and where shadows land; composition with aspect, one shot size, where the subject sits in the frame, one camera angle, focus and depth of field. Always name a medium, era or process (for example a realistic street-style snapshot, a 35mm film photograph, a gouache painting, a 3D render); without one the result drifts to a generic house style. For photographs keep materials, skin and fabric texture natural and unretouched. For anime, illustration, painting, graphic design or 3D, keep that medium and do not force photographic rendering. Under Creative/Dice leave useful aesthetic freedom in the choices you make, but still write them out in full. Keep any supplied trigger or LoRA token first. Put words to render in the image in double quotes. Avoid keyword piles and empty quality slogans.""",
    "FLUX.2 Klein": """FLUX.2 Klein target: write focused natural-language prose in the order subject, action, style, context; the model weighs what comes first most, so lead with the main subject and action. Aim for roughly 40 to 100 words. Lighting is the most influential detail: name its source, direction and quality. For photographs a specific camera, lens, aperture or film stock (for example 35mm f/1.4, Portra 400) works better than "professional photo". The model has no negative prompt: describe what should be visible ("sharp focus throughout"), never what to avoid. Put words to render in double quotes with their placement and style. For editing distinguish requested changes from protected content.""",
    "Z-Image Base": """Z-Image Base target: the non-distilled Base variant. Write concrete, objective descriptive prose of roughly 30 to 120 words: a description, not a keyword list. Keep every subject, count, action, color and text exactly, then add composition, light and atmosphere, material texture, color scheme and depth layers. Spell out specific attributes such as age, hair, clothing and the exact place; vague wording collapses to the same image every time. Use one dominant style. No metaphors, emotional adjectives or quality tags such as 8K or masterpiece. Put text to render in double quotes with its font, layout and material. Keep generator settings and separate negative conditioning out of positive prose.""",
    "Z-Image Turbo": """Z-Image Turbo target: the distilled Turbo variant, which has no negative prompt. Write concrete, objective descriptive prose of roughly 30 to 120 words: a description, not a keyword list. Keep every subject, count, action, color and text exactly, then add composition, light and atmosphere, material texture, color scheme and depth layers. Spell out specific attributes such as age, hair, clothing and the exact place; vague wording collapses to the same image every time. Use one dominant style and state anything to exclude as a positive fact. No metaphors, emotional adjectives or quality tags such as 8K or masterpiece. Put text to render in double quotes with its font, layout and material. Keep generator settings out of the prompt.""",
    "Qwen Image (original)": """Qwen Image (original) target: the original Qwen/Qwen-Image checkpoint, not Qwen Image 2.1. Write one natural descriptive paragraph under about 200 words covering subject attributes, relationships, spatial layout, shot composition, pose/action, anatomical plausibility and lighting. Choose a precise style rather than a vague one; for realism name the capture style (for example a casual phone snapshot or a 50mm editorial portrait) and natural detail such as skin texture and age lines, avoiding a waxy, over-smoothed or oversaturated look. Put requested visible text in double quotes, unaltered and untranslated.""",
    "Qwen Image 2.1": """Qwen Image 2.1 text-to-image rewrite: return only the complete plain prompt text. No JSON object, metadata fields, commentary or Markdown fences.

Write an English observer's description of the finished image, present tense and third person, never addressing the user or renderer. Preserve every fixed subject, count, color, position, named object and literal visible-text string. Preserve text character-for-character in its original script, punctuation and spacing; only visible text is enclosed in straight double quotes. Do not invent signage where none was requested. Obey job instructions silently instead of echoing them as picture content.

First decide the frame from the user's explicit format when one is part of the creative request; otherwise choose a horizontal, vertical, square or wide composition appropriate to the subject. Apply that choice to natural composition and placement without emitting size metadata.

Open by naming medium, style, subject and background/palette, usually with orientation. Inventory each element and its position, then walk the frame from background and top through left/center/right to bottom, or walk a single subject from background/pose through head, body, garments, contacts and remaining edges. Use concrete positional phrases throughout, including corners and edges. Describe actual materials, nuanced colors, scale, occlusion, spatial relationships, pose and coherent lighting/shadow/reflection behavior. Enumerate items rather than saying various decorations; use object classes unless the user named a brand. Hedge genuinely ambiguous details without weakening user-fixed facts. Name the source, direction and quality of light explicitly, generally in its own sentence. End with exactly one whole-frame composition sentence.

Normally use one paragraph; genuinely stacked panels/cards/sections may use one paragraph per region. Keep literal image text in its original language while all descriptive prose is English. Avoid instructions, quality slogans, filler and a second closing summary.""",
    "MiniMax H3": """MiniMax H3 target: in Video mode return H3 named fields, not JSON or a generic prose wrapper: integrated_multimodal_description, overall_soundscape, non_diegetic_music. Put concrete chronological action and synchronized requested sound in the integrated description; use [Shot N] and contiguous time ranges only for requested multishot/timeline staging. Preserve literal dialogue; never invent dialogue or reference contents. With full references use subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music, with registered <Picture N>, <Video N>, <Audio N> labels and only requested transfer/retention roles. Explicit first/last-frame anchors require their corresponding alignment instruction; identity-only references are not first frames. Do not fabricate durations, assets, audio reuse or cuts. In non-video tasks keep the selected Mode's task without inventing a video timeline.""",
    "LTX 2.5": """LTX 2.5 target: in Video mode write one flowing present-tense paragraph of four to eight sentences, at most about 200 words, in this order: shot type; the scene with its light, palette and texture; the action from start to finish; the characters' age, hair and clothing; any requested camera movement and how subjects look after it; audio with a visible source. Show emotion through physical cues rather than labels. Put any requested dialogue in quotes with its language. Avoid readable text, logos, crowded scenes and chaotic physics. Do not invent dialogue, camera movement or cuts unless requested. In other modes preserve the selected task.""",

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

# A suggested layout is only a default: when the user's library supplies templates, their
# structure decides the layout instead.
ADAPTER_LAYOUTS = {
    "Krea 2": 'Long prompts may be organized into labeled sections such as "Subject and action:", "Clothing and '
              'pose:", "Background and lighting:", "Composition and camera:" and "Aesthetic and style:".',
}


def get_model_adapter(name, *, templates=False):
    """Return the selected adapter, falling back to Generic; without templates it adds the default layout."""
    target = canonical_target(name)
    adapter = MODEL_ADAPTERS.get(target, MODEL_ADAPTERS["Generic"])
    layout = ADAPTER_LAYOUTS.get(target)
    return adapter if templates or not layout else f"{adapter} {layout}"


# Edit instructions are not covered by the prompt library (it holds generation prompts), so
# Qwen Image 2.1 editing keeps one worked example.
QWEN21_EDIT_EXAMPLE = (
    "make the sky a sunset",
    "Replace the overcast sky in the image with a clear sunset sky in warm orange and pink gradients, and "
    "relight the scene with low golden light from the left to match. Keep the buildings, people, street "
    "layout, framing and all other content exactly as in the image.",
)


def library_reference_section(references, *, continuation=False):
    """Present user library prompts as templates for how a good prompt is built, not for its look."""
    if not references:
        return ""
    numbered = "\n\n".join(f"Template {index}:\n{prompt}" for index, prompt in enumerate(references, 1))
    return ("TEMPLATES FROM THE USER'S PROMPT LIBRARY\n"
            "The user saved these prompts as examples of how a good prompt for this model is written. Use them as "
            "templates for the craft: the structure (one paragraph, labeled sections, a tag list, a trigger word "
            "first), the order of information, how concretely each subject, pose, outfit, camera and light is "
            "described, and how dense the detail is. Do not take the look of the image from them: the medium, visual "
            "style, aesthetic, palette, mood, subjects, names, setting and sentences come from this request, the "
            "selected Style and the Director. Where the templates differ in structure, follow whichever suits this "
            "image. The selected length still sets roughly how long, and the target's required format still applies."
            "\n\n" + numbered
            + ("\n\nYour output is only the continuation after the app-inserted character tags; do not repeat character tags."
               if continuation else ""))


def get_target_example(name, *, qwen_task="t2i"):
    """Return the worked example for Qwen Image 2.1 editing, or an empty string.

    Generation prompts learn their form from the user's library templates instead.
    """
    if canonical_target(name) != "Qwen Image 2.1" or qwen_task != "edit":
        return ""
    request, output = QWEN21_EDIT_EXAMPLE
    return ("STYLE EXAMPLE (a different subject: copy its form, never its content; follow the selected length, "
            "not this example's)\nRequest: " + request + "\nOutput:\n" + output)
