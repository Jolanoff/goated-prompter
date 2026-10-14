"""Vocabulary pack manager (Phase 2): data-only packs, validated and merged into one registry.

Three locations:
  vocabulary/core/            the core pack: mandatory, always enabled, read-only
  vocabulary/packs/<id>/      official packs that ship with the app (Fantasy, Adult): read-only, optional,
                              enabled by default
  data/vocabulary/packs/<id>/ packs the user installed: optional, enabled by default, removable
Official and installed packs are enabled unless listed in data/vocabulary/state.json, which keeps the
choice for both. A pack id may appear in one location only; a duplicate is rejected, never overridden.
Packs contain JSON data and optional README/LICENSE text only.

The rules implemented here are those of vocabulary/schemas/SPEC.md: manifest and entry schemas,
pack ids as id prefixes, declared categories, dependency versions and conflicts, references only into
reachable packs, inheritance without cycles or contradictions (section 7), and ratings never looser
than the pack. No compatibility resolution, retrieval or scene logic lives here.
"""

from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import zipfile

import jsonschema

from ...config import PROJECT_ROOT

SCHEMA_DIR = PROJECT_ROOT / "vocabulary" / "schemas"
BUNDLED_DIRS = (PROJECT_ROOT / "vocabulary" / "core",)  # mandatory
OFFICIAL_DIR = PROJECT_ROOT / "vocabulary" / "packs"     # bundled, optional
INSTALL_DIR = PROJECT_ROOT / "data" / "vocabulary" / "packs"
STATE_FILE = PROJECT_ROOT / "data" / "vocabulary" / "state.json"
SPEC = 1
RATINGS = ("general", "mature", "adult")
# Text a pack may carry besides its JSON data. Nothing else is accepted: packs are data only.
EXTRA_FILES = re.compile(r"^(README|LICENSE|CHANGELOG)(\.(md|txt))?$", re.IGNORECASE)
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 500
MAX_RATIO = 100  # largest allowed uncompressed / compressed size of one archive member
_VERSION = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
_RANGE_PART = re.compile(r"^(>=|>|<=|<|=)?([0-9]+\.[0-9]+\.[0-9]+)$")


class VocabularyError(ValueError):
    """A pack or operation was rejected. problems lists every reason found."""

    def __init__(self, problems):
        self.problems = list(problems) if isinstance(problems, (list, tuple)) else [str(problems)]
        super().__init__("; ".join(self.problems))


@dataclass
class Pack:
    id: str
    manifest: dict
    path: Path
    bundled: bool                                # ships with the app: read-only
    enabled: bool
    entries: list = field(default_factory=list)  # [(file name, entry)]
    mandatory: bool = False                      # the core: always enabled

    def summary(self):
        return {"id": self.id, "name": self.manifest["name"], "version": self.manifest["version"],
                "description": self.manifest.get("description", ""),
                "origin": "core" if self.mandatory else "bundled" if self.bundled else "installed",
                "rating": self.manifest["rating"], "bundled": self.bundled, "mandatory": self.mandatory,
                "enabled": self.enabled, "requires": dict(self.manifest.get("requires", {})), "entries": len(self.entries)}


# ---------------------------------------------------------------- versions

def parse_version(text):
    match = _VERSION.match(str(text))
    if not match:
        raise ValueError(f'"{text}" is not a version (major.minor.patch)')
    return tuple(int(part) for part in match.groups())


def satisfies(version, spec):
    """True when version (x.y.z) meets every part of a range like ">=1.0.0 <2.0.0"."""
    current = parse_version(version)
    for part in spec.split():
        match = _RANGE_PART.match(part)
        if not match:
            raise ValueError(f'"{spec}" is not a version range')
        op, target = match[1] or "=", parse_version(match[2])
        if not {">=": current >= target, ">": current > target, "<=": current <= target,
                "<": current < target, "=": current == target}[op]:
            return False
    return True


# ---------------------------------------------------------------- schemas and pack reading

_SCHEMAS = {}


