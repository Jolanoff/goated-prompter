"""Local quality checks for Dataset batches."""

from collections import Counter
import hashlib
import json
import re

from .dataset_assignments import dataset_assignments
from .workflow_output import WorkflowFormatError, normalize_workflow_output
from .dataset_triggers import trigger_contract_error, trigger_presence_error, trigger_terms, trigger_text_target
from .dataset_visible_content import visible_content_error, positive_prompt_error


LEAKED_LABELS = re.compile(
    r"(?im)^\s*(?:ITEM|TRIGGER TYPE|TRIGGER DESCRIPTION|REQUIRED TRIGGER TEXT|DATASET CONCEPT|"
    r"SOURCE MODE|GUIDED INPUT|ADDITIONAL CONSISTENCY RULES|CONSISTENCY AND VARIATION RULES|"
    r"EARLIER ITEM|OUTPUT FORMAT|CURRENT SCENE|PLANNED IDEA|PLANNED GEOMETRY|PLANNED SCENE(?: / CURRENT SCENE)?|FINAL PROMPT)\s*(?:\d+[^\n]*)?$|"
    r"</?(?:data|trigger|input|constraints|example|idea|scene)>",
)


def _normalized_words(prompt, trigger, target="Generic", connected=True):
    try:
        text = trigger_text_target(prompt, target)
    except ValueError:
        text = prompt
    for term in trigger_terms(trigger, connected):
        text = re.sub(re.escape(term), " ", text, flags=re.IGNORECASE)
    return re.findall(r"[a-z0-9]+", text.casefold())


def _shingles(words, size=3):
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[index:index + size]) for index in range(len(words) - size + 1)}


