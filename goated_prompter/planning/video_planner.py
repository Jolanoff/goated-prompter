"""Temporal staging after the existing symbolic-reference analysis."""

import json
from ..contracts import PromptInstruction
from ..minimax_contract import exact_dialogue, parse_shot_outline
from .constraints import compile_request, COMPILED_CONTRACT
from .scene_planner import AUTHORITY, supporting_pass
from .validation import validate_plan
from .video_plan import VideoScenePlan


def video_planning_instruction(data, reference_analysis, compiled, *, family="qwen"):
    shots = parse_shot_outline(data["user_request"], data["duration_seconds"])
    return PromptInstruction(system_message=AUTHORITY + "\n" + COMPILED_CONTRACT + """
VIDEO SCENE PLANNING, NOT H3 WRITING
Resolve what happens, in what order, motion mechanics, interactions, continuity,
requested audio/dialogue placement and what the camera needs to reveal.
References are symbolic and UNSEEN. The existing reference_analysis is authoritative
for source roles. Never invent observed identity, appearance, wardrobe, environment,
motion steps or audio. Refer to the requested characteristic from <imageN>/<videoN>/
<audioN> symbolically. Do not transfer unrequested source characteristics or enable
unrequested source audio. Do not generate another reference analysis.
Do not claim anything is "observed in", "seen in" or "shown in" a symbolic token.
Say "requested identity from <imageN>" or "requested movement characteristics
from <videoN>". Do not expand identity into extra source appearance facts or assign
it to additional participants unless the authoritative analysis/user specifies that.
Echo protected_dialogue byte-for-byte if supplied, never paraphrase lyrics or speech.
If shot_outline is supplied, enrich only inside those shots: echo their number,
start_ms and end_ms exactly in shot_details. Never add/remove/reorder/merge/split shots.
Without supplied shots, plan a continuous action progression, not invented cuts.
No H3 sections, shot headings, speaker IDs, dialogue tags or target syntax.
Return only compact JSON. Optional fields core_intent (text), subjects,
action_progression, interactions, continuity, camera_intent, audio_intent,
reference_constraints, protected_dialogue, required, forbidden, variable, uncertainties
(lists of concise text). action_progression must be nonempty.
subjects must be a list of TEXT entries, one per participant, not objects.
continuity, camera_intent and audio_intent must be arrays of text, even for one entry.
Required/forbidden/variable are compiler-owned: omit those fields; they will be
attached unchanged from the supplied constraints. Do not reinterpret those lists.
No unspecified wardrobe, lighting, setting or detailed visual treatment. For
camera_intent describe only requested camera motion/necessary action visibility.
Example SHAPE only: {"action_progression":["requested opening action","requested
next action"],"subjects":["participant A"],"continuity":["identity stays stable"],
"camera_intent":["reveal requested contact"],"audio_intent":[]}.
For supplied shots include shot_details: [{"number":integer,"start_ms":integer,
"end_ms":integer,"action":"concise physical action inside this existing shot"}].
Normally fewer than 450 words.
""", user_message=json.dumps({"user_request": compiled.positive_request, "constraints": compiled.workflow_data(),
        "reference_analysis": reference_analysis, "shot_outline": shots,
        "duration_seconds": data["duration_seconds"], "protected_dialogue": exact_dialogue(data["user_request"])}, ensure_ascii=False),
        model_family=family, diagnostic_stage="minimax:video_planning", max_tokens=1600,
        hard_max_tokens=1600, stream_character_limit=7000, temperature=.25, top_p=.85)


def plan_video_scene(session, data, reference_analysis, *, family="qwen", checkpoint=None, progress=None, semantic_validation=False):
    compiled = compile_request(data["user_request"], has_context=bool(reference_analysis["references"]))
    shots = parse_shot_outline(data["user_request"], data["duration_seconds"])
    def validate(raw):
        details = validate_plan(raw, compiled, video=True, reference_analysis=reference_analysis,
                                shots=shots, dialogue=exact_dialogue(data["user_request"]))
        if semantic_validation:
            from .semantic_validation import invariant_contract, review_candidate
            contract = invariant_contract(compiled.original, constraints=compiled.workflow_data(), temporal=shots)
            contract["reference_roles"] = reference_analysis
            review_candidate(session, contract,
                json.dumps(details, ensure_ascii=False), stage="minimax:plan", family=family, checkpoint=checkpoint,
                checks=("action_fidelity", "scene_fidelity", "constraint_validity", "temporal_fidelity"))
        return VideoScenePlan(details, compiled)
    return supporting_pass(session, data["planning_mode"], data["user_request"],
        lambda: video_planning_instruction(data, reference_analysis, compiled, family=family),
        validate,
        checkpoint=checkpoint, progress=progress, video=True)
