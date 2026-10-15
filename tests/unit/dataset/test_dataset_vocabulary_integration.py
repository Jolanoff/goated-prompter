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
from goated_prompter.features.dataset.v2 import scenes
from goated_prompter.features.vocabulary.packs import BUNDLED_DIRS, PackManager

FIXTURE_PACKS = Path(__file__).resolve().parents[1] / "vocabulary" / "fixtures" / "packs"


def being():
    return {"count": 1, "kind": "being"}


SCENE_PACK = [
    {"id": "scene:body.person", "category": "body", "name": "Person", "aliases": ["person", "human", "man", "woman"],
     "description": "An ordinary adult human.", "extends": ["core:body.humanoid"],
     "components": {"body": {"complete_for": ["core:locomotion"]}}},
    {"id": "scene:action.embrace", "category": "action", "name": "Embrace", "aliases": ["hug", "cuddle"],
     "description": "Two people with their arms wrapped around each other.", "components": {
         "participants": {"slots": {"holder": being(), "held": being()}},
         "requirements": {"participants": {"holder": {"all_of": ["core:limb.arm"]}, "held": {"all_of": ["core:limb.arm"]}}},
         "spatial": {"participants": {"holder": {"posture": "core:posture.standing", "facing": {"toward": "held"},
                                                 "anchors": [{"relation": "in_front", "of": "held", "distance": "contact"}]},
                                      "held": {"posture": "core:posture.standing", "facing": {"toward": "holder"}}},
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
    for name in ("fantasy", "adult"):
        shutil.copytree(FIXTURE_PACKS / name, install / name)
    scene = install / "scene"
    scene.mkdir()
    manifest = {"spec": 1, "id": "scene", "name": "Scene", "version": "1.0.0", "rating": "general",
                "requires": {"core": ">=1.0.0"}, "files": ["entries.json"]}
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
            return json.dumps({"concepts": [{
                "place": PLACES[start + n], "position_name": POSES[start + n], "position": f"variation {POSES[start + n]}",
                "looks": {label: "warm skin, slim, short hair" for label in labels}, "lighting": "soft daylight",
                "camera": "medium shot"} for n in range(user["concepts_needed"])]})
        if stage == "stagings":
            return json.dumps({"stagings": [{"reach": "Nothing is against the touched part.",
                                             "position": {label: f"{label} stands on the floor" for label in labels},
                                             "actions": "They greet each other."} for _ in user["concepts"]]})
        return json.dumps({"scenes": [{
            "subjects": {label: {"skin": "warm", "build": "slim", "hair": "short", "detail": "freckles", "clothing": "linen shirt"}
                         for label in labels},
            "space": "a quiet room", "lighting": "soft daylight", "mood": "calm", "camera": "medium shot",
            "extras": "a lamp"} for _ in user["scenes"]]})


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
    def test_relevant_vocabulary_reaches_concept_and_staging_only(self):
        result, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        self.assertEqual(result["vocabulary"], {"enabled": True, "provided": log["provided"]})
        self.assertIn("scene:action.embrace", log["provided"])
        self.assertIn("scene:space.sofa", log["provided"])
        for stage in ("concepts", "stagings"):
            for user in self.users(stage):
                self.assertIn("- Embrace", user["vocabulary"])
                self.assertIn("optional reference", user["vocabulary"])
        self.assertFalse([user for user in self.users("scenes") if "vocabulary" in user], "description never gets it")
        self.assertEqual(log["provided_to"], ["concept", "staging"])
        self.assertTrue(result["complete"])

    def test_the_log_records_entries_findings_and_what_was_provided(self):
        _, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        self.assertEqual(log["packs"], ["adult", "core", "fantasy", "scene"])
        self.assertEqual(log["allowed_ratings"], ["general", "mature"])
        embrace = next(entry for entry in log["entries"] if entry["id"] == "scene:action.embrace")
        self.assertEqual(embrace["status"], "feasible")
        self.assertTrue(embrace["why"])
        self.assertEqual([member["body"] for member in log["cast"]], ["scene:body.person"] * 2)
        self.assertIn("- Embrace", log["block"])
        json.dumps(log)  # the debug trace is written as JSON

    # -- conflicts and unknowns
    def test_confirmed_conflicts_are_never_offered(self):
        _, log = self.run_scenes(brief("a woman flies while carrying a man in her arms", characters=PEOPLE))
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
        self.assertIn("Embrace", self.users("concepts")[0]["vocabulary"])
        self.assertIn("(unknown)", self.users("concepts")[0]["vocabulary"])

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
        self.assertEqual(result["vocabulary"], {"enabled": True, "provided": []})
        self.assertFalse([user for user in self.users("concepts") if "vocabulary" in user])

    def test_switching_vocabulary_off_changes_only_the_vocabulary_field(self):
        value = brief("two friends hugging on a sofa", characters=PEOPLE)
        result, _ = self.run_scenes(value)
        on = list(self.director.calls)
        off_result, off_log = self.run_scenes(value, config={"dataset_vocabulary": False})
        self.assertEqual(off_result["vocabulary"], {"enabled": False, "provided": []})
        self.assertIn("turned off", off_log["reason"])
        self.assertEqual(len(on), len(self.director.calls))
        for first, second in zip(on, self.director.calls):
            self.assertEqual(first.system_message, second.system_message)
            with_vocabulary, without = json.loads(first.user_message), json.loads(second.user_message)
            with_vocabulary.pop("vocabulary", None)
            self.assertEqual(with_vocabulary, without)
        self.assertEqual(off_result["scenes"], result["scenes"], "the scripted Director answers the same")

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
        user = self.users("concepts")[0]
        for key in ("request", "rules", "fixed", "randomized", "must", "avoid"):
            self.assertIn(key, user)
        self.assertEqual(user["request"], value["input"]["request"])
        self.assertEqual(list(user).index("vocabulary"), list(user).index("style") + 1, "after the brief, as reference")
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
        self.assertTrue(all(entry["pack"] == "core" and entry["rating"] == "general" for entry in log["inspiration"]))
        self.assertTrue(all(len(entry["binding"] or {}) == 2 or entry["category"] == "space" for entry in log["inspiration"]))
        _, log = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE))
        unrelated = {"scene:action.duel", "scene:position.aerial_carry", "fantasy:action.cast_on", "adult:item.dildo"}
        self.assertFalse(unrelated & set(log["provided"]), log["provided"])
        self.assertLessEqual(len(log["block"]), 1200)


class ProductionPacks(Section2Run):
    """The shipped packs (core, vocabulary/packs/fantasy and adult) through Section 2."""

    def setUp(self):
        super().setUp()
        # The official packs are discovered in vocabulary/packs; nothing is installed in data/.
        self.packs = PackManager(install_dir=self.root / "no-installed", state_file=self.root / "state.json",
                                 bundled_dirs=BUNDLED_DIRS)

    def test_the_ab_cases_now_receive_vocabulary(self):
        dragon = [{"label": "dragon", "gender": "custom", "custom": "dragon", "pronoun": "it"}]
        cases = [(brief("A woman and a man hugging goodbye on a train platform", characters=PEOPLE), {"core:action.hug"}),
                 (brief("A dragon resting on a cliff above a stormy sea", characters=dragon), {"core:space.cliff"}),
                 (brief("A woman holding a lantern while walking through a dark forest", characters=PEOPLE[:1]),
                  {"core:action.hold", "core:item.lantern"})]
        for value, expected in cases:
            with self.subTest(request=value["input"]["request"]):
                result, log = self.run_scenes(value)
                self.assertEqual(expected - set(log["provided"]), set(), log["provided"])
                self.assertTrue(result["complete"])
                self.assertIn("vocabulary", self.users("concepts")[0])
                self.assertFalse([entry for entry in log["entries"] if entry["rating"] == "adult"])
        self.assertEqual([member["body"] for member in log["cast"]], ["core:body.human"])

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
        self.assertEqual(log["entries"], [], "the request names no entry")
        self.assertTrue(log["provided"])
        self.assertEqual(log["intent"]["content"], "adult")
        self.assertEqual(len(log["scenes"]), 6)
        concept = self.users("concepts")[0]["vocabulary"]
        self.assertIn("optional inspiration", concept)
        lines = {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in concept.splitlines() if line.startswith("- concept ")}
        self.assertEqual(sorted(lines), [f"- concept {number}" for number in range(1, 7)])
        # Staging is batched by five: the second staging request writes image 6 and gets image 6's ideas as its concept 1.
        second = self.users("stagings")[1]["vocabulary"]
        self.assertIn(f"- concept 1: {lines['- concept 6']}", second)
        self.assertNotIn("- concept 2: ", second)
        self.assertFalse([user for user in self.users("scenes") if "vocabulary" in user], "description never gets it")
        names = {entry["id"]: entry["name"] for entry in log["inspiration"]}
        self.assertEqual(lines["- concept 6"], "; ".join(names[entry_id] for entry_id in log["scenes"][5]["ideas"]))

    def test_each_concept_and_staging_request_gets_its_own_images_ideas(self):
        with mock.patch.object(scenes, "PLAN_BATCH", 4), mock.patch.object(scenes, "BATCH", 2):
            result, log = self.run_scenes(self.broad(seed=8, amount=6))
        self.assertTrue(result["complete"])
        names = {entry["id"]: entry["name"] for entry in log["inspiration"]}
        expected = {scene["scene"]: "; ".join(names[entry_id] for entry_id in scene["ideas"]) for scene in log["scenes"]}
        self.assertTrue(all(expected.values()), "every image has ideas")

        def lines(user):
            return [line.split(": ", 1)[1] for line in user["vocabulary"].splitlines() if line.startswith("- concept ")]
        self.assertEqual([lines(user) for user in self.users("concepts")], [[expected[n] for n in (1, 2, 3, 4)], [expected[5], expected[6]]])
        self.assertEqual([lines(user) for user in self.users("stagings")],
                         [[expected[1], expected[2]], [expected[3], expected[4]], [expected[5], expected[6]]])

    def test_the_seed_rotates_the_ideas_reproducibly(self):
        def vocabulary(seed):
            self.run_scenes(self.broad(seed))
            return self.users("concepts")[0]["vocabulary"]
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
        self.assertEqual(log["provided"], ["core:action.hug"])
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
        self.assertEqual(result["vocabulary"], {"enabled": True, "provided": []})
        self.assertFalse([user for stage in ("concepts", "stagings") for user in self.users(stage) if "vocabulary" in user])
        self.assertTrue(result["complete"])

    def test_a_disabled_official_pack_is_not_offered(self):
        self.packs.set_enabled("adult", False)
        result, log = self.run_scenes(brief("Reverse cowgirl on a sofa", characters=PEOPLE, nsfw=True))
        self.assertEqual(log["packs"], ["core", "fantasy"])
        self.assertFalse([entry_id for entry_id in log["provided"] if entry_id.startswith("adult:")])
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