def _similarity(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _cluster_uniqueness(rows, pairs):
    """Count redundant items, not the fraction of all possible duplicate pairs."""
    parent = {row["index"]: row["index"] for row in rows}
    def root(index):
        while parent[index] != index:
            index = parent[index]
        return index
    for left, right in pairs:
        parent[root(right)] = root(left)
    distinct = len({root(index) for index in parent})
    return round(100 * (distinct - 1) / (len(rows) - 1)) if len(rows) > 1 else 100


# Small dependency-free semantic lexicon: normalize events and object families,
# not a menu of scene ideas. Deliberately conservative for narrow/guided scopes.
_CONCEPT_FAMILIES = {
    "juggle": r"juggl\w*",
    "failure": r"fail\w*|dropp\w*|drops?|spill\w*|fumbl\w*|losing|lost",
    "fruit": r"oranges?|apples?|pears?|bananas?|fruits?",
    "walk": r"walk\w*|stroll\w*|stepp\w*|steps?|strid\w*|trudg\w*",
    "run": r"runn\w*|runs?|sprint\w*|dash\w*|jogg\w*",
    "laugh": r"laugh\w*|chuckl\w*|giggl\w*",
    "wear": r"wear\w*|dressed|donning",
    "catch": r"catch\w*|catches|caught|snatch\w*|intercept\w*",
    "read": r"read\w*",
}


def idea_concepts(text):
    text = text.casefold()
    for family, pattern in _CONCEPT_FAMILIES.items():
        text = re.sub(r"\b(?:" + pattern + r")\b", family, text)
    # Object control in flight is a common paraphrase of failed juggling.
    if "failure" in text and "fruit" in text and re.search(r"\b(?:airborne|air|flight)\b", text):
        text += " juggle"
    text = re.sub(r"\b(?:trying|attempting|attempt|control|airborne|air|flight|three|two|one|and|to)\b", "", text)
    text = re.sub(r"\b(?:at (?:night|dawn|dusk|sunset)|in (?:warm|soft|bright) light|from a low angle)\b", "", text)
    return set(_scene_event_words(text))


def idea_action_error(idea, description):
    """High-confidence action loss only; unknown paraphrases remain review hints."""
    actions = idea_concepts(idea) & {"juggle", "walk", "run", "laugh", "catch", "read"}
    if actions and not actions & idea_concepts(description):
        return "The planned primary action disappeared. Preserve the fixed idea and its important action."
    return None


def _issue(code, severity, message, related=None):
    result = {"code": code, "severity": severity, "message": message}
    if related is not None:
        result["related"] = related
    return result


def _scene_event_words(scene):
    """Cheap lexical heuristic, not semantic inference or a scene planner."""
    event = re.split(r";|\b(?:under|with)\s+(?:soft|bright|diffuse|warm|dramatic|overcast)\b",
                     scene.casefold(), maxsplit=1)[0]
    event = re.split(r"\b(?:in|at|beside|against)\s+(?:a |an |the )?"
                     r"(?:bedroom|kitchen|office|park|studio|room|interior)\b", event, maxsplit=1)[0]
    stop = {"a", "an", "the", "she", "he", "they", "her", "his", "their", "woman", "man",
            "person", "character", "is", "are", "and", "while", "with", "in", "on", "at", "to",
            "of", "for", "by", "from", "as", "it", "its", "outside", "indoors", "outdoors"}
    return [word for word in re.findall(r"[a-z0-9]+", event) if word not in stop]


def analyze_scene_diversity(rows):
    """Flag exact, near-text and cosmetic-event repetitions without another LLM."""
    rows = [row for row in rows if row.get("scene", "").strip()]
    records = {row["index"]: {"index": row["index"], "issues": []} for row in rows}
    duplicate_pairs = set()
    for position, left in enumerate(rows):
        left_text = " ".join(left["scene"].casefold().split())
        left_words = re.findall(r"[a-z0-9]+", left_text)
        left_event = _scene_event_words(left["scene"])
        for right in rows[position + 1:]:
            right_text = " ".join(right["scene"].casefold().split())
            right_words = re.findall(r"[a-z0-9]+", right_text)
            right_event = _scene_event_words(right["scene"])
            code = None
            if left_text == right_text:
                code = "exact_duplicate_scene"
            elif len(left_words) >= 5 and len(right_words) >= 5 and _similarity(_shingles(left_words), _shingles(right_words)) >= .7:
                code = "near_duplicate_scene"
            elif (len(left_event) >= 2 and len(right_event) >= 2
                  and _similarity(set(left_event), set(right_event)) >= .8):
                code = "repeated_scene_event"
            if code:
                duplicate_pairs.add((left["index"], right["index"]))
                for current, other in ((left, right), (right, left)):
                    records[current["index"]]["issues"].append(_issue(
                        code, "warning", f"Scene idea may repeat scene {other['index']} ({code.replace('_', ' ')}). Review the core event, not just its presentation.", other["index"]))
    return {"count": len(rows), "uniqueness": _cluster_uniqueness(rows, duplicate_pairs),
            "scenes": list(records.values()), "method": "lexical heuristics; not a semantic guarantee"}


def analyze_idea_diversity(data, rows):
    """Inspect short ideas separately; heuristics defer to explicit concept scope."""
    rows = [row for row in rows if row.get("idea", "").strip()]
    records = {row["index"]: {"index": row["index"], "issues": []} for row in rows}
    pairs = set()
    guided = data.get("source_mode") == "guided"
    focused = data.get("variety") == "Focused"
    scope = (data.get("subject", "") + " " + data.get("constraints", "")).casefold()
    expression_scope = bool(re.search(r"(?:different|various|funny|facial)\s+(?:facial\s+)?expressions\b", scope))

    for position, left in enumerate(rows):
        for right in rows[position + 1:]:
            # Repeated/cycling authoritative guided lines are not brainstorming failures.
            if guided and (not left.get("input") or not right.get("input")
                           or " ".join(left["input"].split()) == " ".join(right["input"].split())):
                continue
            a, b = [" ".join(row["idea"].casefold().split()) for row in (left, right)]
            aw, bw = [idea_concepts(text) for text in (a, b)]
            facial = all(re.search(r"\b(?:face|facial|expression|expressions)\b", text) for text in (a, b))
            code = None
            if a == b:
                code = "exact_duplicate_idea"
            elif facial and expression_scope:
                continue
            elif focused:
                continue  # Narrow family variants are valid, but exact copies are not.
            elif aw and bw and (_similarity(aw, bw) >= .75 or (facial and not expression_scope)):
                code = "similar_idea_category"
            if code:
                pairs.add((left["index"], right["index"]))
                for current, other in ((left, right), (right, left)):
                    records[current["index"]]["issues"].append(_issue(code, "warning",
                        f"Idea may repeat the concept of idea {other['index']}. Check semantic variety, not just presentation differences.", other["index"]))
    return {"count": len(rows), "uniqueness": _cluster_uniqueness(rows, pairs),
            "ideas": list(records.values()), "method": "concept-aware lexical hints; not semantic verification"}


def explicit_geometry_issues(text):
    """Narrow explicit contradictions only; not a body simulator or pose judge.

    Negated requirements and mirror/multi-panel scenes are left to Deep Review.
    Unusual actions, rear three-quarter head turns and non-viewer gaze are not errors.
    """
    text = text.casefold().replace("–", "-").replace("—", "-")
    if re.search(r"\b(?:mirror|reflection|reflected|collage|inset|split.screen)\b", text):
        return []

    def asserted(pattern):
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 40):match.start()]
            if not re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$", prefix):
                return True
        return False

    issues = []
    rear = asserted(r"\b(?:direct|straight) rear view\b|\bcamera directly behind\b")
    frontal = asserted(r"\bfull(?:y)? frontal face\b|\bface (?:is )?(?:clearly )?fully frontal\b")
    turn = asserted(r"\bhead (?:is )?turned (?:back )?over (?:her |his |their |one )?shoulder\b")
    if rear and frontal and not turn:
        issues.append(_issue("rear_front_conflict", "warning",
            "Explicit direct rear view and fully frontal face conflict without a plausible turn. Check camera/body/head geometry."))
    elif rear and not turn and asserted(r"\blooking (?:straight |directly )?(?:at|into) (?:the )?(?:camera|viewer)\b"):
        issues.append(_issue("rear_gaze_conflict", "warning",
            "Direct rear view cannot support camera-directed gaze without a plausible over-shoulder head turn."))
    if (asserted(r"\b(?:straight |side |direct )?profile view\b|\bin profile\b")
            and asserted(r"\bboth sides of (?:the |her |his |their )?face (?:are )?equally visible\b")):
        issues.append(_issue("profile_face_conflict", "warning",
            "A profile camera view cannot show both sides of the face equally."))
    if (asserted(r"\bbody (?:is )?fully facing away\b")
            and asserted(r"\bhead (?:is )?fully frontal(?: toward (?:the )?camera)?\b")):
        issues.append(_issue("body_head_conflict", "warning",
            "A fully away body cannot support a fully frontal head toward the camera."))
    close = asserted(r"\btight (?:face|facial) close[- ]up\b|\btight upper[- ]body crop\b")
    feet = asserted(r"\b(?:shoes|feet) (?:are )?(?:clearly |fully )?visible\b|\b(?:clearly|fully) (?:showing|shows) (?:her |his |their )?(?:shoes|feet)\b")
    if close and feet:
        issues.append(_issue("crop_visibility_conflict", "warning",
            "A tight face/upper-body crop cannot also clearly show feet or shoes in the same view."))
    front_camera = asserted(r"\bcamera (?:is )?(?:directly )?in front\b")
    rear_camera = asserted(r"\bcamera (?:is )?directly behind\b")
    if front_camera and rear_camera:
        issues.append(_issue("camera_direction_conflict", "warning",
            "One camera is specified both directly in front and directly behind the subject."))
    return issues


