"""Vocabulary-backed arrangements in Dataset V2 (v2/arrangements.py): chosen per image, checked with the resolver,
kept through staging, description and the Builder.

The bundled core, the read-only official packs and synthetic packs in temporary folders are read. A scripted
Director answers every request. No model, GPU or private data is used."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import prompts, scenes, vocabulary_packs
from goated_prompter.features.vocabulary.packs import OFFICIAL_DIR, PackManager
from goated_prompter.features.vocabulary.visual import default_settings
from tests.unit.dataset.test_dataset_vocabulary_integration import PEOPLE, RecordingTrace, ScriptedDirector, brief

SQUAT = "adult:position.squatting_ride"
KNEEL = "adult:position.kneeling_ride"
WOMAN_RIDES = [{"option": SQUAT, "roles": [{"role": "partner", "who": ["man"]}, {"role": "rider", "who": ["woman"]}]}]
TRIO = PEOPLE + [{"label": "friend", "gender": "female", "custom": "woman", "pronoun": "she"}]


def being():
    return {"count": 1, "kind": "being"}


def two_handed(entry_id, name, aliases=()):
    """A synthetic action that takes both of the holder's hands (an exclusive claim)."""
    return {"id": entry_id, "category": "action", "name": name, "aliases": list(aliases),
            "description": f"{name} with both hands.", "components": {
                "participants": {"slots": {"holder": being(), "other": being()}},
                "requirements": {"participants": {"holder": {"all_of": ["core:limb.hand"]}}},
                "claims": {"holder": [{"resource": "core:limb.hand", "count": 2, "mode": "exclusive", "purpose": "hold"}]}}}


class Scripted(ScriptedDirector):
    """The scripted Director, with answers changed per call: concepts[n] / stagings[n] patch the n-th such call."""

    def __init__(self, concepts=None, stagings=None):
        super().__init__()
        self.concept_patches, self.staging_patches = concepts or {}, stagings or {}
        self.count = {"concepts": 0, "stagings": 0}

    def arrangement(self, options):
        """As the base Director, but a squatting ride gives the rider role to the woman, as these briefs say."""
        chosen = super().arrangement(options)
        return copy.deepcopy(WOMAN_RIDES) if chosen and chosen[0]["option"] == SQUAT else chosen

    def generate(self, instruction):
        answer = json.loads(super().generate(instruction))
        stage = instruction.diagnostic_stage.split(":")[1]
        if stage in self.count:
            call = self.count[stage]
            self.count[stage] += 1
            patch = (self.concept_patches if stage == "concepts" else self.staging_patches).get(call)
            if patch:
                patch(answer[stage], json.loads(instruction.user_message))
        return json.dumps(answer)


class ArrangementHarness(unittest.TestCase):
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

    def install(self, pack_id, entries, *, rating="general"):
        folder = self.root / "packs" / pack_id
        folder.mkdir()
        (folder / "manifest.json").write_text(json.dumps({
            "spec": 1, "id": pack_id, "name": pack_id.title(), "version": "1.0.0", "rating": rating,
            "requires": {"core": ">=1.0.0"}, "files": ["entries.json"]}), encoding="utf-8")
        (folder / "entries.json").write_text(json.dumps({"spec": 1, "entries": entries}), encoding="utf-8")

    def reference(self, value, selected=("adult",), director=""):
        return vocabulary_packs.vocabulary_reference({"backend": "mock"}, scenes.validate_brief(copy.deepcopy(value)),
                                                     director=director, manager=self.packs,
                                                     selection=self.packs.resolve_selection(list(selected)))

    def run_scenes(self, value, *, selected=("adult",), director=None, visual=None):
        self.director = director or Scripted()
        return scenes.write_scenes({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), copy.deepcopy(value),
                                   progress=lambda _message: None, packs=self.packs,
                                   vocabulary=self.packs.resolve_selection(list(selected)), visual=visual)

    def users(self, stage):
        return [json.loads(call.user_message) for call in self.director.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]

    def calls(self, stage):
        return [call for call in self.director.calls if call.diagnostic_stage == f"dataset_v2:{stage}"]


def squat_brief(amount=2, **kwargs):
    return brief("a woman doing a squatting ride on a man on a bed", characters=PEOPLE, nsfw=True, amount=amount, **kwargs)


