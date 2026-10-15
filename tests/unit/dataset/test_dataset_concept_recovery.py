"""Regression: the live V2 run that wrote 0 of 10 scenes (fixtures/v2_hold_conflict_run.json).

The recorded concept answer is replayed against the bundled core and official packs; each image's arrangement
options are the ones the run recorded. No model, GPU or private pack is used: the recorded options are all core."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.v2 import arrangements, scenes, vocabulary_packs
from goated_prompter.features.vocabulary.packs import OFFICIAL_DIR, PackManager
from goated_prompter.features.vocabulary.resolver import resolve
from goated_prompter.local_jobs import Job
from tests.unit.dataset.test_dataset_vocabulary_integration import RecordingTrace, ScriptedDirector

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "v2_hold_conflict_run.json").read_text(encoding="utf-8"))
MASTER, SLAVE = "man", "sex slave man"
FAILING = (1, 4, 8)  # from behind with the man as front (on all fours) and as holder


def recorded_brief(**changes):
    value = copy.deepcopy(FIXTURE["brief"])
    value["input"].update(changes)
    return value


class Recorded(arrangements.Arrangements):
    """The run's own per-image options (ids recorded in its diagnostics), with the live Director preference."""

    def options(self, number):
        entries = []
        for entry_id in FIXTURE["options"].get(str(number), []):
            entry = self.registry.resolved(entry_id)
            entries.append(SimpleNamespace(id=entry_id, name=entry["name"], description=entry.get("description", ""),
                                           status="eligible", binding=None))
        return entries

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.asked, self.preferred = set(), set(FIXTURE["director_prefers"])


class Replay(ScriptedDirector):
    """Answers every concept request with the recorded concepts of the images it asks for (as the live model did
    three times); fixes[n](concept) may change image n's concept from the call given in fix_from on."""

    def __init__(self, fixes=None, fix_from=1):
        super().__init__()
        self.fixes, self.fix_from, self.concept_calls = fixes or {}, fix_from, 0

    def generate(self, instruction):
        if instruction.diagnostic_stage != "dataset_v2:concepts":
            return super().generate(instruction)
        self.calls.append(instruction)
        user = json.loads(instruction.user_message)
        start = len(user["earlier_concepts"])
        numbers = user.get("images") or list(range(start + 1, start + user["concepts_needed"] + 1))
        answer = []
        for number in numbers:
            concept = copy.deepcopy(FIXTURE["concepts"][number - 1])
            if self.concept_calls >= self.fix_from and number in self.fixes:
                self.fixes[number](concept)
            answer.append(concept)
        self.concept_calls += 1
        return json.dumps({"concepts": answer})


def swap_roles(concept):
    """What the concept's own prose says: the man kneels behind and holds; the slave is on all fours."""
    for item in concept["arrangement"]:
        for role in item["roles"]:
            if item["option"] == "core:position.from_behind":
                role["who"] = [SLAVE] if role["role"] == "front" else [MASTER]


