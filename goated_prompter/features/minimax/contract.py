"""MiniMax H3 input and output contracts.

Draft validation, symbolic reference and shot parsing, reference-role analysis
validation, and final-output normalization/validation. Prompt text sent to the
model lives in ``prompting.minimax``.
"""

import json
import re

from ...minimax_format import BASE_SECTIONS, REF_SECTIONS, normalize_h3_sections
from ...presets import get_director_preset

MODELS = ("MiniMax H3",)
MODES = ("auto", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA")
RATIOS = ("Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
LIMITS = {"image": 9, "video": 3, "audio": 3}
TOKEN = re.compile(r"<(image|video|audio)(\d+)>", re.I)
SHOT_TAG = re.compile(r"\[Shot\s*(\d+)\]", re.I)
SHOT_INPUT = re.compile(r"<shot(\d+)>", re.I)
SHOT_RANGE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3})?)\s*[-–—]\s*(\d{1,2}(?:\.\d{1,3})?)\s*s\b", re.I)
VISUAL_ROLES = {"identity", "appearance", "character", "object", "product", "environment", "style", "first frame",
                "last frame", "keyframe", "storyboard", "motion", "dance", "pose", "expression", "camera movement",
                "editing source", "video continuation", "cut structure", "timing", "pacing"}
AUDIO_ROLES = {"direct audio reuse", "background music reuse", "music style", "rhythm", "beat", "voice timbre",
               "voice delivery", "dialogue content", "lyrics", "sound effect texture", "audio continuity"}


