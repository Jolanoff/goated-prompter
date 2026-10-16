"""Visual Direction (vocabulary/schemas/SPEC.md section 11): how each Dataset image is seen and lit.

Directions are ordinary vocabulary entries with a "visual" component, so they come from the run's selected packs,
follow ratings and pack isolation, and anyone can add more in a pack. Retrieval never offers them (retrieval.py
leaves them out); this module chooses them, per image, for the dimensions the brief leaves open:

  framing, camera_angle, composition  -> the concept's camera field
  lighting, atmosphere                -> the concept's lighting field (an entry's section may say camera instead)

Rules, in order:
1. The brief comes first. A direction the request, fixed, must or the user's rules name (by its name or an alias) is
   used for that dimension in every image (several named: they take turns). A dimension the brief only mentions in
   general ("dramatic lighting", "the same framing") is left to the brief: no direction is added. A dimension
   randomized mentions stays open. Avoid phrases and negations ("no dutch angle") rule directions out.
2. Each dimension can be turned off, and its variation set: same (one direction for the dataset), low, medium or
   high (more directions take turns); auto follows the creativity setting.
3. A direction must suit the dataset's style (media), its declared cast limits (people, for a direction that needs a
   person, never a framing limited by head count alone) and the directions already chosen for the image (conflicts,
   both ways). Directions named by the brief are placed first, so they always win a conflict.
3b. What the image's composed scene must show (SPEC.md section 12, see(n, visibility)): a direction whose declared
   shows cannot keep those regions, whole bodies or the place in view is not chosen for an open dimension. A direction
   that declares nothing about what it shows is not ruled out (unspecified is not incompatible). The brief's own
   named directions are kept even then: the user's words come first. Only framing decides how much is in view on its
   own (FRAMES): a direction of another dimension (a camera angle, a composition, a light) is checked only when it
   declares shows, so an undeclared light or composition never makes a scene's coverage unknown, while an
   undeclared framing does.
3c. The Director's structured preferences (preferences): directions it prefers enter a dimension's pool first, so a
   small variation keeps them; directions it avoids are left out unless the brief names them.
4. Image N's directions depend only on N, the seed, the brief, the settings and the selected packs: never on other
   images, so a failed or regenerated image changes no other. Within a dimension, each cycle through its pool uses
   every direction once, in an order seeded per cycle and dimension, so images differ and combinations vary.

No model and no semantic hints are read: only the confirmed brief's own words and the packs' declared data.
"""

from dataclasses import dataclass, field
import hashlib
import re

from .packs import RATINGS
from .resolver import implied
from .semantic import NEGATIONS, STOPWORDS, STRUCTURAL, marker, phrase_terms, split_negated, stem

DIMENSIONS = ("framing", "camera_angle", "composition", "lighting", "atmosphere")  # the order an image is decided in
FRAMES = ("framing",)  # the dimensions whose every direction decides how much of the scene is in view (rule 3b)
SECTIONS = ("camera", "lighting")
DEFAULT_SECTION = {"framing": "camera", "camera_angle": "camera", "composition": "camera", "lighting": "lighting",
                   "atmosphere": "lighting"}
VARIATIONS = ("auto", "same", "low", "medium", "high")
POOL = {"same": 1, "low": 2, "medium": 4, "high": None}  # None: every compatible direction takes part
AUTO = {"Strict": "low", "Balanced": "medium", "Creative": "high", "Dice": "high"}
# The style setting as a direction's media (prompting/styles.py resolve_style); Auto: only directions for every style.
MEDIA = {"Anime": "anime", "Realistic": "realistic", "Illustration": "illustration", "3D render": "3d",
         "Product": "product", "Painting": "painting"}
SETTING_KEYS = {"enabled", "variation"}
FIXING = ("must", "fixed", "rules", "request")  # the brief's fields that can set a dimension, strongest first
RANDOMIZED = "randomized"  # directions it names become the pool its dimension takes turns through
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def default_settings():
    return {dimension: {"enabled": True, "variation": "auto"} for dimension in DIMENSIONS}


