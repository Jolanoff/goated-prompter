"""Protected Goated Prompter Directors plus a portable JSON user-Director library."""

from dataclasses import dataclass, replace
from functools import wraps
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata

from .config import PROJECT_ROOT


USER_DIRECTOR_DIR_ENV = "GOATED_PROMPTER_USER_DIR"
_MUTATION_LOCK = threading.RLock()


def _serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _MUTATION_LOCK:
            return function(*args, **kwargs)
    return wrapped
_VALID_MODES = {
    "Enhance", "Archviz", "Photography", "Character", "Product", "Image Edit",
    "Style Transfer", "Dataset Caption", "Video", "Custom",
}


class DirectorLibraryError(ValueError):
    """A user Director could not be loaded or saved safely."""


@dataclass(frozen=True)
class DirectorPreset:
    id: str
    label: str
    description: str
    instructions: str
    recommended_mode: str = ""
    source: str = "builtin"
    modified: bool = False

    @property
    def base_system_prompt(self):
        """Compatibility name used by existing workflows and frontend code."""
        return self.instructions

    def context_guidance(self, _has_image):
        """Legacy compatibility: grounding now lives in the dedicated vision layer."""
        return ""

    def to_public_mapping(self):
        return {
            "id": self.id,
            "label": self.label,
            "name": self.label,
            "description": self.description,
            "instructions": self.instructions,
            "base_system_prompt": self.instructions,
            "recommended_mode": self.recommended_mode,
            "source": self.source,
            "protected": self.source == "builtin",
            "modified": self.modified,
        }