def _validator(name):
    if name not in _SCHEMAS:
        with open(SCHEMA_DIR / f"{name}.schema.json", encoding="utf-8") as handle:
            _SCHEMAS[name] = jsonschema.Draft202012Validator(json.load(handle))
    return _SCHEMAS[name]


def _schema_problems(name, data, where):
    return [f"{where}: {'/'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.message}"
            for error in sorted(_validator(name).iter_errors(data), key=lambda error: list(error.absolute_path))]


def validate_pack_id(pack_id):
    schema = _validator("manifest").schema["$defs"]["packId"]
    if not isinstance(pack_id, str) or not jsonschema.Draft202012Validator(schema).is_valid(pack_id):
        raise VocabularyError("Invalid pack id. Use the id declared in the pack manifest.")
    return pack_id


def _read_json(path, where):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise VocabularyError(f"{where}: cannot read JSON ({error})") from None


def read_pack(folder, *, bundled, enabled=True):
    """Read and validate one pack folder on its own (schemas, files, ids, categories, ratings)."""
    folder = Path(folder)
    manifest = _read_json(folder / "manifest.json", f"{folder.name}/manifest.json")
    problems = _schema_problems("manifest", manifest, f"{folder.name}/manifest.json")
    if problems:
        raise VocabularyError(problems)
    pack_id = manifest["id"]
    if not bundled and folder.name != pack_id:
        problems.append(f"{pack_id}: the folder must be named after the pack id")
    listed = set(manifest["files"])
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():
            problems.append(f"{pack_id}: {path.name} is not a plain file")
        elif path.name != "manifest.json" and path.name not in listed and not EXTRA_FILES.match(path.name):
            problems.append(f"{pack_id}: {path.name} is not listed in the manifest (packs are data only)")
    entries, seen = [], set()
    pack_rating = RATINGS.index(manifest["rating"])
    for name in manifest["files"]:
        if not (folder / name).is_file():
            problems.append(f"{pack_id}: listed file {name} is missing")
            continue
        data = _read_json(folder / name, f"{pack_id}/{name}")
        file_problems = _schema_problems("entry", data, f"{pack_id}/{name}")
        if file_problems:
            problems.extend(file_problems)
            continue
        for entry in data["entries"]:
            if entry["id"].split(":", 1)[0] != pack_id:
                problems.append(f"{pack_id}/{name}: {entry['id']} must start with \"{pack_id}:\"")
            if entry["id"] in seen:
                problems.append(f"{pack_id}/{name}: duplicate id {entry['id']}")
            if RATINGS.index(entry.get("rating", manifest["rating"])) < pack_rating:
                problems.append(f"{pack_id}/{name}: {entry['id']} is rated looser than its pack")
            seen.add(entry["id"])
            entries.append((name, entry))
    if problems:
        raise VocabularyError(problems)
    return Pack(pack_id, manifest, folder, bundled, enabled, entries)


# ---------------------------------------------------------------- registry

def _capability_refs(comp):
    refs = list(comp.get("capability", {}).get("implies", []))
    body = comp.get("body", {})
    refs += [item["type"] for item in body.get("resources", {}).values()] + body.get("provides", []) + body.get("complete_for", [])
    requirements = comp.get("requirements", {})
    for condition in [*requirements.get("participants", {}).values(), requirements.get("space", {})]:
        refs += [ref for key in ("all_of", "any_of", "none_of") for ref in condition.get(key, [])]
    for access in [*requirements.get("access", []), *comp.get("spatial", {}).get("access", [])]:
        refs += [access["using"], *access["regions"]]
    for placement in comp.get("spatial", {}).get("participants", {}).values():
        refs += [anchor["at"] for anchor in placement.get("anchors", []) if "at" in anchor]
    refs += [claim["resource"] for claims in comp.get("claims", {}).values() for claim in claims]
    refs += comp.get("object", {}).get("provides", []) + comp.get("object", {}).get("complete_for", [])
    refs += comp.get("environment", {}).get("provides", [])
    return refs


def _union(*lists):
    return list(dict.fromkeys(item for items in lists for item in items))


