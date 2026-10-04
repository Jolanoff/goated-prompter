"""Advanced semantic contracts; real-engine measurements live in evaluation/."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch, MagicMock

from goated_prompter.core import PromptInstruction, GoatedPrompterRequest
from goated_prompter.dataset import DatasetService, validate_positive_content
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.dataset_constraints import compile_constraints, constraint_issues
from goated_prompter.dataset_idea_history import RecentIdeaHistory
from goated_prompter.dataset_quality import analyze_dataset_quality
from goated_prompter.dataset_visible_content import PositiveContentError
from goated_prompter.prompting.dataset import dataset_instruction
from goated_prompter.prompting.scene_planner import (scene_planner_instruction, idea_planner_instruction,
    scene_composer_instruction, DOMAIN_UNDERSTANDING, ACTION_FIRST_STAGING)
from goated_prompter.scene_planner import ScenePlanner
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.backends.base import BackendConfigurationError
from tests.test_dataset_geometry import character_geometry
from tests.test_dataset_quality_planning import draft


CORPUS = json.loads(Path(__file__).with_name("evaluation").joinpath("dataset_semantics.json").read_text(encoding="utf-8"))


class SemanticContractTests(unittest.TestCase):
    def test_fragment_rules_compile_without_echoing_negative_prefixes(self):
        compiled = compile_constraints(CORPUS["constraints"][0]["rules"])
        self.assertEqual(compiled, {"required": ["same dark hair"], "forbidden": ["hat", "jewelry", "outdoor scenes"],
                                   "variable": ["clothing"], "unresolved": []})
        data = draft(constraints=CORPUS["constraints"][0]["rules"])
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        self.assertNotIn("no hat", instruction.user_message.casefold())
        self.assertNotIn("no jewelry", instruction.user_message.casefold())
        for heading in ("REQUIRED FACTS", "FORBIDDEN FACTS", "VARIATION ALLOWED"):
            self.assertIn(heading, instruction.user_message)

    def test_natural_prose_compiles_by_syntax_not_a_noun_mapping(self):
        compiled = compile_constraints(CORPUS["constraints"][1]["rules"])
        self.assertEqual(compiled["required"], ["Keep her hairstyle consistent"])
        self.assertEqual(compiled["forbidden"], ["hats", "necklaces"])
        self.assertEqual(compiled["variable"], ["Outfits"])
        self.assertEqual(compiled["unresolved"], [])
        self.assertEqual(compile_constraints("no quaternion-shaped badges")["forbidden"], ["quaternion-shaped badges"])

    def test_conditionals_literals_and_conflicting_facts_are_not_silently_reinterpreted(self):
        compiled = compile_constraints('No hats unless the guided input requires one; a sign reads "NO HAT"; clothing may vary')
        self.assertEqual(compiled["forbidden"], [])
        self.assertEqual(len(compiled["unresolved"]), 1)
        self.assertIn('a sign reads "NO HAT"', compiled["required"])
        self.assertEqual(compiled["variable"], ["clothing"])

    def test_forbidden_content_and_verbalized_exclusion_are_separate_checks(self):
        compiled = compile_constraints("no hat; no jewelry")
        for text in ("She wears a red hat.", "She is wearing a tall hat.", "She holds two hats."):
            self.assertEqual(constraint_issues(text, compiled)[0]["code"], "forbidden_content")
        for text in ("She wears no hat.", "A woman without a hat.", "No jewelry decorates her outfit.", "The hat is absent."):
            self.assertEqual(constraint_issues(text, compiled)[0]["code"], "constraint_negative_leakage")
        for text in ("Her uncovered hair catches the light.", 'A placard reads "NO HAT".', "She holds a hatchet."):
            self.assertEqual(constraint_issues(text, compiled), [])
        self.assertEqual(constraint_issues("A woman wearing a red hat.", compiled, ("red hat",)), [])

    def test_plural_exclusions_and_unknown_objects_use_the_supplied_facts(self):
        compiled = compile_constraints("don't use hats or necklaces; no quaternion-shaped badges")
        for text in ("She wears a necklace.", "She wears a hat.", "She wears a quaternion-shaped badge."):
            issues = constraint_issues(text, compiled)
            self.assertTrue(issues)
            self.assertEqual(issues[0]["code"], "forbidden_content")
        compiled = compile_constraints("no " + "very " * 40 + "hat")
        self.assertEqual(constraint_issues("A woman wears " + "very " * 120 + "cloak.", compiled), [])

    def test_writer_repairs_leaked_exclusion_without_replanning(self):
        data = draft(constraints="same dark hair; no hat; clothing may vary")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
        session = Mock()
        session.generate.side_effect = ["person_token, dark hair, no hat, balancing on the beam.",
                                       "person_token balances on the beam, dark hair swept behind her ears."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None)
        self.assertNotIn("no hat", output)
        self.assertEqual(session.generate.call_count, 2)
        self.assertEqual(session.generate.call_args.args[0].user_message, instruction.user_message)
        self.assertIn(":content_retry_1", session.generate.call_args.args[0].diagnostic_stage)
        with self.assertRaises(PositiveContentError):
            validate_positive_content("person_token wears a red hat.", data)

    def test_ideogram_validator_checks_all_positive_fields_not_rendered_literals(self):
        from tests.test_dataset_visible_content import caption
        data = draft(target="Ideogram4", constraints="no hat")
        value = caption()
        value["compositional_deconstruction"]["elements"][0]["desc"] += " She wears a red hat."
        with self.assertRaises(PositiveContentError):
            validate_positive_content(json.dumps(value), data)
        value = caption()
        value["compositional_deconstruction"]["elements"].append({"type": "text", "text": "NO HAT", "desc": "Lettering on a placard."})
        self.assertTrue(validate_positive_content(json.dumps(value), data))

    def test_quality_reports_constraints_separately_and_tracks_rule_changes(self):
        data = draft(amount=2, constraints="no hat")
        prompts = [{"index": 1, "prompt": "person_token wears a tall hat while balancing on a wooden beam."},
                   {"index": 2, "prompt": "person_token balances on a wooden beam with no hat on her head."}]
        report = analyze_dataset_quality(data, prompts)
        codes = [{issue["code"] for issue in row["issues"]} for row in report["prompts"]]
        self.assertIn("forbidden_content", codes[0])
        self.assertIn("constraint_negative_leakage", codes[1])
        self.assertNotEqual(report["signature"], analyze_dataset_quality({**data, "constraints": ""}, prompts)["signature"])

    def test_domain_understanding_is_general_and_shared_by_both_idea_paths(self):
        for case in CORPUS["domains"]:
            data = draft(subject=case["concept"])
            for build in (idea_planner_instruction, scene_planner_instruction):
                instruction = build(data, dataset_assignments(data))
                self.assertIn(DOMAIN_UNDERSTANDING, instruction.system_message)
                self.assertNotIn("explore compatible families", instruction.system_message)
                self.assertNotIn("chef →", instruction.system_message)
                self.assertIn(case["concept"], instruction.user_message)

    def test_stage_sampling_is_exploratory_only_for_ideation(self):
        values = []
        for variety in ("Focused", "Balanced", "Wide"):
            data = draft(variety=variety)
            assignments = dataset_assignments(data)
            idea = idea_planner_instruction(data, assignments)
            fast = scene_planner_instruction(data, assignments)
            composer = scene_composer_instruction(data, assignments, [{"index": 1, "idea": "A specialized movement"}])
            writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1)
            self.assertEqual(idea.temperature, fast.temperature)
            self.assertEqual((composer.temperature, writer.temperature), (.25, .25))
            self.assertLess(composer.temperature, idea.temperature)
            values.append(idea.temperature)
        self.assertEqual(values, sorted(values))
        self.assertIsNone(PromptInstruction("system", "text").temperature)
        self.assertIsNone(PromptInstruction("system", "text").top_p)

    def test_sampling_is_sent_in_request_payload_and_does_not_mutate_backend(self):
        backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:1/v1", "model": "test", "temperature": .3})
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"result"},"finish_reason":"stop"}]}'
        with patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send, \
             patch("goated_prompter.backends.openai_compatible.log_request"), patch("goated_prompter.backends.openai_compatible.log_response"):
            backend.generate(PromptInstruction("system", "text", temperature=.85, top_p=.96))
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual((payload["temperature"], payload["top_p"]), (.85, .96))
            backend.generate(PromptInstruction("system", "text"))
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual(payload["temperature"], .3)
            self.assertNotIn("top_p", payload)

    def test_request_sampling_rejects_invalid_values_before_transport(self):
        backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:1/v1", "model": "test"})
        for overrides in ({"temperature": float("nan")}, {"temperature": True}, {"temperature": 3},
                          {"top_p": -1}, {"top_p": float("inf")}):
            with self.subTest(overrides=overrides), patch("goated_prompter.backends.openai_compatible.urlopen") as send:
                with self.assertRaises(BackendConfigurationError):
                    backend.generate(PromptInstruction("system", "text", **overrides))
                send.assert_not_called()

    def test_advanced_custom_pose_survives_without_repair_or_enum_growth(self):
        data = draft(amount=1, subject="A performer demonstrating a one-hand cartwheel", planning_mode="Quality")
        detail = "Left palm bears weight on the mat; right arm lifted; split legs inverted above the leaning torso; head faces the support hand."
        idea = {"index": 1, "idea": "Performing a one-hand cartwheel"}
        row = {**idea, "scene": "She rotates through a one-hand cartwheel, left palm planted on the mat, right arm raised and legs split overhead, head toward the supporting hand.",
               "geometry": character_geometry(pose_type="custom", pose_detail=detail, gaze_direction="toward_action", head_direction="toward_action")}
        session = Mock()
        session.generate.return_value = json.dumps([row])
        planned = ScenePlanner(lambda: None).compose(session=session, data=data, assignments=dataset_assignments(data), ideas=[idea], progress=lambda _: None)
        self.assertEqual(planned[0]["geometry"]["pose_detail"], detail)
        self.assertEqual(session.generate.call_count, 1)
        instruction = session.generate.call_args.args[0]
        self.assertIn(ACTION_FIRST_STAGING, instruction.system_message)
        self.assertNotIn("recently_used_ideas", json.loads(instruction.user_message))
        writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=row)
        self.assertIn(detail, writer.user_message)

    def test_quality_guided_ideas_preserve_defining_physical_qualifiers(self):
        from goated_prompter.prompting.scene_planner import GUIDED_ASSIGNMENT_RULES
        for case in CORPUS["poses"] + CORPUS["interactions"]:
            data = draft(source_mode="guided", inputs=case["input"], amount=1)
            instruction = idea_planner_instruction(data, dataset_assignments(data))
            self.assertIn(GUIDED_ASSIGNMENT_RULES, instruction.system_message)
            self.assertIn(case["input"], instruction.user_message)
        self.assertEqual(constraint_issues("The table is clear of branding.", compile_constraints("no visible branding"))[0]["code"],
                         "constraint_negative_leakage")

    def test_uncertain_same_family_ideas_are_warnings_not_replacements(self):
        data = draft(amount=2)
        ideas = [{"index": 1, "idea": "Trying to juggle oranges and failing"},
                 {"index": 2, "idea": "Dropping fruit while attempting to juggle"}]
        session = Mock()
        session.generate.return_value = json.dumps(ideas)
        rows = ScenePlanner(lambda: None).plan_ideas(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(rows, ideas)
        self.assertEqual(session.generate.call_count, 1)

    def test_asymmetric_group_support_survives_without_global_pose_or_gaze(self):
        data = draft(amount=1, trigger_type="Multiple characters")
        idea = {"index": 1, "idea": "One performer carries another across a mat"}
        row = {**idea, "scene": "The carrier plants both feet on a mat, left forearm under the partner's knees and right forearm behind their upper back. The carried partner reclines sideways, right arm around the carrier's shoulder, watching the carrier's face; the carrier looks toward the path ahead.",
               "geometry": {"framing": "wide_shot", "camera_azimuth": "front_three_quarter_left",
                            "composition": "centered", "primary_subject_count": 2, "action_visibility": "clear"}}
        session = Mock()
        session.generate.return_value = json.dumps([row])
        composed = ScenePlanner(lambda: None).compose(session=session, data=data, assignments=dataset_assignments(data),
            ideas=[idea], progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(composed[0]["scene"], row["scene"])
        self.assertNotIn("gaze_direction", composed[0]["geometry"])
        self.assertNotIn("pose_type", composed[0]["geometry"])
        writer = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=composed[0])
        self.assertIn(row["scene"], writer.user_message)

    def test_corpus_covers_all_requested_advanced_areas_without_production_imports(self):
        self.assertEqual(len(CORPUS["domains"]), 10)
        self.assertEqual(len(CORPUS["poses"]), 8)
        self.assertEqual(len(CORPUS["interactions"]), 5)
        self.assertTrue(all(case["runs"] == 5 and case["amount"] == 10 for case in CORPUS["novelty"]))

    def test_semantic_metrics_require_annotations_not_lexical_guesses(self):
        import importlib.util
        path = Path(__file__).with_name("evaluation").joinpath("run_dataset_semantics.py")
        spec = importlib.util.spec_from_file_location("semantic_evaluation", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runs = [{"concept": "One concept", "scene_repair_calls": 0, "rows": [{"index": 1, "idea": "Running a race", "evaluation_id": "one"}]},
                {"concept": "One concept", "scene_repair_calls": 0, "rows": [{"index": 1, "idea": "Racing on foot", "evaluation_id": "two"}]}]
        metrics = module.summarize(runs)
        self.assertIsNone(metrics["idea_duplicate_rate_semantic"])
        self.assertIsNone(metrics["cross_run_repeated_idea_rate_semantic"])
        scored = module.summarize(runs, [{"id": "one", "event_id": "footrace"}, {"id": "two", "event_id": "footrace"}])
        self.assertEqual(scored["cross_run_repeated_idea_rate_semantic"], 1)
        self.assertEqual(scored["cross_run_repeated_idea_rate_exact"], 0)


class RecentIdeaTests(unittest.TestCase):
    def test_history_is_bounded_normalized_scoped_and_resettable(self):
        history = RecentIdeaHistory(limit=40, concepts=2)
        data = draft(subject="A Performer")
        history.remember(data, [{"idea": f"Distinct event {n}"} for n in range(60)])
        self.assertEqual(len(history.recent({**data, "subject": " a  performer "})), 40)
        self.assertEqual(history.recent({**data, "trigger_type": "Animal"}), [])
        self.assertEqual(history.recent({**data, "subject": "Another concept"}), [])
        history.clear(data)
        self.assertEqual(history.recent(data), [])

    def test_quality_idea_runs_receive_previous_ideas_but_not_absolute_exclusions(self):
        history = RecentIdeaHistory()
        data = draft(amount=1)
        planner = ScenePlanner(lambda: None, history)
        for number in range(5):
            session = Mock()
            session.generate.return_value = json.dumps([{"index": 1, "idea": f"Concept-specific event {number}"}])
            planner.plan_ideas(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _: None)
            instruction = session.generate.call_args.args[0]
            self.assertEqual(len(json.loads(instruction.user_message)["recently_used_ideas"]), number)
            self.assertIn("never absolute exclusions", instruction.system_message)
        history.clear()
        self.assertEqual(history.recent(data), [])

    def test_fast_cross_run_memory_preserves_four_row_chunks(self):
        history = RecentIdeaHistory()
        data = draft(amount=5, planning_mode="Fast")
        history.remember(data, [{"idea": "Previously used conceptual event"}])
        session = Mock()
        def generate(instruction):
            context = json.loads(instruction.user_message)
            return json.dumps([{"index": index, "idea": f"Activity number {index}", "scene": f"She performs activity number {index} beside a platform.",
                                "geometry": character_geometry()} for index in context["indexes"]])
        session.generate.side_effect = generate
        ScenePlanner(lambda: None, history).plan_batch(session=session, data=data, assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual([json.loads(call.args[0].user_message)["amount"] for call in session.generate.call_args_list], [4, 1])
        self.assertIn("Previously used conceptual event", session.generate.call_args.args[0].user_message)
        self.assertEqual(len(history.recent(data)), 6)

    def test_history_expires_without_disk_storage(self):
        history = RecentIdeaHistory(ttl=10)
        data = draft()
        with patch("goated_prompter.dataset_idea_history.time.monotonic", return_value=1):
            history.remember(data, [{"idea": "A concept-relevant event"}])
        with patch("goated_prompter.dataset_idea_history.time.monotonic", return_value=12):
            self.assertEqual(history.recent(data), [])
