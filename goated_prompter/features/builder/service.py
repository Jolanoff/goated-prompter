"""Prompt assembly and backend orchestration for the standalone website."""

import base64
from dataclasses import replace
import json
import hashlib

from ...backends.factory import create_backend
from ...backends.base import BackendGenerationError
from ...config import load_config
from ...director_profiles import infer_prompt_model_family, resolve_director_config
from ...diagnostics import debug_prompts_enabled, log_evidence_result, resolved_scene_sha256
from .evidence import (
    build_resolved_scene,
    cache_evidence,
    evidence_cache_key,
    get_cached_evidence,
    parse_image_evidence,
)
from ...image_utils import EncodedImage
from ...prompting.base import (
    CORE_SYSTEM_PROMPT,
    LINKED_PRIORITY_CONTRACT,
    PRIORITY_CONTRACT,
    TEXT_ONLY_PRIORITY_CONTRACT,
)
from ...prompting.creativity import CREATIVITY_ADAPTERS as _CREATIVITY_ADAPTERS
from ...prompting.styles import style_section
from ...prompting.details import LENGTH_ADAPTERS as _LENGTH_ADAPTERS, MAXIMUM_DETAIL_GUIDANCE as _MAXIMUM_DETAIL_GUIDANCE, PRESERVATION_ADAPTERS as _PRESERVATION_ADAPTERS, PRESERVATION_LINKED_LOCK, PRESERVATION_NO_LINKED_LOCKS, PRESERVATION_NONE
from .prompting import EVIDENCE_ANALYSIS_SYSTEM_PROMPT, evidence_analysis_user_message
from ...prompting.modes import get_mode_adapter, get_vision_mode_adapter
from ...prompting.output import OUTPUT_CONTRACT, output_contract, qwen_format_repair, minimax_format_repair
from ...prompting.target_models import QWEN21_EDIT_ADAPTER, get_model_adapter, get_target_example, library_reference_section, resolve_target_length, get_target_capabilities
from ...prompt_library import copied_reference, library_file_name, library_profile, pick_references, pick_scenarios, style_profile_text
from ...presets import get_director_preset
from ...options.references import REFERENCE_IMAGE_SLOTS
from ...reference_map import reference_images, resolve_reference_map
from ...output_repetition import drop_repeated_tags, remove_contradictory_solo
from ...workflow_output import WorkflowFormatError, normalize_workflow_output, sanitize_prompt_text, requested_visible_text
from ...contracts import GenerationResult, PromptInstruction, _reference_role, effective_model_family


def _qwen21_source_tokens(request, reference_map=None, text_only=False):
    """Use selected sources even when the final compiler receives evidence, not images."""
    if text_only:
        return ()
    labels = tuple(reference_images(request))
    if reference_map is not None:
        selected = {item.source for item in reference_map.attributes}
        if "Blend" not in selected:
            labels = tuple(label for label in labels if label in selected)
    return tuple(f"<image{label.split()[-1]}>" for label in labels)

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

