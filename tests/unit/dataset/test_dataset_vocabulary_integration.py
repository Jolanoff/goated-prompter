"""Phase 5: vocabulary packs in Dataset Section 2 (scenes), with a scripted Director and temporary packs.

No model, no GPU and no user data: the packs live in a temporary folder and the Director answers with
fixed, well-formed JSON while recording every request it receives.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.features.dataset.v2 import intent, scenes, vocabulary_packs
from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, PackManager

FIXTURE_PACKS = Path(__file__).resolve().parents[1] / "vocabulary" / "fixtures" / "packs"


def being():
    return {"count": 1, "kind": "being"}


SCENE_PACK = [
    {"id": "scene:body.person", "category": "body", "name": "Person", "aliases": ["person", "human", "man", "woman"],
     "description": "An ordinary adult human.", "extends": ["general:body.humanoid"],
     "components": {"body": {"complete_for": ["core:locomotion"]}}},
    {"id": "scene:action.embrace", "category": "action", "name": "Embrace", "aliases": ["hug", "cuddle"],
     "description": "Two people with their arms wrapped around each other.", "components": {
         "participants": {"slots": {"holder": being(), "held": being()}},
         "requirements": {"participants": {"holder": {"all_of": ["core:limb.arm"]}, "held": {"all_of": ["core:limb.arm"]}}},
         "spatial": {"participants": {"holder": {"posture": "general:posture.standing", "facing": {"toward": "held"},
                                                 "anchors": [{"relation": "in_front", "of": "held", "distance": "contact"}]},
                                      "held": {"posture": "general:posture.standing", "facing": {"toward": "holder"}}},
                     "access": [{"from": "holder", "using": "core:limb.hand", "to": "held", "regions": ["core:anatomy.back"],
                                 "kind": "touch"}]}}},
    {"id": "scene:space.sofa", "category": "space", "name": "Sofa", "aliases": ["couch", "settee"],
     "description": "A padded seat for two or three people.", "components": {"environment": {"provides": ["core:surface.wide"]}}},
    {"id": "scene:position.aerial_carry", "category": "position", "name": "Aerial carry",
     "description": "One flies while holding the other in their arms.", "components": {
         "participants": {"slots": {"carrier": being(), "carried": being()}},
         "requirements": {"participants": {"carrier": {"all_of": ["core:locomotion.flight"]}}}}},
    {"id": "scene:action.duel", "category": "action", "name": "Sword duel", "rating": "mature",
     "description": "Two fighters cross blades.", "components": {
         "participants": {"slots": {"a": being(), "b": being()}},
         "requirements": {"participants": {"a": {"all_of": ["core:limb.hand"]}, "b": {"all_of": ["core:limb.hand"]}}}}},
]


def packs_folder(root, *, broken=False):
    """core (bundled) plus fantasy, adult and a small scene pack installed in a temporary folder."""
    install = root / "packs"
    install.mkdir()
    for name in ("fantasy", "adult", "general"):
        source = Path(__file__).resolve().parents[3] / "vocabulary/packs/general" if name == "general" else FIXTURE_PACKS / name
        shutil.copytree(source, install / name)
    scene = install / "scene"
    scene.mkdir()
    manifest = {"spec": 1, "id": "scene", "name": "Scene", "version": "1.0.0", "rating": "general",
                "requires": {"core": ">=1.0.0", "general": ">=1.0.0"}, "files": ["entries.json"]}
    (scene / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (scene / "entries.json").write_text(json.dumps({"spec": 1, "entries": SCENE_PACK}), encoding="utf-8")
    if broken:
        (install / "broken").mkdir()
        (install / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
    return PackManager(install_dir=install, state_file=root / "state.json", bundled_dirs=BUNDLED_DIRS,
                       official_dir=root / "no-official")  # the fixture packs only, not vocabulary/packs


CAST = [{"label": "Ana", "gender": "female", "custom": "", "pronoun": "she"},
        {"label": "Ben", "gender": "male", "custom": "", "pronoun": "he"}]
PEOPLE = [{"label": "woman", "gender": "female", "custom": "woman", "pronoun": "she"},
          {"label": "man", "gender": "male", "custom": "man", "pronoun": "he"}]


def brief(request, *, characters=CAST, path=None, avoid=(), must=(), rules=(), nsfw=False, amount=2):
    path = path or ("nsfw_character" if nsfw else "sfw_character" if characters else "non_character")
    characters = [] if path == "non_character" else [dict(item, custom=item["custom"] if item["gender"] == "custom" else "")
                                                     for item in characters]
    return {"version": 9, "path": path, "summary": request, "people": len(characters), "characters": characters,
            "fixed": "The people and the request.", "randomized": "place, light, camera", "must": list(must), "avoid": list(avoid),
            "input": {"request": request, "trigger": "", "trigger_at_start": False, "rules": list(rules), "amount": amount, "nsfw": nsfw},
            "settings": {"style": "", "target": "", "director": "", "length": "", "creativity": "Balanced"}}


PLACES = ("harbour quay", "attic studio", "pine forest", "rooftop garden", "library corner", "market lane")
POSES = ("standing close together", "seated side by side", "walking arm in arm", "leaning on a rail",
         "kneeling on a rug", "facing the window")


def summary(vocabulary):
    """The two fields every run's vocabulary record has had since Phase 5 (diagnostics are checked separately)."""
    return {key: vocabulary[key] for key in ("enabled", "provided")}


