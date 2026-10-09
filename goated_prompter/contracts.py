"""Shared workflow contracts: the engine request, assembled instruction and generation result.

This module is a dependency leaf for workflows and planning; it must not import
workflow services, so any module can depend on it without an import cycle.
"""

from dataclasses import dataclass

from .director_profiles import canonical_prompt_model, infer_prompt_model_family
from .image_utils import EncodedImage
from .planning import planning_mode
from .presets import DEFAULT_DIRECTOR_PRESET, legacy_preset_for_mode
from .prompting.details import REFERENCE_ROLE_NAMES
from .prompting.target_models import canonical_target
from .reference_map import reference_images, reference_map_from_mapping


def as_bool(value):
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
    director_context_size: int = 32768
    director_image_min_tokens: int = 1024
    director_max_tokens: int = 4096
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
    planning_mode: str = "Auto"

    def __post_init__(self):
        object.__setattr__(self, "target_model", canonical_target(self.target_model))
        planning_mode(self.planning_mode)

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
            director_context_size=int(values.get("director_context_size", 32768)),
            director_image_min_tokens=int(values.get("director_image_min_tokens", 1024)),
            director_max_tokens=int(values.get("director_max_tokens", 4096)),
            director_gpu_layers=str(values.get("director_gpu_layers") or "auto"),
            director_keep_model_loaded=as_bool(values.get("director_keep_model_loaded", False)),
            preserve_subject=as_bool(values.get("preserve_subject", True)),
            preserve_composition=as_bool(values.get("preserve_composition", False)),
            preserve_camera=as_bool(values.get("preserve_camera", False)),
            preserve_materials=as_bool(values.get("preserve_materials", False)),
            preserve_lighting=as_bool(values.get("preserve_lighting", False)),
            preserve_colors=as_bool(values.get("preserve_colors", False)),
            prompt_length="Maximum Detail" if values.get("prompt_length") == "Maximum" else str(values.get("prompt_length") or "Medium"),
            custom_instructions=str(values.get("custom_instructions") or ""),
            system_prompt_override=str(values.get("system_prompt_override") or ""),
            reference_map=reference_map_from_mapping(values),
            image_1_role=_reference_role(values.get("image_1_role")),
            image_2_role=_reference_role(values.get("image_2_role")),
            linked_references=as_bool(values.get("linked_references", False)),
            planning_mode=str(values.get("planning_mode", "Auto")),
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
    # Opt out of application output budgets; the engine's context still applies.
    unlimited_tokens: bool = False
    # A workflow safety ceiling. Unlike max_tokens, this may lower the backend's
    # configured allowance and protects bounded outputs from runaway generation.
    hard_max_tokens: int = None
    # Optional bounded stream ceiling for structured batch planning. Individual
    # prompt workflows retain the transport's default runaway-output ceiling.
    stream_character_limit: int = None
    # Exact user wording is not evidence of a generated tag loop.
    repetition_protected_terms: tuple = ()
    # Tag syntax is a writer contract, not a rule for structured planning text.
    tag_repetition_checks: bool = False
    # Request-local sampling; supporting planners use conservative values.
    temperature: float = None
    top_p: float = None
    # Structured stages can request llama.cpp JSON decoding without changing writers.
    json_output: bool = False
    json_schema: dict = None

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
    planning_status: str = "direct"


def effective_model_family(request, profile, effective_config):
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
