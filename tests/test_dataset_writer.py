"""Scene -> final writer ownership regressions, not mocked semantic guarantees."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock

from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft, validate_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_quality import quality_signature
from goated_prompter.presets import get_director_preset
from goated_prompter.prompting.creativity import CREATIVITY_ADAPTERS
from goated_prompter.prompting.dataset import dataset_instruction, deep_review_instruction, PLANNED_SCENE_CONTRACT
from goated_prompter.prompting.details import LENGTH_ADAPTERS, DATASET_OUTPUT_TOKEN_LIMITS, DATASET_DETAIL_DISCIPLINE
from goated_prompter.prompting.scene_planner import idea_planner_instruction, scene_composer_instruction, scene_planner_instruction
from goated_prompter.prompting.target_models import TARGET_MODEL_NAMES, resolve_target_length, get_model_adapter
from goated_prompter.scene_planner import scene_plan_signature
from tests.evaluation.run_dataset_writer_parity import inputs, experiments
from tests.evaluation.review_dataset_writer import score, annotation_template


class DatasetWriterTests(unittest.TestCase):
    def fixture(self, **changes):
        row = experiments(["sampling"], ["hoop"], ["Generic"])[0]
        return inputs({**row, **changes})

    def test_all_creativity_levels_keep_identical_scene_and_replace_global_policy(self):
        user_messages = []
        request, data, plan = self.fixture()
        original = deepcopy((request, data, plan))
        for creativity in CREATIVITY_ADAPTERS:
            with self.subTest(creativity=creativity):
                writer = dataset_instruction(replace(request, creativity="Dice"), {**data, "creativity": creativity}, 1, plan_item=plan)
                user_messages.append(writer.user_message)
                self.assertIn(f"Dataset Creativity — {creativity}", writer.system_message)
                self.assertIn(PLANNED_SCENE_CONTRACT, writer.system_message)
                self.assertEqual(writer.system_message.count("SCENE-LOCKED VISUAL ENRICHMENT"), 1)
                for global_policy in CREATIVITY_ADAPTERS.values():
                    self.assertNotIn(global_policy, writer.system_message)
                self.assertNotIn("Under Strict creativity", writer.system_message)
                self.assertNotIn("Preserve subject:", writer.system_message)
                for text in (data["subject"], plan["input"], plan["idea"], plan["scene"], plan["geometry"]["pose_detail"]):
                    self.assertIn(text, writer.user_message)
        self.assertEqual(len(set(user_messages)), 1)
        self.assertEqual((request, data, plan), original)

    def test_normal_target_length_envelope_is_identical_for_every_target_length(self):
        request, data, plan = self.fixture()
        for target in TARGET_MODEL_NAMES:
            for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
                with self.subTest(target=target, length=length):
                    writer = dataset_instruction(request, {**data, "target": target, "length": length}, 1, plan_item=plan)
                    normal_length = resolve_target_length(target, length)
                    self.assertIn(normal_length, writer.system_message)
                    self.assertEqual(normal_length, resolve_target_length(target, length, dataset=True))
                    self.assertIn(get_model_adapter(target), writer.system_message)
                    self.assertEqual(writer.hard_max_tokens, DATASET_OUTPUT_TOKEN_LIMITS[length])
                    self.assertEqual(writer.max_tokens, DATASET_OUTPUT_TOKEN_LIMITS[length])
                    self.assertIn(plan["scene"], writer.user_message)
        self.assertNotIn("Stop when it is clearly described", DATASET_DETAIL_DISCIPLINE)
        self.assertIn("Do not stop merely", DATASET_DETAIL_DISCIPLINE)
        builder = assemble_instruction(request, text_only=True)
        self.assertNotIn("DATASET DETAIL DISCIPLINE", builder.system_message)
        self.assertIn(CREATIVITY_ADAPTERS[request.creativity], builder.system_message)

    def test_directors_are_retained_as_treatment_not_scene_authority(self):
        request, data, plan = self.fixture()
        for director in ("general_director", "photography_director", "smartphone_realism"):
            writer = dataset_instruction(request, {**data, "director_preset": director}, 1, plan_item=plan)
            self.assertIn(get_director_preset(director).instructions, writer.system_message)
            self.assertIn("Fully use the selected Director", writer.system_message)
            self.assertIn("It controls treatment, not the semantic scene", writer.system_message)
            self.assertIn(plan["scene"], writer.user_message)

    def test_trigger_off_is_identity_only_in_writer_and_audit(self):
        request, data, plan = self.fixture()
        writer = dataset_instruction(request, data, 1, plan_item=plan)
        for text in ("IDENTITY-ONLY PROTECTION", "intrinsic face/eye", "hairstyle/hair color", "body proportions",
                     "species/markings", "product/logo identity", "NOT a ban on scene detail",
                     "temporary clothing/fabric behavior", "shadows/reflections", "background depth"):
            self.assertIn(text, writer.system_message)
        audit = deep_review_instruction(data, [{**plan, "prompt": "A test prompt."}])
        self.assertIn("not useful scene richness", audit.system_message)
        self.assertIn("fabric behavior", audit.system_message)
        self.assertIn("secondary scene inference alone does not", audit.system_message)
        self.assertIn("singular they", writer.system_message)
        self.assertIn("secondary planner/writer inference is not identity evidence", writer.system_message)
        expanded = dataset_instruction(request, {**data, "expand_trigger": True}, 1, plan_item=plan)
        self.assertNotIn("IDENTITY-ONLY PROTECTION", expanded.system_message)
        self.assertIn("TRIGGER EXPANSION ENABLED", expanded.system_message)

    def test_creativity_does_not_affect_planning_instructions_or_plan_reuse(self):
        request, data, plan = self.fixture()
        signature = scene_plan_signature(data, dataset_assignments(data))
        for creativity in CREATIVITY_ADAPTERS:
            changed = {**data, "creativity": creativity}
            self.assertEqual(signature, scene_plan_signature(changed, dataset_assignments(changed)))
            for builder in (idea_planner_instruction, scene_planner_instruction):
                self.assertEqual(builder(data, dataset_assignments(data)), builder(changed, dataset_assignments(changed)))
            self.assertEqual(scene_composer_instruction(data, dataset_assignments(data), [plan]),
                             scene_composer_instruction(changed, dataset_assignments(changed), [plan]))
        self.assertNotEqual(quality_signature(data, [], [plan]), quality_signature({**data, "creativity": "Dice"}, [], [plan]))

    def test_legacy_settings_default_balanced_and_invalid_creativity_rejected(self):
        old = default_dataset_draft()
        del old["creativity"]
        self.assertEqual(validate_dataset_draft(old)["creativity"], "Balanced")
        for value in ("Experimental", "", None, True, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "descriptive creativity"):
                validate_dataset_draft({**old, "creativity": value})

    def test_final_sampling_override_never_spills_into_format_recovery(self):
        request, data, plan = self.fixture()
        instruction = replace(dataset_instruction(request, data, 1, plan_item=plan), temperature=.45, top_p=.9)
        session = Mock()
        session.generate.side_effect = ['{"prompt":', "A full-body photograph of ohwx_person suspended sideways in an aerial hoop."]
        DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, plan)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual((calls[0].temperature, calls[0].top_p), (.45, .9))
        self.assertEqual((calls[1].temperature, calls[1].top_p), (.25, .85))
        self.assertEqual(calls[0].user_message, calls[1].user_message)
        self.assertEqual(calls[0].hard_max_tokens, calls[1].hard_max_tokens)
        self.assertIn(PLANNED_SCENE_CONTRACT, calls[1].system_message)
        self.assertIn(LENGTH_ADAPTERS["Maximum Detail"], calls[1].system_message)

    def test_semantic_length_gate_rejects_long_paraphrases_and_unreviewed_outputs(self):
        records = [{"id": length, "length": length, "case": "fixed", "target": "Generic", "creativity": "Balanced",
                    "director": "general_director", "condition": "dataset", "trial": 1, "anchors": ["same pose"],
                    "target_valid": True, "word_count": words}
                   for length, words in (("Medium", 100), ("Maximum Detail", 500))]
        labels = annotation_template(records)
        self.assertFalse(score(records, labels)["passed"])
        for label in labels:
            label.update(anchors={"same pose": True}, pose_fidelity=True, constraint_fidelity=True, identity_drift=False, filler_or_repetition=False)
            label["useful_details"]["materials"] = ["cotton sleeve creases"]
        self.assertFalse(score(records, labels)["passed"])  # More words, same visual facts.
        labels[1]["useful_details"]["lighting"] = ["window sidelight"]
        labels[1]["useful_details"]["depth"] = ["foreground separation"]
        self.assertTrue(score(records, labels)["passed"])
        labels[1]["anchors"]["same pose"] = False
        self.assertFalse(score(records, labels)["passed"])  # Richness cannot buy pose drift.


if __name__ == "__main__":
    unittest.main()
