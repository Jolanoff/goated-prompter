"""Standalone website input options and defaults for the bootstrap API."""

from .core import CREATIVITY_NAMES, PROMPT_LENGTH_NAMES, REFERENCE_ROLE_NAMES
from .director_profiles import PROMPT_MODEL_NAMES
from .prompting.modes import MODE_NAMES
from .prompting.target_models import TARGET_MODEL_NAMES
from .presets import DEFAULT_DIRECTOR_PRESET
from .reference_map import REFERENCE_ATTRIBUTES, REFERENCE_SOURCE_NAMES


def builder_input_schema():
    """Return fresh input metadata, preserving the website's bootstrap contract."""
    return {
        "idea": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
        "mode": (MODE_NAMES, {"default": "Enhance"}),
        "target_model": (TARGET_MODEL_NAMES, {"default": "Generic"}),
        "creativity": (CREATIVITY_NAMES, {"default": "Balanced"}),
        "preserve_subject": ("BOOLEAN", {"default": True}),
        "preserve_composition": ("BOOLEAN", {"default": False}),
        "preserve_camera": ("BOOLEAN", {"default": False}),
        "preserve_materials": ("BOOLEAN", {"default": False}),
        "preserve_lighting": ("BOOLEAN", {"default": False}),
        "preserve_colors": ("BOOLEAN", {"default": False}),
        "prompt_length": (PROMPT_LENGTH_NAMES, {"default": "Medium"}),
        "custom_instructions": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
        "system_prompt_override": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
        "generated_prompt": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
        "prompt_model": (PROMPT_MODEL_NAMES, {"default": "Qwen 3.5 9B"}),
        "director_profile": ("STRING", {"default": ""}),
        "director_model_path": ("STRING", {"default": ""}),
        "director_mmproj_path": ("STRING", {"default": ""}),
        "director_llama_server": ("STRING", {"default": ""}),
        "director_context_size": ("INT", {"default": 32768, "min": 512, "max": 1048576}),
        "director_image_min_tokens": ("INT", {"default": 1024, "min": 1, "max": 1048576}),
        "director_max_tokens": ("INT", {"default": 4096, "min": 1, "max": 1048576}),
        "director_gpu_layers": ("STRING", {"default": "auto"}),
        "director_keep_model_loaded": ("BOOLEAN", {"default": False}),
        "director_preset": ("STRING", {"default": DEFAULT_DIRECTOR_PRESET}),
        "image_1_role": (REFERENCE_ROLE_NAMES, {"default": "Auto"}),
        "image_2_role": (REFERENCE_ROLE_NAMES, {"default": "Auto"}),
        **{
            f"reference_{attribute}_source": (REFERENCE_SOURCE_NAMES, {"default": "Auto"})
            for attribute, _label in REFERENCE_ATTRIBUTES
        },
    }
