"""Refine workflow runtime and validated prompt generation."""

from dataclasses import replace
import re

from ...backends.base import BackendGenerationError
from ...backends.factory import create_backend
from ...contracts import PromptInstruction, effective_model_family
from ...director_profiles import resolve_director_config
from .prompting import build_refine_messages, refine_format_repair
from ...prompting.output import output_contract
from ...prompting.target_models import get_model_adapter
from ...workflow_output import (
    WorkflowFormatError,
    normalize_workflow_output,
    sanitize_prompt_text,
    requested_visible_text,
)


def refine_instruction(request, base, changes, detail_locks, model_family="qwen", instructions=None):
    contract = output_contract(request.target_model)
    system, user = build_refine_messages(
        base,
        changes,
        detail_locks,
        get_model_adapter(request.target_model),
        contract,
        instructions,
    )
    # No Length or Creativity text: Refine keeps the source's density and changes only what is asked, so a default
    # length or an invitation to add details would contradict its own contract.
    return PromptInstruction(
        system_message=system,
        user_message=user,
        model_family=model_family,
        diagnostic_stage="refine:edit",
        max_tokens=None,
        unlimited_tokens=True,
    )


_H3_FIELD = re.compile(r"^\s*(?:integrated_multimodal_description|detailed_description)\b", re.MULTILINE)


def source_mode(base):
    """The task the source prompt was written for, as far as its output needs it: a MiniMax source written as H3 video
    fields stays a video; any other source keeps its own form (None leaves other targets unchanged)."""
    return "Video" if _H3_FIELD.search(str(base or "")) else "Enhance" if str(base or "").strip() else None


class RefineService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _generate_prompt(self, session, instruction, target, progress, *, expected_visible_text=(), mode=None):
        """Validate before persistence; allow one format-repair inference."""
        for attempt in range(2):
            self.checkpoint()
            session.validate_instruction(instruction)
            raw = session.generate(instruction)
            self.checkpoint()
            try:
                prompt = normalize_workflow_output(raw, target,
                    expected_visible_text=expected_visible_text, mode=mode)
                if target not in {"Ideogram4", "MiniMax H3"}:
                    prompt = sanitize_prompt_text(prompt)
                    if not prompt:
                        raise WorkflowFormatError("The prompt engine returned only removable metadata.")
                return prompt
            except WorkflowFormatError as exc:
                if attempt:
                    raise BackendGenerationError(
                        f"The prompt engine returned an invalid format twice. {exc}"
                    ) from exc
                progress(f"Refinement failed output validation: {exc}")
                progress("Correcting output format (one retry)")
                instruction = replace(
                    instruction,
                    system_message=refine_format_repair(
                        instruction.system_message, exc, output_contract(target)
                    ),
                    diagnostic_stage=instruction.diagnostic_stage + ":format_retry",
                )

    def run(self, request, workflow, progress):
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = effective_model_family(request, profile, effective)
        instruction = refine_instruction(
            request,
            workflow["base"],
            workflow["changes"],
            workflow["locks"],
            family,
            workflow.get("instructions"),
        )
        progress("Starting the prompt engine for refinement…")
        with backend.generation_session() as session:
            self.checkpoint()
            progress("Writing refinement")
            prompt = self._generate_prompt(session, instruction, request.target_model, progress,
                expected_visible_text=requested_visible_text(workflow["changes"]), mode=source_mode(workflow["base"]))
        return {"ok": True, "kind": "refine", "prompt": prompt, "backend": backend.name}
