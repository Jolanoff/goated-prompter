"""MiniMax contracts with controlled text-engine responses; no media or live APIs."""

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import local_app as local
from tests.helpers import enter_context
from goated_prompter.backends.base import GoatedPrompterBackend, BackendGenerationError
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.minimax import (MiniMaxService, analysis_instruction, default_minimax_draft,
    frame_instruction, generation_instruction, parse_reference_tokens, parse_shot_outline, reference_warnings, requested_spoken_lines,
    validate_analysis, validate_minimax_draft, validate_output)
from goated_prompter.presets import get_director_preset
from goated_prompter.workflow_settings import WorkflowSettingsStore, empty_settings

REQUEST = ("I want the person in <image1> to do the same dancing style and movements as the dancer in <video1>. "
           "Put the person on a rooftop at night with neon city lights behind them. I want energetic electronic music. "
           "Start with a medium full-body shot, then slowly move the camera around the dancer.")
APPLE_REQUEST = ("cartoonish style\n<image1> is mike, its an apple\n<image2> is track, its a bannana\n"
                 "<image3> the background its the street\nstart by apple walking on the street, it steps on dog poop, "
                 "apple looks sad after and walks toward her friend banana\n"
                 "<d>[English] I stepped on poop</d>\nbannana and apple start crying")
APPLE_PLAIN_REQUEST = APPLE_REQUEST.replace("<d>[English] I stepped on poop</d>", "apple says : i stepped on a poop")
APPLE_SHOTS = ("cartoonish style\n<image1> is mike, its an apple\n<image2> is track, its a bannana\n"
               "<image3> the background its the street\n\n<shot1> apple walking on the street, it steps on dog poop,\n"
               "<shot2> apple looks sad after and walks toward her friend banana\n"
               "<shot3>apple says : i stepped on a poop\nbannana and apple start crying")
APPLE_PROMPT = """subject_definitions:
<Subject 1> is the apple character Mike, based on <Picture 1>.
<Subject 2> is the banana friend, based on <Picture 2>.
<Subject 3> is the street setting, based on <Picture 3>.

summary:
[reference generation] In a cartoonish street scene, Mike steps in dog poop, complains to the banana and they cry together.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - retain the apple's referenced appearance.
<Subject 2> (appears in [Shot 1]): fully_preserved - retain the banana's referenced appearance.
<Subject 3> (appears in [Shot 1]): fully_preserved - retain the street's referenced appearance.

detailed_description:
The target video has a cartoonish style.
[Shot 1] <Subject 1> walks along <Subject 3>, steps in dog poop, looks sad, and approaches <Subject 2>. <Subject 1> (S1) says: <d>[English] I stepped on poop</d> Then <Subject 1> and <Subject 2> begin to cry together.

overall_soundscape:
Footsteps and soft crying accompany the street ambience.

non_diegetic_music:
N/A"""
BASE = "integrated_multimodal_description: [Shot 1] A leaf falls onto a quiet path.\n\noverall_soundscape: Wind rustles the branches.\n\nnon_diegetic_music: N/A"
REF = """subject_definitions:
<Subject 1> is the person shown in <Picture 1>, preserving the person's visible identity, appearance and clothing.
<Subject 2> is the dance performance in <Video 1>, supplying only body movement, timing and pose transitions for <Subject 1>.

summary:
[reference generation] <Subject 1> performs the movement of <Subject 2> on a rooftop at night, with neon city lights behind them, in a continuous 15-second shot.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - retain the target person's visible identity, appearance and clothing.
<Subject 2> (appears in [Shot 1]): attribute_transfer - transfer the dance to <Subject 1>, excluding the source dancer's appearance, clothing, environment, camera, lighting and audio.

detailed_description:
The target video uses live-action cinematography on a neon-lit nighttime rooftop.
[Shot 1] A medium full-body composition centers <Subject 1>, with room around their arms and feet for the dance movement supplied by <Subject 2>. The rooftop floor establishes a stable contact plane beneath the dancer, while neon city lights remain behind them. Begin the referenced movement without changing the target person's identity or importing the source video's setting. Over the 15-second clip, the body follows the reference's movement character and pose transitions in a continuous progression, adapting the performed phrase to the available duration rather than squeezing in extra routines. Foot contacts remain grounded as weight shifts follow the referenced performance. The camera arcs slowly around <Subject 1>, keeping their full body in frame while the distant city lights shift gradually in perspective. Let the camera movement remain subordinate to the dance; do not inherit camera motion or framing from the motion source. Rooftop wind and foot contacts stay synchronized with the physical action. As the clip reaches its end, settle the camera into a clear full-body view while the selected movement phrase reaches its natural ending state.

overall_soundscape:
Rooftop wind continues beneath synchronized foot contacts and subtle fabric movement. Distant city traffic remains low in the background.

non_diegetic_music:
Generate an energetic electronic score with a brisk four-on-the-floor kick, crisp hi-hats and a pulsing synthesizer bass. Introduce a bright synth phrase as the dance develops, then resolve it at the 15-second ending without copying reference audio."""


