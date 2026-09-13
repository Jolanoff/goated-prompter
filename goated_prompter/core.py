"""Prompt assembly and backend orchestration, independent of ComfyUI UI code."""

import base64
from dataclasses import dataclass, replace
import hashlib

from .backends.factory import create_backend
from .config import load_config
from .director_profiles import canonical_prompt_model, infer_prompt_model_family, resolve_director_config
from .diagnostics import debug_prompts_enabled, log_evidence_result, resolved_scene_sha256
from .evidence import (
    EVIDENCE_ANALYSIS_SYSTEM_PROMPT,
    build_resolved_scene,
    cache_evidence,
    evidence_analysis_user_message,
    evidence_cache_key,
    get_cached_evidence,
    parse_image_evidence,
)
from .image_utils import EncodedImage, encode_comfy_image
from .models import get_model_adapter
from .modes import get_mode_adapter, get_vision_mode_adapter
from .prompt_catalog import (
    CREATIVITY_ADAPTERS as _CREATIVITY_ADAPTERS,
    CREATIVITY_NAMES,
    LENGTH_ADAPTERS as _LENGTH_ADAPTERS,
    MAXIMUM_DETAIL_GUIDANCE as _MAXIMUM_DETAIL_GUIDANCE,
    PRESERVATION_ADAPTERS as _PRESERVATION_ADAPTERS,
    PRESERVATION_LINKED_LOCK,
    PRESERVATION_NO_LINKED_LOCKS,
    PRESERVATION_NONE,
    PROMPT_LENGTH_NAMES,
    REFERENCE_ROLE_NAMES,
)
from .presets import DEFAULT_DIRECTOR_PRESET, get_director_preset, legacy_preset_for_mode
from .reference_map import REFERENCE_IMAGE_SLOTS, reference_images, reference_map_from_mapping, resolve_reference_map
from .system_prompt import (
    CONTROL_CONTRACT,
    CORE_SYSTEM_PROMPT,
    LINKED_PRIORITY_CONTRACT,
    OUTPUT_CONTRACT,
    PRIORITY_CONTRACT,
    TEXT_ONLY_PRIORITY_CONTRACT,
)

def _image_descriptor(image):
    if image is None:
        return "NONE"
    if not isinstance(image, EncodedImage):
        return f"unencoded {type(image).__name__}"
    try:
        payload = base64.b64decode(image.data, validate=False)
    except (ValueError, TypeError):
        payload = str(image.data).encode("utf-8", errors="replace")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{image.media_type} {image.width}x{image.height} sha256={digest}"


def _log_image_order(request):
    if not debug_prompts_enabled() or not reference_images(request):
        return
    print("[Goated Prompter IMAGE ORDER]", flush=True)
    for field, label in REFERENCE_IMAGE_SLOTS:
        print(f"{label} = {_image_descriptor(getattr(request, field, None))}", flush=True)


def _preservation_section(request, resolved_reference_map, has_image):
    if has_image or request.linked_references:
        locked = [item for item in resolved_reference_map.attributes if item.preserve]
        if not locked:
            return PRESERVATION_NO_LINKED_LOCKS
        return (
            "PRESERVATION CONSTRAINTS\n- "
            + "\n- ".join(
                PRESERVATION_LINKED_LOCK.format(label=item.label, source=item.source)
                for item in locked
            )
        )

    enabled = [
        text
        for field, text in _PRESERVATION_ADAPTERS.items()
        if getattr(request, f"preserve_{field}")
    ]
    return (
        "PRESERVATION CONSTRAINTS\n- " + "\n- ".join(enabled)
        if enabled
        else PRESERVATION_NONE
    )

def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _reference_role(value):
    candidate = str(value or "Auto").strip().casefold()
    return next((role for role in REFERENCE_ROLE_NAMES if role.casefold() == candidate), "Auto")