def _prompt_trigger_valid(prompt, data):
    try:
        return trigger_presence_error(
            prompt, data.get("trigger", ""), data.get("target", "Generic"),
        ) is None
    except ValueError:
        return False


def _prompt_trigger_issue(prompt, data):
    try:
        return trigger_presence_error(
            prompt, data.get("trigger", ""), data.get("target", "Generic"),
        )
    except ValueError as exc:
        return str(exc)


def _prompt_trigger_preference(prompt, data):
    try:
        return trigger_contract_error(
            prompt, data.get("trigger", ""), data.get("target", "Generic"),
            connected=data.get("trigger_connected", True),
            at_start=data.get("trigger_at_start", False),
        )
    except ValueError:
        return None


def quality_signature(data, results, plan):
    value = {"version": 6, "trigger": data.get("trigger"), "target": data.get("target"),
             "trigger_connected": data.get("trigger_connected", True),
             "trigger_at_start": data.get("trigger_at_start", False),
             "amount": data.get("amount"), "results": results, "plan": plan}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def analyze_dataset_quality(data, results=None, plan=None):
    results = list(results if results is not None else data.get("results") or [])
    plan = list(plan if plan is not None else dataset_assignments(data))
    trigger, target = data.get("trigger", ""), data.get("target", "Generic")
    records = {item["index"]: {"index": item["index"], "status": "pass", "issues": []}
               for item in results}
    batch_issues = []

    def add(index, issue):
        records[index]["issues"].append(issue)

    format_passes = trigger_passes = 0
    normalized = {}
    shingles = {}
    openings = {}
    lengths = []
    for item in results:
        index, prompt = item["index"], item["prompt"]
        words = _normalized_words(prompt, trigger, target, data.get("trigger_connected", True))
        normalized[index] = " ".join(words)
        shingles[index] = _shingles(words)
        openings[index] = " ".join(words[:8])
        lengths.append((index, len(words)))
        if not prompt.strip():
            add(index, _issue("empty_output", "error", "The prompt is empty."))
        if _prompt_trigger_valid(prompt, data):
            trigger_passes += 1
            preference = _prompt_trigger_preference(prompt, data)
            if preference:
                add(index, _issue("trigger_preference", "warning", preference))
        else:
            issue = _prompt_trigger_issue(prompt, data)
            add(index, _issue("trigger_missing", "warning", issue or "Requested trigger wording is missing."))
        try:
            normalize_workflow_output(prompt, target)
            format_passes += 1
        except WorkflowFormatError as exc:
            add(index, _issue("target_format", "error", f"Target format is invalid: {exc}"))
        if len(words) < 8:
            add(index, _issue("too_short", "warning", "The prompt is unusually short and may not provide useful coverage."))
        if LEAKED_LABELS.search(prompt):
            add(index, _issue("internal_marker", "error", "Internal planning labels or delimiters leaked into the prompt."))
        try:
            leakage = positive_prompt_error(prompt, target, trigger_terms(trigger, data.get("trigger_connected", True)))
        except (ValueError, KeyError, TypeError):
            leakage = None  # Already reported by the target-format check above.
        if leakage:
            add(index, _issue("positive_content_leakage", "warning", leakage))
        for source in ("idea", "scene"):
            if leakage := visible_content_error(item.get(source, "")):
                add(index, _issue(source + "_content_leakage", "warning", leakage))
        if item.get("geometry"):
            from .dataset_geometry import geometry_errors
            for message in geometry_errors(item):
                add(index, _issue("structured_geometry", "warning", message))
        try:
            final_text = trigger_text_target(prompt, target)
        except ValueError:
            final_text = prompt
        for source, text in (("scene", item.get("scene", "")), ("prompt", final_text)):
            for issue in explicit_geometry_issues(text):
                add(index, {**issue, "code": source + "_" + issue["code"],
                            "message": f"{source.title()} geometry: " + issue["message"]})
        event_words = set(_scene_event_words(item.get("scene", "")))
        if len(event_words) >= 4 and len(event_words & set(words)) / len(event_words) < .25:
            add(index, _issue("scene_anchor_loss", "warning",
                             "Few planned-event words appear in the final prompt. Check scene fidelity or run Deep Review; paraphrasing may explain this warning."))

    duplicate_pairs = set()
    indexes = sorted(records)
    for position, left in enumerate(indexes):
        for right in indexes[position + 1:]:
            if normalized[left] and normalized[left] == normalized[right]:
                duplicate_pairs.add((left, right))
                add(left, _issue("exact_duplicate", "error", f"Exact duplicate of prompt {right}.", right))
                add(right, _issue("exact_duplicate", "error", f"Exact duplicate of prompt {left}.", left))
            elif _similarity(shingles[left], shingles[right]) >= .82:
                duplicate_pairs.add((left, right))
                add(left, _issue("near_duplicate", "warning", f"Very similar to prompt {right}.", right))
                add(right, _issue("near_duplicate", "warning", f"Very similar to prompt {left}.", left))
    opening_groups = {}
    for index, opening in openings.items():
        if opening:
            opening_groups.setdefault(opening, []).append(index)
    for group in opening_groups.values():
        if len(group) >= 3:
            for index in group:
                add(index, _issue("repeated_opening", "warning",
                                  f"Shares the same opening structure with prompts {', '.join(map(str, group))}."))
    if lengths:
        ordered = sorted(length for _index, length in lengths)
        median = ordered[len(ordered) // 2]
        if median >= 20:
            for index, length in lengths:
                if length < median * .35 or length > median * 2.5:
                    add(index, _issue("length_outlier", "warning",
                                      f"Length ({length} words) differs substantially from the batch median ({median})."))

    if len(results) != data.get("amount"):
        batch_issues.append(_issue("incomplete_batch", "error",
                                   f"Expected {data.get('amount')} prompts but found {len(results)}."))
    if not trigger:
        batch_issues.append(_issue("missing_trigger", "error", "No trigger / prepend text is configured for this batch."))
    if data.get("source_mode") == "guided":
        planned_inputs = Counter(item.get("input", "") for item in plan if item.get("input"))
        result_inputs = Counter(item.get("input", "") for item in results if item.get("input"))
        missing = list((planned_inputs - result_inputs).elements())
        if missing:
            batch_issues.append(_issue("guided_coverage", "error",
                                       f"{len(missing)} planned guided input assignments are missing from the results."))

    total = max(1, len(results))
    metrics = {
        "trigger": round(100 * trigger_passes / total),
        "format": round(100 * format_passes / total),
        "uniqueness": _cluster_uniqueness(results, duplicate_pairs),
    }
    scene_quality = analyze_scene_diversity(results)
    if scene_quality["count"]:
        metrics["scene_uniqueness"] = scene_quality["uniqueness"]
        for record in scene_quality["scenes"]:
            for issue in record["issues"]:
                add(record["index"], issue)
    idea_quality = analyze_idea_diversity(data, results)
    if idea_quality["count"]:
        metrics["idea_uniqueness"] = idea_quality["uniqueness"]
        for record in idea_quality["ideas"]:
            for issue in record["issues"]:
                add(record["index"], issue)
    for record in records.values():
        severities = {issue["severity"] for issue in record["issues"]}
        record["status"] = "error" if "error" in severities else "warning" if severities else "pass"
    all_issues = batch_issues + [issue for record in records.values() for issue in record["issues"]]
    weights = {"idea_uniqueness": .30, "scene_uniqueness": .20, "uniqueness": .15,
               "trigger": .15, "format": .10}
    # Legacy results without planning provenance remain diagnosable, not fabricated.
    active_weights = {key: weight for key, weight in weights.items() if key in metrics}
    score = round(sum(metrics[key] * weight for key, weight in active_weights.items()) / sum(active_weights.values()))
    severities = {issue["severity"] for issue in all_issues}
    status = "issues" if "error" in severities else "review" if "warning" in severities or score < 85 else "strong"
    return {"signature": quality_signature(data, results, plan), "status": status, "score": score,
            "metrics": metrics, "batch_issues": batch_issues,
            "scene_quality": scene_quality,
            "idea_quality": idea_quality,
            "prompts": [records[index] for index in sorted(records)]}
