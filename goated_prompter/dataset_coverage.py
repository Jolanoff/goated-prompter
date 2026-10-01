"""Deterministic coverage plans and local quality checks for Dataset batches."""

from collections import Counter
import hashlib
import json
import random
import re

from .workflow_output import WorkflowFormatError, normalize_workflow_output
from .dataset_triggers import trigger_contract_error, trigger_presence_error, trigger_terms, trigger_text_target
from .dataset_visible_content import visible_content_error, positive_prompt_error


AXES = {
    "framing": ("Framing", ("face close-up", "head-and-shoulders", "medium shot", "three-quarter shot", "full view", "wide environmental view")),
    "viewpoint": ("Viewpoint", ("eye level", "three-quarter view", "side profile", "low angle", "high angle", "overhead view")),
    "pose_action": ("Pose / action", ("relaxed standing pose", "seated pose", "walking", "running", "reaching", "looking back", "crouching")),
    "expression": ("Expression", ("neutral expression", "warm smile", "focused expression", "contemplative expression", "surprised expression", "determined expression")),
    "lighting": ("Lighting", ("soft window daylight", "golden-hour light", "clean studio lighting", "dramatic low-key light", "colored practical light", "overcast diffuse light")),
    "setting": ("Setting", ("minimal studio", "quiet interior", "urban street", "natural landscape", "workplace context", "night environment")),
    "subject_matter": ("Subject matter", ("character portrait", "architecture", "product still life", "nature scene", "fashion scene", "vehicle", "food composition", "abstract forms")),
    "composition": ("Composition", ("centered composition", "rule-of-thirds composition", "strong negative space", "layered depth", "symmetrical layout", "diagonal composition")),
    "scale": ("Scale", ("intimate detail", "human scale", "room scale", "environmental scale", "monumental scale")),
    "palette": ("Palette", ("restrained neutral palette", "warm palette", "cool palette", "high-contrast palette", "pastel palette", "limited accent-color palette")),
    "context": ("Use context", ("isolated presentation", "in active use", "editorial presentation", "retail context", "domestic context", "outdoor context")),
    "surface": ("Surface", ("matte seamless surface", "natural wood", "polished stone", "brushed metal", "textured fabric", "reflective glass")),
    "background": ("Background", ("plain neutral background", "tonal gradient", "contextual interior", "outdoor environment", "graphic color field", "dark controlled backdrop")),
    "application": ("Application", ("packaging", "storefront signage", "apparel", "digital interface", "vehicle graphics", "printed campaign", "product marking")),
    "material": ("Material", ("paper print", "embossed card", "painted metal", "fabric embroidery", "glass decal", "digital screen", "three-dimensional signage")),
    "placement": ("Placement", ("central hero placement", "small corner placement", "repeating pattern", "edge-aligned placement", "environment-integrated placement", "label placement")),
    "layout": ("Layout", ("single focal layout", "editorial grid", "stacked layout", "asymmetrical layout", "modular system", "poster layout")),
    "hierarchy": ("Hierarchy", ("single headline", "headline and subhead", "multi-level editorial hierarchy", "oversized display type", "small refined typography", "repeating typographic system")),
}

CATEGORY_AXES = {
    "Character": ("framing", "viewpoint", "pose_action", "expression", "lighting", "setting"),
    "Multiple characters": ("framing", "viewpoint", "pose_action", "expression", "lighting", "setting"),
    "Animal": ("framing", "viewpoint", "pose_action", "context", "lighting", "setting"),
    "Visual style": ("subject_matter", "composition", "scale", "palette", "lighting", "setting"),
    "Object / product": ("framing", "viewpoint", "context", "surface", "lighting", "background"),
    "Location / environment": ("viewpoint", "composition", "scale", "lighting", "setting", "context"),
    "Brand / logo": ("application", "material", "placement", "layout", "lighting", "setting"),
    "Typography / text": ("layout", "hierarchy", "material", "placement", "background", "lighting"),
    "Concept": ("framing", "viewpoint", "composition", "context", "lighting", "setting"),
    "Custom": ("framing", "viewpoint", "composition", "context", "lighting", "setting"),
}

