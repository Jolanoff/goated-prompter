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
  inspiration entries the request does not name, from the categories the brief opens: the brief's own
              words reach a category through its declared name and description (often the randomized
              dimensions: "sex positions, location"), a pack through its declared name and description or
              an entry it names or casts (the mandatory core has no theme; a rating word is no theme), and
              a brief with people leaves its arrangement (positions for exactly this cast) and its place
              open unless it fixes them. The content level (an NSFW brief's top rating) only ranks; it
              opens nothing, so acts and accessories need the brief's words or a theme. Director and style
              texts never open anything. What the request fixes stays fixed: naming a position, action or
              posture fixes the interaction, naming a space or an item fixes that, and so does a place in
              words the vocabulary does not know ("on a train platform"); the randomized text re-opens a
              category. What the request rules out takes along what depends on it (dependencies()).
              Items need an interaction in the pool that they serve. Every idea passes the same rating,
              avoid and resolver checks; each scene gets its own ideas by a seeded, score-weighted rotation
              across the open categories (Retrieval.ideas).

The engine never branches on category names: what an entry is comes from its components.
"""

from dataclasses import dataclass, field
import random
import re
import time

from .packs import _capability_refs
from .resolver import FEASIBLE_NOTE, RANK, _Run, candidate_bindings, implied
from .semantic import Document, TextIndex, place_phrases, split_negated, terms

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
# Step 1 (Understanding) gives each character gender "male" or "female" for a human man or woman, and
# "custom" (with a description) for anything else. Only the first two establish a human.
HUMAN_GENDERS = ("male", "female")
CONTEXT = "space"
# Inspiration. Intent comes from the brief's own texts only; the ones that state a choice can also fix it.
INTENT_SOURCES = ("request", "summary", "must", "rules", "fixed", "randomized")
CHOICE_SOURCES = ("request", "summary", "must", "rules", "fixed")
OPENING_SOURCE = "randomized"
SCENE_KINDS = ("bindable", "self", "item", "space")
INTERACTION_KINDS = ("bindable", "self")
# Creativity setting -> (ideas per scene, pool floor relative to the best idea of a category).
INSPIRATION = {"Strict": (2, 0.8), "Balanced": (3, 0.6), "Creative": (3, 0.4), "Dice": (4, 0.25)}
DECLARED = ("feasible", "eligible")  # an item is offered with a partner whose requirements it declares it meets
# What reached an idea, as weight. A theme says the same as the content level when both hold, so it adds nothing then.
SCOPE_WEIGHTS = {"category": 1.0, "theme": 0.75, "content": 1.0}
# What opens a category. The content level (the rating an NSFW brief allows) never opens anything on its own: it
# only ranks what the brief's own words, its theme or the scene's open dimensions opened.
OPENING = ("category", "arrangement", "setting", "theme")
DIMENSIONS = ("category", "arrangement", "setting")  # the same signal, an open dimension: counted once
IDEA_HEADER = ("VOCABULARY (optional inspiration from installed packs: use, adapt or ignore. The request, fixed, must, "
               "avoid and rules always come first; an idea never replaces what the brief fixes. \"feasible\" means the "
               "declared data supports it for this cast, never that it is proven possible):")


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
    inspiration: bool = True          # ideas from the categories the brief opens (False: named entries only)
    inspiration_shortlist: int = 24   # candidates per category checked with the resolver
    inspiration_pool: int = 12        # ideas kept per category for rotation


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
    seed: int = 0                     # rotation of ideas across scenes

    @classmethod
    def from_brief(cls, brief, director="", cast=None):
        """From a confirmed Dataset brief (v9). Raises ValueError when the brief is not one."""
        try:
            settings, data = brief["settings"], brief["input"]
            seed = data.get("seed", 0)
            return cls(request=data["request"], summary=brief["summary"], must=tuple(brief["must"]),
                       avoid=tuple(brief["avoid"]), rules=tuple(data.get("rules", [])), fixed=brief["fixed"],
                       randomized=brief["randomized"], characters=tuple(brief["characters"]),
                       creativity=settings.get("creativity") or "Balanced", style=settings.get("style") or "",
                       director=director or "", nsfw=data.get("nsfw") is True or brief.get("path") == "nsfw_character",
                       cast=tuple(cast) if cast is not None else None,
                       seed=seed if type(seed) is int else 0)
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
    source: str = "direct"            # direct: the request names it; inspiration: a category the brief opens
    scopes: list = field(default_factory=list)     # inspiration: what reached it (category, theme, content)
    attach_to: list = field(default_factory=list)  # inspiration items: the interactions it serves; offered only with one

    @property
    def note(self):
        return FEASIBLE_NOTE if self.status == "feasible" else ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "category": self.category, "pack": self.pack, "rating": self.rating,
                "description": self.description, "status": self.status, "note": self.note,
                "relevance": round(self.relevance, 4), "score": round(self.score, 4), "why": list(self.why),
                "warnings": list(self.warnings), "needs": list(self.needs), "binding": self.binding,
                "checked_with": list(self.checked_with), "source": self.source, "scopes": list(self.scopes),
                "attach_to": list(self.attach_to)}

    def line(self, limit=160):
        text = f"- {self.name}"
        if self.description:
            text += f": {_clip(self.description, limit)}"
        detail = self.status
        if self.needs:
            detail += "; needs " + "; ".join(self.needs[:2])
        return f"{text} ({detail})"


@dataclass
class Retrieval:
    entries: list                     # what the request names, best first (every scene)
    cast: list                        # [{character, id, body, traits, why}]
    suppressed: list                  # [{id, because}]: relevant but redundant or over a limit
    excluded: list                    # [{id, reason}]: conflict, rating or ruled out by avoid
    warnings: list
    config: RetrievalConfig
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)   # milliseconds; not part of to_dict (not deterministic)
    pools: list = field(default_factory=list)     # [(category, [RetrievedEntry])]: ideas per open category, best first
    intent: dict = field(default_factory=dict)    # what the brief opened, fixed or left out, and why
    seed: int = 0
    per_scene: int = 0                # ideas offered to one scene

    @property
    def inspiration(self):
        return [entry for _, pool in self.pools for entry in pool]

    def to_dict(self):
        return {"entries": [entry.to_dict() for entry in self.entries], "cast": self.cast, "suppressed": self.suppressed,
                "excluded": self.excluded, "warnings": self.warnings, "stats": self.stats,
                "inspiration": [entry.to_dict() for entry in self.inspiration], "intent": self.intent}

    def render(self, max_chars=None):
        """A short reference block for a model prompt; "" when nothing was retrieved."""
        if not self.entries:
            return ""
        limit = self.config.max_chars if max_chars is None else max_chars
        lines = ["VOCABULARY (optional reference from installed packs; use only what fits the request and rules. "
                 "\"feasible\" means the declared data supports it for this cast, never that it is proven possible):"]
        for entry in self.entries:
            line = entry.line()
            if len("\n".join([*lines, line])) > limit:
                break
            lines.append(line)
        return "\n".join(lines) if len(lines) > 1 else ""

    # -- rotation of ideas across scenes
    def _orders(self, seed):
        """Each pool in a seeded order that favours higher scores (weighted sampling without replacement)."""
        orders = []
        for category, pool in self.pools:
            rng = random.Random(f"{seed}:{category}")
            keys = [rng.random() ** (1.0 / max(entry.score, 1e-6)) for entry in pool]
            orders.append([entry for _, entry in sorted(zip(keys, pool), key=lambda item: (-item[0], item[1].id))])
        return orders

    def ideas(self, number, seed=None):
        """The ideas for scene number (1-based): one per open category in turn, the starting category moving with
        the scene, and each category walking through its own seeded order, so a dataset sees all of them. An item
        comes along only with an interaction it serves in the same scene (a named one or an idea), at most one."""
        if number < 1:
            return []
        return self._plan(number, self.seed if seed is None else seed)[number - 1]

    def _plan(self, count, seed):
        """The ideas of scenes 1..count in one pass (kept per seed, extended when a later scene is asked for)."""
        memo = self.__dict__.setdefault("_plans", {})
        if len(memo.get(seed, [])) >= count:
            return memo[seed]
        orders = self._orders(seed)
        main = [order for order in ([entry for entry in order if not entry.attach_to] for order in orders) if order]
        attached = [order for order in ([entry for entry in order if entry.attach_to] for order in orders) if order]
        if self.per_scene < 1 or not (main or attached):
            memo[seed] = [[] for _ in range(count)]
            return memo[seed]
        want = min(self.per_scene, sum(len(order) for order in main))
        visits, extra, plan = [0] * len(main), [0] * len(attached), []
        named = {entry.id for entry in self.entries}
        for scene in range(1, count + 1):
            picked, step = [], 0
            while len(picked) < want:
                category = (scene - 1 + step) % len(main)
                step += 1
                order = main[category]
                for _ in range(len(order)):  # the category's next idea this scene does not have yet
                    entry = order[visits[category] % len(order)]
                    visits[category] += 1
                    if entry not in picked:
                        picked.append(entry)
                        break
            for category, order in enumerate(main):
                if len(order) > 1 and all(entry in picked for entry in order):
                    visits[category] += 1  # a pool a scene uses whole starts one later next time
            anchors = named | {entry.id for entry in picked}
            for step in range(len(attached)):
                category = (scene - 1 + step) % len(attached)
                order = attached[category]
                found = next((offset for offset in range(len(order))
                              if set(order[(extra[category] + offset) % len(order)].attach_to) & anchors), None)
                if found is not None:
                    picked.append(order[(extra[category] + found) % len(order)])
                    extra[category] += found + 1
                    break
            plan.append(picked)
        memo[seed] = plan
        return plan

    def scenes(self, count, seed=None):
        """[{scene, entries, ideas}] for scenes 1..count: what each would be offered (ids)."""
        named = [entry.id for entry in self.entries]
        plan = self._plan(count, self.seed if seed is None else seed) if count > 0 else []
        return [{"scene": number, "entries": named, "ideas": [entry.id for entry in plan[number - 1]]}
                for number in range(1, count + 1)]

    def offer(self, numbers, seed=None):
        """(block, ids) for one model request that writes the given scenes (1-based, in order).

        The named entries stand for every scene; the ideas are listed per concept of this request and described
        once. Without ideas the block is exactly render()."""
        numbers = list(numbers)
        plan = self._plan(max(numbers, default=0), self.seed if seed is None else seed) if numbers else []
        per = [(number, plan[number - 1] if number >= 1 else []) for number in numbers]
        if not any(ideas for _, ideas in per):
            block = self.render()
            return block, [entry.id for entry, _ in zip(self.entries, block.splitlines()[1:])]
        lines, ids = [IDEA_HEADER], []
        if self.entries:
            lines.append("Named by the request (every image):")
            for entry in self.entries:
                lines.append(entry.line())
                ids.append(entry.id)
        lines.append("Ideas per concept, in the order of this request (optional; a concept may use others or none):")
        described = []
        for position, (_, ideas) in enumerate(per, 1):
            lines.append(f"- concept {position}: " + ("; ".join(entry.name for entry in ideas) or "(none)"))
            described += [entry for entry in ideas if entry not in described]
        lines.append("Ideas described:")
        budget = len("\n".join(lines)) + self.config.max_chars
        for entry in described:
            line = entry.line(120)
            if len("\n".join([*lines, line])) > budget:
                line = f"- {entry.name} ({entry.status})"
            lines.append(line)
            ids.append(entry.id)
        return "\n".join(lines), list(dict.fromkeys(ids))


def _clip(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def _body_text(item):
    """What a brief character says about its body: its label and custom description, never its gender."""
    if not isinstance(item, dict):
        return str(item)
    return " ".join(str(part) for part in (item.get("label", ""), item.get("custom", "")) if part)


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
        # What a brief's own words can reach for inspiration: the declared categories of scene entries, and the
        # theme of every pack except the mandatory core (the shared base, not a theme).
        # Every declared category takes part, so a word shared with a non-scene category ("body") is not distinctive.
        self.scene_categories = sorted({self.resolved[entry_id]["category"] for entry_id in ids if self.kind[entry_id] in SCENE_KINDS})
        every = sorted(set(self.scene_categories) | set(categories))
        self.category_labels = _Labels([(key, f"{categories.get(key, {}).get('name', '')} {key.replace('_', ' ')}",
                                         categories.get(key, {}).get("name", key.replace("_", " ").capitalize()),
                                         categories.get(key, {}).get("description", "")) for key in every], description_terms=1)
        packs = getattr(registry, "packs", None) or {}
        # A theme word is one only this pack's own name or description uses: the core's description and every
        # category's name and description are the shared background ("places", "positions", "bodies").
        background = [pack.manifest.get("description", "") for pack in packs.values() if getattr(pack, "mandatory", False)]
        background += [f"{item.get('name', '')} {item.get('description', '')}" for item in categories.values()]
        self.theme_labels = _Labels([(pack_id, pack.manifest.get("name", pack_id), pack.manifest.get("name", pack_id),
                                      pack.manifest.get("description", "")) for pack_id, pack in sorted(packs.items())
                                     if not getattr(pack, "mandatory", False)], description_terms=1, background=background)
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
                    # An item or space and what uses what it provides. Two actions, an action and a posture
                    # (both use a mouth or a back) or two spaces (both have a floor) are alternatives, not
                    # related knowledge.
                    self.neighbours[entry_id] += [(other, "shares") for other in group if other != entry_id
                                                  and (self.kind[other] in ("item", "space")) != (self.kind[entry_id] in ("item", "space"))]
        for entry_id in ids:
            self.neighbours[entry_id] = sorted(set(self.neighbours[entry_id]))

    def _features(self, entry_id):
        entry = self.resolved[entry_id]
        words = terms(" ".join([entry["name"], *entry.get("aliases", []), entry.get("description", "")]))
        return frozenset(words) | {f"@{ref}" for ref in self.uses[entry_id]}


class _Labels:
    """Declared labels (categories, pack themes) that the brief's own words can reach.

    A label is reached by a word of its name, or by description words that no other label and no background
    text uses (description_terms of them): prose shared with others ("reuses core bodies", "places") says
    nothing about intent."""

    def __init__(self, items, description_terms, background=()):
        self.names, self.minimum = {}, description_terms
        documents = []
        for key, name_text, name, description in items:
            self.names[key] = name
            documents.append(Document(key, {"name": terms(name_text), "description": terms(description)},
                                      [(name, "name", tuple(terms(name)))] if terms(name) else []))
        self.text = TextIndex(documents, {"name": 3.0, "description": 1.0})
        self.df = {}
        for words in [{term for words in document.fields.values() for term in words} for document in documents] + \
                [set(terms(text)) for text in background]:
            for term in words:
                self.df[term] = self.df.get(term, 0) + 1

    def keys(self):
        return sorted(self.names)

    def reached(self, key, query):
        """The query words that reach the label: [(word, source)], or [] when it is not reached."""
        _, matches = self.text.score(key, query)
        named = [(term, source) for term, other, name, source, _ in matches if name == "name"]
        described = [(term, source) for term, other, name, source, _ in matches if name != "name" and self.df.get(other) == 1]
        if named or len({term for term, _ in described}) >= self.minimum:
            return sorted(set(named + described))
        return []


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
        self.matched, self.named_by, self.partial, self.usable, self.dependent = {}, {}, {}, [], {}
        self.pools, self.intent = [], {}
        self.per_scene, pool_floor = INSPIRATION.get(request.creativity, INSPIRATION["Balanced"])
        self.pool_floor = pool_floor

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
        selected = []
        if relevant:
            checked = self.compatibility(relevant)
            self.timings["compatibility_ms"] = (time.perf_counter() - started) * 1000 - self.timings["relevance_ms"]
            selected = self.select(checked)
        if self.config.inspiration:
            self.inspire({entry_id for _, entry_id, _ in relevant}, cast_report)
        empty = None if selected or self.pools else (
            "no relevant vocabulary for this request" if not relevant else "no compatible vocabulary for this request")
        return self.result(selected, cast_report, empty, started)

    def result(self, entries, cast_report, empty_warning, started):
        if empty_warning:
            self.warnings.append(empty_warning)
        self.timings["total_ms"] = (time.perf_counter() - started) * 1000
        stats = {"indexed": len(self.index.resolved) if self.index else 0, "returned": len(entries),
                 "ideas": sum(len(pool) for _, pool in self.pools),
                 "suppressed": len(self.suppressed), "excluded": len(self.excluded)}
        return Retrieval(entries, cast_report, self.suppressed, self.excluded, self.warnings, self.config, stats, self.timings,
                         pools=self.pools, intent=self.intent, seed=self.request.seed, per_scene=self.per_scene)

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
    def counted(self, entry_id, query=None, exact=False):
        """The text matches that count for an entry.

        Standing instructions (director, style) count only where they name an entry: a tag, or a whole
        one-word name or alias. Their general words ("action", "composition", "face") would otherwise
        match the descriptions, categories and longer names of everything."""
        _, matches = self.index.text.score(entry_id, self.query if query is None else query, exact=exact)
        single = {phrase[0] for _, _, phrase in self.index.text.documents[entry_id].phrases if len(phrase) == 1}
        return [match for match in matches if match[3] not in STANDING
                or match[2] == "tag" or match[2] in STRONG_FIELDS and match[1] in single]

    def direct(self, entry_id, query=None, sequences=None, exact=False):
        matches = self.counted(entry_id, query, exact)
        score = sum(match[4] for match in matches)
        hits = self.index.text.phrase_hits(entry_id, self.sequences if sequences is None else sequences)
        seen, why = set(), []
        for label, name, source, value, contiguous in hits:
            if label not in seen:
                seen.add(label)
                score += value
                why.append((value, f'{name} "{label}" {"in" if contiguous else "matches"} the {source}'))
        self.matched[entry_id] = {other for _, other, name, _, _ in matches if name in STRONG_FIELDS}
        loose = {other for _, other, name, _, _ in matches if name not in STRONG_FIELDS}
        # Named: a tag, a whole one-word name or alias, or a multi-word name found in full. Isolated: only
        # single words of longer names ("staff" of "Magic staff") and at most one other word.
        single = {phrase[0] for _, _, phrase in self.index.text.documents[entry_id].phrases if len(phrase) == 1}
        whole = {other for _, other, name, _, _ in matches if name == "tag" or name in STRONG_FIELDS and other in single}
        self.evidence = (bool(hits or whole),
                         not hits and not whole and bool(self.matched[entry_id]) and len(self.matched[entry_id] | loose) < 2)
        # Which texts name the entry (a phrase, a tag, a whole one-word name or alias): a choice when they state one.
        self.naming = ({hit[2] for hit in hits} | {source for _, other, name, source, _ in matches
                                                    if name == "tag" or name in STRONG_FIELDS and other in single})
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
        direct, linkable, named, isolated = {}, set(), set(), set()
        self.named_by = {}  # entry -> the texts that name it
        for entry_id in allowed:
            if index.kind[entry_id] == "body":
                continue  # bodies describe the cast; they never make scene entries relevant
            direct[entry_id] = self.direct(entry_id)
            if self.evidence[0]:
                named.add(entry_id)
                self.named_by[entry_id] = set(self.naming)
            elif self.evidence[1]:
                isolated.add(entry_id)
            if self.coverage(entry_id) >= LINK_COVERAGE:
                linkable.add(entry_id)
        # One word of a longer name ("hotel staff" and Magic staff, "side of the road" and Lying on the side)
        # counts only when the request also names an entry linked to it: its parent ("a bow" and Deep bow),
        # the action that uses it ("casting a spell with a staff"), the posture it takes.
        # Only what the brief itself names vouches for an isolated word: a director naming "anatomy" (linked to
        # nearly everything) must not turn "bed" into "Tied to the bed".
        vouching = {entry_id for entry_id in named if self.named_by.get(entry_id, set()) - set(STANDING)}
        for entry_id in sorted(isolated):
            if not any(other in vouching for other, _ in index.neighbours[entry_id]):
                direct[entry_id] = (0.0, [])
        self.partial = {entry_id: value[0] for entry_id, value in direct.items()}
        self.dependent = self.dependencies(named)
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
                if entry_id in self.dependent and entry_id not in named:
                    self.excluded.append({"id": entry_id, "reason": self.dependent[entry_id]})
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

    # -- what the request rules out, through the vocabulary's own dependencies
    def object_needs(self, entry_id):
        """[(slot, minimum count, all_of, any_of groups)] of the object slots an entry declares (resolved
        requirements keep each any_of as a group, of which one capability is needed)."""
        comp = self.index.resolved[entry_id]["components"]
        needs = []
        for slot, spec in sorted(comp.get("participants", {}).get("slots", {}).items()):
            if spec.get("kind") == "object":
                low = spec["count"]["min"] if isinstance(spec["count"], dict) else spec["count"]
                wanted = comp.get("requirements", {}).get("participants", {}).get(slot, {})
                groups = [set(group) for group in wanted.get("any_of_groups", [])] + ([set(wanted["any_of"])] if wanted.get("any_of") else [])
                needs.append((slot, low, set(wanted.get("all_of", [])), groups))
        return needs

    def provides(self, entry_id):
        """What an item provides, with everything that implies."""
        return implied(self.registry, self.index.resolved[entry_id]["components"].get("object", {}).get("provides", []))

    def dependencies(self, named):
        """{entry: reason} for what the request rules out: an entry whose name, alias or tag a negated word or an
        avoid item names, an item that provides what such an entry requires of its objects ("no toys": Toy play,
        and the toys it takes), and an interaction whose required object only ruled-out items provide. What
        the request itself names keeps what it needs."""
        if not self.negated:
            return {}
        index, negative = self.index, {term: (1.0, source) for term, source in self.negated.items()}
        sequences = [(source, 1.0, [term]) for term, source in self.negated.items()]
        out = {}
        for entry_id in sorted(index.resolved):
            if index.kind[entry_id] in SCENE_KINDS:
                _, why = self.direct(entry_id, negative, sequences, exact=True)
                strong = [text for _, text in why if text.startswith(("name", "alias", "tag"))]
                if strong:
                    out[entry_id] = f"ruled out by the request: {strong[0]}"
        kept = [entry_id for entry_id in named if entry_id not in out]
        protected = {cap for entry_id in kept for _, _, every, groups in self.object_needs(entry_id) for cap in every.union(*groups)}
        banned = {}
        for entry_id in sorted(out):
            for _, _, every, groups in self.object_needs(entry_id):
                for cap in sorted(every.union(*groups)):
                    if cap not in protected:
                        banned.setdefault(cap, entry_id)
        items = [entry_id for entry_id in sorted(index.resolved) if index.kind[entry_id] == "item"]
        for entry_id in items:
            hit = sorted(self.provides(entry_id) & set(banned))
            if hit and entry_id not in out and entry_id not in named:
                out[entry_id] = (f"ruled out with {index.resolved[banned[hit[0]]]['name']}: it provides "
                                 f"{index.resolved[hit[0]]['name'].lower()}, which only serves what the request rules out")
        for entry_id in sorted(index.resolved):
            if index.kind[entry_id] != "bindable" or entry_id in out or entry_id in named:
                continue
            for slot, low, every, groups in self.object_needs(entry_id):
                needed = every.union(*groups)
                if needed and needed <= set(banned):  # its object is defined only by what the request rules out
                    out[entry_id] = (f"ruled out with {index.resolved[banned[sorted(needed)[0]]]['name']}: its {slot} needs "
                                     f"{', '.join(index.resolved[cap]['name'].lower() for cap in sorted(needed))}")
                    break
                fits = [item for item in items if every <= self.provides(item) and all(group & self.provides(item) for group in groups)]
                if low >= 1 and fits and all(item in out for item in fits):
                    out[entry_id] = f"ruled out: every item its {slot} needs is ruled out ({', '.join(index.resolved[item]['name'] for item in fits[:3])})"
                    break
        return out

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
            label = character.get("label") if isinstance(character, dict) else None
            label = label or f"character {number}"
            # What the label and custom text name comes first. Gender is never matched against bodies or
            # anatomy; it only says, as Step 1 defines it, whether the character is human at all.
            matches = self.bodies_named(_body_text(character), bodies)
            if isinstance(character, dict) and character.get("gender") in HUMAN_GENDERS:
                human = self.bodies_named("human", bodies)[:1]
                if human and (not matches or matches[0][3] < human[0][3]):
                    # Nothing named is a full body plan (only traits, or nothing): the brief's human body.
                    reason = f'the brief says {character["gender"]}, a human'
                    matches = [(*human[0][:2], reason, human[0][3]), *[item for item in matches if item[1] != human[0][1]]]
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

    def bodies_named(self, text, bodies):
        """Body entries the text names (names, aliases and tags only), largest body plan first."""
        positive, _ = split_negated(text)
        query = {term: (1.0, "character") for term in positive if not term.isdigit()}
        matches = []
        for entry_id in bodies:
            score, why = self.direct(entry_id, query, [("character", 1.0, positive)])
            strong = [text for _, text in why if text.startswith(("name", "alias", "tag"))]
            if score >= CAST_MIN and strong:  # descriptions are too loose for a cast
                size = len(self.index.resolved[entry_id]["components"]["body"].get("resources", {}))
                matches.append((score, entry_id, strong[0], size))
        # The body is the largest matching body plan; the other matches are traits added to it.
        matches.sort(key=lambda item: (-item[3], -item[0], item[1]))
        return matches

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
        self.usable = list(usable)
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
        matched = {entry_id: {match[0] for match in self.counted(entry_id)} for entry_id in ids}
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

    # -- inspiration: what the brief opens without naming it
    def intent_query(self, sources):
        """The brief's own words from the given texts, without what it rules out: {term: (1.0, source)}."""
        query = {}
        for source, text in self.request.texts():
            if source in sources and text:
                for term in split_negated(text)[0]:
                    if not term.isdigit() and term not in self.negated:
                        query.setdefault(term, (1.0, source))
        return query

    def inspire(self, relevant, cast_report):
        """Ideas from the categories the brief opens, checked like named entries, as pools per category."""
        index, registry = self.index, self.registry
        intent, opening = self.intent_query(INTENT_SOURCES), self.intent_query((OPENING_SOURCE,))
        negative = {term: (1.0, source) for term, source in self.negated.items()}
        labels, scene = index.category_labels, index.scene_categories
        reached = {key: words for key in scene if (words := labels.reached(key, intent))}
        reopened = {key for key in scene if labels.reached(key, opening)}
        ruled_out = {key: words for key in scene if negative and (words := labels.reached(key, negative))}
        ordered = sorted(RATINGS.index(rating) for rating in self.allowed if rating in RATINGS)
        top = RATINGS[ordered[-1]] if ordered else None
        content = top if self.request.nsfw and top not in (None, "general") else None
        themes = {}
        # A rating word ("adult") is the content level, which the brief's path already sets, not a theme.
        thematic = {term: value for term, value in intent.items() if term not in RATINGS}
        for pack_id in index.theme_labels.keys():
            words = index.theme_labels.reached(pack_id, thematic)
            if words:
                themes[pack_id] = "the brief says " + ", ".join(f'"{term}" ({source})' for term, source in words[:3])
        for entry_id, sources in sorted(self.named_by.items()):
            pack_id = registry.owner(entry_id)
            if sources & set(INTENT_SOURCES) and pack_id in index.theme_labels.names:
                themes.setdefault(pack_id, f"the brief names {index.resolved[entry_id]['name']}")
        # A cast body or trait reaches its pack's theme, except the plain human body: being human is no theme.
        bodies = [entry_id for entry_id in sorted(index.resolved) if index.kind[entry_id] == "body" and self.allowed_entry(entry_id)]
        plain = {item[1] for item in self.bodies_named("human", bodies)[:1]}
        for member in cast_report:
            for entry_id in [member.get("body"), *member.get("traits", [])]:
                if entry_id in plain:
                    continue
                pack_id = registry.owner(entry_id) if entry_id in index.resolved else None
                if pack_id in index.theme_labels.names:
                    themes.setdefault(pack_id, f"{member['character']} is cast as {index.resolved[entry_id]['name']}")
        # What the request fixes: an entry it names in a text that states a choice.
        fixed = {}
        for entry_id, sources in sorted(self.named_by.items()):
            kind = index.kind[entry_id]
            if sources & set(CHOICE_SOURCES) and kind in SCENE_KINDS:
                group = "interaction" if kind in INTERACTION_KINDS else kind
                fixed.setdefault(group, []).append(index.resolved[entry_id]["name"])
        places = self.fixed_places(cast_report)
        if places:
            fixed.setdefault("place", places)
        report = {key: {"id": key, "name": labels.names[key], "reached": [], "state": "not reached", "reason": "", "ideas": [],
                        "counts": {}} for key in scene}
        for key, words in reached.items():
            report[key]["reached"].append({"scope": "category", "why": "the brief says " + ", ".join(
                f'"{term}" ({source})' for term, source in words[:3])})
        for key in ruled_out:
            report[key]["state"], report[key]["reason"] = "closed", self.closed(None, key, [], set(), {}, ruled_out)
        candidates = {}
        for entry_id in sorted(index.resolved):
            kind = index.kind[entry_id]
            if kind not in SCENE_KINDS or entry_id in relevant:
                continue
            category, rating = index.resolved[entry_id]["category"], index.resolved[entry_id].get("rating", "general")
            pack_id = registry.owner(entry_id)
            scopes = ([("category", report[category]["reached"][0]["why"])] if category in reached else []) + \
                ([("arrangement", "every image arranges its people and the brief leaves how open")]
                 if self.arrangement(entry_id) else []) + \
                ([("setting", "every image with people has a place and the brief leaves it open")]
                 if kind == "space" and self.cast else []) + \
                ([("theme", f"{index.theme_labels.names[pack_id]}: {themes[pack_id]}")] if pack_id in themes else []) + \
                ([("content", f"the brief asks for {content} content")] if content and rating == content else [])
            if category not in report or not any(scope in OPENING for scope, _ in scopes):
                continue  # the content level alone opens nothing
            if pack_id in index.theme_labels.names and not any(scope in ("theme", "content") for scope, _ in scopes):
                continue  # a themed pack's entries belong to briefs that reach its theme (or its content level)
            entry_report = report[category]
            for scope, why in scopes:
                if not any(item["scope"] == scope for item in entry_report["reached"]):
                    entry_report["reached"].append({"scope": scope, "why": why})
            counts = entry_report["counts"]
            if not self.allowed_entry(entry_id):
                counts["rating"] = counts.get("rating", 0) + 1
                continue
            reason = self.closed(kind, category, scopes, reopened, fixed, ruled_out)
            if reason:
                entry_report["state"], entry_report["reason"] = "closed", reason
                continue
            entry_report["state"] = "open"
            if entry_id in self.dependent:
                self.excluded.append({"id": entry_id, "reason": self.dependent[entry_id], "source": "inspiration"})
                counts["ruled out"] = counts.get("ruled out", 0) + 1
                continue
            lowered = False
            if negative:
                against, _ = self.direct(entry_id, negative, [(source, 1.0, [term]) for term, source in self.negated.items()], exact=True)
                lowered = against > 0
            kinds = {scope for scope, _ in scopes}
            weight = (SCOPE_WEIGHTS["category"] if kinds & set(DIMENSIONS) else 0.0) + \
                (SCOPE_WEIGHTS["content"] if "content" in kinds else SCOPE_WEIGHTS["theme"] if "theme" in kinds else 0.0)
            score = (weight + min(0.5, 0.1 * self.partial.get(entry_id, 0.0))) * (0.5 if lowered else 1.0)
            candidates.setdefault(category, []).append((score, entry_id, scopes))
        for key, item in report.items():
            if item["state"] == "not reached" and item["reached"]:
                item["state"] = "open"
        self.check_ideas(candidates, report)
        for key, item in report.items():
            item["empty"] = self.empty_reason(item) if not item["ideas"] else None
            if item["state"] == "not reached":
                item["reason"] = "nothing in the brief names, implies or randomizes it"
        self.intent = {"content": content, "themes": [{"pack": pack_id, "name": index.theme_labels.names[pack_id], "why": why}
                                                       for pack_id, why in sorted(themes.items())],
                       "fixed": {group: sorted(names) for group, names in sorted(fixed.items())},
                       "ruled_out": {key: [term for term, _ in words] for key, words in sorted(ruled_out.items())},
                       "categories": sorted(report.values(), key=lambda item: (not item["ideas"], item["state"] != "open", item["id"])),
                       "per_scene": self.per_scene}

    def arrangement(self, entry_id):
        """Whether an entry arranges the cast, which every image with people does: a bindable entry that places its
        participants without claiming their body resources (a position, not an act), or, for one person, a posture."""
        kind, comp = self.index.kind[entry_id], self.index.resolved[entry_id]["components"]
        if not self.cast:
            return False
        if kind == "bindable":
            # The whole cast: an arrangement for fewer or more people is no arrangement of these people.
            counts = [spec["count"] for spec in comp.get("participants", {}).get("slots", {}).values() if spec.get("kind") == "being"]
            low = sum(count["min"] if isinstance(count, dict) else count for count in counts)
            high = sum(count["max"] if isinstance(count, dict) else count for count in counts)
            return "claims" not in comp and bool(comp.get("spatial")) and low <= len(self.cast) <= high
        return kind == "self" and len(self.cast) == 1

    def fixed_places(self, cast_report):
        """The places the request sets in words the vocabulary does not know ("on a train platform").

        A locative phrase of a text that states a choice fixes the place unless one of its words names an entry the
        request names or casts ("in missionary", "on a bed") or reaches a category ("in different locations")."""
        index, labels = self.index, self.index.category_labels
        known = set(self.named_by) | {entry_id for member in cast_report for entry_id in [member.get("body"), *member.get("traits", [])]
                                      if entry_id in index.resolved}
        covered = {term for entry_id in known for _, _, phrase in index.text.documents[entry_id].phrases for term in phrase}
        places = set()
        for source, text in self.request.texts():
            if source in CHOICE_SOURCES and text:
                for preposition, words in place_phrases(text):
                    if any(word in covered or word in self.negated for word in words):
                        continue
                    if any(labels.reached(key, {word: (1.0, source)}) for key in labels.keys() for word in words):
                        continue
                    places.add(f"{preposition} {' '.join(words)}")
        return sorted(places)

    def closed(self, kind, category, scopes, reopened, fixed, ruled_out):
        """Why an idea of this kind and category may not be offered, or None when the brief leaves it open."""
        if category in ruled_out:
            return "the request rules it out (" + ", ".join(f'"{term}"' for term, _ in ruled_out[category]) + ")"
        if category in reopened:
            return None  # what may vary re-opens it, even next to a named choice
        group = "interaction" if kind in INTERACTION_KINDS else kind
        if fixed.get(group):
            what = "the interaction" if group == "interaction" else f"the {group}"
            return f"the request fixes {what}: " + ", ".join(fixed[group])
        if kind == "space" and fixed.get("place"):
            return "the request sets the place: " + ", ".join(f'"{phrase}"' for phrase in fixed["place"])
        return None

    def check_ideas(self, candidates, report):
        """The resolver on the best candidates of each category: interactions first, then the spaces and items
        checked with the interactions that are offered (named, or ideas that made a pool)."""
        shortlist = {key: sorted(items, key=lambda item: (-item[0], self.tie(item[1])))[:self.config.inspiration_shortlist]
                     for key, items in candidates.items()}
        checked = {}
        for key in sorted(shortlist):
            for score, entry_id, scopes in shortlist[key]:
                kind = self.index.kind[entry_id]
                if kind in INTERACTION_KINDS:
                    verdict = self.check_bindable(entry_id) if kind == "bindable" else self.check_self(entry_id)
                    checked.setdefault(key, []).append((score, entry_id, scopes, verdict))
        pools = self.pool(checked, report)
        partners = list(dict.fromkeys([*self.usable, *(entry.id for _, _, pool in pools for entry in pool
                                                       if self.index.kind[entry.id] == "bindable")]))
        checked = {}
        for key in sorted(shortlist):
            for score, entry_id, scopes in shortlist[key]:
                kind = self.index.kind[entry_id]
                if kind == "space":  # a setting stands on its own; positions that need a space check it
                    checked.setdefault(key, []).append((score, entry_id, scopes, self.check_space(entry_id, partners)))
                elif kind == "item":  # an item serves an interaction whose requirements it declares it meets
                    serves = [partner for partner in partners if self.check_item(entry_id, [partner])["status"] in DECLARED]
                    if not serves:
                        counts = report[key]["counts"]
                        counts["unused"] = counts.get("unused", 0) + 1
                        continue
                    verdict = {**self.check_item(entry_id, serves), "attach_to": serves}
                    checked.setdefault(key, []).append((score, entry_id, scopes, verdict))
        merged = {}  # a category may hold interactions and items alike
        for best, key, pool in pools + self.pool(checked, report):
            merged[key] = (max(best, merged.get(key, (best, []))[0]), merged.get(key, (best, []))[1] + pool)
        self.pools = [(key, sorted(pool, key=lambda entry: (-entry.score, entry.id)))
                      for key, (best, pool) in sorted(merged.items(), key=lambda item: (-item[1][0], item[0]))]

    def pool(self, checked, report):
        """[(best score, category, [RetrievedEntry])] from checked candidates: conflicts out, the floor, no repeats."""
        pools = []
        for key in sorted(checked):
            counts, kept = report[key]["counts"], []
            for score, entry_id, scopes, verdict in checked[key]:
                status = verdict["status"]
                if status == "conflict":
                    reasons = [self.humanize(reason) for reason in verdict.get("reasons", [])[:2]]
                    self.excluded.append({"id": entry_id, "reason": "conflict: " + "; ".join(reasons), "source": "inspiration"})
                    counts["conflict"] = counts.get("conflict", 0) + 1
                    continue
                if status == "unknown" and not self.config.include_unknown:
                    counts["unknown"] = counts.get("unknown", 0) + 1
                    continue
                value = score * STATUS_FACTOR[status] * (0.6 + 0.4 * self.fit(entry_id, verdict))
                kept.append((value, entry_id, scopes, verdict))
            kept.sort(key=lambda item: (-item[0], self.tie(item[1])))
            pool = []
            for value, entry_id, scopes, verdict in kept:
                if value < self.pool_floor * kept[0][0]:
                    self.suppressed.append({"id": entry_id, "because": f"idea below the pool floor of {key}", "source": "inspiration"})
                    counts["below the floor"] = counts.get("below the floor", 0) + 1
                    continue
                same = next((chosen for chosen in pool if self.index.resolved[entry_id]["components"] ==
                             self.index.resolved[chosen.id]["components"] and chosen.id in self.index.ancestors[entry_id]), None)
                similar = max(((_jaccard(self.index.features[entry_id], self.index.features[chosen.id]), chosen.id) for chosen in pool),
                              default=(0, None))
                if same or similar[0] >= self.config.duplicate_similarity:
                    because = f"inherited duplicate of {same.id}" if same else f"repeats {similar[1]} (similarity {similar[0]:.2f})"
                    self.suppressed.append({"id": entry_id, "because": because, "source": "inspiration"})
                    continue
                if len(pool) >= self.config.inspiration_pool:
                    self.suppressed.append({"id": entry_id, "because": f"beyond the {key} pool of {self.config.inspiration_pool}",
                                            "source": "inspiration"})
                    continue
                pool.append(self.idea(entry_id, value, scopes, verdict))
            if pool:
                pools.append((pool[0].score, key, pool))
                report[key]["ideas"] += [entry.id for entry in pool]
        return pools

    def tie(self, entry_id):
        """A seeded order among equally good candidates, so a large pack shows different ideas per seed, never just
        the first in the alphabet; the same seed always gives the same order."""
        return (random.Random(f"{self.request.seed}|{entry_id}").random(), entry_id)

    def fit(self, entry_id, verdict):
        """How much of the cast an interaction involves (1.0 for everything else)."""
        if self.index.kind[entry_id] not in INTERACTION_KINDS or not self.cast:
            return 1.0
        bound = {label for labels in (verdict.get("binding") or {}).values() for label in labels}
        return min(1.0, len(bound) / len(self.cast))

    def idea(self, entry_id, value, scopes, verdict):
        resolved = self.index.resolved[entry_id]
        warnings = [self.humanize(text) for text in verdict.get("warnings", [])]
        return RetrievedEntry(
            id=entry_id, name=resolved["name"], category=resolved["category"], pack=self.registry.owner(entry_id),
            rating=resolved.get("rating", "general"), description=resolved.get("description", ""), status=verdict["status"],
            relevance=float(len(scopes)), score=value, why=[f"{scope}: {why}" for scope, why in scopes],
            warnings=list(dict.fromkeys(warnings)), needs=verdict.get("needs", []), binding=verdict.get("binding"),
            checked_with=verdict.get("checked_with", []), source="inspiration", scopes=[scope for scope, _ in scopes],
            attach_to=list(verdict.get("attach_to", [])))

    @staticmethod
    def empty_reason(item):
        if item["state"] == "closed":
            return item["reason"]
        if item["state"] == "not reached":
            return "not reached by the brief"
        counts = item["counts"]
        parts = {"rating": "rating not allowed", "ruled out": "ruled out by the request", "conflict": "conflicts with this cast",
                 "unknown": "unknown (include_unknown is off)", "unused": "no interaction in the pool that it serves"}
        found = [f"{number} {parts[key]}" for key, number in sorted(counts.items()) if key in parts and number]
        return "no eligible candidate: " + ("; ".join(found) if found else "nothing left after the checks")

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
