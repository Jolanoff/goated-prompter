"""Slots: an entry of any category may name another pack or category in square brackets (vocabulary/catalog.py):

    "kneeling by the table, holding [Kitchen-and-Dining]"   an entry of the pack Kitchen & Dining
    "seated in [Objects & Props]"                            an entry of any selected pack of that category
    "seated in [Furniture: armchair]"                        one of that pack's entries that says "armchair"

An entry is used only when every slot in it names a selected pack or category (and, with wanted words, one of its
entries says them); otherwise it is left out before anything else (only_fillable). A kept slot stays as written: the
writer reads the named pack among the selected vocabulary and takes a fitting entry from it, as the request allows.
Entries with no slot are untouched: packs without brackets work as before.
"""

from ....vocabulary.catalog import SLOT, has_slot, slot_key
from .checks import _words


def slot_sources(groups):
    """{slot_key(name): [entries]}: every selected pack by its name and every selected category by its name. An entry
    that holds a slot itself never counts as one a slot can take (a slot reaches one level deep)."""
    sources = {}
    for group in groups:
        for pack in group["packs"]:
            entries = [entry for entry in pack["entries"] if not has_slot(entry)]
            sources.setdefault(slot_key(group["category"]), []).extend(entries)
            sources.setdefault(slot_key(pack["name"]), []).extend(entries)
    return {name: list(dict.fromkeys(entries)) for name, entries in sources.items()}


def fillable(entry, sources):
    """Whether every slot of the entry names a selected pack or category that has an entry with its wanted words."""
    for match in SLOT.finditer(entry):
        wanted = _words(match.group(2) or "")
        if not any(wanted <= _words(item) for item in sources.get(slot_key(match.group(1)), [])):
            return False
    return True


def only_fillable(groups):
    """The selected vocabulary without the entries that hold a slot nothing selected can fill; a pack or category left
    with no entry is left out."""
    sources, result = slot_sources(groups), []
    for group in groups:
        packs = []
        for pack in group["packs"]:
            entries = [entry for entry in pack["entries"] if fillable(entry, sources)]
            if entries:
                packs.append({**pack, "entries": entries})
        if packs:
            result.append({**group, "packs": packs})
    return result
