"""Vocabulary retrieval (Phase 4): a small, relevant, checked set of entries for the Scene Director.

    index = VocabularyIndex(registry)                    # once per registry (the enabled packs)
    found = retrieve(index, RetrievalRequest.from_brief(brief, director=instructions))
    found.entries        # [RetrievedEntry], best first, at most config.max_results
    found.render()       # a short reference block for a prompt, or "" when nothing is relevant

Retrieval assists; it never decides. It does not choose a scene, a position or a cast, and an
empty result is normal: the director then writes an original scene exactly as without vocabulary.

How an entry is found (SPEC.md section 10):
  relevance   the request, summary, must, rules, fixed, randomized, characters, director and style
              texts against each entry's name, aliases, tags, category, description and notes
              (semantic.py: stems, spelling variants, compounds, multi-word names), plus related
              concepts through the vocabulary's own links: capabilities an entry uses and what they
              imply, postures a position uses, and inheritance. "avoid" and negated phrases
              ("no toys") of the request's own texts count against an entry, and rule it out when they
              name it; negations in the director and style texts are standing instructions and do not.
  eligibility the entry's resolved rating must be allowed (NSFW off: general and mature).
  compatibility the Phase 3 resolver, against a cast inferred from the characters through the
              vocabulary's own body entries (never by gender rules in code). Confirmed conflicts
              are dropped; unknown is kept. A space or an object the scene has not chosen is reported
              as a need, not as unknown about the cast.
  selection   relevance x compatibility. An entry and its descendant: the descendant replaces it when it
              matches more of the request, an equivalent descendant is dropped, otherwise both stay.
              Then a variety pass (maximal marginal relevance, tuned by the creativity setting) that
              drops near-duplicate entries.

The engine never branches on category names: what an entry is comes from its components.
"""

from dataclasses import dataclass, field
import re
import time

from .packs import _capability_refs
from .resolver import FEASIBLE_NOTE, RANK, _Run, candidate_bindings, implied
from .semantic import Document, TextIndex, split_negated, terms

RATINGS = ("general", "mature", "adult")
FIELD_WEIGHTS = {"name": 3.0, "alias": 3.0, "tag": 1.5, "category": 0.5, "description": 1.0, "notes": 0.5}
STRONG_FIELDS = ("name", "alias", "tag")
SOURCE_WEIGHTS = {"must": 1.2, "request": 1.0, "summary": 0.9, "rules": 0.8, "fixed": 0.7, "randomized": 0.5,
                  "characters": 0.5, "director": 0.4, "style": 0.3}
STANDING = ("director", "style")  # standing instructions, not this request: their negations rule nothing out
# Creativity setting -> (weight of relevance against variety, relevance floor relative to the best match).
CREATIVITY = {"Strict": (0.85, 0.30), "Balanced": (0.70, 0.20), "Creative": (0.55, 0.15), "Dice": (0.45, 0.10)}
STATUS_FACTOR = {"feasible": 1.0, "eligible": 0.92, "unknown": 0.8}
LINKS = {"uses": 0.5, "used by": 0.35, "broader": 0.35, "narrower": 0.35, "parent": 0.4, "child": 0.3, "shares": 0.25}
SHARED_MAX = 6          # a capability used by more entries than this is too common to relate them
LINK_COVERAGE = 0.5     # a linked entry passes relevance on only when this much of its name or an alias matched
RELATED_ONLY = 2.0      # an entry found only through links needs this multiple of min_relevance
CAST_MIN = 1.5
CONTEXT = "space"


@dataclass(frozen=True)
class RetrievalConfig:
    max_results: int = 6              # entries returned
    max_chars: int = 1200             # size of render()
    max_per_category: int = 2         # variety across whatever categories the packs declare
    shortlist: int = 24               # entries checked with the resolver
    binding_limit: int = 48           # resolver bindings per entry
    min_relevance: float = 1.5        # absolute floor
    duplicate_similarity: float = 0.7 # at or above: semantically repetitive
    include_unknown: bool = True      # unknown entries are kept; False keeps only eligible and feasible
    allowed_ratings: tuple = None     # overrides the NSFW switch when given
    variety: float = None             # overrides the creativity setting's relevance weight (0..1)


