"""Vocabulary: the Core category files and the packs in each registered category folder.

Core (vocabulary/core/) is three files:
  scene_category_registry.json  {"categories": [{"category": "Spaces", "folder": "Spaces"}, ...]}: the source of truth
                                for which categories exist and where their packs live, in display order.
  category_definitions.json     [{"category", "description", "use_when"}]: what each category means.
  prompt_instructions.json      [{"category", "prompt_text"}]: what the scene writer is told about that category's
                                vocabulary; "{Category name}" in the text is replaced by the name.
Adding a category is one entry in each file plus its folder; nothing in the code names a category.

A pack is one JSON file in a registered folder, vocabulary/<folder>/<file>.json, with
  {"name": "Fantasy", "category": "Spaces", "entries": ["enchanted forest", "floating castle"]}
and optionally "description": a short note from the pack's author on what the pack is for and how its entries are
written, which the scene writer reads with the pack, "people": how many people every entry of the pack needs, and
"always": true for a pack every run uses without being selected (a built-in catalog a run deals from, such as the
places dealt to each image: dataset/v2/scenes/places.py).
An entry is a text, or {"text": ..., "people": n} when that one entry needs a different number of people (an entry
that needs more people than a run's cast is never offered to it). All are optional: a pack of plain texts needs no
count. Instead of "entries" a pack may hold "groups": [{"group": "kitchen", "words": ["cooking", "kitchen"],
"entries": [...]}, ...]: entries under a name and the words a request uses for them, which a search counts
(features/vocabulary/retrieval.py); "worlds" lists the worlds its entries fit (options.dataset.WORLDS; every world when
it gives none), "people" how many people its entries need (over the pack's; one pack can hold solo, couple and group
entries), and "adult_default": true marks a group preferred for adult requests that name no place. Every entry
is in one group only, and the pack's entries are all its groups' entries. An entry may also name another pack or category in square brackets, a slot ("holding [Kitchen-and-Dining]",
"[Furniture: armchair]"): a run uses it only when that pack or category is selected, and the scene writer takes a
fitting entry from it (dataset/v2/scenes/slots.py). Each pack lists the packs its slots name ("links"), so the
Library can show packs that work together. category is the folder's registered category. Its id is "<folder>/<file name without .json>". Each file is read
on its own: a broken file is reported with its reason and every other pack still loads.

Imported packs live in the user's own data folder, data/vocabulary/<folder>/<file>.json, in exactly the same format;
their id is "data/<folder>/<file name without .json>" and their source is "imported" (built-in packs: "built-in").
import_pack() checks an uploaded pack and saves it there, in the folder of its category.

The user selects packs by hand; vocabulary_prompt() turns the selected ones into the scene writer's vocabulary
section, grouped by category with that category's Core instruction. Nothing is selected or matched automatically.
"""

import json
from pathlib import Path

import re

from ...config import PROJECT_ROOT
from ...json_store import atomic_json
from ...options.dataset import WORLDS

ROOT = PROJECT_ROOT / "vocabulary"
USER_ROOT = PROJECT_ROOT / "data" / "vocabulary"
USER_PREFIX = "data/"
REGISTRY = "scene_category_registry.json"
DEFINITIONS = "category_definitions.json"
INSTRUCTIONS = "prompt_instructions.json"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_TEXT = 300
MAX_PEOPLE = 20
PACK_KEYS = {"name", "category"}
CONTENT_KEYS = ("entries", "groups")
OPTIONAL_PACK_KEYS = {"description", "people", "always"}
ENTRY_KEYS = {"text"}
OPTIONAL_ENTRY_KEYS = {"people"}
GROUP_KEYS = {"group", "words", "entries"}
OPTIONAL_GROUP_KEYS = {"adult_default", "worlds", "people"}
MAX_WORDS = 100


# A slot: [Pack or Category] or [Pack or Category: wanted words]. Names ignore case, spaces, hyphens and "&" written as
# "and", so a pack's file name works as well as its name ([Kitchen-and-Dining] is the pack "Kitchen & Dining").
SLOT = re.compile(r"\[([^\[\]:]+)(?::([^\[\]]*))?\]")


