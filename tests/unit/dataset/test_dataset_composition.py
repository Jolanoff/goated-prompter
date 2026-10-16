"""Code-owned mechanics survive finishing and reach Builder; scripted backend only."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.backends.base import GoatedPrompterError
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.v2 import prompts, scenes, vocabulary_packs
from goated_prompter.features.vocabulary.packs import PackManager
from goated_prompter.features.vocabulary.resolver import resolve
from goated_prompter.prompting.directors import DIRECTOR_VOCABULARY
from goated_prompter.local_jobs import Job
from tests.unit.dataset.test_dataset_vocabulary_integration import PEOPLE, RecordingTrace, ScriptedDirector, brief

FIXTURE = Path(__file__).parent / "fixtures/v2_hold_conflict_run.json"


class ComposedScenes(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.packs = PackManager(self.root / "packs", self.root / "state.json")
        self.director = ScriptedDirector()
        for target, value in (("DebugTrace", RecordingTrace), ("create_backend", lambda _: self.director)):
            patcher = mock.patch.object(scenes, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_scenes(self, value, **kwargs):
        return scenes.write_scenes({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), value,
                                   packs=self.packs, progress=lambda _: None, **kwargs)

    def test_composed_scene_uses_only_finishing_and_keeps_checked_mechanics(self):
        events = []
        result = self.run_scenes(brief("two friends hug on a sofa", characters=PEOPLE), on_slot=lambda *args: events.append(args))
        self.assertTrue(result["complete"])
        self.assertEqual(len(self.director.calls), 1)
        call = self.director.calls[0]
        self.assertIn("open", call.json_schema["properties"]["scenes"]["items"]["properties"])
        user = json.loads(call.user_message)
        self.assertIn("Hug", json.dumps(user["scenes"]))
        self.assertNotIn("core:", json.dumps(user["scenes"]))
        for scene in result["scenes"]:
            self.assertIn("Hug", scene["actions"])
            self.assertEqual(scene["arrangement"]["kind"], "vocabulary")
            self.assertTrue(scene["arrangement"]["facts"])
            self.assertIn("a relaxed expression", scene["position"]["woman"])
        self.assertEqual([(stage, number) for stage, number, _ in events],
                         [("concept", 1), ("concept", 2), ("description", 1), ("description", 2)])

    def test_finishing_retries_only_the_bad_image_with_its_original_guided_input(self):
        class Short(ScriptedDirector):
            def generate(self, instruction):
                value = json.loads(super().generate(instruction))
                if len(self.calls) == 1:
                    value["scenes"] = value["scenes"][:1]
                return json.dumps(value)
        self.director = Short()
        value = brief("two friends hug on a sofa", characters=PEOPLE)
        value["input"].update(source_mode="guided", guided_inputs=["hug", "hug on a sofa"])
        result = self.run_scenes(value)
        self.assertTrue(result["complete"])
        users = [json.loads(call.user_message) for call in self.director.calls]
        self.assertEqual([len(user["scenes"]) for user in users], [2, 1])
        self.assertEqual(users[1]["scenes"][0], users[0]["scenes"][1])
        self.assertEqual(users[1]["scenes"][0]["input"], "hug on a sofa")

    def test_finishing_failure_is_bounded_and_identifies_its_stage(self):
        self.director.generate = mock.Mock(return_value='{"scenes": []}')
        result = self.run_scenes(brief("two friends hug", characters=PEOPLE, amount=1))
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing"][0]["stage"], "finishing")
        self.assertEqual(self.director.generate.call_count, scenes.ROUNDS)

    def test_recorded_hand_conflict_is_avoided_during_composition(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value = scenes.validate_brief(copy.deepcopy(fixture["brief"]))
        reference = vocabulary_packs.vocabulary_reference({}, value, manager=self.packs,
                                                         director="holding or guiding", preferences={
                                                             "prefer": {"entries": ["general:action.hold"]}})
        registry = self.packs.registry()
        for number in range(1, 11):
            record = reference["composer"].compose(number)
            # The installed packs do not define domination. A generic placement
            # is no longer misreported as fulfillment of that confirmed action.
            self.assertEqual((record["kind"], record["status"]), ("freeform", "unchecked"))
            self.assertIn("dominating", record["reason"])
            # Replay exactly the conflict that previously needed LLM repair.
        cast = [{"id": "man", "body": "general:body.human"}, {"id": "sex slave man", "body": "general:body.human"}]
        bad = resolve(registry, {"cast": cast, "objects": [{"id": "item", "item": None}], "use": [
            {"entry": "general:position.from_behind", "bind": {"front": "man", "back": "sex slave man"}},
            {"entry": "general:action.hold", "bind": {"holder": "man", "item": "item"}}]})
        self.assertEqual(bad.status, "conflict")

    def test_established_mechanics_place_and_items_reach_builder(self):
        result = self.run_scenes(brief("a woman holding a lantern on a sofa", characters=PEOPLE[:1], amount=1))
        seen = []
        class Service:
            def __init__(self, *args, **kwargs):
                pass

            def generate_text_only(self, request, **kwargs):
                seen.append(request)
                return SimpleNamespace(prompt="a prompt")
        value = scenes.validate_brief(brief("a woman holding a lantern on a sofa", characters=PEOPLE[:1], amount=1))
        with mock.patch.object(prompts, "GoatedPrompterService", Service), mock.patch.object(prompts, "DebugTrace"):
            prompts.write_prompts({"backend": "mock"}, GoatedPrompterRequest(idea="", planning_mode="Direct"), value,
                                  result["scenes"], progress=lambda _: None)
        self.assertIn("ESTABLISHED SCENE FACTS", seen[0].custom_instructions)
        self.assertIn("Lantern", seen[0].idea)
        self.assertIn("Sofa", seen[0].idea)

    def test_mirror_selfie_contract_keeps_activity_phone_hand_and_reflection_together(self):
        value = brief("two adults having sex", characters=PEOPLE, nsfw=True, amount=3)
        value["settings"].update(director="mirror_selfie", target="Krea 2")
        reference = vocabulary_packs.vocabulary_reference({}, value, manager=self.packs,
            preferences=DIRECTOR_VOCABULARY["mirror_selfie"])
        for number in range(1, 4):
            record = reference["composer"].compose(number)
            self.assertEqual(record["kind"], "vocabulary", record)
            entries = {entry["id"] for entry in record["entries"]}
            self.assertTrue({"adult:action.sex", "general:action.mirror_selfie"} <= entries)
            self.assertNotIn("adult:action.undressing_partner", entries)
            self.assertEqual({item["id"] for item in record["items"]}, {"general:item.phone", "general:item.mirror"})
            self.assertIn("reflection", record["visual"]["camera"])
            self.assertTrue(any("hold" in fact and "hand" in fact for fact in record["facts"]))
            # Gender is not anatomy: this request leaves genitals undeclared.
            self.assertEqual(record["status"], "unknown")
            self.assertFalse(record["verified"])
            self.assertEqual(record["checked"], [])
            view = scenes.composed_view(record)
            self.assertFalse(view["verified"])
            self.assertTrue(view["unresolved"])

    def test_finisher_cannot_replace_composed_camera_and_builder_cannot_drop_mechanics(self):
        value = brief("two adults having sex", characters=PEOPLE, nsfw=True, amount=1)
        reference = vocabulary_packs.vocabulary_reference({}, value, manager=self.packs,
            preferences=DIRECTOR_VOCABULARY["mirror_selfie"])
        record = reference["composer"].compose(1)
        finish = {"subjects": {person["label"]: {key: "detail" for key in scenes.SUBJECT_FIELDS} for person in PEOPLE},
                  "open": {person["label"]: "a relaxed expression" for person in PEOPLE},
                  "space": "a different place", "lighting": "daylight", "mood": "calm", "camera": "unrelated camera",
                  "extras": "a lamp"}
        scene = scenes._composed_scene(1, record, finish, [person["label"] for person in PEOPLE])
        self.assertEqual(scene["camera"], record["visual"]["camera"])
        if record["space"]:
            self.assertNotIn("a different place", scene["space"])
        self.assertIsNotNone(prompts.mechanics_problem("two people undressing", scene))
        # Meaning, not wording: any phrasing of each checked row (its name or an alias) keeps the scene.
        checked = [row for row in prompts.preserved(scene) if row["check"]]
        self.assertTrue(checked)
        expressed = ", ".join(row["phrases"][-1] for row in checked)
        self.assertIsNone(prompts.mechanics_problem(expressed, scene))
        self.assertNotIn("(a:", expressed)
        class DropsMechanics:
            def __init__(self, *args, **kwargs):
                pass

            def generate_text_only(self, request, **kwargs):
                return SimpleNamespace(prompt="two people undressing")
        with mock.patch.object(prompts, "GoatedPrompterService", DropsMechanics), mock.patch.object(prompts, "DebugTrace"):
            result = prompts.write_prompts({}, GoatedPrompterRequest(idea="", planning_mode="Direct"), value,
                                           [scene], progress=lambda _: None)
        self.assertEqual(result[0]["prompt"], "")
        self.assertFalse(result[0]["mechanics_preserved"])
        self.assertIn("lost part of the established scene", result[0]["error"])

    def test_symmetric_confirmed_activity_and_director_can_be_verified_with_declared_anatomy(self):
        from goated_prompter.features.dataset.v2 import intent
        characters = [{"label": label, "gender": "custom", "custom": "adult human with a penis", "pronoun": "they"}
                      for label in ("first adult", "second adult")]
        value = brief("two adults having sex", characters=characters, nsfw=True, amount=1)
        value["version"] = 10
        value["intent"] = intent.normalize({"elements": [
            {"id": "a", "kind": "subject", "text": "first adult", "character": "first adult", "source": "request", "status": "fixed"},
            {"id": "b", "kind": "subject", "text": "second adult", "character": "second adult", "source": "request", "status": "fixed"},
            {"id": "act", "kind": "action", "text": "having sex", "by": ["a", "b"], "source": "request", "status": "fixed"}
        ], "relations": []}, characters, [], [value["summary"]])
        record = vocabulary_packs.vocabulary_reference({}, value, manager=self.packs,
            preferences=DIRECTOR_VOCABULARY["mirror_selfie"])["composer"].compose(1)
        self.assertEqual(record["status"], "feasible", record)
        self.assertTrue(record["verified"])
        self.assertEqual(len(record["items"]), 2)


class RunStatus(unittest.TestCase):
    def test_a_run_without_any_scene_fails_with_its_reasons(self):
        empty = {"complete": False, "requested": 2, "written": 0, "scenes": [], "concepts": [], "slots": [],
                 "vocabulary": {"enabled": True, "provided": []},
                 "missing": [{"slot": number, "stage": "composition", "tries": 0, "input": "",
                              "reasons": ["the named entry does not fit this cast"]} for number in (1, 2)]}
        job = Job()
        with mock.patch.object(runner, "write_scenes", return_value=empty), \
                mock.patch.object(runner, "write_prompts") as builder, mock.patch.object(runner, "create_backend"), \
                mock.patch.object(runner, "resolve_director_config", return_value=({}, None)):
            with self.assertRaisesRegex(GoatedPrompterError, "No scene could be written.*the named entry does not fit this cast"):
                runner.run_dataset_v2_scenes(None, job, GoatedPrompterRequest(idea="x", planning_mode="Direct"),
                                             {"backend": "mock"}, {"brief": brief("x")})
        builder.assert_not_called()
        self.assertEqual(job.result["written"], 0)
        self.assertNotEqual(job.status, "succeeded")

    def test_an_incomplete_run_says_so(self):
        self.assertIsNone(runner.incomplete({"complete": True}))
        message = runner.incomplete({"complete": False, "written": 7, "requested": 10,
                                     "missing": [{"slot": 1}, {"slot": 4}, {"slot": 8}]})
        self.assertEqual(message, "Generation finished incomplete: 7 of 10 scenes written; not written: images 1, 4, 8.")
        job = Job()
        job.deliver({"ok": True}, message)
        self.assertEqual((job.status, job.status_reason), ("succeeded", message))
