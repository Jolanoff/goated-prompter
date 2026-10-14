"""Phase 2: the data-only pack manager. Every test uses temporary folders; the bundled core is real."""

import io
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from goated_prompter.features.vocabulary.packs import (
    MAX_FILE_BYTES, PackManager, VocabularyError, build_registry, read_pack, satisfies)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "packs"


def pack_files(folder):
    return {path.name: path.read_bytes() for path in Path(folder).iterdir() if path.is_file()}


def archive(files, prefix=""):
    """ZIP bytes from {name: bytes or dict}; dicts are written as JSON."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            if isinstance(content, (dict, list)):
                content = json.dumps(content).encode()
            zipped.writestr(prefix + name, content)
    return buffer.getvalue()


def fixture(name, **changes):
    """A fixture pack's files, with manifest fields or whole files replaced."""
    files = pack_files(FIXTURES / name)
    manifest = json.loads(files["manifest.json"])
    manifest.update(changes.pop("manifest", {}))
    files["manifest.json"] = manifest
    files.update(changes)
    return files


def tiny_pack(pack_id, entries, requires=None, version="1.0.0", conflicts=None, categories=None, rating="general"):
    manifest = {"spec": 1, "id": pack_id, "name": pack_id.title(), "version": version, "rating": rating,
                "requires": requires if requires is not None else {"core": ">=1.0.0 <2.0.0"},
                "files": ["entries.json"]}
    if conflicts:
        manifest["conflicts"] = conflicts
    if categories:
        manifest["categories"] = categories
    return {"manifest.json": manifest, "entries.json": {"spec": 1, "entries": entries}}


def capability(entry_id, implies=None):
    return {"id": entry_id, "category": "capability", "name": entry_id,
            "components": {"capability": {"implies": implies} if implies else {}}}


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.manager = PackManager(self.root / "packs", self.root / "state.json")

    def installed(self):
        folder = self.root / "packs"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []

    def assertRejected(self, data, fragment, **kwargs):
        before = self.installed()
        with self.assertRaises(VocabularyError) as caught:
            self.manager.install_archive(data, **kwargs)
        self.assertIn(fragment, str(caught.exception))
        self.assertEqual(self.installed(), before, "a rejected install must leave nothing behind")
        return caught.exception


