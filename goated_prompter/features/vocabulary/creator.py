"""Editable drafts and data-only ZIPs. PackManager remains the validation/install authority."""

import io
import json
from pathlib import Path
import re
import tempfile
import threading
import uuid
import zipfile

from ...json_store import MAX_STORE_BYTES, atomic_json
from ...options.vocabulary import MAX_DRAFT_DEPTH, MAX_DRAFT_NODES
from .explorer import inspect_registry
from .packs import (EXTRA_FILES, MAX_ARCHIVE_BYTES, MAX_FILE_BYTES, MAX_FILES, MAX_UNPACKED_BYTES,
                    VocabularyError, extract_archive, pack_schemas, read_pack, schema_issues, validate_pack_id)


def document_shape(document):
    """Bound draft storage and filenames even when the pack itself is not yet valid."""
    pending, nodes = [(document, 0)], 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > MAX_DRAFT_DEPTH or nodes > MAX_DRAFT_NODES:
            raise VocabularyError("Draft is too deeply nested or has too many values.")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    if not isinstance(document, dict) or set(document) - {"manifest", "files", "extras"}:
        raise VocabularyError("Expected a draft with manifest, files and optional supporting text files.")
    if not isinstance(document.get("manifest"), dict) or not isinstance(document.get("files"), dict):
        raise VocabularyError("Manifest and entry files must be objects.")
    manifest = document["manifest"]
    for key in ("id", "name", "description", "version", "license", "rating"):
        if key in manifest and not isinstance(manifest[key], str):
            raise VocabularyError(f"Manifest {key} must be text.")
    for key in ("files", "categories"):
        if key in manifest and (not isinstance(manifest[key], list) or any(
                not isinstance(item, str if key == "files" else dict) for item in manifest[key])):
            raise VocabularyError(f"Manifest {key} has an invalid editor structure.")
    extras = document.get("extras", {})
    if not isinstance(extras, dict) or len(document["files"]) + len(extras) + 1 > MAX_FILES:
        raise VocabularyError("Too many draft files or invalid supporting files.")
    names = ["manifest.json", *document["files"], *extras]
    if len({name.casefold() for name in names}) != len(names):
        raise VocabularyError("Draft filenames must be unique (ignoring case).")
    for name, content in document["files"].items():
        if not re.fullmatch(r"[a-z0-9_]+\.json", name) or not isinstance(content, dict):
            raise VocabularyError(f"{name}: use a plain entry JSON filename and an object.")
        if not isinstance(content.get("entries"), list) or any(not isinstance(entry, dict) for entry in content["entries"]):
            raise VocabularyError(f"{name}: an entry file needs an entries list of objects.")
        for entry in content["entries"]:
            if any(key in entry and not isinstance(entry[key], str) for key in ("id", "name", "category", "description", "rating")):
                raise VocabularyError(f"{name}: entry identifiers, names and ratings must be text.")
    for name, text in extras.items():
        if not EXTRA_FILES.fullmatch(name) or not isinstance(text, str):
            raise VocabularyError("Only README, LICENSE and CHANGELOG supporting text is allowed.")
    total = 0
    for _name, data in document_files(document):
        if len(data) > MAX_FILE_BYTES:
            raise VocabularyError("A draft file exceeds the pack file size limit.")
        total += len(data)
    if total > MAX_UNPACKED_BYTES:
        raise VocabularyError("Draft exceeds the unpacked pack size limit.")
    return document


def document_files(document):
    for name, value in {"manifest.json": document["manifest"], **document["files"]}.items():
        yield name, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    for name, text in document.get("extras", {}).items():
        yield name, text.encode("utf-8")