@dataclass(frozen=True)
class GoatedPrompterRequest:
    idea: str
    mode: str = "Enhance"
    target_model: str = "Generic"
    creativity: str = "Balanced"
    prompt_model: str = "Qwen 3.5 9B"
    director_preset: str = DEFAULT_DIRECTOR_PRESET
    director_ai: str = ""
    director_profile: str = ""
    director_model_path: str = ""
    director_mmproj_path: str = ""
    director_llama_server: str = ""
    director_context_size: int = 8192
    director_image_min_tokens: int = 1024
    director_max_tokens: int = 768
    director_gpu_layers: str = "auto"
    director_keep_model_loaded: bool = False
    preserve_subject: bool = True
    preserve_composition: bool = False
    preserve_camera: bool = False
    preserve_materials: bool = False
    preserve_lighting: bool = False
    preserve_colors: bool = False
    prompt_length: str = "Medium"
    custom_instructions: str = ""
    system_prompt_override: str = ""
    reference_map: object = None
    image: object = None
    image_2: object = None
    image_1_role: str = "Auto"
    image_2_role: str = "Auto"

    image_3: object = None
    image_4: object = None
    linked_references: bool = False

    @property
    def selected_prompt_model(self):
        return canonical_prompt_model(self.director_ai or self.prompt_model)

    @classmethod
    def from_mapping(cls, values):
        values = values or {}
        legacy_payload = "prompt_model" not in values and "director_ai" in values
        preset_value = values.get("director_preset") or (
            legacy_preset_for_mode(values.get("mode")) if legacy_payload else DEFAULT_DIRECTOR_PRESET
        )
        return cls(
            idea=str(values.get("idea") or ""),
            mode=str(values.get("mode") or "Enhance"),
            target_model=str(values.get("target_model") or "Generic"),
            creativity=str(values.get("creativity") or "Balanced"),
            prompt_model=str(values.get("prompt_model") or values.get("director_ai") or "Qwen 3.5 9B"),
            director_preset=str(preset_value),
            director_profile=str(values.get("director_profile") or ""),
            director_model_path=str(values.get("director_model_path") or ""),
            director_mmproj_path=str(values.get("director_mmproj_path") or ""),
            director_llama_server=str(values.get("director_llama_server") or ""),
            director_context_size=int(values.get("director_context_size", 8192)),
            director_image_min_tokens=int(values.get("director_image_min_tokens", 1024)),
            director_max_tokens=int(values.get("director_max_tokens", 768)),
            director_gpu_layers=str(values.get("director_gpu_layers") or "auto"),
            director_keep_model_loaded=_as_bool(values.get("director_keep_model_loaded", False)),
            preserve_subject=_as_bool(values.get("preserve_subject", True)),
            preserve_composition=_as_bool(values.get("preserve_composition", False)),
            preserve_camera=_as_bool(values.get("preserve_camera", False)),
            preserve_materials=_as_bool(values.get("preserve_materials", False)),
            preserve_lighting=_as_bool(values.get("preserve_lighting", False)),
            preserve_colors=_as_bool(values.get("preserve_colors", False)),
            prompt_length="Maximum Detail" if values.get("prompt_length") == "Maximum" else str(values.get("prompt_length") or "Medium"),
            custom_instructions=str(values.get("custom_instructions") or ""),
            system_prompt_override=str(values.get("system_prompt_override") or ""),
            reference_map=reference_map_from_mapping(values),
            image_1_role=_reference_role(values.get("image_1_role")),
            image_2_role=_reference_role(values.get("image_2_role")),
            linked_references=_as_bool(values.get("linked_references", False)),
        )


@dataclass(frozen=True)
class PromptInstruction:
    system_message: str
    user_message: str
    image: EncodedImage = None
    image_2: EncodedImage = None
    image_1_role: str = "Auto"
    image_2_role: str = "Auto"
    reference_map: object = None
    resolved_scene: object = None
    model_family: str = "qwen"
    director_preset: str = DEFAULT_DIRECTOR_PRESET
    image_label: str = "Image 1"
    diagnostic_stage: str = "final"
    diagnostic_context: object = None
    image_3: EncodedImage = None
    image_4: EncodedImage = None
    max_tokens: int = None

    def _user_content(self, text):
        if not reference_images(self):
            return text
        content = [{"type": "text", "text": text}]
        for label, image in reference_images(self).items():
            label = self.image_label if label == "Image 1" else label
            description = f"{label.upper()} - REFERENCE\nThe next image content part is {label}."
            if len(content) == 1:
                content[0]["text"] += "\n\n" + description
            else:
                content.append({"type": "text", "text": description})
            content.append({"type": "image_url", "image_url": {"url": image.data_url}})
        return content

    def to_messages(self):
        if self.model_family == "gemma":
            folded = (
                "SYSTEM-STYLE INSTRUCTIONS:\n"
                f"{self.system_message}\n\n"
                "USER REQUEST:\n"
                f"{self.user_message}"
            )
            return [{"role": "user", "content": self._user_content(folded)}]
        return [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": self._user_content(self.user_message)},
        ]


