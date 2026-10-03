"""Dataset-only planning contracts, schema, retries, fallback and writer handoff."""

from contextlib import contextmanager
import json
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.dataset import DatasetService, default_dataset_draft, validate_dataset_draft, _parse_deep_review
from goated_prompter.dataset_assignments import dataset_assignments
from goated_prompter.prompting import dataset as dataset_prompts
from goated_prompter.prompting.scene_planner import (scene_planner_instruction, MAX_SCENE_CHARACTERS,
                                                    MAX_SCENE_WORDS, MAX_IDEA_CHARACTERS, MAX_IDEA_WORDS, TYPE_GUIDANCE)
from goated_prompter.scene_planner import (ScenePlanner, validate_scene_plan, scene_plan_signature,
                                         reusable_scene_plan, validate_saved_scene_plan)


def draft(**changes):
    return {**default_dataset_draft(), "amount": 2, "trigger": "person_token",
            "subject": "An adult character reading at home.", **changes}


def scene_rows(amount=2):
    from tests.test_dataset_geometry import character_geometry
    return [{"index": index, "idea": f"Reading a different book {index}",
             "scene": f"Reading on a red couch beside window {index}, face visible in soft daylight.",
             "geometry": character_geometry(action_focus="reading")}
            for index in range(1, amount + 1)]


def with_staging(rows, dataset_type="Character"):
    from tests.test_dataset_geometry import character_geometry
    from goated_prompter.dataset_staging import CHARACTER_REQUIRED_FIELDS
    return [{**row, "geometry": {key: value for key, value in character_geometry().items() if key in CHARACTER_REQUIRED_FIELDS}
             if dataset_type == "Character" else {"framing": "full_subject", "camera_azimuth": "front"}} for row in rows]