def slot_key(name):
    return re.sub(r"[^a-z0-9]", "", str(name).casefold().replace("&", "and"))


def has_slot(text):
    return bool(SLOT.search(str(text)))


def pack_links(packs):
    """Each pack's slots with the packs they name: {pack id: [{"slot": name as written, "packs": [ids]}]}, for the
    packs that have slots. A slot names a pack by its name or file name, or every pack of a category by its name."""
    names = {}
    for pack in packs:
        for key in {slot_key(pack["name"]), slot_key(pack["id"].rsplit("/", 1)[-1]), slot_key(pack["category"])}:
            names.setdefault(key, []).append(pack["id"])
    links = {}
    for pack in packs:
        slots = dict.fromkeys(" ".join(match.group(1).split()) for entry in pack["entries"] for match in SLOT.finditer(entry))
        rows = [{"slot": slot, "packs": [ident for ident in names.get(slot_key(slot), []) if ident != pack["id"]]}
                for slot in slots]
        if rows:
            links[pack["id"]] = rows
    return links


class CatalogError(ValueError):
    """A selection names a pack the catalog does not have."""


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_categories(root=None):
    """The registered categories, in registry order, each with its folder, definition and Core instruction.
    Core itself must be readable: without it nothing can be shown. Returns (categories, problems)."""
    core = Path(root if root is not None else ROOT) / "core"
    registry = _json(core / REGISTRY)
    rows = registry.get("categories") if isinstance(registry, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f'{REGISTRY} must be {{"categories": [...]}}.')
    definitions = {row.get("category"): row for row in _json(core / DEFINITIONS) if isinstance(row, dict)}
    instructions = {row.get("category"): row for row in _json(core / INSTRUCTIONS) if isinstance(row, dict)}
    categories, problems, seen = [], [], set()
    for row in rows:
        name, folder = (row.get("category"), row.get("folder")) if isinstance(row, dict) else (None, None)
        if not isinstance(name, str) or not name.strip() or not isinstance(folder, str) or not folder.strip() \
                or "/" in folder or "\\" in folder or folder in (".", ".."):
            raise ValueError(f"{REGISTRY}: each category needs a category name and a plain folder name.")
        if name in seen:
            raise ValueError(f'{REGISTRY}: "{name}" is registered twice.')
        seen.add(name)
        definition, instruction = definitions.get(name, {}), instructions.get(name, {})
        for missing, source in ((not definition, DEFINITIONS), (not instruction.get("prompt_text"), INSTRUCTIONS)):
            if missing:
                problems.append({"file": f"core/{source}", "problem": f'no entry for the category "{name}"'})
        categories.append({"id": name, "name": name, "folder": folder,
                           "description": str(definition.get("description", "")),
                           "use_when": str(definition.get("use_when", "")),
                           "instruction": str(instruction.get("prompt_text", "")).replace("{" + name + "}", name)})
    return categories, problems


def _text(value, where):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f"{where} must be text of 1 to {MAX_TEXT} characters.")
    return " ".join(value.split())


def _parse(text):
    try:
        return json.loads(text)
    except ValueError as error:
        raise ValueError(f"not valid JSON ({error})") from None


def _people(value, where):
    if type(value) is not int or not 1 <= value <= MAX_PEOPLE:
        raise ValueError(f"{where} must be a whole number of people from 1 to {MAX_PEOPLE}.")
    return value