class TheResolverDecides(ArrangementHarness):
    def test_a_named_position_is_a_required_option_with_checked_facts(self):
        plan = self.reference(squat_brief())["arrangements"]
        self.assertIsNotNone(plan)
        option = next(item for item in plan.offer([1])[0]["options"] if item["id"] == SQUAT)
        self.assertTrue(option["named_by_request"])
        self.assertEqual(set(option["roles"]), {"rider", "partner"})
        record, errors = plan.check(1, WOMAN_RIDES)
        self.assertEqual(errors, [])
        self.assertEqual(record["kind"], "vocabulary")
        self.assertIn(record["status"], ("unknown", "eligible", "feasible"), "never a conflict once accepted")
        self.assertNotEqual(record["status"], "feasible", "the place is free text: the space stays unknown, never proven")
        self.assertIn("man: lying on the back", record["facts"])
        self.assertTrue(any(fact.startswith("woman: squatting, facing toward man") for fact in record["facts"]))
        self.assertIn("the place (free text): space requirements stay unknown", record["not_checked"])
        self.assertEqual(plan.check(1, [])[1], ["the request names Squatting ride: use one of them as the arrangement, "
                                                "with every role assigned"])

    def test_the_partner_posture_and_a_reversal_are_conflicts_at_staging(self):
        plan = self.reference(squat_brief())["arrangements"]
        record, _ = plan.check(1, WOMAN_RIDES)
        right = {"woman": {"posture": "adult:posture.squatting", "facing": "toward man"},
                 "man": {"posture": "core:posture.lying_back", "facing": "other"}}
        self.assertEqual(plan.check_staging(record, right), [])
        kneeling = {**right, "man": {"posture": "core:posture.kneeling", "facing": "other"}}
        self.assertTrue(any("man is given different postures" in error and "Squatting ride" in error
                            for error in plan.check_staging(record, kneeling)))
        reversed_ = {"woman": {"posture": "core:posture.lying_back", "facing": "toward man"},
                     "man": {"posture": "adult:posture.squatting", "facing": "toward woman"}}
        errors = plan.check_staging(record, reversed_)
        self.assertTrue(any(error.startswith("woman is given different postures") for error in errors))
        self.assertTrue(any(error.startswith("man is given different postures") for error in errors))
        away = {**right, "woman": {"posture": "adult:posture.squatting", "facing": "away from man"}}
        self.assertTrue(any("different facings" in error for error in plan.check_staging(record, away)))
        unstated = {**right, "man": {"posture": "other", "facing": "other"}}
        self.assertEqual(plan.check_staging(record, unstated), ["man's posture is fixed by the arrangement: lying on the back"])

    def test_role_assignments_must_fit_the_entry(self):
        plan = self.reference(squat_brief())["arrangements"]
        twice = [{"option": SQUAT, "roles": [{"role": "rider", "who": ["woman"]}, {"role": "partner", "who": ["woman"]}]}]
        self.assertTrue(any("bound" in error or "two slots" in error for error in plan.check(1, twice)[1]))
        missing = [{"option": SQUAT, "roles": [{"role": "rider", "who": ["woman"]}]}]
        self.assertEqual(plan.check(1, missing)[1], ["Squatting ride needs exactly the roles partner, rider, each once"])
        stranger = [{"option": SQUAT, "roles": [{"role": "rider", "who": ["ghost"]}, {"role": "partner", "who": ["man"]}]}]
        self.assertIn("rider takes 1-1 of woman, man", plan.check(1, stranger)[1][0])

    def test_a_position_and_an_action_that_disagree_are_rejected(self):
        value = brief("a woman doing a squatting ride and a kneeling ride on a man", characters=PEOPLE, nsfw=True)
        plan = self.reference(value)["arrangements"]
        both = [*WOMAN_RIDES, {"option": KNEEL, "roles": [{"role": "rider", "who": ["woman"]}, {"role": "seated", "who": ["man"]}]}]
        record, errors = plan.check(1, both)
        self.assertIsNone(record)
        self.assertTrue(any("woman is given different postures" in error for error in errors))

    def test_declared_resource_use_is_checked(self):
        self.install("grips", [two_handed("grips:action.lift", "Overhead lift", ["lifting overhead"]),
                               two_handed("grips:action.carry_sign", "Carrying a sign", ["carrying a sign"])])
        value = brief("a woman lifting overhead while carrying a sign next to a man", characters=PEOPLE)
        plan = self.reference(value, selected=("grips",))["arrangements"]
        both = [{"option": "grips:action.lift", "roles": [{"role": "holder", "who": ["woman"]}, {"role": "other", "who": ["man"]}]},
                {"option": "grips:action.carry_sign", "roles": [{"role": "holder", "who": ["woman"]}, {"role": "other", "who": ["man"]}]}]
        record, errors = plan.check(1, both)
        self.assertIsNone(record)
        self.assertTrue(any("hand" in error.casefold() and "claimed" in error for error in errors), errors)
        record, errors = plan.check(1, both[:1])
        self.assertEqual(errors, [])
        self.assertIn("woman's hand left: hold", record["facts"])

    def test_unsupported_or_unselected_content_is_not_an_option(self):
        plan = self.reference(squat_brief())["arrangements"]
        record, errors = plan.check(1, [{"option": "adult:position.not_real", "roles": []}])
        self.assertIsNone(record)
        self.assertIn("is not an arrangement option for this image", errors[0])
        sfw = brief("two friends hugging on a sofa", characters=PEOPLE)
        plan = self.reference(sfw, selected=())["arrangements"]
        self.assertNotIn(SQUAT, {option["id"] for item in plan.offer([1, 2]) for option in item["options"]},
                         "an unselected or disallowed pack never offers an option")
        self.assertIn(SQUAT, plan.check(1, WOMAN_RIDES)[1][0])