class ScenePlannerTests(unittest.TestCase):
    def test_planning_process_separates_concept_ideas_scenes_and_silent_audit(self):
        data = draft()
        system = scene_planner_instruction(data, dataset_assignments(data)).system_message
        steps = ["STEP 1 — UNDERSTAND", "STEP 2 — GENERATE", "STEP 3 — COMPOSE",
                 "STEP 4 — CHECK GEOMETRY", "STEP 5 — REPAIR", "STEP 6 — RETURN"]
        self.assertEqual([system.index(step) for step in steps], sorted(system.index(step) for step in steps))
        for heading in ("IDEA DUPLICATION CHECK", "SCENE GEOMETRY AND VISIBILITY", "VISIBLE DETAIL RULE",
                        "ACTION LOGIC", "SCENE COHERENCE AUDIT"):
            self.assertIn(heading, system)
        self.assertIn("Do not mechanically use every category", system)
        self.assertIn("fields supplied by the selected staging schema", system)
        self.assertIn("normally 3–15 words", system)
        self.assertIn("14. NO STAGING HACKS", system)
        self.assertIn('"geometry" (object)', system)

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
                rows = with_staging(rows, kind)
                session = Mock()
                session.generate.return_value = json.dumps(rows)
                planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                    assignments=dataset_assignments(data), progress=lambda _: None)
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
        rows = with_staging(rows)
        session = Mock()
        session.generate.side_effect = [json.dumps(rows[start:start + 4]) for start in range(0, 10, 4)]
        data = draft(subject="woman doing funny stuff", amount=10)
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(len(planned), 10)
        self.assertEqual(len({row["idea"] for row in planned}), 10)
        self.assertTrue(all(row["idea"] != row["scene"] for row in planned))
        self.assertEqual(session.generate.call_count, 3)

    def test_idea_similarity_distinguishes_broad_concept_from_expression_scope(self):
        from goated_prompter.dataset_quality import analyze_idea_diversity
        rows = [{"index": i, "idea": idea} for i, idea in enumerate(
            ("laughing indoors", "laughing outside", "laughing at night"), 1)]
        quality = analyze_idea_diversity(draft(subject="woman doing funny stuff"), rows)
        self.assertLess(quality["uniqueness"], 100)
        faces = [{"index": i, "idea": idea} for i, idea in enumerate(
            ("funny face with tongue out", "funny face crossing eyes", "funny face puffing cheeks"), 1)]
        self.assertEqual(analyze_idea_diversity(draft(subject="woman doing funny stuff"), faces)["uniqueness"], 100)
        self.assertEqual(analyze_idea_diversity(draft(subject="woman doing funny facial expressions"), faces)["uniqueness"], 100)
        self.assertEqual(analyze_idea_diversity(draft(source_mode="guided"), faces)["uniqueness"], 100)

    def test_guided_clown_costume_stays_an_idea_and_not_another_activity(self):
        data = draft(amount=1, source_mode="guided", inputs="clown costume")
        rows = [{"index": 1, "idea": "Wearing a ridiculous clown costume",
                 "scene": "She stands in a clown costume in full-body front three-quarter view, balanced with hands on hips and an intentionally deadpan expression."}]
        session = Mock()
        session.generate.return_value = json.dumps(rows)
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertIn("clown costume", planned[0]["idea"])
        self.assertIn("clown costume", planned[0]["scene"])
        self.assertNotIn("juggling", planned[0]["scene"])
        self.assertNotIn("clown costume", session.generate.call_args.args[0].system_message.casefold())

    def test_legacy_plans_remain_loadable_but_are_not_reused_without_ideas(self):
        data = draft(scene_plan=[{"index": i, "input": "", "scene": f"Reading beside window {i}."} for i in (1, 2)])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        self.assertEqual(validate_dataset_draft(data)["scene_plan"], data["scene_plan"])
        self.assertIsNone(reusable_scene_plan(data, dataset_assignments(data)))
        data["results"] = [{"index": 1, "input": "", "scene": "An old scene.", "prompt": "An old prompt."}]
        self.assertNotIn("idea", validate_dataset_draft(data)["results"][0])

    def test_geometry_hints_flag_explicit_conflicts_without_policing_valid_poses(self):
        from goated_prompter.dataset_quality import explicit_geometry_issues, analyze_dataset_quality
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
        instruction = scene_planner_instruction(data, dataset_assignments(data))
        for section in ("SCENE IDEA FIRST", "VISUAL DEPICTABILITY", "ONE PRIMARY EVENT",
                        "CONTROLLED VARIATION", "PRESENTATION SUPPORTS THE IDEA"):
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
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("woman" in row["scene"].lower() for row in rows))
        from goated_prompter.dataset_quality import analyze_scene_diversity
        self.assertEqual(analyze_scene_diversity(rows)["uniqueness"], 100)

    def test_guided_plan_retains_original_action_and_named_objects(self):
        data = draft(amount=1, source_mode="guided", inputs="sitting on a red couch reading a book")
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "idea": "Sitting on a red couch reading a book",
            "scene": "Sitting sideways on a red couch reading an open book, with a relaxed posture beside a window."}])
        rows = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        context = json.loads(session.generate.call_args.args[0].user_message)
        self.assertEqual(context["assignments"][0]["input"], data["inputs"])
        for anchor in ("sitting", "red couch", "reading", "book"):
            self.assertIn(anchor, rows[0]["scene"].lower())

    def test_plan_signature_excludes_writer_settings_and_invalidates_semantic_changes(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        assignments = dataset_assignments(data)
        data["scene_plan_signature"] = scene_plan_signature(data, assignments)
        self.assertEqual(reusable_scene_plan(data, assignments), data["scene_plan"])
        for changes in ({"target": "Anima"}, {"target": "Ideogram4", "length": "Detailed"},
                        {"director_preset": "other"}, {"trigger": "new_token", "trigger_at_start": True}):
            changed = {**data, **changes}
            self.assertEqual(reusable_scene_plan(changed, dataset_assignments(changed)), data["scene_plan"])
        for changes in ({"subject": "A dog having adventures"}, {"inputs": "running"}, {"amount": 3},
                        {"constraints": "No outdoors"}, {"variety": "Wide"}, {"trigger_type": "Animal"},
                        {"visual_style": "Illustration"}):
            changed = {**data, **changes}
            self.assertIsNone(reusable_scene_plan(changed, dataset_assignments(changed)))
        changed_assignments = dataset_assignments(data)
        changed_assignments[0]["input"] = "a different guided idea"
        self.assertIsNone(reusable_scene_plan(data, changed_assignments))

    def test_scene_plan_and_new_and_legacy_results_roundtrip(self):
        data = draft(scene_plan=[{**row, "input": ""} for row in scene_rows()])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
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
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
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
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
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
        data = draft(amount=1)
        chunk = [{"index": 1, "input": "", "scene": "Chasing a runaway shopping cart across a parking lot.",
                  "prompt": "A smiling woman portrait in a supermarket."}]
        instruction = dataset_prompts.deep_review_instruction(data, chunk)
        self.assertIn(chunk[0]["scene"], instruction.user_message)
        self.assertIn(chunk[0]["prompt"], instruction.user_message)
        self.assertIn("scene_drift", instruction.system_message)
        self.assertNotIn("coverage_mismatch", instruction.system_message)
        result = _parse_deep_review(json.dumps([{"index": 1, "issues": [{"category": "scene_drift",
            "severity": "error", "message": "The chase was replaced by a portrait."}]}]), chunk)
        self.assertEqual(result[0]["issues"][0]["code"], "deep_scene_drift")
        legacy = [{key: value for key, value in chunk[0].items() if key != "scene"}]
        self.assertIn("legacy result", dataset_prompts.deep_review_instruction(data, legacy).user_message)

    def test_quality_checks_scene_similarity_without_planned_coverage(self):
        from goated_prompter.dataset_quality import analyze_dataset_quality, analyze_scene_diversity
        data = draft()
        results = [{"index": 1, "input": "", "scene": "A woman stands laughing in a bedroom under soft daylight.",
                    "prompt": "person_token enjoys a well-described clear scene at home."},
                   {"index": 2, "input": "", "scene": "A woman stands laughing in a kitchen under warm light.",
                    "prompt": "An entirely different written prompt of person_token elsewhere."}]
        report = analyze_dataset_quality(data, results)
        self.assertNotIn("planned_coverage", report["metrics"])
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
                     variety="Wide", target="Ideogram4", visual_style="Custom",
                     custom_style="Ink drawing", trigger_type="Custom", custom_type="A recurring adult character")
        assignments = dataset_assignments(data)
        instruction = scene_planner_instruction(data, assignments, "gemma")
        context = json.loads(instruction.user_message)
        for key in ("amount", "subject", "source_mode", "trigger_type", "custom_type", "visual_style",
                    "custom_style", "variety", "constraints"):
            self.assertEqual(context[key], data[key])
        self.assertEqual(context["assignments"], assignments)
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
        other = scene_planner_instruction({**data, "target": "Generic"}, assignments, "gemma")
        self.assertEqual(other.system_message, instruction.system_message)
        self.assertEqual(other.user_message, instruction.user_message)

    def test_assignments_do_not_prescribe_scene_facets(self):
        data = draft()
        context = json.loads(scene_planner_instruction(data, dataset_assignments(data)).user_message)
        self.assertTrue(all(set(row) == {"index", "input"} for row in context["assignments"]))

    def test_guidance_is_type_specific_and_variety_uses_existing_values(self):
        self.assertEqual(set(dataset_prompts.DATASET_TYPES), set(TYPE_GUIDANCE))
        for kind in dataset_prompts.DATASET_TYPES:
            data = draft(trigger_type=kind)
            context = json.loads(scene_planner_instruction(data, dataset_assignments(data)).user_message)
            self.assertTrue(context["type_guidance"])
        data = draft(trigger_type="Object / product")
        instruction = scene_planner_instruction(data, dataset_assignments(data))
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
                    raw_row(scene="```Reading```"),
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
            session=session, data=data, assignments=dataset_assignments(data), progress=progress.append)
        self.assertEqual(result, scene_rows())
        self.assertEqual(session.generate.call_count, 2)
        first, repair = [call.args[0] for call in session.generate.call_args_list]
        repair_context = json.loads(repair.user_message)
        self.assertEqual(repair_context.pop("previous_response"), "invalid")
        self.assertEqual(json.loads(first.user_message), repair_context)
        self.assertIn("FORMAT CORRECTION", repair.system_message)
        self.assertEqual(repair.diagnostic_stage, "dataset:scene_planner:repair")

    def test_duplicate_scenes_are_allowed_only_for_the_same_nonempty_guided_input(self):
        rows = [{"index": index, "idea": "Reading on a red couch", "scene": "She sits on a red couch reading a book."}
                for index in (1, 2)]
        raw = json.dumps(rows)
        self.assertEqual(validate_scene_plan(raw, 2, guided_inputs=["reading on a red couch", " reading  on a red couch "]), rows)
        for inputs in (None, ["reading", "park"], ["", ""], ["reading", ""],
                       ["a sign reading HELLO", "a sign reading hello"]):
            with self.subTest(inputs=inputs), self.assertRaisesRegex(ValueError, "identical scenes"):
                validate_scene_plan(raw, 2, guided_inputs=inputs)
        for inputs in ([], ["reading"], ["reading", None], "reading"):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                validate_scene_plan(raw, 2, guided_inputs=inputs)

    def test_guided_repetition_does_not_bypass_schema_or_positive_content_checks(self):
        rows = [{"index": index, "idea": "Reading", "scene": "Reading on a red couch."} for index in (1, 2)]
        for changes in ({"scene": "Reading, no other people."}, {"idea": ""}, {"index": 1}, {"extra": "field"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                invalid = [rows[0], {**rows[1], **changes}]
                validate_scene_plan(json.dumps(invalid), 2, guided_inputs=["reading", "reading"])

    def test_six_guided_fragments_cycle_to_ten_expanded_scenes_without_fallback(self):
        inputs = ["outdoor, wearing only a tshirt,", "indoors", "sitting on the table", "park", "beach", "zoo"]
        examples = [
            ("Balancing a toy flamingo outdoors", "Outdoors, she wears only a t-shirt while holding a toy flamingo balanced on her head, seen from the front with both arms raised."),
            ("Juggling rubber chickens indoors", "She juggles rubber chickens indoors beside a sofa, gaze tracking a falling chicken with her hands beneath it."),
            ("Eating spaghetti with chopsticks while sitting on a table", "She sits on a wooden table with a bowl of spaghetti beside her, lifting tangled noodles with chopsticks and watching them slip."),
            ("Chasing a runaway hat in a park", "She runs through a park after a windblown hat, leaning forward with her gaze on the hat and arms reaching toward it."),
            ("Building a lopsided sandcastle at the beach", "She kneels on a beach beside a lopsided sandcastle, holding a small bucket and grinning at its crooked tower."),
            ("Imitating a giraffe's tall stance at the zoo", "She stands near a giraffe enclosure at the zoo, stretching upward on tiptoes with an amused expression while the giraffe towers beside her."),
        ]
        rows = [{"index": index + 1, "idea": examples[index % 6][0], "scene": examples[index % 6][1]}
                for index in range(10)]
        rows = with_staging(rows)
        data = draft(amount=10, source_mode="guided", subject="A woman doing funny stuff",
                     inputs="\n".join(inputs), constraints="The woman must be the same in every prompt.")
        session, progress = Mock(), []
        session.generate.side_effect = [json.dumps(rows[start:start + 4]) for start in range(0, 10, 4)]
        planned = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=progress.append)
        self.assertEqual(planned, rows)
        self.assertEqual(session.generate.call_count, 3)
        self.assertFalse(any("failed" in message or "unavailable" in message for message in progress))
        contexts = [json.loads(call.args[0].user_message) for call in session.generate.call_args_list]
        self.assertEqual([row["input"] for context in contexts for row in context["assignments"]], inputs + inputs[:4])
        self.assertNotEqual(planned[2]["scene"], inputs[2])
        self.assertNotEqual(planned[3]["idea"], inputs[3])

    def test_guided_instructions_fill_missing_actions_without_spreading_local_clothing(self):
        data = draft(amount=2, source_mode="guided", subject="A woman doing funny stuff",
                     inputs="outdoors wearing only a t-shirt\nindoors", constraints="Same woman in every image.")
        instruction = scene_planner_instruction(data, dataset_assignments(data))
        self.assertIn("GUIDED ASSIGNMENT MODE", instruction.system_message)
        self.assertIn("full scene OR a partial anchor", instruction.system_message)
        self.assertIn("Creativity fills gaps, not overrides", instruction.system_message)
        self.assertIn("Do not copy one line's clothing restrictions", instruction.system_message)
        self.assertIn("Exact repeated ideas/scenes for the", instruction.system_message)
        context = json.loads(instruction.user_message)
        self.assertEqual(context["assignments"][1]["input"], "indoors")
        writer = dataset_prompts.dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 2,
            plan_item={"input": "indoors", "idea": "Juggling indoors", "scene": "She juggles rubber chickens indoors."})
        self.assertNotIn("wearing only a t-shirt", writer.user_message)
        self.assertIn("local to this item", writer.user_message)
        random = scene_planner_instruction({**data, "source_mode": "random"}, dataset_assignments({**data, "source_mode": "random"}))
        self.assertNotIn("GUIDED ASSIGNMENT MODE", random.system_message)

    def test_different_guided_inputs_and_random_repetition_still_trigger_repair(self):
        from tests.test_dataset_geometry import character_geometry
        repeated = [{"index": index, "idea": "Reading a book", "scene": "She reads a book sitting on a red couch."}
                    for index in (1, 2)]
        repeated = with_staging(repeated)
        repaired = {**repeated[1], "scene": "She reads a book seated on a park bench.",
                    "geometry": character_geometry(action_focus="reading")}
        for source, inputs in (("guided", "reading\npark"), ("random", "reading\nreading")):
            with self.subTest(source=source):
                data = draft(source_mode=source, inputs=inputs)
                session = Mock()
                session.generate.side_effect = [json.dumps(repeated), json.dumps([repaired])]
                result = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
                    assignments=dataset_assignments(data), progress=lambda _: None)
                self.assertEqual(result, [repeated[0], repaired])
                self.assertEqual(session.generate.call_count, 2)
                self.assertEqual(json.loads(session.generate.call_args.args[0].user_message)["indexes"], [2])
                self.assertEqual(result[1]["idea"], repeated[1]["idea"])

    def test_cycled_guided_plan_is_persisted_and_reused_by_writer_not_raw_fallback(self):
        data = draft(amount=3, source_mode="guided", inputs="sitting on a table\npark")
        rows = [
            {"index": 1, "idea": "Sitting on a table juggling oranges", "scene": "She sits on a table juggling oranges, eyes tracking the fruit."},
            {"index": 2, "idea": "Chasing a hat in a park", "scene": "She runs through a park after a windblown hat, gaze focused on it."},
            {"index": 3, "idea": "Sitting on a table juggling oranges", "scene": "She sits on a table juggling oranges, eyes tracking the fruit."},
        ]
        rows = with_staging(rows)
        session = Mock()
        session.generate.side_effect = [json.dumps(rows)] + ["person_token in a coherent funny scene." for _ in rows]
        backend = Mock()
        backend.name = "guided-cycle-test"
        @contextmanager
        def generation_session():
            yield session
        backend.generation_session = generation_session
        request = GoatedPrompterRequest(idea=data["subject"])
        progress, partial = [], []
        with patch("goated_prompter.dataset.create_backend", return_value=backend):
            service = DatasetService({"backend": "mock"}, lambda: None)
            planned = service.run(request, data, progress.append, partial.append, scenes_only=True)
            data.update(scene_plan=planned["scene_plan"], scene_plan_signature=planned["scene_plan_signature"])
            data = validate_dataset_draft(data)
            self.assertEqual(data["scene_plan"][0]["scene"], rows[0]["scene"])
            self.assertEqual(reusable_scene_plan(data, dataset_assignments(data)), data["scene_plan"])
            final = service.run(request, data, progress.append, partial.append)
        self.assertEqual(session.generate.call_count, 4)  # One planner + three writers, no repair.
        self.assertFalse(any("unavailable" in message for message in progress))
        self.assertEqual(final["scene_plan"], [{**row, "prompt_status": "valid"} for row in data["scene_plan"]])
        for index, (row, call) in enumerate(zip(rows, session.generate.call_args_list[1:])):
            writer = call.args[0]
            self.assertIn(row["idea"], writer.user_message)
            self.assertIn(row["scene"], writer.user_message)
            self.assertEqual(final["prompts"][index]["scene"], row["scene"])
            self.assertEqual(final["prompts"][index]["input"], "sitting on a table" if index in (0, 2) else "park")
        self.assertEqual(partial[0]["scene_plan"], data["scene_plan"])

    def test_format_or_transport_failure_is_bounded_and_retains_guided_assignment(self):
        for guided in (False, True):
            for error in ("[]", BackendGenerationError("engine transport failed")):
                data = draft(source_mode="guided" if guided else "random", inputs="lying on floor\nreading")
                session = Mock()
                if isinstance(error, Exception):
                    session.generate.side_effect = error
                else:
                    session.generate.return_value = error
                result = ScenePlanner(lambda: None).plan_batch(
                    session=session, data=data, assignments=dataset_assignments(data), progress=lambda _: None)
                self.assertEqual(session.generate.call_count, 8)
                self.assertTrue(all(row["scene_status"] == "failed" and row["failure_reason"] for row in result))
                contexts = [json.loads(call.args[0].user_message) for call in session.generate.call_args_list]
                if guided:
                    self.assertTrue(all(row["input"] == ("lying on floor" if row["index"] == 1 else "reading")
                                        for context in contexts for row in context["assignments"]))

    def test_cancellation_is_not_swallowed_as_planner_failure(self):
        class Cancelled(Exception):
            pass
        checkpoint = Mock(side_effect=[None, Cancelled()])
        session, data = Mock(), draft()
        session.generate.return_value = json.dumps(scene_rows())
        with self.assertRaises(Cancelled):
            ScenePlanner(checkpoint).plan_batch(session=session, data=data,
                assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(session.generate.call_count, 1)

    def test_instruction_validation_failure_is_bounded_per_item(self):
        data, session = draft(), Mock()
        session.validate_instruction.side_effect = BackendGenerationError("unsupported planning response")
        result = ScenePlanner(lambda: None).plan_batch(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertEqual(session.validate_instruction.call_count, 8)
        self.assertTrue(all(row["scene_status"] == "failed" for row in result))
        session.generate.assert_not_called()

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
        data = draft(amount=1, source_mode="guided", inputs="lying on floor")
        session = Mock()
        session.generate.side_effect = ["not json", "[]", json.dumps(with_staging([
            {"index": 1, "idea": "Lying on floor", "scene": "lying on floor"}])), "person_token lying on floor."]
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
        self.assertNotIn("COVERAGE ASSIGNMENT", writer.user_message)
        self.assertEqual(result["prompts"][0]["input"], "lying on floor")

    def test_large_batch_can_stream_past_single_prompt_limit_but_remains_bounded(self):
        data = draft(amount=25)
        instruction = scene_planner_instruction(data, dataset_assignments(data))
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