class ScriptedDirector(GoatedPrompterBackend):
    """Answers each Section 2 request with well-formed JSON and keeps every request it saw."""
    name = "scripted-director"

    def __init__(self):
        self.calls = []

    def generate(self, instruction):
        self.calls.append(instruction)
        user = json.loads(instruction.user_message)
        labels = [item["label"] for item in user["characters"]]
        stage = instruction.diagnostic_stage.split(":")[1]
        if stage == "concepts":
            start = len(user["earlier_concepts"])
            # The images asked for: those after the earlier ones, or the ones named when others were already kept.
            numbers = user.get("images") or list(range(start + 1, start + user["concepts_needed"] + 1))
            concepts = [{
                "place": PLACES[number - 1], "position_name": POSES[number - 1], "position": f"variation {POSES[number - 1]}",
                "looks": {label: "warm skin, slim, short hair" for label in labels}, "lighting": "soft daylight",
                "camera": "medium shot"} for number in numbers]
            return json.dumps({"concepts": concepts})
        if stage == "stagings":
            stagings = [{"reach": "Nothing is against the touched part.",
                         "position": {label: f"{label} stands on the floor" for label in labels},
                         "actions": "They greet each other."} for _ in user["concepts"]]
            return json.dumps({"stagings": stagings})
        finishing = "open" in instruction.json_schema["properties"]["scenes"]["items"]["properties"]
        return json.dumps({"scenes": [{
            "subjects": {label: {"skin": "warm", "build": "slim", "hair": "short", "detail": "freckles", "clothing": "linen shirt"}
                         for label in labels},
            "space": "a quiet room", "lighting": "soft daylight", "mood": "calm", "camera": "medium shot",
            "extras": "a lamp", **({"open": {label: "a relaxed expression" for label in labels}} if finishing else {})}
            for _ in user["scenes"]]})


class RecordingTrace:
    """DebugTrace without files: the record stays in memory for the test."""
    records = []

    def __init__(self, stage, **inputs):
        self.record = {"stage": stage, "input": inputs, "attempts": [], "decisions": [], "output": None, "error": None}
        RecordingTrace.records.append(self.record)

    def attempt(self, **details):
        self.record["attempts"].append(details)

    def decide(self, rule, detail):
        self.record["decisions"].append({"rule": rule, "detail": detail})

    def finish(self, output=None, error=None):
        self.record.update(output=output, error=error)


