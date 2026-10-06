"""Writer ownership and comparison integrity, not model-quality guarantees."""

from copy import deepcopy
from dataclasses import replace
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.scene_planner import scene_plan_signature
from tests.test_dataset import CaptureBackend
from tests.evaluation.review_dataset_writer import annotation_template, score


def fixture():
    data = {**default_dataset_draft(), "subject": "Two machines positioning one panel together.",
            "trigger": "panel_token", "trigger_type": "Custom", "custom_type": "industrial machines",
            "amount": 1, "target": "Anima", "length": "Maximum Detail", "creativity": "Balanced",
            "visual_style": "Anime / manga", "source_mode": "guided", "inputs": "Both hold the same panel.",
            "constraints": "The panel remains red. No people.", "planning_mode": "Quality"}
    plan = {"index": 1, "input": data["inputs"], "idea": "Two machines positioning one shared panel.",
            "scene": "Two industrial machines grip opposite edges of the same red panel in a cargo bay. "
                     "The left machine raises its edge while the right machine stabilizes the other edge. "
                     "An eye-level frontal view includes both grips and the entire panel.",
            "geometry": {}}
    request = GoatedPrompterRequest(idea=data["subject"], target_model=data["target"],
        prompt_length=data["length"], creativity=data["creativity"], director_preset=data["director_preset"],
        planning_mode="Direct")
    return request, data, plan


def reviewed_sample():
    record = {"id": "arbitrary-scene", "condition": "dataset", "trial": 1, "case": "arbitrary-scene",
              "target": "Anima", "length": "Maximum Detail", "creativity": "Balanced",
              "director": "general_director", "anchors": ["two machines share one panel"],
              "target_valid": True, "word_count": 80}
    label = annotation_template([record])[0]
    label.update(anchors={"two machines share one panel": True}, pose_fidelity=True,
                 constraint_fidelity=True, identity_drift=False, filler_or_repetition=False,
                 reviewer="fixture reviewer", review_kind="human")
    label["useful_details"]["materials"] = ["reflected light along panel edge"]
    label["writing_review"] = {"descriptive_usefulness": True, "coherence": True, "target_suitability": True}
    return record, label