@dataclass(frozen=True)
class RetrievalRequest:
    request: str = ""
    summary: str = ""
    must: tuple = ()
    avoid: tuple = ()
    rules: tuple = ()
    fixed: str = ""
    randomized: str = ""
    characters: tuple = ()            # brief characters: {label, gender, custom, pronoun}
    creativity: str = "Balanced"
    style: str = ""
    director: str = ""                # the active director's instructions (text)
    nsfw: bool = False
    cast: tuple = None                # optional explicit resolver cast; replaces inference from characters

    @classmethod
    def from_brief(cls, brief, director="", cast=None):
        """From a confirmed Dataset brief (v9). Raises ValueError when the brief is not one."""
        try:
            settings, data = brief["settings"], brief["input"]
            return cls(request=data["request"], summary=brief["summary"], must=tuple(brief["must"]),
                       avoid=tuple(brief["avoid"]), rules=tuple(data.get("rules", [])), fixed=brief["fixed"],
                       randomized=brief["randomized"], characters=tuple(brief["characters"]),
                       creativity=settings.get("creativity") or "Balanced", style=settings.get("style") or "",
                       director=director or "", nsfw=data.get("nsfw") is True or brief.get("path") == "nsfw_character",
                       cast=tuple(cast) if cast is not None else None)
        except (KeyError, TypeError) as error:
            raise ValueError(f"not a confirmed brief: missing {error}") from None

    def texts(self):
        return [("request", self.request), ("summary", self.summary), *(("must", item) for item in self.must),
                *(("rules", item) for item in self.rules), ("fixed", self.fixed), ("randomized", self.randomized),
                *(("characters", _character_text(item)) for item in self.characters),
                ("director", self.director), ("style", "" if self.style in ("", "Auto") else self.style)]


@dataclass
class RetrievedEntry:
    id: str
    name: str
    category: str
    pack: str
    rating: str
    description: str
    status: str                       # feasible | eligible | unknown (conflicts are never returned)
    relevance: float
    score: float
    why: list                         # relevance explanations
    warnings: list = field(default_factory=list)
    needs: list = field(default_factory=list)      # what the unchosen space or objects must provide
    binding: dict = None              # slot -> character labels of the best binding
    checked_with: list = field(default_factory=list)

    @property
    def note(self):
        return FEASIBLE_NOTE if self.status == "feasible" else ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "category": self.category, "pack": self.pack, "rating": self.rating,
                "description": self.description, "status": self.status, "note": self.note,
                "relevance": round(self.relevance, 4), "score": round(self.score, 4), "why": list(self.why),
                "warnings": list(self.warnings), "needs": list(self.needs), "binding": self.binding,
                "checked_with": list(self.checked_with)}


@dataclass
class Retrieval:
    entries: list
    cast: list                        # [{character, id, body, traits, why}]
    suppressed: list                  # [{id, because}]: relevant but redundant or over a limit
    excluded: list                    # [{id, reason}]: conflict, rating or ruled out by avoid
    warnings: list
    config: RetrievalConfig
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)   # milliseconds; not part of to_dict (not deterministic)

    def to_dict(self):
        return {"entries": [entry.to_dict() for entry in self.entries], "cast": self.cast, "suppressed": self.suppressed,
                "excluded": self.excluded, "warnings": self.warnings, "stats": self.stats}

    def render(self, max_chars=None):
        """A short reference block for a model prompt; "" when nothing was retrieved."""
        if not self.entries:
            return ""
        limit = self.config.max_chars if max_chars is None else max_chars
        lines = ["VOCABULARY (optional reference from installed packs; use only what fits the request and rules. "
                 "\"feasible\" means the declared data supports it for this cast, never that it is proven possible):"]
        for entry in self.entries:
            text = f"- {entry.name}"
            if entry.description:
                text += f": {_clip(entry.description, 160)}"
            detail = entry.status
            if entry.needs:
                detail += "; needs " + "; ".join(entry.needs[:2])
            line = f"{text} ({detail})"
            if len("\n".join([*lines, line])) > limit:
                break
            lines.append(line)
        return "\n".join(lines) if len(lines) > 1 else ""


