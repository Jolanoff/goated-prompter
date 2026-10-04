"""Bounded schema and high-confidence integrity checks, not a geometry engine."""

import json
import re


SCENE_STRINGS = {"intent", "primary_action", "environment", "staging", "pose_detail"}
SCENE_LISTS = {"subjects", "interactions", "important_visibility", "required", "forbidden", "variable", "uncertainties"}
VIDEO_STRINGS = {"core_intent"}
VIDEO_LISTS = {"subjects", "action_progression", "interactions", "continuity", "camera_intent", "audio_intent", "reference_constraints", "protected_dialogue", "required", "forbidden", "variable", "uncertainties"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Planning returned duplicate JSON fields.")
        result[key] = value
    return result


def _silent_exclusions(value, compiled):
    # Catch only verbatim leak forms for safely parsed facts. This is not a
    # synonym/absence-state detector or an automatic semantic pose reviewer.
    # A standalone absence note contributes no positive staging information and
    # exactly duplicates the compiler's restriction. Drop that redundancy only;
    # mixed positive/negative prose is rejected rather than heuristically edited.
    for key in ("important_visibility", "interactions", "continuity", "camera_intent", "audio_intent", "uncertainties"):
        if key not in value:
            continue
        retained = []
        for text in value[key]:
            literal_content = any(literal in text or literal[1:-1] in text
                                  for literal in compiled.protected_literals if len(literal) > 2)
            standalone = not literal_content and any(re.fullmatch(r"(?:no|without)\s+(?:(?:a|an|the|any)\s+)?" + re.escape(fact)
                + r"(?:\s+(?:is|are)\s+(?:present|visible|worn)(?:\s+(?:on|in)\s+(?:the|a|an)\s+\w+)?)?[.!]?",
                text.strip(), re.I) for fact in compiled.forbidden)
            if not standalone:
                retained.append(text)
        value[key] = retained
    def texts(item):
        if isinstance(item, str):
            yield item
        elif isinstance(item, list):
            for part in item:
                yield from texts(part)
        elif isinstance(item, dict):
            for key, part in item.items():
                if key not in {"required", "forbidden", "variable", "protected_dialogue"}:
                    yield from texts(part)
    for text in texts(value):
        for literal in compiled.protected_literals:
            text = text.replace(literal, "")
            if literal.startswith(('"', "“", "'")):
                text = text.replace(literal[1:-1], "")
        for fact in compiled.forbidden:
            phrase = re.escape(fact)
            if re.search(r"\b(?:no|without)\s+(?:(?:a|an|the|any)\s+)?" + phrase + r"\b|\b" + phrase + r"[- ]free\b", text, re.I):
                raise ValueError("Planning verbalized a safely compiled exclusion.")


def _symbolic_provenance(value, compiled):
    # Only a clear claim of observation with a symbolic token is provable here.
    # Indirect appearance inference remains a semantic limitation, not a regex map.
    text = json.dumps({key: item for key, item in value.items() if key != "protected_dialogue"}, ensure_ascii=False)
    for literal in compiled.protected_literals:
        text = text.replace(json.dumps(literal, ensure_ascii=False)[1:-1], "")
        if literal.startswith(('"', "“", "'")):
            text = text.replace(json.dumps(literal[1:-1], ensure_ascii=False)[1:-1], "")
    if re.search(r"\b(?:observed|seen|shown)\s+in\s+<(?:image|video|audio)\d+>", text, re.I):
        raise ValueError("Video planning claimed observation of unseen symbolic media.")


def _axis_compatibility(value, compiled):
    # A narrow world-axis contradiction, not a pose taxonomy. It is only applied
    # within a single clause; independent limbs or different timeline states are
    # not inferred to conflict. Other mechanics remain semantic uncertainties.
    for key, item in value.items():
        if key not in {"pose_detail", "interactions", "staging", "action_progression"}:
            continue
        for text in ([item] if isinstance(item, str) else item):
            for literal in compiled.protected_literals:
                text = text.replace(literal, "")
                if literal.startswith(('"', "“", "'")):
                    text = text.replace(literal[1:-1], "")
            for clause in re.split(r"[.;\n]|\b(?:while|then|but)\b", text, flags=re.I):
                entities = re.findall(r"\b(?:arms?|legs?|limbs?|torso|spine|body|feet|foot|hands?|head)\b", clause, re.I)
                if len(entities) != 1 or re.search(r"\b(?:from|becomes?|turns?|moves?|transitions?|rotates?)\b", clause, re.I):
                    continue
                vertical = re.search(r"\b(?:vertically|straight\s+(?:up|down)|vertically\s+(?:upward|downward))\b", clause, re.I)
                level = re.search(r"\bparallel\s+to\s+(?:the\s+)?(?:ground|floor)\b", clause, re.I)
                if vertical and level and not re.search(r"\b(?:camera|frame|screen|appears?|looks?|other|opposite|or|may|might|could|if|depending)\b", clause, re.I):
                    raise ValueError("Planning contradicts vertical and ground-parallel orientation in one clause.")


def validate_plan(raw, compiled, *, video=False, reference_analysis=None, shots=(), dialogue=()):
    if not isinstance(raw, str) or len(raw) > 7000:
        raise ValueError("Planning response must be a compact JSON object.")
    value = json.loads(raw, object_pairs_hook=_unique)
    strings, lists = (VIDEO_STRINGS, VIDEO_LISTS) if video else (SCENE_STRINGS, SCENE_LISTS)
    allowed = strings | lists | ({"shot_details"} if video else set())
    if not isinstance(value, dict) or not value or value.keys() - allowed:
        raise ValueError("Planning response contains unsupported fields.")
    for key, item in value.items():
        # A lone concise detail has the same semantics as a singleton array.
        # Normalize that harmless schema variance; never coerce objects/numbers.
        if key in lists and isinstance(item, str):
            item = value[key] = [item]
        if key in strings and (not isinstance(item, str) or len(item) > 900):
            raise ValueError(f"Planning {key} must be concise text.")
        if key in lists and (not isinstance(item, list) or len(item) > 12 or any(not isinstance(part, str) or not part.strip() or len(part) > 500 for part in item)):
            raise ValueError(f"Planning {key} must be a short list of text details.")
    if video:
        if not value.get("action_progression"):
            raise ValueError("Video planning must resolve action progression.")
        details = value.get("shot_details", [])
        if shots:
            if not isinstance(details, list) or len(details) != len(shots):
                raise ValueError("Video planning must preserve all supplied shots.")
            for detail, shot in zip(details, shots):
                if (not isinstance(detail, dict) or set(detail) != {"number", "start_ms", "end_ms", "action"}
                        or any(type(detail[key]) is not int or detail[key] != shot[key] for key in ("number", "start_ms", "end_ms"))
                        or not isinstance(detail["action"], str) or not detail["action"].strip() or len(detail["action"]) > 700):
                    raise ValueError("Video planning changed shot order/timing or returned invalid shot details.")
        elif details:
            raise ValueError("Video planning invented shots for a continuous request.")
        if "protected_dialogue" in value and value["protected_dialogue"] != list(dialogue):
            raise ValueError("Video planning altered protected dialogue.")
        value["protected_dialogue"] = list(dialogue)
        if reference_analysis is not None:
            _symbolic_provenance(value, compiled)
            text = json.dumps(value, ensure_ascii=False)
            references = {token.casefold() for token in re.findall(r"<(?:image|video|audio)\d+>", text, re.I)}
            registered = {("<" + item["token"] + ">").casefold() for item in reference_analysis["references"]}
            if references - registered:
                raise ValueError("Video planning invented symbolic references.")
            # Source roles are supplied deterministically, never accepted from an
            # alternate model analysis or recast as observed media descriptions.
            value["reference_constraints"] = ["<" + item["token"] + ">: " + ", ".join(item["roles"])
                                               for item in reference_analysis["references"]]
    elif not any(value.get(key, "").strip() for key in ("primary_action", "staging", "pose_detail")):
        raise ValueError("Scene planning must resolve action or physical staging.")
    _silent_exclusions(value, compiled)
    _axis_compatibility(value, compiled)
    # The model cannot change the source intent, parsed exclusions or variation.
    for key in ("required", "forbidden", "variable"):
        supplied = list(getattr(compiled, key))
        if key in value and value[key] != supplied:
            raise ValueError(f"Planning changed compiled {key} facts.")
        value[key] = supplied
    # The writer already receives the source request. Do not repeat it or let a
    # model's alternate intent become a second competing prompt.
    value.pop("core_intent" if video else "intent", None)
    count = re.match(r"\s*(two|three|2|3)\s+(?:people|persons|subjects|characters)\b", compiled.positive_request, re.I)
    if count and value.get("subjects") and len(value["subjects"]) != {"two": 2, "three": 3, "2": 2, "3": 3}[count[1].lower()]:
        raise ValueError("Planning changed the explicit subject count.")
    return value
