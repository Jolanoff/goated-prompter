"""The vocabulary library: Core's three files, the registered category folders and their packs (catalog.py)."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.features.vocabulary import catalog
from goated_prompter.features.vocabulary.catalog import (CatalogError, catalog_for, load_catalog, record, selected_vocabulary,
                                                         validate_selection, vocabulary_prompt)

CATEGORIES = ["Subjects", "Actions", "Spaces", "Objects", "Positions & Poses", "Expressions", "Clothing", "Mood & Tone",
              "Lighting", "Camera & Composition", "Effects & Atmosphere"]


class Bundled(unittest.TestCase):
    def test_core_registers_the_eleven_categories_with_definitions_and_instructions(self):
        loaded = load_catalog()
        self.assertEqual(loaded["problems"], [])
        self.assertEqual([row["id"] for row in loaded["categories"]], CATEGORIES)
        for row in loaded["categories"]:
            self.assertEqual(row["folder"], row["id"])
            self.assertTrue(row["description"] and row["use_when"])
            self.assertTrue(row["instruction"].startswith(f"{row['id']} provides vocabulary"), row["instruction"])
            self.assertNotIn("{", row["instruction"])

    def test_core_is_exactly_three_files(self):
        self.assertEqual(sorted(path.name for path in (catalog.ROOT / "core").iterdir()),
                         ["category_definitions.json", "prompt_instructions.json", "scene_category_registry.json"])

    def test_every_starter_pack_is_name_category_entries_in_its_folder(self):
        loaded = load_catalog()
        self.assertEqual(len(loaded["packs"]), 50)
        for path in sorted(catalog.ROOT.glob("*/*.json")):
            if path.parent.name == "core":
                continue
            with self.subTest(pack=str(path.relative_to(catalog.ROOT))):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(list(data), ["name", "category", "entries"])
                self.assertEqual(data["category"], path.parent.name)
                self.assertTrue(all(isinstance(entry, str) and entry for entry in data["entries"]))
        names = {pack["id"]: pack["name"] for pack in loaded["packs"]}
        self.assertEqual(names["Spaces/Sci-Fi"], "Sci-Fi")
        self.assertEqual(names["Positions & Poses/Seductive-Solo-Poses"], "Seductive Solo Poses")


class Library(unittest.TestCase):
    """A synthetic library copied from the bundled Core."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(catalog.ROOT / "core", self.root / "core")

    def pack(self, folder, stem, content):
        (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / folder / f"{stem}.json").write_text(content if isinstance(content, str) else json.dumps(content), "utf-8")

    def core(self, name, change):
        path = self.root / "core" / name
        path.write_text(json.dumps(change(json.loads(path.read_text(encoding="utf-8")))), "utf-8")

    def test_a_new_pack_needs_only_its_file(self):
        self.pack("Positions & Poses", "Dragon-Poses", {"name": "Dragon Poses", "category": "Positions & Poses",
                                                        "entries": ["wings fully extended", "perched on a cliff"]})
        packs = load_catalog(self.root)["packs"]
        self.assertEqual([(pack["id"], pack["category"]) for pack in packs], [("Positions & Poses/Dragon-Poses", "Positions & Poses")])
        groups = selected_vocabulary(load_catalog(self.root), {"packs": ["Positions & Poses/Dragon-Poses"]})
        self.assertEqual(groups[0]["category"], "Positions & Poses")

    def test_a_new_category_needs_only_core_entries_and_its_folder(self):
        name = "Materials & Textures"
        self.core("category_definitions.json", lambda rows: rows + [{"category": name, "description": "Surfaces.", "use_when": "Always."}])
        self.core("prompt_instructions.json", lambda rows: rows + [{"category": name, "prompt_text": "{Materials & Textures} gives surfaces."}])
        self.core("scene_category_registry.json", lambda data: {"categories": data["categories"] + [{"category": name, "folder": name}]})
        self.pack(name, "Metals", {"name": "Metals", "category": name, "entries": ["brushed steel"]})
        loaded = load_catalog(self.root)
        self.assertEqual(loaded["categories"][-1]["instruction"], "Materials & Textures gives surfaces.")
        self.assertEqual(loaded["packs"][0]["id"], f"{name}/Metals")
        self.assertIn("Materials & Textures\nCore instruction:\nMaterials & Textures gives surfaces.",
                      vocabulary_prompt(selected_vocabulary(loaded, {"packs": [f"{name}/Metals"]})))

    def test_an_invalid_pack_is_reported_and_never_breaks_the_others(self):
        self.pack("Spaces", "Good", {"name": "Good", "category": "Spaces", "entries": ["attic"]})
        broken = {
            "Not-Json": "{ nope",
            "Extra-Key": {"name": "X", "category": "Spaces", "entries": ["a"], "tags": ["x"]},
            "Wrong-Category": {"name": "X", "category": "Lighting", "entries": ["a"]},
            "No-Entries": {"name": "X", "category": "Spaces", "entries": []},
            "Object-Entry": {"name": "X", "category": "Spaces", "entries": [{"name": "a"}]},
        }
        for stem, content in broken.items():
            self.pack("Spaces", stem, content)
        self.pack("Unregistered", "Stray", {"name": "Stray", "category": "Unregistered", "entries": ["a"]})
        loaded = load_catalog(self.root)
        self.assertEqual([pack["id"] for pack in loaded["packs"]], ["Spaces/Good"], "unregistered folders are not read")
        self.assertEqual(sorted(row["file"] for row in loaded["problems"]), sorted(f"Spaces/{stem}.json" for stem in broken))

    def test_oversized_files_are_problems(self):
        self.pack("Spaces", "Big", {"name": "Big", "category": "Spaces", "entries": ["a" * 200]})
        with patch.object(catalog, "MAX_FILE_BYTES", 100):
            loaded = load_catalog(self.root)
        self.assertIn("larger than", loaded["problems"][0]["problem"])

    def test_a_category_missing_from_definitions_or_instructions_is_reported(self):
        self.core("prompt_instructions.json", lambda rows: [row for row in rows if row["category"] != "Lighting"])
        loaded = load_catalog(self.root)
        self.assertEqual(loaded["problems"], [{"file": "core/prompt_instructions.json", "problem": 'no entry for the category "Lighting"'}])
        self.assertIn("Lighting", [row["id"] for row in loaded["categories"]])

    def test_a_run_without_packs_reads_no_pack_folder(self):
        with patch.object(catalog, "load_catalog", side_effect=AssertionError("no pack folder may be read")):
            empty = catalog_for({"packs": []}, self.root)
        self.assertEqual(empty["packs"], [])
        self.assertEqual(len(empty["categories"]), 11)