class RecoveryHarness(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "packs").mkdir()
        self.packs = PackManager(self.root / "packs", self.root / "state.json", official_dir=OFFICIAL_DIR)
        self.director = Replay()
        RecordingTrace.records = []
        for module, target, value in ((scenes, "DebugTrace", RecordingTrace), (scenes, "create_backend", lambda _config: self.director),
                                      (vocabulary_packs, "Arrangements", Recorded)):
            patcher = mock.patch.object(module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_scenes(self, value=None, director=None, visual=None):
        self.director = director or Replay()
        return scenes.write_scenes({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"),
                                   value or recorded_brief(), progress=lambda _message: None, packs=self.packs,
                                   vocabulary=self.packs.resolve_selection(["visual"]),
                                   visual=FIXTURE["visual_direction"] if visual is None else visual)

    def concept_users(self):
        return [json.loads(call.user_message) for call in self.director.calls if call.diagnostic_stage == "dataset_v2:concepts"]

    def concept_systems(self):
        return [call.system_message for call in self.director.calls if call.diagnostic_stage == "dataset_v2:concepts"]


class TheConflictIsGenuine(RecoveryHarness):
    def test_the_recorded_rejection_is_reproduced_and_explained(self):
        reference = vocabulary_packs.vocabulary_reference({"backend": "mock"}, scenes.validate_brief(recorded_brief()),
                                                          manager=self.packs, selection=self.packs.resolve_selection(["visual"]))
        plan = reference["arrangements"]
        record, errors = plan.check(1, FIXTURE["concepts"][0]["arrangement"])
        self.assertIsNone(record)
        self.assertTrue(errors[0].startswith(FIXTURE["recorded_rejection"].removeprefix("concept 1: ")), errors)
        self.assertIn("From behind as front (on all fours): 2 hand for support", errors[0])
        self.assertIn("Hold an object as holder: 1 hand for hold", errors[0])
        self.assertIn("Give one of these roles to someone else, or drop one option", errors[0])

    def test_the_claims_are_counted_once_each(self):
        registry = self.packs.registry_for(self.packs.resolve_selection(["visual"]))
        cast = [{"id": MASTER, "body": "core:body.human"}, {"id": SLAVE, "body": "core:body.human"}]
        hold = {"entry": "core:action.hold", "bind": {"holder": MASTER, "item": "item"}}
        objects = [{"id": "item", "item": None}]
        recorded = resolve(registry, {"cast": cast, "objects": objects, "use": [
            {"entry": "core:position.from_behind", "bind": {"front": MASTER, "back": SLAVE}}, hold]})
        self.assertEqual(recorded.status, "conflict")
        claims = [use for uses in recorded.allocation[MASTER].values() for use in uses]
        self.assertEqual(sorted(entry for use in claims for entry in use["entries"]).count("core:posture.all_fours"), 4,
                         "all fours: two hands and two legs, once each")
        self.assertNotIn("core:action.hold", {entry for use in claims for entry in use["entries"]},
                         "the hold found no free hand: a genuine third hand, not a duplicate")
        prose = resolve(registry, {"cast": cast, "objects": objects, "use": [
            {"entry": "core:position.from_behind", "bind": {"front": SLAVE, "back": MASTER}}, hold]})
        self.assertNotEqual(prose.status, "conflict", "the roles the concept's own prose describes are compatible")


class OneBadImageNeverBlocksTheOthers(RecoveryHarness):
    def test_the_recorded_answer_now_writes_every_image(self):
        result = self.run_scenes()
        self.assertEqual((result["written"], result["complete"]), (10, True))
        kinds = {slot["slot"]: slot["concept"]["arrangement"]["kind"] for slot in result["slots"]}
        self.assertEqual({number for number, kind in kinds.items() if kind == "freeform"}, set(FAILING))
        for number in FAILING:
            arrangement = result["slots"][number - 1]["concept"]["arrangement"]
            self.assertEqual(arrangement["status"], "unchecked", "never described as checked")
            self.assertIn("man has 2 Hand but 3 are claimed", arrangement["rejected"][0]["why"][0])
            self.assertEqual(result["scenes"][number - 1]["arrangement"], {"kind": "freeform", "status": "unchecked"})
        for number in set(range(1, 11)) - set(FAILING):
            self.assertEqual(kinds[number], "vocabulary")
        for slot in result["slots"]:
            self.assertEqual(slot["concept"]["position_name"], FIXTURE["concepts"][slot["slot"] - 1]["position_name"],
                             "every concept stays in its own image")

    def test_only_the_failing_images_are_asked_again_with_their_own_reasons(self):
        self.run_scenes()
        users, systems = self.concept_users(), self.concept_systems()
        self.assertEqual(len(users), 3)
        self.assertEqual(users[1]["images"], list(FAILING))
        self.assertEqual(users[1]["concepts_needed"], 3)
        self.assertEqual(len(users[1]["earlier_concepts"]), 7, "the seven valid concepts were kept")
        for position, number in enumerate(FAILING, 1):
            self.assertIn(f"concept {position} (image {number}): man has 2 Hand but 3 are claimed", systems[1])
            options = users[1]["arrangement_options"][position - 1]
            self.assertEqual(options["rejected_before"][0]["arrangement"], FIXTURE["concepts"][number - 1]["arrangement"])
        self.assertIn("this arrangement was already rejected for this image", systems[2],
                      "a repeated combination is named as a repeat")
        self.assertEqual(users[1]["visual_direction"], [
            {**item, "concept": index} for index, item in enumerate(
                [users[0]["visual_direction"][number - 1] for number in FAILING], 1)], "each image keeps its visual direction")

    def test_corrected_roles_are_accepted_as_checked(self):
        result = self.run_scenes(director=Replay(fixes={number: swap_roles for number in FAILING}))
        self.assertEqual(len(self.concept_users()), 2)
        for number in FAILING:
            arrangement = result["scenes"][number - 1]["arrangement"]
            self.assertEqual(arrangement["kind"], "vocabulary")
            self.assertEqual(arrangement["entries"][0]["roles"], {"back": [MASTER], "front": [SLAVE]})

    def test_visual_direction_is_the_same_whatever_was_retried(self):
        retried = self.run_scenes()["vocabulary"]["visual"]["slots"]
        clean = self.run_scenes(director=Replay(fixes={number: swap_roles for number in FAILING}, fix_from=0))["vocabulary"]["visual"]["slots"]
        self.assertEqual(retried, clean)

    def test_guided_inputs_stay_with_their_images(self):
        inputs = [f"guided idea {number}" for number in range(1, 11)]
        result = self.run_scenes(recorded_brief(source_mode="guided", guided_inputs=inputs))
        self.assertEqual([slot["concept"]["input"] for slot in result["slots"]], inputs)
        self.assertEqual([item["input"] for item in self.concept_users()[1]["assignments"]], [inputs[n - 1] for n in FAILING])

    def test_a_required_option_is_never_dropped_to_freeform(self):
        class Required(Recorded):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.asked = {"core:position.from_behind"}
        with mock.patch.object(vocabulary_packs, "Arrangements", Required):
            result = self.run_scenes()
        self.assertEqual(sorted(item["slot"] for item in result["missing"]), list(FAILING),
                         "the request's own choice cannot be skipped; those images fail with their reasons")
        self.assertIn("man has 2 Hand but 3 are claimed", result["missing"][0]["reasons"][0] + " ".join(result["missing"][0]["reasons"]))
        self.assertEqual(result["written"], 7)


class DirectorPreferences(RecoveryHarness):
    def test_a_director_only_preference_reaches_some_images_and_is_never_required(self):
        with mock.patch.object(vocabulary_packs, "Arrangements", arrangements.Arrangements):
            reference = vocabulary_packs.vocabulary_reference(
                {"backend": "mock"}, scenes.validate_brief(recorded_brief()), manager=self.packs,
                selection=self.packs.resolve_selection(["adult", "visual"]),
                director="For domination requests, show control through posture, restraint, who is holding or guiding whom.")
        plan = reference["arrangements"]
        offered = [number for number in range(1, 11) if "core:action.hold" in {entry.id for entry in plan.options(number)}]
        self.assertTrue(0 < len(offered) < 10, offered)
        self.assertEqual(plan.record()["required"], [])
        self.assertIn("core:action.hold", plan.record()["director_prefers"])
        self.assertEqual(offered, [number for number in range(1, 11)
                                   if "core:action.hold" in {entry.id for entry in plan.options(number)}], "seeded, stable")

    def test_roles_are_described_from_declared_data_instead_of_an_arbitrary_suggestion(self):
        reference = vocabulary_packs.vocabulary_reference({"backend": "mock"}, scenes.validate_brief(recorded_brief()),
                                                          manager=self.packs, selection=self.packs.resolve_selection(["visual"]))
        options = {option["id"]: option for option in reference["arrangements"].offer([1])[0]["options"]}
        behind = options["core:position.from_behind"]
        self.assertNotIn("suggested_roles", behind)
        self.assertNotIn("only_valid_roles", behind, "both men fit either role: nothing is suggested")
        self.assertIn("on all fours (its 2 hand and 2 leg are busy holding the body up)", behind["roles"]["front"])
        self.assertIn("behind the front at hips", behind["roles"]["back"])
        self.assertIn("uses 1 hand to hold", options["core:action.hold"]["roles"]["holder"])


class LapSitRoles(RecoveryHarness):
    def test_structured_roles_stay_authoritative_and_what_is_not_checked_is_said(self):
        result = self.run_scenes()
        arrangement = result["scenes"][1]["arrangement"]
        self.assertEqual(arrangement["entries"][0]["roles"], {"base": [SLAVE], "seated": [MASTER]},
                         "the structured choice, even where the concept's prose put them the other way")
        self.assertIn("anchors, contact and reach in the prose", arrangement["not_checked"])
        staging = [call.system_message for call in self.director.calls if call.diagnostic_stage == "dataset_v2:stagings"][0]
        self.assertIn("the arrangement wins", staging)
        plan = vocabulary_packs.vocabulary_reference({"backend": "mock"}, scenes.validate_brief(recorded_brief()),
                                                     manager=self.packs, selection=self.packs.resolve_selection(["visual"]))["arrangements"]
        notes = plan.role_notes("core:position.lap_sit")
        self.assertIn("on the base at hips", notes["seated"])
        record, _ = plan.check(2, FIXTURE["concepts"][1]["arrangement"])
        both_sitting = {MASTER: {"posture": "core:posture.sitting", "facing": "other"},
                        SLAVE: {"posture": "core:posture.sitting", "facing": "other"}}
        self.assertEqual(plan.check_staging(record, both_sitting), [],
                         "both roles sit: a reversal cannot be told from postures, so it is not claimed as checked")


class RunStatus(unittest.TestCase):
    def test_a_run_without_any_scene_fails_with_its_reasons(self):
        empty = {"complete": False, "requested": 10, "written": 0, "scenes": [], "concepts": [], "slots": [],
                 "vocabulary": {"enabled": True, "provided": []},
                 "missing": [{"slot": number, "stage": "concepts", "tries": 3, "input": "",
                              "reasons": [FIXTURE["recorded_rejection"]]} for number in range(1, 11)]}
        job = Job()
        with mock.patch.object(runner, "write_scenes", return_value=empty), \
                mock.patch.object(runner, "write_prompts") as prompts, \
                mock.patch.object(runner, "create_backend"), mock.patch.object(runner, "resolve_director_config",
                                                                                 return_value=({}, None)):
            with self.assertRaises(RuntimeError) as caught:
                runner.run_dataset_v2_scenes(None, job, GoatedPrompterRequest(idea="x", planning_mode="Direct"),
                                             {"backend": "mock"}, {"brief": recorded_brief()})
        prompts.assert_not_called()
        self.assertIn("No scene could be written (10 requested)", str(caught.exception))
        self.assertIn("images 1, 2, 3", str(caught.exception))
        self.assertEqual(job.result["written"], 0, "the reasons stay visible in the job's result")
        self.assertNotEqual(job.status, "succeeded")

    def test_an_incomplete_run_says_so(self):
        self.assertIsNone(runner.incomplete({"complete": True}))
        message = runner.incomplete({"complete": False, "written": 7, "requested": 10,
                                     "missing": [{"slot": 1}, {"slot": 4}, {"slot": 8}]})
        self.assertEqual(message, "Generation finished incomplete: 7 of 10 scenes written; not written: images 1, 4, 8.")
        job = Job()
        job.deliver({"ok": True}, message)
        self.assertEqual((job.status, job.status_reason), ("succeeded", message))
        plain = Job()
        plain.deliver({"ok": True})
        self.assertEqual(plain.status_reason, "Generation completed successfully.")


if __name__ == "__main__":
    unittest.main()