VARIETY_AXIS_COUNTS = {"Focused": 3, "Balanced": 5, "Wide": 6}
LEAKED_LABELS = re.compile(
    r"(?im)^\s*(?:ITEM|TRIGGER TYPE|TRIGGER DESCRIPTION|REQUIRED TRIGGER TEXT|DATASET CONCEPT|"
    r"SOURCE MODE|GUIDED INPUT|ADDITIONAL CONSISTENCY RULES|CONSISTENCY AND VARIATION RULES|"
    r"EARLIER ITEM|OUTPUT FORMAT|CURRENT SCENE|PLANNED IDEA|PLANNED SCENE(?: / CURRENT SCENE)?|FINAL PROMPT|COVERAGE ASSIGNMENT)\s*(?:\d+[^\n]*)?$|"
    r"</?(?:data|trigger|input|constraints|example|idea|scene)>",
)


def available_axes(trigger_type):
    keys = CATEGORY_AXES.get(trigger_type, CATEGORY_AXES["Custom"])
    return [{"key": key, "label": AXES[key][0], "options": list(AXES[key][1])} for key in keys]


def selected_axes(data):
    allowed = CATEGORY_AXES.get(data.get("trigger_type"), CATEGORY_AXES["Custom"])
    explicit = data.get("coverage_axes") or []
    if explicit:
        selected = tuple(key for key in explicit if key in allowed)
        return selected or allowed[:VARIETY_AXIS_COUNTS.get(data.get("variety"), 5)]
    return allowed[:VARIETY_AXIS_COUNTS.get(data.get("variety"), 5)]


def plan_signature(data):
    relevant = {
        "trigger_type": data.get("trigger_type"), "custom_type": data.get("custom_type"),
        "amount": data.get("amount"), "visual_style": data.get("visual_style"),
        "source_mode": data.get("source_mode"), "inputs": data.get("inputs"),
        "variety": data.get("variety"), "coverage_axes": data.get("coverage_axes") or [],
    }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def build_coverage_plan(data, seed=None):
    signature = plan_signature(data)
    seed = data.get("plan_seed", 0) if seed is None else seed
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Coverage plan seed must be between 0 and 2147483647.")
    enabled = data.get("coverage_enabled") is True
    axes = selected_axes(data) if enabled else ()
    lines = [line.strip() for line in str(data.get("inputs") or "").splitlines() if line.strip()]
    amount = int(data.get("amount", 1))
    columns = {}
    for position, key in enumerate(axes):
        values = list(AXES[key][1])
        rng = random.Random(f"{signature}:{seed}:{key}")
        rng.shuffle(values)
        offset = position % len(values)
        columns[key] = [values[(index + offset) % len(values)] for index in range(amount)]
    plan = []
    for index in range(amount):
        guided = lines[index % len(lines)] if data.get("source_mode") == "guided" and lines else ""
        plan.append({"index": index + 1, "input": guided,
                     "facets": {key: columns[key][index] for key in axes}})
    return {"enabled": enabled, "plan": plan, "signature": signature, "seed": seed,
            "selected_axes": list(axes), "available_axes": available_axes(data.get("trigger_type"))}