class Selection(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_only_selected_categories_reach_the_prompt_with_their_core_instruction(self):
        selection = validate_selection(self.catalog, ["Spaces/Fantasy", "Clothing/Fantasy-Outfits", "Effects & Atmosphere/Magic-Effects"])
        text = vocabulary_prompt(selected_vocabulary(self.catalog, selection))
        self.assertTrue(text.startswith("SELECTED VOCABULARY:\n\nSpaces\nCore instruction:\nSpaces provides vocabulary"))
        for heading in ("Spaces\nCore instruction:", "Clothing\nCore instruction:", "Effects & Atmosphere\nCore instruction:"):
            self.assertEqual(text.count(heading), 1)
        for absent in ("Subjects", "Actions", "Lighting", "Positions & Poses"):
            self.assertNotIn(f"\n{absent}\nCore instruction:", text)
        self.assertIn("Available vocabulary:\nenchanted forest\nancient dragon temple\nfloating castle", text)
        self.assertNotIn("foggy graveyard", text, "an unselected pack of a selected category is not sent")

    def test_two_packs_of_one_category_share_one_block(self):
        text = vocabulary_prompt(selected_vocabulary(self.catalog, {"packs": ["Spaces/Horror", "Spaces/Fantasy"]}))
        self.assertEqual(text.count("Core instruction:"), 1)
        self.assertLess(text.index("enchanted forest"), text.index("foggy graveyard"), "packs keep catalog order")

    def test_nothing_selected_means_no_vocabulary_section(self):
        self.assertEqual(vocabulary_prompt(selected_vocabulary(self.catalog, {"packs": []})), "")

    def test_unknown_packs_and_malformed_selections_are_refused(self):
        for selection in (["Spaces/Gone"], {"packs": "Spaces/Fantasy"}, {"packs": [], "entries": {}}, {"packs": [1]}):
            with self.subTest(selection=selection), self.assertRaises(CatalogError):
                validate_selection(self.catalog, selection)
        self.assertEqual(validate_selection(self.catalog, None), {"packs": []})

    def test_record(self):
        selection = validate_selection(self.catalog, ["Lighting/Cinematic", "Lighting/Cinematic"])
        self.assertEqual(record(self.catalog, selection),
                         {"packs": [{"id": "Lighting/Cinematic", "name": "Cinematic", "category": "Lighting", "entries": 3}]})


if __name__ == "__main__":
    unittest.main()
