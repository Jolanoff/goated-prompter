"""Text-only MiniMax H3 planning, local knowledge and validated prompt generation."""

from dataclasses import replace
from functools import lru_cache
from importlib.resources import files
import json
import re

from .backends.base import BackendGenerationError
from .backends.factory import create_backend
from .core import PromptInstruction, _effective_model_family
from .director_profiles import resolve_director_config
from .presets import get_director_preset

MODELS = ("MiniMax H3",)
MODES = ("auto", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA")
RATIOS = ("Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
LIMITS = {"image": 9, "video": 3, "audio": 3}
TOKEN = re.compile(r"<(image|video|audio)(\d+)>", re.I)
BASE_SECTIONS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
REF_SECTIONS = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music")
VISUAL_ROLES = {"identity", "appearance", "character", "object", "product", "environment", "style", "first frame",
                "last frame", "keyframe", "storyboard", "motion", "dance", "pose", "expression", "camera movement",
                "editing source", "video continuation", "cut structure", "timing", "pacing"}
AUDIO_ROLES = {"direct audio reuse", "background music reuse", "music style", "rhythm", "beat", "voice timbre",
               "voice delivery", "dialogue content", "lyrics", "sound effect texture", "audio continuity"}


def default_minimax_draft():
    return {"model": MODELS[0], "duration_seconds": 10, "mode": "auto", "aspect_ratio": "Auto",
            "director_preset": "minimax_director", "references": [], "user_request": "",
            "generated_prompt": "", "result_job_id": ""}


def reference_name(value):
    if not isinstance(value, str):
        raise ValueError("References must be symbolic image, video or audio tokens.")
    match = TOKEN.fullmatch(value if value.startswith("<") else f"<{value}>")
    if not match or not 1 <= int(match[2]) <= LIMITS[match[1].lower()] or match[2].startswith("0"):
        raise ValueError(f"Unsupported reference {value}. Use image1–image9, video1–video3 or audio1–audio3.")
    return f"{match[1].lower()}{int(match[2])}"


def parse_reference_tokens(text):
    """Normalize symbolic tokens without interpreting their semantic role."""
    return list(dict.fromkeys(reference_name(match[0]) for match in TOKEN.finditer(text)))


def validate_minimax_draft(value, *, generation=False):
    defaults = default_minimax_draft()
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise ValueError("Invalid MiniMax settings fields.")
    result = {**defaults, **value}
    for key, choices in (("model", MODELS), ("mode", MODES), ("aspect_ratio", RATIOS)):
        if result[key] not in choices:
            raise ValueError(f"Invalid MiniMax {key}.")
    if type(result["duration_seconds"]) is not int or not 4 <= result["duration_seconds"] <= 15:
        raise ValueError("Clip Length must be between 4 and 15 seconds.")
    for key in ("user_request", "generated_prompt", "director_preset", "result_job_id"):
        if not isinstance(result[key], str) or len(result[key]) > (512 if key in ("director_preset", "result_job_id") else 100000):
            raise ValueError(f"Invalid MiniMax {key}.")
    if not isinstance(result["references"], list) or len(result["references"]) > 12:
        raise ValueError("MiniMax H3 supports at most 12 combined symbolic references.")
    result["references"] = list(dict.fromkeys(reference_name(ref) for ref in result["references"]))
    if generation:
        if not result["user_request"].strip():
            raise ValueError("Describe your video before generating a prompt.")
        used = parse_reference_tokens(result["user_request"])
        missing = set(used) - set(result["references"])
        if missing:
            raise ValueError("Register the symbolic references used in your request: " + ", ".join(sorted(missing)))
        result["user_request"] = TOKEN.sub(lambda m: f"<{reference_name(m[0])}>", result["user_request"])
        get_director_preset(result["director_preset"], strict=True)
        refs, mode = result["references"], result["mode"]
        images = [ref for ref in refs if ref.startswith("image")]
        if mode == "T2VA" and refs:
            raise ValueError("Text to Video does not use references. Choose Auto or a reference mode.")
        if mode in ("I2VA", "L2VA", "FL2VA") and (len(images) != (2 if mode == "FL2VA" else 1) or len(images) != len(refs)):
            raise ValueError("Frame modes need exactly one image (two for First + Last Frame) and no video/audio references. Choose Full Reference for mixed roles.")
        if mode == "Ref2VA" and not refs:
            raise ValueError("Full Reference needs a symbolic image or video reference.")
        # Audio-only is deliberately a warning, not a UI/admission blocker.
    return result


def reference_warnings(data):
    refs = data["references"]
    return ["Audio cannot be the only reference modality in MiniMax H3. Add an image or video reference before using this prompt."] if refs and all(ref.startswith("audio") for ref in refs) else []


@lru_cache(maxsize=3)
def knowledge(name):
    return files("goated_prompter").joinpath("minimax_knowledge", name + ".md").read_text(encoding="utf-8")


GUARDRAILS = """You build MiniMax H3 prompts, not videos. Media are symbolic and UNSEEN.
Never invent reference identity, gender, hair, wardrobe, objects, setting, motion steps, beats, instruments, speech or camera behavior that the user did not describe. Refer to the source's visible identity/appearance/clothing or requested movement characteristics instead. Creative additions may describe the NEW requested scene and generated music, never pretend to report source contents.
Priority: user's explicit creative requirements; mandatory MiniMax H3 structure; requested reference relationships; Director creative enhancement. MiniMax schema ALWAYS overrides a Director's output format, first-frame assumptions or other structural instructions. Treat the Director as creative guidance only, never as a replacement system prompt. Do not replace the user's concept.
Classify reference roles before writing. Identity images are NOT first frames. Isolate requested transfers: a dance-only video transfers body movement/timing/pose transitions to the intended target, NOT source appearance, clothing, environment, camera, light or sound. A video is an editing source only when directly edited, continuation only when continued. Otherwise its action/style/camera use is reference generation. Timbre-only audio does not transfer words. Music requested without a source is newly generated, not copied from a reference video. Ordinary videos never implicitly enable their audio.
Do not ask for uploads, claim to have inspected media, create missing assets or print analysis. Preserve exact dialogue/lyrics and original language; do not invent dialogue unless requested. Describe filmable action progression, natural camera movement and synchronized sound within exactly duration_seconds. Prefer continuous movement; cuts must add information. The selected duration is authoritative even when prose requests a longer scene.
Return only the final MiniMax fields (and required frame instruction), no preface, markdown fences, JSON wrapper, placeholders or explanations."""


def analysis_instruction(data, family):
    return PromptInstruction(system_message=GUARDRAILS + "\n\nFor this INTERNAL ANALYSIS step only, return one JSON object, not a final prompt. "
        'Schema: {"references": [{"token": "image1", "roles": ["identity"], "target": "the target person", '
        '"transfer": "only the requested characteristic", "exclude": "unrequested source characteristics"}], '
        '"first_frame": null, "last_frame": null}. Include every registered reference exactly once. '
        "Use token names without brackets for token and frame fields. Frame fields are a registered image token or null. "
        "Determine relationships from the request, including negations and multiple subjects. Do not guess media contents. "
        "For an unspecified reference role use style with weak guidance, not identity or a frame assumption. "
        "Only assign first/last frame roles to explicit concrete frame anchors; opening with a person is not anchoring an image. "
        "When a frame mode is explicitly selected it establishes those frame roles; use user-specified ordering, otherwise numeric image order. "
        "All additional identity/motion/style/audio roles require full reference mode in Auto. "
        "Assign audio roles to a VIDEO only when the user explicitly requests its audio track; dance rhythm is visual timing, not an enabled soundtrack. "
        "Visual roles: " + ", ".join(sorted(VISUAL_ROLES)) + ". Audio roles: " + ", ".join(sorted(AUDIO_ROLES)),
        user_message=json.dumps({key: data[key] for key in ("mode", "references", "user_request")}, ensure_ascii=False),
        model_family=family, diagnostic_stage="minimax:analysis", unlimited_tokens=True)


def validate_analysis(raw, data):
    try:
        plan = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("Reference analysis must be a JSON object without fences.") from exc
    if not isinstance(plan, dict) or set(plan) != {"references", "first_frame", "last_frame"} or not isinstance(plan["references"], list):
        raise ValueError("Reference analysis has missing fields.")
    by_token = {}
    for item in plan["references"]:
        if not isinstance(item, dict) or set(item) != {"token", "roles", "target", "transfer", "exclude"}:
            raise ValueError("Each reference needs token, roles, target, transfer and exclude.")
        token = reference_name(item["token"])
        roles = item["roles"]
        allowed = AUDIO_ROLES if token.startswith("audio") else VISUAL_ROLES | (AUDIO_ROLES if token.startswith("video") else set())
        if not isinstance(roles, list) or not roles or any(not isinstance(role, str) or role not in allowed for role in roles):
            raise ValueError("Reference analysis used an unsupported role.")
        if token in by_token or token not in data["references"]:
            raise ValueError("Reference analysis invented or duplicated a reference.")
        if any(not isinstance(item[key], str) or len(item[key]) > 4000 for key in ("target", "transfer", "exclude")):
            raise ValueError("Reference relationship descriptions must be text.")
        by_token[token] = {**item, "token": token}
    if set(by_token) != set(data["references"]):
        raise ValueError("Reference analysis omitted registered references.")
    for key, role in (("first_frame", "first frame"), ("last_frame", "last frame")):
        token = plan[key]
        if token is not None:
            token = reference_name(token)
            if token not in by_token or not token.startswith("image") or role not in by_token[token]["roles"]:
                raise ValueError("Frame anchors must identify an existing image with the corresponding frame role.")
            plan[key] = token
    plan["references"] = list(by_token.values())
    first, last = plan["first_frame"], plan["last_frame"]
    if first and first == last:
        # One asset serving both endpoints is a full-reference keyframe task.
        inferred = "Ref2VA"
    elif len(by_token) == 2 and first and last and all(set(item["roles"]) <= {"first frame", "last frame"} for item in by_token.values()):
        inferred = "FL2VA"
    elif len(by_token) == 1 and first and by_token[first]["roles"] == ["first frame"]:
        inferred = "I2VA"
    elif len(by_token) == 1 and last and by_token[last]["roles"] == ["last frame"]:
        inferred = "L2VA"
    else:
        inferred = "Ref2VA" if by_token else "T2VA"
    plan["mode"] = inferred if data["mode"] == "auto" else data["mode"]
    if (plan["mode"] in ("I2VA", "FL2VA") and not first) or (plan["mode"] in ("L2VA", "FL2VA") and not last):
        raise ValueError("The selected frame mode needs its corresponding frame anchors.")
    if plan["mode"] == "FL2VA" and first == last:
        raise ValueError("First and last frames must identify the two distinct images.")
    # Base frame numbering is positional; symbolic tokens themselves are never renumbered.
    if plan["mode"] in ("I2VA", "L2VA", "FL2VA"):
        order = [first, last] if plan["mode"] == "FL2VA" else [first or last]
        plan["label_map"] = {token: f"Picture {i + 1}" for i, token in enumerate(order)}
    else:
        plan["label_map"] = {token: re.sub(r"^(image|video|audio)", lambda m: {"image": "Picture ", "video": "Video ", "audio": "Audio "}[m[1]], token) for token in by_token}
    # An explicitly requested video soundtrack is an existing source track, not
    # an invented standalone file. Ordinary motion/camera videos create no audio.
    plan["video_audio_tracks"] = {}
    used_audio = {label for label in plan["label_map"].values() if label.startswith("Audio ")}
    for token, item in by_token.items():
        if token.startswith("video") and set(item["roles"]) & AUDIO_ROLES:
            label = next((f"Audio {n}" for n in range(1, 4) if f"Audio {n}" not in used_audio), None)
            if label is None:
                raise ValueError("At most three audio references, including explicitly enabled video soundtracks, can be described. Reduce the requested audio sources.")
            used_audio.add(label)
            plan["video_audio_tracks"][label] = token
    return plan


def frame_instruction(mode, duration, last_shot=1):
    if mode == "I2VA":
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if mode == "FL2VA":
        return f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot {last_shot}) aligns with the {duration:.2f}-second mark of the target video."
    if mode == "L2VA":
        return f"How the reference pictures align with the target video — <Picture 1> (from [Shot {last_shot}]) aligns with the {duration:.2f}-second mark of the target video."
    return ""


def generation_instruction(data, plan, director, family):
    mode = plan["mode"]
    context = {key: data[key] for key in ("model", "duration_seconds", "mode", "references")}
    context.update(resolved_mode=mode, reference_analysis=plan)
    return PromptInstruction(system_message="\n\n".join([
        knowledge("skill"), knowledge("base"), knowledge("reference") if mode == "Ref2VA" else "",
        GUARDRAILS,
        "SELECTED MODE: " + mode + ". Output sections in exact order: " + ", ".join(REF_SECTIONS if mode == "Ref2VA" else BASE_SECTIONS),
        "Use the supplied label_map only after interpreting roles. It maps provenance, NOT a blind text replacement. "
        "The video_audio_tracks map, when nonempty, enables ONLY explicitly requested audio from existing videos. "
        "Define each mapped Audio label as that video's synchronized track, with explicit provenance; it is not a new file. "
        "No other unregistered Audio label is permitted. Never enable a video's sound merely because it contains audio.",
    ]), user_message="\n\n".join([
        "STRUCTURED SETTINGS\n" + json.dumps(context, ensure_ascii=False),
        "DIRECTOR PRESET — CREATIVE GUIDANCE ONLY\n" + json.dumps({"name": director.label, "instructions": director.instructions}, ensure_ascii=False),
        "USER REQUEST\n" + data["user_request"],
        f"Write the complete {mode} prompt for exactly {data['duration_seconds']} seconds. Return only the final prompt.",
    ]), model_family=family, diagnostic_stage="minimax:prompt", unlimited_tokens=True)


def exact_dialogue(text):
    tagged = re.findall(r"<d>\[[^\]]+\]\s*(.*?)</d>", text, re.S)
    cue = r'\b(?:says?|say|speaks?|dialogue|lyrics|sings?|sing|voiceover|narrat(?:es?|ion)|shouts?|whispers?)\b'
    quoted = re.findall(cue + r'[^"“\n]{0,60}["“]([^"”]+)["”]', text, re.I)
    quoted += re.findall(cue + r"[^'‘\n]{0,60}['‘]([^'’]+)['’]", text, re.I)
    return tagged + quoted


def validate_output(raw, data, plan):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("MiniMax returned an empty prompt.")
    prompt = raw.strip()
    if "```" in prompt:
        raise ValueError("Remove markdown fences; return only the MiniMax prompt.")
    if TOKEN.search(prompt):
        # Validate the number before giving the role-translation error.
        parse_reference_tokens(prompt)
        raise ValueError("Translate symbolic references into role-aware official MiniMax labels.")
    if re.search(r"<[^>]*(?:\bN\b|placeholder|insert|TODO)[^>]*>|\[Shot N\]|\(Sx\)|S\.SS|\{\{.*?\}\}|\[(?:insert|TODO|placeholder)[^\]]*\]", prompt, re.I):
        raise ValueError("Resolve internal placeholders before returning the prompt.")
    sections = REF_SECTIONS if plan["mode"] == "Ref2VA" else BASE_SECTIONS
    headers = list(re.finditer(r"(?m)^([a-z_]+):", prompt))
    if [match[1] for match in headers] != list(sections):
        raise ValueError("Required MiniMax sections must occur exactly once in this order: " + ", ".join(sections))
    parts = {match[1]: prompt[match.end():headers[i + 1].start() if i + 1 < len(headers) else len(prompt)].strip() for i, match in enumerate(headers)}
    if any(not value for value in parts.values()):
        raise ValueError("MiniMax sections must not be empty.")
    timeline = parts["detailed_description" if plan["mode"] == "Ref2VA" else "integrated_multimodal_description"]
    shots = list(re.finditer(r"\[Shot (\d+)\]", timeline))
    if not shots or [int(shot[1]) for shot in shots] != list(range(1, len(shots) + 1)):
        raise ValueError("Timeline shots must start at [Shot 1] and be sequential without duplicates.")
    previous = 0
    for i, shot in enumerate(shots):
        after = timeline[shot.end():].lstrip()
        cut = re.match(r"At (\d{2}):([0-5]\d)\.(\d{3}),", after)
        if i == 0 and re.match(r"(?:At\s+)?\d{1,2}:\d{2}", after, re.I):
            raise ValueError("[Shot 1] must have no timestamp.")
        if i:
            if not cut:
                raise ValueError("Later shots must begin At MM:SS.mmm, using MiniMax timing.")
            seconds = int(cut[1]) * 60 + int(cut[2]) + int(cut[3]) / 1000
            if not previous < seconds < data["duration_seconds"]:
                raise ValueError("Shot cut times must increase strictly and leave time before the clip ends.")
            previous = seconds
    for stamp in re.finditer(r"\b(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\b", prompt):
        seconds = int(stamp[1]) * 60 + int(stamp[2]) + float("0." + (stamp[3] or "0"))
        if int(stamp[2]) >= 60 or seconds > data["duration_seconds"]:
            raise ValueError("A generated timestamp exceeds Clip Length or is malformed.")
    alignment = frame_instruction(plan["mode"], data["duration_seconds"], len(shots))
    if prompt[:headers[0].start()] != (alignment + "\n\n" if alignment else ""):
        raise ValueError("Use the exact frame-alignment instruction before the fields, or no preamble for T2VA/Ref2VA.")
    allowed = set(plan["label_map"].values()) | set(plan["video_audio_tracks"])
    for label in re.findall(r"<(?:Subject|Picture|Video|Audio)[^>]*>", prompt, re.I):
        if not re.fullmatch(r"<(?:Subject|Picture|Video|Audio) [1-9]\d*>", label):
            raise ValueError("Official reference labels require their exact spelling and positive numeric IDs.")
    for match in re.finditer(r"\b(Picture|Video|Audio)\s+(\d+)\b", prompt, re.I):
        label = f"{match[1].title()} {match[2]}"
        if label not in allowed:
            raise ValueError(f"{label} is not an existing reference in the supplied label map.")
    if plan["mode"] == "Ref2VA":
        definitions = set(re.findall(r"(?m)^<(Subject|Picture|Video|Audio) (\d+)>", parts["subject_definitions"]))
        subjects = set(re.findall(r"<Subject (\d+)>", prompt))
        if not subjects <= {number for kind, number in definitions if kind == "Subject"}:
            raise ValueError("Every Subject must be defined before use.")
        if not definitions:
            raise ValueError("Full Reference needs role-aware reference definitions.")
        for kind, number in definitions:
            markers = "fully_copy|partially_copy|reference|weak_reference" if kind == "Audio" else "fully_preserved|partially_preserved|attribute_transfer|weak_reference"
            if not re.search(rf"(?m)^<{kind} {number}>[^\n]*:\s*(?:{markers})\s*-", parts["retention_analysis"]):
                raise ValueError(f"Missing or invalid retention marker for {kind} {number}.")
        tasks = re.match(r"\[([^\]]+)\]", parts["summary"])
        if not tasks or any(task not in {"reference generation", "keyframe completion", "video editing", "video continuation", "audio reuse", "audio reference"} for task in tasks[1].split(" + ")):
            raise ValueError("Summary must begin with applicable official task relationship markers.")
        if re.search(r"\(S\d", parts["retention_analysis"]):
            raise ValueError("Speaker IDs do not belong in retention_analysis.")
    blocks = re.findall(r"<d>\[([^\]\n]+)\]\s*(.*?)</d>", timeline, re.S)
    if len(blocks) != prompt.count("<d>") or len(blocks) != prompt.count("</d>") or any(not text.strip() for _, text in blocks):
        raise ValueError("Dialogue must use balanced <d>[Language] exact words</d> blocks only in the timeline.")
    spoken = " ".join(re.sub(r"<(?:scenetrans|cutoff)>", "", text).strip() for _, text in blocks)
    for original in exact_dialogue(data["user_request"]):
        if original not in spoken:
            raise ValueError("Preserve the exact supplied dialogue/lyrics and original language inside <d>.")
    for language, original in re.findall(r"<d>\[([^\]]+)\]\s*(.*?)</d>", data["user_request"], re.S):
        if (language, original) not in blocks:
            raise ValueError("Preserve user-supplied dialogue language tags and text verbatim.")
    if blocks and not re.search(r"\(S\d+(?:,S\d+)*\)|<Audio \d+>", timeline):
        raise ValueError("Spoken dialogue needs stable speaker IDs (or a directly reused Audio cue).")
    for match in re.finditer(r"says in an off-screen voiceover[^<]*<d>.*?</d>([^.]*\.)?", timeline, re.S):
        if not re.search(r"lips.*closed", match[1] or "", re.I):
            raise ValueError("State that lips remain closed immediately after every voiceover block.")
    return prompt


class MiniMaxService:
    def __init__(self, config, checkpoint):
        self.config, self.checkpoint = config, checkpoint

    def _call(self, session, instruction, validator, progress):
        for attempt in range(2):
            self.checkpoint()
            session.validate_instruction(instruction)
            raw = session.generate(instruction)
            self.checkpoint()
            try:
                return validator(raw)
            except ValueError as exc:
                if attempt:
                    raise BackendGenerationError(f"MiniMax prompt validation failed after one repair attempt: {exc}") from exc
                progress("Correcting MiniMax formatting (one retry)")
                instruction = replace(instruction, user_message=instruction.user_message +
                    "\n\nVALIDATION CORRECTION: " + str(exc) + "\nRegenerate the complete response from the original request. Do not explain the correction.",
                    diagnostic_stage=instruction.diagnostic_stage + ":repair")

    def run(self, request, data, progress):
        data = validate_minimax_draft(data, generation=True)
        director = get_director_preset(data["director_preset"], strict=True)
        effective, profile = resolve_director_config(self.config, request)
        backend = create_backend(effective)
        family = _effective_model_family(request, profile, effective)
        with backend.generation_session() as session:
            if data["references"]:
                progress("Understanding reference roles")
                plan = self._call(session, analysis_instruction(data, family), lambda raw: validate_analysis(raw, data), progress)
            else:
                plan = validate_analysis('{"references": [], "first_frame": null, "last_frame": null}', data)
            progress("Writing MiniMax H3 prompt")
            prompt = self._call(session, generation_instruction(data, plan, director, family), lambda raw: validate_output(raw, data, plan), progress)
        return {"ok": True, "kind": "minimax", "prompt": prompt, "mode": plan["mode"],
                "warnings": reference_warnings(data), "backend": backend.name}