def validate_settings(value):
    """Per-dimension {enabled, variation}; missing dimensions or fields take the defaults. Raises ValueError."""
    if value is None:
        return default_settings()
    if not isinstance(value, dict) or set(value) - set(DIMENSIONS):
        raise ValueError(f"Visual Direction settings are per dimension: {', '.join(DIMENSIONS)}.")
    settings = default_settings()
    for dimension, item in value.items():
        if not isinstance(item, dict) or set(item) - SETTING_KEYS:
            raise ValueError(f"Visual Direction {dimension} takes enabled and variation.")
        enabled, variation = item.get("enabled", True), item.get("variation", "auto")
        if type(enabled) is not bool or variation not in VARIATIONS:
            raise ValueError(f"Visual Direction {dimension}: enabled is true or false, variation one of {', '.join(VARIATIONS)}.")
        settings[dimension] = {"enabled": enabled, "variation": variation}
    return settings


def is_direction(entry):
    return ("visual" in entry.get("components", {}) and entry.get("abstract") is not True
            and not entry["components"].get("participants"))


def fit(registry, shows, visibility):
    """(status, reason) of a direction that declares shows (its visual.shows, {} when undeclared) for what a composed
    image must show (resolver Resolution.visibility, or None): "feasible", "unknown" (the direction does not say) or
    "conflict" (it declares it cannot). Nothing to show is always feasible."""
    participants = (visibility or {}).get("participants", {})
    whole = sorted(who for who, need in participants.items() if need.get("whole"))
    regions = [(who, region) for who, need in participants.items() for region in dict.fromkeys(need.get("regions", []))]
    space = bool((visibility or {}).get("space"))
    if not (whole or regions or space):
        return "feasible", ""
    statuses, reasons = [], []
    if whole:
        if shows.get("whole") is False:
            statuses.append("conflict")
            reasons.append(f"it does not show {', '.join(whole)} whole")
        elif "whole" not in shows:
            statuses.append("unknown")
    if regions and not shows.get("whole"):
        limit = shows.get("max_regions")
        if limit is not None and len(regions) > limit:
            statuses.append("conflict")
            reasons.append(f"it shows {limit} {'region' if limit == 1 else 'regions'}, the scene needs {len(regions)} in view")
        declared = set(shows.get("regions", []))
        missing = sorted({region for _, region in regions if not implied(registry, [region]) & declared})
        if missing and shows.get("complete"):
            statuses.append("conflict")
            reasons.append(f"it does not show {', '.join(missing)}")
        elif missing and limit is None:
            statuses.append("unknown")
    if space:
        if shows.get("space") is False:
            statuses.append("conflict")
            reasons.append("it does not show the place")
        elif "space" not in shows:
            statuses.append("unknown")
    status = "conflict" if "conflict" in statuses else "unknown" if "unknown" in statuses else "feasible"
    return status, "; ".join(reasons)


def coverage(registry, item, visibility):
    """(status, reason) of a Direction for what a composed image must show: fit() of its declared shows. A direction
    outside FRAMES that declares no shows says nothing about what is in view, so it imposes nothing (feasible)."""
    if not item.shows and item.dimension not in FRAMES:
        return "feasible", ""
    return fit(registry, item.showing(), visibility)


# -- the brief's words, matched the way retrieval matches names (semantic.phrase_terms), with their spans

def _tokens(text):
    """[(term, start, end)]: content words stemmed, structural words as markers, other function words dropped."""
    out = []
    for match in _WORD.finditer(str(text or "").casefold()):
        word = match.group().replace("'s", "").replace("'", "")
        if word in STRUCTURAL:
            out.append((marker(word), match.start(), match.end()))
        elif word not in STOPWORDS and word not in NEGATIONS:
            out.append((stem(word), match.start(), match.end()))
        elif word in NEGATIONS:
            out.append(("!", match.start(), match.end()))  # never part of a phrase
    return out


def _find(tokens, phrase):
    """Spans where phrase (phrase_terms) occurs, in order, in the tokens."""
    size, found = len(phrase), []
    for start in range(len(tokens) - size + 1):
        if [term for term, _, _ in tokens[start:start + size]] == phrase:
            found.append((tokens[start][1], tokens[start + size - 1][2]))
    return found