class Discovery(ManagerTest):
    def test_bundled_core_is_separate_and_always_enabled(self):
        packs = self.manager.discover()
        self.assertEqual([(pack["id"], pack["bundled"], pack["enabled"]) for pack in packs], [("core", True, True)])
        self.assertFalse((self.root / "packs").exists(), "discovery never creates the install folder")
        registry = self.manager.registry()
        self.assertIn("core:body.humanoid", registry)

    def test_core_cannot_be_disabled_removed_or_replaced(self):
        for action in (lambda: self.manager.set_enabled("core", False), lambda: self.manager.remove("core")):
            with self.assertRaises(VocabularyError):
                action()
        self.assertRejected(archive(tiny_pack("core", [])), "bundled pack")

    def test_broken_installed_pack_is_reported_not_raised(self):
        folder = self.root / "packs" / "broken"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{not json", encoding="utf-8")
        broken = [pack for pack in self.manager.discover() if pack["id"] == "broken"][0]
        self.assertFalse(broken["enabled"])
        self.assertTrue(broken["problems"])


class Install(ManagerTest):
    def test_install_merges_entries_and_resolves_inheritance(self):
        summary = self.manager.install_archive(archive(fixture("fantasy")))
        self.assertEqual((summary["id"], summary["enabled"], summary["bundled"]), ("fantasy", True, False))
        registry = self.manager.registry()
        dragon = registry.resolved("fantasy:creature.dragon")["components"]["body"]
        # quadruped (from core, via vertebrate) + wings + tail, written once each
        for resource in ("head", "leg.front_left", "wing.left", "tail"):
            self.assertIn(resource, dragon["resources"])
        self.assertIn("core:size.huge", dragon["provides"])
        self.assertIn("core:locomotion.flight", dragon["provides"])
        self.assertEqual(registry.owner("fantasy:creature.dragon"), "fantasy")
        self.assertIn("fantasy:creature.dragon", registry.by_category("creature"))
        self.assertIn("core:position.from_behind", registry.find("kneeling behind"))

    def test_downgrade_needs_its_own_flag(self):
        self.manager.install_archive(archive(fixture("fantasy", manifest={"version": "0.5.0"})))
        older = archive(fixture("fantasy", manifest={"version": "0.4.0"}))
        self.assertRejected(older, "older than the installed 0.5.0", replace=True)
        self.manager.install_archive(older, replace=True, allow_downgrade=True)
        self.assertEqual(self.manager.registry().packs["fantasy"].manifest["version"], "0.4.0")
        same = archive(fixture("fantasy", manifest={"version": "0.4.0"}))
        self.manager.install_archive(same, replace=True)  # reinstalling the same version is not a downgrade

    def test_archive_with_one_top_level_folder_is_accepted(self):
        self.manager.install_archive(archive(fixture("fantasy"), prefix="fantasy-main/"))
        self.assertEqual(self.installed(), ["fantasy"])

    def test_update_needs_replace_and_keeps_the_old_pack_when_the_new_one_fails(self):
        self.manager.install_archive(archive(fixture("fantasy")))
        self.assertRejected(archive(fixture("fantasy", manifest={"version": "0.2.0"})), "already installed")
        broken = fixture("fantasy", manifest={"version": "0.3.0"})
        broken["creatures.json"] = {"spec": 1, "entries": [{"id": "fantasy:bad", "category": "nope", "name": "x", "components": {}}]}
        with self.assertRaises(VocabularyError):
            self.manager.install_archive(archive(broken), replace=True)
        self.assertEqual(self.manager.registry().packs["fantasy"].manifest["version"], "0.1.0")
        self.manager.install_archive(archive(fixture("fantasy", manifest={"version": "0.2.0"})), replace=True)
        self.assertEqual(self.manager.registry().packs["fantasy"].manifest["version"], "0.2.0")

    def test_invalid_schema_is_rejected(self):
        missing_version = fixture("fantasy")
        del missing_version["manifest.json"]["version"]
        self.assertRejected(archive(missing_version), "version")
        unknown_key = fixture("fantasy")
        entries = json.loads(unknown_key["abilities.json"])
        entries["entries"][0]["attributes"] = {"anything": True}
        unknown_key["abilities.json"] = entries
        self.assertRejected(archive(unknown_key), "attributes")

    def test_duplicate_ids_and_wrong_prefixes_are_rejected(self):
        twice = tiny_pack("dupes", [capability("dupes:thing"), capability("dupes:thing")])
        self.assertRejected(archive(twice), "duplicate id dupes:thing")
        foreign = tiny_pack("thief", [capability("core:limb.hand")])
        self.assertRejected(archive(foreign), 'must start with "thief:"')

    def test_missing_dependency_and_unsatisfied_version_are_rejected(self):
        self.assertRejected(archive(fixture("fantasy", manifest={"requires": {"elves": ">=1.0.0"}})), "requires elves")
        self.assertRejected(archive(fixture("fantasy", manifest={"requires": {"core": ">=2.0.0"}})), "1.0.0 is enabled")

    def test_declared_conflicts_are_rejected(self):
        self.manager.install_archive(archive(fixture("fantasy")))
        rival = tiny_pack("scifi", [capability("scifi:laser")], conflicts=["fantasy"])
        self.assertRejected(archive(rival), "conflicts with fantasy")

    def test_inheritance_cycles_and_contradictions_are_rejected(self):
        loop = tiny_pack("loop", [{**capability("loop:a"), "extends": ["loop:b"]}, {**capability("loop:b"), "extends": ["loop:a"]}])
        self.assertRejected(archive(loop), "inheritance cycle")
        def posture(entry_id, orientation):
            return {"id": entry_id, "category": "posture", "name": entry_id,
                    "components": {"spatial": {"participants": {"self": {"orientation": orientation}}}}}
        split = tiny_pack("split", [posture("split:up", "upright"), posture("split:down", "face_down"),
                                    {"id": "split:both", "category": "posture", "name": "both", "extends": ["split:up", "split:down"],
                                     "components": {}}])
        self.assertRejected(archive(split), "inherited orientation differs")
        forbids = tiny_pack("forbid", [{"id": "forbid:a", "category": "action", "name": "a", "components": {
            "participants": {"slots": {"x": {"count": 1, "kind": "being"}}},
            "requirements": {"participants": {"x": {"all_of": ["core:limb.hand"], "none_of": ["core:limb.hand"]}}}}}])
        self.assertRejected(archive(forbids), "both requires and forbids")

    def test_references_must_exist_and_stay_in_required_packs(self):
        dangling = tiny_pack("dangling", [capability("dangling:x", ["core:limb.tentacle"])])
        self.assertRejected(archive(dangling), "core:limb.tentacle does not exist")
        self.manager.install_archive(archive(fixture("fantasy")))
        # Uses fantasy's capability but only requires core.
        sneaky = tiny_pack("sneaky", [capability("sneaky:x", ["fantasy:magic"])])
        self.assertRejected(archive(sneaky), "which sneaky does not require")
        honest = tiny_pack("honest", [capability("honest:x", ["fantasy:magic"])],
                           requires={"core": ">=1.0.0", "fantasy": ">=0.1.0"})
        self.manager.install_archive(archive(honest))
        self.assertIn("honest:x", self.manager.registry())

    def test_object_completeness_references_are_checked_and_inherited(self):
        def item(entry_id, complete_for, extends=None):
            entry = {"id": entry_id, "category": "item", "name": entry_id,
                     "components": {"object": {"provides": ["core:item.handheld"], "complete_for": complete_for}}}
            return {**entry, "extends": extends} if extends else entry
        self.assertRejected(archive(tiny_pack("rods", [item("rods:rod", ["core:limb.tentacle"])])), "core:limb.tentacle does not exist")
        self.assertRejected(archive(tiny_pack("rods", [item("rods:rod", ["core:posture.sitting"])])), "is used as a capability but is not one")
        self.manager.install_archive(archive(tiny_pack("rods", [
            item("rods:rod", ["core:anatomy"]),
            {"id": "rods:long_rod", "category": "item", "name": "Long rod", "extends": ["rods:rod"],
             "components": {"object": {"provides": [], "complete_for": ["core:limb"]}}}])))
        merged = self.manager.registry().resolved("rods:long_rod")["components"]["object"]
        self.assertEqual(merged["complete_for"], ["core:anatomy", "core:limb"])
        self.assertEqual(merged["provides"], ["core:item.handheld"])

    def test_undeclared_category_and_loose_rating_are_rejected(self):
        self.assertRejected(archive(tiny_pack("cats", [{"id": "cats:x", "category": "spells", "name": "x", "components": {}}])),
                            "category spells is not declared")
        loose = fixture("adult")
        toys = json.loads(loose["toys.json"])
        toys["entries"][1]["rating"] = "general"
        loose["toys.json"] = toys
        self.assertRejected(archive(loose), "rated looser than its pack")


class UnsafeArchives(ManagerTest):
    def raw(self, members):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
            for info, content in members:
                zipped.writestr(info, content)
        return buffer.getvalue()

    def good(self):
        return {name: (json.dumps(value).encode() if isinstance(value, dict) else value) for name, value in fixture("fantasy").items()}

    def test_path_traversal_and_absolute_paths(self):
        for name in ("../evil.json", "/etc/evil.json", "C:/evil.json", "packs/../../evil.json", "a\\..\\evil.json"):
            with self.subTest(name=name):
                self.assertRejected(self.raw([(name, b"{}"), *self.good().items()]), "unsafe path")

    def test_links_are_rejected(self):
        link = zipfile.ZipInfo("link.json")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assertRejected(self.raw([(link, "/etc/passwd"), *self.good().items()]), "links are not allowed")

    def test_scripts_and_unlisted_or_nested_files_are_rejected(self):
        for name, fragment in (("install.py", "only JSON data"), ("run.bat", "only JSON data"),
                               ("extra.json", "not listed in the manifest"), ("deep/more.json", "")):
            with self.subTest(name=name):
                files = self.good()
                files[name] = b"{}"
                self.assertRejected(self.raw(list(files.items())), fragment)
        files = self.good()
        files["README.md"] = b"# Fantasy"
        self.manager.install_archive(self.raw(list(files.items())))

    def test_oversized_and_compression_bombs_are_rejected(self):
        self.assertRejected(self.raw([("huge.json", b" " * (MAX_FILE_BYTES + 1)), *self.good().items()]), "larger than")
        self.assertRejected(self.raw([("bomb.json", b"0" * 2_000_000), *self.good().items()]), "compression ratio")

    def test_duplicate_names_are_rejected(self):
        files = list(self.good().items())
        self.assertRejected(self.raw([*files, ("Manifest.json", b"{}")]), "appears more than once")

    def test_not_a_zip_or_without_manifest(self):
        self.assertRejected(b"plain text", "not a ZIP archive")
        files = self.good()
        del files["manifest.json"]
        self.assertRejected(self.raw(list(files.items())), "no manifest.json")


class EnableDisableRemove(ManagerTest):
    def setUp(self):
        super().setUp()
        self.manager.install_archive(archive(fixture("fantasy")))
        self.manager.install_archive(archive(fixture("adult")))
        self.manager.install_archive(archive(tiny_pack("wizards", [capability("wizards:x", ["fantasy:magic"])],
                                                       requires={"core": ">=1.0.0", "fantasy": ">=0.1.0"})))

    def test_disable_removes_entries_and_persists(self):
        self.manager.set_enabled("adult", False)
        self.assertNotIn("adult:item.dildo", self.manager.registry())
        reloaded = PackManager(self.root / "packs", self.root / "state.json")
        self.assertFalse([pack for pack in reloaded.discover() if pack["id"] == "adult"][0]["enabled"])
        reloaded.set_enabled("adult", True)
        self.assertIn("adult:item.dildo", reloaded.registry())

    def test_dependencies_block_disable_and_remove(self):
        for action in (lambda: self.manager.set_enabled("fantasy", False), lambda: self.manager.remove("fantasy")):
            with self.assertRaises(VocabularyError) as caught:
                action()
            self.assertIn("wizards", str(caught.exception))
        self.manager.set_enabled("wizards", False)
        self.manager.set_enabled("fantasy", False)
        with self.assertRaises(VocabularyError) as caught:
            self.manager.set_enabled("wizards", True)
        self.assertIn("requires fantasy", str(caught.exception))

    def test_remove_deletes_only_that_pack_and_clears_its_state(self):
        self.manager.set_enabled("adult", False)
        self.manager.remove("adult")
        self.assertEqual(self.installed(), ["fantasy", "wizards"])
        self.assertNotIn("adult", json.loads((self.root / "state.json").read_text())["disabled"])
        with self.assertRaises(VocabularyError):
            self.manager.remove("adult")

    def test_disabled_pack_still_must_be_valid_to_update(self):
        self.manager.set_enabled("adult", False)
        summary = self.manager.install_archive(archive(fixture("adult", manifest={"version": "0.2.0"})), replace=True)
        self.assertFalse(summary["enabled"], "an update keeps the pack's enabled state")


class Units(unittest.TestCase):
    def test_version_ranges(self):
        self.assertTrue(satisfies("1.2.3", ">=1.0.0 <2.0.0"))
        self.assertFalse(satisfies("2.0.0", ">=1.0.0 <2.0.0"))
        self.assertTrue(satisfies("1.0.0", "1.0.0"))
        with self.assertRaises(ValueError):
            satisfies("1.0", ">=1.0.0")

    def test_dependency_cycles_between_packs_are_rejected(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        packs = []
        for pack_id, other in (("ping", "pong"), ("pong", "ping")):
            folder = root / pack_id
            folder.mkdir()
            for name, content in tiny_pack(pack_id, [], requires={other: ">=1.0.0"}).items():
                (folder / name).write_text(json.dumps(content), encoding="utf-8")
            packs.append(read_pack(folder, bundled=False))
        with self.assertRaises(VocabularyError) as caught:
            build_registry(packs)
        self.assertIn("dependency cycle", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
