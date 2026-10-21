"""The vocabulary library: Core's three files, the registered category folders and their packs (catalog.py)."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tests.helpers import enter_context

from goated_prompter.features.vocabulary import catalog
from goated_prompter.features.vocabulary.catalog import (CatalogError, catalog_for, import_pack, load_catalog, record,
                                                         selected_vocabulary, validate_selection, vocabulary_prompt)

CATEGORIES = ["Subjects", "Actions & Poses", "Spaces", "Objects & Props", "Expressions", "Clothing", "Mood & Tone",
              "Lighting", "Camera & Composition", "Effects & Atmosphere"]


def isolate_imports(case):
    """Point the imported-pack folder at an empty temporary one, so the user's own data/vocabulary never counts."""
    folder = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, folder, True)
    enter_context(case, patch.object(catalog, "USER_ROOT", folder))
    return folder


class Bundled(unittest.TestCase):
    def setUp(self):
        isolate_imports(self)

    def test_core_registers_the_ten_categories_with_definitions_and_instructions(self):
        loaded = load_catalog()
        self.assertEqual(loaded["problems"], [])
        self.assertEqual([row["id"] for row in loaded["categories"]], CATEGORIES)
        for row in loaded["categories"]:
            # A renamed category keeps its folder, so pack ids (and saved selections) stay the same.
            self.assertEqual(row["folder"], "Objects" if row["id"] == "Objects & Props" else row["id"])
            self.assertTrue(row["description"] and row["use_when"])
            self.assertTrue(row["instruction"].startswith(f"{row['id']} provides vocabulary"), row["instruction"])
            self.assertNotIn("{", row["instruction"])

    def test_camera_vocabulary_is_turned_into_what_the_image_shows(self):
        camera = next(row for row in load_catalog()["categories"] if row["id"] == "Camera & Composition")
        self.assertIn("Turn an entry into what the image shows", camera["instruction"])
        self.assertIn("never a reason to cut a person of the cast down to a body part", camera["instruction"])

    def test_core_is_exactly_three_files(self):
        self.assertEqual(sorted(path.name for path in (catalog.ROOT / "core").iterdir()),
                         ["category_definitions.json", "prompt_instructions.json", "scene_category_registry.json"])

    def test_every_starter_pack_has_a_description_and_20_to_40_entries_in_its_folder(self):
        loaded = load_catalog()
        self.assertEqual(len(loaded["packs"]), 63)
        folders = {row["folder"]: row["id"] for row in loaded["categories"]}
        self.assertEqual({pack["source"] for pack in loaded["packs"]}, {"built-in"})
        for path in sorted(catalog.ROOT.glob("*/*.json")):
            if path.parent.name == "core":
                continue
            with self.subTest(pack=str(path.relative_to(catalog.ROOT))):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(set(data), {"name", "category", "description", "entries"})
                self.assertEqual(data["category"], folders[path.parent.name])
                self.assertTrue(all(isinstance(entry, str) and entry for entry in data["entries"]))
                self.assertIsInstance(data["description"], str)
                self.assertTrue(1 <= len(data["description"].strip()) <= 300)
                self.assertTrue(20 <= len(data["entries"]) <= 40)
                self.assertTrue(all(len(entry) <= 300 for entry in data["entries"]))
                self.assertEqual(len({" ".join(entry.casefold().split()) for entry in data["entries"]}),
                                 len(data["entries"]), "entries must be distinct")
        names = {pack["id"]: pack["name"] for pack in loaded["packs"]}
        self.assertEqual(names["Spaces/Sci-Fi"], "Sci-Fi")
        self.assertEqual(names["Actions & Poses/Solo-Activities"], "Solo Activities")


