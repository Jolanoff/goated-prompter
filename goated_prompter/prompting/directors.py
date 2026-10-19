"""Built-in Director definitions and prompt-engine labels."""

from dataclasses import dataclass

# Prompt engine names. Runtime discovery and model-family resolution remain in
# director_profiles.py because they depend on the local filesystem.


@dataclass(frozen=True)
class DirectorPreset:
    id: str
    label: str
    description: str
    instructions: str
    recommended_mode: str = ""
    source: str = "builtin"
    modified: bool = False
    supported_targets: tuple = ()

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
            "supported_targets": list(self.supported_targets),
        }


DIRECTOR_PRESETS = (
    DirectorPreset(
        id="general_director",
        label="General",
        description="Balanced visual prompt direction for general image and video requests.",
        recommended_mode="Enhance",
        instructions="""Act as a disciplined general visual director. Convert the current task into one coherent, production-ready prompt whose subject, action or state, environment, spatial relationships, composition, viewpoint, materials, lighting, color behavior, depth, and medium agree with one another. Make every detail serve one legible image or video and drop any that would create a second scene or a conflict. Prefer observable, actionable visual details over empty quality claims.""",
    ),
    DirectorPreset(
        id="prompt_enhancer",
        label="Polish a Rough Prompt",
        description="Turns rough text or tags into a complete, coherent prompt without replacing the concept.",
        recommended_mode="Enhance",
        instructions="""Improve rough text, fragments, or tags into a complete, coherent description while retaining the user's distinctive wording. Turn fragments and tags into whole sentences, make composition, camera perspective, lighting, material or texture behavior, color relationships and mood explicit where the text only hints at them, and make the spatial and causal relationships between details clear.""",
    ),
    DirectorPreset(
        id="reverse_engineer",
        label="Recreate a Reference Image",
        description="Forensic reference reconstruction driven by observable evidence.",
        instructions="""Act as a forensic visual reverse engineer. Treat reference evidence as the source for shot type, subject and defining appearance, wardrobe and materials, exact pose or action, setting and background, composition, lighting, color and tonal response, perspective, and depth; the reference's medium and image character carry over only while no Style is selected. Reconstruct those decisions precisely, with fidelity taking precedence over beautification. Preserve defining structure unless the current task explicitly changes it. Include a characteristic only when the request or visible evidence supports it.""",
    ),
    DirectorPreset(
        id="surgical_edit",
        label="Edit Only the Requested Details",
        description="Minimum-change editing with explicit add, remove, and replace boundaries.",
        recommended_mode="Image Edit",
        instructions="""Direct a minimum-change image edit. First identify whether the request adds an element, removes an element, or replaces or changes a named attribute, and make that requested edit authoritative for its target. Preserve every unrelated visible fact, including identity, pose, geometry, layout, viewpoint, materials, lighting, colors, background, text, and unaffected subjects. For removal, describe the resulting visible state naturally rather than relying on awkward negative wording. When several subjects are present, modify only the explicitly targeted subject. Never restage or beautify the rest of the image as a side effect.""",
    ),
    DirectorPreset(
        id="face_identity_analyst",
        label="Describe Facial Features",
        description="Reference-grounded face, head, and hair identity analysis.",
        instructions="""Build a precise identity-relevant description of the visible face, head, and hair. Prioritize face geometry and proportions, eye shape and spacing, brows, nose, lips, cheek structure, jaw and chin, skin tone and visible texture or marks, hairline, hairstyle, hair texture, and distinctive asymmetries or features. Describe only supported visual evidence and protect likeness rather than idealizing or intentionally changing it. Omit body, clothing, environment, narrative, camera, and lighting details by default unless the current task explicitly asks for them or they are necessary to disambiguate the face.""",
    ),
    DirectorPreset(
        id="subject_appearance_analyst",
        label="Describe Face & Body",
        description="Reusable reference-grounded face and body appearance descriptors.",
        instructions="""Create a reusable appearance descriptor from visible reference evidence. Prioritize identity-defining face and body characteristics, proportions, silhouette, skin, hair, distinctive marks, and other stable traits that help preserve the subject across generations. Do not impose deliberate similarity reduction, idealize the subject, invent hidden anatomy, or infer unsupported age, ethnicity, history, or personality. Omit clothing, environment, pose, action, and camera treatment by default because those are scene variables; include them only when the current task explicitly makes them part of the identity description.""",
    ),
    DirectorPreset(
        id="reference_composer",
        label="Combine Reference Images",
        description="Composes role-assigned subject, scene, pose, style, lighting, and material references coherently.",
        instructions="""Act as the strongest general multi-reference composer. Assign every selected fact to its named source before composing: face or subject identity from a Subject reference; environment, architecture, props, and spatial context from a Scene reference; action and limb relationships from a Pose reference; framing and viewpoint from a Composition reference; illumination from a Lighting reference; and aesthetic or surface language from a Style reference. Support architecture from one image with lighting or style from another, and transfer object or material inspiration only when the request makes that relationship useful. Preserve defining identity, appearance, object design, and role-authoritative evidence while integrating them with physically coherent scale, contact, occlusion, perspective, material response, and light. Ignore incidental backgrounds, people, poses, objects, and treatments that fall outside each reference's role. Never blend both images wholesale or let one source silently replace facts assigned to the other.""",
    ),
    DirectorPreset(
        id="arms_length_selfie",
        label="Front-Camera Selfie",
        description="Front-camera selfie geometry with correct arm, phone, and perspective logic.",
        recommended_mode="Photography",
        instructions="""Construct a true arm's-length front-camera selfie. Reason explicitly about whether the phone is held above, level with, or below the face; the resulting head angle and gaze; close wide-angle perspective; shoulder and arm geometry; foreshortening; crop; and the background visible from that handheld position. The camera is the phone being held, so the phone itself must not appear in the image unless the task is explicitly a mirror shot. Preserve identity and requested pose, avoid impossible limb placement, and keep the casual framing and optical distortion consistent with the stated camera position.""",
    ),
    DirectorPreset(
        id="mirror_selfie",
        label="Mirror Selfie",
        description="Reflection-aware selfie framing with a visible phone and coherent mirror geometry.",
        recommended_mode="Photography",
        instructions="""Construct a mirror selfie rather than a front-camera selfie. The phone is visible in the reflection and its position must agree with the subject's hand, gaze, body angle, mirror plane, crop, and reflected room geometry. Describe the reflected framing, plausible phone occlusion, body posture, and available light without creating a second physical subject or an impossible reflection. Preserve identity, wardrobe, and requested environment. State text, asymmetric details and left-right claims only when the reference or request makes them reliable.""",
    ),
    DirectorPreset(
        id="first_person_pov",
        label="First-Person View",
        description="Embodied first-person camera geometry with plausible hands and foreshortening.",
        recommended_mode="Photography",
        instructions="""Treat the camera as the person's own eye or explicitly requested phone viewpoint. Keep the viewpoint embodied: describe what lies ahead, which hands or parts of the body are naturally visible, their reach and foreshortening, and how objects align with the camera's height and orientation. Do not accidentally turn the viewpoint character into a third-person full-body subject. Preserve spatial continuity and avoid impossible self-visibility. Include hands, arms, legs, held objects, or body edges only when they would genuinely enter the chosen field of view.""",
    ),
    DirectorPreset(
        id="fashion_editorial",
        label="Fashion & Styling",
        description="Fashion and styling direction: garment, styling, pose and material response.",
        recommended_mode="Photography",
        instructions="""Direct a fashion editorial centered on the garment, styling intention, subject attitude, pose, silhouette, fabric construction, drape, texture, accessories, set design, lighting, framing, and color story. Coordinate pose and camera angle so the clothing reads clearly and the body remains anatomically credible. Let the request determine whether the result is studio, location, polished, raw, graphic, or documentary, and keep the featured styling unobscured.""",
    ),
    DirectorPreset(
        id="boudoir_intimate",
        label="Boudoir & Intimate",
        description="Adult intimate direction with credible bodies, fabric, light and composition.",
        recommended_mode="Photography",
        instructions="""Direct lawful adult boudoir or intimate imagery with deliberate composition, consenting adult presentation, credible anatomy, fabric and surface behavior, pose, gaze, gesture, privacy, environment, and light that supports the requested mood. Distinguish elegant, candid, sensual, dramatic, or documentary intent from generic glamour defaults. Never use coercive framing or age ambiguity.""",
    ),
    DirectorPreset(
        id="krea_2_high_detail",
        label="Krea 2 Precision",
        description="Coherent spatial, material and lighting relationships, not increased verbosity.",
        supported_targets=("Krea 2",),
        instructions="""Direct technically precise visual relationships for Krea 2: resolve ambiguous object placement, contact, scale, material response and lighting logic.""",
    ),
    DirectorPreset(
        id="krea_2_pose_lock",
        label="Krea 2 Match Reference Pose",
        supported_targets=("Krea 2",),
        description="Reference-grounded pose precision with full body and camera geometry.",
        instructions="""Lock the pose and camera relationship to reference evidence with precise natural language. Describe torso orientation, head direction and tilt, shoulder levels, arm paths, elbow bends, hand placement and gesture, hip rotation, leg positions, knee and ankle bends, stride or weight distribution, crop, framing, camera height, and viewpoint. Use active present-progressive verbs when they make the action clearer. Preserve identity and visible structure while applying only requested changes.""",
    ),
    DirectorPreset(
        id="video_director",
        label="Video Action & Camera Movement",
        description="Temporal action, camera movement, continuity, timing, and final state.",
        recommended_mode="Video",
        instructions="""Direct a coherent shot unfolding through time. If one reference image is present, treat it as the exact initial visual state, then describe chronological subject action, secondary and environmental movement, explicit camera movement, pacing, continuity, and a clear final state or framing. Protect identity, scale, lighting logic, screen direction, and spatial relationships across the shot. Use motion language instead of repeatedly restating static reference detail. Include dialogue or sound guidance only when appropriate to the request. Keep the structure ready for a future optional end-frame reference without assuming one exists now.""",
    ),
    DirectorPreset(
        id="minimax_director",
        label="MiniMax H3",
        description="MiniMax H3 staging, reference-aware motion and synchronized sound direction.",
        recommended_mode="Video",
        instructions="""Enhance the user's concept through clear staging, subject placement, physical action progression, expressions, environment and background detail, lighting, composition, plausible camera movement, pacing, audiovisual synchronization, soundscape, concrete music direction and a deliberate ending state. Fit the selected clip duration. Prefer coherent movement to unnecessary cuts. References have only the roles requested by the user; never assume an image is a starting frame or invent the contents of unseen media. Preserve explicit user requirements and exact dialogue. This is creative guidance only: MiniMax H3 structural rules and reference relationships belong to the target adapter and outrank this preset.""",
    ),
    DirectorPreset(
        id="archviz_director",
        label="Architecture & Interiors",
        description="Architecture and interiors with disciplined spatial and material fidelity.",
        recommended_mode="Archviz",
        instructions="""Direct the result around the architecture. Prioritize architectural geometry, scale, circulation and spatial relationships, openings, materials and finishes, visible furniture and styling, camera position, architectural perspective, controlled verticals, natural and artificial lighting, landscaping or context, and believable surface response, with undistorted geometry.""",
    ),
    DirectorPreset(
        id="character_director",
        label="Character Focus",
        description="Character identity, anatomy, expression, wardrobe, pose, and staging.",
        recommended_mode="Character",
        instructions="""Direct the result around a consistent character. Define identity, age range when relevant, distinguishing features, anatomy, expression, gaze, pose, gesture, action, clothing construction, materials, accessories, framing, environment and lighting. Keep identity and wardrobe details consistent throughout the prompt, protect named or visible traits, and avoid contradictory anatomy.""",
    ),
    DirectorPreset(
        id="product_director",
        label="Product Focus",
        description="Product geometry, materials, brand-neutral presentation, and lighting that reveals form.",
        recommended_mode="Product",
        instructions="""Direct the result as a precise product image. Protect product identity, proportions, geometry, functional details, materials, finish, color, branding supplied by the user, and scale. Specify an intentional viewing angle, composition, support surface or environment, background, reflections, shadow behavior, and lighting that reveals form and material response. Keep important geometry visible rather than hidden behind staging.""",
    ),
    DirectorPreset(
        id="style_transfer_director",
        label="Change the Visual Style",
        description="Transfer visual treatment while preserving selected content and structure.",
        recommended_mode="Style Transfer",
        instructions="""Direct the task as a controlled style transfer. Emphasize the requested treatment in concrete terms: mark-making or rendering behavior, material appearance, texture, palette logic, contrast, lighting treatment, edge behavior, and finish in concrete terms. Preserve subject identity, pose, composition, spatial relationships, and essential content unless the user asks to change them. Avoid using an artist name as a substitute for visual description or allowing style language to rewrite the scene.""",
    ),
    DirectorPreset(
        id="dataset_caption_director",
        label="Dataset & LoRA Caption",
        description="Factual, literal emphasis for dataset and LoRA captions.",
        recommended_mode="Dataset Caption",
        instructions="""Emphasize what is visibly there and useful for retrieval or training: subject, count, defining attributes, clothing or product traits, pose or action, environment, composition, viewpoint and lighting, in literal terms.""",
    ),
    DirectorPreset(
        id="maximum_detail_director",
        label="Technical Precision",
        description="Technical spatial, material and lighting precision without controlling verbosity.",
        instructions="""Direct technical visual precision: make spatial contacts, scale, occlusion, viewpoint, material response and lighting direction physically consistent and unambiguous.""",
    ),
    DirectorPreset(
    id="krea_2_identity_edit",
    label="Krea 2 Identity Edit v1.2 (Community)",
    description="Reference-grounded identity-preserving edits for the community model/workflow, not an official Krea.ai base capability.",
    supported_targets=("Krea 2",),
    recommended_mode="Image Edit",
    instructions="""Act as a specialized edit director for the Krea 2 Identity Edit v1.2 community model/workflow, not an official Krea.ai base capability. Convert the user's request into one clear edit instruction in English, grounded in the supplied reference image or images when Mode is Image Edit. Never replace another selected Mode with image editing. The editing model already sees the source image, so do not redundantly redescribe the entire image or expand the request into a new scene unless the user explicitly asks for a restage.

    Determine the intended operation first: local attribute change, recolor, add, remove, replace, outfit change, subject restaging, global restyle, head/face/eye/person swap, inpainting, outpainting, or multi-reference composition. State the requested transformation directly with an explicit action and target.

    For local edits, change only the named subject, object, region, or attribute. Treat every unrelated visible property as locked by default, including identity, facial features, body proportions, hairstyle, pose, clothing not targeted by the request, objects, architecture, layout, framing, viewpoint, lighting, color balance, text, and background.

    For additions, specify what is being added, where it belongs, and any necessary physical relationship with the existing scene. Integrate it naturally with the existing perspective, scale, occlusion, lighting, and contact surfaces without redesigning the rest of the image.

    For removals, state clearly what must disappear and describe the natural visible state that should replace it, continuing whatever lay behind the removed element. Do not compensate for a removal by inventing unrelated content.

    For replacements, explicitly identify the existing target and what replaces it. Preserve the target's appropriate location, scale, perspective, interaction, and surrounding scene unless the user requests otherwise.

    For subject restaging, preserve the referenced person's exact identity and stable appearance while changing only the requested pose, camera angle, environment, action, framing, or lighting. Preserve facial structure, distinguishing features, skin character, hair, body characteristics, and clothing unless one of those is intentionally being changed. Allow lighting, shadows, perspective, and pose to adapt naturally to the new scene instead of trying to copy the original pixels.

    When facial likeness is especially important, explicitly instruct the model to preserve the exact facial identity. If reliable reference evidence or an identity analysis provides distinctive facial traits, mention only the few traits that genuinely distinguish the person; never invent facial characteristics.

    For head, face, eye, or person swaps, state exactly which subject or region receives the referenced identity and preserve the receiving scene's requested pose, body, composition, environment, perspective, and lighting unless the user says otherwise. Do not blend identities together.

    For full-image restyles, preserve the source composition, subjects, identities, geometry, pose, object placement, and spatial relationships while changing only the requested visual treatment. Describe the desired style through concrete visual behavior rather than unrelated decorative additions.

    For two-reference edits, follow the reference roles the user assigned; when none are assigned, Krea 2 Identity Edit reads image 1 as the scene or primary source and image 2 as the subject/person reference. Compose the subject from image 2 into the scene from image 1 while preserving the scene's geometry and context and the subject's identity and defining appearance. Do not swap or ambiguously blend the two reference roles.

    Use positive descriptions of the intended final state instead of negative-prompt syntax. Preserve the user's wording, constraints, identities, and requested scope.

    Keep generator and workflow settings out of the edit instruction; they belong to the workflow rather than the prompt.

    Keep simple edits simple: a one-attribute request stays a single change that preserves everything else. Add detail only when it helps locate the edit, protect identity, establish a requested new scene, or resolve a spatial relationship.""",
),
DirectorPreset(
    id="nsfw_director",
    label="Explicit Adult",
    description="Explicit adult direction: credible anatomy, contact and staging while preserving identity and the user’s intent.",
    recommended_mode="Enhance",
    instructions="""Direct adult content around the bodies and their contact. Describe anatomy, pose, contact, weight distribution, and spatial relationships clearly so bodies remain credible and readable. Within the framing given, keep face, body, and genitals logically positioned without impossible or nonsensical overlaps.
    Keep expression, arousal cues, skin response, fluids and fabric consistent with the scene. Make physical contact believable: weight, pressure and how skin and bodies respond where they touch.
    Always clearly state who is penetrating whom (whose penis is entering which person’s orifice), describe the state of each relevant penis (erect, partially erect, soft, etc.), and describe every subject’s genitals whenever the scene, pose, clothing state, or framing makes them visible.""",
),

)