@dataclass(frozen=True)
class GenerationResult:
    prompt: str
    backend_name: str
    instruction: PromptInstruction
    director_profile: str = ""
    prompt_model: str = ""
    director_preset: str = ""


def assemble_instruction(
    request,
    model_family=None,
    resolved_scene=None,
    resolved_reference_map=None,
    text_only=False,
):
    if text_only:
        resolved_scene = None
    idea = request.idea.strip()
    if request.linked_references and not text_only:
        resolved_reference_map = (
            resolved_reference_map
            or (resolved_scene.reference_map if resolved_scene is not None else None)
            or resolve_reference_map(request)
        )
        selected = {item.source for item in resolved_reference_map.attributes}
        request = replace(request, **{
            field: getattr(request, field) if label in selected or "Blend" in selected else None
            for field, label in REFERENCE_IMAGE_SLOTS
        })
        if not idea and selected <= {"Off"}:
            raise ValueError("All reference attributes are Off. Enter an idea or select an uploaded image source for at least one attribute.")
    has_raw_image = not text_only and bool(reference_images(request))
    has_visual_context = has_raw_image or resolved_scene is not None
    if request.linked_references and not text_only and selected <= {"Off"}:
        has_visual_context = False
    if not idea and not has_visual_context:
        raise ValueError("Idea / Prompt cannot be empty.")

    preset = get_director_preset(request.director_preset)
    resolved_reference_map = None if text_only else (
        resolved_reference_map
        or (resolved_scene.reference_map if resolved_scene is not None else None)
        or resolve_reference_map(request, preset.label)
    )
    if has_raw_image and resolved_scene is None:
        _log_image_order(request)
    active_director_instructions = request.system_prompt_override.strip() or preset.instructions
    sections = [
        CORE_SYSTEM_PROMPT,
        TEXT_ONLY_PRIORITY_CONTRACT if text_only else LINKED_PRIORITY_CONTRACT if request.linked_references else PRIORITY_CONTRACT,
        CONTROL_CONTRACT,
    ]
    if has_visual_context:
        sections.append(f"VISUAL GROUNDING\n{get_vision_mode_adapter(request.mode)}")
    sections.extend([
        f"MODE ADAPTER\n{get_mode_adapter(request.mode)}",
        f"TARGET MODEL ADAPTER\n{get_model_adapter(request.target_model)}",
        "USER SETTINGS",
        _CREATIVITY_ADAPTERS.get(request.creativity, _CREATIVITY_ADAPTERS["Balanced"]),
        _LENGTH_ADAPTERS.get(request.prompt_length, _LENGTH_ADAPTERS["Medium"]),
    ])

    sections.append(_preservation_section(
        replace(request, linked_references=False) if text_only else request,
        resolved_reference_map, has_visual_context,
    ))

    sections.append(f"DIRECTOR BEHAVIOR — {preset.label}\n{active_director_instructions}")
    if request.custom_instructions.strip():
        sections.append(f"WORKFLOW RULES\n{request.custom_instructions.strip()}")

    if resolved_scene is not None:
        compiler_input = resolved_scene.compiler_input(request.target_model)
        sections.append(compiler_input)
        if debug_prompts_enabled():
            print("[Goated Prompter FINAL COMPILER INPUT]", flush=True)
            print(compiler_input, flush=True)
    elif has_raw_image or (request.linked_references and not text_only):
        reference_constraints = resolved_reference_map.to_instructions()
        sections.append(reference_constraints)
        print("[Goated Prompter DIRECTOR CONSTRAINTS]", flush=True)
        print(resolved_reference_map.director_constraints(), flush=True)

    sections.append(OUTPUT_CONTRACT)

    if has_visual_context:
        user_message = (
            "USER REQUESTED CHANGES / DIRECTION:\n" + idea
            if idea
            else "USER REQUESTED CHANGES / DIRECTION:\nNo additional change requested; follow the selected mode using only observed image content."
        )
    else:
        user_message = idea
    return PromptInstruction(
        system_message="\n\n".join(sections),
        user_message=user_message,
        image=request.image if has_raw_image and resolved_scene is None else None,
        image_2=request.image_2 if has_raw_image and resolved_scene is None else None,
        image_3=request.image_3 if has_raw_image and resolved_scene is None else None,
        image_4=request.image_4 if has_raw_image and resolved_scene is None else None,
        image_1_role=_reference_role(request.image_1_role),
        image_2_role=_reference_role(request.image_2_role),
        reference_map=resolved_reference_map,
        resolved_scene=resolved_scene,
        model_family=model_family or infer_prompt_model_family(request.selected_prompt_model),
        director_preset=preset.label,
        max_tokens=3072 if request.prompt_length in {"Maximum", "Maximum Detail"} else None,
    )


