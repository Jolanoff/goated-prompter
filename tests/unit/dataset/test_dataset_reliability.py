"""Universal Vocabulary V2 reliability (issue 106 review): Understanding, Director and target requirements, composition
and final-prompt preservation. Scripted models and bundled packs only; nothing here is live-model evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import intent, prompts, scenes, understanding, vocabulary_packs
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.vocabulary import visual
from goated_prompter.features.vocabulary.composer import SceneContract, director_obligations, mentions
from goated_prompter.features.vocabulary.packs import PackManager
from goated_prompter.features.vocabulary.preferences import Preferences
from goated_prompter.prompt_library import copied_reference
from goated_prompter.prompting.directors import DIRECTOR_PRESETS, DIRECTOR_VOCABULARY
from tests.unit.dataset.test_dataset_vocabulary_integration import PEOPLE, brief

# The two answers the model gave for "magical world" (debug trace understanding-20261016-152619-212432.json): both
# were rejected before this fix, the first for its punctuation-only fixed and blank randomized, the second for an
# empty fixed; both also scoped their only part to a guided input that does not exist.
MAGICAL_FIRST = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": ",[],", '
                 '"randomized": " ", "must": [], "avoid": [], "intent": {"elements": [{"id": "env1", "kind": '
                 '"environment", "text": "magical world", "status": "fixed", "source": "request", "input": 1}], '
                 '"relations": []}}')
MAGICAL_SECOND = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": "", '
                  '"randomized": "setting, lighting, camera, mood, style", "must": [], "avoid": [], "intent": {"elements": '
                  '[{"id": "env1", "kind": "environment", "text": "magical world", "status": "randomized", "source": '
                  '"request", "input": 1, "terms": ["fantasy", "magic"]}], "relations": [], "unresolved": [], '
                  '"truncated": false}}')
LOGS = Path(__file__).parent / "fixtures"


class Understanding(unittest.TestCase):
    def understand(self, answers, **data):
        backend = MockBackend()
        replies = iter(answers)
        calls = []

        def generate(instruction):
            calls.append(instruction)
            return next(replies)
        values = {**default_dataset_draft(), "subject": "magical world", "amount": 3, "seed": 5, "seed_mode": "fixed", **data}
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(understanding, "create_backend", return_value=backend), \
                patch.object(understanding, "DebugTrace", return_value=Mock()), \
                patch.object(understanding, "resolve_director_config", return_value=({}, None)):
            result = understanding.understand({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), values,
                                              progress=lambda _: None)
        return result, calls

    def test_broad_request_with_malformed_optional_text_is_understood_in_one_call(self):
        result, calls = self.understand([MAGICAL_FIRST])
        self.assertEqual(len(calls), 1, "a recoverable answer is not regenerated")
        self.assertEqual((result["path"], result["fixed"], result["randomized"]), ("non_character", "", ""))
        self.assertEqual(result["summary"], "A magical world.")
        self.assertTrue(result["intent"]["available"], result["intent"])
        element = result["intent"]["elements"][0]
        self.assertEqual(element["text"], "magical world")
        self.assertEqual(element["input"], 0, "for every image: the stray guided-input scope is dropped")
        self.assertEqual(understanding.validate_brief(result), result)

    def test_the_retry_answer_from_the_regression_trace_is_also_valid(self):
        result, calls = self.understand([MAGICAL_SECOND])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["fixed"], "")
        self.assertEqual(result["randomized"], "setting, lighting, camera, mood, style")
        self.assertTrue(result["intent"]["available"])

    def test_missing_summary_falls_back_to_the_request_never_to_an_invention(self):
        answer = json.loads(MAGICAL_SECOND)
        answer["summary"] = "  "
        result, _ = self.understand([json.dumps(answer)])
        self.assertEqual(result["summary"], "magical world")

    def test_nsfw_switch_keeps_a_place_request_without_people(self):
        result, calls = self.understand([MAGICAL_FIRST], nsfw=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["path"], result["people"], result["input"]["nsfw"]), ("non_character", 0, True))
        self.assertIn("without people", calls[0].system_message)

    def test_nsfw_sexual_request_without_people_is_still_sent_back(self):
        errors = understanding.model_errors(understanding.recover(json.loads(MAGICAL_FIRST)), True,
                                            {"subject": "two people having sex", "source_mode": "random"})
        self.assertTrue(any("path must be" in error for error in errors), errors)

    def test_unrecoverable_answers_still_fail_after_one_retry(self):
        broken = json.dumps({**json.loads(MAGICAL_FIRST), "path": "landscape"})
        with self.assertRaisesRegex(ValueError, "invalid answer twice"):
            self.understand([broken, broken])

    def test_stray_input_on_a_brief_with_guided_inputs_is_still_a_scope_error(self):
        value = {"elements": [{"id": "a", "kind": "action", "text": "reads", "status": "fixed", "source": "request",
                               "input": 3}], "relations": []}
        kept, _ = intent.sanitize(value, {}, 2)
        self.assertTrue(intent.check(kept, {}, 2))


class Composition(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.packs = PackManager(Path(folder.name) / "packs", Path(folder.name) / "state.json")

    def reference(self, value, selected, **kwargs):
        selection = self.packs.resolve_selection(selected, enabled=True)
        kwargs.setdefault("visual", visual.default_settings())
        return vocabulary_packs.vocabulary_reference({}, value, manager=self.packs, selection=selection, **kwargs)

    def records(self, reference, amount):
        return [reference["composer"].compose(number) for number in range(1, amount + 1)]

    def test_magical_world_with_general_only_is_an_honest_freeform_run(self):
        records = self.records(self.reference(brief("magical world", characters=[], amount=3), ["general"]), 3)
        for record in records:
            self.assertEqual((record["kind"], record["status"]), ("freeform", "unchecked"))
            self.assertIn("no vocabulary place", record["reason"])

    def test_magical_world_with_fantasy_composes_fantasy_places(self):
        records = self.records(self.reference(brief("magical world", characters=[], amount=4), ["general", "fantasy"]), 4)
        for record in records:
            self.assertEqual(record["kind"], "vocabulary", record)
            self.assertEqual(record["space"]["id"].split(":")[0], "fantasy")
            self.assertFalse(record["verified"], "nothing was checked, so nothing is verified")
            self.assertFalse([finding for finding in record["findings"] if finding["code"] == "visual_visibility"])

    def test_multi_character_general_scene_places_everyone_without_spurious_unknowns(self):
        cast = [{"label": f"friend {number}", "gender": gender, "custom": "", "pronoun": pronoun}
                for number, (gender, pronoun) in enumerate((("female", "she"), ("male", "he"), ("female", "she")), 1)]
        records = self.records(self.reference(brief("three friends sitting together", characters=cast, amount=3),
                                              ["general"]), 3)
        for record in records:
            self.assertEqual(record["kind"], "vocabulary", record)
            self.assertEqual(record["unplaced"], [], record)
            # A light or a composition says nothing about what is in view: never an "undeclared coverage" unknown.
            self.assertFalse([finding for finding in record["findings"] if finding["code"] == "visual_visibility"
                              and not finding["entries"][0].startswith("general:framing.")], record["findings"])

    def test_adult_composition_with_declared_anatomy_is_feasible_and_verified(self):
        cast = [{"label": label, "gender": "custom", "custom": "adult human with a penis", "pronoun": "he"}
                for label in ("first man", "second man")]
        records = self.records(self.reference(brief("two men having sex", characters=cast, nsfw=True, amount=3),
                                              ["adult"]), 3)
        for record in records:
            self.assertEqual((record["kind"], record["status"]), ("vocabulary", "feasible"), record["findings"])
            self.assertTrue(record["verified"])
            self.assertIn("adult:action.sex", [entry["id"] for entry in record["entries"]])

    def test_regression_log_brief_is_unknown_only_for_undeclared_anatomy(self):
        """The brief of dataset-generation-log (3): every image was unknown, citing anatomy, places and visual coverage.
        Gender is not anatomy, so genitals stay undeclared (unknown, never verified); everything else the entries need
        is now declared by the chosen place, and lights or compositions no longer count as undeclared coverage."""
        value = json.loads((LOGS / "v2_issue106_men_brief.json").read_text(encoding="utf-8"))
        records = self.records(self.reference(value, ["adult"], preferences=DIRECTOR_VOCABULARY["nsfw_director"]), 10)
        for record in records:
            self.assertEqual((record["kind"], record["status"]), ("vocabulary", "unknown"))
            self.assertFalse(record["verified"])
            codes = {(finding["code"], "Genitals" in finding["message"]) for finding in record["findings"]}
            self.assertEqual(codes, {("undeclared_capability", True)}, record["findings"])

    def test_director_object_requirement_in_any_sentence_is_in_every_image(self):
        director = "Keep the mood warm and quiet. Every image must show a phone. Never show a mirror."
        reference = self.reference(brief("two friends hug", characters=PEOPLE, amount=4), ["general"], director=director)
        contract = reference["composer"].contract
        self.assertIn(["general:item.phone"], [row["entries"] for row in contract.requirements if row["source"] == "director"])
        self.assertNotIn(["general:item.mirror"], [row["entries"] for row in contract.requirements])
        for record in self.records(reference, 4):
            self.assertEqual(record["kind"], "vocabulary", record)
            self.assertIn("general:item.phone", [item["id"] for item in record["items"]])
            self.assertIn("general:action.hug", [entry["id"] for entry in record["entries"]], "the user's action stays")
            self.assertIn({"kind": "item", "check": True},
                          [{"kind": row["kind"], "check": row["check"]} for row in record["semantics"] if row["kind"] == "item"])

    def test_director_viewpoint_requirement_sets_every_image_camera(self):
        reference = self.reference(brief("two friends hug", characters=PEOPLE, amount=3), ["general"],
                                   preferences=DIRECTOR_VOCABULARY["first_person_pov"])
        for record in self.records(reference, 3):
            self.assertEqual(record["kind"], "vocabulary", record)
            self.assertIn("general:camera_angle.pov", [entry["id"] for entry in record["entries"]])
            self.assertIn("Point of view", record["visual"]["camera"])
            self.assertIn("visual", [row["kind"] for row in record["semantics"] if row["check"]])

    def test_target_requirements_join_the_same_contract(self):
        with patch.object(vocabulary_packs, "target_vocabulary", return_value={"require": ["general:camera_angle.high_angle"]}):
            reference = self.reference(brief("two friends hug", characters=PEOPLE, amount=2), ["general"])
        self.assertIn({"source": "target", "entries": ["general:camera_angle.high_angle"]},
                      [{"source": row["source"], "entries": row["entries"]} for row in reference["composer"].contract.requirements])
        for record in self.records(reference, 2):
            self.assertIn("High angle", record["visual"]["camera"])

    def test_director_prose_obligations_are_clauses_not_any_mention(self):
        self.assertEqual([words for _, words in director_obligations("Always include a candle; never show a whip")],
                         [["candl"]])
        self.assertEqual(director_obligations("Composition and staging must remain intentional."), [])
        self.assertEqual(director_obligations("Avoid redesigning the product or hiding it behind props."), [])
        selection = self.packs.resolve_selection(["general", "fantasy", "adult", "visual"], enabled=True)
        registry = self.packs.registry_for(selection)
        required = {}
        for preset in DIRECTOR_PRESETS:
            contract = SceneContract.build(registry, brief("x", amount=1), Preferences(None, registry), preset.instructions,
                                           allowed=("general", "mature", "adult"))
            if contract.requirements:
                required[preset.id] = [row["entries"] for row in contract.requirements]
        self.assertEqual(required, {"mirror_selfie": [["general:action.mirror_selfie"]]},
                         "built-in Director prose requires only what it explicitly constructs")


class FinalPrompts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.packs = PackManager(Path(folder.name) / "packs", Path(folder.name) / "state.json")
        cast = [{"label": label, "gender": "custom", "custom": "adult human with a penis", "pronoun": "he"}
                for label in ("man 1", "man 2")]
        self.value = brief("two men having sex", characters=cast, nsfw=True, amount=1)
        selection = self.packs.resolve_selection(["adult"], enabled=True)
        record = vocabulary_packs.vocabulary_reference({}, self.value, manager=self.packs, selection=selection,
                                                       visual=visual.default_settings())["composer"].compose(1)
        finish = {"subjects": {label: {key: "detail" for key in scenes.SUBJECT_FIELDS} for label in ("man 1", "man 2")},
                  "open": {"man 1": "eyes closed", "man 2": "looking down"}, "space": "x", "lighting": "x", "mood": "x",
                  "camera": "x", "extras": "pillows"}
        self.scene = scenes._composed_scene(1, record, finish, ["man 1", "man 2"])

    def natural(self):
        """A prompt that rewrites every checked meaning in its own words (the last phrase: an alias where one exists)."""
        return "Two men; " + "; ".join(row["phrases"][-1].lower() for row in prompts.preserved(self.scene) if row["check"])

    def write(self, target, answers):
        self.value["settings"].update(target=target)
        seen = []
        replies = iter(answers)

        class Service:
            def __init__(self, *args, **kwargs):
                pass

            def generate_text_only(self, request, **kwargs):
                seen.append(request)
                return SimpleNamespace(prompt=next(replies))
        with mock.patch.object(prompts, "GoatedPrompterService", Service), mock.patch.object(prompts, "DebugTrace"):
            result = prompts.write_prompts({}, GoatedPrompterRequest(idea="", planning_mode="Direct"), self.value,
                                           [self.scene], progress=lambda _: None)
        return result[0], seen

    def test_rewritten_meaning_passes_for_every_target_without_verbatim_internal_lines(self):
        prompt = self.natural()
        for fact in self.scene["arrangement"]["facts"]:
            self.assertNotIn(fact, prompt)
        for target in ("Krea 2", "Anima", "FLUX.2 Klein", "Z-Image Turbo", "Qwen Image 2.1"):
            with self.subTest(target=target):
                result, seen = self.write(target, [prompt])
                self.assertTrue(result["mechanics_preserved"], result)
                self.assertEqual(result["prompt"], prompt)
                self.assertEqual(seen[0].target_model, target)
                self.assertIn("MEANING TO KEEP", seen[0].custom_instructions)
                self.assertNotIn("verbatim", seen[0].custom_instructions)

    def test_a_dropped_action_is_named_in_the_retry_and_then_reported(self):
        result, seen = self.write("Krea 2", ["Two men in a room.", "Two men in a room, still."])
        self.assertEqual(len(seen), 2)
        self.assertIn("CORRECTION: The prompt lost part of the established scene", seen[1].custom_instructions)
        self.assertIn("action: Sex", seen[1].custom_instructions)
        self.assertEqual(result["prompt"], "")
        self.assertFalse(result["mechanics_preserved"])
        self.assertIn("action: Sex", result["error"])

    def test_retry_that_restores_the_meaning_is_accepted(self):
        result, _ = self.write("Krea 2", ["Two men in a room.", self.natural()])
        self.assertTrue(result["mechanics_preserved"])
        self.assertTrue(result["prompt"])

    def test_mentions_is_word_order_free_and_stemmed(self):
        self.assertTrue(mentions("the back seat of a parked car", ["Car back seat"]))
        self.assertTrue(mentions("he is kneeling on the rug", ["Kneeling"]))
        self.assertFalse(mentions("a car parked outside", ["Car back seat"]))


class LibraryReferences(unittest.TestCase):
    TEMPLATE = "Soft window light falls across the quiet room while dust drifts slowly through the warm afternoon air."

    def test_copy_check_names_the_copied_passage(self):
        copied = copied_reference("A man reads. Soft window light falls across the quiet room while dust drifts slowly.",
                                  [self.TEMPLATE])
        self.assertEqual(copied, "soft window light falls across the quiet room while dust")

    def test_wording_the_request_itself_contains_is_not_a_copy(self):
        idea = "the quiet room while dust drifts slowly through the warm afternoon air"
        prompt = "A man reads in " + idea + "."
        self.assertTrue(copied_reference(prompt, [self.TEMPLATE]))
        self.assertEqual(copied_reference(prompt, [self.TEMPLATE], allowed=[idea]), "")

    def test_retry_after_copying_is_written_without_the_templates(self):
        from goated_prompter.features.builder import service as builder
        backend = MockBackend()
        instructions = []

        def generate(instruction):
            instructions.append(instruction)
            return self.TEMPLATE if len(instructions) == 1 else "A reader sits by a bright window with a book."
        request = GoatedPrompterRequest(idea="a reader by a window", planning_mode="Direct", target_model="Krea 2")
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(builder, "create_backend", return_value=backend), \
                patch.object(builder, "pick_references", return_value=(self.TEMPLATE,)):
            result = builder.GoatedPrompterService({"backend": "mock"}).generate_text_only(request)
        self.assertEqual(result.prompt, "A reader sits by a bright window with a book.")
        self.assertEqual(len(instructions), 2)
        self.assertIn("TEMPLATES FROM THE USER'S PROMPT LIBRARY", instructions[0].system_message)
        self.assertNotIn(self.TEMPLATE, instructions[1].system_message)
        self.assertIn("copied wording", instructions[1].system_message)


if __name__ == "__main__":
    unittest.main()