DEFAULT_DIRECTOR_PRESET = "General"
DIRECTOR_PRESET_NAMES = tuple(preset.label for preset in DIRECTOR_PRESETS)
MODE_DIRECTOR_RECOMMENDATIONS = {
    "Enhance": "General",
    "Photography": "General",
    "Archviz": "Architecture & Interiors",
    "Video": "Video Action & Camera Movement",
    "Product": "Product Focus",
    "Character": "Character Focus",
    "Image Edit": "Edit Only the Requested Details",
    "Style Transfer": "Change the Visual Style",
    "Dataset Caption": "Dataset & LoRA Caption",
    "Custom": "General",
    "Remix": "General",
}
# Directors that set a medium became Style choices: the Style owns medium and rendering, a Director only what is
# emphasized. A saved choice of one of them reads as General plus this style and capture.
REPLACED_DIRECTORS = {
    "photography_director": ("Realistic", "Pro camera"),
    "smartphone_realism": ("Realistic", "Phone snapshot"),
    "krea_2_smartphone_realism": ("Realistic", "Phone snapshot"),
    "vintage_analog": ("Realistic", "Analog film"),
    "anime_director": ("Anime", "Auto"),
}
_REPLACED_LABELS = {"photography director": "photography_director", "smartphone realism": "smartphone_realism",
                    "krea 2 smartphone realism": "krea_2_smartphone_realism", "vintage / analog": "vintage_analog",
                    "anime director": "anime_director"}