def _words_of(value, where):
    """A group's words: 1 to MAX_WORDS short texts, compared without case."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_WORDS:
        raise ValueError(f"{where} must be a list of 1 to {MAX_WORDS} texts")
    return list(dict.fromkeys(_text(item, where).casefold() for item in value))


def _entries(values, where, every):
    """(entries, people) of one list of entries; a repeated entry (ignoring case) is the same entry."""
    if not isinstance(values, list) or not values or len(values) > MAX_ENTRIES:
        raise ValueError(f"{where} must be a list of 1 to {MAX_ENTRIES} texts")
    entries, people, seen = [], {}, set()
    for number, value in enumerate(values, 1):
        at, need = f"{where}[{number}]", every
        if isinstance(value, dict):
            if not ENTRY_KEYS <= set(value) or set(value) - ENTRY_KEYS - OPTIONAL_ENTRY_KEYS:
                raise ValueError(f'{at} must be a text, or {{"text": ..., "people": n}}')
            if "people" in value:
                need = _people(value["people"], f"{at}.people")
            value = value["text"]
        entry = _text(value, at)
        if entry.casefold() not in seen:
            seen.add(entry.casefold())
            entries.append(entry)
            if need is not None:
                people[entry] = need
    return entries, people


def _groups(values, every):
    """(entries, people, groups) of a pack's groups: each {"name", "words", "entries"} (plus "worlds", "people" and
    "adult_default"), names unique, every entry in one group only; a group's people count is its entries' unless one
    gives its own, the pack's when it gives none."""
    if not isinstance(values, list) or not values:
        raise ValueError("groups must be a list of 1 or more groups")
    entries, people, groups, names, seen = [], {}, [], set(), set()
    for number, group in enumerate(values, 1):
        where = f"groups[{number}]"
        if not isinstance(group, dict) or not GROUP_KEYS <= set(group) or set(group) - GROUP_KEYS - OPTIONAL_GROUP_KEYS:
            raise ValueError(f'{where} needs exactly "group", "words" and "entries", and optionally "worlds", '
                             '"people" and "adult_default"')
        if "adult_default" in group and type(group["adult_default"]) is not bool:
            raise ValueError(f"{where}.adult_default must be true or false")
        if "worlds" in group and (not isinstance(group["worlds"], list) or not group["worlds"]
                                  or any(world not in WORLDS for world in group["worlds"])):
            raise ValueError(f"{where}.worlds must list worlds from: {', '.join(WORLDS)}")
        name = _text(group["group"], f"{where}.group")
        if name.casefold() in names:
            raise ValueError(f'{where}: the group "{name}" is listed twice')
        names.add(name.casefold())
        count = _people(group["people"], f"{where}.people") if "people" in group else None
        own, needs = _entries(group["entries"], f"{where}.entries", every if count is None else count)
        taken = next((entry for entry in own if entry.casefold() in seen), None)
        if taken:
            raise ValueError(f'{where}: "{taken}" is already in another group; every entry belongs to one group')
        seen.update(entry.casefold() for entry in own)
        entries += own
        people.update(needs)
        groups.append({"name": name, "words": _words_of(group["words"], f"{where}.words"), "entries": own,
                       **({"worlds": list(dict.fromkeys(group["worlds"]))} if "worlds" in group else {}),
                       **({"people": count} if count is not None else {}),
                       **({"adult_default": True} if group.get("adult_default") else {})})
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"a pack holds at most {MAX_ENTRIES} entries")
    return entries, people, groups


def _checked(data):
    """(name, category, entries, description, people, groups, always) of pack data: name, category and either entries
    or groups, plus an optional description ("" without one), people and always. entries are texts (a grouped pack's
    are all its groups' entries); people is {entry: how many people it needs} for the entries that say so, themselves
    or through the pack's own "people" ({} for a pack of plain texts); groups is [] for a pack of entries. Raises
    ValueError naming the first problem."""
    content = [key for key in CONTENT_KEYS if isinstance(data, dict) and key in data]
    if not isinstance(data, dict) or not PACK_KEYS <= set(data) or len(content) != 1 \
            or set(data) - PACK_KEYS - OPTIONAL_PACK_KEYS - set(CONTENT_KEYS):
        raise ValueError('needs exactly "name", "category" and either "entries" or "groups", and optionally '
                         '"description", "people" and "always"')
    if "always" in data and type(data["always"]) is not bool:
        raise ValueError("always must be true or false")
    if not isinstance(data["category"], str):
        raise ValueError("category must be text")
    every = _people(data["people"], "people") if "people" in data else None
    if content == ["groups"]:
        entries, people, groups = _groups(data["groups"], every)
    else:
        (entries, people), groups = _entries(data["entries"], "entries", every), []
    description = _text(data["description"], "description") if "description" in data else ""
    return (_text(data["name"], "name"), data["category"], entries, description, people, groups,
            data.get("always") is True)