def _merge_scalar(merged, key, value, where, problems):
    if key in merged and merged[key] != value:
        problems.append(f"{where}: inherited {key} differs ({json.dumps(merged[key])} vs {json.dumps(value)})")
    else:
        merged[key] = value


def _merge_components(parts, own, where, problems):
    """SPEC.md section 7. parts are the parents' resolved components in order, own is the child's."""
    out = {}
    def scalars(target, sources, keys, child):
        # Parents must agree; the child's own value is final.
        for key in keys:
            for source in sources:
                if key in source:
                    _merge_scalar(target, key, source[key], where, problems)
            if key in child:
                target[key] = child[key]
    if any("capability" in part for part in [*parts, own]):
        out["capability"] = {"implies": _union(*(part.get("capability", {}).get("implies", []) for part in [*parts, own]))}
    if any("body" in part for part in [*parts, own]):
        resources = {}
        for part in [*parts, own]:
            for name, resource in part.get("body", {}).get("resources", {}).items():
                if name in resources and resources[name] != resource:
                    problems.append(f"{where}: resource {name} is defined differently by two sources")
                resources.setdefault(name, resource)
        bodies = [part.get("body", {}) for part in [*parts, own]]
        out["body"] = {"resources": resources, "provides": _union(*(body.get("provides", []) for body in bodies)),
                       "complete_for": _union(*(body.get("complete_for", []) for body in bodies))}
    if any("participants" in part for part in [*parts, own]):
        slots = {}
        for part in [*parts, own]:
            for name, slot in part.get("participants", {}).get("slots", {}).items():
                if name in slots and slots[name] != slot:
                    problems.append(f"{where}: slot {name} is defined differently by two sources")
                slots.setdefault(name, slot)
        out["participants"] = {"slots": slots}
    if any("requirements" in part for part in [*parts, own]):
        # Resolved conditions keep every any_of group: all groups must hold (AND of parents).
        def add(target, condition):
            target["all_of"] = _union(target.get("all_of", []), condition.get("all_of", []))
            target["none_of"] = _union(target.get("none_of", []), condition.get("none_of", []))
            groups = condition.get("any_of_groups", []) + ([condition["any_of"]] if "any_of" in condition else [])
            target["any_of_groups"] = target.get("any_of_groups", []) + [group for group in groups if group not in target.get("any_of_groups", [])]
        merged = {"participants": {}, "space": {}, "access": []}
        for part in [*parts, own]:
            requirements = part.get("requirements", {})
            for ref, condition in requirements.get("participants", {}).items():
                add(merged["participants"].setdefault(ref, {}), condition)
            if "space" in requirements:
                add(merged["space"], requirements["space"])
            merged["access"] = _union(merged["access"], (json.dumps(item, sort_keys=True) for item in requirements.get("access", [])))
        merged["access"] = [json.loads(item) for item in merged["access"]]
        for ref, condition in [*merged["participants"].items(), ("space", merged["space"])]:
            if set(condition.get("all_of", [])) & set(condition.get("none_of", [])):
                problems.append(f"{where}: {ref} both requires and forbids {sorted(set(condition['all_of']) & set(condition['none_of']))}")
        out["requirements"] = merged
    if any("spatial" in part for part in [*parts, own]):
        placements, access = {}, []
        refs = _union(*(part.get("spatial", {}).get("participants", {}) for part in [*parts, own]))
        for ref in refs:
            sources = [part.get("spatial", {}).get("participants", {}).get(ref, {}) for part in parts]
            child = own.get("spatial", {}).get("participants", {}).get(ref, {})
            placement = {}
            scalars(placement, sources, ("posture", "orientation", "facing"), child)
            anchors = _union([json.dumps(anchor, sort_keys=True) for source in [*sources, child] for anchor in source.get("anchors", [])])
            if anchors:
                placement["anchors"] = [json.loads(anchor) for anchor in anchors]
            placements[ref] = placement
        for part in [*parts, own]:
            access = _union(access, (json.dumps(item, sort_keys=True) for item in part.get("spatial", {}).get("access", [])))
        out["spatial"] = {"participants": placements, "access": [json.loads(item) for item in access]}
    if any("claims" in part for part in [*parts, own]):
        claims = {}
        for part in [*parts, own]:
            for ref, items in part.get("claims", {}).items():
                claims.setdefault(ref, []).extend(items)
        out["claims"] = claims
    if any("object" in part for part in [*parts, own]):
        sources = [part.get("object", {}) for part in parts]
        merged = {"provides": _union(*(source.get("provides", []) for source in [*sources, own.get("object", {})]))}
        complete = _union(*(source.get("complete_for", []) for source in [*sources, own.get("object", {})]))
        if complete:
            merged["complete_for"] = complete
        scalars(merged, sources, ("size", "hands"), own.get("object", {}))
        out["object"] = merged
    if any("environment" in part for part in [*parts, own]):
        out["environment"] = {"provides": _union(*(part.get("environment", {}).get("provides", []) for part in [*parts, own]))}
    return out