def replaced_director(value):
    """(style, capture) when a saved Director id or label is one that became a Style choice, else None."""
    key = str(value or "").strip().casefold()
    return REPLACED_DIRECTORS.get(_REPLACED_LABELS.get(key, key))


def fold_replaced_director(settings, key="director_preset"):
    """Settings whose Director became a Style choice, read as General plus that style and capture. A style the
    user already chose stays; settings with any other Director come back unchanged."""
    found = replaced_director(settings.get(key))
    if not found:
        return settings
    result = {**settings, key: "general_director"}
    if str(settings.get("style") or "Auto") == "Auto":
        result["style"], result["capture"] = found
    return result


_LEGACY_DIRECTOR_ALIASES = {
    "minimax_h3_director": "MiniMax H3",
    "minimax director": "MiniMax H3",
    "maximum detail director": "Technical Precision",
    "krea 2 high detail": "Krea 2 Precision",
    "krea 2 identity edit": "Krea 2 Identity Edit v1.2 (Community)",
    "reference reconstruction": "Recreate a Reference Image",
    "reference_reconstruction": "Recreate a Reference Image",
    "creative enhancement": "General",
    "creative_enhancement": "General",
    "archviz reconstruction": "Architecture & Interiors",
    "archviz_reconstruction": "Architecture & Interiors",
    "image edit director": "Edit Only the Requested Details",
    "image_edit_director": "Edit Only the Requested Details",
    # Labels before the Directors were renamed.
    "general director": "General",
    "prompt enhancer": "Polish a Rough Prompt",
    "reverse engineer": "Recreate a Reference Image",
    "surgical edit": "Edit Only the Requested Details",
    "face identity analyst": "Describe Facial Features",
    "subject appearance analyst": "Describe Face & Body",
    "reference composer": "Combine Reference Images",
    "arm's-length selfie": "Front-Camera Selfie",
    "first-person pov": "First-Person View",
    "fashion editorial": "Fashion & Styling",
    "boudoir / intimate": "Boudoir & Intimate",
    "krea 2 visual precision": "Krea 2 Precision",
    "krea 2 pose lock": "Krea 2 Match Reference Pose",
    "video director": "Video Action & Camera Movement",
    "minimax h3 director": "MiniMax H3",
    "archviz director": "Architecture & Interiors",
    "character director": "Character Focus",
    "product director": "Product Focus",
    "style transfer director": "Change the Visual Style",
    "dataset caption director": "Dataset & LoRA Caption",
    "technical visual precision": "Technical Precision",
    "nsfw director": "Explicit Adult",
    "photography_director": "General",
    "smartphone_realism": "General",
    "krea_2_smartphone_realism": "General",
    "vintage_analog": "General",
    "anime_director": "General",
    "photography director": "General",
    "smartphone realism": "General",
    "krea 2 smartphone realism": "General",
    "vintage / analog": "General",
    "anime director": "General",
}
