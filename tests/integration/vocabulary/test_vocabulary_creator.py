"""Creator contracts: persistent isolated drafts, authoritative validation and explicit publication."""

from copy import deepcopy
import io
import json
import zipfile
from unittest.mock import patch

from goated_prompter.features.vocabulary.creator import PackCreator
from goated_prompter.features.vocabulary.packs import OFFICIAL_DIR, read_pack, read_foundation
from tests.integration.vocabulary.test_vocabulary_api import VocabularyAPIBase
from tests.unit.vocabulary.test_vocabulary_packs import archive, capability, tiny_pack


def document(entries=None, **kwargs):
    files = tiny_pack("studio", entries if entries is not None else [dict(capability("studio:moonlight"), name="Moonlight", aliases=["lunar light"])], **kwargs)
    manifest = files.pop("manifest.json")
    manifest.update(name="Studio vocabulary", description="Synthetic editor fixture", authors=["Test author"], license="MIT")
    return {"manifest": manifest, "files": files, "extras": {"README.md": "A synthetic vocabulary pack.\n"}}


class VocabularyCreatorTests(VocabularyAPIBase):
    async def call(self, action, payload=None, expected=200, method=None):
        response = await self.client.request(method or ("POST" if payload is not None else "GET"),
            "/api/vocabulary/creator/" + action, json=payload)
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()

    async def validate(self, doc):
        return await self.call("validate", {"document": doc})

    async def test_schemas_are_the_real_complete_schemas_and_selectors_include_adult_and_disabled_packs(self):
        data = await self.call("schemas")
        self.assertEqual(set(data["entry"]["$defs"]["components"]["properties"]),
                         {"capability", "body", "participants", "requirements", "spatial", "claims", "object", "environment", "visual", "visibility", "capacity"})
        await self.enabled("adult", False)
        refs = await self.call("references")
        self.assertTrue(any(row["pack"] == "adult" for row in refs["entries"]))
        self.assertTrue(any(row["pack"] == "fantasy" for row in refs["entries"]))
        self.assertTrue(any(row["capability"] and row["pack"] == "core" for row in refs["entries"]))
        self.assertTrue(any(row["posture"] for row in refs["entries"]))

    async def test_new_pack_metadata_and_all_supported_components_categories_validate(self):
        seen_components, seen_categories = set(), set()
        for source in [read_foundation(), *[read_pack(OFFICIAL_DIR / name, bundled=True) for name in ("general", "fantasy", "adult")]]:
            entries = []
            for _name, entry in source.entries:
                clone = deepcopy(entry)
                clone["id"] = "studio:" + entry["id"].split(":", 1)[1]
                clone.pop("replaces", None)  # clones are new entries, not a second owner of the source's retired ids
                entries.append(clone)
                seen_components.update(entry["components"])
                seen_categories.add(entry["category"])
            requires = {"core": ">=1.0.0", **({source.id: ">=1.0.0"} if source.id != "core" else {})}
            result = await self.validate(document(entries, requires=requires, rating=source.manifest["rating"]))
            self.assertTrue(result["valid"], result)
        self.assertEqual(seen_components, {"capability", "body", "participants", "requirements", "spatial", "claims", "object", "environment", "visual", "visibility"})
        self.assertGreater(len(seen_categories), 5)

    async def test_custom_schema_category_and_multiple_entry_files_are_supported(self):
        doc = document([dict(capability("studio:knowledge"), category="studio_category")], categories=[{"id": "studio_category", "name": "Studio category"}])
        doc["manifest"]["files"].append("second.json")
        doc["files"]["second.json"] = {"spec": 1, "entries": [capability("studio:second")]}
        self.assertTrue((await self.validate(doc))["valid"])

    async def test_save_incomplete_draft_reopen_restart_and_revision_conflicts(self):
        doc = document()
        doc["files"]["entries.json"]["entries"][0]["name"] = ""
        saved = await self.call("drafts", {"document": doc})
        self.assertEqual(saved["document"], doc)
        self.assertEqual(len((await self.call("drafts"))["drafts"]), 1)
        self.assertEqual(PackCreator(self.manager).open(saved["id"])["document"], doc)
        doc["manifest"]["name"] = "Revised name"
        revised = await self.call("drafts/" + saved["id"], {"document": doc, "revision": saved["revision"]}, method="PUT")
        self.assertEqual(revised["revision"], 2)
        await self.call("drafts/" + saved["id"], {"document": document(), "revision": 1}, expected=400, method="PUT")
        opened = await self.call("drafts/" + saved["id"])
        self.assertEqual(opened["document"]["manifest"]["name"], "Revised name")
        self.assertFalse(any(pack["id"] == "studio" for pack in self.manager.discover()))

    async def test_manifest_and_entry_errors_have_field_paths(self):
        doc = document()
        doc["manifest"]["version"] = "not-semver"
        doc["files"]["entries.json"]["entries"][0]["name"] = ""
        doc["files"]["entries.json"]["entries"][0]["components"]["unsupported"] = {}
        result = await self.validate(doc)
        self.assertFalse(result["valid"])
        paths = [issue["path"] for issue in result["issues"]]
        self.assertIn(["manifest", "version"], paths)
        self.assertIn(["files", "entries.json", "entries", 0, "name"], paths)
        self.assertIn(["files", "entries.json", "entries", 0, "components"], paths)

    async def test_duplicate_ids_missing_references_and_inheritance_cycles_are_rejected(self):
        for entries in ([capability("studio:same"), capability("studio:same")],
                        [capability("studio:missing", ["core:does_not_exist"])],
                        [dict(capability("studio:a"), extends=["studio:b"]), dict(capability("studio:b"), extends=["studio:a"])]):
            with self.subTest(entries=entries):
                result = await self.validate(document(entries))
                self.assertFalse(result["valid"])
                self.assertTrue(result["issues"])
                await self.call("export", {"document": document(entries)}, expected=400)

    async def test_dependency_versions_missing_dependencies_and_undeclared_cross_pack_references(self):
        for requires in ({"core": ">=99.0.0"}, {"absent": ">=1.0.0"}, {}):
            result = await self.validate(document([capability("studio:ref", ["core:limb.hand"])], requires=requires))
            self.assertFalse(result["valid"], result)

    async def test_adult_ratings_and_inheritance_are_not_loosened(self):
        doc = document([dict(capability("studio:adult_capability"), rating="general")], rating="adult")
        self.assertFalse((await self.validate(doc))["valid"])
        entry = {"id": "studio:adult_position", "name": "Inherited adult position", "category": "position",
                 "extends": ["adult:position.reverse_cowgirl"], "components": {}}
        doc = document([entry], rating="adult", requires={"core": ">=1.0.0", "adult": ">=1.0.0"})
        self.assertTrue((await self.validate(doc))["valid"])

    async def test_preview_uses_engine_without_install_or_state_changes_and_adult_filter_still_applies(self):
        await self.enabled("adult", False)
        before, state = self.manager.registry().ids(), self.manager.state_file.read_bytes()
        doc = document([{"id": "studio:moonlight", "name": "Moonlight lantern", "category": "item", "aliases": ["lunar light"],
                         "components": {"object": {"provides": []}}}], rating="adult")
        body = {"document": doc, "sample": {"request": "Moonlight lunar light", "nsfw": False}}
        with patch("goated_prompter.backends.factory.create_backend", side_effect=AssertionError("No inference")):
            sfw = await self.call("preview", body)
            body["sample"]["nsfw"] = True
            adult = await self.call("preview", body)
            again = await self.call("preview", body)
        self.assertTrue(sfw["valid"])
        self.assertFalse(any(entry["pack"] == "studio" for entry in sfw["retrieval"]["entries"]))
        self.assertTrue(any(entry["id"] == "studio:moonlight" for entry in adult["retrieval"]["entries"]))
        self.assertEqual(adult, again)
        self.assertEqual(before, self.manager.registry().ids())
        self.assertEqual(state, self.manager.state_file.read_bytes())
        self.assertFalse(self.manager.install_dir.exists())

    async def test_disabled_dependency_can_be_previewed_but_install_enforces_active_rules(self):
        await self.enabled("adult", False)
        doc = document([{"id": "studio:adult_position", "name": "Synthetic position", "category": "position",
                         "extends": ["adult:position.reverse_cowgirl"], "components": {}}], rating="adult",
                       requires={"core": ">=1.0.0", "adult": ">=1.0.0"})
        self.assertTrue((await self.validate(doc))["valid"])
        await self.call("install", {"document": doc, "confirmed": True}, expected=400)
        self.assertFalse(any(pack["id"] == "studio" for pack in self.manager.discover()))

    async def test_export_import_roundtrip_and_install_preserve_files_and_text(self):
        doc = document()
        response = await self.client.post("/api/vocabulary/creator/export", json={"document": doc})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/zip")
        data = await response.read()
        imported = await self.client.post("/api/vocabulary/creator/import", data=data)
        self.assertEqual(imported.status, 200, await imported.text())
        self.assertEqual((await imported.json())["document"], doc)
        self.assertFalse(any(pack["id"] == "studio" for pack in self.manager.discover()))
        await self.call("install", {"document": doc}, expected=400)
        await self.call("install", {"document": doc, "confirmed": True})
        source = await self.call("source/studio?origin=installed")
        self.assertFalse(source["read_only"])
        self.assertEqual(source["document"], doc)

    async def test_update_requires_target_confirmation_and_keeps_disabled_state(self):
        doc = document()
        await self.call("install", {"document": doc, "confirmed": True})
        await self.enabled("studio", False)
        before = self.manager.state_file.read_bytes()
        doc["manifest"]["version"] = "1.1.0"
        await self.call("install", {"document": doc, "update_id": "studio"}, expected=400)
        await self.call("install", {"document": doc, "confirmed": True}, expected=400)
        result = await self.call("install", {"document": doc, "confirmed": True, "update_id": "studio"})
        self.assertFalse(result["pack"]["enabled"])
        self.assertEqual(before, self.manager.state_file.read_bytes())
        self.assertEqual((await self.call("source/studio"))["document"]["manifest"]["version"], "1.1.0")

    async def test_bundled_sources_and_imports_are_readonly_and_write_paths_reject_them(self):
        for ident in ("core", "fantasy", "adult"):
            source = await self.call("source/" + ident)
            self.assertTrue(source["read_only"])
            doc = source["document"]
            self.assertFalse((await self.validate(doc))["valid"])
            for action in ("drafts", "export", "install"):
                await self.call(action, {"document": doc, **({"confirmed": True} if action == "install" else {})}, expected=400)
            files = {"manifest.json": doc["manifest"], **doc["files"]}
            response = await self.client.post("/api/vocabulary/creator/import", data=archive(files))
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["read_only"])

    async def test_unsafe_draft_filenames_shapes_and_excessive_nesting_are_rejected(self):
        for name in ("../outside.json", "sub/file.json", "manifest.json", "C:\\outside.json"):
            doc = document()
            doc["files"][name] = {"spec": 1, "entries": []}
            await self.call("drafts", {"document": doc}, expected=400)
        for value in (None, [], {"manifest": {}, "files": []}, {"manifest": {}, "files": {}, "script": "x"}):
            await self.call("validate", {"document": value}, expected=400)
        doc = document()
        for _ in range(45):
            doc = {"manifest": {}, "files": {"deep.json": doc}}
        await self.call("drafts", {"document": doc}, expected=400)
        await self.call("drafts/not-a-draft", expected=400)

    async def test_import_uses_existing_zip_protections(self):
        for filename in ("../escape.json", "payload.exe", "sub/deep/file.json"):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as zip_file:
                zip_file.writestr(filename, "{}"); zip_file.writestr("manifest.json", "{}")
            response = await self.client.post("/api/vocabulary/creator/import", data=output.getvalue())
            self.assertEqual(response.status, 400, await response.text())
        response = await self.client.post("/api/vocabulary/creator/import", data=b"not a ZIP")
        self.assertEqual(response.status, 400)

    async def test_invalid_preview_sample_and_invalid_pack_never_install(self):
        await self.call("preview", {"document": document(), "sample": {"request": "x", "nsfw": "true"}}, expected=400)
        doc = document()
        doc["manifest"]["version"] = "broken"
        result = await self.call("preview", {"document": doc, "sample": {"request": "Moonlight"}})
        self.assertFalse(result["valid"])
        self.assertNotIn("retrieval", result)
        await self.call("install", {"document": doc, "confirmed": True}, expected=400)
        self.assertFalse(self.manager.install_dir.exists())