def effective_coverage_plan(data):
    if data.get("coverage_enabled") is not True:
        return build_coverage_plan(data)
    expected = plan_signature(data)
    plan = data.get("coverage_plan")
    if (data.get("plan_signature") == expected and isinstance(plan, list)
            and len(plan) == data.get("amount")):
        return {"enabled": True, "plan": plan, "signature": expected, "seed": data.get("plan_seed", 0),
                "selected_axes": list(selected_axes(data)),
                "available_axes": available_axes(data.get("trigger_type"))}
    return build_coverage_plan(data)


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
    pairs = max(1, len(rows) * (len(rows) - 1) // 2)
    return {"count": len(rows), "uniqueness": round(100 * (1 - len(duplicate_pairs) / pairs)),
            "scenes": list(records.values()), "method": "lexical heuristics; not a semantic guarantee"}


def analyze_idea_diversity(data, rows):
    """Inspect short ideas separately; heuristics defer to explicit concept scope."""
    rows = [row for row in rows if row.get("idea", "").strip()]
    records = {row["index"]: {"index": row["index"], "issues": []} for row in rows}
    pairs = set()
    constrained = data.get("source_mode") == "guided" or data.get("variety") == "Focused"
    scope = (data.get("subject", "") + " " + data.get("constraints", "")).casefold()
    expression_scope = bool(re.search(r"(?:different|various|funny|facial)\s+(?:facial\s+)?expressions\b", scope))

    def idea_words(text):
        text = re.sub(r"\b(?:at (?:night|dawn|dusk|sunset)|in (?:warm|soft|bright) light|from a low angle)\b", "", text)
        return set(_scene_event_words(text))

    for position, left in enumerate(rows):
        for right in rows[position + 1:]:
            # Repeated/cycling authoritative guided lines are not brainstorming failures.
            if constrained:
                continue
            a, b = [" ".join(row["idea"].casefold().split()) for row in (left, right)]
            aw, bw = [idea_words(text) for text in (a, b)]
            facial = all(re.search(r"\b(?:face|facial|expression|expressions)\b", text) for text in (a, b))
            code = None
            if a == b:
                code = "exact_duplicate_idea"
            elif facial and expression_scope:
                continue
            elif aw and bw and (_similarity(aw, bw) >= .75 or (facial and not expression_scope)):
                code = "similar_idea_category"
            if code:
                pairs.add((left["index"], right["index"]))
                for current, other in ((left, right), (right, left)):
                    records[current["index"]]["issues"].append(_issue(code, "warning",
                        f"Idea may repeat the concept of idea {other['index']}. Check semantic variety, not just presentation differences.", other["index"]))
    total_pairs = max(1, len(rows) * (len(rows) - 1) // 2)
    return {"count": len(rows), "uniqueness": round(100 * (1 - len(pairs) / total_pairs)),
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
    value = {"version": 4, "trigger": data.get("trigger"), "target": data.get("target"),
             "trigger_connected": data.get("trigger_connected", True),
             "trigger_at_start": data.get("trigger_at_start", False),
             "amount": data.get("amount"), "results": results, "plan": plan}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def analyze_dataset_quality(data, results=None, plan=None):
    results = list(results if results is not None else data.get("results") or [])
    plan = list(plan if plan is not None else effective_coverage_plan(data)["plan"])
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

    coverage_enabled = data.get("coverage_enabled") is True
    coverage_parts = []
    if coverage_enabled:
        for key in selected_axes(data):
            values = [item.get("facets", {}).get(key) for item in plan if item.get("facets", {}).get(key)]
            expected = min(len(values), len(AXES[key][1]))
            coverage_parts.append(len(set(values)) / expected if expected else 1)
    coverage_score = round(100 * sum(coverage_parts) / len(coverage_parts)) if coverage_parts else 100
    total = max(1, len(results))
    pair_count = max(1, len(results) * (len(results) - 1) // 2)
    metrics = {
        "trigger": round(100 * trigger_passes / total),
        "format": round(100 * format_passes / total),
        "uniqueness": max(0, round(100 * (1 - len(duplicate_pairs) / pair_count))),
    }
    if coverage_enabled:
        metrics["planned_coverage"] = coverage_score
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
    score = (round(metrics["trigger"] * .25 + metrics["format"] * .20
                   + metrics["uniqueness"] * .30 + metrics["planned_coverage"] * .25)
             if coverage_enabled else
             round((metrics["trigger"] * .25 + metrics["format"] * .20
                    + metrics["uniqueness"] * .30) / .75))
    severities = {issue["severity"] for issue in all_issues}
    status = "issues" if "error" in severities else "review" if "warning" in severities or score < 85 else "strong"
    return {"signature": quality_signature(data, results, plan), "status": status, "score": score,
            "metrics": metrics, "batch_issues": batch_issues,
            "scene_quality": scene_quality,
            "idea_quality": idea_quality,
            "prompts": [records[index] for index in sorted(records)]}