class DatasetWriterUsabilityTests(unittest.TestCase):
    def test_writer_directs_concrete_rendering_without_replanning_or_builder_defaults(self):
        request, data, plan = fixture()
        instruction = dataset_instruction(request, data, 1, plan_item=plan)
        self.assertIn("polished, directly usable prompt", instruction.system_message)
        self.assertIn("material response to actual surfaces", instruction.system_message)
        self.assertIn("lighting to visible effects", instruction.system_message)
        self.assertIn("entities, attributes, action/state, relationships and composition", instruction.system_message)
        self.assertNotIn("FRAME COMPLETENESS DEFAULT", instruction.system_message)
        self.assertIn(plan["scene"], instruction.user_message)
        self.assertIn(plan["idea"], instruction.user_message)
        self.assertIn(data["trigger"], instruction.user_message)
        self.assertEqual((instruction.max_tokens, instruction.hard_max_tokens, instruction.unlimited_tokens),
                         (3072, 3072, False))
        self.assertEqual((instruction.temperature, instruction.top_p), (.25, .85))

    def test_writer_keeps_detail_in_description_and_identity_agreement_across_sections(self):
        request, data, plan = fixture()
        system = dataset_instruction(request, data, 1, plan_item=plan).system_message
        self.assertIn("keep optional tags compact and develop the scene in fluent prose", system)
        self.assertIn("Source identity facts govern every output section, including prose", system)
        self.assertIn("Preserve conflicting source attributes without inventing a reconciliation", system)
        self.assertNotIn("Batch planning, next-scene suggestions", system)

    def test_public_service_reuses_accepted_noncharacter_scene_without_planning(self):
        request, data, plan = fixture()
        data["scene_plan"] = [deepcopy(plan)]
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        original = deepcopy(data)
        backend = CaptureBackend()
        output = "panel_token. Two machines grip opposite edges of one red panel in a cargo bay."
        def generate(instruction):
            backend.calls.append(instruction)
            return output
        backend.generate = generate
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _: None, lambda _: None)
        self.assertEqual([call.diagnostic_stage for call in backend.calls], ["dataset:1"])
        self.assertEqual(result["prompts"][0]["prompt"], output)
        self.assertEqual(result["prompts"][0]["scene"], plan["scene"])
        self.assertEqual(result["prompts"][0]["idea"], plan["idea"])
        self.assertEqual(data, original)

    def test_comparison_matches_full_scene_context_settings_locks_and_budget(self):
        from tests.evaluation.run_dataset_writer_parity import comparison_instructions
        request, data, plan = fixture()
        plan["geometry"] = {"framing": "full_subject", "visibility_focus": ["both grips"]}
        original = deepcopy((request, data, plan))
        controls = comparison_instructions(request, data, plan)
        builder, writer = controls["builder"], controls["dataset"]
        self.assertEqual(builder.user_message, writer.user_message)
        for text in (plan["scene"], plan["idea"], data["subject"], data["inputs"], "both grips"):
            self.assertIn(text, builder.user_message)
        for instruction in (builder, writer):
            self.assertIn("anime/manga", instruction.system_message)
            self.assertIn("Semantic decisions are locked", instruction.system_message)
            self.assertIn('"panel_token"', instruction.system_message)
            self.assertEqual((instruction.max_tokens, instruction.hard_max_tokens, instruction.unlimited_tokens),
                             (3072, 3072, False))
            self.assertEqual((instruction.temperature, instruction.top_p), (.25, .85))
        self.assertEqual(builder.director_preset, writer.director_preset)
        self.assertEqual((request, data, plan), original)
        self.assertTrue(assemble_instruction(request, text_only=True).unlimited_tokens)

    def test_comparison_uses_dataset_settings_not_stale_builder_request(self):
        from tests.evaluation.run_dataset_writer_parity import comparison_instructions
        request, data, plan = fixture()
        request = replace(request, target_model="Generic", creativity="Strict", prompt_length="Short",
                          director_preset="photography_director", system_prompt_override="wrong director")
        controls = comparison_instructions(request, data, plan)
        self.assertIn("Anima target", controls["builder"].system_message)
        self.assertIn("Creativity — Balanced", controls["builder"].system_message)
        self.assertNotIn("wrong director", controls["builder"].system_message)
        self.assertEqual(controls["builder"].director_preset, controls["dataset"].director_preset)

    def test_frozen_baseline_with_different_scene_is_rejected_before_inference(self):
        from tests.evaluation.run_dataset_writer_parity import comparison_instructions
        request, data, plan = fixture()
        before = replace(dataset_instruction(request, data, 1, plan_item=plan), user_message="another scene")
        with self.assertRaisesRegex(ValueError, "same accepted scene"):
            comparison_instructions(request, data, plan, before=before)

    def test_frozen_baseline_with_different_style_or_budget_is_rejected(self):
        from tests.evaluation.run_dataset_writer_parity import comparison_instructions
        request, data, plan = fixture()
        before = dataset_instruction(request, data, 1, plan_item=plan)
        for altered in (replace(before, hard_max_tokens=768),
                        replace(before, system_message=before.system_message.replace("anime/manga", "photography"))):
            with self.subTest(altered=altered), self.assertRaisesRegex(ValueError, "matched"):
                comparison_instructions(request, data, plan, before=altered)

    def test_accepted_case_file_is_arbitrary_data_not_a_domain_registry(self):
        from tests.evaluation.run_dataset_writer_parity import load_accepted_cases, inputs
        request, data, plan = fixture()
        case = {"id": "industrial-panel", "accepted_by": "fixture reviewer", "concept": data["subject"],
                "idea": plan["idea"], "scene": plan["scene"], "input": plan["input"], "geometry": {},
                "trigger": data["trigger"], "type": "Custom", "custom_type": "industrial machines",
                "visual_style": "Anime / manga", "constraints": data["constraints"],
                "anchors": ["two machines share one panel"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accepted.json"
            path.write_text(json.dumps([case]), encoding="utf-8")
            cases = load_accepted_cases(path)
        row = {"case": "industrial-panel", "target": "Anima", "length": "Maximum Detail",
               "creativity": "Balanced", "director": "general_director"}
        _, actual_data, actual_plan = inputs(row, cases=cases)
        self.assertEqual(actual_plan["scene"], plan["scene"])
        self.assertEqual(actual_data["custom_type"], "industrial machines")
        self.assertEqual(actual_data["constraints"], data["constraints"])
        self.assertEqual(actual_data["visual_style"], "Anime / manga")

    def test_unaccepted_or_duplicate_case_files_are_rejected(self):
        from tests.evaluation.run_dataset_writer_parity import load_accepted_cases
        _, data, plan = fixture()
        case = {"id": "panel", "accepted_by": "fixture reviewer", "concept": data["subject"],
                "idea": plan["idea"], "scene": plan["scene"], "trigger": data["trigger"],
                "anchors": ["same panel"]}
        for rows in ([{**case, "accepted_by": ""}], [case, case], []):
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "accepted.json"
                path.write_text(json.dumps(rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_accepted_cases(path)

    def test_approved_character_fixtures_keep_exact_tags_and_block_four_person_case(self):
        from tests.evaluation.run_dataset_writer_parity import load_accepted_cases, inputs
        path = Path(__file__).parent / "evaluation" / "fixtures" / "issue_24_accepted_scenes.json"
        cases = load_accepted_cases(path)
        exact = "2boys, midoriya izuku, boku no hero academia, 1boy, green eyes, short hair, green hair, freckles, eren yeager, shingeki no kyojin, 1boy, green eyes, brown hair, black hair, short hair"
        self.assertEqual(len(cases), 10)
        for case in cases.values():
            self.assertEqual(case["trigger"], exact)
        runnable = [key for key, case in cases.items() if not case.get("evaluation_blocked")]
        self.assertEqual(len(runnable), 9)
        row = {"case": "three-rescuers-separate-civilian", "target": "Anima", "length": "Maximum Detail",
               "creativity": "Balanced", "director": "general_director"}
        with self.assertRaisesRegex(ValueError, "blocked"):
            inputs(row, cases=cases)
        for key in runnable:
            _, data, plan = inputs({**row, "case": key}, cases=cases)
            self.assertEqual(data["trigger"], exact)
            self.assertEqual(plan["scene"], cases[key]["scene"])

    def test_historical_snapshot_loads_original_writer_not_current_candidate(self):
        from tests.evaluation.run_dataset_writer_parity import baseline_dataset_writer, comparison_instructions
        baseline = "df92c88e12154e608f4a86cec2f44559d885191e"
        source_path = Path(__file__).parents[1] / "goated_prompter" / "prompting" / "dataset.py"
        source = source_path.read_text(encoding="utf-8").replace("        DATASET_WRITING_TASK,\n", "")
        with patch("tests.evaluation.run_dataset_writer_parity.subprocess.check_output",
                   side_effect=[baseline + "\n", source]) as git:
            writer, commit = baseline_dataset_writer(baseline)
        self.assertEqual(git.call_count, 2)
        self.assertEqual(git.call_args_list[1].args[0],
                         ["git", "show", f"{baseline}:goated_prompter/prompting/dataset.py"])
        self.assertEqual(commit, baseline)
        request, data, plan = fixture()
        before = writer(request, data, 1, plan_item=plan)
        controls = comparison_instructions(request, data, plan, before=before)
        self.assertNotIn("polished, directly usable prompt", before.system_message)
        self.assertIn("polished, directly usable prompt", controls["dataset"].system_message)
        self.assertEqual(before.user_message, controls["dataset"].user_message)

    def test_live_cli_refuses_managed_model_backend_before_creation(self):
        from tests.evaluation import run_dataset_writer_parity as runner
        _, data, plan = fixture()
        case = {"id": "panel", "accepted_by": "fixture reviewer", "concept": data["subject"],
                "idea": plan["idea"], "scene": plan["scene"], "trigger": data["trigger"], "anchors": ["panel"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps([case]), encoding="utf-8")
            (root / "engine.json").write_text('{"backend": "local_llama_cpp"}', encoding="utf-8")
            args = ["writer-parity", "--allow-live", "--accepted-scenes", str(root / "cases.json"),
                    "--config", str(root / "engine.json"), "--conditions", "builder", "dataset"]
            with patch("sys.argv", args), patch.object(runner, "create_backend") as factory, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    runner.main()
            self.assertEqual(error.exception.code, 2)
            factory.assert_not_called()

    def test_comparison_cli_runs_only_matched_first_pass_writers_with_mocked_engine(self):
        from tests.evaluation import run_dataset_writer_parity as runner
        _, data, plan = fixture()
        case = {"id": "panel", "accepted_by": "fixture reviewer", "concept": data["subject"],
                "idea": plan["idea"], "scene": plan["scene"], "trigger": data["trigger"],
                "visual_style": "Anime / manga", "anchors": ["same panel"]}
        backend = CaptureBackend()
        def generate(instruction):
            backend.calls.append(instruction)
            return "panel_token. Two machines hold one shared red panel."
        backend.generate = generate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps([case]), encoding="utf-8")
            (root / "engine.json").write_text('{"backend": "openai"}', encoding="utf-8")
            arguments = ["writer-parity", "--allow-live", "--accepted-scenes", str(root / "cases.json"),
                         "--config", str(root / "engine.json"), "--artifacts", str(root / "results.json"),
                         "--suite", "sampling", "--conditions", "builder", "dataset"]
            with patch("sys.argv", arguments), patch.object(runner, "create_backend", return_value=backend), redirect_stdout(io.StringIO()):
                runner.main()
            rows = json.loads((root / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(backend.calls[0].user_message, backend.calls[1].user_message)
        self.assertNotIn("no hat; no necklace", backend.calls[0].user_message)
        self.assertEqual({row["target"] for row in rows}, {"Anima"})
        self.assertEqual({row["comparison_phase"] for row in rows}, {"first_pass"})
        self.assertEqual(len({row["context_id"] for row in rows}), 1)
        self.assertTrue(all(row["controls_matched"] for row in rows))
        self.assertEqual(backend.sessions, 1)

    def test_comparison_cli_without_live_permission_never_creates_backend(self):
        from tests.evaluation import run_dataset_writer_parity as runner
        with patch("sys.argv", ["writer-parity", "--config", "not-read.json"]), \
                patch.object(runner, "create_backend") as factory, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                runner.main()
        self.assertEqual(error.exception.code, 2)
        factory.assert_not_called()

    def test_missing_render_review_cannot_pass_complete_quality_acceptance(self):
        record, label = reviewed_sample()
        report = score([record], [label])
        self.assertTrue(report["text_quality_passed"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["image_quality_status"], "unverified")
        label["render_review"] = {"quality": True, "artifact": "fixture-image.png",
                                  "settings": {"model": "fixture", "seed": 42}}
        self.assertTrue(score([record], [label])["passed"])

    def test_syntax_and_length_do_not_establish_writing_or_image_quality(self):
        record, label = reviewed_sample()
        report = score([record], annotation_template([record]))
        self.assertEqual(report["writing_quality_status"], "unverified")
        self.assertEqual(report["image_quality_status"], "unverified")
        self.assertEqual(report["semantic_correctness_status"], "unverified")

    def test_semantic_correctness_and_writing_quality_are_independent(self):
        record, label = reviewed_sample()
        label["writing_review"]["descriptive_usefulness"] = False
        report = score([record], [label])
        self.assertEqual(report["semantic_correctness_status"], "pass")
        self.assertEqual(report["writing_quality_status"], "fail")
        self.assertEqual(report["image_quality_status"], "unverified")
        label["writing_review"]["descriptive_usefulness"] = True
        label["anchors"]["two machines share one panel"] = False
        report = score([record], [label])
        self.assertEqual(report["semantic_correctness_status"], "fail")
        self.assertEqual(report["writing_quality_status"], "pass")
        self.assertFalse(report["passed"])

    def test_exploratory_labels_cannot_establish_independent_quality(self):
        record, label = reviewed_sample()
        label["review_kind"] = "exploratory"
        report = score([record], [label])
        self.assertEqual(report["writing_quality_status"], "unverified")
        self.assertEqual(report["semantic_correctness_status"], "unverified")

    def test_render_quality_requires_artifact_and_generator_settings(self):
        record, label = reviewed_sample()
        label["render_review"] = {"quality": True, "artifact": "", "settings": {}}
        self.assertEqual(score([record], [label])["image_quality_status"], "unverified")
        label["render_review"] = {"quality": False, "artifact": "fixture-image.png",
                                  "settings": {"model": "fixture", "seed": 42}}
        self.assertEqual(score([record], [label])["image_quality_status"], "fail")


if __name__ == "__main__":
    unittest.main()
