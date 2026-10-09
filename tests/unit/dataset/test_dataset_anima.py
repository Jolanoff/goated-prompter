"""Final Anima writer regressions using synthetic checked scenes and responses."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from goated_prompter.backends import openai_compatible as openai
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import PromptInstruction
from goated_prompter.features.dataset.service import DatasetService, dataset_instruction, validate_dataset_draft
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.visible_content import positive_prompt_error
from goated_prompter.features.dataset.plan import scene_plan_signature
from goated_prompter.workflow_output import WorkflowFormatError, normalize_workflow_output
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import saved_scene, valid_draft
from tests.support.backends import ScriptedBackend


SCENE = ("Mira stands on the left in a blue jacket, offering a red ceramic cup with her right hand to "
         "Hana on the right in a green jacket beside a cafe table. Both are adult women with long hair. "
         "A medium two-shot preserves the cup and their hand contact.")
PROMPT = ("2girls, anime, cel_shading\n"
          "Mira: 1girl, long_hair, blue_jacket, standing\n"
          "Hana: 1girl, long_hair, green_jacket, standing\n\n"
          "Mira on the left offers the red ceramic cup to Hana on the right beside the cafe table, her right hand "
          "supporting its base as Hana receives it. The two adult women stand in a medium two-shot that keeps their hand "
          "contact visible, with crisp drawn contours and warm afternoon shading.")
TAG_CYCLE = ("long_hair, blue_jacket, standing, outdoors, sunlight, tree, bench, "
             "ceramic_cup, cafe_table, warm_colors, soft_shadows, medium_shot, drawn_contours, ")
CHARACTER_TRIGGER = ("2 girls, remilia scarlet, touhou, 1girl, red eyes, short hair, blue hair, mob cap, "
                     "bat wings, bat wing, flandre scarlet, touhou, 1girl, red eyes, blonde hair, short hair, "
                     "side ponytail, mob cap, wings, wings, one side up, crystal")


class StreamResponse:
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, text):
        self.text = text
        self.characters = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def __iter__(self):
        for offset in range(0, len(self.text), 128):
            text = self.text[offset:offset + 128]
            self.characters += len(text)
            reason = "stop" if offset + 128 >= len(self.text) else None
            chunk = {"choices": [{"delta": {"content": text}, "finish_reason": reason}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()


class DatasetAnimaTests(unittest.TestCase):
    def setUp(self):
        self.scene = saved_scene(idea="Two adult women pass a cup beside a cafe table.", scene=SCENE)
        self.data = valid_draft(subject=self.scene["idea"], trigger="Mira, Hana", trigger_type="Multiple characters",
            target="Anima", director_preset="general_director", amount=1,
            scene_plan=[self.scene], _confirmed_intent=dataset_understanding_fixture(
                hard=[{"scope": "all_outputs", "text": "Two adult women in anime/manga style."}]))
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        self.request = GoatedPrompterRequest(idea=self.data["subject"], prompt_model="Custom")

    def run_writer(self, outputs):
        backend = ScriptedBackend(outputs)
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                self.request, self.data, lambda _message: None, lambda _result: None)
        return result, backend

    def test_looping_tags_retry_only_writer_and_preserve_the_checked_scene(self):
        looping = "2girls, anime\nMira: " + TAG_CYCLE * 41 + "\nHana: 1girl, green_jacket\nMira offers a cup to Hana."
        self.assertGreater(len(looping), 6000)
        before = deepcopy(self.data)
        result, backend = self.run_writer([looping, PROMPT])
        self.assertEqual(len(backend.calls), 2, "Repeated Anima tags were accepted without a writer correction.")
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["scene_plan"][0]["scene"], SCENE)
        self.assertEqual(result["scene_plan"][0]["self_check"], "PASS")
        self.assertTrue(all(call.diagnostic_stage.startswith("dataset:1") for call in backend.calls))
        self.assertTrue(all(call.user_message == SCENE for call in backend.calls))
        self.assertEqual(self.data, before)

    def test_streaming_tag_loop_stops_early_and_closes_the_response(self):
        looping = "2girls, anime\nMira: " + TAG_CYCLE * 41
        response = StreamResponse(looping)
        backend = openai.OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "synthetic",
            "_activity_callback": lambda _event: None})
        instruction = dataset_instruction(self.request, self.data, 1, plan_item=self.scene)
        with patch.object(openai, "urlopen", return_value=response), \
                patch.object(openai, "log_request"), patch.object(openai, "log_response"), \
                self.assertRaisesRegex(openai.BackendRunawayError, "repetition loop"):
            backend.generate(instruction)
        self.assertLess(response.characters, 2000)
        self.assertTrue(response.closed)

    def test_style_setting_echo_is_corrected_without_replanning_or_losing_the_medium(self):
        result, backend = self.run_writer([PROMPT + "\nThe style is anime/manga.", PROMPT])
        self.assertEqual(len(backend.calls), 2, "Style-setting commentary was accepted as Anima scene content.")
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)
        self.assertIn("anime/manga", self.data["_confirmed_intent"]["hard"][0]["text"])
        self.assertTrue(all(call.user_message == SCENE for call in backend.calls))
        self.assertIn("anime/manga", backend.calls[-1].system_message)

    def test_comma_wrapped_tag_loops_still_require_a_writer_correction(self):
        looping = "2girls, anime\nMira:\n" + TAG_CYCLE.replace(", ", ",\n") * 41
        looping += "\nHana: 1girl, green_jacket\nMira offers a cup to Hana."
        result, backend = self.run_writer([looping, PROMPT])
        self.assertEqual(len(backend.calls), 2, "Newlines hid a repeating tag list from the output guard.")
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)

    def test_flat_character_trigger_uses_existing_anima_adapter_without_extra_blocks(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_connected=True, trigger_at_start=True, expand_trigger=False,
            _confirmed_intent=dataset_understanding_fixture(hard=[
                {"scope": "all_outputs", "text": "Remilia Scarlet and Flandre Scarlet in anime/manga style."}]))
        self.scene["scene"] = ("Remilia Scarlet on the left offers a red ceramic cup to Flandre Scarlet on the right "
                               "in a dimly lit bedroom. A medium two-shot keeps their hand contact visible.")
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        instruction = dataset_instruction(self.request, self.data, 1, plan_item=self.scene)
        message = instruction.system_message
        self.assertNotIn("ANIMA DATASET OUTPUT", message, "A second Anima layout overrides the target adapter.")
        self.assertIn("Do not output or repeat it, rebuild character tag blocks", message)
        self.assertIn("The application inserts the locked trigger unchanged at the beginning", message)
        self.assertNotIn("For Anima, keep character tag blocks", message)
        self.assertNotIn("STYLE EXAMPLE", message, "A full tags-then-prose example contradicts the continuation-only writer.")
        self.assertIn(json.dumps([CHARACTER_TRIGGER]), message)
        self.assertIn("General Director", message)
        self.assertIn("anime/manga", message)
        self.assertEqual(instruction.user_message, self.scene["scene"])
        prompt = CHARACTER_TRIGGER + ", bedroom, ceramic_cup, " + self.scene["scene"]
        result, backend = self.run_writer([prompt])
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], prompt)
        self.assertTrue(prompt.startswith(CHARACTER_TRIGGER))
        self.assertEqual(prompt.count(CHARACTER_TRIGGER), 1)
        self.assertEqual(prompt.count("1girl"), 2)
        self.assertIsNone(positive_prompt_error(prompt, "Anima", (CHARACTER_TRIGGER,)))

    def test_scene_style_commentary_is_corrected_without_losing_the_bedroom_or_replanning(self):
        self.scene["scene"] = SCENE + " In the background is a dimly lit bedroom."
        prompt = PROMPT + " In the background is a dimly lit bedroom."
        for commentary in (
                "The scene is rendered in anime/manga style with distinct line work and shading, set in a dimly lit bedroom.",
                "The anime/manga style is evident in the line work and shading."):
            with self.subTest(commentary=commentary):
                self.scene["scene"] = SCENE + " In the background is a dimly lit bedroom. " + commentary
                self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
                result, backend = self.run_writer([prompt + " " + commentary, prompt])
                self.assertEqual(len(backend.calls), 2, "Anima medium commentary bypassed final validation.")
                self.assertEqual(result["prompts"][0]["prompt"], prompt)
                self.assertTrue(all(call.user_message == self.scene["scene"] for call in backend.calls))
                self.assertIn("Style-setting commentary", backend.calls[-1].system_message)

    def test_shared_tags_in_distinct_character_blocks_are_not_global_duplicates(self):
        shared = ("1girl, long_hair, smile, standing, blue_jacket, green_eyes, white_shirt, "
                  "black_skirt, brown_shoes, hair_ribbon, looking_at_viewer, adult, freckles")
        for separator in ("\n", "\n\n", ", ", "; "):
            with self.subTest(separator=separator):
                prompt = "3girls, anime\n" + separator.join(f"{name}: {shared}" for name in ("Mira", "Hana", "Tala"))
                self.assertIsNone(positive_prompt_error(prompt, "Anima"))

    def test_supported_quality_tags_weights_and_character_bindings_survive_every_length(self):
        prompt = "masterpiece, best quality, score_9, " + PROMPT.replace(
            "blue_jacket", "(blue_jacket:1.2)").replace("green_jacket", "(green_jacket:1.1)")
        for length in ("Short", "Medium", "Detailed", "Maximum Detail"):
            with self.subTest(length=length):
                self.data["length"] = length
                self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
                result, backend = self.run_writer([prompt] * 4)
                self.assertEqual(len(backend.calls), 1)
                self.assertEqual(result["prompts"][0]["prompt"], prompt)
                self.assertEqual(result["scene_plan"][0]["scene"], SCENE)

    def test_literal_style_text_and_exact_trigger_wording_are_not_style_metadata(self):
        for kind in ("lettering", "trigger"):
            with self.subTest(kind=kind):
                if kind == "lettering":
                    literal = "Title; The style is anime/manga"
                    self.scene["scene"] = SCENE + f' A sign reads "{literal}".'
                    prompt = PROMPT + f' A sign reads "{literal}".'
                else:
                    self.scene["scene"] = SCENE
                    self.data["trigger"] = "The style is anime/manga"
                    prompt = PROMPT + "\n" + self.data["trigger"] + "."
                self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
                result, backend = self.run_writer([prompt] * 4)
                self.assertEqual(len(backend.calls), 1)
                self.assertEqual(result["prompts"][0]["prompt"], prompt)

    def test_streaming_preserves_an_exact_1000_character_trigger_even_when_it_contains_repeated_tags(self):
        trigger = ("Mira, Hana, " + TAG_CYCLE * 6).ljust(1000, "x")
        self.assertEqual(len(trigger), 1000)
        prompt = trigger + "\n" + PROMPT
        response = StreamResponse(prompt)
        data = {**self.data, "trigger": trigger}
        instruction = dataset_instruction(self.request, data, 1, plan_item=self.scene)
        backend = openai.OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "synthetic",
            "_activity_callback": lambda _event: None})
        with patch.object(openai, "urlopen", return_value=response), \
                patch.object(openai, "log_request"), patch.object(openai, "log_response"):
            self.assertEqual(backend.generate(instruction), prompt)
        self.assertTrue(response.closed)
        self.assertEqual(response.characters, len(prompt))

    def test_permanent_repetition_failure_is_bounded_and_never_publishes_bad_prompts(self):
        looping = "Mira: " + TAG_CYCLE * 41 + "\nHana waits."
        before = deepcopy(self.data)
        result, backend = self.run_writer([looping] * 4)
        self.assertEqual(len(backend.calls), 4)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["prompts"], [])
        self.assertEqual(result["scene_plan"][0]["scene"], SCENE)
        self.assertEqual(result["scene_plan"][0]["self_check"], "PASS")
        self.assertEqual(result["scene_plan"][0]["scene_status"], "valid")
        self.assertEqual(result["scene_plan"][0]["failure_stage"], "prompt")
        self.assertTrue(all(call.diagnostic_stage.startswith("dataset:1") for call in backend.calls))
        self.assertEqual(self.data, before)

    def test_a_prompt_wrapper_cannot_hide_looping_tags_from_final_validation(self):
        looping = "Mira: " + TAG_CYCLE * 41 + "\nHana waits."
        result, backend = self.run_writer([json.dumps({"prompt": looping}), PROMPT])
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)

    def test_structured_planning_source_is_not_subject_to_anima_tag_block_rules(self):
        source = json.dumps({"hard": [{"scope": "all_outputs", "text": TAG_CYCLE * 18}], "soft": [], "free": []})
        response = StreamResponse(source)
        instruction = PromptInstruction("Return the approved source as JSON.", "Synthetic source.",
            diagnostic_stage="dataset:understanding", hard_max_tokens=3072, json_output=True)
        backend = openai.OpenAICompatibleBackend({"base_url": "http://localhost:8189/v1", "model": "synthetic",
            "_activity_callback": lambda _event: None})
        with patch.object(openai, "urlopen", return_value=response), \
                patch.object(openai, "log_request"), patch.object(openai, "log_response"):
            self.assertEqual(backend.generate(instruction), source)
        self.assertTrue(response.closed)

    def test_anima_accepts_100_tags_but_rejects_101_without_counting_scene_commas(self):
        prose = ('Mira hands the red cup to Hana, who stands beside the table, under warm light. '
                 'A sign reads "' + ", ".join(f"word{index}" for index in range(120)) + '".')
        for separator in (", ", ",\n"):
            with self.subTest(separator=separator):
                tags = separator.join(f"tag_{index}" for index in range(100))
                prompt = tags + ", " + prose
                self.assertEqual(normalize_workflow_output(prompt, "Anima"), prompt)
                overflow = tags + ", (extra_tag:1.2), " + prose
                with self.assertRaisesRegex(WorkflowFormatError, "100 tags"):
                    normalize_workflow_output(json.dumps({"prompt": overflow}), "Anima")
                self.assertEqual(normalize_workflow_output(overflow, "Krea 2"), overflow)

    def test_locked_character_tags_are_inserted_by_the_app_when_model_only_writes_scene(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_at_start=True, trigger_connected=True, expand_trigger=False)
        self.scene["scene"] = ("Remilia Scarlet on the left offers a red ceramic cup to Flandre Scarlet on the right "
                               "in a dimly lit bedroom. Their hand contact is visible in a medium two-shot.")
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        before = deepcopy(self.data)
        body = "bedroom, ceramic_cup, " + self.scene["scene"]
        result, backend = self.run_writer([body] * 4)
        self.assertEqual(len(backend.calls), 1, "The model should not need to reproduce a locked prefix.")
        self.assertEqual(result["prompts"][0]["prompt"], CHARACTER_TRIGGER + ", " + body)
        self.assertIn("The application inserts the locked trigger", backend.calls[0].system_message)
        self.assertIn("Do not output or repeat it", backend.calls[0].system_message)
        self.assertEqual(self.data, before)

    def test_tag_limit_includes_app_inserted_prefix_and_correction_only_retries_writer(self):
        self.data.update(trigger=", ".join(f"t{index}" for index in range(99)), trigger_at_start=True)
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        result, backend = self.run_writer(["ceramic_cup, warm_light, " + SCENE, "ceramic_cup, " + SCENE] * 2)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["prompts"][0]["prompt"], self.data["trigger"] + ", ceramic_cup, " + SCENE)
        self.assertIn("100 tags", backend.calls[-1].system_message)
        self.assertTrue(all(call.user_message == SCENE for call in backend.calls))

    def test_oversized_anima_source_tags_are_rejected_before_generation_without_changing_saved_text(self):
        data = {**self.data, "trigger": ", ".join(f"t{index}" for index in range(101)), "trigger_at_start": True}
        saved = validate_dataset_draft(data)
        self.assertEqual(saved["trigger"], data["trigger"])
        with self.assertRaisesRegex(ValueError, "100 tags"):
            validate_dataset_draft(saved, generation=True)

    def test_user_medium_survives_without_a_style_control_for_anima_and_krea(self):
        for target in ("Anima", "Krea 2"):
            instruction = dataset_instruction(self.request, {**self.data, "target": target}, 1, plan_item=self.scene)
            directive = "Render the scene as anime/manga rather than realistic photography."
            self.assertNotIn(directive, instruction.system_message)
            self.assertIn("Two adult women in anime/manga style.", instruction.system_message)
        leaked = PROMPT + " The scene is rendered in a detailed anime style."
        result, backend = self.run_writer([leaked, PROMPT])
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)

    def test_locked_single_name_remains_available_for_natural_scene_prose(self):
        self.data.update(trigger="Mira", trigger_at_start=True)
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        result, backend = self.run_writer([SCENE] * 4)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], "Mira, " + SCENE)

    def test_locked_tag_words_inside_requested_lettering_are_preserved_as_literal_text(self):
        self.data["trigger_at_start"] = True
        self.scene["scene"] = SCENE + ' A sign reads "Mira, Hana".'
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        result, backend = self.run_writer([self.scene["scene"]] * 4)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], 'Mira, Hana, ' + self.scene["scene"])

    def test_nonlocked_anima_settings_still_leave_trigger_placement_to_the_writer(self):
        for patch_data in ({"trigger_at_start": False}, {"trigger_connected": False}, {"expand_trigger": True}):
            with self.subTest(patch_data=patch_data):
                self.data.update({"trigger": "Mira, Hana", "trigger_at_start": True, "trigger_connected": True,
                                  "expand_trigger": False, **patch_data})
                self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
                result, backend = self.run_writer([PROMPT])
                self.assertEqual(result["prompts"][0]["prompt"], PROMPT)
                self.assertNotIn("The application inserts the locked trigger", backend.calls[0].system_message)

    def test_locked_inventory_echo_after_scene_tags_is_rejected_not_published(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_at_start=True)
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        for echo in (CHARACTER_TRIGGER, ", ".join(CHARACTER_TRIGGER.split(", ")[1:])):
            with self.subTest(echo=echo):
                body = "ceramic cup\n\n" + SCENE
                result, backend = self.run_writer(["bedroom, " + echo + "\n\n" + SCENE, body])
                self.assertEqual(len(backend.calls), 2)
                self.assertEqual(result["prompts"][0]["prompt"], CHARACTER_TRIGGER + ", " + body)
                self.assertIn("supplied tags", backend.calls[-1].system_message)

    def test_live_negative_constraint_tags_require_correction_even_without_a_loop(self):
        for tag in ("no cropping", "no camera movement", "no action beyond reading", "no changed wings"):
            with self.subTest(tag=tag):
                result, backend = self.run_writer(["ceramic cup, " + tag + "\n\n" + SCENE, PROMPT])
                self.assertEqual(len(backend.calls), 2)
                self.assertEqual(result["prompts"][0]["prompt"], PROMPT)
        self.assertIsNone(positive_prompt_error('no bra\n\nMira wears a jacket.', "Anima"))
        self.assertIsNone(positive_prompt_error('no cropping\n\nMira waits.', "Anima", ("no cropping",)))

    def test_100_tags_allow_short_scene_clause_and_long_spaced_tag_cannot_hide_overflow(self):
        tags = ", ".join(f"tag{index}" for index in range(100))
        for separator in (", ", "\n\n"):
            prompt = tags + separator + "Mira lifts the cup, while Hana watches from the table."
            self.assertEqual(normalize_workflow_output(prompt, "Anima"), prompt)
        prompt = "zero two (darling in the franxx), " + tags + "\n\nMira waits."
        with self.assertRaisesRegex(WorkflowFormatError, "100 tags"):
            normalize_workflow_output(prompt, "Anima")

    def test_locked_writer_finishes_with_positive_continuation_boundary_guidance(self):
        self.data["trigger_at_start"] = True
        instruction = dataset_instruction(self.request, self.data, 1, plan_item=self.scene)
        self.assertIn("Separate the scene tags from the prose with a blank line", instruction.system_message)
        self.assertIn("Apply preservation constraints silently", instruction.system_message)
        self.assertIn("a few useful scene tags", instruction.system_message)

    def test_supplied_named_blocks_are_all_counted_across_blank_lines(self):
        tags = lambda amount: ", ".join(f"t{index}" for index in range(amount))
        trigger = "Mira: " + tags(50) + "\n\nHana: " + tags(51)
        data = {**self.data, "trigger": trigger, "trigger_at_start": True}
        self.assertLess(len(trigger), 1000)
        self.assertEqual(validate_dataset_draft(data)["trigger"], trigger)
        with self.assertRaisesRegex(ValueError, "100 tags"):
            validate_dataset_draft(data, generation=True)

    def test_comma_separated_character_name_starts_scene_only_prose_not_a_tag_inventory(self):
        self.data["trigger_at_start"] = True
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        body = "Mira, seated on the left, offers the cup to Hana on the right beside the table."
        result, backend = self.run_writer([body] * 4)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], "Mira, Hana, " + body)

    def test_visual_confusion_instruction_is_not_a_positive_scene_tag(self):
        result, backend = self.run_writer(["reading, no visual confusion\n\n" + SCENE, PROMPT])
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["prompts"][0]["prompt"], PROMPT)

    def test_locked_inventory_is_not_recreated_as_appearance_prose(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_at_start=True)
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        inventory_prose = ("Remilia Scarlet on the left has red eyes, short blue hair, a mob cap and bat wings. "
                           "Flandre Scarlet on the right has red eyes, short blonde hair in a side ponytail, a mob cap and crystal wings. ")
        body = "reading, open book\n\nRemilia Scarlet on the left reads with Flandre Scarlet on the right at a wooden table."
        result, backend = self.run_writer(["reading, open book\n\n" + inventory_prose + SCENE, body])
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result["prompts"][0]["prompt"], CHARACTER_TRIGGER + ", " + body)
        self.assertIn("appearance inventory", backend.calls[-1].system_message)

    def test_locked_appearance_facts_in_requested_lettering_remain_literal(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_at_start=True)
        lettering = "red eyes, blue hair, mob cap, bat wings, blonde hair, side ponytail, crystal"
        self.scene["scene"] = SCENE + f' A sign reads "{lettering}".'
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        body = "reading, open book\n\n" + self.scene["scene"]
        result, backend = self.run_writer([body] * 4)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], CHARACTER_TRIGGER + ", " + body)

    def test_locked_traits_with_actual_scene_roles_are_not_an_appearance_list(self):
        self.data.update(trigger=CHARACTER_TRIGGER, trigger_at_start=True)
        scene = ("Remilia's red eyes follow the text. Her short hair slips beneath her mob cap while blue hair catches light. "
                 "Her bat wings fold behind the chair. Flandre's blonde hair and side ponytail hover near the book as her wings tilt outward.")
        self.scene["scene"] = scene
        self.data["scene_plan_signature"] = scene_plan_signature(self.data, dataset_assignments(self.data))
        body = "reading, open book\n\n" + scene
        result, backend = self.run_writer([body] * 4)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["prompts"][0]["prompt"], CHARACTER_TRIGGER + ", " + body)