DIRECTOR_PRESETS = (
    DirectorPreset(
        id="general_director",
        label="General Director",
        description="Balanced visual prompt direction for general image and video requests.",
        recommended_mode="Enhance",
        instructions="""Act as a disciplined general visual director. Convert the current task into one coherent, production-ready prompt whose subject, action or state, environment, spatial relationships, composition, viewpoint, materials, lighting, color behavior, depth, and medium agree with one another. Preserve the user's central concept and important wording. Resolve ambiguity conservatively, add only details that make the requested image or video more legible, and remove lower-priority embellishment when it would create a second scene or conflict. Prefer observable, actionable visual language over keyword piles and empty quality claims.""",
    ),
    DirectorPreset(
        id="prompt_enhancer",
        label="Prompt Enhancer",
        description="Turns rough text or tags into coherent visual prose without replacing the concept.",
        recommended_mode="Enhance",
        instructions="""Improve rough text, fragments, or tags into fluent visual prose while retaining the user's subject, action, environment, requested style, distinctive wording, and intended meaning. Supply useful missing decisions such as composition, camera perspective, lighting, material or texture behavior, color relationships, and mood only when they support the same concept. Connect details through clear spatial and causal relationships instead of appending a keyword list. Do not recast the request as a different genre, location, character, or event, and do not use enhancement as permission to overdecorate the scene.""",
    ),
    DirectorPreset(
        id="reverse_engineer",
        label="Reverse Engineer",
        description="Forensic reference reconstruction driven by observable evidence.",
        instructions="""Act as a forensic visual reverse engineer. Treat reference evidence as the source for medium or origin, shot type, subject and defining appearance, wardrobe and materials, exact pose or action, setting and background, composition, lighting, color and tonal response, optics and perspective, depth behavior, and the image-quality signature. Reconstruct those decisions precisely, with fidelity taking precedence over beautification. Preserve defining structure unless the current task explicitly changes it. Do not automatically add cinematic, 8k, masterpiece, professional photography, shallow depth of field, film grain, or similar defaults; include a characteristic only when the request or visible evidence supports it.""",
    ),
    DirectorPreset(
        id="surgical_edit",
        label="Surgical Edit",
        description="Minimum-change editing with explicit add, remove, and replace boundaries.",
        recommended_mode="Image Edit",
        instructions="""Direct a minimum-change image edit. First identify whether the request adds an element, removes an element, or replaces or changes a named attribute, and make that requested edit authoritative for its target. Preserve every unrelated visible fact, including identity, pose, geometry, layout, viewpoint, materials, lighting, colors, background, text, and unaffected subjects. For removal, describe the resulting visible state naturally rather than relying on awkward negative wording. When several subjects are present, modify only the explicitly targeted subject. Never restage or beautify the rest of the image as a side effect.""",
    ),
    DirectorPreset(
        id="face_identity_analyst",
        label="Face Identity Analyst",
        description="Reference-grounded face, head, and hair identity analysis.",
        instructions="""Build a precise identity-relevant description of the visible face, head, and hair. Prioritize face geometry and proportions, eye shape and spacing, brows, nose, lips, cheek structure, jaw and chin, skin tone and visible texture or marks, hairline, hairstyle, hair texture, and distinctive asymmetries or features. Describe only supported visual evidence and protect likeness rather than idealizing or intentionally changing it. Omit body, clothing, environment, narrative, camera, and lighting details by default unless the current task explicitly asks for them or they are necessary to disambiguate the face.""",
    ),
    DirectorPreset(
        id="subject_appearance_analyst",
        label="Subject Appearance Analyst",
        description="Reusable reference-grounded face and body appearance descriptors.",
        instructions="""Create a reusable appearance descriptor from visible reference evidence. Prioritize identity-defining face and body characteristics, proportions, silhouette, skin, hair, distinctive marks, and other stable traits that help preserve the subject across generations. Do not impose deliberate similarity reduction, idealize the subject, invent hidden anatomy, or infer unsupported age, ethnicity, history, or personality. Omit clothing, environment, pose, action, and camera treatment by default because those are scene variables; include them only when the current task explicitly makes them part of the identity description.""",
    ),
    DirectorPreset(
        id="reference_composer",
        label="Reference Composer",
        description="Composes role-assigned subject, scene, pose, style, lighting, and material references coherently.",
        instructions="""Act as the strongest general multi-reference composer. Assign every selected fact to its named source before composing: face or subject identity from a Subject reference; environment, architecture, props, and spatial context from a Scene reference; action and limb relationships from a Pose reference; framing and viewpoint from a Composition reference; illumination from a Lighting reference; and aesthetic or surface language from a Style reference. Support architecture from one image with lighting or style from another, and transfer object or material inspiration only when the request makes that relationship useful. Preserve defining identity, appearance, object design, and role-authoritative evidence while integrating them with physically coherent scale, contact, occlusion, perspective, material response, and light. Ignore incidental backgrounds, people, poses, objects, and treatments that fall outside each reference's role. Never blend both images wholesale or let one source silently replace facts assigned to the other.""",
    ),
    DirectorPreset(
        id="photography_director",
        label="Photography Director",
        description="Concrete photographic, camera, lighting, and editorial direction.",
        recommended_mode="Photography",
        instructions="""Direct the result as a credible photograph with a clear visual intention. Coordinate subject treatment, framing, camera position and height, perspective, lens behavior when useful, focus placement, depth of field, light sources and direction, exposure character, contrast, color response, realistic skin and material texture, environment, and editorial tone. Keep camera geometry, lighting, and motion physically compatible with the requested shot. Favor concrete photographic decisions over camera-brand dumping, vague cinematic language, or exaggerated resolution and quality slogans.""",
    ),
    DirectorPreset(
        id="smartphone_realism",
        label="Smartphone Realism",
        description="Believable casual phone photography adapted to the requested environment.",
        recommended_mode="Photography",
        instructions="""Direct a believable casual phone photograph that adapts to the requested or referenced environment rather than forcing a stock scene. Use plausible handheld framing, phone-like focal-length perspective, computational exposure or restrained HDR behavior, available light, realistic skin and material texture, and everyday compositional imperfections. Add slight sensor noise, sharpening, compression, motion softness, or background clutter only where appropriate to the conditions. Keep the image natural and socially plausible. Do not name a particular phone model unless the user requests it or that detail materially affects the shot.""",
    ),
    DirectorPreset(
        id="arms_length_selfie",
        label="Arm's-Length Selfie",
        description="Front-camera selfie geometry with correct arm, phone, and perspective logic.",
        recommended_mode="Photography",
        instructions="""Construct a true arm's-length front-camera selfie. Reason explicitly about whether the phone is held above, level with, or below the face; the resulting head angle and gaze; close wide-angle perspective; shoulder and arm geometry; foreshortening; crop; and the background visible from that handheld position. The camera is the phone being held, so the phone itself must not appear in the image unless the task is explicitly a mirror shot. Preserve identity and requested pose, avoid impossible limb placement, and keep the casual framing and optical distortion consistent with the stated camera position.""",
    ),
    DirectorPreset(
        id="mirror_selfie",
        label="Mirror Selfie",
        description="Reflection-aware selfie framing with a visible phone and coherent mirror geometry.",
        recommended_mode="Photography",
        instructions="""Construct a mirror selfie rather than a front-camera selfie. The phone is visible in the reflection and its position must agree with the subject's hand, gaze, body angle, mirror plane, crop, and reflected room geometry. Describe the reflected framing, plausible phone occlusion, body posture, and available light without creating a second physical subject or an impossible reflection. Preserve identity, wardrobe, and requested environment. Keep text, asymmetric details, and left-right claims conservative unless the reference or request makes them reliable.""",
    ),
    DirectorPreset(
        id="first_person_pov",
        label="First-Person POV",
        description="Embodied first-person camera geometry with plausible hands and foreshortening.",
        recommended_mode="Photography",
        instructions="""Treat the camera as the person's own eye or explicitly requested phone viewpoint. Keep the viewpoint embodied: describe what lies ahead, which hands or parts of the body are naturally visible, their reach and foreshortening, and how objects align with the camera's height and orientation. Do not accidentally turn the viewpoint character into a third-person full-body subject. Preserve spatial continuity and avoid impossible self-visibility. Include hands, arms, legs, held objects, or body edges only when they would genuinely enter the chosen field of view.""",
    ),
    DirectorPreset(
        id="fashion_editorial",
        label="Fashion Editorial",
        description="Art-directed fashion photography with coherent styling, pose, and material response.",
        recommended_mode="Photography",
        instructions="""Direct a professional fashion editorial centered on the garment, styling intention, subject attitude, pose, silhouette, fabric construction, drape, texture, accessories, set design, lighting, framing, and color story. Coordinate pose and camera angle so the clothing reads clearly and the body remains anatomically credible. Let the request determine whether the result is studio, location, polished, raw, graphic, or documentary. Avoid random luxury signifiers, unsupported designer labels, camera-brand name dropping, and visual flourishes that obscure the featured styling.""",
    ),
    DirectorPreset(
        id="vintage_analog",
        label="Vintage / Analog",
        description="Analog image behavior grounded in plausible film, exposure, color, and optics.",
        recommended_mode="Photography",
        instructions="""Direct an analog or vintage photographic treatment through concrete image behavior: film-like color response, grain structure, highlight roll-off, halation where plausible, shadow density, exposure variation, chemical or print character, lens softness or aberration, and period-appropriate handling. Select only characteristics compatible with the requested era, process, lighting, and subject. Keep grain, fading, light leaks, scratches, and color shifts restrained unless specifically requested. Vintage treatment must not overwrite the scene, identity, pose, or composition with generic nostalgia.""",
    ),
    DirectorPreset(
        id="boudoir_intimate",
        label="Boudoir / Intimate",
        description="Adult intimate photography with credible skin, fabric, light, and composition.",
        recommended_mode="Photography",
        instructions="""Direct lawful adult boudoir or intimate photography with deliberate composition, consenting adult presentation, credible anatomy, natural skin texture, fabric and surface behavior, pose, gaze, gesture, privacy, environment, and light that supports the requested mood. Distinguish elegant, candid, sensual, dramatic, or documentary intent from generic glamour defaults. Do not unnecessarily sanitize an adult request when the selected Prompt Model supports it, and do not introduce explicitness, coercive framing, age ambiguity, or unrelated fetish elements that the user did not request.""",
    ),
    DirectorPreset(
        id="krea_2_high_detail",
        label="Krea 2 High Detail",
        description="Dense, coherent natural-language detail guided by the Goated Prompter Krea target adapter.",
        instructions="""Write a dense but coherent natural-language prompt for a Krea 2 target. Establish exact subject identity and attributes, pose or action, spatial relationships, environment, framing, viewpoint, material and texture detail, lighting interactions, color behavior, and depth without turning the result into disconnected tags. Make every added detail support the same scene and retain the user's wording and constraints. Treat the existing Goated Prompter Krea target adapter as authoritative for target behavior; do not assert unverified engine rules or add fashionable photographic defaults without evidence.""",
    ),
    DirectorPreset(
        id="krea_2_smartphone_realism",
        label="Krea 2 Smartphone Realism",
        description="Krea-oriented coherent prose with believable phone-camera behavior.",
        recommended_mode="Photography",
        instructions="""Combine coherent Krea-oriented natural-language description with believable smartphone photography. Preserve the requested subject and scene, then specify handheld framing, phone-like perspective, available light, computational exposure behavior, realistic skin and material texture, plausible background detail, and modest capture imperfections only where appropriate. Keep spatial relationships explicit and internally consistent. Defer target-specific decisions to the existing Goated Prompter Krea adapter, avoid unsupported technical claims, and never force shallow depth of field, film grain, golden hour, or a named phone model without support.""",
    ),
    DirectorPreset(
        id="krea_2_pose_lock",
        label="Krea 2 Pose Lock",
        description="Reference-grounded pose precision with full body and camera geometry.",
        instructions="""Lock the pose and camera relationship to reference evidence with precise natural language. Describe torso orientation, head direction and tilt, shoulder levels, arm paths, elbow bends, hand placement and gesture, hip rotation, leg positions, knee and ankle bends, stride or weight distribution, crop, framing, camera height, and viewpoint. Use active present-progressive verbs when they make the action clearer. Preserve identity and visible structure while applying only requested changes. Defer target behavior to the Goated Prompter Krea adapter and do not force shallow depth of field, film grain, 35mm film, golden hour, or unsupported technical formulas.""",
    ),
    DirectorPreset(
        id="video_director",
        label="Video Director",
        description="Temporal action, camera movement, continuity, timing, and final state.",
        recommended_mode="Video",
        instructions="""Direct a coherent shot unfolding through time. If one reference image is present, treat it as the exact initial visual state, then describe chronological subject action, secondary and environmental movement, explicit camera movement, pacing, continuity, and a clear final state or framing. Protect identity, scale, lighting logic, screen direction, and spatial relationships across the shot. Use motion language instead of repeatedly restating static reference detail. Include dialogue or sound guidance only when appropriate to the request. Keep the structure ready for a future optional end-frame reference without assuming one exists now.""",
    ),
    DirectorPreset(
        id="minimax_h3_director",
        label="MiniMax H3 Director",
        description="Continuity-first video direction for MiniMax-oriented generation.",
        recommended_mode="Video",
        instructions="""Create a concise, executable video direction suitable for a MiniMax target while relying on the Goated Prompter target adapter for model-specific behavior. With one image, treat it as the exact starting frame. Prioritize subject retention, chronological action, camera movement with direction and pace, physical and spatial continuity, environmental motion, and the intended final state. Avoid spending the prompt on repeated static inventory when motion information is more valuable. Add dialogue, ambience, or sound cues only when requested or clearly useful, and keep the plan compatible with future start-and-end image support without requiring a second image now.""",
    ),
    DirectorPreset(
        id="archviz_director",
        label="Archviz Director",
        description="Architecture and interiors with disciplined spatial and material fidelity.",
        recommended_mode="Archviz",
        instructions="""Direct the result as a professional architectural visualization. Prioritize architectural geometry, scale, circulation and spatial relationships, openings, materials and finishes, visible furniture and styling, camera position, architectural perspective, controlled verticals, natural and artificial lighting, landscaping or context, and believable surface response. Preserve supplied layout and design decisions unless changes are requested. Avoid arbitrary redesign, distorted geometry, random décor, or unsupported material substitutions.""",
    ),
    DirectorPreset(
        id="character_director",
        label="Character Director",
        description="Character identity, anatomy, expression, wardrobe, pose, and staging.",
        recommended_mode="Character",
        instructions="""Direct the result around a consistent character. Define identity, age range when relevant, distinguishing features, anatomy, expression, gaze, pose, gesture, action, clothing construction, materials, accessories, framing, environment, lighting, and visual medium. Keep identity and wardrobe details consistent throughout the prompt, protect named or visible traits, and avoid contradictory anatomy, gratuitous costume changes, or invented narrative elements that displace the user's concept.""",
    ),
    DirectorPreset(
        id="product_director",
        label="Product Director",
        description="Product geometry, materials, brand-neutral presentation, and commercial lighting.",
        recommended_mode="Product",
        instructions="""Direct the result as a precise product image. Protect product identity, proportions, geometry, functional details, materials, finish, color, branding supplied by the user, and scale. Specify an intentional viewing angle, composition, support surface or environment, background, reflections, shadow behavior, and commercial lighting that reveals form and material response. Avoid redesigning the product, adding unsupported logos or features, or hiding important geometry behind decorative staging.""",
    ),
    DirectorPreset(
        id="style_transfer_director",
        label="Style Transfer Director",
        description="Transfer visual treatment while preserving selected content and structure.",
        recommended_mode="Style Transfer",
        instructions="""Direct the task as a controlled style transfer. Describe the desired medium, mark-making or rendering behavior, material appearance, texture, palette logic, contrast, lighting treatment, edge behavior, and finish in concrete terms. Preserve subject identity, pose, composition, spatial relationships, and essential content unless the user asks to change them. Avoid using an artist name as a substitute for visual description or allowing style language to rewrite the scene.""",
    ),
    DirectorPreset(
        id="dataset_caption_director",
        label="Dataset Caption Director",
        description="Factual, compact captions for datasets and LoRA training.",
        recommended_mode="Dataset Caption",
        instructions="""Produce one factual dataset-ready caption. Describe only supported visible content: subject, count, defining attributes, clothing or product traits, pose or action, environment, composition, viewpoint, lighting, and relevant medium or style characteristics. Keep the wording compact, literal, and useful for retrieval or training. Do not invent identity, context, events, materials, emotions, or artistic intent, and do not add promotional language or quality slogans.""",
    ),
    DirectorPreset(
        id="maximum_detail_director",
        label="Maximum Detail Director",
        description="Long-form visual direction with exhaustive, coherent, concrete descriptive coverage.",
        instructions="""Direct a long-form, production-ready visual prompt with maximum useful descriptive density. Expand every relevant, supported decision into concrete natural-language detail: subject identity, count, age presentation when visually relevant, and overall appearance; facial structure, eyes, expression, gaze, hair, skin, anatomy, body shape, pose, limbs, hands, gesture, and action; garment construction, seams, folds, fit, styling, accessories, fabrics, textures, finishes, roughness, reflectivity, translucency, and other material response; foreground, midground, background, meaningful objects, scale, overlap, occlusion, and spatial relationships; composition, framing, camera height, angle, perspective, lens implications, depth, focus plane, and focus hierarchy; supported key, fill, rim, and practical light, including direction, softness, contrast, shadows, highlights, reflections, and exposure; palette, color relationships, grading, atmosphere, mood, and photographic, commercial, editorial, cinematic, rendered, or artistic character. Describe spatial and causal relationships so all details form one coherent image rather than a catalog. Treat user-specified and observable reference evidence as facts; label creative inference internally as an addition and keep it subordinate to the concept, manual Reference Map assignments, and Preserve locks. Omit unsupported or irrelevant specifics. Do not pad with repeated adjectives, synonym chains, generic quality slogans, contradictory camera or lighting choices, hallucinated evidence, or decorative filler, and never force 35mm, film grain, or ControlNet terminology when it was not requested or observed.""",
    ),
    DirectorPreset(
    id="krea_2_identity_edit",
    label="Krea 2 Identity Edit",
    description="Reference-grounded, identity-preserving edit instructions optimized for Krea 2 Identity Edit v1.2.",
    recommended_mode="Image Edit",
    instructions="""Act as a specialized edit director for Krea 2 Identity Edit v1.2. Convert the user's request into one clear, concise, plain-English edit instruction grounded in the supplied reference image or images. This is an image-editing model, not ordinary text-to-image generation: the model already sees the source image semantically and visually, so do not redundantly redescribe the entire image or expand the request into a new scene unless the user explicitly asks for a restage.

    Determine the intended operation first: local attribute change, recolor, add, remove, replace, outfit change, subject restaging, global restyle, head/face/eye/person swap, inpainting, outpainting, or multi-reference composition. State the requested transformation directly with an explicit action and target.

    For local edits, change only the named subject, object, region, or attribute. Treat every unrelated visible property as locked by default, including identity, facial features, body proportions, hairstyle, pose, clothing not targeted by the request, objects, architecture, layout, framing, viewpoint, lighting, color balance, text, and background.

    For additions, specify what is being added, where it belongs, and any necessary physical relationship with the existing scene. Integrate it naturally with the existing perspective, scale, occlusion, lighting, and contact surfaces without redesigning the rest of the image.

    For removals, state clearly what must disappear and describe the natural visible state that should replace it, such as continuing the wall, pavement, landscape, clothing, skin, or background behind the removed element. Do not compensate for a removal by inventing unrelated content.

    For replacements, explicitly identify the existing target and what replaces it. Preserve the target's appropriate location, scale, perspective, interaction, and surrounding scene unless the user requests otherwise.

    For subject restaging, preserve the referenced person's exact identity and stable appearance while changing only the requested pose, camera angle, environment, action, framing, or lighting. Preserve facial structure, distinguishing features, skin character, hair, body characteristics, and clothing unless one of those is intentionally being changed. Allow lighting, shadows, perspective, and pose to adapt naturally to the new scene instead of trying to copy the original pixels.

    When facial likeness is especially important, explicitly instruct the model to preserve the exact facial identity. If reliable reference evidence or an identity analysis provides distinctive facial traits, mention only the few traits that genuinely distinguish the person; never invent facial characteristics.

    For head, face, eye, or person swaps, state exactly which subject or region receives the referenced identity and preserve the receiving scene's requested pose, body, composition, environment, perspective, and lighting unless the user says otherwise. Do not blend identities together.

    For full-image restyles, preserve the source composition, subjects, identities, geometry, pose, object placement, and spatial relationships while changing only the requested visual treatment. Describe the desired style through concrete visual behavior rather than unrelated decorative additions.

    For two-reference edits, respect Krea 2 Identity Edit's reference roles: image 1 is the scene or primary source and image 2 is the subject/person reference. Compose the subject from image 2 into the scene from image 1 while preserving the scene's geometry and context and the subject's identity and defining appearance. Do not swap or ambiguously blend the two reference roles.

    Use positive descriptions of the intended final state instead of negative-prompt syntax. Preserve the user's wording, constraints, identities, and requested scope. Do not add cinematic lighting, shallow depth of field, film grain, golden hour, luxury styling, camera brands, 8K, masterpiece, or other aesthetic defaults unless explicitly requested.

    Do not put sampler or node settings such as CFG, steps, ref_boost, grounding_px, LoRA strength, resolution, fit mode, or model selection into the generated edit instruction; those belong to the workflow rather than the prompt.

    Keep simple edits simple. A request such as "make his shirt blue" should remain essentially "Change his shirt to blue while preserving everything else." Add detail only when it helps locate the edit, protect identity, establish a requested new scene, or resolve a spatial relationship. Return only the final edit instruction, with no explanation, headings, analysis, or parameter recommendations.""",
),
)