def default_minimax_draft():
    return {"model": MODELS[0], "duration_seconds": 10, "mode": "auto", "aspect_ratio": "Auto",
            "planning_mode": "Auto",
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


def parse_shot_outline(text, duration):
    """Resolve optional user shot markers to contiguous millisecond boundaries."""
    if any(not SHOT_INPUT.fullmatch(match[0]) for match in re.finditer(r"<shot[^>]*>", text, re.I)):
        raise ValueError("Shot shortcuts use <shot1>, <shot2>, and so on.")
    matches = list(SHOT_INPUT.finditer(text))
    if not matches:
        return []
    if [match[1] for match in matches] != [str(i) for i in range(1, len(matches) + 1)]:
        raise ValueError("Shot shortcuts must appear once each in order: <shot1>, <shot2>, and so on.")
    boundaries = [None] * (len(matches) + 1)
    boundaries[0], boundaries[-1] = 0, duration * 1000
    descriptions = []

    def set_boundary(index, millis):
        if boundaries[index] is not None and boundaries[index] != millis:
            raise ValueError("Shot time ranges must meet without gaps or overlaps and match Clip Length.")
        boundaries[index] = millis

    for i, match in enumerate(matches):
        content = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        timing = SHOT_RANGE.match(content)
        if timing:
            for boundary, value in ((i, timing[1]), (i + 1, timing[2])):
                whole, _, fraction = value.partition(".")
                set_boundary(boundary, int(whole) * 1000 + int(fraction.ljust(3, "0") or "0"))
            content = content[timing.end():].lstrip(" ,:-\n\t")
        elif re.match(r"^\s*\d+(?:\.\d+)?\s*[-–—]\s*\d+", content):
            raise ValueError(f"Use a shot time range like <shot{i + 1}> 0-3s (seconds, up to three decimals).")
        if not content:
            raise ValueError(f"Describe the action in <shot{i + 1}> before generating.")
        descriptions.append(content)
    known = [i for i, value in enumerate(boundaries) if value is not None]
    for left, right in zip(known, known[1:]):
        start, end = boundaries[left], boundaries[right]
        if end - start < right - left:
            raise ValueError("Every shot needs time within Clip Length; adjust the shot ranges or clip length.")
        for i in range(left + 1, right):
            boundaries[i] = start + (end - start) * (i - left) // (right - left)
    return [{"number": i + 1, "start_ms": boundaries[i], "end_ms": boundaries[i + 1], "description": description}
            for i, description in enumerate(descriptions)]


def validate_minimax_draft(value, *, generation=False):
    defaults = default_minimax_draft()
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise ValueError("Invalid MiniMax settings fields.")
    result = {**defaults, **value}
    from ...planning import PLANNING_MODES
    for key, choices in (("model", MODELS), ("mode", MODES), ("aspect_ratio", RATIOS), ("planning_mode", PLANNING_MODES)):
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
        result["references"] = [ref for ref in result["references"] if ref in used]
        result["user_request"] = TOKEN.sub(lambda m: f"<{reference_name(m[0])}>", result["user_request"])
        parse_shot_outline(result["user_request"], result["duration_seconds"])
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
                if data["mode"] in ("auto", "Ref2VA"):
                    token = None
                else:
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


def reference_scaffold(plan):
    """Render provenance and retention from validated roles, without inspecting media."""
    definitions, retention = [], []
    subject_number = 0
    for item in plan["references"]:
        token, roles = item["token"], set(item["roles"])
        source = plan["label_map"][token]
        if token.startswith("audio"):
            label, marker = source, "partially_copy" if roles & {"direct audio reuse", "background music reuse"} else "reference"
            definitions.append(f"<{label}> is the supplied audio reference, used only for the requested {', '.join(item['roles'])}.")
        elif token.startswith("video") and roles & {"editing source", "video continuation", "camera movement", "cut structure", "pacing"}:
            label, marker = source, "partially_preserved" if roles & {"editing source", "video continuation"} else "weak_reference"
            definitions.append(f"<{label}> is the supplied video reference, used only for the requested {', '.join(item['roles'])}.")
        elif token.startswith("image") and roles <= {"first frame", "last frame", "keyframe", "storyboard"}:
            label, marker = source, "fully_preserved"
            definitions.append(f"<{label}> is the supplied frame reference, used only for the requested {', '.join(item['roles'])}.")
        else:
            subject_number += 1
            label = f"Subject {subject_number}"
            marker = "fully_preserved" if roles & {"identity", "appearance", "character", "object", "product", "environment"} else "weak_reference"
            definitions.append(f"<{label}> is the requested {', '.join(item['roles'])} subject from <{source}>; follow only the role described by the user.")
        retention.append(f"<{label}>: {marker} - retain only the requested {', '.join(item['roles'])} characteristics from <{source}>.")
    for label, token in plan["video_audio_tracks"].items():
        source = plan["label_map"][token]
        definitions.append(f"<{label}> is the explicitly requested synchronized soundtrack from <{source}>.")
        retention.append(f"<{label}>: partially_copy - reuse only the requested portions of the soundtrack from <{source}>.")
    return "\n".join(definitions), "\n".join(retention)


def requested_spoken_lines(text):
    """Extract explicitly spoken, untagged lines from natural-language requests."""
    lines = []
    cue = r"(?:says?|said|speaks?|whispers?|shouts?|sings?)"
    for line in text.splitlines():
        if re.match(r"\s*<shot\d+>", line, re.I):
            line = re.sub(r"^\s*<shot\d+>\s*", "", line, count=1, flags=re.I)
            line = SHOT_RANGE.sub("", line, count=1)
        match = re.match(rf"\s*(?P<speaker>[^:\n<>]{{1,80}}?)\s+{cue}\s*:\s*(?P<words>.+?)\s*$", line, re.I)
        if not match:
            match = re.match(rf'''\s*(?P<speaker>[^:\n<>]{{1,80}}?)\s+{cue}\s+(?:["“](?P<words>.+?)["”]|['‘](?P<single>.+?)['’])\s*$''', line, re.I)
        if not match:
            continue
        words = (match["words"] or match.groupdict().get("single") or "").strip().strip('"“”‘’')
        if "<d>" in words:
            continue
        if words:
            lines.append({"speaker": match["speaker"].strip(), "words": words})
    return lines


def exact_dialogue(text):
    tagged = re.findall(r"<d>\[[^\]]+\]\s*(.*?)</d>", text, re.S)
    cue = r'\b(?:says?|say|speaks?|dialogue|lyrics|sings?|sing|voiceover|narrat(?:es?|ion)|shouts?|whispers?)\b'
    quoted = re.findall(cue + r'[^"“\n]{0,60}["“]([^"”]+)["”]', text, re.I)
    quoted += re.findall(cue + r"[^'‘\n]{0,60}['‘]([^'’]+)['’]", text, re.I)
    return tagged + quoted + [line["words"] for line in requested_spoken_lines(text)]


def normalize_spoken_lines(parts, data, plan):
    """Repair model dialogue formatting using words explicitly supplied by the user."""
    lines = requested_spoken_lines(data["user_request"])
    if not lines or "<d>" in data["user_request"]:
        return False
    key = "detailed_description" if plan["mode"] == "Ref2VA" else "integrated_multimodal_description"
    timeline = parts[key]
    blocks = list(re.finditer(r"<d>\[([^\]\n]+)\]\s*(.*?)</d>", timeline, re.S))
    if len(blocks) == len(lines) and timeline.count("<d>") == len(blocks) and timeline.count("</d>") == len(blocks):
        for block, line in reversed(list(zip(blocks, lines))):
            language = "English" if block[1].casefold() in {"language", "unknown"} else block[1]
            if block[2] != line["words"] or language != block[1]:
                timeline = timeline[:block.start()] + f"<d>[{language}] {line['words']}</d>" + timeline[block.end():]
    else:
        # A malformed or absent model block is recoverable when the user supplied
        # the actual words; keep the visual action and put dialogue at its cue.
        timeline = re.sub(r"<d>(?:\[[^\]\n]+\]\s*)?|</d>", "", timeline)
        search_from = 0
        for line in lines:
            block = f"<d>[English] {line['words']}</d>"
            cue = re.search(r"\b(?:says?|said|speaks?|whispers?|shouts?|sings?)\b\s*:?\s*", timeline[search_from:], re.I)
            if cue:
                cue_start, cue_end = search_from + cue.start(), search_from + cue.end()
                tail = timeline[cue_end:]
                quoted = re.match(r'''["“'‘][^"”'’\n]*["”'’]''', tail)
                words = re.search(re.escape(line["words"]), tail[:200], re.I)
                if quoted:
                    start, end = cue_end, cue_end + quoted.end()
                elif words:
                    start, end = cue_end + words.start(), cue_end + words.end()
                else:
                    phrase = re.match(r"[^.!?\n]+[.!?]?", tail)
                    start, end = cue_end, cue_end + phrase.end() if phrase else cue_end
                timeline = timeline[:start] + block + timeline[end:]
                search_from = start + len(block)
            else:
                speech = f"{line['speaker']} says: {block}. "
                crying = re.search(r"\b(?:crying|cry|cries)\b", timeline[search_from:], re.I)
                boundary = timeline.rfind(".", 0, search_from + crying.start()) + 1 if crying else len(timeline)
                timeline = timeline[:boundary].rstrip() + " " + speech + timeline[boundary:].lstrip()
                search_from = boundary + len(speech)
    speaker_ids = {speaker: i + 1 for i, speaker in enumerate(dict.fromkeys(line["speaker"].casefold() for line in lines))}
    for block, line in reversed(list(zip(re.finditer(r"<d>\[[^\]\n]+\]\s*.*?</d>", timeline, re.S), lines))):
        before = timeline[max(0, block.start() - 100):block.start()]
        cues = list(re.finditer(r"\b(?:says?|said|speaks?|whispers?|shouts?|sings?)\b", before, re.I))
        if cues and len(before) - cues[-1].end() < 80:
            cue_start = block.start() - len(before) + cues[-1].start()
            if not re.search(r"\(S\d+\)", timeline[max(0, cue_start - 16):cue_start]):
                timeline = timeline[:cue_start] + f"(S{speaker_ids[line['speaker'].casefold()]}) " + timeline[cue_start:]
        else:
            timeline = timeline[:block.start()] + f"{line['speaker']} (S{speaker_ids[line['speaker'].casefold()]}) says: " + timeline[block.start():]
    timeline = re.sub(r"\b(says?|said|speaks?|whispers?|shouts?|sings?)\s+:\s*(?=<d>)", r"\1: ", timeline, flags=re.I)
    parts[key] = timeline
    for section in parts:
        if section != key and ("<d>" in parts[section] or "</d>" in parts[section]):
            parts[section] = re.sub(r"<d>.*?</d>|<d>(?:\[[^\]\n]+\]\s*)?[^\n]*|</d>",
                                    "the requested dialogue", parts[section], flags=re.S)
    return True


def shot_headings(timeline):
    """Find actual timeline shot starts, not incidental references to a shot."""
    headings = []
    for match in SHOT_TAG.finditer(timeline):
        prefix = timeline[timeline.rfind("\n", 0, match.start()) + 1:match.start()]
        timed_cut = re.match(r"\s*(?:At\s+)?\d{1,2}:\d{2}", timeline[match.end():], re.I)
        if not prefix.strip() or timeline[:match.start()].rstrip().endswith((".", "!", "?", ";", ":")) or timed_cut:
            headings.append(match)
    return headings


def normalize_shots(timeline, data, plan):
    """Format model shot headings without fabricating cuts or cut times."""
    outline = parse_shot_outline(data["user_request"], data["duration_seconds"])
    timeline = re.sub(r"(?im)^[ \t]*(?:[-*][ \t]*)?Shot\s*(\d+)[ \t]*[:.)\-–—][ \t]*",
                      lambda match: f"[Shot {int(match[1])}] ", timeline)
    timeline = re.sub(r"(?im)^[ \t]*[-*][ \t]*(?=\[Shot\s*\d+\])", "", timeline)
    headings = shot_headings(timeline)
    if outline:
        return normalize_outlined_shots(timeline, headings, outline, plan, data["user_request"])
    if not headings:
        style = re.match(r"((?:The target video|This video|The clip)[^.!?\n]*[.!?])\s*", timeline, re.I)
        if style:
            return timeline[:style.end(1)] + "\n[Shot 1] " + timeline[style.end():].lstrip()
        return "[Shot 1] " + timeline
    output, previous, shot_number = timeline[:headings[0].start()], 0, 1
    collapse = plan["mode"] in ("Ref2VA", "T2VA") and not re.search(r"\b(?:shots?|cuts?)\s*\d+|\bcut\s+to\b", data["user_request"], re.I)
    for i, heading in enumerate(headings):
        after = timeline[heading.end():headings[i + 1].start() if i + 1 < len(headings) else len(timeline)]
        stamp = re.match(r"\s*(?:At\s+)?(\d{1,2}):([0-5]\d)(?:\.(\d{1,3}))?\s*[,;:\-]?\s*", after, re.I)
        if i == 0:
            if stamp:
                after = " " + after[stamp.end():]
            output += "[Shot 1]" + after
        elif stamp:
            millis = int(stamp[3] or "0") * 10 ** (3 - len(stamp[3] or ""))
            seconds = int(stamp[1]) * 60 + int(stamp[2]) + millis / 1000
            if previous < seconds < data["duration_seconds"]:
                previous = seconds
                shot_number += 1
                output += f"[Shot {shot_number}] At {int(stamp[1]):02d}:{int(stamp[2]):02d}.{millis:03d}, " + after[stamp.end():]
            else:
                shot_number += 1
                output += f"[Shot {shot_number}]" + after
        elif collapse and not re.match(r"\s*(?:At\b|\d{1,2}:\d{2})", after, re.I):
            output += after
        else:
            shot_number += 1
            output += f"[Shot {shot_number}]" + after
    return output


def normalize_outlined_shots(timeline, headings, outline, plan, request):
    """Make user-authored shot boundaries authoritative, retaining model prose when usable."""
    scene = timeline[:headings[0].start()].strip() if headings else ""
    if not scene:
        style = re.match(r"((?:The target video|This video|The clip)[^.!?\n]*[.!?])\s*", timeline, re.I)
        if style:
            scene = style[1]
    if not scene:
        introduction = request[:SHOT_INPUT.search(request).start()]
        style = next((line.strip().rstrip(".") for line in introduction.splitlines()
                      if line.strip() and not TOKEN.search(line)), "the requested visual style and reference roles")
        scene = f"The target video follows {style}."
    bodies = []
    if len(headings) == len(outline):
        for i, heading in enumerate(headings):
            body = timeline[heading.end():headings[i + 1].start() if i + 1 < len(headings) else len(timeline)]
            body = re.sub(r"^\s*(?:At\s+)?\d{1,2}:\d{2}(?:\.\d{1,3})?\s*[,;:\-]?\s*", "", body, count=1, flags=re.I).strip()
            body = SHOT_RANGE.sub("", body, count=1).strip()
            bodies.append(body)
        numbers = [int(heading[1]) for heading in headings]
        if set(numbers) == set(range(1, len(outline) + 1)) and len(set(numbers)) == len(outline):
            bodies = [bodies[numbers.index(i)] for i in range(1, len(outline) + 1)]
    if len(bodies) != len(outline) or any(not body for body in bodies):
        bodies = [shot["description"] for shot in outline]
        for token, label in plan["label_map"].items():
            bodies = [re.sub(re.escape(f"<{token}>"), f"<{label}>", body, flags=re.I) for body in bodies]
    sections = [scene] if plan["mode"] == "Ref2VA" else []
    for i, (shot, body) in enumerate(zip(outline, bodies)):
        start = shot["start_ms"]
        heading = "[Shot 1]" if i == 0 else f"[Shot {i + 1}] At {start // 60000:02d}:{start // 1000 % 60:02d}.{start % 1000:03d},"
        sections.append(f"{heading} {scene} {body}" if i == 0 and plan["mode"] != "Ref2VA" else f"{heading} {body}")
    return "\n".join(sections)


def validate_output(raw, data, plan):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("MiniMax returned an empty prompt.")
    prompt = normalize_h3_sections(raw, reference=plan["mode"] == "Ref2VA")
    allowed = set(plan["label_map"].values()) | set(plan["video_audio_tracks"])
    prompt = re.sub(r"<(subject|picture|video|audio) ([1-9]\d*)>",
                    lambda match: f"<{match[1].title()} {match[2]}>", prompt, flags=re.I)
    if re.search(r"<shot[^>]*>", prompt, re.I) and not SHOT_INPUT.search(prompt):
        raise ValueError("Remove unresolved symbolic shot tokens from the MiniMax output.")
    prompt = SHOT_INPUT.sub(lambda match: f"[Shot {int(match[1])}]", prompt)
    prompt = re.sub(r"(\[Shot 1\])\s+(?:At\s+)?\d{1,2}:\d{2}(?:\.\d{1,3})?\s*[,\-:;]?\s*", r"\1 ", prompt)
    prompt = re.sub(r"(?<!<)\bVideo\s+([1-9]\d*)\b(?!>)",
                    lambda match: match[0] if f"Video {match[1]}" in allowed else "target video", prompt, flags=re.I)
    prompt = re.sub(r"(?<!<)\bAudio\s+([1-9]\d*)\b(?!>)",
                    lambda match: match[0] if f"Audio {match[1]}" in allowed else "generated audio", prompt, flags=re.I)
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
    if plan["mode"] == "Ref2VA" and not re.search(r"(?m)^<(?:Subject|Picture|Video|Audio) [1-9]\d*>", parts["subject_definitions"]):
        # The scene writer sometimes returns descriptive prose here instead of
        # official definitions. Provenance is known from the validated plan.
        if not any(f"{kind} {number}" not in allowed for kind, number in
                   re.findall(r"<(Picture|Video|Audio) (\d+)>", parts["subject_definitions"])):
            definitions, retention = reference_scaffold(plan)
            parts["subject_definitions"] = definitions
            parts["retention_analysis"] = retention
            prompt = prompt[:headers[0].start()] + "\n\n".join(f"{section}:\n{parts[section]}" for section in sections)
    timeline_key = "detailed_description" if plan["mode"] == "Ref2VA" else "integrated_multimodal_description"
    timeline = parts[timeline_key]
    normalized_timeline = normalize_shots(timeline, data, plan)
    if normalized_timeline != timeline:
        parts[timeline_key] = timeline = normalized_timeline
        prompt = prompt[:headers[0].start()] + "\n\n".join(f"{section}:\n{parts[section]}" for section in sections)
    if normalize_spoken_lines(parts, data, plan):
        timeline = parts[timeline_key]
        prompt = prompt[:headers[0].start()] + "\n\n".join(f"{section}:\n{parts[section]}" for section in sections)
    validate_temporal_endpoints(timeline, data)
    shots = shot_headings(timeline)
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
    if parse_shot_outline(data["user_request"], data["duration_seconds"]) and alignment:
        prompt = alignment + "\n\n" + prompt[headers[0].start():]
    first_header = re.search(r"(?m)^[a-z_]+:", prompt)
    if prompt[:first_header.start()] != (alignment + "\n\n" if alignment else ""):
        raise ValueError("Use the exact frame-alignment instruction before the fields, or no preamble for T2VA/Ref2VA.")
    for label in re.findall(r"<(?:Subject|Picture|Video|Audio)[^>]*>", prompt, re.I):
        if not re.fullmatch(r"<(?:Subject|Picture|Video|Audio) [1-9]\d*>", label):
            raise ValueError("Official reference labels require their exact spelling and positive numeric IDs.")
    for match in re.finditer(r"\b(Picture|Video|Audio)\s+(\d+)\b", prompt, re.I):
        label = f"{match[1].title()} {match[2]}"
        if label not in allowed:
            raise ValueError(f"{label} was introduced without a supplied reference. Do not create forced Picture, Video or Audio labels.")
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
    from ...planning.constraints import compile_request
    from ...planning.constraint_validation import output_constraint_issues
    compiled = compile_request(data["user_request"], has_context=bool(plan["references"]))
    problems = [issue for issue in output_constraint_issues(prompt, "MiniMax H3", compiled.workflow_data())
                if issue["severity"] == "error"]
    if problems:
        raise ValueError(problems[0]["message"])
    return prompt


def validate_temporal_endpoints(timeline, data):
    """Require user-authored temporal boundaries; never fabricate missing events."""
    request = data["user_request"]
    from ...planning.rule_compiler import QUOTED
    request = QUOTED.sub("[protected literal]", re.sub(r"<d>.*?</d>", "[protected dialogue]", request, flags=re.S))
    explicit = []
    markers = list(SHOT_INPUT.finditer(request))
    for i, marker in enumerate(markers):
        content = request[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(request)]
        if timing := SHOT_RANGE.match(content):
            explicit.extend(float(timing[j]) for j in (1, 2) if float(timing[j]) != 0)
    explicit.extend(float(match[1]) for match in re.finditer(r"\bat\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)\b", request, re.I))
    present = [int(match[1]) * 60 + int(match[2]) + float("0." + (match[3] or "0"))
               for match in re.finditer(r"\b(\d{1,2}):([0-5]\d)(?:\.(\d{1,3}))?\b", timeline)]
    present.extend(float(match[1]) for match in re.finditer(r"\b(?:at|by|until|through|ends?\s+at)\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)\b", timeline, re.I))
    missing = sorted({seconds for seconds in explicit if not any(abs(seconds - actual) < .0005 for actual in present)})
    if missing:
        raise ValueError("Temporal endpoint completeness: explicitly describe the required state/event at "
                         + ", ".join(f"{seconds:g} seconds" for seconds in missing) + ". Preserve existing shots, support/contact states and exact dialogue.")
