"""Release smoke check for the built website and its real local API."""

import asyncio
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app


DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@unittest.skipUnless((DIST / "index.html").is_file(), "Build frontend/dist before the release smoke check")
class BuiltSiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_built_assets_bootstrap_and_generation_with_fresh_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(root / "directors")}):
                app = local_app.create_app(
                    config_loader=lambda: {"backend": "mock"},
                    settings_path=root / "settings.json",
                )
                async with TestClient(TestServer(app), headers={"Host": "127.0.0.1:8190"}) as client:
                    response = await client.get("/")
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.content_type, "text/html")
                    html = await response.text()
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                    self.assertTrue(any(path.endswith(".js") for path in assets))
                    self.assertTrue(any(path.endswith(".css") for path in assets))
                    for path in assets:
                        asset = await client.get(path)
                        self.assertEqual(asset.status, 200, path)
                        self.assertTrue(await asset.read(), path)

                    bootstrap = await (await client.get("/api/bootstrap")).json()
                    self.assertIsNone(bootstrap["active_job"])
                    self.assertEqual(bootstrap["max_reference_images"], 4)
                    self.assertTrue(bootstrap["presets"]["presets"])
                    self.assertEqual(Path(bootstrap["presets"]["storage"]), root / "directors")

                    response = await client.post("/api/generate", json={
                        "settings": {"idea": "A quiet forest at dawn.", "linked_references": True},
                        "images": [None] * 4,
                        "text_only": True,
                    })
                    self.assertEqual(response.status, 202)
                    job = await response.json()
                    for _ in range(200):
                        job = await (await client.get(f"/api/jobs/{job['id']}")).json()
                        if job["status"] in local_app.TERMINAL:
                            break
                        await asyncio.sleep(0.01)
                    self.assertEqual(job["status"], "succeeded", job)
                    self.assertIn("A quiet forest at dawn.", job["result"]["prompt"])
