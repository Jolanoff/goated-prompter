"""MiniMax H3 backend orchestration."""

from dataclasses import replace
from .backends.base import BackendGenerationError
from .backends.factory import create_backend
from .contracts import effective_model_family
from .director_profiles import resolve_director_config
from .presets import get_director_preset
from .prompting.minimax import *


class MiniMaxService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _call(self, session, instruction, validator, progress, retry_budget, contract=None):
        original = instruction
        attempt = 0
        while True:
            self.checkpoint()
            session.validate_instruction(instruction)
            raw = session.generate(instruction)
            self.checkpoint()
            try:
                candidate = validator(raw)
                session.emit_activity("validation", workflow="minimax", attempt=attempt, accepted=True)
                return candidate
            except ValueError as exc:
                from .planning.semantic_validation import SemanticValidationError
                session.emit_activity("validation", workflow="minimax", attempt=attempt, accepted=False,
                    format_valid=True if isinstance(exc, SemanticValidationError) else None,
                    error=str(exc), issues=getattr(exc, "issues", []))
                if retry_budget[0] == 0:
                    raise BackendGenerationError(f"MiniMax prompt validation failed after {REPAIR_ATTEMPTS} repair attempts: {exc}") from exc
                retry_budget[0] -= 1
                attempt += 1
                progress(
                    f"MiniMax output failed validation: {exc} Correcting the output "
                    f"(retry {REPAIR_ATTEMPTS - retry_budget[0]}/{REPAIR_ATTEMPTS})."
                )
                instruction = repair_instruction(original, raw, exc)
                if contract is not None:
                    from .planning.semantic_validation import repair_contract
                    contract.update(previous_response=raw, listed_defect=str(exc))
                    instruction = replace(instruction, user_message=instruction.user_message
                        + repair_contract(contract, raw, exc, getattr(exc, "accepted_facts", ())))

    def run(self, request, data, progress):
        data = validate_minimax_draft(data, generation=True)
        director = get_director_preset(data["director_preset"], strict=True)
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = effective_model_family(request, profile, effective)
        retry_budget = [REPAIR_ATTEMPTS]
        progress("Starting the prompt engine for MiniMax…")
        with backend.generation_session() as session:
            if data["references"]:
                progress("Understanding reference roles")
                plan = self._call(session, analysis_instruction(data, family), lambda raw: validate_analysis(raw, data), progress, retry_budget)
            else:
                plan = validate_analysis('{"references": [], "first_frame": null, "last_frame": null}', data)
            video_scene_plan, planning_status = None, "direct"
            from .planning.semantic_validation import enabled, constraints_enabled, invariant_contract, review_candidate
            from .planning.constraints import compile_request
            validate_semantics = enabled(effective)
            if data["planning_mode"] != "Direct":
                from .planning.video_planner import plan_video_scene
                video_scene_plan, planning_status = plan_video_scene(session, data, plan,
                    family=family, checkpoint=self.checkpoint, progress=progress,
                    **({"semantic_validation": True} if validate_semantics else {}))
            compiled = compile_request(data["user_request"], has_context=bool(plan["references"]))
            audit_constraints = bool(compiled.forbidden) and constraints_enabled(effective)
            contract = invariant_contract(data["user_request"], planned=video_scene_plan.details if video_scene_plan else None,
                constraints=compiled.workflow_data(), literal_text=exact_dialogue(data["user_request"]),
                target="MiniMax H3", temporal=parse_shot_outline(data["user_request"], data["duration_seconds"]))
            contract["reference_roles"] = plan
            accepted_facts = ()
            def validate_final(raw):
                nonlocal accepted_facts
                candidate = validate_output(raw, data, plan)
                if validate_semantics or audit_constraints:
                    from .planning.semantic_validation import SemanticValidationError
                    try:
                        accepted_facts = review_candidate(session, {**contract, "accepted_facts": list(accepted_facts)}, candidate,
                            stage="minimax:final", family=family, checkpoint=self.checkpoint,
                            checks=("action_fidelity", "scene_fidelity", "constraint_validity", "temporal_fidelity",
                                    *(["repair_preservation"] if contract.get("previous_response") else []))
                            if validate_semantics else ("constraint_validity",))
                    except SemanticValidationError as exc:
                        accepted_facts = exc.accepted_facts or accepted_facts
                        raise
                return candidate
            progress("Writing MiniMax H3 prompt")
            prompt = self._call(session, generation_instruction(data, plan, director, family,
                **({"video_scene_plan": video_scene_plan} if video_scene_plan is not None else {})), validate_final, progress, retry_budget, contract)
        return {"ok": True, "kind": "minimax", "prompt": prompt, "mode": plan["mode"],
                "warnings": reference_warnings(data), "backend": backend.name, "planning_status": planning_status}
