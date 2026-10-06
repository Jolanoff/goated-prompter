"""Target-model names and output adapters."""

from dataclasses import dataclass

from .details import LENGTH_ADAPTERS

TARGET_MODEL_NAMES = ("Generic", "Anima", "Krea 2", "FLUX.2 Klein", "Z-Image Base", "Z-Image Turbo", "Qwen Image (original)", "Qwen Image 2.1", "MiniMax H3", "LTX 2.5", "Ideogram4")
TARGET_ALIASES = {"Z-Image": "Z-Image Base", "Qwen Image": "Qwen Image (original)",
                  "Qwen2.1": "Qwen Image 2.1", "MiniMax": "MiniMax H3"}


def canonical_target(name):
    return TARGET_ALIASES.get(name, name) if isinstance(name, str) else name


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
        detail_envelope="Use coherent natural-language visual direction in the requested medium. Under Creative/Dice leave useful aesthetic freedom rather than specifying every visual decision."),
    "FLUX.2 Klein": TargetCapabilities(supports_image_edit=True, positive_description_only=True,
        detail_envelope="Moderately detailed, focused natural-language prose even at Maximum Detail; avoid extreme verbosity and keyword piles."),
    "Z-Image Base": TargetCapabilities(supports_negative_prompt=True, supports_cfg=True),
    "Z-Image Turbo": TargetCapabilities(positive_description_only=True, supports_cfg=False),
    "Qwen Image (original)": TargetCapabilities(supports_negative_prompt=True, positive_description_only=False),
    "Qwen Image 2.1": TargetCapabilities(supports_image_edit=True, prompt_style="observer_description",
        detail_envelope="Preserve the rich observer-description structure and whole-frame closing sentence. Short compresses; Detailed/Maximum enrich supported positional, material and lighting descriptions."),
    "MiniMax H3": TargetCapabilities(output_format="minimax_fields", prompt_style="temporal_sections",
        supports_image_edit=True, supports_structured_output=True, supports_audio=True, supports_multishot=True,
        detail_envelope="Keep H3 required sections, reference roles and requested timeline complete at every length; enrich shot staging, not repeated static inventories."),
    "LTX 2.5": TargetCapabilities(prompt_style="flowing_video_paragraph", supports_audio=True,
        detail_envelope="One focused flowing paragraph, not an oversized essay even at Maximum Detail. Preserve chronological concrete motion; never invent dialogue, camera movement or cuts."),
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
   
    "Anima": """Anima target: use a hybrid of Danbooru/Gelbooru-style character tags and natural-language scene description. Use lowercase-style tags where appropriate, subject-count/general character tags and useful scene tags. Model-supported quality/meta tags such as masterpiece, best quality and score tags are allowed where appropriate; this target-specific allowance overrides the generic quality-slogan default. Negative conditioning belongs only in a separate negative prompt if that channel exists; never concatenate it into positive prose.
    When the user's input contains character tag blocks, preserve each named character's tags as a distinct block instead of merging all attributes into one global tag list. Keep character-specific count tags such as 1boy or 1girl inside their respective character blocks when supplied. A scene-level count such as 3boys, 3girls may appear once at the beginning.
    After the character blocks, use fluent natural language to construct the requested scene. Clearly assign each character's position, pose, action, expression, interaction, and relationship to the environment by naming the character. Use the tagged appearance and clothing as character facts and do not randomly exchange attributes between characters.
    Do not rewrite a well-structured character tag block into generic prose, and do not flatten multiple characters into one ambiguous tag pile. Add only useful shared scene tags when appropriate. The active Director, creativity, and prompt-length settings determine how elaborate the scene, composition, lighting, atmosphere, and visual direction should become.""",

    "Krea 2": """Krea 2 target: use coherent natural-language visual direction. Make subject, action/state, composition, spatial relationships, environment, materials where useful, lighting and the requested visual medium clear. For photographic requests, use appropriate photographic language. For anime, illustration, painting, graphic design, 3D or other non-photographic requests, preserve that medium and do not force photographic rendering. Under Creative/Dice leave useful aesthetic freedom rather than describing every visual decision. Avoid disconnected keyword piles and unnecessary stylistic defaults.""",
    "FLUX.2 Klein": """FLUX.2 Klein target: use moderately detailed natural-language prose, subject/action first, then setting, important appearance/material details, spatial relationships and lighting. Use positive visible description, not negative prompt syntax or keyword piles. For editing distinguish requested changes from protected content. Maximum Detail stays focused within a useful moderate prose envelope; avoid extreme verbosity.""",
    "Z-Image Base": """Z-Image Base target: the non-distilled Base variant. Use straightforward descriptive prose with clear subjects, action and visual relationships. Keep generator settings and separate negative conditioning out of positive prose.""",
    "Z-Image Turbo": """Z-Image Turbo target: the distilled Turbo variant. Use straightforward descriptive positive prose with clear subjects, action and visual relationships. Keep generator settings out of positive prose.""",
    "Qwen Image (original)": """Qwen Image (original) target: the original Qwen/Qwen-Image checkpoint, not Qwen Image 2.1. Use natural descriptive language emphasizing subject attributes, relationships, composition, pose/action, anatomical plausibility, lighting and literal visible text when requested. Preserve text exactly.""",
    "Qwen Image 2.1": """Qwen Image 2.1 text-to-image rewrite: return only the complete plain prompt text. No JSON object, metadata fields, commentary or Markdown fences.

Write an English observer's description of the finished image, present tense and third person, never addressing the user or renderer. Preserve every fixed subject, count, color, position, named object and literal visible-text string. Preserve text character-for-character in its original script, punctuation and spacing; only visible text is enclosed in straight double quotes. Do not invent signage where none was requested. Obey job instructions silently instead of echoing them as picture content.

First decide the frame from the user's explicit format when one is part of the creative request; otherwise choose a horizontal, vertical, square or wide composition appropriate to the subject. Apply that choice to natural composition and placement without emitting size metadata.

Open by naming medium, style, subject and background/palette, usually with orientation. Inventory each element and its position, then walk the frame from background and top through left/center/right to bottom, or walk a single subject from background/pose through head, body, garments, contacts and remaining edges. Use concrete positional phrases throughout, including corners and edges. Describe actual materials, nuanced colors, scale, occlusion, spatial relationships, pose and coherent lighting/shadow/reflection behavior. Enumerate items rather than saying various decorations; use object classes unless the user named a brand. Hedge genuinely ambiguous details without weakening user-fixed facts. Name the source, direction and quality of light explicitly, generally in its own sentence. End with exactly one whole-frame composition sentence.

Respect the application's selected length and creativity controls: Short stays compact, Medium balanced, Detailed rich, and Maximum Detail expansive with useful concrete detail. Normally use one paragraph; genuinely stacked panels/cards/sections may use one paragraph per region. Keep literal image text in its original language while all descriptive prose is English. Avoid instructions, quality slogans, filler and a second closing summary.""",
    "MiniMax H3": """MiniMax H3 target: in Video mode return H3 named fields, not JSON or a generic prose wrapper: integrated_multimodal_description, overall_soundscape, non_diegetic_music. Put concrete chronological action and synchronized requested sound in the integrated description; use [Shot N] and contiguous time ranges only for requested multishot/timeline staging. Preserve literal dialogue; never invent dialogue or reference contents. With full references use subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music, with registered <Picture N>, <Video N>, <Audio N> labels and only requested transfer/retention roles. Explicit first/last-frame anchors require their corresponding alignment instruction; identity-only references are not first frames. Do not fabricate durations, assets, audio reuse or cuts. In non-video tasks keep the selected Mode's task without inventing a video timeline.""",
    "LTX 2.5": """LTX 2.5 target: in Video mode write one focused flowing paragraph. Put the main action early; describe literal concrete chronological motion with active/present-progressive language, coherent environment and lighting, and audio when applicable. Do not automatically invent dialogue, camera movement or cuts unless requested or required. Keep a focused useful prompt envelope even at Maximum Detail, not an oversized essay. In other modes preserve the selected task.""",

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
    return MODEL_ADAPTERS.get(canonical_target(name), MODEL_ADAPTERS["Generic"])