def _effective_model_family(request, profile, effective_config):
    if profile is not None:
        return profile.model_family
    local_settings = effective_config.get("local_llama_cpp", {}) if isinstance(effective_config, dict) else {}
    identity = " ".join(
        str(local_settings.get(field) or "").casefold()
        for field in ("model_path", "mmproj_path")
    )
    if "gemma" in identity:
        return "gemma"
    if "qwen" in identity:
        return "qwen"
    return infer_prompt_model_family(request.selected_prompt_model)


def _analysis_model_identity(request, profile, effective_config):
    config = effective_config if isinstance(effective_config, dict) else {}
    backend_name = str(config.get("backend") or "unknown")
    selected = str(getattr(profile, "prompt_model", "") or request.selected_prompt_model)
    local = config.get("local_llama_cpp", {}) if isinstance(config.get("local_llama_cpp", {}), dict) else {}
    remote = config.get("openai_compatible", {}) if isinstance(config.get("openai_compatible", {}), dict) else {}
    critical = (
        local.get("model_path"), local.get("mmproj_path"), local.get("alias"),
        remote.get("model"), remote.get("base_url"),
    )
    return "|".join([backend_name, selected, *(str(value or "") for value in critical)])


def _diagnostic_context(request, evidence_digest="NONE"):
    return {
        "model": request.selected_prompt_model,
        "preset": request.director_preset,
        "length": request.prompt_length,
        "target": request.target_model,
        "creativity": request.creativity,
        "director_override": bool(request.system_prompt_override.strip()),
        "workflow_rules": bool(request.custom_instructions.strip()),
        "image_references": len(reference_images(request)),
        "evidence_sha256": evidence_digest,
    }


def _analyze_image_evidence(backend, image, source_label, model_family, analysis_model, request, checkpoint=None):
    key = evidence_cache_key(image, analysis_model)
    evidence = get_cached_evidence(key)
    cache_state = "HIT"
    if evidence is None:
        cache_state = "MISS"
        instruction = PromptInstruction(
            system_message=EVIDENCE_ANALYSIS_SYSTEM_PROMPT,
            user_message=evidence_analysis_user_message(source_label),
            image=image,
            model_family=model_family,
            image_label=source_label,
            diagnostic_stage=f"evidence:{source_label.casefold().replace(' ', '_')}",
            diagnostic_context=_diagnostic_context(request),
        )
        backend.validate_instruction(instruction)
        if checkpoint is not None:
            checkpoint()
        raw_evidence = backend.generate(instruction)
        if checkpoint is not None:
            checkpoint()
        evidence = parse_image_evidence(raw_evidence, key[0])
        cache_evidence(key, evidence)
    log_evidence_result(source_label, evidence, cache_state)
    print(f"[Goated Prompter {source_label.upper()} EVIDENCE]", flush=True)
    print(f"Cache = {cache_state}; sha256={evidence.fingerprint}", flush=True)
    if debug_prompts_enabled():
        print(evidence.diagnostic_text(), flush=True)
    return evidence