class TheDirectorChooses(ArrangementHarness):
    def setUp(self):
        super().setUp()
        self.install("grips", [two_handed("grips:action.lift", "Overhead lift", ["lifting overhead"]),
                               two_handed("grips:action.carry_sign", "Carrying a sign", ["carrying a sign"])])

    def test_director_preferences_shape_the_options_before_binding_but_never_require(self):
        value = brief("a woman and a man at a street festival", characters=PEOPLE, amount=6)
        images = list(range(1, 7))
        without = self.reference(value, selected=("grips",))["arrangements"]
        self.assertNotIn("grips:action.lift", {option["id"] for item in without.offer(images) for option in item["options"]})
        plan = self.reference(value, selected=("grips",), director="Favor scenes of lifting overhead.")["arrangements"]
        offered = [item for item in plan.offer(images) if any(option["id"] == "grips:action.lift" for option in item["options"])]
        self.assertTrue(0 < len(offered) < 6, "a Director-only preference reaches some images, not every image")
        option = next(option for option in offered[0]["options"] if option["id"] == "grips:action.lift")
        self.assertEqual((option["director_prefers"], option["named_by_request"]), (True, False))
        self.assertEqual(plan.check(1, [])[1], [], "a Director preference never makes an option required")
        unselected = self.reference(value, selected=(), director="Favor scenes of lifting overhead.")["arrangements"]
        self.assertFalse([option for item in unselected.offer(images) for option in item["options"] if option["id"].startswith("grips:")],
                         "a Director never enables an unselected pack")

    def test_the_users_named_requirement_wins_over_the_directors_preference(self):
        value = brief("a woman carrying a sign next to a man", characters=PEOPLE)
        plan = self.reference(value, selected=("grips",), director="Favor scenes of lifting overhead.")["arrangements"]
        options = {option["id"]: option for option in plan.offer([1])[0]["options"]}
        self.assertTrue(options["grips:action.carry_sign"]["named_by_request"])
        self.assertFalse(options.get("grips:action.lift", {}).get("named_by_request"), "a preference is never a requirement")
        lift = [{"option": "grips:action.lift", "roles": [{"role": "holder", "who": ["woman"]}, {"role": "other", "who": ["man"]}]}]
        errors = plan.check(1, lift)[1]
        self.assertTrue(errors and ("Carrying a sign" in errors[0] or "not an arrangement option" in errors[0]), errors)

    def test_in_a_run_the_director_rule_and_options_reach_the_concept_request(self):
        def prefer_lift(concepts, user):
            for concept in concepts:
                concept["arrangement"] = [{"option": "grips:action.lift",
                                           "roles": [{"role": "holder", "who": ["woman"]}, {"role": "other", "who": ["man"]}]}]
        director = Scripted(concepts={0: prefer_lift})
        result = self.run_scenes(brief("a woman carrying a sign next to a man", characters=PEOPLE, amount=2), selected=("grips",),
                                 director=director)
        self.assertIn("director_prefers marks options", self.calls("concepts")[0].system_message)
        self.assertEqual(len(self.calls("concepts")), 2, "the Director's choice broke the request's requirement: written again")
        self.assertTrue(result["complete"])
        self.assertTrue(all(slot["concept"]["arrangement"]["entries"][0]["id"] == "grips:action.carry_sign" for slot in result["slots"]))