def read_pack(path, category, folder, prefix=""):
    """One pack file in a registered category folder, checked. Raises ValueError naming the first problem."""
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise ValueError(f"not valid JSON ({error})") from None
    name, declared, entries, description, people, groups, always = _checked(_parse(text))
    if declared != category:
        raise ValueError(f'category is "{declared}", but the {folder} folder holds "{category}" packs')
    return {"id": f"{prefix}{folder}/{path.stem}", "name": name, "category": category, "description": description,
            "entries": entries, **({"people": people} if people else {}), **({"groups": groups} if groups else {}),
            **({"always": True} if always else {}), "source": "imported" if prefix else "built-in"}


def _roots(root, user_root):
    """The built-in and imported vocabulary folders: None means the app's own (read when called, so tests can point
    them elsewhere); user_root=False reads no imported packs."""
    return Path(root if root is not None else ROOT), (None if user_root is False
                                                     else Path(user_root if user_root is not None else USER_ROOT))


def load_catalog(root=None, user_root=None):
    """{"categories", "packs", "problems"}: every pack that loads, by category (registry order), built-in packs before
    imported ones, then file name, and one {"file", "problem"} row for each file (or Core entry) that does not. Only
    Core can raise."""
    root, user_root = _roots(root, user_root)
    categories, problems = read_categories(root)
    packs = []
    for category in categories:
        for base, prefix in ((root, ""), (user_root, USER_PREFIX)):
            folder = base / category["folder"] if base else None
            if folder is None or not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json"), key=lambda item: item.name.casefold()):
                try:
                    packs.append(read_pack(path, category["id"], category["folder"], prefix))
                except (OSError, ValueError) as error:
                    problems.append({"file": f"{prefix}{category['folder']}/{path.name}", "problem": str(error)})
    links = pack_links(packs)
    packs = [{**pack, "links": links[pack["id"]]} if pack["id"] in links else pack for pack in packs]
    return {"categories": categories, "packs": packs, "problems": problems}


def pack_file_stem(filename, name):
    """The file name an imported pack is saved under: the uploaded file's name (or the pack name), words joined by
    hyphens."""
    base = Path(str(filename or "")).name
    base = base[:-5] if base.lower().endswith(".json") else base
    words = re.findall(r"[A-Za-z0-9]+", base) or re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        raise ValueError("the pack needs a file name or a name with letters or digits")
    return "-".join(words)[:120]