def _contains(terms, phrase):
    plain = [term for term in phrase if term != "@"]
    return bool(plain) and any(terms[index:index + len(plain)] == plain for index in range(len(terms) - len(plain) + 1))


def _positive(text):
    """The text's tokens outside the scope of a negation ("no dutch angle" names nothing)."""
    positive = set(split_negated(text)[0])
    tokens, ruled = _tokens(text), set(split_negated(text)[1])
    return [token for token in tokens if token[0] == "@" or token[0] in positive or token[0] not in ruled]


def _phrases(entry):
    return [phrase for phrase in (phrase_terms(text) for text in [entry["name"], *entry.get("aliases", [])]) if phrase]


def _hash(*parts):
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


@dataclass(frozen=True)
class Direction:
    id: str
    name: str
    description: str
    dimension: str
    section: str
    pack: str
    conflicts: frozenset = field(default_factory=frozenset)
    shows: tuple = ()  # the declared visual.shows as sorted (key, value) pairs; () when undeclared

    def showing(self):
        return {key: list(value) if isinstance(value, tuple) else value for key, value in self.shows}

    def text(self):
        description = self.description.strip().rstrip(".")
        return f"{self.name}: {description[:1].lower()}{description[1:]}" if description else self.name


class Plan:
    """The Visual Direction of one Dataset run. directions(n) is image n's {dimension: Direction}."""

    def __init__(self, enabled, *, reason="", dimensions=None, pools=None, every=None, seed=0, log=None):
        self.enabled, self.reason = enabled, reason
        self.dimensions = dimensions or {}
        self.pools = pools or {}
        self.every = every or {}
        self.seed = seed
        self.log = log or {}
        self.mask = ([], [])  # (phrases, patterns) masked out of content retrieval while active
        self._memo = {}
        self.registry = None
        self.visibility = {}  # image number -> what its composed scene must show (see())
        self.required = {}

    def see(self, number, visibility, directions=()):
        """What image number's composed scene must show (resolver visibility): open dimensions then choose only
        directions that can show it. Set before the image's directions are read; changing it recomputes them."""
        if visibility:
            self.visibility[number] = visibility
        else:
            self.visibility.pop(number, None)
        self._memo.pop(number, None)
        self.required[number] = {direction(self.registry, ident).dimension: direction(self.registry, ident)
                                 for ident in directions} if self.registry else {}

    @property
    def active(self):
        return self.enabled and bool(self.pools)

    def _order(self, dimension, cycle):
        pool = self.pools[dimension]
        if self.dimensions[dimension]["status"] == "fixed" and len(pool) > 1:
            return list(pool)  # the brief's own order: named directions take turns as written
        return sorted(pool, key=lambda item: _hash(self.seed, dimension, cycle, item.id))

    def directions(self, number):
        """{dimension: Direction} for image number (1-based) and [notes] on what could not be placed."""
        if number in self._memo:
            return self._memo[number]
        chosen, notes = dict(self.required.get(number, {})), []
        fixed = [dimension for dimension in DIMENSIONS if self.dimensions.get(dimension, {}).get("status") == "fixed"]
        order = fixed + [dimension for dimension in DIMENSIONS if dimension in self.pools and dimension not in fixed]
        visibility = self.visibility.get(number)
        for dimension in order:
            if dimension in chosen:
                continue
            pool = self.pools[dimension]
            cycle, position = divmod(number - 1, len(pool))
            ranked = self._order(dimension, cycle)
            ranked = ranked[position:] + ranked[:position]
            if visibility and self.registry:
                ranked.sort(key=lambda item: {"feasible": 0, "unknown": 1, "conflict": 2}[
                    coverage(self.registry, item, visibility)[0]])
            # The brief's own directions are kept whatever the scene needs; open ones must be able to show it.
            visible = (lambda item: True) if self.dimensions[dimension]["status"] == "fixed" else (
                lambda item: self.shows_enough(item, visibility))
            pick = next((item for item in ranked if self._fits(item, chosen) and visible(item)), None)
            if pick is None and self.dimensions[dimension]["status"] == "open":
                rest = sorted((item for item in self.every.get(dimension, []) if item not in pool),
                              key=lambda item: _hash(self.seed, dimension, "rest", item.id))
                pick = next((item for item in rest if self._fits(item, chosen) and visible(item)), None)
                if pick is not None:
                    notes.append(f"{dimension}: {pick.id} from outside the pool, no pooled direction fits the image")
            if pick is None:
                notes.append(f"{dimension}: none, every candidate conflicts with "
                             + ", ".join(item.id for item in chosen.values()))
                continue
            chosen[dimension] = pick
        self._memo[number] = (chosen, notes)
        return chosen, notes

    @staticmethod
    def _fits(item, chosen):
        return all(item.id not in other.conflicts and other.id not in item.conflicts for other in chosen.values())

    def shows_enough(self, item, visibility):
        return not visibility or self.registry is None or coverage(self.registry, item, visibility)[0] != "conflict"

    def concept(self, number):
        """The visual_direction item for one concept request: camera and lighting text, in the concept's own fields."""
        chosen, _ = self.directions(number)
        fields = {}
        for dimension in DIMENSIONS:
            if dimension in chosen:
                fields.setdefault(chosen[dimension].section, []).append(chosen[dimension].text())
        return {section: "; ".join(fields[section]) for section in SECTIONS if section in fields}

    def offer(self, numbers):
        """[{concept, camera?, lighting?}] for a request writing these images (1-based, in order); [] without any."""
        if not self.active:
            return []
        items = [{"concept": position, **self.concept(number)} for position, number in enumerate(numbers, 1)]
        return items if any(len(item) > 1 for item in items) else []

    def record(self, count):
        """The diagnostics: settings, every dimension's status and pool, exclusions and each image's directions."""
        slots = []
        if self.active:
            for number in range(1, count + 1):
                chosen, notes = self.directions(number)
                slots.append({"slot": number, "directions": {dimension: item.id for dimension, item in chosen.items()},
                              **({"visibility": self.visibility[number]} if number in self.visibility else {}),
                              **({"notes": notes} if notes else {})})
        return {**self.log, "enabled": self.active, **({"reason": self.reason} if self.reason else {}), "slots": slots}