class InARun(ArrangementHarness):
    def test_only_the_slot_whose_staging_contradicts_is_written_again(self):
        def kneeling_partner(stagings, user):
            stagings[1]["placement"]["man"] = {"posture": "core:posture.kneeling", "facing": "other"}
        director = Scripted(stagings={0: kneeling_partner})
        result = self.run_scenes(squat_brief(amount=2), director=director)
        stagings = self.users("stagings")
        self.assertEqual(len(stagings), 2)
        self.assertEqual(len(stagings[1]["concepts"]), 1, "only image 2 is staged again")
        self.assertIn("man is given different postures", self.calls("stagings")[1].system_message)
        self.assertTrue(result["complete"])
        for scene in result["scenes"]:
            self.assertEqual(scene["arrangement"]["kind"], "vocabulary")
            self.assertEqual(scene["arrangement"]["placement"]["man"]["posture"], "core:posture.lying_back")
            self.assertEqual(scene["arrangement"]["entries"][0]["roles"], {"partner": ["man"], "rider": ["woman"]})

    def test_staging_and_description_read_the_fixed_roles_and_facts_not_raw_bindings(self):
        self.run_scenes(squat_brief(amount=1))
        concept = self.users("stagings")[0]["concepts"][0]["arrangement"]
        self.assertEqual(concept["entries"], [{"name": "Squatting ride", "roles": {"partner": ["man"], "rider": ["woman"]}}])
        self.assertEqual(concept["placement"]["woman"], {"posture": "adult:posture.squatting", "facing": "toward man"})
        self.assertNotIn("placements", json.dumps(concept))
        self.assertIn("fixed and checked", self.calls("stagings")[0].system_message)
        self.assertIn("An arrangement's roles, postures and facing are fixed", self.calls("scenes")[0].system_message)
        self.assertEqual(self.users("scenes")[0]["scenes"][0]["concept"]["arrangement"]["entries"][0]["name"], "Squatting ride")

    def test_a_rejected_concept_never_shifts_a_later_image(self):
        def wrong_first(concepts, user):
            concepts[0]["arrangement"] = [{"option": "adult:position.not_real", "roles": []}]
        director = Scripted(concepts={0: wrong_first})
        result = self.run_scenes(squat_brief(amount=3), director=director)
        first, second = self.users("concepts")[:2]
        self.assertEqual(second["images"], [1], "only image 1 is asked again; images 2 and 3 kept their own concepts")
        self.assertEqual(len(second["earlier_concepts"]), 2)
        self.assertEqual({**first["arrangement_options"][0], "rejected_before": second["arrangement_options"][0]["rejected_before"]},
                         second["arrangement_options"][0], "image 1 keeps its own options")
        self.assertEqual([slot["slot"] for slot in result["slots"]], [1, 2, 3])
        self.assertTrue(result["complete"])

    def test_visual_direction_coexists_with_checked_staging(self):
        def kneeling_partner(stagings, user):
            stagings[0]["placement"]["man"] = {"posture": "core:posture.kneeling", "facing": "other"}
        plain = self.run_scenes(squat_brief(amount=3), selected=("adult", "visual"), visual=default_settings())
        retried = self.run_scenes(squat_brief(amount=3), selected=("adult", "visual"), visual=default_settings(),
                                  director=Scripted(stagings={0: kneeling_partner}))
        self.assertEqual(plain["vocabulary"]["visual"]["slots"], retried["vocabulary"]["visual"]["slots"],
                         "a staging retry changes no visual direction")
        concept = self.users("concepts")[0]
        self.assertTrue(concept["visual_direction"] and concept["arrangement_options"])
        system = self.calls("stagings")[0].system_message
        self.assertIn("is where the image is seen from", system)
        self.assertIn("keeping the named position", system)
        self.assertTrue(retried["complete"])
        self.assertEqual(retried["scenes"][0]["arrangement"]["placement"]["man"]["posture"], "core:posture.lying_back")

    def test_sfw_and_multi_character_runs(self):
        result = self.run_scenes(brief("two friends hugging on a sofa", characters=PEOPLE, amount=2), selected=())
        self.assertEqual({scene["arrangement"]["entries"][0]["id"] for scene in result["scenes"]}, {"core:action.hug"})
        self.assertIn("This dataset is not sexual", self.calls("concepts")[0].system_message)
        trio = brief("two women and a man, a woman doing a squatting ride on a man", characters=TRIO, nsfw=True, amount=2)
        result = self.run_scenes(trio)
        self.assertTrue(result["complete"])
        placement = result["scenes"][0]["arrangement"]["placement"]
        self.assertEqual(set(placement), {"woman", "man", "friend"}, "every person has a placement")
        self.assertEqual(placement["friend"], {"posture": "other", "facing": "other"}, "an unbound person is not fixed")

    def test_guided_inputs_may_stay_freeform_and_are_never_called_checked(self):
        value = squat_brief(amount=2)
        value["input"].update(source_mode="guided", guided_inputs=["dancing together", "sharing a meal"])
        result = self.run_scenes(value)
        self.assertTrue(result["complete"])
        self.assertTrue(all(scene["arrangement"] == {"kind": "freeform", "status": "unchecked"} for scene in result["scenes"]))
        self.assertTrue(all(not option["named_by_request"] for item in self.users("concepts")[0]["arrangement_options"]
                            for option in item["options"]), "guided inputs fix each image's action, not the request")

    def test_no_applicable_interaction_keeps_the_previous_requests(self):
        value = brief("a perfume bottle on marble", characters=[])
        result = self.run_scenes(value, selected=())
        self.assertIsNone(result["vocabulary"]["arrangements"]["enabled"] or None)
        for stage, rule in (("concepts", scenes.ARRANGEMENT_CONCEPT_RULE), ("stagings", scenes.ARRANGEMENT_STAGING_RULE),
                            ("scenes", scenes.ARRANGEMENT_DESCRIPTION_RULE)):
            self.assertNotIn(rule, self.calls(stage)[0].system_message)
            self.assertNotIn('"arrangement', json.dumps(self.users(stage)[0]))
            self.assertNotIn("placement", json.dumps(self.calls(stage)[0].json_schema))
        self.assertFalse([scene for scene in result["scenes"] if "arrangement" in scene])


