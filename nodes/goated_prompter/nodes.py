"""ComfyUI node definition for Goated Prompter."""

from .core import CREATIVITY_NAMES, PROMPT_LENGTH_NAMES, REFERENCE_ROLE_NAMES, GoatedPrompterRequest, GoatedPrompterService
from .director_profiles import PROMPT_MODEL_NAMES
from .models import TARGET_MODEL_NAMES
from .modes import MODE_NAMES
from .presets import DEFAULT_DIRECTOR_PRESET, legacy_preset_for_mode
from .reference_map import REFERENCE_ATTRIBUTES, REFERENCE_SOURCE_NAMES


def _execution_result(prompt):
    """Return one exact prompt to both downstream nodes and the ComfyUI frontend."""
    return {"ui": {"generated_prompt": [prompt]}, "result": (prompt,)}


class GoatedPrompter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
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
                "director_context_size": ("INT", {"default": 8192, "min": 512, "max": 1048576}),
                "director_image_min_tokens": ("INT", {"default": 1024, "min": 1, "max": 1048576}),
                "director_max_tokens": ("INT", {"default": 768, "min": 1, "max": 1048576}),
                "director_gpu_layers": ("STRING", {"default": "auto"}),
                "director_keep_model_loaded": ("BOOLEAN", {"default": False}),
                "director_preset": ("STRING", {"default": DEFAULT_DIRECTOR_PRESET}),
                "image_1_role": (REFERENCE_ROLE_NAMES, {"default": "Auto"}),
                "image_2_role": (REFERENCE_ROLE_NAMES, {"default": "Auto"}),
                "lock_generated_prompt": ("BOOLEAN", {"default": False}),
                **{
                    f"reference_{attribute}_source": (REFERENCE_SOURCE_NAMES, {"default": "Auto"})
                    for attribute, _label in REFERENCE_ATTRIBUTES
                },
            },
            "optional": {
                "image": ("IMAGE",),
                "image_2": ("IMAGE",),
                "image_3": ("IMAGE",),
                "image_4": ("IMAGE",),
                "linked_references": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "direct"
    CATEGORY = "Goated Prompter"
    DESCRIPTION = "Transforms a rough visual idea into a model-aware image or video prompt."

    def direct(
        self,
        idea,
        mode,
        target_model,
        creativity,
        preserve_subject,
        preserve_composition,
        preserve_camera,
        preserve_materials,
        preserve_lighting,
        preserve_colors,
        prompt_length,
        custom_instructions,
        system_prompt_override,
        generated_prompt,
        prompt_model="Qwen 3.5 9B",
        director_profile="",
        director_model_path="",
        director_mmproj_path="",
        director_llama_server="",
        director_context_size=8192,
        director_image_min_tokens=1024,
        director_max_tokens=768,
        director_gpu_layers="auto",
        director_keep_model_loaded=False,
        director_preset=DEFAULT_DIRECTOR_PRESET,
        image_1_role="Auto",
        image_2_role="Auto",
        lock_generated_prompt=False,
        image=None,
        image_2=None,
        director_ai="",
        reference_subject_source="Auto",
        reference_face_source="Auto",
        reference_outfit_source="Auto",
        reference_pose_source="Auto",
        reference_composition_source="Auto",
        reference_camera_source="Auto",
        reference_scene_source="Auto",
        reference_lighting_source="Auto",
        reference_colors_source="Auto",
        reference_mood_source="Auto",
        reference_materials_source="Auto",
        image_3=None,
        image_4=None,
        linked_references=False,
    ):
        generated = str(generated_prompt or "")
        if lock_generated_prompt:
            if not generated.strip():
                raise ValueError("Generated Prompt is locked but empty. Generate or enter a prompt before queueing.")
            return _execution_result(generated)

        cached = generated.strip()
        if cached and image is None and image_2 is None and image_3 is None and image_4 is None:
            return _execution_result(cached)

        request = GoatedPrompterRequest(
            idea=str(idea or ""), mode=mode, target_model=target_model, creativity=creativity,
            preserve_subject=preserve_subject, preserve_composition=preserve_composition,
            preserve_camera=preserve_camera, preserve_materials=preserve_materials,
            preserve_lighting=preserve_lighting, preserve_colors=preserve_colors,
            prompt_length=prompt_length, custom_instructions=str(custom_instructions or ""),
            system_prompt_override=str(system_prompt_override or ""),
            prompt_model=str(director_ai or prompt_model or "Qwen 3.5 9B"),
            director_preset=str(
                legacy_preset_for_mode(mode)
                if director_ai and director_preset == DEFAULT_DIRECTOR_PRESET
                else director_preset or DEFAULT_DIRECTOR_PRESET
            ),
            director_profile=str(director_profile or ""),
            director_model_path=str(director_model_path or ""),
            director_mmproj_path=str(director_mmproj_path or ""),
            director_llama_server=str(director_llama_server or ""),
            director_context_size=director_context_size,
            director_image_min_tokens=director_image_min_tokens,
            director_max_tokens=director_max_tokens,
            director_gpu_layers=str(director_gpu_layers or "auto"),
            director_keep_model_loaded=director_keep_model_loaded,
            image=image,
            image_2=image_2,
            image_3=image_3,
            image_4=image_4,
            linked_references=linked_references,
            image_1_role=str(image_1_role or "Auto"),
            image_2_role=str(image_2_role or "Auto"),
            reference_map={
                "subject": reference_subject_source,
                "face": reference_face_source,
                "outfit": reference_outfit_source,
                "pose": reference_pose_source,
                "composition": reference_composition_source,
                "camera": reference_camera_source,
                "scene": reference_scene_source,
                "lighting": reference_lighting_source,
                "colors": reference_colors_source,
                "mood": reference_mood_source,
                "materials": reference_materials_source,
            },
        )
        return _execution_result(GoatedPrompterService().generate(request).prompt)


NODE_CLASS_MAPPINGS = {"GoatedPrompter": GoatedPrompter}
NODE_DISPLAY_NAME_MAPPINGS = {"GoatedPrompter": "Goated Prompter"}