def off(reason, settings=None):
    return Plan(False, reason=reason, log={"settings": settings})


def _shows(visual):
    shows = visual.get("shows", {})
    return tuple(sorted((key, tuple(value) if isinstance(value, list) else value) for key, value in shows.items()))


def direction(registry, ident):
    entry = registry.resolved(ident)
    visual = entry["components"]["visual"]
    return Direction(ident, entry["name"], entry.get("description", ""), visual["dimension"],
                     visual.get("section", DEFAULT_SECTION[visual["dimension"]]), registry.owner(ident),
                     frozenset(visual.get("conflicts", [])), _shows(visual))


def plan(registry, brief, settings, *, allowed=RATINGS, preferences=None):
    """The Visual Direction for a confirmed brief from the directions in registry (the run's selected packs).

    preferences: the Director's {"prefer": [ids], "avoid": [ids]} (ids may be replaced ids; unknown ones are ignored)."""
    settings = validate_settings(settings)
    preferences = preferences or {}
    prefer = [registry.canonical(item) for item in preferences.get("prefer", [])]
    avoid = {registry.canonical(item) for item in preferences.get("avoid", [])}
    if not any(item["enabled"] for item in settings.values()):
        return off("every Visual Direction dimension is turned off", settings)
    directions = {}
    for entry_id in sorted(registry.ids()):
        entry = registry.resolved(entry_id)
        if is_direction(entry):
            directions[entry_id] = entry
    if not directions:
        return off("the selected packs hold no visual directions", settings)
    data, brief_settings = brief["input"], brief["settings"]
    style = _style(brief_settings)
    medium = MEDIA.get(style)
    people = brief.get("people") if type(brief.get("people")) is int else len(brief.get("characters", []))
    creativity = brief_settings.get("creativity") or "Balanced"
    seed = data.get("seed") if type(data.get("seed")) is int else 0
    texts = {"request": [data.get("request", "")], "fixed": [brief.get("fixed", "")], "must": list(brief.get("must", [])),
             "rules": list(data.get("rules", [])), "randomized": [brief.get("randomized", "")]}
    tokens = {name: [_positive(text) for text in values] for name, values in texts.items()}

    # What the brief rules out: avoid phrases and negated words anywhere in it.
    ruled_out = [split_negated(item)[0] + split_negated(item)[1] for item in brief.get("avoid", [])]
    ruled_out += [split_negated(text)[1] for values in texts.values() for text in values]
    excluded, candidates = [], {dimension: [] for dimension in DIMENSIONS}
    every = {dimension: [] for dimension in DIMENSIONS}
    for entry_id, entry in directions.items():
        visual = entry["components"]["visual"]
        item = direction(registry, entry_id)
        reason = None
        if entry.get("rating") not in allowed:
            reason = f"rating {entry.get('rating')} is not allowed"
        elif any(_contains(terms, phrase) for terms in ruled_out for phrase in _phrases(entry)):
            reason = "ruled out by the brief"
        elif "media" in visual and medium not in visual["media"]:
            reason = (f"only for {', '.join(visual['media'])} styles, the style is {style}" if medium
                      else f"only for {', '.join(visual['media'])} styles, the style is left to the request")
        elif item.dimension != "framing" and not _cast_fits(visual.get("people", {}), people):
            reason = f"not for {people} {'person' if people == 1 else 'people'} per image"
        elif entry_id in avoid:
            reason = "the Director avoids it"
        if reason:
            excluded.append({"id": entry_id, "reason": reason})
        else:
            candidates[item.dimension].append(item)
        every[item.dimension].append(item)

    dimensions, pools, masked, patterns = {}, {}, [], []
    for dimension in DIMENSIONS:
        setting = settings[dimension]
        named, source = _named(tokens, every[dimension], directions, FIXING)
        varied, _ = _named(tokens, candidates[dimension], directions, (RANDOMIZED,))
        words = _dimension_patterns(dimension, every[dimension], registry)
        mentioned = {name: any(pattern.search(text) for pattern in words for text in values) for name, values in texts.items()}
        patterns += [pattern.pattern for pattern in words if any(mentioned.values())]
        info = {"enabled": setting["enabled"], "variation": setting["variation"], "candidates": len(candidates[dimension])}
        if not setting["enabled"]:
            info["status"] = "off"
        elif named:
            # What the brief names is used even when the Director avoids it: the user's words come first.
            usable = [item for item in named if item in candidates[dimension] or
                      (item.id in avoid and any(row["id"] == item.id and row["reason"] == "the Director avoids it" for row in excluded))]
            info.update(status="fixed" if usable else "kept", source=source, named=[item.id for item in named])
            if usable:
                pools[dimension] = usable
            else:
                info["reason"] = "the brief names it, but it does not suit this style or cast: left to the brief"
        elif any(mentioned[name] for name in ("must", "fixed", "rules")) or (mentioned["request"] and not mentioned[RANDOMIZED]):
            info.update(status="kept", source=next(name for name in FIXING if mentioned[name]),
                        reason="the brief sets it in its own words")
        elif varied:
            pools[dimension] = varied
            info.update(status="open", source=RANDOMIZED, named=[item.id for item in varied], effective_variation="named")
        elif not candidates[dimension]:
            info["status"] = "unavailable"
        else:
            variation = AUTO.get(creativity, "medium") if setting["variation"] == "auto" else setting["variation"]
            # The Director's preferred directions come first (in its order), so a small variation keeps them.
            ranked = sorted(candidates[dimension], key=lambda item: (item.id not in prefer,
                                                                    prefer.index(item.id) if item.id in prefer else 0,
                                                                    _hash(seed, dimension, "pool", item.id)))
            pools[dimension] = ranked[:POOL[variation]] if POOL[variation] else ranked
            info.update(status="open", effective_variation=variation)
            preferred = [item.id for item in pools[dimension] if item.id in prefer]
            if preferred:
                info["director_prefers"] = preferred
        if dimension in pools:
            info["pool"] = [item.id for item in pools[dimension]]
        dimensions[dimension] = info
        for item in [*named, *varied]:
            masked += _phrases(directions[item.id])
    log = {"settings": settings, "style": style, "people": people, "seed": seed, "dimensions": dimensions,
           "excluded": excluded, "masked": [" ".join(phrase) for phrase in _unique(masked)] + list(dict.fromkeys(patterns))}
    if prefer or avoid:
        log["director"] = {"prefer": [item for item in prefer if item in directions],
                           "avoid": sorted(item for item in avoid if item in directions),
                           "unknown": sorted({*prefer, *avoid} - set(directions))}
    if not pools:
        return Plan(False, reason="no dimension is open for Visual Direction", dimensions=dimensions, log=log)
    plan_ = Plan(True, dimensions=dimensions, pools=pools, every=candidates, seed=seed, log=log)
    plan_.registry = registry
    plan_.mask = (_unique(masked), list(dict.fromkeys(patterns)))
    return plan_