def assemble_instruction(
    request,
    model_family=None,
    resolved_scene=None,
    resolved_reference_map=None,
    text_only=False,
    prompt_scene_plan=None,
    compile_user_constraints=True,
    include_target_example=True,
    references=None,
):
    if text_only:
        resolved_scene = None
    idea = (prompt_scene_plan.compiled_request.writer_request(include_constraints=False) if prompt_scene_plan is not None else request.idea).strip()
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
    if preset.supported_targets and request.target_model not in preset.supported_targets:
        # A target-specific Director that does not apply contributes nothing.
        active_director_instructions = ""
    qwen_images = _qwen21_source_tokens(request, resolved_reference_map, text_only) if request.target_model == "Qwen Image 2.1" else ()
    # Reference priorities only apply when reference images or evidence are present.
    sections = [
        CORE_SYSTEM_PROMPT,
        TEXT_ONLY_PRIORITY_CONTRACT if text_only or not has_visual_context
        else LINKED_PRIORITY_CONTRACT if request.linked_references else PRIORITY_CONTRACT,
    ]
    # Any saved library prompt replaces the built-in example; matching ones are picked first.
    if references is None:
        references = () if qwen_images else pick_references(request.target_model, idea)
    scenario = ""
    if request.mode == "Remix":
        picks = pick_scenarios(request.target_model, idea, 1)
        if not picks:
            raise ValueError(f"Remix needs saved prompts in data/prompt_library/{library_file_name(request.target_model)} "
                             f"for {request.target_model}.")
        scenario = picks[0]
        # The recast scenario is meant to be reused, so it is neither a style reference nor copy-checked.
        references = tuple(reference for reference in references if reference != scenario)
    # Library templates go last, right before the output rules, so the user's way of building a
    # prompt is the freshest guidance; the built-in example stays with the adapter for empty libraries.
    library_style = library_reference_section(references, continuation=not include_target_example) if references else ""
    target_example = ("" if references else get_target_example(request.target_model, qwen_task="edit" if qwen_images else "t2i")
                      if include_target_example else "")
    if has_visual_context:
        sections.append(f"VISUAL GROUNDING\n{get_vision_mode_adapter(request.mode)}")
    sections.extend([
        f"MODE ADAPTER\n{get_mode_adapter(request.mode)}"
        + ("\n\nSCENARIO TO RECAST (from the user's prompt library)\n" + scenario
           + "\nKeep its place, situation, activity, props, camera and mood. Cast the subjects from the user's request "
           "into its roles, main role first; adapt gender, age and relationship wording; drop roles the request does not "
           "fill; never reuse its character names." if scenario else ""),
        "TARGET MODEL ADAPTER\n" + (QWEN21_EDIT_ADAPTER if qwen_images else get_model_adapter(request.target_model))
        + ("\n\n" + target_example if target_example else ""),
        "USER SETTINGS",
        _CREATIVITY_ADAPTERS.get(request.creativity, _CREATIVITY_ADAPTERS["Balanced"]),
        # With a library, structure and length are measured against the user's own prompts.
        style_profile_text(profile, request.prompt_length) if references and (profile := library_profile(request.target_model))
        else resolve_target_length(request.target_model, request.prompt_length),
    ])
    if style := style_section(request.style, request.target_model):
        sections.append(style)

    sections.append(_preservation_section(
        replace(request, linked_references=False) if text_only else request,
        resolved_reference_map, has_visual_context,
    ))

    # Library templates show how to write; the Director still decides the look, the default one included.
    if active_director_instructions:
        sections.append(f"DIRECTOR BEHAVIOR — {preset.label}\n{active_director_instructions}")
    if prompt_scene_plan is not None:
        sections.append(prompt_scene_plan.supporting_input())
    workflow_rules = request.custom_instructions
    if prompt_scene_plan is not None and prompt_scene_plan.compiled_request.workflow_rules is not None:
        workflow_rules = prompt_scene_plan.compiled_request.workflow_rules
    if workflow_rules.strip():
        sections.append(f"WORKFLOW RULES\n{workflow_rules.strip()}")

    if resolved_scene is not None:
        compiler_scene = resolved_scene
        if prompt_scene_plan is not None:
            compiler_scene = replace(resolved_scene, attributes=tuple(
                replace(item, evidence="User-requested transformation: " + prompt_scene_plan.compiled_request.positive_request)
                if item.source == "User Prompt" else item for item in resolved_scene.attributes))
        compiler_input = compiler_scene.compiler_input(request.target_model)
        sections.append(compiler_input)
        if debug_prompts_enabled():
            print("[Goated Prompter FINAL COMPILER INPUT]", flush=True)
            print(compiler_input, flush=True)
    elif has_raw_image or (request.linked_references and not text_only):
        reference_constraints = resolved_reference_map.to_instructions()
        sections.append(reference_constraints)
        print("[Goated Prompter DIRECTOR CONSTRAINTS]", flush=True)
        print(resolved_reference_map.director_constraints(), flush=True)

    if prompt_scene_plan is None and compile_user_constraints:
        from ...planning.constraints import compile_prompt_request, COMPILED_CONTRACT
        compiled = compile_prompt_request(request, has_context=has_visual_context)
        if compiled.forbidden or compiled.variable:
            # Direct still performs no planning call. Only safely compiled rule
            # clauses move from positive prose to compiler-owned restrictions.
            idea = compiled.positive_request
            if workflow_rules.strip() and compiled.workflow_rules != workflow_rules:
                sections = [section for section in sections if section != f"WORKFLOW RULES\n{workflow_rules.strip()}"]
                if compiled.workflow_rules.strip():
                    sections.append(f"WORKFLOW RULES\n{compiled.workflow_rules.strip()}")
            sections.append(COMPILED_CONTRACT + "\n" + json.dumps(compiled.workflow_data(), ensure_ascii=False))

    if request.target_model == "Qwen Image 2.1":
        if qwen_images:
            sections.append("QWEN INPUT SOURCES\nSelected source tags, keeping the reference image numbering: "
                            + ", ".join(qwen_images) + ". Image N evidence refers to <imageN>. "
                            "These sources are available through the selected evidence even if raw pixels are not attached to this final compiler call. "
                            "Do not reference unused or missing sources. Use natural language for a single image, "
                             "and individual source tags for multiple images.")

    if library_style:
        sections.append(library_style)
    sections.append(OUTPUT_CONTRACT)
    sections.append(output_contract(request.target_model, qwen_task="edit" if qwen_images else "t2i", qwen_images=qwen_images,
                                    library_style=bool(references)))

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
        max_tokens=None,
        unlimited_tokens=True,
        reference_prompts=references,
    )


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
        "style": request.style,
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
            unlimited_tokens=True,
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
        prompt_scene_plan=None,
    ):
        return assemble_instruction(
            request,
            model_family=model_family,
            resolved_scene=resolved_scene,
            resolved_reference_map=resolved_reference_map,
            text_only=text_only,
            **({"prompt_scene_plan": prompt_scene_plan} if prompt_scene_plan is not None else {}),
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
        resolved_reference_map = None
        selected_sources = set()
        if not text_only:
            preset = get_director_preset(request.director_preset)
            # Resolve before analysis without dropping uploaded-image identity.
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
                    raise ValueError("Reference images must be decoded uploads before generation.")
        model_family = effective_model_family(request, profile, effective_config)

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
            prompt_scene_plan, planning_status = None, "direct"
            from ...planning.semantic_validation import enabled, constraints_enabled, invariant_contract, review_candidate, repair_contract, SemanticValidationError
            validate_semantics = enabled(effective_config)
            if request.planning_mode != "Direct":
                from ...planning.scene_planner import plan_prompt_scene
                def planning_progress(message):
                    session_backend.emit_activity("planning", message=message)
                prompt_scene_plan, planning_status = plan_prompt_scene(
                    session_backend, request, resolved_scene=resolved_scene,
                    family=model_family, checkpoint=self._checkpoint, progress=planning_progress,
                    **({"semantic_validation": True} if validate_semantics else {}))
            instruction = self.assemble(
                request,
                model_family=model_family,
                resolved_scene=resolved_scene,
                resolved_reference_map=resolved_reference_map,
                text_only=text_only,
                **({"prompt_scene_plan": prompt_scene_plan} if prompt_scene_plan is not None else {}),
            )
            instruction = replace(
                instruction,
                diagnostic_stage="final",
                diagnostic_context=_diagnostic_context(
                    request,
                    evidence_digest=resolved_scene_sha256(resolved_scene) if resolved_scene is not None else "NONE",
                ),
            )
            qwen_images = _qwen21_source_tokens(request, resolved_reference_map, text_only) if request.target_model == "Qwen Image 2.1" else ()
            qwen_task = "edit" if qwen_images else "t2i"
            validate_format = request.target_model == "Qwen Image 2.1" or get_target_capabilities(request.target_model).supports_structured_output
            from ...planning.constraints import compile_prompt_request
            from ...planning.constraint_validation import output_constraint_issues
            compiled_constraints = compile_prompt_request(request, has_context=resolved_scene is not None or bool(reference_images(request)))
            validate_constraints = bool(compiled_constraints.forbidden)
            audit_constraints = validate_constraints and constraints_enabled(effective_config)
            semantic_contract = invariant_contract(request.idea + "\n" + request.custom_instructions,
                planned=prompt_scene_plan.details if prompt_scene_plan else None,
                constraints=compiled_constraints.workflow_data(), literal_text=requested_visible_text(request.idea), target=request.target_model)
            accepted_facts = ()
            if resolved_scene is not None:
                semantic_contract["preserved_reference_facts"] = [{"attribute":item.key,"source":item.source,"evidence":item.evidence}
                    for item in resolved_scene.attributes if item.preserve and item.source not in {"Off","User Prompt"}]
            validate_copy = bool(instruction.reference_prompts)
            for attempt in range(2 if validate_format or validate_constraints or validate_semantics or audit_constraints or validate_copy else 1):
                format_valid = None
                session_backend.validate_instruction(instruction)
                if self._checkpoint is not None:
                    self._checkpoint()
                prompt = str(session_backend.generate(instruction) or "").strip()
                if self._checkpoint is not None:
                    self._checkpoint()
                raw_candidate = prompt
                if not validate_format and not validate_constraints and not validate_semantics and not audit_constraints and not validate_copy:
                    break
                problems = []
                try:
                    if validate_format:
                        prompt = normalize_workflow_output(prompt, request.target_model,
                                                            expected_visible_text=requested_visible_text(request.idea), mode=request.mode)
                        format_valid = True
                    if validate_copy and copied_reference(prompt, instruction.reference_prompts):
                        raise WorkflowFormatError("The prompt copied wording from a library reference prompt. Write new wording "
                                                  "for this request; use the references only for style and quality.")
                    problems = [issue for issue in output_constraint_issues(prompt, request.target_model,
                        compiled_constraints.workflow_data()) if issue["severity"] == "error"] if validate_constraints else []
                    if problems:
                        raise WorkflowFormatError(problems[0]["message"])
                    if validate_semantics or audit_constraints:
                        accepted_facts = review_candidate(session_backend, {**semantic_contract, "accepted_facts": list(accepted_facts)},
                            prompt, stage="builder:final", family=model_family, checkpoint=self._checkpoint,
                            checks=("action_fidelity", "scene_fidelity", "constraint_validity", *(["repair_preservation"] if attempt else []))
                            if validate_semantics else ("constraint_validity",))
                    session_backend.emit_activity("validation", workflow="builder", attempt=attempt, accepted=True, format_valid=format_valid)
                    break
                except (WorkflowFormatError, SemanticValidationError) as exc:
                    session_backend.emit_activity("validation", workflow="builder", attempt=attempt, accepted=False,
                        format_valid=False if format_valid is None and validate_format else format_valid,
                        error=str(exc), issues=getattr(exc, "issues", []))
                    if attempt:
                        raise BackendGenerationError(f"{request.target_model} returned an invalid prompt after one format-repair attempt: {exc}") from exc
                    accepted_facts = getattr(exc, "accepted_facts", ()) or accepted_facts
                    semantic_contract.update(previous_response=raw_candidate, listed_defect=str(exc))
                    instruction = replace(instruction,
                        system_message=(instruction.system_message + "\n\nCONSTRAINT CORRECTION: " + str(exc)
                            + " Preserve the original scene/action and all supplied facts. Apply exclusions silently; change only invalid final wording."
                            if problems else minimax_format_repair(instruction.system_message, exc) if request.target_model == "MiniMax H3" else qwen_format_repair(
                            instruction.system_message,
                            exc,
                            output_contract(request.target_model, qwen_task=qwen_task, qwen_images=qwen_images),
                        )), user_message=instruction.user_message + repair_contract(semantic_contract, raw_candidate, exc, accepted_facts), temperature=.25, top_p=.85,
                        diagnostic_stage="final:semantic_retry" if isinstance(exc, SemanticValidationError) else "final:constraint_retry" if problems else "final:format_retry")
        if not prompt:
            raise RuntimeError("Goated Prompter backend returned an empty prompt.")
        if request.target_model != "Ideogram4" and not (request.target_model == "MiniMax H3" and request.mode == "Video"):
            prompt = sanitize_prompt_text(prompt)
        if request.target_model == "Anima":
            prompt = drop_repeated_tags(remove_contradictory_solo(prompt))
        if not prompt:
            raise RuntimeError("Goated Prompter backend returned only removable metadata.")
        return GenerationResult(
            prompt=prompt,
            backend_name=backend.name,
            instruction=instruction,
            director_profile=profile.label if profile else "",
            prompt_model=profile.prompt_model if profile else request.selected_prompt_model,
            director_preset=instruction.director_preset,
            planning_status=planning_status,
        )