class Registry:
    """The merged, validated vocabulary of the enabled packs. Read-only once built."""

    def __init__(self, packs, entries, owners):
        self.packs = packs          # {pack id: Pack}, in load order
        self._entries = entries     # {entry id: entry as written}
        self._owners = owners       # {entry id: pack id}
        self._resolved = {}
        self._by_category, self._by_tag = {}, {}

    def __contains__(self, entry_id):
        return entry_id in self._entries

    def __len__(self):
        return len(self._entries)

    def ids(self):
        return list(self._entries)

    def entry(self, entry_id):
        """The entry exactly as written in its pack."""
        return self._entries[entry_id]

    def owner(self, entry_id):
        return self._owners[entry_id]

    def resolved(self, entry_id):
        """The entry with its inheritance applied (SPEC.md section 7)."""
        return self._resolved[entry_id]

    def by_category(self, category):
        return list(self._by_category.get(category, []))

    def by_tag(self, tag):
        return list(self._by_tag.get(tag, []))

    def categories(self):
        return {category["id"]: {**category, "pack": pack.id} for pack in self.packs.values()
                for category in pack.manifest.get("categories", [])}

    def find(self, text):
        """Entries whose name, alias or tag contains the text (case-insensitive). Not ranked retrieval."""
        needle = str(text).casefold().strip()
        if not needle:
            return []
        return [entry_id for entry_id, entry in self._entries.items()
                if needle in entry["name"].casefold() or any(needle in alias.casefold() for alias in entry.get("aliases", []))
                or any(needle in tag for tag in entry.get("tags", []))]


def _reachable(packs, pack_id):
    result, stack = set(), [pack_id]
    while stack:
        current = stack.pop()
        if current not in result and current in packs:
            result.add(current)
            stack.extend(packs[current].manifest.get("requires", {}))
    return result