def _style(settings):
    from ...prompting.styles import resolve_style  # the same resolution the Builder uses
    return resolve_style(settings.get("style"), settings.get("target"))


def _cast_fits(people, count):
    return people.get("min", 0) <= count <= people.get("max", 64)


def _named(tokens, items, directions, fields):
    """The directions of one dimension the brief names, strongest field first, in the order written; and that field.
    A match inside a longer one is not a mention ("extreme close-up" names no "Close-up")."""
    for name in fields:
        found = []
        for text, values in enumerate(tokens[name]):
            for item in items:
                for phrase in _phrases(directions[item.id]):
                    found += [(text, start, end, item) for start, end in _find(values, phrase)]
        found = [hit for hit in found if not any(other[0] == hit[0] and other[1] <= hit[1] and hit[2] <= other[2]
                                                 and (other[1], other[2]) != (hit[1], hit[2]) for other in found)]
        if found:
            ordered = sorted(found, key=lambda hit: (hit[0], hit[1], hit[3].id))
            return list(dict.fromkeys(hit[3] for hit in ordered)), name
    return [], None


def _dimension_patterns(dimension, items, registry):
    """How a brief mentions a dimension in general: the dimension's own name ("camera angle") and the names of the
    categories that hold its directions ("Camera angles"), as written (a plural s allowed), never stemmed, so
    "lighting" is not "light blue". Data, never a list of subjects."""
    categories = registry.categories()
    names = {dimension.replace("_", " ")} | {categories.get(registry.resolved(item.id)["category"], {}).get("name", "")
                                              for item in items}
    patterns = []
    for name in sorted(names):
        words = re.findall(r"[a-z0-9]+", name.casefold())
        if words:
            patterns.append(re.compile(r"\b" + r"\W+".join(re.escape(word) + "s?" if not word.endswith("s") else re.escape(word[:-1]) + "s?"
                                                             for word in words) + r"\b", re.IGNORECASE))
    return patterns


