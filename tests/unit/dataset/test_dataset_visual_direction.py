"""Visual Direction inside Dataset V2 Section 2 (scenes.py): the concept's camera and lighting fields carry it.

A scripted Director answers every request; the bundled core and the read-only official packs (with the Visual
Direction pack) are read; runs are saved to a temporary store. No model, GPU or private data is used."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from goated_prompter.features.dataset.v2 import runs, scenes
from goated_prompter.features.vocabulary.packs import OFFICIAL_DIR, PackManager
from goated_prompter.features.vocabulary.visual import default_settings
from tests.unit.dataset.test_dataset_vocabulary_integration import PEOPLE, RecordingTrace, ScriptedDirector, brief


class ShortFirstDirector(ScriptedDirector):
    """Writes only four concepts the first time, so the remaining images are asked for again."""

    def generate(self, instruction):
        answer = super().generate(instruction)
        if instruction.diagnostic_stage == "dataset_v2:concepts" and not getattr(self, "shortened", False):
            self.shortened = True
            value = json.loads(answer)
            return json.dumps({"concepts": value["concepts"][:4]})
        return answer


class VisualRun(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "packs").mkdir()
        self.packs = PackManager(self.root / "packs", self.root / "state.json", official_dir=OFFICIAL_DIR)
        self.director = ScriptedDirector()
        RecordingTrace.records = []
        for target, value in (("DebugTrace", RecordingTrace), ("create_backend", lambda _config: self.director)):
            patcher = mock.patch.object(scenes, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_scenes(self, value, *, visual=None, selected=("visual",), director=None):
        self.director = director or ScriptedDirector()
        selection = self.packs.resolve_selection(list(selected))
        return scenes.write_scenes({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), copy.deepcopy(value),
                                   progress=lambda _message: None, packs=self.packs, vocabulary=selection, visual=visual)

    def calls(self, stage):
        return [call for call in self.director.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]

    def users(self, stage):
        return [json.loads(call.user_message) for call in self.calls(stage)]


class ConceptAndStaging(VisualRun):
    def test_each_concept_gets_its_own_images_directions(self):
        result = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE, amount=6), visual=default_settings())
        record = result["vocabulary"]["visual"]
        self.assertTrue(record["enabled"])
        offered = [scene for user in self.users("scenes") for scene in user["scenes"]]
        self.assertEqual(len(offered), 6)
        registry = self.packs.registry_for(self.packs.resolve_selection(["visual"]))
        for item, slot in zip(offered, record["slots"]):
            for dimension, entry_id in slot["directions"].items():
                section = "lighting" if dimension in ("lighting", "atmosphere") else "camera"
                section = registry.resolved(entry_id)["components"]["visual"].get("section", section)
                self.assertIn(registry.resolved(entry_id)["name"], item[section], (slot["slot"], dimension))

    def test_the_rules_ride_on_the_existing_camera_and_lighting_fields(self):
        self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE, amount=3), visual=default_settings())
        self.assertFalse(self.calls("concepts") or self.calls("stagings"))
        self.assertIn("come from Visual Direction", self.calls("scenes")[0].system_message)
        self.assertTrue(all("camera" in scene and "lighting" in scene for scene in self.users("scenes")[0]["scenes"]))

    def test_a_retried_concept_keeps_its_images_directions(self):
        result = self.run_scenes(brief("a perfume bottle on marble", characters=[], amount=6), visual=default_settings(),
                                 director=ShortFirstDirector())
        first, second = self.users("concepts")[:2]
        self.assertEqual(len(second["earlier_concepts"]), 4)
        again = self.run_scenes(brief("a perfume bottle on marble", characters=[], amount=6), visual=default_settings())
        whole = self.users("concepts")[0]["visual_direction"]
        self.assertEqual([{**item, "concept": index} for index, item in enumerate(whole[4:], 1)], second["visual_direction"])
        self.assertEqual(first["visual_direction"][:4], whole[:4])
        self.assertEqual(result["vocabulary"]["visual"]["slots"], again["vocabulary"]["visual"]["slots"])

    def test_a_fixed_camera_is_kept_for_every_image_and_masked_from_content_retrieval(self):
        value = brief("low angle shots of two friends hugging on a sofa", characters=PEOPLE, amount=4)
        result = self.run_scenes(value, visual=default_settings())
        self.assertTrue(all(item["camera"].count("Low angle") == 1 for item in self.users("scenes")[0]["scenes"]))
        dimensions = result["vocabulary"]["visual"]["dimensions"]
        self.assertEqual((dimensions["camera_angle"]["status"], dimensions["camera_angle"]["source"]), ("fixed", "request"))
        self.assertIn("low angl", result["vocabulary"]["visual"]["masked"])
        self.assertEqual(self.users("scenes")[0]["request"], value["input"]["request"], "the Director still reads the brief as written")

    def test_nsfw_and_larger_casts(self):
        trio = PEOPLE + [{"label": "partner", "gender": "female", "custom": "woman", "pronoun": "she"}]
        result = self.run_scenes(brief("three adults on a bed", characters=trio, nsfw=True, amount=4), visual=default_settings())
        record = result["vocabulary"]["visual"]
        self.assertEqual(record["people"], 3)
        self.assertNotIn({"id": "general:framing.extreme_close_up", "reason": "not for 3 people per image"}, record["excluded"])
        self.assertIn("This dataset is sexual and explicit", self.calls("scenes")[0].system_message)
        self.assertTrue(self.users("scenes")[0]["scenes"][0]["camera"])


class WithoutVisualDirection(VisualRun):
    def test_core_directions_need_no_visual_pack_and_all_disabled_changes_no_request(self):
        value = brief("low angle shots of two friends hugging on a sofa", characters=PEOPLE, amount=3)
        self.run_scenes(value, visual=None)
        baseline = [(call.system_message, call.user_message) for call in self.director.calls]
        self.run_scenes(value, visual=default_settings(), selected=())
        self.assertNotEqual([(call.system_message, call.user_message) for call in self.director.calls], baseline,
                            "Core owns framing, camera, composition and light even without the Visual pack")
        self.assertFalse(any("atmosphere" in row["directions"] for row in self.run_scenes(
            value, visual=default_settings(), selected=())["vocabulary"]["visual"]["slots"]))
        self.run_scenes(value, visual={dimension: {"enabled": False} for dimension in default_settings()})
        self.assertEqual([(call.system_message, call.user_message) for call in self.director.calls], baseline)
        self.assertFalse([user for user in self.users("concepts") if "visual_direction" in user])

    def test_vocabulary_switched_off_turns_it_off_too(self):
        self.director = ScriptedDirector()
        result = scenes.write_scenes({"backend": "mock", "dataset_vocabulary": False}, SimpleNamespace(selected_prompt_model="Default"),
                                     brief("two friends", characters=PEOPLE, amount=2), progress=lambda _message: None,
                                     packs=self.packs, visual=default_settings())
        self.assertFalse(result["vocabulary"]["visual"]["enabled"])
        self.assertIn("no vocabulary packs", result["vocabulary"]["visual"]["reason"])
        self.assertFalse([user for user in self.users("concepts") if "visual_direction" in user])


class Diagnostics(VisualRun):
    def test_the_run_record_keeps_what_each_image_was_given_and_why_others_were_not(self):
        value = brief("two friends hugging on a sofa, no dutch angle", characters=PEOPLE, amount=3)
        value["settings"]["style"] = "Anime"
        result = self.run_scenes(value, visual=default_settings())
        store = runs.DatasetRunStore(self.root / "runs")
        recorder = runs.RunRecorder.start(store, "job-1", value, inputs={1: "", 2: "", 3: ""},
                                          packs=self.packs.resolve_selection(["visual"]))
        recorder.scenes_finished(result)
        kept = store.get(recorder.run_id)["vocabulary"]["visual"]
        self.assertEqual(kept, json.loads(json.dumps(result["vocabulary"]["visual"])))
        self.assertEqual([slot["slot"] for slot in kept["slots"]], [1, 2, 3])
        excluded = {item["id"]: item["reason"] for item in kept["excluded"]}
        self.assertEqual(excluded["general:camera_angle.dutch_angle"], "ruled out by the brief")
        self.assertIn("Anime", excluded["visual:atmosphere.film_grain"])
        self.assertEqual(kept["style"], "Anime")
        self.assertEqual(set(kept["dimensions"]), {"framing", "camera_angle", "composition", "lighting", "atmosphere"})
        self.assertEqual(store.get(recorder.run_id)["vocabulary"]["selection"]["selected"], ["visual"])


if __name__ == "__main__":
    unittest.main()