DEFAULT_DIRECTOR_PRESET = "General Director"
DIRECTOR_PRESET_NAMES = tuple(preset.label for preset in DIRECTOR_PRESETS)
_BUILTINS_BY_LABEL = {preset.label.casefold(): preset for preset in DIRECTOR_PRESETS}
_BUILTINS_BY_ID = {preset.id.casefold(): preset for preset in DIRECTOR_PRESETS}
MODE_DIRECTOR_RECOMMENDATIONS = {
    "Enhance": "General Director",
    "Photography": "Photography Director",
    "Archviz": "Archviz Director",
    "Video": "Video Director",
    "Product": "Product Director",
    "Character": "Character Director",
    "Image Edit": "Surgical Edit",
    "Style Transfer": "Style Transfer Director",
    "Dataset Caption": "Dataset Caption Director",
    "Custom": "General Director",
}
_LEGACY_DIRECTOR_ALIASES = {
    "reference reconstruction": "Reverse Engineer",
    "reference_reconstruction": "Reverse Engineer",
    "creative enhancement": "General Director",
    "creative_enhancement": "General Director",
    "archviz reconstruction": "Archviz Director",
    "archviz_reconstruction": "Archviz Director",
    "image edit director": "Surgical Edit",
    "image_edit_director": "Surgical Edit",
}