class TheBuilderKeepsTheFacts(ArrangementHarness):
    def builder_inputs(self, scenes_):
        seen = []

        class Service:
            def __init__(self, *_args, **_kwargs):
                pass

            def generate_text_only(self, request, seed=None, recovery=None):
                seen.append(request)
                return SimpleNamespace(prompt="a prompt")

        value = scenes.validate_brief(squat_brief())
        with mock.patch.object(prompts, "GoatedPrompterService", Service), mock.patch.object(prompts, "DebugTrace"):
            prompts.write_prompts({"backend": "mock"}, GoatedPrompterRequest(idea="", planning_mode="Direct",
                                                                              director_preset="general_director"), value, scenes_,
                                  progress=lambda _message: None)
        return seen

    def test_established_facts_reach_the_builder_and_freeform_scenes_claim_nothing(self):
        result = self.run_scenes(squat_brief(amount=1))
        seen = self.builder_inputs(result["scenes"])
        self.assertIn("arrangement: Squatting ride (partner: man; rider: woman)", seen[0].idea)
        self.assertIn("arrangement fact: man: lying on the back", seen[0].idea)
        self.assertIn("ESTABLISHED SCENE FACTS", seen[0].custom_instructions)
        self.assertEqual(seen[0].director_preset, "general_director", "the Director still writes the prompt")
        freeform = [{**result["scenes"][0], "arrangement": {"kind": "freeform", "status": "unchecked"}}]
        plain = self.builder_inputs(freeform)[0]
        self.assertNotIn("arrangement", plain.idea)
        self.assertNotIn("ESTABLISHED SCENE FACTS", plain.custom_instructions)
        legacy = {key: value for key, value in result["scenes"][0].items() if key != "arrangement"}
        self.assertEqual(self.builder_inputs([legacy])[0].idea, plain.idea, "scenes from before arrangements read the same")


if __name__ == "__main__":
    unittest.main()