def import_pack(filename, text, root=None, user_root=None):
    """Check one uploaded pack and save it as data/vocabulary/<its category's folder>/<file>.json, replacing an
    earlier import of the same file. Returns the saved pack. Raises ValueError naming the first problem."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"a pack must be a JSON text file of at most {MAX_FILE_BYTES // (1024 * 1024)} MB")
    root, user_root = _roots(root, user_root)
    if user_root is None:
        raise ValueError("there is no folder for imported packs")
    data = _parse(text)
    name, category, entries, description, people, groups, always = _checked(data)
    categories, _ = read_categories(root)
    match = next((row for row in categories if row["id"] == category), None)
    if match is None:
        raise ValueError(f'"{category}" is not a vocabulary category')
    stem = pack_file_stem(filename, name)
    path = user_root / match["folder"] / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    every = data.get("people")  # saved as written: the pack's count, and an entry's own count when it differs
    own = lambda entry, base=every: {"text": entry, "people": people[entry]} if people.get(entry, base) != base else entry
    content = ({"groups": [{"group": group["name"], "words": group["words"],
                            "entries": [own(entry, group.get("people", every)) for entry in group["entries"]],
                            **({"worlds": group["worlds"]} if "worlds" in group else {}),
                            **({"people": group["people"]} if "people" in group else {}),
                            **({"adult_default": True} if group.get("adult_default") else {})} for group in groups]}
               if groups else {"entries": [own(entry) for entry in entries]})
    atomic_json(path, {"name": name, "category": category, **({"description": description} if description else {}),
                       **({"people": every} if every is not None else {}), **({"always": True} if always else {}),
                       **content})
    return read_pack(path, category, match["folder"], USER_PREFIX)


def catalog_for(selection, root=None, user_root=None):
    """The catalog a run needs: the built-in packs when it selects no pack (they hold the always-on catalogs; the
    user's own folder is not read), else everything."""
    packs = selection.get("packs") if isinstance(selection, dict) else selection
    return load_catalog(root, False if not packs else user_root)


def always_on(catalog, category):
    """The always-on packs of one category ("always": true), built-in ones first."""
    return [pack for pack in catalog["packs"] if pack["category"] == category and pack.get("always")]


# ---------------------------------------------------------------- one run's selection

def validate_selection(catalog, selection):
    """The run's selection {"packs": [pack ids]} (or the bare list), checked against the catalog. Raises
    CatalogError."""
    selection = selection if selection is not None else {"packs": []}
    if isinstance(selection, list):
        selection = {"packs": selection}
    if not isinstance(selection, dict) or set(selection) != {"packs"} or not isinstance(selection["packs"], list) \
            or any(not isinstance(item, str) for item in selection["packs"]):
        raise CatalogError('Vocabulary selection must be a list of pack ids.')
    known = {pack["id"] for pack in catalog["packs"]}
    for ident in selection["packs"]:
        if ident not in known:
            raise CatalogError(f'The vocabulary pack "{ident}" is not installed (or could not be read).')
    return {"packs": list(dict.fromkeys(selection["packs"]))}


def record(catalog, selection):
    """What a run records of its selection: each pack's id, name, category and entry count."""
    packs = {pack["id"]: pack for pack in catalog["packs"]}
    return {"packs": [{key: packs[ident][key] for key in ("id", "name", "category")}
                      | {"entries": len(packs[ident]["entries"])} for ident in selection["packs"]]}


def selected_vocabulary(catalog, selection):
    """[{"category", "instruction", "packs": [{"name", "description", "entries"}]}] for the categories that have a
    selected pack, in registry order; categories without one are left out."""
    chosen = set(selection["packs"])
    groups = []
    for category in catalog["categories"]:
        packs = [{"name": pack["name"], "description": pack.get("description", ""), "entries": list(pack["entries"]),
                  **({"people": dict(pack["people"])} if pack.get("people") else {})}
                 for pack in catalog["packs"]
                 if pack["category"] == category["id"] and pack["id"] in chosen]
        if packs:
            groups.append({"category": category["name"], "instruction": category["instruction"], "packs": packs})
    return groups


def vocabulary_prompt(groups):
    """The SELECTED VOCABULARY section of the scene writer's prompt ("" when nothing is selected)."""
    if not groups:
        return ""
    blocks = []
    for group in groups:
        # A pack with a description is listed under it, so its note stays with its own entries; packs without one
        # share a plain list. An entry in two packs is listed once.
        seen, lines = set(), []
        for pack in sorted(group["packs"], key=lambda pack: not pack.get("description")):
            entries = [entry for entry in pack["entries"] if entry not in seen]
            seen.update(entries)
            if pack.get("description") and entries:
                lines.append(f'Pack "{pack["name"]}" (its author\'s note: {pack["description"]}):')
            elif entries and lines and any(other.get("description") for other in group["packs"]):
                lines.append(f'Pack "{pack["name"]}":')
            lines.extend(entries)
        blocks.append(f"{group['category']}\nCore instruction:\n{group['instruction']}\n\nAvailable vocabulary:\n"
                      + "\n".join(lines))
    return "SELECTED VOCABULARY:\n\n" + "\n\n".join(blocks)
