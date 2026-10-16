"""A Director's vocabulary preferences (SPEC.md section 13): structured data, never code.

A Director preset may carry a "vocabulary" block. It steers selection; it never adds an entry from a pack the run did
not select, never outranks what the request, fixed, must, avoid or the user's rules say, and an id, tag or category
that the run's packs do not have is simply unused (and reported in the run's diagnostics):

  {"require":    [ids],                                                          mandatory scene mechanics
   "prefer":    {"entries": [ids], "tags": [tags], "categories": [categories]},   chosen more often
   "avoid":      {"entries": [...], "tags": [...], "categories": [...]},          not chosen unless the request names it
   "visual":     {"prefer": [direction ids], "avoid": [direction ids]},           Visual Direction (section 11)
   "priorities": ["arrangement", "interaction", "space"],                        the order roles are composed in
   "themes":     ["short phrases"]}                                               words that may reach entries, like
                                                                                  the Director's own text (section 10)

Every key is optional; {} is no preference. A Director without the block keeps steering through its instructions
alone (they are a retrieval source, section 10).
"""

import re

ROLES = ("arrangement", "interaction", "space")
GROUPS = ("entries", "tags", "categories")
KEYS = ("require", "prefer", "avoid", "visual", "priorities", "themes")
PREFER_WEIGHT = 3.0   # how much likelier a preferred idea is drawn (retrieval rotation weight and composer race)
MAX_ITEMS, MAX_THEMES, MAX_THEME = 64, 12, 80
_ID = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _list(value, where, pattern=None, limit=MAX_ITEMS):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{where} must be a list of at most {limit} strings.")
    if pattern is not None and any(not pattern.match(item) for item in value):
        raise ValueError(f"{where} has an invalid {'id' if pattern is _ID else 'name'}.")
    return list(dict.fromkeys(value))


def validate(value):
    """The normalized block; {} for None. Raises ValueError naming the first problem."""
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(KEYS):
        raise ValueError(f"Director vocabulary preferences take only {', '.join(KEYS)}.")
    out = {}
    if "require" in value:
        out["require"] = _list(value["require"], "vocabulary.require", _ID)
    for side in ("prefer", "avoid"):
        if side in value:
            group = value[side]
            if not isinstance(group, dict) or set(group) - set(GROUPS):
                raise ValueError(f"vocabulary.{side} takes only {', '.join(GROUPS)}.")
            cleaned = {key: _list(group[key], f"vocabulary.{side}.{key}", _ID if key == "entries" else _NAME)
                       for key in GROUPS if key in group}
            cleaned = {key: items for key, items in cleaned.items() if items}
            if cleaned:
                out[side] = cleaned
    if "visual" in value:
        visual = value["visual"]
        if not isinstance(visual, dict) or set(visual) - {"prefer", "avoid"}:
            raise ValueError("vocabulary.visual takes only prefer and avoid.")
        cleaned = {key: _list(visual[key], f"vocabulary.visual.{key}", _ID) for key in ("prefer", "avoid") if key in visual}
        cleaned = {key: items for key, items in cleaned.items() if items}
        if cleaned:
            out["visual"] = cleaned
    if "priorities" in value:
        priorities = _list(value["priorities"], "vocabulary.priorities", limit=len(ROLES))
        if set(priorities) - set(ROLES):
            raise ValueError(f"vocabulary.priorities lists roles: {', '.join(ROLES)}.")
        if priorities:
            out["priorities"] = priorities
    if "themes" in value:
        themes = _list(value["themes"], "vocabulary.themes", limit=MAX_THEMES)
        themes = [" ".join(item.split()) for item in themes]
        if any(not item or len(item) > MAX_THEME for item in themes):
            raise ValueError(f"vocabulary.themes are phrases of 1 to {MAX_THEME} characters.")
        if themes:
            out["themes"] = themes
    for side in ("prefer", "avoid"):
        for key in GROUPS:
            both = set(out.get("prefer", {}).get(key, [])) & set(out.get("avoid", {}).get(key, []))
            if both:
                raise ValueError(f"vocabulary {key} both preferred and avoided: {', '.join(sorted(both))}.")
    both = set(out.get("visual", {}).get("prefer", [])) & set(out.get("visual", {}).get("avoid", []))
    if both:
        raise ValueError(f"vocabulary.visual directions both preferred and avoided: {', '.join(sorted(both))}.")
    return out


class Preferences:
    """A validated block read against one run's registry: ids are made canonical (replaced ids follow their entry)."""

    def __init__(self, block=None, registry=None):
        self.block = validate(block)
        canonical = registry.canonical if registry is not None else (lambda entry_id: entry_id)
        self.registry = registry
        self.require = tuple(canonical(item) for item in self.block.get("require", []))
        get = lambda side, key: self.block.get(side, {}).get(key, [])
        self.prefer_entries = {canonical(item) for item in get("prefer", "entries")}
        self.avoid_entries = {canonical(item) for item in get("avoid", "entries")}
        self.prefer_tags, self.avoid_tags = set(get("prefer", "tags")), set(get("avoid", "tags"))
        self.prefer_categories, self.avoid_categories = set(get("prefer", "categories")), set(get("avoid", "categories"))
        self.visual = {"prefer": [canonical(item) for item in get("visual", "prefer")],
                       "avoid": [canonical(item) for item in get("visual", "avoid")]}
        self.priorities = tuple(self.block.get("priorities", ()))
        self.themes = tuple(self.block.get("themes", ()))

    def __bool__(self):
        return bool(self.block)

    def _resolved(self, entry_id):
        return self.registry.resolved(entry_id) if self.registry is not None and entry_id in self.registry else None

    def prefers(self, entry_id):
        entry = self._resolved(entry_id)
        return entry_id in self.prefer_entries or bool(entry and (set(entry.get("tags", [])) & self.prefer_tags
                                                                  or entry["category"] in self.prefer_categories))

    def avoids(self, entry_id):
        entry = self._resolved(entry_id)
        return entry_id in self.avoid_entries or bool(entry and (set(entry.get("tags", [])) & self.avoid_tags
                                                                 or entry["category"] in self.avoid_categories))

    def weight(self, entry_id):
        return PREFER_WEIGHT if self.prefers(entry_id) else 1.0

    def order(self, default):
        """The roles in composition order: the Director's priorities first, then the rest in their default order."""
        return tuple(dict.fromkeys([*self.priorities, *default]))

    def text(self):
        """What the block adds to the Director's retrieval text: the names of preferred entries, preferred tags as
        words and the themes, so they can reach entries the way the Director's own words do (section 10)."""
        names = [self._resolved(entry_id)["name"] for entry_id in sorted(self.prefer_entries) if self._resolved(entry_id)]
        tags = [tag.replace("_", " ") for tag in sorted(self.prefer_tags)]
        return "; ".join([*names, *tags, *self.themes])

    def unknown(self):
        """Ids in the block that the run's packs do not have: unused, reported."""
        if self.registry is None:
            return []
        ids = self.prefer_entries | self.avoid_entries | set(self.require) | set(self.visual["prefer"]) | set(self.visual["avoid"])
        return sorted(entry_id for entry_id in ids if entry_id not in self.registry)

    def record(self):
        return {**self.block, **({"unknown": self.unknown()} if self.unknown() else {})} if self.block else {}