class GoatedPrompterService:
    """Stateless facade that assembles instructions and resolves a backend per call."""

    def __init__(self, config=None, config_path=None, checkpoint=None):
        self._config = config
        self._config_path = config_path
        self._checkpoint = checkpoint

    def assemble(
        self,
        request,
        model_family=None,
        resolved_scene=None,
        resolved_reference_map=None,
        text_only=False,
    ):
        return assemble_instruction(
            request,
            model_family=model_family,
            resolved_scene=resolved_scene,
            resolved_reference_map=resolved_reference_map,
            text_only=text_only,
        )

    def generate(self, request):
        return self._generate(request, text_only=False)

    def generate_text_only(self, request):
        """Generate from text settings without touching image/reference state."""
        if not str(request.idea or "").strip():
            raise ValueError("Enter a text prompt first.")
        sanitized = replace(
            request,
            image=None,
            image_2=None,
            image_3=None,
            image_4=None,
            linked_references=False,
            reference_map=None,
            image_1_role="Auto",
            image_2_role="Auto",
            preserve_subject=False,
            preserve_composition=False,
            preserve_camera=False,
            preserve_materials=False,
            preserve_lighting=False,
            preserve_colors=False,
        )
        return self._generate(sanitized, text_only=True)

    def _generate(self, request, text_only=False):
        if self._checkpoint is not None:
            self._checkpoint()
        config = self._config if self._config is not None else load_config(self._config_path)
        effective_config, profile = resolve_director_config(config, request)
        backend = create_backend(effective_config)
        vision_config = effective_config.get("vision", {}) if isinstance(effective_config, dict) else {}
        if not isinstance(vision_config, dict):
            vision_config = {}
        max_dimension = vision_config.get("max_image_dimension", 1344)
        resolved_reference_map = None
        selected_sources = set()
        if not text_only:
            preset = get_director_preset(request.director_preset)
            # Resolve before encoding without dropping connected-image identity.
            resolved_reference_map = resolve_reference_map(request, preset.label)
            selected_sources = {item.source for item in resolved_reference_map.attributes}
            if "Blend" in selected_sources:
                selected_sources.update(reference_images(request))
            if request.linked_references and not request.idea.strip() and not any(
                label in selected_sources for _field, label in REFERENCE_IMAGE_SLOTS
            ):
                raise ValueError("All reference attributes are Off. Enter an idea or select an uploaded image source for at least one attribute.")
            if not reference_images(request) and not request.linked_references:
                resolved_reference_map = None
        for field, label in REFERENCE_IMAGE_SLOTS:
            image = getattr(request, field)
            if label in selected_sources:
                backend.validate_vision_input(image)
                if not isinstance(image, EncodedImage):
                    request = replace(request, **{field: encode_comfy_image(image, max_dimension=max_dimension)})
        model_family = _effective_model_family(request, profile, effective_config)

        # One lifecycle session covers the complete operation. This keeps a
        # manual unload request deferred across evidence analysis, compilation,
        # and any current or future final enhancement pass.
        with backend.generation_session() as session_backend:
            resolved_scene = None
            if resolved_reference_map is not None:
                _log_image_order(request)
                analysis_model = _analysis_model_identity(request, profile, effective_config)
                evidence_by_source = {
                    label: _analyze_image_evidence(
                        session_backend, image, label, model_family, analysis_model, request,
                        checkpoint=self._checkpoint,
                    )
                    for label, image in reference_images(request).items() if label in selected_sources
                }
                resolved_scene = build_resolved_scene(
                    resolved_reference_map,
                    user_prompt=request.idea,
                    evidence_by_source=evidence_by_source,
                )
                if debug_prompts_enabled():
                    print("[Goated Prompter RESOLVED SCENE]", flush=True)
                    print(resolved_scene.diagnostic_text(), flush=True)
            instruction = self.assemble(
                request,
                model_family=model_family,
                resolved_scene=resolved_scene,
                resolved_reference_map=resolved_reference_map,
                text_only=text_only,
            )
            instruction = replace(
                instruction,
                diagnostic_stage="final",
                diagnostic_context=_diagnostic_context(
                    request,
                    evidence_digest=resolved_scene_sha256(resolved_scene) if resolved_scene is not None else "NONE",
                ),
            )
            session_backend.validate_instruction(instruction)
            if self._checkpoint is not None:
                self._checkpoint()
            prompt = str(session_backend.generate(instruction) or "").strip()
            if self._checkpoint is not None:
                self._checkpoint()
        if not prompt:
            raise RuntimeError("Goated Prompter backend returned an empty prompt.")
        return GenerationResult(
            prompt=prompt,
            backend_name=backend.name,
            instruction=instruction,
            director_profile=profile.label if profile else "",
            prompt_model=profile.prompt_model if profile else request.selected_prompt_model,
            director_preset=instruction.director_preset,
        )
