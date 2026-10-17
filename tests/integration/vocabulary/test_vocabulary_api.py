"""The vocabulary catalog over HTTP, read from a synthetic copy of the bundled library."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tests.helpers import enter_context

from aiohttp.test_utils import TestClient, TestServer

import local_app
from goated_prompter.features.vocabulary import catalog


class VocabularyCatalogAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "vocabulary"
        shutil.copytree(catalog.ROOT, self.root, ignore=shutil.ignore_patterns("SKILL.md"))
        self.user = Path(self.temp.name) / "data-vocabulary"
        enter_context(self, patch.object(catalog, "ROOT", self.root))
        enter_context(self, patch.object(catalog, "USER_ROOT", self.user))
        enter_context(self, patch("local_app.get_process_manager"))
        app = local_app.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp.name) / "settings.json")
        self.client = TestClient(TestServer(app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def get(self):
        response = await self.client.get("/api/vocabulary/catalog")
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_catalog_lists_registered_categories_and_their_packs(self):
        body = await self.get()
        self.assertEqual(len(body["categories"]), 10)
        self.assertEqual(body["categories"][2]["id"], "Spaces")
        self.assertIn("Spaces/Fantasy", {pack["id"] for pack in body["packs"]})
        self.assertEqual(body["problems"], [])

    async def test_a_new_pack_appears_and_a_broken_one_is_reported(self):
        (self.root / "Spaces" / "Rooftops.json").write_text(json.dumps(
            {"name": "Rooftops", "category": "Spaces", "entries": ["rooftop bar"]}), encoding="utf-8")
        (self.root / "Spaces" / "Broken.json").write_text("{ not json", encoding="utf-8")
        body = await self.get()
        self.assertIn("Spaces/Rooftops", {pack["id"] for pack in body["packs"]})
        self.assertEqual([row["file"] for row in body["problems"]], ["Spaces/Broken.json"])

    async def test_an_imported_pack_is_saved_in_its_category_folder_and_listed(self):
        content = json.dumps({"name": "Rooftops", "category": "Spaces", "entries": ["rooftop bar"]})
        response = await self.client.post("/api/vocabulary/import", json={"filename": "Rooftops.json", "content": content})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["pack"]["id"], "data/Spaces/Rooftops")
        self.assertTrue((self.user / "Spaces" / "Rooftops.json").is_file())
        self.assertIn("data/Spaces/Rooftops", {pack["id"] for pack in (await self.get())["packs"]})

    async def test_an_invalid_import_is_refused_with_its_reason(self):
        response = await self.client.post("/api/vocabulary/import", json={"filename": "x.json", "content": "{}"})
        self.assertEqual(response.status, 400)
        self.assertIn("Could not import x.json", (await response.json())["error"])
        self.assertFalse(self.user.exists())

    async def test_old_pack_management_routes_are_gone(self):
        for method, path in (("GET", "/api/vocabulary/packs"), ("POST", "/api/vocabulary/packs")):
            response = await self.client.request(method, path)
            self.assertIn(response.status, (404, 405))

    async def test_an_unreadable_core_fails_the_catalog_with_a_reason(self):
        (self.root / "core" / "scene_category_registry.json").unlink()
        response = await self.client.get("/api/vocabulary/catalog")
        self.assertEqual(response.status, 500)
        self.assertIn("Vocabulary Core could not be read", (await response.json())["error"])


if __name__ == "__main__":
    unittest.main()
