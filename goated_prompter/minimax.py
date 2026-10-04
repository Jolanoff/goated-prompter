"""MiniMax H3 backend orchestration."""

from .backends.base import BackendGenerationError
from .backends.factory import create_backend
from .core import _effective_model_family
from .director_profiles import resolve_director_config
from .presets import get_director_preset
from .prompting.minimax import *


class MiniMaxService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _call(self, session, instruction, validator, progress, retry_budget):
        original = instruction
        while True:
            self.checkpoint()
            session.validate_instruction(instruction)
            raw = session.generate(instruction)
            self.checkpoint()
            try:
                return validator(raw)
            except ValueError as exc:
                if retry_budget[0] == 0:
                    raise BackendGenerationError(f"MiniMax prompt validation failed after {REPAIR_ATTEMPTS} repair attempts: {exc}") from exc
                retry_budget[0] -= 1
                progress(
                    f"MiniMax output failed validation: {exc} Correcting the format "
                    f"(retry {REPAIR_ATTEMPTS - retry_budget[0]}/{REPAIR_ATTEMPTS})."
                )
                instruction = repair_instruction(original, raw, exc)

    def run(self, request, data, progress):
        data = validate_minimax_draft(data, generation=True)
        director = get_director_preset(data["director_preset"], strict=True)
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        retry_budget = [REPAIR_ATTEMPTS]
        progress("Starting the prompt engine for MiniMax…")
        with backend.generation_session() as session:
            if data["references"]:
                progress("Understanding reference roles")
                plan = self._call(session, analysis_instruction(data, family), lambda raw: validate_analysis(raw, data), progress, retry_budget)
            else:
                plan = validate_analysis('{"references": [], "first_frame": null, "last_frame": null}', data)
            video_scene_plan, planning_status = None, "direct"
            if data["planning_mode"] != "Direct":
                from .planning.video_planner import plan_video_scene
                video_scene_plan, planning_status = plan_video_scene(session, data, plan,
                    family=family, checkpoint=self.checkpoint, progress=progress)
            progress("Writing MiniMax H3 prompt")
            prompt = self._call(session, generation_instruction(data, plan, director, family,
                **({"video_scene_plan": video_scene_plan} if video_scene_plan is not None else {})), lambda raw: validate_output(raw, data, plan), progress, retry_budget)
        return {"ok": True, "kind": "minimax", "prompt": prompt, "mode": plan["mode"],
                "warnings": reference_warnings(data), "backend": backend.name, "planning_status": planning_status}