def build_registry(packs):
    """Validate the enabled packs together and merge them. Raises VocabularyError listing every problem."""
    problems = []
    active = {pack.id: pack for pack in packs if pack.enabled}
    # Dependencies, versions and declared conflicts.
    for pack in active.values():
        for required, spec in pack.manifest.get("requires", {}).items():
            if required not in active:
                problems.append(f"{pack.id} requires {required} {spec}, which is not "
                                f"{'enabled' if any(other.id == required for other in packs) else 'installed'}")
            elif not satisfies(active[required].manifest["version"], spec):
                problems.append(f"{pack.id} requires {required} {spec}; {active[required].manifest['version']} is enabled")
        for other in pack.manifest.get("conflicts", []):
            if other in active:
                problems.append(f"{pack.id} conflicts with {other}; both are enabled")
    order, state = [], {}
    def visit(pack_id, trail):
        if state.get(pack_id) == "done" or pack_id not in active:
            return
        if state.get(pack_id) == "visiting":
            problems.append("dependency cycle: " + " -> ".join([*trail, pack_id]))
            return
        state[pack_id] = "visiting"
        for required in active[pack_id].manifest.get("requires", {}):
            visit(required, [*trail, pack_id])
        state[pack_id] = "done"
        order.append(pack_id)
    for pack_id in sorted(active):
        visit(pack_id, [])
    if problems:
        raise VocabularyError(problems)
    # Entries: unique ids, declared categories, references into reachable packs only.
    entries, owners = {}, {}
    for pack_id in order:
        for name, entry in active[pack_id].entries:
            if entry["id"] in entries:
                problems.append(f"{pack_id}/{name}: duplicate id {entry['id']} (also in {owners[entry['id']]})")
            entries[entry["id"]], owners[entry["id"]] = entry, pack_id
    for entry_id, entry in entries.items():
        reachable = _reachable(active, owners[entry_id])
        categories = {category["id"] for pack_id in reachable for category in active[pack_id].manifest.get("categories", [])}
        if entry["category"] not in categories:
            problems.append(f"{entry_id}: category {entry['category']} is not declared by its pack or the packs it requires")
        comp = entry["components"]
        postures = [placement["posture"] for placement in comp.get("spatial", {}).get("participants", {}).values() if "posture" in placement]
        for kind, refs in (("extends", entry.get("extends", [])), ("capability", _capability_refs(comp)), ("posture", postures)):
            for ref in refs:
                if ref not in entries:
                    problems.append(f"{entry_id}: {kind} reference {ref} does not exist")
                elif owners[ref] not in reachable:
                    problems.append(f"{entry_id}: {kind} reference {ref} is in pack {owners[ref]}, which {owners[entry_id]} does not require")
                elif kind == "capability" and "capability" not in entries[ref]["components"]:
                    problems.append(f"{entry_id}: {ref} is used as a capability but is not one")
                elif kind == "posture" and "self" not in entries[ref]["components"].get("spatial", {}).get("participants", {}):
                    problems.append(f"{entry_id}: {ref} is used as a posture but has no self placement")
    if problems:
        raise VocabularyError(problems)
    registry = Registry({pack_id: active[pack_id] for pack_id in order}, entries, owners)
    # Inheritance: cycles and contradictions are rejected, never overridden.
    resolving = set()
    def resolve(entry_id, trail):
        if entry_id in registry._resolved:
            return registry._resolved[entry_id]
        if entry_id in resolving:
            problems.append("inheritance cycle: " + " -> ".join([*trail, entry_id]))
            return None
        resolving.add(entry_id)
        entry = entries[entry_id]
        parents = [resolve(parent, [*trail, entry_id]) for parent in entry.get("extends", [])]
        resolving.discard(entry_id)
        if any(parent is None for parent in parents):
            return None
        merged = dict(entry)
        merged["aliases"] = _union(*(parent.get("aliases", []) for parent in parents), entry.get("aliases", []))
        merged["tags"] = _union(*(parent.get("tags", []) for parent in parents), entry.get("tags", []))
        if "description" not in entry:
            description = next((parent["description"] for parent in parents if "description" in parent), None)
            if description:
                merged["description"] = description
        # A resolved entry is at least as strict as anything it inherits from.
        ratings = [entry.get("rating", registry.packs[owners[entry_id]].manifest["rating"])]
        ratings += [parent["rating"] for parent in parents]
        merged["rating"] = max(ratings, key=RATINGS.index)
        merged["components"] = _merge_components([parent["components"] for parent in parents], entry["components"],
                                                 entry_id, problems)
        registry._resolved[entry_id] = merged
        return merged
    for entry_id in entries:
        resolve(entry_id, [])
    if problems:
        raise VocabularyError(list(dict.fromkeys(problems)))
    for entry_id, entry in entries.items():
        registry._by_category.setdefault(entry["category"], []).append(entry_id)
        for tag in registry._resolved[entry_id]["tags"]:
            registry._by_tag.setdefault(tag, []).append(entry_id)
    return registry


# ---------------------------------------------------------------- safe ZIP import