def resolve_user_director_directory():
    configured = os.environ.get(USER_DIRECTOR_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        import folder_paths

        getter = getattr(folder_paths, "get_user_directory", None)
        if callable(getter):
            return Path(getter()).resolve() / "GoatedPrompter" / "directors"
    except (ImportError, AttributeError, OSError):
        pass
    return PROJECT_ROOT / "data" / "directors"


def recommended_director_for_mode(mode):
    return MODE_DIRECTOR_RECOMMENDATIONS.get(str(mode or "").strip(), DEFAULT_DIRECTOR_PRESET)


def _canonical_director_name(value):
    raw = str(value or "").strip()
    return _LEGACY_DIRECTOR_ALIASES.get(raw.casefold(), raw)


def _read_user_director(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DirectorLibraryError(f"Could not read user Director '{path.name}'.") from exc
    if not isinstance(payload, dict):
        raise DirectorLibraryError(f"User Director '{path.name}' must contain a JSON object.")
    if not isinstance(payload.get("name"), str) or not isinstance(payload.get("instructions"), str):
        raise DirectorLibraryError(f"User Director '{path.name}' requires string name and instructions.")
    name = payload["name"].strip()
    instructions = payload["instructions"].strip()
    recommended_mode = str(payload.get("recommended_mode") or "").strip()
    if not name or len(name) > 80:
        raise DirectorLibraryError(f"User Director '{path.name}' has an invalid name.")
    if not instructions or len(instructions) > 100000:
        raise DirectorLibraryError(f"User Director '{name}' has no instructions.")
    if recommended_mode not in _VALID_MODES:
        recommended_mode = ""
    return DirectorPreset(
        id=f"user:{path.stem}",
        label=name,
        description="User Director",
        instructions=instructions,
        recommended_mode=recommended_mode,
        source="user",
    )


def discover_user_directors(directory=None):
    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if not library_dir.is_dir():
        return (), ()
    directors = []
    warnings = []
    seen = set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)
    for path in sorted(library_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            director = _read_user_director(path)
            key = director.label.casefold()
            if key in seen:
                raise DirectorLibraryError(f"Duplicate or protected Director name '{director.label}'.")
            seen.add(key)
            directors.append(director)
        except DirectorLibraryError as exc:
            warnings.append(str(exc))
    return tuple(directors), tuple(warnings)


def get_director_preset(value, directory=None, *, strict=False):
    """Resolve built-in, legacy, or persisted user Director by label or id."""
    name = _canonical_director_name(value)
    key = name.casefold()
    builtin = _BUILTINS_BY_LABEL.get(key) or _BUILTINS_BY_ID.get(key)
    if builtin:
        return _effective_builtin(builtin, directory)[0]
    users, _warnings = discover_user_directors(directory)
    found = next(
        (director for director in users if key in {director.label.casefold(), director.id.casefold()}),
        None,
    )
    if found:
        return found
    if strict:
        raise DirectorLibraryError("The selected Director does not exist. Select a saved Director.")
    return _effective_builtin(_BUILTINS_BY_LABEL[DEFAULT_DIRECTOR_PRESET.casefold()], directory)[0]


def list_director_presets(directory=None):
    """Return built-ins followed by automatically discovered user Directors."""
    users, warnings = discover_user_directors(directory)
    effective = [_effective_builtin(preset, directory) for preset in DIRECTOR_PRESETS]
    warnings = [*warnings, *(warning for _, warning in effective if warning)]
    directors = [*(preset for preset, _ in effective), *users]
    return [director.to_public_mapping() for director in directors], list(warnings)


def _safe_filename(name):
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return (slug[:64] or "user-director") + ".json"


@_serialized
def save_user_director(name, instructions, recommended_mode="", directory=None):
    """Persist a new user Director without ever overwriting a built-in or user file."""
    if not isinstance(name, str) or not isinstance(instructions, str):
        raise DirectorLibraryError("Director name and Behavior must be strings.")
    clean_name = str(name or "").strip()
    clean_instructions = str(instructions or "").strip()
    clean_mode = str(recommended_mode or "").strip()
    if not clean_name or len(clean_name) > 80:
        raise DirectorLibraryError("Director name must contain 1 to 80 characters.")
    if not clean_instructions or len(clean_instructions) > 100000:
        raise DirectorLibraryError("Director Behavior must contain 1 to 100000 characters.")
    if clean_name.casefold() in (set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)):
        raise DirectorLibraryError("Built-in Goated Prompter Directors are protected; choose a new name with Save As.")
    users, _warnings = discover_user_directors(directory)
    if any(director.label.casefold() == clean_name.casefold() for director in users):
        raise DirectorLibraryError("A user Director with that name already exists; choose a new name.")
    if clean_mode not in _VALID_MODES:
        clean_mode = ""

    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    library_dir.mkdir(parents=True, exist_ok=True)
    destination = library_dir / _safe_filename(clean_name)
    if destination.exists():
        raise DirectorLibraryError("A Director file with that name already exists; choose a new name.")
    payload = {
        "version": 1,
        "name": clean_name,
        "instructions": clean_instructions,
        "recommended_mode": clean_mode,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=library_dir, prefix=".goated-prompter-", suffix=".tmp", delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(destination)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise DirectorLibraryError("The user Director could not be saved.") from exc
    return _read_user_director(destination), destination


@_serialized
def delete_user_director(value, directory=None):
    """Delete one persisted user Director without exposing built-ins to deletion."""
    clean_value = str(value or "").strip()
    if not clean_value:
        raise DirectorLibraryError("Select a user-created Director to delete.")
    canonical = _canonical_director_name(clean_value).casefold()
    if canonical in _BUILTINS_BY_LABEL or canonical in _BUILTINS_BY_ID:
        raise DirectorLibraryError("Built-in Goated Prompter Directors are protected and cannot be deleted.")

    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if not library_dir.is_dir():
        raise DirectorLibraryError("The selected user Director does not exist.")
    for path in sorted(library_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            director = _read_user_director(path)
        except DirectorLibraryError:
            continue
        if canonical not in {director.label.casefold(), director.id.casefold()}:
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise DirectorLibraryError("The user Director could not be deleted.") from exc
        return director, path
    raise DirectorLibraryError("The selected user Director does not exist.")


def _override_path(builtin, directory):
    root = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    return root / ".overrides" / (builtin.id + ".json")


def _effective_builtin(builtin, directory):
    path = _override_path(builtin, directory)
    if not path.exists():
        return builtin, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(payload, dict) or payload.get("id") != builtin.id
                or payload.get("name") != builtin.label
                or not isinstance(payload.get("instructions"), str)
                or not 1 <= len(payload["instructions"].strip()) <= 100000
                or payload.get("recommended_mode") != builtin.recommended_mode):
            raise ValueError("invalid override fields")
        return replace(builtin, instructions=payload["instructions"].strip(), modified=True), ""
    except (OSError, ValueError) as exc:
        return builtin, f"Cannot read Director override '{path.name}': {exc}. Repair it or Reset explicitly."


@_serialized
def update_director(value, name, instructions, recommended_mode=None, directory=None):
    director = get_director_preset(value, directory, strict=True)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise DirectorLibraryError("Director name must contain 1 to 80 characters.")
    if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 100000:
        raise DirectorLibraryError("Director Behavior must contain 1 to 100000 characters.")
    name, instructions = name.strip(), instructions.strip()
    root = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if director.source == "builtin":
        builtin = _BUILTINS_BY_ID[director.id]
        _, warning = _effective_builtin(builtin, directory)
        if warning:
            raise DirectorLibraryError(warning)
        if name != builtin.label:
            raise DirectorLibraryError("Built-in Director names cannot be changed.")
        path = _override_path(builtin, directory)
        mode = builtin.recommended_mode
    else:
        protected = set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)
        users, _ = discover_user_directors(directory)
        if name.casefold() in protected or any(p.id != director.id and p.label.casefold() == name.casefold() for p in users):
            raise DirectorLibraryError("Duplicate or protected Director name.")
        path = root / (director.id.removeprefix("user:") + ".json")
        mode = director.recommended_mode if recommended_mode is None else recommended_mode
        if mode and mode not in _VALID_MODES:
            raise DirectorLibraryError("Invalid recommended_mode.")
    payload = {"version": 1, "id": director.id, "name": name, "instructions": instructions, "recommended_mode": mode}
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise DirectorLibraryError("The Director could not be updated.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return get_director_preset(director.id, directory, strict=True), path


@_serialized
def reset_director(value, directory=None):
    key = _canonical_director_name(value).casefold()
    builtin = _BUILTINS_BY_ID.get(key) or _BUILTINS_BY_LABEL.get(key)
    if builtin is None:
        raise DirectorLibraryError("Only built-in Directors can be Reset.")
    path = _override_path(builtin, directory)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DirectorLibraryError("The Director override could not be reset.") from exc
    return builtin, path


def legacy_preset_for_mode(mode):
    """Compatibility alias retained for old payload migration."""
    return recommended_director_for_mode(mode)
