"""Explorer reads disabled packs, preserves declarations and delegates matching to the engine."""

import json
from unittest.mock import patch

import local_app

from goated_prompter.features.vocabulary.retrieval import RetrievalRequest, retrieve
from tests.integration.vocabulary.test_vocabulary_api import VocabularyAPIBase
from tests.unit.vocabulary.test_vocabulary_packs import capability, tiny_pack


class VocabularyExplorerTests(VocabularyAPIBase):
    async def query(self, path, expected=200):
        response = await self.client.get("/api/vocabulary/" + path)
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()

    async def inspect(self, text, nsfw=False, characters=None, expected=200):
        response = await self.client.post("/api/vocabulary/retrieve", json={"request": text, "nsfw": nsfw,
            "characters": characters or []})
        self.assertEqual(response.status, expected, await response.text())
        return await response.json()

    async def test_listing_uses_real_categories_counts_and_deterministic_sort(self):
        data = await self.query("packs/general/entries")
        self.assertEqual(data["total"], 96)
        self.assertEqual(sum(item["count"] for item in data["categories"]), data["total"])
        self.assertEqual([entry["name"].casefold() for entry in data["entries"]], sorted(entry["name"].casefold() for entry in data["entries"]))
        filtered = await self.query("packs/general/entries?category=body&sort=id")
        self.assertTrue(filtered["entries"])
        self.assertTrue(all(entry["category"] == "body" for entry in filtered["entries"]))
        self.assertEqual(filtered["total"], data["total"])
        self.assertEqual([item["id"] for item in filtered["entries"]], sorted(item["id"] for item in filtered["entries"]))

    async def test_catalogue_search_matches_names_ids_aliases_and_tags_not_unrelated_entries(self):
        entries = [dict(capability("custom:alpha"), name="Moon anchor", aliases=["Lunar clasp"], tags=["night_prop"]),
                   dict(capability("custom:beta"), name="Sun anchor")]
        await self.upload(tiny_pack("custom", entries))
        for text in ("MOON", "custom:alpha", "lunar", "night_prop"):
            with self.subTest(text=text):
                data = await self.query(f"packs/custom/entries?q={text}")
                self.assertEqual([item["id"] for item in data["entries"]], ["custom:alpha"])
        self.assertFalse((await self.query("packs/custom/entries?q=missing"))["entries"])
        self.assertFalse((await self.query("packs/custom/entries?rating=adult"))["entries"])

    async def test_details_preserve_direct_and_inherited_fields_and_cross_pack_navigation(self):
        raw = {"id": "custom:body.reader", "category": "body", "name": "Reader", "aliases": ["bookworm"],
               "extends": ["general:body.human"], "components": {"body": {"provides": ["core:limb.hand"]}}}
        await self.upload(tiny_pack("custom", [raw], requires={"core": ">=1.0.0", "general": ">=1.0.0"}))
        detail = await self.query("entries/custom:body.reader")
        self.assertEqual(detail["declared"], raw)
        self.assertNotIn("resources", detail["declared"]["components"]["body"])
        self.assertTrue(detail["resolved"]["components"]["body"]["resources"])
        self.assertEqual(detail["pack"]["id"], "custom")
        parent = next(ref for ref in detail["references"] if ref["id"] == "general:body.human" and ref["kind"] == "extends")
        self.assertTrue(parent["declared"])
        self.assertTrue(parent["exists"])
        self.assertEqual(parent["origin"], "bundled")
        self.assertTrue(any(not ref["declared"] for ref in detail["references"]))
        parent_detail = await self.query(f"entries/{parent['id']}?origin={parent['origin']}")
        self.assertEqual(parent_detail["pack"]["id"], "general")

    async def test_disabled_adult_pack_is_browsable_without_enabling_it(self):
        await self.enabled("adult", False)
        before = self.manager.state_file.read_bytes()
        data = await self.query("packs/adult/entries?origin=bundled&rating=adult")
        self.assertEqual(data["matched"], data["total"])
        self.assertGreater(data["total"], 0)
        detail = await self.query("entries/adult:position.reverse_cowgirl?origin=bundled")
        self.assertEqual(detail["resolved"]["rating"], "adult")
        self.assertFalse(detail["pack"]["enabled"])
        self.assertEqual(before, self.manager.state_file.read_bytes())
        result = await self.inspect("Reverse cowgirl on a sofa", True, ["adult human", "adult human"])
        self.assertFalse(any(item["pack"] == "adult" for item in result["entries"]))

    async def test_retrieval_matches_existing_engine_exactly_and_has_no_generation_calls(self):
        sample = "A woman holding a lantern while walking through a dark forest"
        with patch("goated_prompter.backends.factory.create_backend", side_effect=AssertionError("No generation")):
            result = await self.inspect(sample)
            again = await self.inspect(sample)
        self.assertEqual(result, again)
        expected = retrieve(self.manager.registry(), RetrievalRequest(request=sample)).to_dict()
        self.assertEqual(result["entries"], expected["entries"])
        self.assertEqual(result["warnings"], expected["warnings"])
        self.assertNotIn("timings", result)
        self.assertFalse(self.client.app[local_app.STATE].jobs)

    async def test_adult_visibility_is_distinct_from_retrieval_rating_eligibility(self):
        self.assertTrue((await self.query("packs/adult/entries"))["entries"])
        sample, cast = "Reverse cowgirl on a sofa", ["adult human", "adult human"]
        sfw = await self.inspect(sample, False, cast)
        self.assertFalse(any(item["rating"] == "adult" for item in sfw["entries"]))
        self.assertTrue(any(item["pack"] == "adult" and "rating adult" in item["reason"] for item in sfw["excluded"]))
        adult = await self.inspect(sample, True, cast)
        self.assertIn("adult:position.reverse_cowgirl", [item["id"] for item in adult["entries"]])

    async def test_unknowns_and_conflicts_are_only_those_the_engine_reports(self):
        missing_cast = await self.inspect("Reverse cowgirl on a sofa", True)
        self.assertTrue(any(item["reason"].startswith("conflict:") for item in missing_cast["excluded"]))
        unknown = await self.inspect("Reverse cowgirl on a sofa", True, ["unidentified being", "unidentified being"])
        match = next(item for item in unknown["entries"] if item["id"] == "adult:position.reverse_cowgirl")
        self.assertEqual(match["status"], "unknown")
        self.assertTrue(match["warnings"])

    async def test_broken_references_keep_declarations_and_report_missing_links(self):
        folder = self.manager.install_dir / "custom"
        folder.mkdir(parents=True)
        raw = {"id": "custom:missing", "name": "Missing parent", "category": "body", "extends": ["core:body.missing"], "components": {}}
        for filename, content in tiny_pack("custom", [raw]).items():
            (folder / filename).write_text(json.dumps(content), encoding="utf-8")
        catalogue = await self.query("packs/custom/entries")
        self.assertEqual(len(catalogue["entries"]), 1)
        self.assertTrue(catalogue["problems"])
        detail = await self.query("entries/custom:missing")
        self.assertIsNone(detail["resolved"])
        self.assertEqual(detail["declared"], raw)
        self.assertFalse(detail["references"][0]["exists"])
        await self.query("entries/core:body.missing", 400)
        self.assertTrue((await self.query("packs/core/entries"))["entries"], "Unrelated damage must not hide Core")
        await self.inspect("A lantern", expected=400)

    async def test_malformed_pack_is_selectable_but_returns_diagnostics_not_invented_entries(self):
        folder = self.manager.install_dir / "broken"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{broken", encoding="utf-8")
        data = await self.query("packs/broken/entries?origin=installed")
        self.assertFalse(data["entries"])
        self.assertTrue(data["problems"])

    async def test_validation_rejects_invalid_filters_and_unbounded_samples(self):
        for suffix in ("?sort=anything", "?rating=extreme", "?extra=1", "?q=" + "x" * 201):
            await self.query("packs/core/entries" + suffix, 400)
        await self.query("packs/absent/entries", 400)
        for payload in ({"request": ""}, {"request": "x" * 4001}, {"request": "a", "nsfw": "true"},
                        {"request": "a", "characters": ["x"] * 17}, {"request": "a", "characters": [1]},
                        {"request": "a", "generate": True}):
            response = await self.client.post("/api/vocabulary/retrieve", json=payload)
            self.assertEqual(response.status, 400)