def extract_archive(data, target):
    """Unpack a pack archive into the empty folder target. Raises VocabularyError when unsafe.

    Accepted: manifest.json and other plain JSON/text files, optionally under one top-level folder.
    Rejected: absolute or parent paths, links, encrypted members, oversized or compression-bomb
    members, too many files, nested folders, duplicate names (also by case) and any file that is not data."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise VocabularyError(f"the archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise VocabularyError("the file is not a ZIP archive") from None
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if not members:
            raise VocabularyError("the archive is empty")
        if len(members) > MAX_FILES:
            raise VocabularyError(f"the archive has more than {MAX_FILES} files")
        problems, paths, total = [], [], 0
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in path.parts or not path.parts:
                problems.append(f"{name}: unsafe path")
            elif stat.S_ISLNK(mode):
                problems.append(f"{name}: links are not allowed")
            elif member.flag_bits & 0x1:
                problems.append(f"{name}: encrypted files are not allowed")
            elif member.file_size > MAX_FILE_BYTES:
                problems.append(f"{name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
            elif member.compress_size and member.file_size / member.compress_size > MAX_RATIO:
                problems.append(f"{name}: compression ratio is suspiciously high")
            paths.append(path)
            total += member.file_size
        if total > MAX_UNPACKED_BYTES:
            problems.append(f"the archive unpacks to more than {MAX_UNPACKED_BYTES // (1024 * 1024)} MB")
        if problems:
            raise VocabularyError(problems)
        # Either every file is at the top, or every file sits in one shared top-level folder.
        roots = {path.parts[0] for path in paths}
        strip = 1 if len(roots) == 1 and all(len(path.parts) == 2 for path in paths) else 0
        for member, path in zip(members, paths):
            relative = PurePosixPath(*path.parts[strip:])
            if len(relative.parts) != 1:
                problems.append(f"{member.filename}: packs have no sub-folders")
            elif not (relative.name.endswith(".json") or EXTRA_FILES.match(relative.name)):
                problems.append(f"{member.filename}: only JSON data and README/LICENSE text are allowed")
        names = [path.parts[-1].casefold() for path in paths]
        problems += [f"{name}: appears more than once" for name in sorted({name for name in names if names.count(name) > 1})]
        if problems:
            raise VocabularyError(problems)
        target = Path(target)
        for member, path in zip(members, paths):
            name = path.parts[-1]
            with archive.open(member) as source, open(target / name, "xb") as sink:
                written = 0
                while chunk := source.read(65536):
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise VocabularyError(f"{member.filename}: larger than declared")
                    sink.write(chunk)


# ---------------------------------------------------------------- manager

class PackManager:
    """Discovery, install, removal, enable/disable and the merged registry. Thread-safe."""

    def __init__(self, install_dir=INSTALL_DIR, state_file=STATE_FILE, bundled_dirs=BUNDLED_DIRS, official_dir=OFFICIAL_DIR):
        self.install_dir = Path(install_dir)
        self.state_file = Path(state_file)
        self.bundled_dirs = tuple(Path(path) for path in bundled_dirs)
        self.official_dir = Path(official_dir) if official_dir is not None else None
        self._lock = threading.RLock()

    # -- state
    def _disabled(self):
        if not self.state_file.is_file():
            return set()
        state = _read_json(self.state_file, self.state_file.name)
        if not isinstance(state, dict) or state.get("spec") != SPEC or not isinstance(state.get("disabled"), list):
            raise VocabularyError(f"{self.state_file.name} is not a vocabulary state file")
        return set(state["disabled"])

    def _write_disabled(self, disabled):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.state_file.parent, prefix=".state-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"spec": SPEC, "disabled": sorted(disabled)}, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, self.state_file)

    # -- discovery
    def _bundled(self):
        """The mandatory core pack(s)."""
        packs = [read_pack(path, bundled=True) for path in self.bundled_dirs]
        for pack in packs:
            pack.mandatory = True
        return packs

    @staticmethod
    def _folders(root):
        if root is None or not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))

    def _installed_folders(self):
        return self._folders(self.install_dir)

    def _official_folders(self):
        return self._folders(self.official_dir)

    def _optional(self, folder, *, bundled, enabled):
        """An official or installed pack: its folder carries its id (read_pack checks it)."""
        pack = read_pack(folder, bundled=False, enabled=enabled)
        pack.bundled = bundled
        return pack

    def _duplicate(self, pack_id, where, seen):
        if pack_id in seen:
            article = "an" if seen[pack_id][0] in "aeiou" else "a"
            return (f"{where} pack {pack_id} uses the id of {article} {seen[pack_id]} pack; "
                    "a pack id may appear in one location only (rename or remove one)")
        seen[pack_id] = where
        return None

    def discover(self):
        """Every pack with its summary. A broken official or installed pack, or a duplicate id, is
        reported, not raised."""
        with self._lock:
            disabled = self._disabled()
            found, loaded, seen = [], [], {}
            for where, folders in (("core", self.bundled_dirs), ("official", self._official_folders()),
                                   ("installed", self._installed_folders())):
                for folder in folders:
                    fallback = {"id": folder.name, "name": folder.name, "description": "", "version": None,
                                "rating": None, "entries": None, "requires": {}, "valid": False,
                                "bundled": where != "installed", "mandatory": where == "core",
                                "origin": "bundled" if where == "official" else where,
                                "enabled": where == "core" or folder.name not in disabled}
                    if problem := self._duplicate(folder.name, where, seen):
                        found.append(fallback | {"enabled": False, "problems": [problem]})
                        continue
                    try:
                        pack = (read_pack(folder, bundled=True) if where == "core" else
                                self._optional(folder, bundled=where == "official", enabled=folder.name not in disabled))
                        pack.mandatory = where == "core"
                        loaded.append(pack)
                        found.append(pack.summary() | {"valid": True, "problems": []})
                    except (VocabularyError, OSError) as error:
                        found.append(fallback | {"enabled": where == "core", "problems": getattr(error, "problems", [str(error)])})
            try:
                build_registry(loaded)
            except VocabularyError as error:
                for summary in found:
                    summary["problems"].extend(problem for problem in error.problems
                        if re.search(rf"(?<![a-z0-9_]){re.escape(summary['id'])}(?=[: /;]|$)", problem))
            return found

    def _packs(self, overrides=None, exclude=()):
        """All packs as Pack objects, with optional per-id enabled overrides (official and installed).
        exclude leaves out installed folders. A broken pack or a duplicate id raises."""
        disabled = self._disabled()
        overrides = overrides or {}
        packs = self._bundled()
        seen = {pack.id: "bundled" for pack in packs}
        for where, folders in (("official", self._official_folders()), ("installed", self._installed_folders())):
            for folder in folders:
                if where == "installed" and folder.name in exclude:
                    continue
                if problem := self._duplicate(folder.name, where, seen):
                    raise VocabularyError(problem)
                enabled = overrides.get(folder.name, folder.name not in disabled)
                packs.append(self._optional(folder, bundled=where == "official", enabled=enabled))
        return packs

    def registry(self):
        """The merged registry of every enabled pack."""
        with self._lock:
            return build_registry(self._packs())

    # -- enable / disable / remove
    def _require_optional(self, pack_id):
        """An official or installed pack can be enabled and disabled; the core cannot."""
        validate_pack_id(pack_id)
        if any(read_pack(path, bundled=True).id == pack_id for path in self.bundled_dirs):
            raise VocabularyError(f"{pack_id} is bundled with the app and cannot be changed")
        if not ((self.install_dir / pack_id).is_dir()
                or self.official_dir is not None and (self.official_dir / pack_id).is_dir()):
            raise VocabularyError(f"{pack_id} is not installed")

    def _require_installed(self, pack_id):
        """Only a user-installed pack can be removed or replaced; bundled packs are read-only."""
        self._require_optional(pack_id)
        if not (self.install_dir / pack_id).is_dir():
            raise VocabularyError(f"{pack_id} is bundled with the app and cannot be removed; disable it instead")

    def _dependents(self, pack_id, packs):
        return sorted(pack["id"] for pack in packs if pack["enabled"] and pack_id in pack.get("requires", {}))

    def set_enabled(self, pack_id, enabled):
        with self._lock:
            self._require_optional(pack_id)
            packs = self._packs(overrides={pack_id: bool(enabled)})
            if not enabled and (dependents := self._dependents(pack_id, [pack.summary() for pack in packs])):
                raise VocabularyError(f"{pack_id} cannot be disabled; enabled packs require it: {', '.join(dependents)}")
            build_registry(packs)  # the new combination must load before it is saved
            disabled = self._disabled()
            (disabled.discard if enabled else disabled.add)(pack_id)
            self._write_disabled(disabled)

    def remove(self, pack_id):
        with self._lock:
            self._require_installed(pack_id)
            # Invalid unrelated packs must not prevent removing a broken installation.
            packs = [pack for pack in self.discover() if pack["origin"] != "installed" or pack["id"] != pack_id]
            if dependents := self._dependents(pack_id, packs):
                raise VocabularyError(f"{pack_id} cannot be removed; enabled packs require it: {', '.join(dependents)}")
            shutil.rmtree(self.install_dir / pack_id)
            disabled = self._disabled()
            if pack_id in disabled:
                disabled.discard(pack_id)
                self._write_disabled(disabled)

    # -- install / update
    def install_archive(self, data, *, replace=False, allow_downgrade=False, expected_id=None):
        """Install (or, with replace=True, update) a pack from ZIP bytes. Nothing changes unless the
        pack validates and every enabled pack still loads together with it. Replacing a pack with an
        older version also needs allow_downgrade=True."""
        with self._lock:
            if expected_id is not None:
                self._require_installed(expected_id)
            self.install_dir.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(dir=self.install_dir, prefix=".install-"))
            backup = None
            try:
                payload = staging / "payload"
                payload.mkdir()
                extract_archive(data, payload)
                if not (payload / "manifest.json").is_file():
                    raise VocabularyError("the archive has no manifest.json")
                manifest = _read_json(payload / "manifest.json", "manifest.json")
                if problems := _schema_problems("manifest", manifest, "manifest.json"):
                    raise VocabularyError(problems)
                pack_id = manifest["id"]
                if expected_id is not None and pack_id != expected_id:
                    raise VocabularyError(f"This ZIP contains {pack_id}, not {expected_id}. Choose the matching pack to update.")
                if any(pack.id == pack_id for pack in self._bundled()) or pack_id in {folder.name for folder in self._official_folders()}:
                    raise VocabularyError(f"{pack_id} is the id of a bundled pack")
                target = self.install_dir / pack_id
                if target.exists() and not replace:
                    raise VocabularyError(f"{pack_id} is already installed; update it instead")
                if target.exists() and not allow_downgrade:
                    try:
                        current = _read_json(target / "manifest.json", f"{pack_id}/manifest.json")
                        current_version = parse_version(current.get("version")) if isinstance(current, dict) else None
                    except (VocabularyError, ValueError):
                        current_version = None  # A broken installation may be repaired by a valid ZIP.
                    if current_version is not None and parse_version(manifest["version"]) < current_version:
                        raise VocabularyError(f"{pack_id} {manifest['version']} is older than the installed {current['version']}; "
                                              "allow the downgrade explicitly to install it")
                folder = staging / pack_id  # read_pack requires the folder to carry the pack id
                payload.rename(folder)
                enabled = pack_id not in self._disabled()
                others = self._packs(exclude={pack_id})
                # The pack must load with everything enabled, also when it is currently disabled.
                build_registry([*others, read_pack(folder, bundled=False, enabled=True)])
                new_pack = read_pack(folder, bundled=False, enabled=enabled)
                if target.exists():
                    backup = staging / "previous"
                    target.rename(backup)
                try:
                    folder.rename(target)
                except OSError:
                    if backup is not None:
                        backup.rename(target)
                        backup = None
                    raise
                return new_pack.summary() | {"enabled": enabled}
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as error:
                raise VocabularyError(f"Cannot read ZIP archive: {error}") from None
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def install_file(self, path, *, replace=False, allow_downgrade=False):
        path = Path(path)
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise VocabularyError(f"the archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
        return self.install_archive(path.read_bytes(), replace=replace, allow_downgrade=allow_downgrade)