class Section2Run(unittest.TestCase):
    """Runs Section 2 with the scripted Director, temporary packs and an in-memory trace (no tests here)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.packs = packs_folder(self.root)
        RecordingTrace.records = []
        for target, value in (("DebugTrace", RecordingTrace), ("create_backend", lambda _config: self.director)):
            patcher = mock.patch.object(scenes, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_scenes(self, value, *, packs=None, config=None):
        self.director = ScriptedDirector()
        result = scenes.write_scenes({"backend": "mock", **(config or {})}, SimpleNamespace(selected_prompt_model="Default"),
                                     copy.deepcopy(value), progress=lambda _message: None, packs=packs or self.packs)
        log = next(item["detail"] for item in RecordingTrace.records[-1]["decisions"] if item["rule"] == "vocabulary")
        return result, log

    def users(self, stage):
        return [json.loads(call.user_message) for call in self.director.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]


class Section2Vocabulary(Section2Run):

    # -- retrieval reaches the Director
    def test_relevant_vocabulary_is_composed_before_finishing(self):
        result, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        self.assertEqual(summary(result["vocabulary"]), {"enabled": True, "provided": log["provided"]})
        self.assertIn("scene:action.embrace", log["provided"])
        self.assertIn("scene:space.sofa", log["provided"])
        self.assertFalse(self.users("concepts") or self.users("stagings"))
        self.assertTrue(self.users("scenes"))
        self.assertFalse([user for user in self.users("scenes") if "vocabulary" in user], "finishing gets checked facts, not suggestions")
        self.assertTrue(all(scene["arrangement"]["kind"] == "vocabulary" for scene in result["scenes"]))
        self.assertEqual(log["provided_to"], ["composition"])
        self.assertTrue(result["complete"])

    def test_the_result_keeps_export_safe_diagnostics_by_image(self):
        result, log = self.run_scenes(brief("a woman doing an aerial carry of a man in her arms, then hugging on a sofa",
                                            characters=PEOPLE))
        kept = result["vocabulary"]
        self.assertEqual([entry["id"] for entry in kept["entries"]], [entry["id"] for entry in log["entries"]])
        self.assertEqual(set(kept["entries"][0]), set(vocabulary_packs.ENTRY_FIELDS))
        self.assertEqual([image["slot"] for image in kept["images"]], [1, 2])
        self.assertEqual(kept["images"][0]["entries"], log["scenes"][0]["entries"])
        excluded = {item["id"]: item["reason"] for item in kept["excluded"]}
        self.assertIn("conflict", excluded["scene:position.aerial_carry"])
        self.assertEqual(kept["allowed_ratings"], ["general", "mature"])
        self.assertIsNone(kept["selection"], "no recorded selection: the enabled packs were read")
        text = json.dumps(kept)
        for private in ('"description"', '"notes"', '"block"', "VOCABULARY ("):
            self.assertNotIn(private, text, "pack wording stays in the debug trace")

    def test_a_recorded_selection_is_kept_with_versions_and_fingerprints(self):
        selection = self.packs.resolve_selection(["scene"])
        self.director = ScriptedDirector()
        result = scenes.write_scenes({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"),
                                     brief("two friends hugging on a sofa", characters=PEOPLE), progress=lambda _message: None,
                                     packs=self.packs, vocabulary=selection)
        kept = result["vocabulary"]["selection"]
        self.assertEqual(kept["selected"], ["scene"])
        self.assertEqual({item["id"]: item["fingerprint"] for item in kept["packs"]},
                         {item["id"]: item["fingerprint"] for item in selection["packs"]})
        off = vocabulary_packs.vocabulary_reference({"backend": "mock"}, brief("x"), manager=self.packs,
                                                    selection={**selection, "enabled": False, "selected": [], "packs": []})
        self.assertEqual(off["diagnostics"]["reason"], "the run's pack selection uses no vocabulary")
        self.assertFalse(off["diagnostics"]["enabled"])

    def test_the_log_records_entries_findings_and_what_was_provided(self):
        _, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        self.assertEqual(log["packs"], ["adult", "core", "fantasy", "general", "scene"])
        self.assertEqual(log["allowed_ratings"], ["general", "mature"])
        embrace = next(entry for entry in log["entries"] if entry["id"] == "scene:action.embrace")
        self.assertEqual(embrace["status"], "feasible")
        self.assertTrue(embrace["why"])
        self.assertEqual([member["body"] for member in log["cast"]], ["scene:body.person"] * 2)
        self.assertIn("- Embrace", log["block"])
        json.dumps(log)  # the debug trace is written as JSON

    # -- conflicts and unknowns
    def test_confirmed_conflicts_are_never_offered(self):
        _, log = self.run_scenes(brief("a woman doing an aerial carry of a man in her arms", characters=PEOPLE))
        self.assertNotIn("scene:position.aerial_carry", log["provided"])
        reason = next(item["reason"] for item in log["excluded"] if item["id"] == "scene:position.aerial_carry")
        self.assertIn("conflict", reason)
        self.assertNotIn("Aerial carry", "".join(user.get("vocabulary", "") for user in self.users("concepts")))

    def test_unknown_entries_stay_as_optional_suggestions(self):
        robots = [{"label": "Unit A", "gender": "custom", "custom": "robot", "pronoun": "it"},
                  {"label": "Unit B", "gender": "custom", "custom": "robot", "pronoun": "it"}]
        _, log = self.run_scenes(brief("two robots hugging", characters=robots))
        embrace = next(entry for entry in log["entries"] if entry["id"] == "scene:action.embrace")
        self.assertEqual(embrace["status"], "unknown")
        composed = log["composer"]["images"]
        self.assertTrue(all(image["status"] == "unknown" for image in composed))

    # -- no vocabulary
    def test_nothing_relevant_changes_nothing(self):
        value = brief("a perfume bottle on marble", characters=[])
        result, log = self.run_scenes(value)
        self.assertEqual((log["provided"], log["block"], log["provided_to"]), ([], "", []))
        self.assertIn("no relevant vocabulary for this request", log["warnings"])
        on = [(call.system_message, call.user_message) for call in self.director.calls]
        self.run_scenes(value, config={"dataset_vocabulary": False})
        self.assertEqual([(call.system_message, call.user_message) for call in self.director.calls], on,
                         "byte-for-byte the requests of a run without vocabulary")
        self.assertTrue(result["complete"])

    def test_core_only_and_broken_packs_never_break_generation(self):
        core_only = PackManager(install_dir=self.root / "none", state_file=self.root / "none.json", bundled_dirs=BUNDLED_DIRS,
                                official_dir=self.root / "no-official")
        result, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE), packs=core_only)
        self.assertTrue(result["complete"])
        self.assertEqual(log["packs"], ["core"])
        broken_root = self.root / "broken"
        broken_root.mkdir()
        result, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE), packs=packs_folder(broken_root, broken=True))
        self.assertTrue(result["complete"])
        self.assertIn("could not be loaded", log["error"])
        self.assertEqual(summary(result["vocabulary"]), {"enabled": True, "provided": []})
        self.assertFalse([user for user in self.users("concepts") if "vocabulary" in user])

    def test_switching_vocabulary_off_uses_the_freeform_flow(self):
        value = brief("two friends hugging on a sofa", characters=PEOPLE)
        result, _ = self.run_scenes(value)
        on = list(self.director.calls)
        off_result, off_log = self.run_scenes(value, config={"dataset_vocabulary": False})
        self.assertEqual(summary(off_result["vocabulary"]), {"enabled": False, "provided": []})
        self.assertIn("turned off", off_log["reason"])
        self.assertEqual(len(on), 1)
        self.assertEqual([call.diagnostic_stage for call in self.director.calls],
                         ["dataset_v2:concepts", "dataset_v2:stagings", "dataset_v2:scenes"])
        self.assertTrue(all(scene["arrangement"]["kind"] == "freeform" for scene in off_result["scenes"]))
        self.assertTrue(all(scene["arrangement"]["kind"] == "vocabulary" for scene in result["scenes"]))

    def test_the_switch_must_be_a_boolean(self):
        with self.assertRaises(ValueError):
            self.run_scenes(brief("two friends hugging", characters=PEOPLE), config={"dataset_vocabulary": "off"})

    # -- the user's constraints win
    def test_the_users_avoid_and_rules_rule_entries_out(self):
        _, log = self.run_scenes(brief("two friends cuddling on a couch", characters=PEOPLE, avoid=["no hugging"]))
        self.assertNotIn("scene:action.embrace", log["provided"])
        self.assertTrue(any(item["id"] == "scene:action.embrace" and "ruled out" in item["reason"] for item in log["excluded"]))
        self.assertIn("scene:space.sofa", log["provided"], "the rest of the request still finds vocabulary")
        _, log = self.run_scenes(brief("two friends hugging on a couch", characters=PEOPLE, rules=["no sofas"]))
        self.assertNotIn("scene:space.sofa", log["provided"])
        self.assertIn("scene:action.embrace", log["provided"])

    def test_the_request_and_rules_stay_in_the_brief_above_the_vocabulary(self):
        value = brief("two friends hugging on a sofa", characters=PEOPLE, must=["outdoors"], rules=["keep it playful"])
        self.run_scenes(value)
        user = self.users("scenes")[0]
        for key in ("request", "rules", "fixed", "randomized", "must", "avoid"):
            self.assertIn(key, user)
        self.assertEqual(user["request"], value["input"]["request"])
        self.assertTrue(user["scenes"][0]["facts"], "checked facts accompany the unchanged brief")
        self.assertIn("outrank everything else", self.director.calls[0].system_message)

    # -- characters
    def test_roles_and_identities_come_only_from_the_brief(self):
        value = brief("Ana hugs Ben on a sofa")
        result, log = self.run_scenes(value)
        self.assertIn("scene:action.embrace", log["provided"])
        block = log["block"]
        embrace = next(entry for entry in log["entries"] if entry["id"] == "scene:action.embrace")
        self.assertTrue(embrace["binding"], "retrieval binds the cast for its own check")
        for slot, labels in embrace["binding"].items():  # ...but the Director never sees that assignment
            self.assertNotIn(f"{slot}:", block)
            for label in labels:
                self.assertNotIn(label, block)
        for stage in ("concepts", "stagings", "scenes"):
            for user in self.users(stage):
                self.assertEqual(user["characters"], value["characters"])
        self.assertTrue(all(set(scene["subjects"]) == {"Ana", "Ben"} for scene in result["scenes"]))

    # -- ratings
    def test_sfw_never_offers_adult_entries(self):
        for value in (brief("a woman using a dildo on her partner", characters=PEOPLE),
                      # a brief whose input flag disagrees with its path still follows the path Section 2 writes for
                      {**brief("a woman using a dildo on her partner", characters=PEOPLE),
                       "input": {**brief("x")["input"], "request": "a woman using a dildo on her partner", "nsfw": True}}):
            with self.subTest(nsfw_flag=value["input"]["nsfw"]):
                if value["input"]["nsfw"]:
                    with self.assertRaisesRegex(ValueError, "NSFW switch"):
                        self.run_scenes(value)
                    continue
                _, log = self.run_scenes(value)
                self.assertEqual(log["allowed_ratings"], ["general", "mature"])
                self.assertFalse([entry for entry in log["entries"] if entry["rating"] == "adult"])
                self.assertTrue(any(item["id"] == "adult:item.dildo" and "rating" in item["reason"] for item in log["excluded"]))
        _, log = self.run_scenes(brief("a woman using a dildo on her partner", characters=PEOPLE, nsfw=True))
        self.assertIn("adult:item.dildo", log["provided"], "NSFW allows adult entries")

    # -- pollution
    def test_unrelated_vocabulary_does_not_reach_scene_planning(self):
        _, log = self.run_scenes(brief("a red sports car on a mountain road at dusk", characters=[]))
        self.assertEqual(log["provided"], [])
        self.assertFalse([user for user in self.users("concepts") if "vocabulary" in user])
        # People with an open arrangement and place get ideas for those two only, never unrelated entries.
        _, log = self.run_scenes(brief("a quiet afternoon reading", characters=PEOPLE))
        self.assertEqual(log["entries"], [])
        self.assertEqual({entry["category"] for entry in log["inspiration"]}, {"position", "space"})
        self.assertTrue(all(entry["pack"] == "general" and entry["rating"] == "general" for entry in log["inspiration"]))
        self.assertTrue(all(len(entry["binding"] or {}) == 2 or entry["category"] == "space" for entry in log["inspiration"]))
        _, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        unrelated = {"scene:action.duel", "scene:position.aerial_carry", "fantasy:action.cast_on", "adult:item.dildo"}
        self.assertFalse(unrelated & set(log["provided"]), log["provided"])
        self.assertLessEqual(len(log["block"]), 1200)


class IntentVocabulary(Section2Run):
    def understood(self, text="Two friends greet each other", terms=("Embrace",)):
        value = brief(text, characters=PEOPLE)
        value.update(version=10, fixed=text, randomized="lighting")
        value["input"]["seed"] = 7
        value["intent"] = intent.normalize({"elements": [
            {"id": "s1", "kind": "subject", "text": "woman", "character": "woman", "status": "fixed", "source": "request"},
            {"id": "s2", "kind": "subject", "text": "man", "character": "man", "status": "fixed", "source": "request"},
            {"id": "a", "kind": "action", "text": "greet", "by": ["s1"], "to": ["s2"],
             "status": "fixed", "source": "request", "terms": list(terms)}], "relations": []},
            value["characters"], value["avoid"], [text])
        return value

    def reference(self, value, selected=None):
        selection = vocabulary_packs.select_packs({}, ["scene"] if selected is None else selected, manager=self.packs)
        return vocabulary_packs.vocabulary_reference({}, value, manager=self.packs, selection=selection)

    def extend_pack(self, entries):
        path = self.root / "packs/scene/entries.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["entries"].extend(entries)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_semantic_hints_reach_director_only_as_optional_ideas(self):
        value = self.understood()
        before = copy.deepcopy(value)
        result, log = self.run_scenes(value)
        self.assertIn("scene:action.embrace", log["provided"])
        self.assertNotIn("scene:action.embrace", [entry["id"] for entry in log["entries"]],
                         "a semantic hint is not named by the request")
        self.assertNotIn("Embrace", log["intent"]["fixed"].get("interaction", []))
        for user in self.users("scenes"):
            self.assertEqual(user["fixed"], value["fixed"])
            self.assertEqual(user["must"], [])
        self.assertNotIn("scene:action.embrace", log["composer"]["required"])
        self.assertEqual(value, before, "retrieval cannot rewrite participant links or the brief")
        self.assertTrue(result["complete"])

    def test_recorded_camera_is_neither_search_evidence_nor_a_vocabulary_constraint(self):
        from goated_prompter.features.dataset.v2 import understanding
        from tests.unit.dataset.test_dataset_understanding_v10 import draft
        cases = json.loads((Path(__file__).parent / "fixtures/understanding_gemma_smoke.json").read_text(encoding="utf-8"))
        case = cases["two-men-simplified"]
        value = understanding.apply_rules(copy.deepcopy(case["responses"][0]), draft(case["request"]), mock.Mock())
        self.extend_pack([
            {"id": "scene:item.camera", "category": "item", "name": "Camera",
             "components": {"object": {"hands": 1, "provides": ["core:item.handheld"]}}},
            {"id": "scene:action.photography", "category": "action", "name": "Photography", "components": {
                "participants": {"slots": {"actor": being(), "subject": being()}}}},
        ])
        # Hints on the ungrounded object must not leak either, even though the model labelled it request/fixed.
        camera = next(item for item in value["intent"]["elements"] if item["id"] == "o2")
        camera["terms"] = ["Sword duel"]
        photo = next(item for item in value["intent"]["elements"] if item["id"] == "a2")
        photo["terms"] = ["Photography"]
        before = copy.deepcopy(value)
        reference = self.reference(value)
        log = reference["log"]
        self.assertNotIn("scene:item.camera", reference["provided"])
        self.assertNotIn("scene:action.duel", reference["provided"])
        self.assertIn("scene:action.photography", reference["provided"], "grounded photographing remains usable")
        self.assertNotIn("Camera", json.dumps(log["intent"]["fixed"]))
        self.assertNotIn("camera", intent.search_hints(value))
        self.assertEqual(value, before)
        self.assertEqual((photo["by"], photo["to"]), (["s2"], ["s1"]))
        playing = next(item for item in value["intent"]["elements"] if item["id"] == "a1")
        self.assertEqual((playing["by"], playing["to"]), (["s1"], ["o1"]))
        self.assertEqual([value["intent"]["elements"][n]["cast"] for n in (0, 3)], [["man 1"], ["man 2"]])
        self.assertEqual(value["must"], [])

    def test_unusable_or_ambiguous_intent_has_exact_v9_retrieval_fallback(self):
        for mode in ("v9", "unavailable", "unresolved", "truncated", "invalid"):
            with self.subTest(mode=mode):
                value = self.understood()
                baseline = {key: field for key, field in value.items() if key != "intent"}
                baseline["version"] = 9
                if mode == "v9":
                    value["version"] = 9
                elif mode == "unavailable":
                    value["intent"] = intent.unavailable("unusable response")
                elif mode in ("unresolved", "truncated"):
                    value["intent"][mode] = ["Unclear actor"] if mode == "unresolved" else True
                else:
                    value["intent"]["elements"][-1]["to"] = ["missing"]
                actual, expected = self.reference(value), self.reference(baseline)
                for field in ("block", "provided"):
                    self.assertEqual(actual[field], expected[field])
                self.assertEqual(actual["log"]["scenes"], expected["log"]["scenes"])

    def test_missing_hints_keep_original_wording_and_existing_named_matches(self):
        value = self.understood("Two friends hug", terms=())
        value["intent"]["elements"][-1]["text"] = "hug"
        reference = self.reference(value)
        self.assertIn("scene:action.embrace", reference["provided"])
        self.assertIn("scene:action.embrace", [item["id"] for item in reference["log"]["entries"]])
        self.assertIn("hug", intent.search_hints(value))

    def test_suggestions_scoped_inputs_and_missing_actors_do_not_open_search(self):
        for mode in ("suggested", "scoped", "unbound", "excluded", "unsupported"):
            with self.subTest(mode=mode):
                value = self.understood()
                action = value["intent"]["elements"][-1]
                if mode == "suggested":
                    action.update(source="suggested", status="randomized")
                elif mode == "scoped":
                    action["input"] = 1
                    value["input"]["guided_inputs"] = ["They greet"]
                elif mode == "unbound":
                    action["by"] = []
                elif mode == "excluded":
                    action["status"] = "excluded"
                else:
                    action["text"] = "duel"
                reference = self.reference(value)
                self.assertNotIn("scene:action.embrace", reference["provided"])

    def test_hints_obey_pack_selection_dependencies_and_isolation(self):
        value = self.understood()
        self.assertNotIn("scene:action.embrace", self.reference(value, selected=[])["provided"])
        path = self.root / "packs/scene/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["requires"]["fantasy"] = ">=0.1.0"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        first = self.reference(value)
        self.assertEqual(first["log"]["packs"], ["core", "fantasy", "general", "scene"])
        self.assertIn({"id": "fantasy", "role": "dependency"},
                      [{"id": item["id"], "role": item["role"]} for item in first["log"]["selection"]["packs"]])
        self.packs.set_enabled("adult", False)
        second = self.reference(value)
        self.assertEqual(first["block"], second["block"])
        self.assertEqual(first["log"]["scenes"], second["log"]["scenes"])

    def test_hints_use_existing_ratings_conflict_and_avoid_checks(self):
        self.extend_pack([{"id": "scene:action.flourish", "category": "action", "name": "Forbidden flourish", "rating": "adult",
                           "components": {"participants": {"slots": {"actor": being()}}}}])
        for terms, avoid, forbidden in [
            (("Forbidden flourish",), [], "scene:action.flourish"),
            (("Aerial carry",), [], "scene:position.aerial_carry"),
            (("Embrace",), ["no hugging"], "scene:action.embrace"),
        ]:
            with self.subTest(terms=terms):
                value = self.understood(terms=terms)
                value["avoid"] = avoid
                reference = self.reference(value, selected=["scene", "adult"])
                self.assertNotIn(forbidden, reference["provided"])
                if terms == ("Forbidden flourish",):
                    self.assertTrue(any(item["id"] == forbidden and "rating" in item["reason"]
                                        for item in reference["log"]["excluded"]))
                if terms == ("Aerial carry",):
                    self.assertTrue(any(item["id"] == forbidden and "conflict" in item["reason"]
                                        for item in reference["log"]["excluded"]))

    def test_retrieval_preserves_valid_ownership_and_target_links(self):
        value = self.understood("A woman greets a man while holding his hand")
        value["intent"]["elements"].insert(2, {"id": "b", "kind": "body_part", "text": "hand", "status": "fixed",
            "source": "request", "character": "", "member": 0, "cast": [], "of": "s2", "by": [], "to": [], "input": 0, "terms": []})
        value["intent"]["elements"][-1]["to"] = ["b"]
        before = copy.deepcopy(value)
        self.reference(value)
        self.assertEqual(value, before)
        self.assertEqual(value["intent"]["elements"][-1]["to"], ["b"])
        self.assertEqual(value["intent"]["elements"][2]["of"], "s2")

    def test_hint_concepts_match_pack_tags_without_becoming_named_entries(self):
        entry = copy.deepcopy(SCENE_PACK[1])
        entry.update(id="scene:action.reunion", name="Gathered embrace", aliases=[], tags=["friendly_reunion"])
        self.extend_pack([entry])
        reference = self.reference(self.understood(terms=("Friendly reunion",)))
        self.assertIn("scene:action.reunion", reference["provided"])
        self.assertNotIn("scene:action.reunion", [entry["id"] for entry in reference["log"]["entries"]])
        self.assertEqual(reference["log"]["intent"]["fixed"], {})

    def test_hinted_alternatives_do_not_override_a_fixed_interaction(self):
        value = self.understood("Two friends hug", terms=("Sword duel",))
        value["intent"]["elements"][-1]["text"] = "hug"
        reference = self.reference(value)
        self.assertIn("scene:action.embrace", reference["provided"])
        self.assertNotIn("scene:action.duel", reference["provided"])
        self.assertNotIn("Sword duel", json.dumps(reference["log"]["intent"]["fixed"]))

    def test_negated_search_hint_cannot_create_an_exclusion(self):
        value = self.understood("Two friends hug", terms=("no Embrace",))
        value["intent"]["elements"][-1]["text"] = "hug"
        reference = self.reference(value)
        self.assertIn("scene:action.embrace", reference["provided"])
        self.assertEqual(value["avoid"], [])
        self.assertFalse(any(item["id"] == "scene:action.embrace" for item in reference["log"]["excluded"]))

    def test_pack_drift_still_requires_reconfirmation_before_hint_retrieval(self):
        value = self.understood()
        selection = vocabulary_packs.select_packs({}, ["scene"], manager=self.packs)
        self.extend_pack([{"id": "scene:space.hall", "category": "space", "name": "Hall",
                           "components": {"environment": {"provides": ["core:surface.wide"]}}}])
        with self.assertRaisesRegex(ValueError, "changed since this run was confirmed"):
            vocabulary_packs.vocabulary_reference({}, value, manager=self.packs, selection=selection)

    def test_optional_hint_pool_uses_existing_seeded_diversity(self):
        entries = []
        for ident, name in [("hello", "Open welcome"), ("farewell", "Warm farewell")]:
            entries.append({"id": f"scene:action.{ident}", "category": "action", "name": name, "components": {
                "participants": {"slots": {"actor": being()}},
                "claims": {"actor": [{"resource": "core:limb.hand", "count": 1, "mode": "shared", "purpose": "use"}]}}})
        self.extend_pack(entries)
        value = self.understood(terms=("Open welcome", "Warm farewell"))
        value["input"]["amount"] = 6
        first = self.reference(value)
        repeated = self.reference(value)
        self.assertEqual(first["log"]["scenes"], repeated["log"]["scenes"])
        action_ids = {"scene:action.hello", "scene:action.farewell"}
        offers = [set(scene["ideas"]) & action_ids for scene in first["log"]["scenes"]]
        self.assertTrue(all(len(items) == 1 for items in offers), offers)
        self.assertEqual(set.union(*offers), action_ids)
        self.assertTrue(all(previous != following for previous, following in zip(offers, offers[1:])))


class ProductionPacks(Section2Run):
    """The shipped packs (core, vocabulary/packs/fantasy and adult) through Section 2."""

    def setUp(self):
        super().setUp()
        # The official packs are discovered in vocabulary/packs; nothing is installed in data/.
        self.packs = PackManager(install_dir=self.root / "no-installed", state_file=self.root / "state.json",
                                 bundled_dirs=BUNDLED_DIRS)

    def test_the_ab_cases_now_receive_vocabulary(self):
        dragon = [{"label": "dragon", "gender": "custom", "custom": "dragon", "pronoun": "it"}]
        cases = [(brief("A woman and a man hugging goodbye on a train platform", characters=PEOPLE), {"general:action.hug"}),
                 (brief("A dragon resting on a cliff above a stormy sea", characters=dragon), {"general:space.cliff"}),
                 (brief("A woman holding a lantern while walking through a dark forest", characters=PEOPLE[:1]),
                  {"general:action.hold", "general:item.lantern"})]
        for value, expected in cases:
            with self.subTest(request=value["input"]["request"]):
                result, log = self.run_scenes(value)
                self.assertEqual(expected - set(log["provided"]), set(), log["provided"])
                self.assertTrue(result["complete"])
                self.assertTrue(result["vocabulary"]["composer"]["images"])
                self.assertFalse([entry for entry in log["entries"] if entry["rating"] == "adult"])
        self.assertEqual([member["body"] for member in log["cast"]], ["general:body.human"])

    def test_nsfw_brief_receives_adult_entries_and_keeps_its_cast(self):
        result, log = self.run_scenes(brief("Reverse cowgirl on a sofa", characters=PEOPLE, nsfw=True))
        self.assertIn("adult:position.reverse_cowgirl", log["provided"])
        self.assertNotIn("adult:position.cowgirl", log["provided"])
        self.assertEqual(log["allowed_ratings"], ["general", "mature", "adult"])
        self.assertTrue(all(set(scene["subjects"]) == {"woman", "man"} for scene in result["scenes"]))

    # -- inspiration: a broad request, per image, rotated by the seed
    def broad(self, seed=4, amount=6):
        men = [{"label": "man 1", "gender": "male", "custom": "", "pronoun": "he"},
               {"label": "man 2", "gender": "male", "custom": "", "pronoun": "he"}]
        value = brief("Two adult men having sex", characters=men, nsfw=True, amount=amount)
        value["randomized"] = "sex positions, location, lighting"
        value["input"]["seed"] = seed
        return value

    def test_a_broad_nsfw_brief_gets_ideas_for_each_image(self):
        result, log = self.run_scenes(self.broad())
        self.assertTrue(result["complete"])
        self.assertIn("adult:action.sex", {entry["id"] for entry in log["entries"]})
        self.assertTrue(all("adult:action.sex" in image["entries"] for image in log["composer"]["images"]),
                        "position inspiration cannot replace the requested activity")
        self.assertTrue(log["provided"])
        self.assertEqual(log["intent"]["content"], "adult")
        self.assertEqual(len(log["scenes"]), 6)
        self.assertEqual([image["kind"] for image in log["composer"]["images"]], ["vocabulary"] * 6)
        self.assertFalse(self.users("concepts") or self.users("stagings"))
        self.assertEqual([len(user["scenes"]) for user in self.users("scenes")], [5, 1])

    def test_each_finishing_request_gets_its_own_images_facts(self):
        with mock.patch.object(scenes, "PLAN_BATCH", 4), mock.patch.object(scenes, "BATCH", 2):
            result, log = self.run_scenes(self.broad(seed=8, amount=6))
        self.assertTrue(result["complete"])
        self.assertEqual([len(user["scenes"]) for user in self.users("scenes")], [2, 2, 2])
        offered = [scene for user in self.users("scenes") for scene in user["scenes"]]
        for scene, slot in zip(offered, result["scenes"]):
            self.assertEqual(scene["facts"], slot["arrangement"]["facts"])
        self.assertEqual([row["slot"] for row in log["composer"]["images"]], list(range(1, 7)))

    def test_the_seed_rotates_the_ideas_reproducibly(self):
        def vocabulary(seed):
            self.run_scenes(self.broad(seed))
            return [scene for user in self.users("scenes") for scene in user["scenes"]]
        first = vocabulary(4)
        self.assertEqual(first, vocabulary(4))
        self.assertTrue(any(first != vocabulary(other) for other in (5, 6, 7)))

    def test_the_log_is_the_engines_result_for_this_brief(self):
        from goated_prompter.features.vocabulary.retrieval import RetrievalConfig, RetrievalRequest, retrieve
        value = self.broad()
        _, log = self.run_scenes(value)
        found = retrieve(self.packs.registry(), RetrievalRequest.from_brief(value),
                         RetrievalConfig(allowed_ratings=("general", "mature", "adult")))
        self.assertEqual(log["inspiration"], found.to_dict()["inspiration"])
        self.assertEqual(log["scenes"], found.scenes(6))
        self.assertEqual(log["seed"], 4)

    def test_a_fixed_action_and_place_get_no_competing_ideas(self):
        value = brief("A woman and a man hugging goodbye on a train platform", characters=PEOPLE)
        value["randomized"] = "clothing, facial expression, lighting, weather, train station details, camera angle"
        _, log = self.run_scenes(value)
        self.assertEqual(log["provided"], ["general:action.hug"])
        self.assertEqual(log["inspiration"], [])

    def test_an_incompatible_pack_leaves_section_2_unchanged(self):
        folder = self.root / "no-installed" / "future"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({"spec": 1, "id": "future", "name": "Future", "version": "1.0.0",
                                                          "rating": "general", "requires": {"core": ">=9.0.0"},
                                                          "files": ["entries.json"]}), encoding="utf-8")
        (folder / "entries.json").write_text(json.dumps({"spec": 1, "entries": []}), encoding="utf-8")
        result, log = self.run_scenes(self.broad())
        self.assertIn("requires core", log["error"])
        self.assertEqual(summary(result["vocabulary"]), {"enabled": True, "provided": []})
        self.assertFalse([user for stage in ("concepts", "stagings") for user in self.users(stage) if "vocabulary" in user])
        self.assertTrue(result["complete"])

    def test_a_disabled_official_pack_is_not_offered(self):
        self.packs.set_enabled("adult", False)
        result, log = self.run_scenes(brief("Reverse cowgirl on a sofa", characters=PEOPLE, nsfw=True))
        self.assertEqual(log["packs"], ["core", "fantasy", "general", "visual"], "General and Visual are official packs too")
        self.assertFalse([entry_id for entry_id in log["provided"] if entry_id.startswith("adult:")])
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