def role(token, *roles):
    return {"token": token, "roles": list(roles), "target": "target person", "transfer": "requested role only",
            "exclude": "unrequested appearance, environment, camera, light and audio"}


def plan_json(*items, first=None, last=None):
    return json.dumps({"references": items, "first_frame": first, "last_frame": last})


DANCE_PLAN = plan_json(role("image1", "identity", "appearance"), role("video1", "dance", "motion"))


def dance_input(**overrides):
    return validate_minimax_draft({"references": ["image1", "video1"], "duration_seconds": 15,
                                  "planning_mode": "Direct",  # Freeze the pre-planning writer/repair contract.
                                  "user_request": REQUEST, **overrides}, generation=True)


class ScriptedBackend(GoatedPrompterBackend):
    name = "scripted"

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.sessions = self.exits = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        try:
            yield self
        finally:
            self.exits += 1

    def generate(self, instruction):
        self.calls.append(instruction)
        self.entered.set()
        if self.block and not self.release.wait(5):
            raise ValueError("Test timeout")
        return next(self.responses)


class MiniMaxContractTests(unittest.TestCase):
    def test_tokens_case_limits_missing_assets_and_draft_tolerance(self):
        self.assertEqual(parse_reference_tokens("<IMAGE1> <video3> <Audio2> <image1>"), ["image1", "video3", "audio2"])
        for token in ("<image10>", "<image0>", "<image01>", "<video4>", "<audio4>"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                parse_reference_tokens(token)
        for duration in (3, 16, True, "10", 4.5):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validate_minimax_draft({"duration_seconds": duration})
        with self.assertRaisesRegex(ValueError, "Register"):
            validate_minimax_draft({"user_request": "Use <image1>"}, generation=True)
        self.assertEqual(validate_minimax_draft({"user_request": "unfinished <image10>"})["user_request"], "unfinished <image10>")
        with self.assertRaises(ValueError):
            validate_minimax_draft({"references": [f"image{i}" for i in range(1, 10)] + ["video1", "video2", "video3", "audio1"]})

    def test_optional_shot_shortcuts_validate_and_allocate_clip_timing(self):
        self.assertEqual(parse_shot_outline("An apple walks", 10), [])
        shots = parse_shot_outline(APPLE_SHOTS, 10)
        self.assertEqual([(shot["start_ms"], shot["end_ms"]) for shot in shots],
                         [(0, 3333), (3333, 6666), (6666, 10000)])
        timed = APPLE_SHOTS.replace("<shot1> apple", "<shot1> 0-3s apple")
        self.assertEqual([(shot["start_ms"], shot["end_ms"]) for shot in parse_shot_outline(timed, 10)],
                         [(0, 3000), (3000, 6500), (6500, 10000)])
        self.assertEqual(parse_shot_outline("<shot1> 0-2.5s Walk. <shot2> 2.5-6s Stop.", 6)[1]["start_ms"], 2500)
        self.assertEqual(requested_spoken_lines(timed), [{"speaker": "apple", "words": "i stepped on a poop"}])
        for request in ("<shot2> hello", "<shot1> hello <shot1> again", "<shot01> hello", "<shot0> hello",
                        "<shotx> hello", "<shot1> hello <shotx> again", "<shot1> 0-3sec hello <shot2> goodbye",
                        "<shot1> hello <shot2> 4-8s goodbye", "<shot1> 0-3s hello",
                        "<shot1> 1-3s hello <shot2> goodbye", "<shot1> 0-3s hello <shot2> 4-10s goodbye",
                        "<shot1> hello <shot2>"):
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate_minimax_draft({"user_request": request}, generation=True)

    def test_image_only_shot_outline_converts_to_guide_fields_and_keeps_speech(self):
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"],
                                       "planning_mode": "Direct",
                                       "user_request": APPLE_SHOTS.replace("<shot1> apple", "<shot1> 0-3s apple")}, generation=True)
        roles = plan_json(role("image1", "character"), role("image2", "character"), role("image3", "environment"))
        plan = validate_analysis(roles, data)
        instruction = generation_instruction(data, plan, get_director_preset(data["director_preset"]), "qwen")
        self.assertIn('"start_ms": 3000', instruction.user_message)
        self.assertIn('"start_ms": 6500', instruction.user_message)
        self.assertIn('"speaker": "apple", "words": "i stepped on a poop"', instruction.user_message)
        result = validate_output(APPLE_PROMPT, data, plan)
        timeline = result.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape:", 1)[0]
        self.assertIn("[Shot 1] apple walking on the street, it steps on dog poop", timeline)
        self.assertIn("[Shot 2] At 00:03.000, apple looks sad", timeline)
        self.assertIn("[Shot 3] At 00:06.500, apple (S1) says: <d>[English] i stepped on a poop</d>", timeline)
        self.assertIn("bannana and apple start crying", timeline)
        self.assertNotIn("<shot", result.lower())
        model = APPLE_PROMPT.replace(
            APPLE_PROMPT.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape:", 1)[0],
            "The target video has a cartoonish style.\n<shot1> <Subject 1> walks along <Subject 3> and steps in dog poop.\n"
            "<shot2> At 00:04.000, <Subject 1> looks sad and approaches <Subject 2>.\n"
            "<shot3> At 00:08.000, <Subject 1> (S1) says: <d>[English] i stepped on a poop</d> "
            "and <Subject 1> and <Subject 2> begin crying.")
        enhanced = validate_output(model, data, plan)
        self.assertIn("[Shot 2] At 00:03.000, <Subject 1> looks sad", enhanced)
        self.assertIn("[Shot 3] At 00:06.500, <Subject 1> (S1) says", enhanced)
        backend = ScriptedBackend(roles, model)
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            generated = MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=APPLE_SHOTS), data, lambda _: None)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(generated["prompt"], enhanced)

    def test_shot_outline_preserves_base_frame_alignment(self):
        request = "Start from <image1>. <shot1> 0-3s Begin walking. <shot2> Continue walking and stop."
        data = validate_minimax_draft({"mode": "I2VA", "references": ["image1"], "user_request": request}, generation=True)
        plan = validate_analysis(plan_json(role("image1", "first frame"), first="image1"), data)
        model = frame_instruction("I2VA", 10) + "\n\n" + BASE
        result = validate_output(model, data, plan)
        self.assertTrue(result.startswith(frame_instruction("I2VA", 10) + "\n\n"))
        self.assertIn("[Shot 2] At 00:03.000, Continue walking and stop.", result)
        self.assertIn("[Shot 1]", result)

    def test_shot_shortcuts_also_work_without_media_references(self):
        request = "A cartoon leaf scene.\n<shot1> 0-2s A leaf falls.\n<shot2> The leaf lands on a path."
        data = validate_minimax_draft({"user_request": request, "duration_seconds": 6}, generation=True)
        plan = validate_analysis(plan_json(), data)
        result = validate_output(BASE, data, plan)
        self.assertTrue(result.startswith("integrated_multimodal_description:\n[Shot 1]"))
        self.assertIn("[Shot 2] At 00:02.000, The leaf lands on a path.", result)
        self.assertNotIn("<shot", result)

    def test_auto_uses_semantic_roles_not_presence_of_an_image_or_video(self):
        cases = [([], plan_json(), "T2VA"),
                 (["image1"], plan_json(role("image1", "identity")), "Ref2VA"),
                 (["image1"], plan_json(role("image1", "first frame"), first="image1"), "I2VA"),
                 (["image1"], plan_json(role("image1", "last frame"), last="image1"), "L2VA"),
                 (["image1", "image2"], plan_json(role("image1", "first frame"), role("image2", "last frame"), first="image1", last="image2"), "FL2VA"),
                 (["image1", "video1"], DANCE_PLAN, "Ref2VA"),
                 (["video1"], plan_json(role("video1", "camera movement")), "Ref2VA"),
                 (["video1"], plan_json(role("video1", "editing source")), "Ref2VA"),
                 (["video1"], plan_json(role("video1", "video continuation")), "Ref2VA"),
                 (["image1", "audio1"], plan_json(role("image1", "first frame"), role("audio1", "voice timbre"), first="image1"), "Ref2VA")]
        for refs, raw, mode in cases:
            with self.subTest(refs=refs, mode=mode):
                data = validate_minimax_draft({"references": refs})
                self.assertEqual(validate_analysis(raw, data)["mode"], mode)

    def test_auto_and_full_reference_ignore_unrequested_frame_anchor_guesses(self):
        raw = plan_json(role("image1", "identity"), role("image2", "object"), role("image3", "environment"), first="image1")
        for mode in ("auto", "Ref2VA"):
            with self.subTest(mode=mode):
                data = validate_minimax_draft({"mode": mode, "references": ["image1", "image2", "image3"],
                                              "user_request": "<image1> is an apple, <image2> is a banana, <image3> is the street."})
                plan = validate_analysis(raw, data)
                self.assertIsNone(plan["first_frame"])
                self.assertEqual(plan["mode"], "Ref2VA")

    def test_analysis_cannot_invent_or_omit_assets_or_roles(self):
        for raw in ("not JSON", "[]", plan_json(role("image1", "identity")),
                    plan_json(role("image1", "identity"), role("video2", "motion")),
                    plan_json(role("image1", "invented role"), role("video1", "motion"))):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_analysis(raw, dance_input())

    def test_frame_order_mapping_and_exact_final_shot_alignment(self):
        for mode, refs, first, last in (("I2VA", ["image7"], "image7", None),
                                      ("L2VA", ["image4"], None, "image4"),
                                      ("FL2VA", ["image2", "image5"], "image5", "image2")):
            data = validate_minimax_draft({"mode": mode, "references": refs, "duration_seconds": 6})
            raw = plan_json(*(role(token, "first frame" if token == first else "last frame") for token in refs), first=first, last=last)
            plan = validate_analysis(raw, data)
            self.assertEqual(plan["label_map"][first or last], "Picture 1")
            prompt = frame_instruction(mode, 6, 2) + "\n\n" + BASE.replace("quiet path.", "quiet path. [Shot 2] At 00:03.000, the camera cuts to the ending frame.")
            self.assertEqual(validate_output(prompt, data, plan), prompt)
            if mode != "I2VA":
                with self.assertRaises(ValueError):
                    validate_output(prompt.replace("6.00-second", "7.00-second"), data, plan)

    def test_ref_schema_and_rejection_of_fences_missing_sections_bad_times_and_labels(self):
        data = dance_input()
        plan = validate_analysis(DANCE_PLAN, data)
        self.assertEqual(validate_output(REF, data, plan), REF)
        bad = ["Here is your prompt\n" + REF, "```text\n" + REF + "\n```", REF.replace("summary:", "overview:"),
               REF.replace("<Picture 1>", "<Picture 2>"), REF.replace("<Video 1>", "<Video 4>"),
               REF.replace("<Subject 2>", "<Subject N>"), REF.replace("attribute_transfer", "fully_copy"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:16.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:05.000, A [Shot 3] At 00:04.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:05.000, A [Shot 3] At 00:05.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:15.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] <image10> A"),
               REF.replace("[reference generation]", "[editing]"), REF.replace("[Shot 1] A", "[Shot 1] <Subject 99> A")]
        for prompt in bad:
            with self.subTest(prompt=prompt[:100]), self.assertRaises(ValueError):
                validate_output(prompt, data, plan)

    def test_output_normalizes_generated_video_audio_wording_and_first_shot_timestamp(self):
        data = validate_minimax_draft({"user_request": "A cartoon apple walks down a street."})
        plan = validate_analysis(plan_json(), data)
        variants = ["[Shot 1] At 00:00.000, Video 1 shows a leaf",
                    "[Shot 1] 0:00 - Video 1 shows a leaf",
                    "[Shot 1] At 00:01.000: Video 1 shows a leaf"]
        for variant in variants:
            with self.subTest(variant=variant):
                normalized = validate_output(BASE.replace("[Shot 1] A leaf", variant), data, plan)
                self.assertIn("[Shot 1] target video shows", normalized)
                self.assertNotIn("Video 1", normalized)
        normalized = validate_output(BASE.replace("Wind rustles", "Audio 1 carries the spoken line while wind rustles"), data, plan)
        self.assertIn("generated audio carries", normalized)
        self.assertNotIn("Audio 1", normalized)

    def test_dialogue_language_exact_words_voiceover_and_speaker_ids(self):
        data = validate_minimax_draft({"user_request": 'The speaker says: <d>[French] Bonjour, mes amis!</d>'})
        plan = validate_analysis(plan_json(), data)
        prompt = BASE.replace("A leaf falls onto a quiet path.", 'The speaker (S1) says: <d>[French] Bonjour, mes amis!</d>')
        self.assertEqual(validate_output(prompt, data, plan), prompt)
        for bad in (prompt.replace("Bonjour,", "Salut,"), prompt.replace("[French]", "[English]"),
                    prompt.replace("</d>", ""), prompt.replace(" (S1)", ""),
                    prompt.replace("says:", "says in an off-screen voiceover:")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_output(bad, data, plan)
        data["user_request"] = 'She says "Wait, don’t go!"'
        normalized = validate_output(BASE, data, plan)
        self.assertIn('She (S1) says: <d>[English] Wait, don’t go!</d>', normalized)

    def test_plain_speech_is_formatted_and_preserved_from_user_text(self):
        self.assertEqual(requested_spoken_lines(APPLE_PLAIN_REQUEST),
                         [{"speaker": "apple", "words": "i stepped on a poop"}])
        self.assertEqual(requested_spoken_lines("Apple says 'Don't go!'"),
                         [{"speaker": "Apple", "words": "Don't go!"}])
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"],
                                       "user_request": APPLE_PLAIN_REQUEST}, generation=True)
        roles = plan_json(role("image1", "character"), role("image2", "character"), role("image3", "environment"))
        plan = validate_analysis(roles, data)
        instruction = generation_instruction(data, plan, get_director_preset(data["director_preset"]), "qwen")
        self.assertIn('"speaker": "apple", "words": "i stepped on a poop"', instruction.user_message)
        for spoken in ('<d>[English] I stepped on poop</d>', '<d>[Language] i stepped on a poop</d>', '"I stepped on a poop."',
                       '<d>[English] i stepped on a poop', 'i stepped on a poop'):
            with self.subTest(spoken=spoken):
                raw = APPLE_PROMPT.replace('<d>[English] I stepped on poop</d>', spoken).replace('(S1) says:', 'says:')
                raw = raw.replace('Footsteps and soft crying', '<d>[English] i stepped on a poop</d> Footsteps and soft crying')
                result = validate_output(raw, data, plan)
                self.assertIn('<Subject 1> (S1) says: <d>[English] i stepped on a poop</d>', result)
                self.assertEqual(result.count('<d>'), 1)
                self.assertEqual(result.count('</d>'), 1)
                self.assertIn('Then <Subject 1> and <Subject 2> begin to cry together.', result)
        raw = APPLE_PROMPT.replace('<d>[English] I stepped on poop</d>', 'i stepped on a poop')
        raw = raw.replace('Footsteps and soft crying', '<d>[English] i stepped on a poop Footsteps and soft crying')
        result = validate_output(raw, data, plan)
        self.assertEqual(result.count('<d>'), 1)
        without_speech = APPLE_PROMPT.replace('<Subject 1> (S1) says: <d>[English] I stepped on poop</d>', '')
        self.assertIn('apple (S1) says: <d>[English] i stepped on a poop</d>', validate_output(without_speech, data, plan))
        backend = ScriptedBackend(roles, raw)
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=APPLE_PLAIN_REQUEST), data, lambda _: None)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn('<d>[English] i stepped on a poop</d>', result["prompt"])

    def test_multiple_natural_speakers_keep_distinct_ids_and_exact_words(self):
        request = APPLE_PLAIN_REQUEST.replace("apple says : i stepped on a poop",
                                              'apple says : i stepped on a poop\nbanana whispers: "We will cry together!"')
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"], "user_request": request}, generation=True)
        plan = validate_analysis(plan_json(role("image1", "character"), role("image2", "character"),
                                           role("image3", "environment")), data)
        raw = APPLE_PROMPT.replace('<d>[English] I stepped on poop</d>', '"I stepped on a poop."')
        raw = raw.replace('Then <Subject 1>', '<Subject 2> whispers: "We will cry together!" Then <Subject 1>')
        result = validate_output(raw, data, plan)
        self.assertIn('<Subject 1> (S1) says: <d>[English] i stepped on a poop</d>', result)
        self.assertIn('<Subject 2> (S2) whispers: <d>[English] We will cry together!</d>', result)
        self.assertEqual(result.count('<d>'), 2)

    def test_image_only_scene_repairs_model_shot_headings_without_retries(self):
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"],
                                       "user_request": APPLE_PLAIN_REQUEST}, generation=True)
        roles = plan_json(role("image1", "character"), role("image2", "character"), role("image3", "environment"))
        plan = validate_analysis(roles, data)
        variants = {
            "missing": APPLE_PROMPT.replace("[Shot 1] <Subject 1> walks", "<Subject 1> walks"),
            "unnumbered": APPLE_PROMPT.replace("[Shot 1] <Subject 1> walks", "Shot 2: <Subject 1> walks"),
            "dash": APPLE_PROMPT.replace("[Shot 1] <Subject 1> walks", "Shot 1 — <Subject 1> walks"),
            "repeated": APPLE_PROMPT.replace("begin to cry together.",
                                              "begin to cry together. [Shot 1] They comfort each other."),
            "timed": APPLE_PROMPT.replace("begin to cry together.",
                                           "begin to cry together. [Shot 4] At 00:04.000, the camera cuts to their faces."),
            "short_time": APPLE_PROMPT.replace("begin to cry together.",
                                                "begin to cry together. [Shot 4] 0:04 - the camera cuts to their faces."),
            "mention": APPLE_PROMPT.replace("The target video has a cartoonish style.",
                                             "The target video has a cartoonish style, echoed in [Shot 1] without a cut."),
        }
        for kind, raw in variants.items():
            with self.subTest(kind=kind):
                result = validate_output(raw, data, plan)
                timeline = result.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape:", 1)[0]
                self.assertIn("[Shot 1]", timeline)
                self.assertIn("<d>[English] i stepped on a poop</d>", timeline)
                self.assertIn("cry together", timeline)
                if kind == "repeated":
                    self.assertIn("They comfort each other", timeline)
                    self.assertEqual(timeline.count("[Shot 1]"), 1)
                if kind in ("timed", "short_time"):
                    self.assertIn("[Shot 2] At 00:04.000,", timeline)
        backend = ScriptedBackend(roles, variants["unnumbered"])
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=APPLE_PLAIN_REQUEST), data, lambda _: None)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("[Shot 1]", result["prompt"])

    def test_audio_only_is_a_nonblocking_warning_and_missing_audio_is_never_invented(self):
        data = validate_minimax_draft({"user_request": "Use <audio1> for music style", "references": ["audio1"]}, generation=True)
        self.assertTrue(reference_warnings(data))
        self.assertFalse(reference_warnings(dance_input()))
        data = validate_minimax_draft({"user_request": "Generate new music", "references": ["audio1"]}, generation=True)
        self.assertEqual(data["references"], [])
        self.assertFalse(reference_warnings(data))
        with self.assertRaises(ValueError):
            validate_output(REF.replace("Generate an energetic", "Use <Audio 1> for an energetic"), dance_input(), validate_analysis(DANCE_PLAN, dance_input()))

    def test_video_audio_requires_an_explicit_audio_role_and_preserves_asset_provenance(self):
        data = dance_input()
        self.assertEqual(validate_analysis(DANCE_PLAN, data)["video_audio_tracks"], {})
        data = validate_minimax_draft({"references": ["video1", "audio1"], "user_request": "Keep the soundtrack of <video1> and use <audio1> as the voice timbre."})
        plan = validate_analysis(plan_json(role("video1", "editing source", "direct audio reuse"), role("audio1", "voice timbre")), data)
        self.assertEqual(plan["video_audio_tracks"], {"Audio 2": "video1"})
        self.assertEqual(plan["label_map"]["audio1"], "Audio 1")

    def test_local_knowledge_and_director_priority_enter_the_actual_instruction(self):
        data = dance_input(director_preset="video_director")
        plan = validate_analysis(DANCE_PLAN, data)
        instruction = generation_instruction(data, plan, get_director_preset("video_director"), "qwen")
        self.assertIn("six", instruction.system_message)
        self.assertIn("attribute_transfer", instruction.system_message)
        self.assertIn("<Video 1> (cut and pacing structure)", instruction.system_message)
        self.assertIn("UNSEEN", instruction.system_message)
        self.assertIn("ALWAYS overrides", instruction.system_message)
        self.assertIn('"duration_seconds": 15', instruction.user_message)
        self.assertIn('"mode": "Ref2VA"', instruction.user_message)
        self.assertIn(REQUEST, instruction.user_message)
        self.assertIn("exact initial visual state", instruction.user_message)  # lower-priority legacy director
        self.assertIn("Identity images are NOT first frames", analysis_instruction(data, "qwen").system_message)
        self.assertIsNone(instruction.image)
        self.assertTrue(instruction.unlimited_tokens)
        self.assertIsNone(instruction.max_tokens)
        self.assertTrue(analysis_instruction(data, "qwen").unlimited_tokens)
        self.assertIsNone(analysis_instruction(data, "qwen").max_tokens)

    def test_image_only_generation_excludes_unregistered_guide_examples_and_repairs_draft(self):
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"],
                                       "user_request": APPLE_REQUEST}, generation=True)
        roles = plan_json(role("image1", "character"), role("image2", "character"), role("image3", "environment"))
        plan = validate_analysis(roles, data)
        instruction = generation_instruction(data, plan, get_director_preset(data["director_preset"]), "qwen")
        self.assertNotIn("<Video 1>", instruction.system_message)
        self.assertNotIn("<Audio 1>", instruction.system_message)
        self.assertNotIn("<Video N>", instruction.system_message)
        self.assertNotIn("<Audio N>", instruction.system_message)
        for label in ("<Picture 1>", "<Picture 2>", "<Picture 3>"):
            self.assertIn(label, instruction.system_message)
        self.assertIn("No video source was supplied", instruction.system_message)
        self.assertIn("No audio source was supplied", instruction.system_message)
        self.assertIn(APPLE_REQUEST, instruction.user_message)
        self.assertEqual(validate_output(APPLE_PROMPT, data, plan), APPLE_PROMPT)
        bad = APPLE_PROMPT.replace("<Subject 1> walks", "<Video 1> shows <Subject 1> walking as <Subject 1> walks")
        with self.assertRaisesRegex(ValueError, "Video 1 was introduced"):
            validate_output(bad, data, plan)
        backend = ScriptedBackend(roles, bad, APPLE_PROMPT)
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=APPLE_REQUEST), data, lambda _: None)
        self.assertEqual(result["prompt"], APPLE_PROMPT)
        self.assertIn("PREVIOUS RESPONSE:\n" + bad, backend.calls[-1].user_message)
        self.assertIn("VALIDATION CORRECTION", backend.calls[-1].user_message)
        self.assertEqual(backend.calls[-1].system_message, backend.calls[-2].system_message)
        self.assertEqual(backend.calls[-1].user_message.count("VALIDATION CORRECTION"), 1)

    def test_image_only_generation_supplies_missing_role_definitions_without_retries(self):
        data = validate_minimax_draft({"references": ["image1", "image2", "image3"],
                                       "user_request": APPLE_REQUEST}, generation=True)
        roles = plan_json(role("image1", "character"), role("image2", "character"), role("image3", "environment"))
        bad = APPLE_PROMPT.replace(
            APPLE_PROMPT.split("subject_definitions:\n", 1)[1].split("\n\nsummary:", 1)[0],
            "Mike the apple comes from Picture 1; the banana comes from Picture 2; the street comes from Picture 3.")
        bad = bad.replace(
            bad.split("retention_analysis:\n", 1)[1].split("\n\ndetailed_description:", 1)[0],
            "Keep the three referenced subjects recognizable.")
        backend = ScriptedBackend(roles, bad)
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=APPLE_REQUEST), data, lambda _: None)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("reference_definitions", backend.calls[-1].user_message)
        for subject, picture in ((1, 1), (2, 2), (3, 3)):
            self.assertIn(f"<Subject {subject}> is the requested", result["prompt"])
            self.assertIn(f"from <Picture {picture}>", result["prompt"])
            self.assertIn(f"<Subject {subject}>: ", result["prompt"])
        self.assertIn(APPLE_PROMPT.split("detailed_description:\n", 1)[1], result["prompt"])
        self.assertNotIn("<Video 1>", result["prompt"])
        plan = validate_analysis(roles, data)
        self.assertEqual(validate_output(APPLE_PROMPT.replace("<Subject 1>", "<subject 1>")
                                         .replace("<Picture 1>", "<picture 1>"), data, plan), APPLE_PROMPT)
        with self.assertRaisesRegex(ValueError, "Video 1 was introduced"):
            validate_output(bad.replace("Mike the apple comes", "<Video 1> comes"), data, plan)

    def test_scaffold_uses_actual_video_source_without_enabling_audio(self):
        data = dance_input()
        plan = validate_analysis(DANCE_PLAN, data)
        bad = REF.replace(REF.split("subject_definitions:\n", 1)[1].split("\n\nsummary:", 1)[0],
                          "Use the person image for appearance and the video for dance movement.")
        result = validate_output(bad, data, plan)
        self.assertIn("<Subject 2> is the requested dance, motion subject from <Video 1>", result)
        self.assertNotIn("<Audio 1>", result)

    def test_generation_acceptance_and_bounded_repair_keep_one_model_session(self):
        backend = ScriptedBackend(DANCE_PLAN, REF.replace("summary:", "overview:"), REF)
        with patch("goated_prompter.minimax.create_backend", return_value=backend):
            result = MiniMaxService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea=REQUEST), dance_input(), lambda _: None)
        self.assertEqual(result["mode"], "Ref2VA")
        self.assertEqual(result["prompt"], REF)
        self.assertEqual((backend.sessions, backend.exits, len(backend.calls)), (1, 1, 3))
        self.assertIn("VALIDATION CORRECTION", backend.calls[-1].user_message)
        self.assertTrue(all(call.image is None and call.image_2 is None for call in backend.calls))
        self.assertTrue(all(call.unlimited_tokens and call.max_tokens is None for call in backend.calls))
        backend = ScriptedBackend(*(["wrong"] * 3))
        with patch("goated_prompter.minimax.create_backend", return_value=backend), self.assertRaisesRegex(BackendGenerationError, "after 2 repair attempts"):
            MiniMaxService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea="A leaf falls"), {"user_request": "A leaf falls"}, lambda _: None)
        self.assertEqual(len(backend.calls), 3)
        backend = ScriptedBackend("invalid plan", DANCE_PLAN, "bad prompt", "still bad")
        progress = []
        with patch("goated_prompter.minimax.create_backend", return_value=backend), self.assertRaisesRegex(BackendGenerationError, "after 2 repair attempts"):
            MiniMaxService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=REQUEST), dance_input(), progress.append)
        self.assertEqual(len(backend.calls), 4)
        self.assertTrue(any("retry 1/2" in update for update in progress))
        self.assertTrue(any("retry 2/2" in update for update in progress))


class MiniMaxEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = enter_context(self, tempfile.TemporaryDirectory())
        enter_context(self, patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp) / "directors")}))
        self.backend = ScriptedBackend(DANCE_PLAN, REF)
        enter_context(self, patch("goated_prompter.minimax.create_backend", return_value=self.backend))
        self.app = local.create_app(config_loader=lambda: {"backend": "mock"}, settings_path=Path(self.temp) / "settings.json")
        self.client = TestClient(TestServer(self.app), headers={"Host": "127.0.0.1:8190"})
        await self.client.start_server()

    async def asyncTearDown(self):
        self.backend.release.set()
        await self.client.close()

    async def terminal(self, job):
        for _ in range(300):
            result = await (await self.client.get(f"/api/jobs/{job['id']}")).json()
            if result["status"] in local.TERMINAL:
                return result
            await asyncio.sleep(.01)
        self.fail("Job did not finish")

    async def test_generate_is_text_only_isolated_from_builder_and_history(self):
        history = await (await self.client.get("/api/workspace")).json()
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input()})
        self.assertEqual(response.status, 202, await response.text())
        job = await self.terminal(await response.json())
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(job["result"]["prompt"], REF)
        self.assertEqual(job["kind"], "minimax")
        self.assertEqual(await (await self.client.get("/api/workspace")).json(), history)
        self.assertNotIn("builder", self.app[local.STATE].saved_settings)

    async def test_invalid_contract_rejected_before_inference(self):
        for data in ({"duration_seconds": 16, "user_request": "Test"},
                     {"user_request": "Use <image1>"},
                     {"references": ["video4"], "user_request": "Test"},
                     {"mode": "I2VA", "user_request": "Test"}):
            response = await self.client.post("/api/workspace/minimax", json={"input": data})
            self.assertEqual(response.status, 400, await response.text())
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input(), "images": ["data:image/png;base64,abc"]})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.backend.calls, [])

    async def test_shared_admission_cancellation_discards_output(self):
        self.backend.block = True
        response = await self.client.post("/api/workspace/minimax", json={"input": dance_input()})
        job = await response.json()
        self.assertTrue(await asyncio.to_thread(self.backend.entered.wait, 2))
        for url, payload in (("/api/workspace/minimax", {"input": dance_input()}), ("/api/generate", {})):
            self.assertEqual((await self.client.post(url, json=payload)).status, 409)
        self.assertEqual((await self.client.post(f"/api/jobs/{job['id']}/cancel", json={})).status, 200)
        self.backend.release.set()
        result = await self.terminal(job)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["result"])
        self.assertEqual(len(self.backend.calls), 1)

    async def test_settings_migrate_roundtrip_and_detect_stale_revisions(self):
        path = self.app[local.STATE].workflow_settings.path
        old = empty_settings()
        del old["minimax"]
        local.atomic_json(path, old)
        response = await self.client.get("/api/workspace/settings/minimax")
        record = await response.json()
        self.assertEqual(record["draft"], default_minimax_draft())
        draft = {**dance_input(), "generated_prompt": REF}
        saved = await self.client.put("/api/workspace/settings/minimax", json={"revision": record["revision"], "draft": draft})
        self.assertEqual(saved.status, 200)
        reload = WorkflowSettingsStore(path, local.read_store, local.atomic_json)
        self.assertEqual(reload.snapshot("minimax")["draft"], draft)
        stale = await self.client.put("/api/workspace/settings/minimax", json={"revision": 0, "draft": {}})
        self.assertEqual(stale.status, 409)


if __name__ == "__main__":
    unittest.main()
