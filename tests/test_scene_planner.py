"""Dataset-only planning contracts, schema, retries, fallback and writer handoff."""

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft, validate_dataset_draft, _parse_deep_review
from goated_prompter.dataset_coverage import effective_coverage_plan
from goated_prompter.prompting import dataset as dataset_prompts
from goated_prompter.prompting.scene_planner import (scene_planner_instruction, MAX_SCENE_CHARACTERS,
                                                    MAX_SCENE_WORDS, MAX_IDEA_CHARACTERS, MAX_IDEA_WORDS, TYPE_GUIDANCE)
from goated_prompter.scene_planner import (ScenePlanner, validate_scene_plan, scene_plan_signature,
                                         reusable_scene_plan, validate_saved_scene_plan)


def draft(**changes):
    return {**default_dataset_draft(), "amount": 2, "trigger": "person_token",
            "subject": "An adult character reading at home.", **changes}


def scene_rows(amount=2):
    return [{"index": index, "idea": f"Reading a different book {index}",
             "scene": f"Reading on a red couch beside window {index}, face visible in soft daylight."}
            for index in range(1, amount + 1)]


class ScenePlannerTests(unittest.TestCase):
    def test_planning_process_separates_concept_ideas_scenes_and_silent_audit(self):
        data = draft()
        system = scene_planner_instruction(data, effective_coverage_plan(data)).system_message
        steps = ["STEP 1 — UNDERSTAND", "STEP 2 — GENERATE", "STEP 3 — COMPOSE",
                 "STEP 4 — CHECK GEOMETRY", "STEP 5 — REPAIR", "STEP 6 — RETURN"]
        self.assertEqual([system.index(step) for step in steps], sorted(system.index(step) for step in steps))
        for heading in ("IDEA DUPLICATION CHECK", "SCENE GEOMETRY AND VISIBILITY", "VISIBLE DETAIL RULE",
                        "BODY AND POSE LOGIC", "ACTION LOGIC", "GAZE LOGIC", "EXPRESSION LOGIC", "SCENE COHERENCE AUDIT"):
            self.assertIn(heading, system)
        self.assertIn("not only everyday accidents", system)
        self.assertIn("Do not automatically force eye contact", system)
        self.assertIn("normally 3–15 words", system)
        self.assertIn("14. NO ANATOMY HACKS", system)
        self.assertIn("exactly three keys", system)

    def test_broad_and_narrow_concepts_produce_matching_idea_scene_counts_in_one_call(self):
        # Mocked semantic examples test orchestration, not real LLM creativity.
        cases = [
            ("woman doing funny stuff", "Character", ["Wearing a ridiculous clown costume", "Trying to juggle and failing", "Walking in oversized shoes"]),
            ("dog having adventures", "Animal", ["Exploring a tide pool", "Digging up a buried toy", "Crossing a shallow stream"]),
            ("man doing sports", "Character", ["Shooting a basketball", "Returning a tennis serve", "Balancing on a skateboard"]),
            ("woman posing confidently", "Character", ["Standing with hands on hips", "Leaning against a wall", "Sitting with relaxed shoulders"]),
            ("robot doing human jobs", "Custom", ["Serving coffee", "Sorting letters", "Painting a wall"]),
            ("woman doing different facial expressions", "Character", ["Puffing her cheeks", "Raising one eyebrow", "Crossing her eyes"]),
            ("product used in creative situations", "Object / product", ["Illuminating a shadow puppet", "Lighting a paper lantern", "Casting light through colored glass"]),
        ]
        for concept, kind, ideas in cases:
            with self.subTest(concept=concept):
                data = draft(subject=concept, trigger_type=kind, amount=len(ideas))
                rows = [{"index": i, "idea": idea,
                         "scene": f"{idea}, with the recurring subject and necessary interaction visible together from one three-quarter viewpoint."}
                        for i, idea in enumerate(ideas, 1)]
                session = Mock()
                session.generate.return_value = json.dumps(rows)
                planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                    coverage=effective_coverage_plan(data), progress=lambda _: None)
                self.assertEqual(planned, rows)
                self.assertEqual(len([row["idea"] for row in planned]), data["amount"])
                self.assertEqual(len([row["scene"] for row in planned]), data["amount"])
                self.assertEqual(session.generate.call_count, 1)
                self.assertEqual(json.loads(session.generate.call_args.args[0].user_message)["subject"], concept)

    def test_ten_distinct_funny_ideas_remain_separate_from_their_scenes(self):
        ideas = ["Wearing a clown costume", "Making a ridiculous facial expression", "Trying to juggle and failing",
                 "Walking in oversized shoes", "Getting tangled in a bedsheet", "Carrying too many grocery bags",
                 "Sitting in an undersized chair", "Taking a ridiculous selfie", "Catching popcorn in her mouth",
                 "Wearing a sweater backwards"]
        rows = [{"index": i, "idea": idea, "scene": f"A woman {idea.lower()}, in a single readable moment with the necessary props in reach and her gaze supporting the action."}
                for i, idea in enumerate(ideas, 1)]
        session = Mock()
        session.generate.return_value = json.dumps(rows)
        data = draft(subject="woman doing funny stuff", amount=10)
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(len(planned), 10)
        self.assertEqual(len({row["idea"] for row in planned}), 10)
        self.assertTrue(all(row["idea"] != row["scene"] for row in planned))
        session.generate.assert_called_once()

    def test_idea_similarity_distinguishes_broad_concept_from_expression_scope(self):
        from goated_prompter.dataset_coverage import analyze_idea_diversity
        rows = [{"index": i, "idea": idea} for i, idea in enumerate(
            ("laughing indoors", "laughing outside", "laughing at night"), 1)]
        quality = analyze_idea_diversity(draft(subject="woman doing funny stuff"), rows)
        self.assertLess(quality["uniqueness"], 100)
        faces = [{"index": i, "idea": idea} for i, idea in enumerate(
            ("funny face with tongue out", "funny face crossing eyes", "funny face puffing cheeks"), 1)]
        self.assertLess(analyze_idea_diversity(draft(subject="woman doing funny stuff"), faces)["uniqueness"], 100)
        self.assertEqual(analyze_idea_diversity(draft(subject="woman doing funny facial expressions"), faces)["uniqueness"], 100)
        self.assertEqual(analyze_idea_diversity(draft(source_mode="guided"), faces)["uniqueness"], 100)

    def test_guided_clown_costume_stays_an_idea_and_not_another_activity(self):
        data = draft(amount=1, source_mode="guided", inputs="clown costume")
        rows = [{"index": 1, "idea": "Wearing a ridiculous clown costume",
                 "scene": "She stands in a clown costume in full-body front three-quarter view, balanced with hands on hips and an intentionally deadpan expression."}]
        session = Mock()
        session.generate.return_value = json.dumps(rows)
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertIn("clown costume", planned[0]["idea"])
        self.assertIn("clown costume", planned[0]["scene"])
        self.assertNotIn("juggling", planned[0]["scene"])
        self.assertIn("Clown costume", session.generate.call_args.args[0].system_message)

    def test_legacy_plans_remain_loadable_but_are_not_reused_without_ideas(self):
        data = draft(scene_plan=[{"index": i, "input": "", "scene": f"Reading beside window {i}."} for i in (1, 2)])
        data["scene_plan_signature"] = scene_plan_signature(data, effective_coverage_plan(data))
        self.assertEqual(validate_dataset_draft(data)["scene_plan"], data["scene_plan"])
        self.assertIsNone(reusable_scene_plan(data, effective_coverage_plan(data)))
        data["results"] = [{"index": 1, "input": "", "scene": "An old scene.", "prompt": "An old prompt."}]
        self.assertNotIn("idea", validate_dataset_draft(data)["results"][0])

    def test_geometry_hints_flag_explicit_conflicts_without_policing_valid_poses(self):
        from goated_prompter.dataset_coverage import explicit_geometry_issues, analyze_dataset_quality
        cases = [
            ("Direct rear view of woman, looking directly into the camera, full frontal face clearly visible.", "rear_front_conflict"),
            ("Tight face close-up with shoes clearly visible.", "crop_visibility_conflict"),
            ("Camera directly in front of her; camera directly behind her.", "camera_direction_conflict"),
            ("Rear three-quarter body orientation, head turned over shoulder toward camera, one side of face visible.", None),
            ("Juggling oranges, eyes following one falling orange, hands ready beneath it.", None),
            ("Tight face close-up, shoes not visible.", None),
            ("Not a direct rear view; full frontal face clearly visible.", None),
            ("Direct rear view with full frontal face visible in a mirror reflection.", None),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                codes = {issue["code"] for issue in explicit_geometry_issues(text)}
                self.assertEqual(codes, {expected} if expected else set())
        data = draft(amount=1)
        result = [{"index": 1, "input": "", "idea": "Looking over her shoulder",
                   "scene": cases[3][0], "prompt": "person_token. " + cases[0][0]}]
        report = analyze_dataset_quality(data, result)
        codes = {issue["code"] for issue in report["prompts"][0]["issues"]}
        self.assertIn("prompt_rear_front_conflict", codes)
        self.assertNotIn("scene_rear_front_conflict", codes)

    def test_deep_review_compares_idea_geometry_and_handles_valid_and_invalid_cases(self):
        from goated_prompter.dataset import DatasetReviewService
        rows = [
            {"index": 1, "input": "", "idea": "Looking back over a shoulder",
             "scene": "Rear three-quarter body, head turned over shoulder with one side of face visible.",
             "prompt": "person_token in direct rear view with full frontal face clearly visible, looking at camera."},
            {"index": 2, "input": "", "idea": "Looking back over a shoulder",
             "scene": "Rear three-quarter body, head turned over shoulder with one side of face visible.",
             "prompt": "person_token in rear three-quarter orientation with head turned over shoulder and one side of face visible."},
            {"index": 3, "input": "", "idea": "Walking in oversized shoes",
             "scene": "Full-body side three-quarter view, taking an awkward balanced step in oversized shoes.",
             "prompt": "person_token in tight face close-up with shoes clearly visible."},
            {"index": 4, "input": "", "idea": "Trying to juggle and failing",
             "scene": "Three-quarter body, hands below falling oranges, eyes tracking the nearest orange.",
             "prompt": "person_token attempting to juggle, three-quarter body, eyes following one falling orange."},
        ]
        session = Mock()
        session.generate.return_value = json.dumps([
            {"index": i, "issues": ([{"category": category, "severity": "error", "message": message}] if category else [])}
            for i, category, message in ((1, "scene_drift", "Writer replaced valid rear three-quarter turn with contradictory frontal visibility."),
                                         (2, None, ""), (3, "target_usability", "Tight face crop cannot show shoes."), (4, None, ""))])
        backend = Mock()
        backend.name = "geometry-review-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        data = draft(amount=4, results=rows)
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetReviewService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None)
        instruction = session.generate.call_args.args[0]
        for row in rows:
            for key in ("idea", "scene", "prompt"):
                self.assertIn(row[key], instruction.user_message)
        self.assertIn("IDEA FIDELITY", instruction.system_message)
        self.assertIn("SCENE GEOMETRY", instruction.system_message)
        self.assertEqual(result["report"]["deep_review"]["errors"], 2)
        checks = {row["index"]: row for row in result["report"]["prompts"]}
        self.assertIn("deep_scene_drift", {issue["code"] for issue in checks[1]["issues"]})
        self.assertIn("deep_target_usability", {issue["code"] for issue in checks[3]["issues"]})
        self.assertTrue(all(not issue["code"].startswith("deep_") for i in (2, 4) for issue in checks[i]["issues"]))

    def test_writer_preserves_semantic_purpose_and_geometry_through_loop_retry(self):
        from goated_prompter.backends.base import BackendRunawayError
        data = draft(amount=1)
        plan = {"index": 1, "input": "", "idea": "Trying to juggle and failing",
                "scene": "She stands in three-quarter body orientation, hands beneath falling oranges, gaze tracking the nearest falling orange."}
        original = dataset_prompts.dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=plan)
        session = Mock()
        session.generate.side_effect = [BackendRunawayError("loop"),
            "person_token in three-quarter body orientation, unsuccessfully juggling oranges, gaze tracking a falling orange."]
        final = DatasetService({}, lambda: None)._generate(session, original, data, 1, lambda _: None)
        for call in session.generate.call_args_list:
            instruction = call.args[0]
            self.assertIn(plan["idea"], instruction.user_message)
            self.assertIn(plan["scene"], instruction.user_message)
            self.assertIn("IDEA is authoritative for semantic purpose", instruction.system_message)
            self.assertIn("independently force eye contact", instruction.system_message)
            self.assertIn("GEOMETRY FIDELITY", instruction.system_message)
        self.assertIn("gaze tracking", final)
        self.assertNotIn("looking directly at viewer", final)

    def test_idea_first_and_still_image_contract(self):
        data = draft(subject="A woman doing funny stuff")
        instruction = scene_planner_instruction(data, effective_coverage_plan(data))
        for section in ("SCENE IDEA FIRST", "VISUAL DEPICTABILITY", "ONE PRIMARY EVENT",
                        "CONTROLLED VARIATION", "COVERAGE SUPPORTS THE IDEA"):
            self.assertIn(section, instruction.system_message)
        self.assertIn("SEMANTIC DIVERSITY FIRST", instruction.system_message)
        self.assertIn("normally 20–70 words", instruction.system_message)
        self.assertIn(f"at most {MAX_SCENE_WORDS} words", instruction.system_message)
        scenes = ["A woman freezes with a raised spatula as a flipped pancake lands on her head in the kitchen.",
                  "A woman chases oranges rolling from a torn grocery bag across a supermarket parking lot.",
                  "A woman leans into the wind holding an inverted umbrella and a precariously tilted coffee cup."]
        session = Mock()
        data["amount"] = len(scenes)
        ideas = ["Pancake flip landing on her head", "Chasing spilled oranges", "Fighting an inverted umbrella"]
        session.generate.return_value = json.dumps([{"index": i, "idea": idea, "scene": scene}
            for i, (idea, scene) in enumerate(zip(ideas, scenes), 1)])
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("woman" in row["scene"].lower() for row in rows))
        from goated_prompter.dataset_coverage import analyze_scene_diversity
        self.assertEqual(analyze_scene_diversity(rows)["uniqueness"], 100)

    def test_guided_plan_retains_original_action_and_named_objects(self):
        data = draft(amount=1, source_mode="guided", inputs="sitting on a red couch reading a book")
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "idea": "Sitting on a red couch reading a book",
            "scene": "Sitting sideways on a red couch reading an open book, with a relaxed posture beside a window."}])
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        context = json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual(context["assignments"][0]["input"], data["inputs"])
        for anchor in ("sitting", "red couch", "reading", "book"):
            self.assertIn(anchor, rows[0]["scene"].lower())

    def test_plan_signature_excludes_writer_settings_and_invalidates_semantic_changes(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        coverage = effective_coverage_plan(data)
        data["scene_plan_signature"] = scene_plan_signature(data, coverage)
        self.assertEqual(reusable_scene_plan(data, coverage), data["scene_plan"])
        for changes in ({"target": "Anima"}, {"target": "Ideogram4", "length": "Detailed"},
                        {"director_preset": "other"}, {"trigger": "new_token", "trigger_at_start": True}):
            changed = {**data, **changes}
            self.assertEqual(reusable_scene_plan(changed, effective_coverage_plan(changed)), data["scene_plan"])
        for changes in ({"subject": "A dog having adventures"}, {"inputs": "running"}, {"amount": 3},
                        {"constraints": "No outdoors"}, {"variety": "Wide"}, {"trigger_type": "Animal"},
                        {"coverage_enabled": True}, {"visual_style": "Illustration"}):
            changed = {**data, **changes}
            self.assertIsNone(reusable_scene_plan(changed, effective_coverage_plan(changed)))
        covered = {**data, "coverage_enabled": True}
        coverage = effective_coverage_plan(covered)
        covered["scene_plan_signature"] = scene_plan_signature(covered, coverage)
        self.assertEqual(reusable_scene_plan(covered, coverage), data["scene_plan"])
        changed_coverage = json.loads(json.dumps(coverage))
        changed_coverage["plan"][0]["facets"]["framing"] = "full view"
        if changed_coverage == coverage:
            changed_coverage["plan"][0]["facets"]["framing"] = "medium shot"
        self.assertIsNone(reusable_scene_plan(covered, changed_coverage))

    def test_scene_plan_and_new_and_legacy_results_roundtrip(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        data["scene_plan_signature"] = scene_plan_signature(data, effective_coverage_plan(data))
        data["results"] = [{"index": 1, "input": "", "idea": data["scene_plan"][0]["idea"],
                           "scene": data["scene_plan"][0]["scene"], "prompt": "A readable prompt."},
                           {"index": 2, "input": "", "prompt": "A legacy prompt."}]
        self.assertEqual(validate_dataset_draft(json.loads(json.dumps(data))), data)
        for invalid in ([{"index": 2, "input": "", "scene": "Wrong index"}],
                        [{"index": 1, "input": "", "scene": "text", "extra": True}]):
            with self.assertRaises(ValueError):
                validate_saved_scene_plan(invalid)

    def test_valid_saved_plan_skips_scene_llm_for_different_targets(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        data["scene_plan_signature"] = scene_plan_signature(data, effective_coverage_plan(data))
        session = Mock()
        session.generate.return_value = "A clear person_token scene with a red couch and an open book."
        backend = Mock()
        backend.name = "test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            for target in ("Generic", "Qwen Image", "Anima", "Krea 2"):
                changed = {**data, "target": target}
                result = DatasetService({"backend": "mock"}, lambda: None).run(
                    GoatedPrompterRequest(idea=data["subject"], target_model=target), changed, lambda _: None, lambda _: None)
                self.assertEqual(result["scene_plan"], data["scene_plan"])
                self.assertEqual([row["scene"] for row in result["prompts"]], [row["scene"] for row in data["scene_plan"]])
        self.assertEqual(session.generate.call_count, 8)
        self.assertTrue(all(not call.args[0].diagnostic_stage.startswith("dataset:scene_planner")
                            for call in session.generate.call_args_list))

    def test_changed_concept_replans_and_plan_only_does_not_write_prompts(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        data["scene_plan_signature"] = scene_plan_signature(data, effective_coverage_plan(data))
        data["subject"] = "A woman doing funny stuff"
        session = Mock()
        session.generate.return_value = json.dumps(scene_rows())
        backend = Mock()
        backend.name = "test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None, scenes_only=True)
        self.assertEqual(session.generate.call_count, 1)
        self.assertEqual(result["kind"], "dataset_scenes")
        self.assertNotIn("prompts", result)
        self.assertEqual(len(result["scene_plan"]), 2)
        session.reset_mock()
        session.generate.side_effect = [json.dumps(scene_rows()),
            "person_token in a concrete scene with a red couch.",
            "person_token in another clear scene with a book."]
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None)
        self.assertEqual(session.generate.call_count, 3)
        self.assertEqual(session.generate.call_args_list[0].args[0].diagnostic_stage, "dataset:scene_planner")

    def test_deep_review_sees_originating_scene_and_accepts_scene_drift(self):
        data = draft(amount=1, coverage_enabled=True)
        chunk = [{"index": 1, "input": "", "scene": "Chasing a runaway shopping cart across a parking lot.",
                  "prompt": "A smiling woman portrait in a supermarket."}]
        instruction = dataset_prompts.deep_review_instruction(data, chunk)
        self.assertIn(chunk[0]["scene"], instruction.user_message)
        self.assertIn(chunk[0]["prompt"], instruction.user_message)
        self.assertIn("scene_drift", instruction.system_message)
        self.assertIn("not proof of achieved coverage", instruction.system_message)
        result = _parse_deep_review(json.dumps([{"index": 1, "issues": [{"category": "scene_drift",
            "severity": "error", "message": "The chase was replaced by a portrait."}]}]), chunk, True)
        self.assertEqual(result[0]["issues"][0]["code"], "deep_scene_drift")
        legacy = [{key: value for key, value in chunk[0].items() if key != "scene"}]
        self.assertIn("legacy result", dataset_prompts.deep_review_instruction(data, legacy).user_message)

    def test_quality_distinguishes_planned_coverage_and_scene_similarity(self):
        from goated_prompter.dataset_coverage import analyze_dataset_quality, analyze_scene_diversity
        data = draft(coverage_enabled=True)
        results = [{"index": 1, "input": "", "scene": "A woman stands laughing in a bedroom under soft daylight.",
                    "prompt": "person_token enjoys a well-described clear scene at home."},
                   {"index": 2, "input": "", "scene": "A woman stands laughing in a kitchen under warm light.",
                    "prompt": "An entirely different written prompt of person_token elsewhere."}]
        report = analyze_dataset_quality(data, results)
        self.assertIn("planned_coverage", report["metrics"])
        self.assertNotIn("coverage", report["metrics"])
        self.assertLess(report["metrics"]["scene_uniqueness"], 100)
        codes = {issue["code"] for row in report["prompts"] for issue in row["issues"]}
        self.assertIn("repeated_scene_event", codes)
        results[1]["scene"] = results[0]["scene"]
        quality = analyze_scene_diversity(results)
        self.assertEqual(quality["scenes"][0]["issues"][0]["code"], "exact_duplicate_scene")
    def test_whole_batch_context_preserves_guided_inputs_and_all_settings(self):
        data = draft(amount=3, source_mode="guided", inputs="sitting on a red couch reading a book\nlying on floor",
                     constraints="No outdoor scenes; only neutral expressions; same outfit in every image.",
                     coverage_enabled=True, variety="Wide", target="Ideogram4", visual_style="Custom",
                     custom_style="Ink drawing", trigger_type="Custom", custom_type="A recurring adult character")
        coverage = effective_coverage_plan(data)
        instruction = scene_planner_instruction(data, coverage, "gemma")
        context = json.loads(instruction.user_message)
        for key in ("amount", "subject", "source_mode", "trigger_type", "custom_type", "visual_style",
                    "custom_style", "variety", "constraints"):
            self.assertEqual(context[key], data[key])
        self.assertEqual(context["assignments"], coverage["plan"])
        self.assertEqual(context["assignments"][2]["input"], context["assignments"][0]["input"])
        self.assertNotIn("target_context", context)
        self.assertNotIn("subject_definition", context)
        self.assertNotIn(data["trigger"], instruction.user_message)
        self.assertEqual(instruction.model_family, "gemma")
        self.assertIn("input is authoritative", instruction.system_message)
        self.assertIn("Do not generate finished image prompts", instruction.system_message)
        self.assertIn("constraints", instruction.system_message)
        for key in ("trigger_at_start", "trigger_connected", "director_preset", "results", "quality_report"):
            self.assertNotIn(key, context)
        self.assertNotIn("high_level_description", instruction.system_message)
        other = scene_planner_instruction({**data, "target": "Generic"}, coverage, "gemma")
        self.assertEqual(other.system_message, instruction.system_message)
        self.assertEqual(other.user_message, instruction.user_message)

    def test_disabled_coverage_has_no_hidden_facet_assignments(self):
        data = draft()
        coverage = effective_coverage_plan(data)
        coverage["plan"][0]["facets"] = {"setting": "urban street"}
        context = json.loads(scene_planner_instruction(data, coverage).user_message)
        self.assertTrue(all(row["facets"] == {} for row in context["assignments"]))

    def test_guidance_is_type_specific_and_variety_uses_existing_values(self):
        self.assertEqual(set(dataset_prompts.DATASET_TYPES), set(TYPE_GUIDANCE))
        for kind in dataset_prompts.DATASET_TYPES:
            data = draft(trigger_type=kind)
            context = json.loads(scene_planner_instruction(data, effective_coverage_plan(data)).user_message)
            self.assertTrue(context["type_guidance"])
        data = draft(trigger_type="Object / product")
        instruction = scene_planner_instruction(data, effective_coverage_plan(data))
        self.assertIn("Do not impose human poses or expressions", json.loads(instruction.user_message)["type_guidance"])
        for variety in dataset_prompts.DATASET_VARIETY:
            self.assertIn(variety, instruction.system_message)

    def test_strict_schema_accepts_paragraphs_longer_than_old_limit(self):
        rows = [{"index": 1, "idea": "Reading a book", "scene": " ".join(f"detail{index}" for index in range(60))}]
        self.assertGreater(len(rows[0]["scene"]), 200)
        self.assertEqual(validate_scene_plan(json.dumps(rows), 1), rows)

    def test_strict_schema_rejects_invalid_rows_and_containers(self):
        def raw_row(**changes):
            return json.dumps([{"index": 1, "idea": "Reading a book", "scene": "Reading beside a window.", **changes}])
        invalid = [None, "not json", "```json\n[]\n```", "{}", "[]",
                   '[{"index": 1, "index": 1, "idea": "Reading", "scene": "Reading"}]',
                   '[{"index": 1, "idea": "Reading", "idea": "Reading", "scene": "Reading"}]',
                   json.dumps([{"index": 1, "scene": "Old model output missing idea"}]),
                   raw_row(index=True), raw_row(index=2), raw_row(extra=True),
                   raw_row(scene=" "), raw_row(scene=None),
                   raw_row(scene="x" * (MAX_SCENE_CHARACTERS + 1)),
                   raw_row(scene="w " * (MAX_SCENE_WORDS + 1)),
                   raw_row(scene="Reading\nExplanation"), raw_row(scene="```Reading```"),
                   raw_row(idea=""), raw_row(idea=None), raw_row(idea=3),
                   raw_row(idea="x" * (MAX_IDEA_CHARACTERS + 1)),
                   raw_row(idea="w " * (MAX_IDEA_WORDS + 1)),
                   raw_row(idea="Reading\nAnother idea"), raw_row(idea="```Reading```")]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                validate_scene_plan(raw, 1)
        for rows in ([{"index": 1, "idea": "A", "scene": "A"}, {"index": 1, "idea": "B", "scene": "B"}],
                     [{"index": 1, "idea": "A", "scene": " Reading "}, {"index": 2, "idea": "B", "scene": "reading"}]):
            with self.assertRaises(ValueError):
                validate_scene_plan(json.dumps(rows), 2)

    def test_one_repair_then_success(self):
        data, session, progress = draft(), Mock(), []
        session.generate.side_effect = ["invalid", json.dumps(scene_rows())]
        result = ScenePlanner(lambda: None).plan_batch(
            session=session, data=data, coverage=effective_coverage_plan(data), progress=progress.append)
        self.assertEqual(result, scene_rows())
        self.assertEqual(session.generate.call_count, 2)
        first, repair = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(first.user_message, repair.user_message)
        self.assertIn("FORMAT CORRECTION", repair.system_message)
        self.assertEqual(repair.diagnostic_stage, "dataset:scene_planner:repair")

    def test_fallback_preserves_input_after_format_or_transport_failure(self):
        for guided in (False, True):
            for error in ("[]", BackendGenerationError("engine transport failed")):
                data = draft(source_mode="guided" if guided else "random", inputs="lying on floor\nreading")
                session = Mock()
                if isinstance(error, Exception):
                    session.generate.side_effect = error
                else:
                    session.generate.return_value = error
                result = ScenePlanner(lambda: None).plan_batch(
                    session=session, data=data, coverage=effective_coverage_plan(data), progress=lambda _: None)
                self.assertEqual(session.generate.call_count, 2)
                self.assertEqual([row["scene"] for row in result],
                                 ["lying on floor", "reading"] if guided else [data["subject"]] * 2)
                self.assertEqual([row["idea"] for row in result], [row["scene"] for row in result])

    def test_cancellation_is_not_swallowed_as_planner_failure(self):
        class Cancelled(Exception):
            pass
        checkpoint = Mock(side_effect=[None, Cancelled()])
        session, data = Mock(), draft()
        session.generate.return_value = json.dumps(scene_rows())
        with self.assertRaises(Cancelled):
            ScenePlanner(checkpoint).plan_batch(session=session, data=data,
                coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 1)

    def test_instruction_validation_failure_also_retries_then_falls_back(self):
        data, session = draft(), Mock()
        session.validate_instruction.side_effect = BackendGenerationError("unsupported planning response")
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            coverage=effective_coverage_plan(data), progress=lambda _: None)
        self.assertEqual(session.validate_instruction.call_count, 2)
        session.generate.assert_not_called()
        self.assertEqual([row["scene"] for row in rows], [data["subject"]] * 2)

    def test_no_second_planner_and_normal_builder_is_unchanged(self):
        self.assertFalse(hasattr(dataset_prompts, "dataset_plan_instruction"))
        self.assertFalse(hasattr(DatasetService, "_plan"))
        for mode in ("Enhance", "Character", "Photography", "Product", "Archviz", "Image Edit",
                     "Style Transfer", "Dataset Caption", "Video", "Custom"):
            with self.subTest(mode=mode):
                instruction = assemble_instruction(GoatedPrompterRequest(idea="A red bicycle", mode=mode), text_only=True)
                self.assertNotIn("Scene Planner", instruction.system_message)
                self.assertIn("Creativity — Balanced", instruction.system_message)

    def test_pipeline_hands_same_authoritative_scene_to_writer_and_format_retry(self):
        data = draft(amount=1, source_mode="guided", inputs="reading on a red couch", variety="Wide")
        planned = scene_rows(1)
        session = Mock()
        session.generate.side_effect = [json.dumps(planned), '{"prompt":',
                                       "An adult person_token reading on a red couch in soft daylight."]
        backend = Mock(name="scene-test")
        backend.name = "scene-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        request = GoatedPrompterRequest(idea=data["subject"], creativity="Dice")
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                request, data, lambda _: None, lambda _: None)
        calls = [call.args[0] for call in session.generate.call_args_list]
        self.assertEqual(len(calls), 3)
        for writer in calls[1:]:
            self.assertIn(planned[0]["scene"], writer.user_message)
            self.assertIn(planned[0]["idea"], writer.user_message)
            self.assertIn("SCENE PLANNER AUTHORITY", writer.system_message)
            self.assertIn("Creativity — Strict", writer.system_message)
            self.assertIn("Director supplies rendering technique", writer.system_message)
            self.assertIsNone(writer.stream_character_limit)
        self.assertEqual(calls[1].user_message, calls[2].user_message)
        self.assertEqual(result["prompts"][0]["input"], "reading on a red couch")
        self.assertEqual(result["prompts"][0]["idea"], planned[0]["idea"])

    def test_failed_planning_still_completes_dataset_with_original_guided_input(self):
        data = draft(amount=1, source_mode="guided", inputs="lying on floor", coverage_enabled=True)
        session = Mock()
        session.generate.side_effect = ["not json", "[]", "person_token lying on floor."]
        backend = Mock()
        backend.name = "scene-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"]), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 1)
        writer = session.generate.call_args_list[-1].args[0]
        self.assertIn("<scene>\nlying on floor\n</scene>", writer.user_message)
        self.assertIn("COVERAGE ASSIGNMENT", writer.user_message)
        self.assertEqual(result["prompts"][0]["input"], "lying on floor")

    def test_large_batch_can_stream_past_single_prompt_limit_but_remains_bounded(self):
        data = draft(amount=25)
        instruction = scene_planner_instruction(data, effective_coverage_plan(data))
        rows = [{"index": index, "idea": f"Reading book {index}", "scene": " ".join(f"detail{index}x{word}" for word in range(40))}
                for index in range(1, 26)]
        text = json.dumps(rows)
        self.assertGreater(len(text), 7000)
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.__iter__ = Mock(return_value=iter([
            ("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]}) + "\n").encode(),
            b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n',
        ]))
        transport = Mock()
        transport.__enter__ = Mock(return_value=response)
        transport.__exit__ = Mock(return_value=False)
        backend = OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "test",
                                           "_activity_callback": lambda _: None})
        with patch("goated_prompter.backends.openai_compatible.urlopen", return_value=transport):
            self.assertEqual(validate_scene_plan(backend.generate(instruction), 25), rows)
        chunk = {"choices": [{"delta": {"content": "x" * (instruction.stream_character_limit + 1)}, "finish_reason": None}]}
        with self.assertRaisesRegex(BackendGenerationError, "generated characters"):
            backend._stream_response([("data: " + json.dumps(chunk)).encode()], False,
                                     instruction.hard_max_tokens, instruction.stream_character_limit)


if __name__ == "__main__":
    unittest.main()