def _unique(phrases):
    out = []
    for phrase in phrases:
        if phrase and list(phrase) not in out:
            out.append(list(phrase))
    return out


def mask(text, phrases, patterns=()):
    """The text with every occurrence of these phrases (phrase_terms) and patterns blanked, punctuation kept: what a
    brief says about the camera or light is not scene content for retrieval ("low camera angle" is no Camera prop)."""
    text = str(text or "")
    if not (phrases or patterns) or not text:
        return text
    tokens = _tokens(text)
    spans = sorted([span for phrase in phrases for span in _find(tokens, phrase)]
                   + [match.span() for pattern in patterns for match in re.finditer(pattern, text, re.IGNORECASE)])
    out, last = [], 0
    for start, end in spans:
        if start < last:
            continue
        out.append(text[last:start])
        last = end
    out.append(text[last:])
    return " ".join("".join(out).split())


def masked_brief(brief, masks):
    """A copy of the brief for content retrieval with the visual phrases (Plan.mask) masked out of its free text."""
    phrases, patterns = masks
    if not (phrases or patterns):
        return brief
    def clean(text):
        return mask(text, phrases, patterns)
    data = brief["input"]
    return {**brief, "summary": clean(brief.get("summary", "")), "fixed": clean(brief.get("fixed", "")),
            "randomized": clean(brief.get("randomized", "")), "must": [clean(item) for item in brief.get("must", [])],
            "input": {**data, "request": clean(data.get("request", "")), "rules": [clean(item) for item in data.get("rules", [])]}}