def _clip(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _character_text(item):
    if not isinstance(item, dict):
        return str(item)
    gender = item.get("gender", "")
    return " ".join(str(part) for part in (item.get("label", ""), "" if gender == "custom" else gender, item.get("custom", "")) if part)


# ---------------------------------------------------------------- the index

class VocabularyIndex:
    """Searchable text and concept links of every entry in a registry. Build once per registry."""

    def __init__(self, registry):
        started = time.perf_counter()
        self.registry = registry
        categories = registry.categories() if registry is not None else {}
        ids = sorted(registry.ids()) if registry is not None else []
        self.resolved = {entry_id: registry.resolved(entry_id) for entry_id in ids}
        documents = []
        for entry_id in ids:
            entry = self.resolved[entry_id]
            category = categories.get(entry["category"], {})
            fields = {"name": terms(entry["name"]), "alias": [t for alias in entry.get("aliases", []) for t in terms(alias)],
                      "tag": [t for tag in entry.get("tags", []) for t in terms(tag.replace("_", " "))],
                      "category": terms(f"{entry['category'].replace('_', ' ')} {category.get('name', '')}"),
                      "description": terms(entry.get("description", "")),
                      "notes": [t for note in entry.get("notes", []) for t in terms(note)]}
            phrases = [(entry["name"], "name", tuple(terms(entry["name"])))]
            phrases += [(alias, "alias", tuple(terms(alias))) for alias in entry.get("aliases", [])]
            documents.append(Document(entry_id, fields, [phrase for phrase in phrases if phrase[2]]))
        self.text = TextIndex(documents, FIELD_WEIGHTS)
        self.kind = {entry_id: _kind(self.resolved[entry_id]["components"]) for entry_id in ids}
        self._links(ids)
        self.features = {entry_id: self._features(entry_id) for entry_id in ids}
        self.build_ms = (time.perf_counter() - started) * 1000

    def _links(self, ids):
        raw_parents = {entry_id: list(self.registry.entry(entry_id).get("extends", [])) for entry_id in ids}
        self.ancestors = {}
        for entry_id in ids:
            seen, stack = [], list(raw_parents[entry_id])
            while stack:
                parent = stack.pop(0)
                if parent not in seen:
                    seen.append(parent)
                    stack.extend(raw_parents.get(parent, []))
            self.ancestors[entry_id] = seen
        self.uses = {}
        for entry_id in ids:
            comp = self.resolved[entry_id]["components"]
            refs = list(_capability_refs(comp))
            refs += [placement["posture"] for placement in comp.get("spatial", {}).get("participants", {}).values() if "posture" in placement]
            self.uses[entry_id] = sorted(set(ref for ref in refs if ref in self.resolved and ref != entry_id))
        broader = {entry_id: sorted(implied(self.registry, [entry_id]) - {entry_id}) for entry_id in ids if self.kind[entry_id] == "concept"}
        narrower = {}
        for entry_id, wider in broader.items():
            for other in wider:
                narrower.setdefault(other, []).append(entry_id)
        self.neighbours = {entry_id: [] for entry_id in ids}
        for entry_id in ids:
            links = self.neighbours[entry_id]
            for ref in self.uses[entry_id]:
                links.append((ref, "uses"))
                self.neighbours.setdefault(ref, []).append((entry_id, "used by"))
                links += [(other, "broader") for other in broader.get(ref, [])]
                links += [(other, "narrower") for other in sorted(narrower.get(ref, []))]
            for parent in self.ancestors[entry_id]:
                links.append((parent, "parent"))
                self.neighbours[parent].append((entry_id, "child"))
        users = {}
        for entry_id in ids:
            if self.kind[entry_id] not in ("concept", "body"):
                for ref in self.uses[entry_id]:
                    if self.kind.get(ref) == "concept":
                        users.setdefault(ref, []).append(entry_id)
        for ref, group in sorted(users.items()):
            if 1 < len(group) <= SHARED_MAX:
                for entry_id in group:
                    self.neighbours[entry_id] += [(other, "shares") for other in group if other != entry_id]
        for entry_id in ids:
            self.neighbours[entry_id] = sorted(set(self.neighbours[entry_id]))

    def _features(self, entry_id):
        entry = self.resolved[entry_id]
        words = terms(" ".join([entry["name"], *entry.get("aliases", []), entry.get("description", "")]))
        return frozenset(words) | {f"@{ref}" for ref in self.uses[entry_id]}


def _kind(comp):
    """What an entry is, from its components only (never its category)."""
    if any(spec["kind"] == "being" for spec in comp.get("participants", {}).get("slots", {}).values()):
        return "bindable"
    if comp.get("participants", {}).get("slots"):
        return "bindable"
    if "body" in comp:
        return "body"
    if "object" in comp:
        return "item"
    if "environment" in comp:
        return "space"
    uses_self = ("self" in comp.get("requirements", {}).get("participants", {}) or "self" in comp.get("claims", {})
                 or "self" in comp.get("spatial", {}).get("participants", {}))
    if uses_self:
        return "self"
    if set(comp) <= {"capability"}:
        return "concept"
    return "standalone"


# ---------------------------------------------------------------- one retrieval

def retrieve(source, request, config=None):
    """Retrieve vocabulary for one request. source: a VocabularyIndex, a Registry, or None (no packs)."""
    config = config or RetrievalConfig()
    if source is None or isinstance(source, VocabularyIndex):
        index = source
    else:
        index = VocabularyIndex(source)
    return _Retrieval(index, request, config).run()


class _Retrieval:
    def __init__(self, index, request, config):
        self.index, self.request, self.config = index, request, config
        self.registry = index.registry if index else None
        self.allowed = set(config.allowed_ratings or (RATINGS if request.nsfw else ("general", "mature")))
        self.relevance_weight, self.floor = CREATIVITY.get(request.creativity, CREATIVITY["Balanced"])
        if config.variety is not None:
            self.relevance_weight = config.variety
        self.excluded, self.suppressed, self.warnings, self.timings = [], [], [], {}
        self.matched = {}

    def run(self):
        started = time.perf_counter()
        if not self.index or not self.index.resolved:
            return self.result([], [], "no vocabulary packs are enabled", started)
        self.query, self.sequences, self.negated = self.build_query()
        if not self.query:
            return self.result([], [], "the request has no searchable words", started)
        self.cast, cast_report = self.infer_cast()
        relevant = self.relevance()
        self.timings["relevance_ms"] = (time.perf_counter() - started) * 1000
        if not relevant:
            return self.result([], cast_report, "no relevant vocabulary for this request", started)
        checked = self.compatibility(relevant)
        self.timings["compatibility_ms"] = (time.perf_counter() - started) * 1000 - self.timings["relevance_ms"]
        selected = self.select(checked)
        return self.result(selected, cast_report, None if selected else "no compatible vocabulary for this request", started)

    def result(self, entries, cast_report, empty_warning, started):
        if empty_warning:
            self.warnings.append(empty_warning)
        self.timings["total_ms"] = (time.perf_counter() - started) * 1000
        stats = {"indexed": len(self.index.resolved) if self.index else 0, "returned": len(entries),
                 "suppressed": len(self.suppressed), "excluded": len(self.excluded)}
        return Retrieval(entries, cast_report, self.suppressed, self.excluded, self.warnings, self.config, stats, self.timings)

    # -- the query
    def build_query(self):
        query, sequences, negated = {}, [], {}
        for source, text in self.request.texts():
            if not text:
                continue
            weight = SOURCE_WEIGHTS[source]
            positive, negative = split_negated(text)
            positive = [term for term in positive if not term.isdigit()]
            for term in positive:
                if weight > query.get(term, (0, ""))[0]:
                    query[term] = (weight, source)
            for term in [] if source in STANDING else negative:
                negated.setdefault(term, source)
            if positive:
                sequences.append((source, weight, positive))
        for item in self.request.avoid:
            positive, negative = split_negated(item)
            for term in [*positive, *negative]:
                negated.setdefault(term, "avoid")
        for term in negated:
            query.pop(term, None)  # a word the request rules out never counts for an entry
        return query, sequences, negated

    def allowed_entry(self, entry_id):
        return self.index.resolved[entry_id].get("rating", "general") in self.allowed

    # -- direct and related relevance
    def direct(self, entry_id, query=None, sequences=None, exact=False):
        score, matches = self.index.text.score(entry_id, self.query if query is None else query, exact=exact)
        hits = self.index.text.phrase_hits(entry_id, self.sequences if sequences is None else sequences)
        seen, why = set(), []
        for label, name, source, value, contiguous in hits:
            if label not in seen:
                seen.add(label)
                score += value
                why.append((value, f'{name} "{label}" {"in" if contiguous else "matches"} the {source}'))
        self.matched[entry_id] = {other for _, other, name, _, _ in matches if name in STRONG_FIELDS}
        loose = {other for _, other, name, _, _ in matches if name not in STRONG_FIELDS}
        if not hits and not self.matched[entry_id] and len(loose) < 2:
            return 0.0, []  # one shared word in a description is not meaning
        for term, other, name, source, value in matches:
            where = "name" if name in STRONG_FIELDS else name
            shown = term if term == other else f"{term} ~ {other}"
            why.append((value, f'{where} matches "{shown}" ({source})'))
        why.sort(key=lambda item: -item[0])
        return score, why

    def relevance(self):
        index = self.index
        allowed = [entry_id for entry_id in sorted(index.resolved) if self.allowed_entry(entry_id)]
        for entry_id in sorted(index.resolved):
            if entry_id not in allowed and index.kind[entry_id] not in ("concept", "body"):
                if self.direct(entry_id)[0] >= self.config.min_relevance:
                    self.excluded.append({"id": entry_id, "reason": f"rating {index.resolved[entry_id].get('rating')} is not allowed"})
        direct, linkable = {}, set()
        for entry_id in allowed:
            if index.kind[entry_id] == "body":
                continue  # bodies describe the cast; they never make scene entries relevant
            direct[entry_id] = self.direct(entry_id)
            if self.coverage(entry_id) >= LINK_COVERAGE:
                linkable.add(entry_id)
        negative = {term: (1.0, source) for term, source in self.negated.items()}
        scored = {}
        for entry_id in allowed:
            if index.kind[entry_id] in ("concept", "body"):
                continue
            score, why = direct[entry_id]
            related = []
            for other, link in index.neighbours[entry_id]:
                if other in linkable and direct[other][0] > 0 and other != entry_id:
                    related.append((LINKS[link] * direct[other][0], other, link))
            related.sort(key=lambda item: (-item[0], item[1], item[2]))
            if score <= 0 and (not related or related[0][0] < RELATED_ONLY * self.config.min_relevance):
                continue
            if related:
                value, other, link = related[0]
                score += value + 0.25 * sum(item[0] for item in related[1:3])
                reason = direct[other][1][0][1] if direct[other][1] else ""
                why.append((value, f"related: {link} {index.resolved[other]['name']} ({reason})"))
            if score <= 0:
                continue
            if negative:
                # Exact normalized words only: what the request rules out never reaches entries through
                # spelling variants or compounds ("no hands" keeps the handbag).
                against, against_why = self.direct(entry_id, negative, [(source, 1.0, [term]) for term, source in self.negated.items()],
                                                   exact=True)
                strong = [text for _, text in against_why if text.startswith(("name", "alias"))]
                if strong:
                    self.excluded.append({"id": entry_id, "reason": f"ruled out by the request: {strong[0]}"})
                    continue
                if against > 0:
                    score *= 0.5
                    why.append((0, "partly matches what the request rules out (lowered)"))
            why.sort(key=lambda item: -item[0])
            scored[entry_id] = (score, [text for _, text in why[:3]])
        if not scored:
            return []
        top = max(score for score, _ in scored.values())
        floor = max(self.config.min_relevance, self.floor * top)
        relevant = sorted(((score, entry_id, why) for entry_id, (score, why) in scored.items() if score >= floor),
                          key=lambda item: (-item[0], item[1]))
        return relevant

    def coverage(self, entry_id):
        """The largest share of one name or alias of the entry that the query matched."""
        matched = self.matched.get(entry_id, set())
        phrases = [set(phrase) for _, _, phrase in self.index.text.documents[entry_id].phrases]
        return max((len(phrase & matched) / len(phrase) for phrase in phrases if phrase), default=0)

    # -- the cast
    def infer_cast(self):
        if self.request.cast is not None:
            cast = [dict(member) for member in self.request.cast]
            self.labels = {member["id"]: member["id"] for member in cast}
            return cast, [{"character": member["id"], "id": member["id"], "body": member.get("body"),
                           "traits": list(member.get("traits", [])), "why": "given"} for member in cast]
        bodies = [entry_id for entry_id in sorted(self.index.resolved)
                  if self.index.kind[entry_id] == "body" and self.allowed_entry(entry_id)]
        cast, report, self.labels = [], [], {}
        for number, character in enumerate(self.request.characters, start=1):
            text = _character_text(character)
            label = character.get("label") if isinstance(character, dict) else None
            label = label or f"character {number}"
            positive, _ = split_negated(text)
            query = {term: (1.0, "character") for term in positive if not term.isdigit()}
            matches = []
            for entry_id in bodies:
                score, why = self.direct(entry_id, query, [("character", 1.0, positive)])
                strong = [text for _, text in why if text.startswith(("name", "alias", "tag"))]
                if score >= CAST_MIN and strong:  # names, aliases and tags only: descriptions are too loose for a cast
                    size = len(self.index.resolved[entry_id]["components"]["body"].get("resources", {}))
                    matches.append((score, entry_id, strong[0], size))
            # The body is the largest matching body plan; the other matches are traits added to it.
            matches.sort(key=lambda item: (-item[3], -item[0], item[1]))
            ident = f"c{number}"
            self.labels[ident] = label
            member = {"id": ident, "body": matches[0][1] if matches else None, "traits": [item[1] for item in matches[1:]]}
            cast.append(member)
            report.append({"character": label, "id": ident, "body": member["body"], "traits": member["traits"],
                           "why": "; ".join(f"{item[1]}: {item[2]}" for item in matches) or
                                  "no vocabulary body matches; its capabilities are undeclared (unknown)"})
            if not matches:
                self.warnings.append(f"{label}: no vocabulary body matches, so compatibility involving them is unknown")
        return cast, report

    # -- compatibility (Phase 3 resolver)
    def compatibility(self, relevant):
        shortlist = relevant[:self.config.shortlist]
        for score, entry_id, why in relevant[self.config.shortlist:]:
            self.suppressed.append({"id": entry_id, "because": f"beyond the shortlist of {self.config.shortlist}"})
        checked, bindables = [], []
        for score, entry_id, why in shortlist:
            kind = self.index.kind[entry_id]
            if kind == "bindable":
                verdict = self.check_bindable(entry_id)
                bindables.append((entry_id, verdict))
            elif kind == "self":
                verdict = self.check_self(entry_id)
            else:
                verdict = None
            checked.append([score, entry_id, why, verdict])
        usable = [entry_id for entry_id, verdict in bindables if verdict["status"] != "conflict"]
        for item in checked:
            if item[3] is None:
                kind = self.index.kind[item[1]]
                item[3] = (self.check_item(item[1], usable) if kind == "item" else
                           self.check_space(item[1], usable) if kind == "space" else
                           {"status": "unknown", "warnings": ["checked only when a position or action uses it"]})
        result = []
        for score, entry_id, why, verdict in checked:
            status = verdict["status"]
            if status == "conflict":
                reasons = [self.humanize(reason) for reason in verdict.get("reasons", [])[:2]]
                self.excluded.append({"id": entry_id, "reason": "conflict: " + "; ".join(reasons)})
                continue
            if status == "unknown" and not self.config.include_unknown:
                self.excluded.append({"id": entry_id, "reason": "unknown (include_unknown is off)"})
                continue
            result.append((score * STATUS_FACTOR[status], score, entry_id, why, verdict))
        result.sort(key=lambda item: (-item[0], item[2]))
        return result

    def placeholders(self, slots, skip=None):
        objects, names = [], {}
        for name in sorted(slots):
            spec = slots[name]
            low = spec["count"]["min"] if isinstance(spec["count"], dict) else spec["count"]
            if spec["kind"] == "object" and name != skip:
                for number in range(1, low + 1):
                    ident = f"_{name}{number}"
                    objects.append({"id": ident, "item": None})
                    names[ident] = name
        return objects, names

    def view(self, resolution, context):
        """The resolver's verdict about the cast, with unchosen space and objects split off as needs."""
        kept, needs = [], []
        for finding in resolution.findings:
            if finding.status == "unknown" and finding.participants and set(finding.participants) <= set(context):
                capabilities = [entry for entry in finding.entries if self.index.kind.get(entry) == "concept"]
                who = "a space" if finding.participants == (CONTEXT,) else _article(context[finding.participants[0]])
                for capability in capabilities[:1]:
                    needs.append(f"{who} with: {self.index.resolved[capability]['name'].lower()}")
            else:
                kept.append(finding)
        status = max((finding.status for finding in kept), key=RANK.get, default="feasible")
        return status, kept, sorted(set(needs))

    def best(self, entry_id, objects, names, space=None, require=None):
        found = candidate_bindings(self.registry, entry_id, self.cast, objects=objects, space=space,
                                   limit=self.config.binding_limit)
        context = {**names, **({} if space else {CONTEXT: CONTEXT})}
        options = []
        for order, (bind, resolution) in enumerate(found):
            bound = {ident for value in bind.values() for ident in (value if isinstance(value, list) else [value])}
            if require and require not in bound:
                continue
            status, kept, needs = self.view(resolution, context)
            options.append((RANK[status], len(kept), order, bind, status, kept, needs))
        options.sort(key=lambda item: item[:3])
        return found, options

    def check_bindable(self, entry_id):
        slots = self.index.resolved[entry_id]["components"]["participants"]["slots"]
        objects, names = self.placeholders(slots)
        found, options = self.best(entry_id, objects, names)
        if not options:
            sizes = ", ".join(f"{name}: {spec['count']}" for name, spec in sorted(slots.items()) if spec["kind"] == "being")
            reason = f"no way to bind the cast of {len(self.cast)} to {sizes}"
            if found.truncated:
                return {"status": "unknown", "warnings": [found.note], "reasons": [reason]}
            return {"status": "conflict", "reasons": [reason]}
        _, _, _, bind, status, kept, needs = options[0]
        warnings = []
        if status == "conflict" and found.viable is None:
            status, warnings = "unknown", [found.note]
        reasons = [finding.message for finding in kept if finding.status == status][:3]
        binding = {slot: [self.labels.get(ident, ident) for ident in (value if isinstance(value, list) else [value])]
                   for slot, value in sorted(bind.items()) if not (isinstance(value, str) and value in names)
                   and not (isinstance(value, list) and set(value) <= set(names))}
        if status == "unknown":
            warnings += [finding.message for finding in kept if finding.status == "unknown"][:2]
        return {"status": status, "reasons": reasons, "warnings": warnings, "needs": needs, "binding": binding}

    def check_self(self, entry_id):
        """An entry about one participant ("self"), such as a posture, against each cast member."""
        if not self.cast:
            return {"status": "conflict", "reasons": ["the scene has no characters to take it"]}
        options = []
        for member in self.cast:
            run = _Run(self.registry, {"cast": self.cast})
            run.place(member["id"], {"posture": entry_id}, {}, entry_id)
            run.allocate()
            status = max((finding.status for finding in run.findings), key=RANK.get, default="feasible")
            options.append((RANK[status], member["id"], status, run.findings))
        options.sort(key=lambda item: item[:2])
        _, ident, status, findings = options[0]
        return {"status": status, "reasons": [finding.message for finding in findings][:2],
                "warnings": [finding.message for finding in findings if finding.status == "unknown"][:2],
                "binding": {"self": [self.labels.get(ident, ident)]}}

    def pair(self, entry_id, partners, build):
        """Best verdict of a context entry (an item or a space) combined with compatible bindables."""
        verdicts, checked_with = [], []
        for partner in partners:
            objects, names, space, require = build(partner)
            if objects is None:
                continue
            found, options = self.best(partner, objects, names, space=space, require=require)
            if options:
                checked_with.append(partner)
                _, _, _, _, status, kept, needs = options[0]
                if status == "conflict" and found.viable is None:
                    status = "unknown"
                verdicts.append((RANK[status], partner, status, kept, needs))
        if not verdicts:
            return {"status": "unknown", "warnings": ["no retrieved position or action uses it, so it is not checked"]}
        verdicts.sort(key=lambda item: item[:2])
        _, partner, status, kept, needs = verdicts[0]
        return {"status": status, "checked_with": sorted(checked_with), "needs": needs,
                "reasons": [f"with {partner}: {finding.message}" for finding in kept if finding.status == status][:2],
                "warnings": [f"with {partner}: {finding.message}" for finding in kept if finding.status == "unknown"][:2]}

    def check_item(self, entry_id, partners):
        def build(partner):
            slots = self.index.resolved[partner]["components"]["participants"]["slots"]
            object_slots = [name for name, spec in sorted(slots.items()) if spec["kind"] == "object"]
            if not object_slots:
                return None, None, None, None
            objects, names = self.placeholders(slots, skip=object_slots[0])
            return [{"id": "_candidate", "item": entry_id}, *objects], names, None, "_candidate"
        return self.pair(entry_id, partners, build)

    def check_space(self, entry_id, partners):
        def build(partner):
            if not self.index.resolved[partner]["components"].get("requirements", {}).get("space"):
                return None, None, None, None
            objects, names = self.placeholders(self.index.resolved[partner]["components"]["participants"]["slots"])
            return objects, names, entry_id, None
        return self.pair(entry_id, partners, build)

    # -- ranking with variety
    def inheritance(self, checked):
        """Settle an entry and a descendant that are both relevant, before ranking.

        The descendant replaces its ancestor when it matches more of the request: every request term the
        ancestor matched and at least one more, unless the request also names the ancestor on its own ("a polite
        bow and a deep bow" keeps both). Otherwise a descendant that declares the same components is an
        equivalent and is dropped. A descendant that declares more is never dropped because its ancestor stays;
        when it matches nothing beyond its ancestor, the ancestor ranks first ("a bow": Bow, then Deep bow).
        """
        ids = [item[2] for item in checked]
        matched = {entry_id: {match[0] for match in self.index.text.score(entry_id, self.query)[1]} for entry_id in ids}
        dropped, self.after = {}, {}
        for child in ids:
            for parent in self.index.ancestors[child]:
                if parent not in matched or child in dropped or parent in dropped:
                    continue
                same = self.index.resolved[child]["components"] == self.index.resolved[parent]["components"]
                more = matched[child] > matched[parent]
                if more and same:
                    dropped[parent] = f"inherited duplicate of {child}, which matches more of the request"
                elif more and not self.named_apart(parent, child):
                    dropped[parent] = f"covered by its more specific {child}, which matches more of the request"
                elif same:
                    dropped[child] = f"inherited duplicate of {parent} (declares nothing more)"
                elif not more:
                    self.after.setdefault(child, set()).add(parent)
        self.suppressed += [{"id": entry_id, "because": dropped[entry_id]} for entry_id in sorted(dropped)]
        return [item for item in checked if item[2] not in dropped]

    def named_apart(self, parent, child):
        """Whether the request names the parent (its name or an alias) outside the child's own names and aliases."""
        phrases = self.index.text.documents
        own = [phrase for _, _, phrase in phrases[parent].phrases]
        inside = [phrase for _, _, phrase in phrases[child].phrases if phrase not in own]
        for _, _, sequence in self.sequences:
            def at(phrase):
                return [index for index in range(len(sequence) - len(phrase) + 1) if tuple(sequence[index:index + len(phrase)]) == phrase]
            covered = {index + offset for phrase in inside for index in at(phrase) for offset in range(len(phrase))}
            if any(not set(range(index, index + len(phrase))) <= covered for phrase in own for index in at(phrase)):
                return True
        return False

    def select(self, checked):
        checked = self.inheritance(checked)
        if not checked:
            return []
        top = checked[0][0]
        pool, selected, per_category = list(checked), [], {}
        while pool and len(selected) < self.config.max_results:
            def value(item):
                similar = max((_jaccard(self.index.features[item[2]], self.index.features[chosen[2]]) for chosen in selected), default=0)
                return self.relevance_weight * item[0] / top - (1 - self.relevance_weight) * similar
            pool.sort(key=lambda item: (-value(item), item[2]))
            waiting = {item[2] for item in pool}  # a descendant waits for an ancestor that matches as much
            item = pool.pop(next(number for number, item in enumerate(pool) if not self.after.get(item[2], set()) & waiting))
            entry_id = item[2]
            category = self.index.resolved[entry_id]["category"]
            similar = max(((_jaccard(self.index.features[entry_id], self.index.features[chosen[2]]), chosen[2]) for chosen in selected),
                          default=(0, None))
            if similar[0] >= self.config.duplicate_similarity:
                self.suppressed.append({"id": entry_id, "because": f"repeats {similar[1]} (similarity {similar[0]:.2f})"})
                continue
            if per_category.get(category, 0) >= self.config.max_per_category:
                self.suppressed.append({"id": entry_id, "because": f"category {category} already has {self.config.max_per_category}"})
                continue
            per_category[category] = per_category.get(category, 0) + 1
            selected.append(item)
        return [self.entry(item) for item in selected]

    def humanize(self, text):
        """Cast ids and placeholder objects in resolver messages, as the brief names them."""
        text = re.sub(r"\b_([a-z][a-z0-9_]*?)\d+\b", lambda match: f"the {match[1]}", text)
        text = re.sub(r"\b_candidate\b", "this item", text)
        return re.sub(r"\bc\d+\b", lambda match: self.labels.get(match[0], match[0]), text)

    def entry(self, item):
        adjusted, score, entry_id, why, verdict = item
        resolved = self.index.resolved[entry_id]
        verdict = {**verdict, "warnings": [self.humanize(text) for text in verdict.get("warnings", [])]}
        return RetrievedEntry(
            id=entry_id, name=resolved["name"], category=resolved["category"], pack=self.registry.owner(entry_id),
            rating=resolved.get("rating", "general"), description=resolved.get("description", ""), status=verdict["status"],
            relevance=score, score=adjusted, why=why, warnings=list(dict.fromkeys(verdict.get("warnings", []))),
            needs=verdict.get("needs", []), binding=verdict.get("binding"), checked_with=verdict.get("checked_with", []))


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a or b else 0.0


def _article(noun):
    return f"{'an' if noun[:1] in 'aeiou' else 'a'} {noun}"
