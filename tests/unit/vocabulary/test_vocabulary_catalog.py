"""The vocabulary library: Core's three files, the registered category folders and their packs (catalog.py)."""

import itertools
import json
from pathlib import Path
import re
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
        self.assertEqual(len([pack for pack in loaded["packs"] if not pack.get("always")]), 63)
        folders = {row["folder"]: row["id"] for row in loaded["categories"]}
        self.assertEqual({pack["source"] for pack in loaded["packs"]}, {"built-in"})
        for path in sorted(catalog.ROOT.glob("*/*.json")):
            if path.parent.name == "core" or json.loads(path.read_text(encoding="utf-8")).get("always"):
                continue  # always-on catalogs have their own shape (test_always_on_catalogs_are_distinct_and_safe)
            with self.subTest(pack=str(path.relative_to(catalog.ROOT))):
                data = json.loads(path.read_text(encoding="utf-8"))
                # Actions & Poses packs give their cast size (vocabulary/SKILL.md): on the pack, and on an entry that differs.
                acts = path.parent.name == "Actions & Poses"
                content = "groups" if "groups" in data else "entries"
                self.assertEqual(set(data) - ({"people"} if acts else set()), {"name", "category", "description", content})
                self.assertEqual(data["category"], folders[path.parent.name])
                if content == "groups":  # grouped packs: trigger words, people for poses and worlds for places
                    places = path.parent.name == "Spaces"
                    self.assertFalse([group["group"] for group in data["groups"]
                                      if not {"group", "words", "entries"} <= set(group)
                                      or set(group) - {"group", "words", "entries", *(["people"] if acts else []),
                                                       *(["worlds"] if places else [])}])
                    data["entries"] = [entry for group in data["groups"] for entry in group["entries"]]
                data["entries"] = [entry["text"] if acts and isinstance(entry, dict) and set(entry) == {"text", "people"}
                                   else entry for entry in data["entries"]]
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

    def test_always_on_catalogs_are_distinct_and_safe(self):
        # The built-in catalogs every run deals from: groups of 20 to 50 places with the words a request uses for them,
        # each place in one group and named once, no two places alike (a catalog that grows must not fill with near
        # copies), every group's worlds named (a backdrop fits every world) and nothing adult (vocabulary/SKILL.md).
        from goated_prompter.features.dataset.v2.safety import adult_text
        from goated_prompter.features.vocabulary.retrieval import entry_name as head
        from goated_prompter.options.dataset import WORLDS
        words = lambda text: set(re.findall(r"[a-z0-9]+", text.casefold())) - {"a", "an", "the", "and", "with", "of", "on", "in"}
        always = catalog.always_on(load_catalog(user_root=False), "Spaces")
        self.assertEqual([pack["id"] for pack in always], ["Spaces/Backdrops", "Spaces/Everyday-Places",
                                                           "Spaces/Fantasy-Places", "Spaces/Fun-and-Creative-Places",
                                                           "Spaces/Outer-Space"])
        groups = [group for pack in always for group in pack["groups"]]
        entries = [entry for pack in always for entry in pack["entries"]]
        self.assertGreater(len(entries), 1500)
        self.assertEqual(sorted(place for group in groups for place in group["entries"]), sorted(entries))
        self.assertFalse([group["name"] for group in groups if not 20 <= len(group["entries"]) <= 50], "20 to 50 a group")
        self.assertEqual(len({group["name"] for group in groups}), len(groups), "every group named once")
        self.assertEqual({group["name"] for group in groups if group.get("adult_default")}, {"bedroom", "hotel room"})
        self.assertEqual([group["name"] for group in groups if not group.get("worlds")], ["plain backdrop"],
                         "every group names its worlds but the backdrops, which fit every one")
        self.assertTrue(set(WORLDS) >= {world for group in groups for world in group.get("worlds") or ()})
        self.assertFalse([word for group in groups for word in group["words"] if adult_text(word)])
        names = [head(entry).casefold() for entry in entries]
        self.assertEqual(len(set(names)), len(names), "every place has its own name")
        sets = [words(entry) for entry in entries]
        near = [(entries[a], entries[b]) for a, b in itertools.combinations(range(len(entries)), 2)
                if len(sets[a] & sets[b]) / len(sets[a] | sets[b]) >= .6]
        self.assertEqual(near, [], "near copies")
        self.assertFalse([entry for entry in entries if adult_text(entry)])

    def test_the_built_in_looks_are_hair_eyes_and_skin_in_one_female_and_one_male_group(self):
        # Looks the run deals to people whose looks vary: build and marks come from the request, never from a look, and
        # no two looks share their eyes and skin.
        from goated_prompter.features.dataset.v2.safety import adult_text
        from goated_prompter.features.vocabulary.retrieval import entry_name as head
        always = [pack for pack in catalog.always_on(load_catalog(user_root=False), "Subjects")
                  if not any("kinds" in group for group in pack["groups"])]  # people's looks; Non-Human below
        self.assertEqual([pack["id"] for pack in always], ["Subjects/Female", "Subjects/Male"])
        self.assertEqual([[group["name"] for group in pack["groups"]] for pack in always], [["female"], ["male"]])
        entries = [entry for pack in always for entry in pack["entries"]]
        self.assertFalse([entry for entry in entries if not re.fullmatch(r"\S.* with \S.* eyes and \S.* skin", entry)],
                         "hair, then eyes and skin")
        self.assertEqual(len({head(entry).casefold() for entry in entries}), len(entries), "every look has its own name")
        pairs = [entry.split(" with ", 1)[1] for entry in entries]
        self.assertEqual(len(set(pairs)), len(pairs), "every look has its own eyes and skin")
        words = [word for pack in always for group in pack["groups"] for word in group["words"]]
        self.assertFalse([text for text in [*words, *entries] if adult_text(text)])

    def test_the_built_in_non_human_looks_are_grouped_by_anatomy_in_four_parts(self):
        # Looks dealt to characters that are not humans: each group fits kinds of character, never a human, and every
        # entry is a covering, its texture or markings, eyes or lights and a build, so a part the request asks for is
        # kept and the others are dealt anew; a covering names one colour ("a black cat" never turns black and white).
        from goated_prompter.features.dataset.v2.safety import adult_text
        from goated_prompter.features.vocabulary.retrieval import entry_parts
        pack = next(pack for pack in catalog.always_on(load_catalog(user_root=False), "Subjects")
                    if pack["id"] == "Subjects/Non-Human")
        self.assertTrue(all(group.get("kinds") and "human" not in group["kinds"] for group in pack["groups"]))
        for group in pack["groups"]:
            shapes = {tuple(facet for facet, _ in entry_parts(entry)) for entry in group["entries"]}
            self.assertEqual(len(shapes), 1, group["name"])
            self.assertEqual(len(next(iter(shapes))), 4, group["name"])
            self.assertGreaterEqual(len(group["entries"]), 20)
        words = [word for group in pack["groups"] for word in group["words"]]
        self.assertFalse([text for text in [*words, *pack["entries"]] if adult_text(text)])


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

    def test_a_pack_may_say_how_many_people_its_entries_need(self):
        self.pack("Actions & Poses", "Pairs", {"name": "Pairs", "category": "Actions & Poses", "people": 2,
                                               "entries": ["two people dancing", {"text": "the person bowing", "people": 1}]})
        self.pack("Actions & Poses", "Mixed", {"name": "Mixed", "category": "Actions & Poses",
                                               "entries": ["a person waving", {"text": "a group of three posing", "people": 3}]})
        self.pack("Actions & Poses", "Plain", {"name": "Plain", "category": "Actions & Poses", "entries": ["a person sitting"]})
        packs = {pack["name"]: pack for pack in load_catalog(self.root)["packs"]}
        self.assertEqual(packs["Pairs"]["entries"], ["two people dancing", "the person bowing"], "entries stay texts")
        self.assertEqual(packs["Pairs"]["people"], {"two people dancing": 2, "the person bowing": 1})
        self.assertEqual(packs["Mixed"]["people"], {"a group of three posing": 3}, "an entry without a count gives none")
        self.assertNotIn("people", packs["Plain"], "a pack of plain texts is unchanged")
        groups = selected_vocabulary(load_catalog(self.root), {"packs": ["Actions & Poses/Mixed", "Actions & Poses/Plain"]})
        self.assertEqual([pack.get("people") for pack in groups[0]["packs"]], [{"a group of three posing": 3}, None])
        text = json.dumps({"name": "Pairs", "category": "Actions & Poses", "people": 2,
                           "entries": ["two people dancing", {"text": "the person bowing", "people": 1},
                                       {"text": "two people bowing", "people": 2}]})
        saved = import_pack("pairs.json", text, self.root)
        self.assertEqual(saved["people"], {"two people dancing": 2, "the person bowing": 1, "two people bowing": 2})
        stored = json.loads((self.user / "Actions & Poses" / "pairs.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["people"], 2)
        self.assertEqual(stored["entries"], ["two people dancing", {"text": "the person bowing", "people": 1},
                                             "two people bowing"], "saved as written, the pack's count once")
        for bad, problem in ((0, "people"), ("2", "people"), (21, "people"), (True, "people")):
            with self.subTest(people=bad), self.assertRaisesRegex(ValueError, problem):
                import_pack("bad.json", json.dumps({"name": "X", "category": "Spaces", "people": bad, "entries": ["a"]}),
                            self.root)
        for entry in ({"text": "a", "people": 0}, {"text": "a", "extra": 1}, {"people": 2}, {"text": ""}):
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, "entries"):
                import_pack("bad.json", json.dumps({"name": "X", "category": "Spaces", "entries": [entry]}), self.root)

    def test_each_pack_lists_the_packs_its_slots_name(self):
        self.pack("Objects", "Kitchen-and-Dining", {"name": "Kitchen & Dining", "category": "Objects & Props",
                                                     "entries": ["teapot", "wine glass"]})
        self.pack("Objects", "Furniture", {"name": "Furniture", "category": "Objects & Props", "entries": ["armchair"]})
        self.pack("Actions & Poses", "Dinner", {"name": "Dinner", "category": "Actions & Poses", "entries": [
            "two people at a table, one holding [Kitchen-and-Dining]", "one person seated in [Furniture: armchair]",
            "two people beside [Objects & Props]", "two people near [Nowhere]", "two people dancing"]})
        packs = {pack["id"]: pack for pack in load_catalog(self.root)["packs"]}
        self.assertEqual(packs["Actions & Poses/Dinner"]["links"], [
            {"slot": "Kitchen-and-Dining", "packs": ["Objects/Kitchen-and-Dining"]},
            {"slot": "Furniture", "packs": ["Objects/Furniture"]},
            {"slot": "Objects & Props", "packs": ["Objects/Furniture", "Objects/Kitchen-and-Dining"]},
            {"slot": "Nowhere", "packs": []}])
        self.assertNotIn("links", packs["Objects/Furniture"], "a pack without slots has no links")

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

    def test_a_run_without_packs_reads_only_the_built_in_packs(self):
        # The built-in packs hold the always-on catalogs every run deals from; the user's own folder is not read.
        with patch.object(catalog, "load_catalog", wraps=catalog.load_catalog) as loaded:
            empty = catalog_for({"packs": []}, self.root)
        self.assertEqual(loaded.call_args.args, (self.root, False))
        self.assertEqual(len(empty["categories"]), 10)
        self.assertTrue(all(pack["source"] == "built-in" for pack in empty["packs"]))

    def test_a_pack_may_hold_groups_with_their_words_and_be_always_on(self):
        data = {"name": "Places", "category": "Spaces", "always": True,
                "groups": [{"group": "bedroom", "words": ["His Room", "my room", "his room"], "adult_default": True,
                            "worlds": ["everyday", "fantasy", "everyday"], "entries": ["bedroom with a window", "attic bedroom"]},
                           {"group": "garden", "words": ["gardening"], "shapes": ["wide", "square", "wide"],
                            "entries": ["a garden"]}]}
        name, category, entries, description, people, groups, always = catalog._checked(data)
        self.assertEqual(entries, ["bedroom with a window", "attic bedroom", "a garden"], "the pack's entries are its groups'")
        self.assertEqual(groups, [{"name": "bedroom", "words": ["his room", "my room"], "adult_default": True,
                                   "worlds": ["everyday", "fantasy"], "entries": ["bedroom with a window", "attic bedroom"]},
                                  {"name": "garden", "words": ["gardening"], "shapes": ["wide", "square"],
                                   "entries": ["a garden"]}])
        self.assertTrue(always)
        saved = import_pack("places.json", json.dumps({**data, "always": False}), self.root)
        self.assertEqual((saved["entries"], saved["groups"]), (entries, groups), "an import keeps its groups")

    def test_a_group_may_list_actions_with_the_poses_they_can_be_done_in(self):
        data = {"name": "Acts", "category": "Actions & Poses",
                "groups": [{"group": "handling a lantern", "people": 1, "words": ["lantern"],
                            "poses": ["standing", "moving"], "actions": ["A raising a lantern", "A lowering a lantern"]},
                           {"group": "waving", "words": ["waving"], "entries": ["A waving"]}]}
        _, _, entries, _, people, groups, _ = catalog._checked(data)
        self.assertEqual(entries, ["A raising a lantern", "A lowering a lantern", "A waving"])
        self.assertEqual((groups[0]["poses"], groups[0].get("actions"), "poses" in groups[1], groups[1].get("actions")),
                         (["standing", "moving"], True, False, None), "actions say their poses; entries keep their way")
        saved = import_pack("acts.json", json.dumps(data), self.root)
        self.assertEqual([(group.get("actions"), group.get("poses")) for group in saved["groups"]],
                         [(True, ["standing", "moving"]), (None, None)], "an import keeps actions and poses as written")
        group = lambda **change: {"group": "g", "words": ["w"], "actions": ["A waving"], **change}
        for broken in ({"groups": [group(poses=["floating"])]}, {"groups": [group(poses=[])]},
                       {"groups": [{"group": "g", "words": ["w"], "actions": ["A"], "entries": ["B"]}]}):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                catalog._checked({"name": "Acts", "category": "Actions & Poses", **broken})

    def test_a_group_may_give_how_many_people_its_entries_need(self):
        data = {"name": "Poses", "category": "Actions & Poses", "people": 1,
                "groups": [{"group": "stretching", "words": ["stretching"], "entries": ["A stretching"]},
                           {"group": "sparring", "words": ["sparring"], "people": 2,
                            "entries": ["A and B sparring", {"text": "A, B and C sparring", "people": 3}]}]}
        people = catalog._checked(data)[4]
        self.assertEqual(people, {"A stretching": 1, "A and B sparring": 2, "A, B and C sparring": 3},
                         "an entry's own count, else its group's, else the pack's")
        saved = import_pack("poses.json", json.dumps(data), self.root)
        self.assertEqual((saved["people"], [group.get("people") for group in saved["groups"]]), (people, [None, 2]))
        with self.assertRaises(ValueError):
            catalog._checked({**data, "groups": [{"group": "g", "words": ["w"], "people": 0, "entries": ["a"]}]})
        group = lambda **change: {"group": "g", "words": ["w"], "entries": ["a"], **change}
        for broken in ({"always": "yes"}, {"entries": ["a"], "groups": [group()]}, {"groups": []},
                       {"groups": [group(words=[])]}, {"groups": [group(words=["x"] * 101)]},
                       {"groups": [group(), group(group="h", entries=["A"])]}, {"groups": [group(), group()]},
                       {"groups": [group(adult_default="yes")]}, {"groups": [group(more=1)]},
                       {"groups": [group(worlds=[])]}, {"groups": [group(worlds=["the moon"])]},
                       {"groups": [group(shapes=[])]}, {"groups": [group(shapes=["round"])]}):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                catalog._checked({"name": "Places", "category": "Spaces", **({"entries": ["a"]} if "groups" not in broken
                                                                             else {}), **broken})


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
        for place in ("enchanted forest", "ancient dragon temple", "floating castle"):
            self.assertIn(f"\n{place}\n", text)
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