class PackCreator:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.state_file.parent / "drafts"
        self._lock = threading.RLock()

    def protected(self, ident):
        return any(pack["id"] == ident and pack["bundled"] for pack in self.manager.discover())

    def schemas(self):
        return pack_schemas()

    def _path(self, ident):
        if not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise VocabularyError("Invalid draft identifier.")
        return self.root / f"{ident}.json"

    def drafts(self):
        with self._lock:
            rows = []
            for path in sorted(self.root.glob("*.json")):
                try:
                    record = self.open(path.stem)
                    manifest = record["document"]["manifest"]
                    rows.append({"id": path.stem, "revision": record["revision"], "name": manifest.get("name", "Untitled draft"),
                                 "pack_id": manifest.get("id", "")})
                except (OSError, ValueError, KeyError):
                    rows.append({"id": path.stem, "name": "Unreadable draft", "error": "Draft could not be read. Restore its backup."})
            return rows

    def open(self, ident):
        path = self._path(ident)
        try:
            if path.is_symlink() or path.stat().st_size > MAX_STORE_BYTES:
                raise VocabularyError("Draft is a link or exceeds the storage limit.")
            with self._lock, path.open(encoding="utf-8") as handle:
                record = json.load(handle)
            if record["id"] != ident or type(record["revision"]) is not int or record["revision"] < 1:
                raise ValueError("Invalid draft record")
            document_shape(record["document"])
            return record
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise VocabularyError("Draft is missing or unreadable. It has not been overwritten; restore its backup.") from None

    def save(self, document, ident=None, revision=None):
        document_shape(document)
        if self.protected(document["manifest"].get("id")):
            raise VocabularyError("Bundled packs are read-only. Create a pack with a new ID instead.")
        with self._lock:
            previous = self.open(ident) if ident else None
            if previous and (type(revision) is not int or revision != previous["revision"]):
                raise VocabularyError("Draft changed in another editor. Reopen it before saving; your changes have not overwritten it.")
            ident = ident or uuid.uuid4().hex
            record = {"id": ident, "revision": previous["revision"] + 1 if previous else 1, "document": document}
            atomic_json(self._path(ident), record)
            return record

    def _folder_document(self, folder, pack):
        return {"manifest": pack.manifest,
                "files": {name: json.loads((folder / name).read_text(encoding="utf-8")) for name in pack.manifest["files"]},
                "extras": {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir() if EXTRA_FILES.fullmatch(path.name)}}

    def import_archive(self, data):
        # Use the exact same data-only ZIP extraction protections as installation.
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            try:
                extract_archive(data, folder)
                pack = read_pack(folder, bundled=True)
                document = document_shape(self._folder_document(folder, pack))
            except (zipfile.BadZipFile, RuntimeError, EOFError, UnicodeError) as error:
                raise VocabularyError(f"Cannot import pack ZIP: {error}") from None
        return {"document": document, "read_only": self.protected(pack.id)}

    def installed_document(self, ident, origin=None):
        view = self.manager.inspect_pack(ident, origin)
        pack = view["loaded"].get(ident)
        if pack is None:
            raise VocabularyError(view["problems"] or "Pack could not be loaded.")
        try:
            document = document_shape(self._folder_document(pack.path, pack))
        except UnicodeError:
            raise VocabularyError("Supporting pack files must be UTF-8 text to open in the editor.") from None
        return {"document": document, "read_only": pack.bundled}

    def _issues(self, document):
        issues = schema_issues("manifest", document["manifest"], ("manifest",))
        for name, content in document["files"].items():
            issues.extend(schema_issues("entry", content, ("files", name)))
        if self.protected(document["manifest"].get("id")):
            issues.append({"path": ["manifest", "id"], "message": "Bundled packs are read-only. Choose a new pack ID."})
        return issues

    def _semantic_issues(self, document, problems):
        issues = []
        for message in problems:
            path = ["manifest", "requires"]
            reference = re.search(r"reference ([a-z][a-z0-9_]*):", message)
            if reference and reference[1] != document["manifest"]["id"] and reference[1] not in document["manifest"].get("requires", {}):
                message += f". Declare a dependency on {reference[1]} and verify that the pack and reference exist."
            for name, content in document["files"].items():
                for index, entry in enumerate(content.get("entries", [])):
                    if entry.get("id") and entry["id"] in message:
                        field = ("id" if "duplicate id" in message or "must start with" in message else "category" if "category" in message else
                                 "extends" if "inherit" in message or "extends" in message else "rating" if "rated" in message else "components")
                        path = ["files", name, "entries", index, field]
            issues.append({"path": path, "message": message})
        return issues

    def validate(self, document, sample=None):
        document_shape(document)
        issues = self._issues(document)
        if issues:
            return {"valid": False, "issues": issues}
        manifest = document["manifest"]
        try:
            validate_pack_id(manifest["id"])
            with tempfile.TemporaryDirectory() as scratch:
                folder = Path(scratch) / manifest["id"]
                folder.mkdir()
                for name, data in document_files(document):
                    (folder / name).write_bytes(data)
                registry = self.manager.draft_registry(read_pack(folder, bundled=False))
                result = {"valid": True, "issues": [], "entries": len(registry)}
                if sample is not None:
                    result["retrieval"] = inspect_registry(registry, **sample)
                return result
        except VocabularyError as error:
            return {"valid": False, "issues": self._semantic_issues(document, error.problems)}

    def export(self, document):
        result = self.validate(document)
        if not result["valid"]:
            raise VocabularyError([issue["message"] for issue in result["issues"]])
        output = io.BytesIO()
        # Stored data avoids producing high-ratio archives rejected by the existing ZIP safety rules.
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in document_files(document):
                archive.writestr(name, data)
        data = output.getvalue()
        if len(data) > MAX_ARCHIVE_BYTES:
            raise VocabularyError("Export exceeds the pack archive size limit.")
        return data

    def install(self, document, update_id=None):
        data = self.export(document)
        return self.manager.install_archive(data, replace=update_id is not None, expected_id=update_id)

    def references(self):
        rows, categories, problems = {}, {}, []
        for summary in self.manager.discover():
            view = self.manager.inspect_pack(summary["id"], summary["origin"])
            problems.extend(view["problems"])
            registry = view["registry"]
            for pack in view["loaded"].values():
                for category in pack.manifest.get("categories", []):
                    categories[category["id"]] = category
                for _file, raw in pack.entries:
                    entry = registry.resolved(raw["id"]) if registry is not None else raw
                    rows[raw["id"]] = {"id": raw["id"], "name": raw["name"], "pack": pack.id,
                                       "category": raw["category"], "rating": entry.get("rating", pack.manifest["rating"]),
                                       "capability": "capability" in entry["components"],
                                       "posture": "self" in entry["components"].get("spatial", {}).get("participants", {}), "enabled": pack.enabled}
        return {"entries": list(rows.values()), "categories": list(categories.values()), "problems": list(dict.fromkeys(problems))}
