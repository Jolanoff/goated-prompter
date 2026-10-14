"""Pack management over HTTP with synthetic installed storage and real schema validation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app
from goated_prompter.features.vocabulary import routes
from goated_prompter.features.vocabulary.packs import PackManager
from goated_prompter.features.dataset.v2 import scenes
from tests.unit.vocabulary.test_vocabulary_packs import archive, capability, tiny_pack
from tests.unit.dataset.test_dataset_vocabulary_integration import ScriptedDirector, RecordingTrace, PEOPLE, brief


class VocabularyAPIBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = PackManager(self.root / "packs", self.root / "state.json")
        self.enterContext(patch("local_app.get_process_manager"))
        self.client = await self.new_client(self.manager)

    async def new_client(self, manager):
        with patch.object(routes, "PackManager", return_value=manager):
            app = local_app.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=self.root / "settings.json")
        client = TestClient(TestServer(app), headers={"Host": "127.0.0.1:8190"})
        await client.start_server()
        async def close():
            await client.close()
            self.assertTrue(client.server.closed, "Owned HTTP listener must close")
        self.addAsyncCleanup(close)
        return client

    async def get(self, client=None):
        response = await (client or self.client).get("/api/vocabulary/packs")
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def upload(self, files, pack_id=None, expected=200):
        response = await self.client.request("PUT" if pack_id else "POST",
            "/api/vocabulary/packs" + (f"/{pack_id}" if pack_id else ""), data=archive(files),
            headers={"Content-Type": "application/zip"})
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()

    async def enabled(self, pack_id, enabled, expected=200):
        response = await self.client.patch(f"/api/vocabulary/packs/{pack_id}", json={"enabled": enabled})
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()


class VocabularyAPITests(VocabularyAPIBase):
    async def test_inventory_includes_complete_metadata_and_all_three_ratings(self):
        for rating in ("general", "mature", "adult"):
            pack_id = f"user_{rating}"
            files = tiny_pack(pack_id, [capability(f"{pack_id}:knowledge")], rating=rating)
            files["manifest.json"]["description"] = f"A {rating} pack."
            await self.upload(files)
        data = await self.get()
        self.assertFalse(data["problems"])
        self.assertEqual({pack["origin"] for pack in data["packs"]}, {"core", "bundled", "installed"})
        for pack in data["packs"]:
            for key in ("name", "description", "version", "entries", "rating", "requires", "enabled", "origin", "problems", "valid"):
                self.assertIn(key, pack)
        mature = next(pack for pack in data["packs"] if pack["id"] == "user_mature")
        self.assertEqual((mature["rating"], mature["entries"], mature["description"]), ("mature", 1, "A mature pack."))

    async def test_optional_state_persists_across_new_application_instances(self):
        for pack_id in ("fantasy", "adult"):
            await self.enabled(pack_id, False)
        new_manager = PackManager(self.manager.install_dir, self.manager.state_file)
        new_client = await self.new_client(new_manager)
        packs = {pack["id"]: pack for pack in (await self.get(new_client))["packs"]}
        self.assertTrue(packs["core"]["enabled"])
        self.assertFalse(packs["adult"]["enabled"])
        self.assertFalse(packs["fantasy"]["enabled"])
        await self.enabled("adult", True)
        self.assertTrue(next(pack for pack in new_manager.discover() if pack["id"] == "adult")["enabled"])

    async def test_core_is_immutable_and_bundled_optional_files_cannot_be_removed_or_updated(self):
        await self.enabled("core", False, 400)
        for pack_id in ("core", "fantasy", "adult"):
            response = await self.client.delete(f"/api/vocabulary/packs/{pack_id}")
            self.assertEqual(response.status, 400)
            await self.upload(tiny_pack(pack_id, []), pack_id, 400)
            await self.upload(tiny_pack(pack_id, []), expected=400)
        self.assertEqual({pack["id"] for pack in (await self.get())["packs"]}, {"core", "fantasy", "adult"})

    async def test_install_update_and_remove_keep_disabled_state_and_protect_other_packs(self):
        await self.upload(tiny_pack("custom", [capability("custom:knowledge")]))
        await self.enabled("custom", False)
        await self.upload(tiny_pack("custom", [capability("custom:new")], version="1.1.0"), "custom")
        pack = next(pack for pack in (await self.get())["packs"] if pack["id"] == "custom")
        self.assertEqual(pack["version"], "1.1.0")
        self.assertFalse(pack["enabled"])
        response = await self.client.delete("/api/vocabulary/packs/custom")
        self.assertEqual(response.status, 200)
        self.assertNotIn("custom", {pack["id"] for pack in (await response.json())["packs"]})
        self.assertFalse((self.manager.install_dir / "custom").exists())

    async def test_duplicate_pack_and_entry_ids_are_rejected_without_partial_installs(self):
        files = tiny_pack("custom", [capability("custom:knowledge")])
        await self.upload(files)
        result = await self.upload(files, expected=400)
        self.assertIn("already installed", result["error"])
        result = await self.upload(tiny_pack("duplicates", [capability("duplicates:same"), capability("duplicates:same")]), expected=400)
        self.assertIn("duplicate id", result["error"])
        self.assertFalse((self.manager.install_dir / "duplicates").exists())

    async def test_dependency_errors_block_disable_remove_and_incompatible_update(self):
        await self.upload(tiny_pack("parent", [capability("parent:knowledge")]))
        await self.upload(tiny_pack("child", [capability("child:knowledge")], requires={"core": ">=1.0.0", "parent": ">=1.0.0 <2.0.0"}))
        self.assertIn("require", (await self.enabled("parent", False, 400))["error"])
        response = await self.client.delete("/api/vocabulary/packs/parent")
        self.assertEqual(response.status, 400)
        result = await self.upload(tiny_pack("parent", [], version="2.0.0"), "parent", 400)
        self.assertIn("requires parent", result["error"])
        self.assertEqual(self.manager.registry().packs["parent"].manifest["version"], "1.0.0")
        missing = await self.upload(tiny_pack("missing", [], requires={"absent": ">=1.0.0"}), expected=400)
        self.assertIn("requires absent", missing["error"])

    async def test_selected_update_must_match_archive_id_and_cannot_downgrade(self):
        await self.upload(tiny_pack("custom", [], version="2.0.0"))
        result = await self.upload(tiny_pack("another", []), "custom", 400)
        self.assertIn("not custom", result["error"])
        await self.upload(tiny_pack("custom", [], version="1.0.0"), "custom", 400)
        self.assertFalse((self.manager.install_dir / "another").exists())
        await self.upload(tiny_pack("absent", []), "absent", 400)

    async def test_invalid_zip_schema_and_traversal_are_rejected(self):
        for data in (b"not a zip", archive({"../escape.json": {}}), archive({"manifest.json": {"id": "invalid"}})):
            response = await self.client.post("/api/vocabulary/packs", data=data)
            self.assertEqual(response.status, 400, await response.text())
        self.assertFalse((self.root / "escape.json").exists())
        self.assertFalse(any(self.manager.install_dir.iterdir()), "Rejected ZIP staging must be removed")

    async def test_upload_limit_covers_known_length_and_chunked_bodies(self):
        with patch.object(routes, "MAX_ARCHIVE_BYTES", 8):
            response = await self.client.post("/api/vocabulary/packs", data=b"123456789")
            self.assertEqual(response.status, 413)
            async def chunks():
                yield b"12345"
                yield b"67890"
            response = await self.client.post("/api/vocabulary/packs", data=chunks())
            self.assertEqual(response.status, 413)

    async def test_path_ids_and_enabled_contract_are_strict(self):
        for pack_id in ("bad!", "123", "..%2Foutside"):
            response = await self.client.delete(f"/api/vocabulary/packs/{pack_id}")
            self.assertIn(response.status, (400, 404))
        for payload in ({"enabled": "false"}, {"enabled": 1}, {"enabled": True, "extra": 0}, {}):
            response = await self.client.patch("/api/vocabulary/packs/adult", json=payload)
            self.assertEqual(response.status, 400)

    async def test_broken_duplicate_and_incompatible_packs_remain_visible(self):
        for name, files in (("broken", {"manifest.json": "{broken"}),
                            ("incompatible", tiny_pack("incompatible", [], requires={"missing": ">=1.0.0"})),
                            ("adult", tiny_pack("adult", []))):
            folder = self.manager.install_dir / name
            folder.mkdir(parents=True)
            for filename, value in files.items():
                (folder / filename).write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        data = await self.get()
        self.assertTrue(data["problems"])
        for name in ("broken", "incompatible", "adult"):
            pack = next(pack for pack in data["packs"] if pack["id"] == name and pack["origin"] == "installed")
            self.assertTrue(pack["problems"], name)
        response = await self.client.delete("/api/vocabulary/packs/broken")
        # Other invalid packs still prevent registry loading, but must not hide the completed removal.
        self.assertEqual(response.status, 200)
        self.assertFalse((self.manager.install_dir / "broken").exists())

    async def test_disabling_adult_pack_changes_the_next_dataset_run_without_restart(self):
        request = brief("Reverse cowgirl on a sofa", characters=PEOPLE, nsfw=True)
        def generate():
            manager = PackManager(self.manager.install_dir, self.manager.state_file)
            with patch.object(scenes, "create_backend", return_value=ScriptedDirector()), patch.object(scenes, "DebugTrace", RecordingTrace), \
                    patch("goated_prompter.features.dataset.v2.vocabulary_packs.PackManager", return_value=manager):
                return scenes.write_scenes({"backend": "mock"}, unittest.mock.Mock(selected_prompt_model="Default"),
                                           request, progress=lambda _message: None)
        before = generate()
        self.assertTrue(any(entry.startswith("adult:") for entry in before["vocabulary"]["provided"]),
                        next(item["detail"] for item in RecordingTrace.records[-1]["decisions"] if item["rule"] == "vocabulary"))
        await self.enabled("adult", False)
        after = generate()
        self.assertFalse(any(entry.startswith("adult:") for entry in after["vocabulary"]["provided"]))
        self.assertEqual(before["written"], after["written"])

    async def test_valid_update_can_repair_an_unreadable_installed_manifest(self):
        folder = self.manager.install_dir / "custom"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{bad json", encoding="utf-8")
        await self.upload(tiny_pack("custom", [capability("custom:knowledge")]), "custom")
        pack = next(pack for pack in (await self.get())["packs"] if pack["id"] == "custom")
        self.assertTrue(pack["valid"])
        self.assertFalse(pack["problems"])
        self.assertIn("custom:knowledge", self.manager.registry())

    async def test_broken_core_is_reported_as_mandatory_not_hidden(self):
        folder = self.root / "core"
        folder.mkdir()
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
        self.manager.bundled_dirs = (folder,)
        data = await self.get()
        core = next(pack for pack in data["packs"] if pack["id"] == "core")
        self.assertTrue(core["mandatory"])
        self.assertTrue(core["enabled"])
        self.assertTrue(core["problems"])
        self.assertTrue(data["problems"])