class Library(unittest.TestCase):
    """A synthetic library copied from the bundled Core."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(catalog.ROOT / "core", self.root / "core")
        self.user = isolate_imports(self)

    def pack(self, folder, stem, content):
        (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / folder / f"{stem}.json").write_text(content if isinstance(content, str) else json.dumps(content), "utf-8")

    def core(self, name, change):
        path = self.root / "core" / name
        path.write_text(json.dumps(change(json.loads(path.read_text(encoding="utf-8")))), "utf-8")

    def test_a_new_pack_needs_only_its_file(self):
        self.pack("Actions & Poses", "Dragon-Poses", {"name": "Dragon Poses", "category": "Actions & Poses",
                                                        "entries": ["wings fully extended", "perched on a cliff"]})
        packs = load_catalog(self.root)["packs"]
        self.assertEqual([(pack["id"], pack["category"]) for pack in packs], [("Actions & Poses/Dragon-Poses", "Actions & Poses")])
        groups = selected_vocabulary(load_catalog(self.root), {"packs": ["Actions & Poses/Dragon-Poses"]})
        self.assertEqual(groups[0]["category"], "Actions & Poses")

    def test_an_imported_pack_is_saved_in_its_category_folder_and_listed_after_the_built_in_ones(self):
        self.pack("Spaces", "Fantasy", {"name": "Fantasy", "category": "Spaces", "entries": ["floating castle"]})
        text = json.dumps({"name": "My Rooftops", "category": "Spaces", "entries": ["rooftop bar", "rooftop bar", "water tower"]})
        pack = import_pack("my rooftops.json", text, self.root)
        self.assertEqual((pack["id"], pack["source"], pack["entries"]),
                         ("data/Spaces/my-rooftops", "imported", ["rooftop bar", "water tower"]))
        self.assertTrue((self.user / "Spaces" / "my-rooftops.json").is_file())
        packs = load_catalog(self.root)["packs"]
        self.assertEqual([item["id"] for item in packs], ["Spaces/Fantasy", "data/Spaces/my-rooftops"])
        replaced = import_pack("my rooftops.json", json.dumps({"name": "My Rooftops", "category": "Spaces",
                                                                "entries": ["sky garden"]}), self.root)
        self.assertEqual(replaced["entries"], ["sky garden"], "importing the same file again replaces it")
        groups = selected_vocabulary(load_catalog(self.root), {"packs": ["data/Spaces/my-rooftops"]})
        self.assertEqual(groups[0]["packs"][0]["entries"], ["sky garden"])

    def test_a_pack_may_carry_its_authors_description(self):
        self.pack("Objects", "Paint", {"name": "Paint", "category": "Objects & Props",
                                       "description": "Paint marks for painterly scenes; entries name the colour.",
                                       "entries": ["red paint splash"]})
        self.pack("Objects", "Plain", {"name": "Plain", "category": "Objects & Props", "entries": ["mug"]})
        packs = {pack["name"]: pack for pack in load_catalog(self.root)["packs"]}
        self.assertEqual(packs["Paint"]["description"], "Paint marks for painterly scenes; entries name the colour.")
        self.assertEqual(packs["Plain"]["description"], "", "a pack without a description still loads")
        saved = import_pack("paint.json", json.dumps({"name": "Paint", "category": "Objects & Props",
                                                      "description": "  Paint   marks. ", "entries": ["a"]}), self.root)
        self.assertEqual(saved["description"], "Paint marks.")
        stored = json.loads((self.user / "Objects" / "paint.json").read_text(encoding="utf-8"))
        self.assertEqual(list(stored), ["name", "category", "description", "entries"])
        for bad in ("", 7, "x" * 301):
            with self.subTest(description=bad), self.assertRaisesRegex(ValueError, "description"):
                import_pack("bad.json", json.dumps({"name": "X", "category": "Spaces", "description": bad, "entries": ["a"]}),
                            self.root)

    def test_a_description_stays_with_its_own_entries_in_the_prompt(self):
        groups = [{"category": "Objects & Props", "instruction": "Objects & Props provides vocabulary.",
                   "packs": [{"name": "Plain", "description": "", "entries": ["mug", "paint splash"]},
                             {"name": "Paint", "description": "for painterly scenes", "entries": ["paint splash", "brush"]}]}]
        text = vocabulary_prompt(groups)
        self.assertIn('Available vocabulary:\nPack "Paint" (its author\'s note: for painterly scenes):\npaint splash\nbrush\n'
                      'Pack "Plain":\nmug', text)
        self.assertEqual(text.count("paint splash"), 1, "an entry in two packs is listed once")
        self.assertNotIn("Pack ", vocabulary_prompt([{**groups[0], "packs": [groups[0]["packs"][0]]}]),
                         "without descriptions the list stays plain")

    def test_an_import_is_checked_before_anything_is_saved(self):
        for text, problem in (("{ not json", "not valid JSON"),
                              (json.dumps({"name": "X", "category": "Nowhere", "entries": ["a"]}), "not a vocabulary category"),
                              (json.dumps({"name": "X", "category": "Spaces", "entries": []}), "entries must be"),
                              (json.dumps({"name": "X", "category": "Spaces", "entries": ["a"], "extra": 1}), "exactly")):
            with self.subTest(problem=problem), self.assertRaisesRegex(ValueError, problem):
                import_pack("pack.json", text, self.root)
        self.assertFalse(any(self.user.rglob("*.json")))

    def test_a_broken_imported_file_is_a_problem_named_with_its_folder(self):
        (self.user / "Spaces").mkdir(parents=True)
        (self.user / "Spaces" / "Broken.json").write_text("{ not json", "utf-8")
        self.assertEqual([row["file"] for row in load_catalog(self.root)["problems"]], ["data/Spaces/Broken.json"])

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
        self.assertEqual(len(empty["categories"]), 10)


class Selection(unittest.TestCase):
    def setUp(self):
        isolate_imports(self)
        self.catalog = load_catalog()

    def test_only_selected_categories_reach_the_prompt_with_their_core_instruction(self):
        selection = validate_selection(self.catalog, ["Spaces/Fantasy", "Clothing/Fantasy-Outfits", "Effects & Atmosphere/Magic-Effects"])
        text = vocabulary_prompt(selected_vocabulary(self.catalog, selection))
        self.assertTrue(text.startswith("SELECTED VOCABULARY:\n\nSpaces\nCore instruction:\nSpaces provides vocabulary"))
        for heading in ("Spaces\nCore instruction:", "Clothing\nCore instruction:", "Effects & Atmosphere\nCore instruction:"):
            self.assertEqual(text.count(heading), 1)
        for absent in ("Subjects", "Actions & Poses", "Lighting"):
            self.assertNotIn(f"\n{absent}\nCore instruction:", text)
        self.assertIn('Pack "Fantasy" (its author\'s note:', text)
        self.assertIn("enchanted forest\nancient dragon temple\nfloating castle", text)
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
                         {"packs": [{"id": "Lighting/Cinematic", "name": "Cinematic", "category": "Lighting", "entries": 20}]})


if __name__ == "__main__":
    unittest.main()
