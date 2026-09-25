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
from goated_prompter.backends.base import GoatedPrompterBackend, BackendGenerationError
from goated_prompter.core import GoatedPrompterRequest
from goated_prompter.minimax import (MiniMaxService, analysis_instruction, default_minimax_draft,
    frame_instruction, generation_instruction, parse_reference_tokens, reference_warnings,
    validate_analysis, validate_minimax_draft, validate_output)
from goated_prompter.presets import get_director_preset
from goated_prompter.workflow_settings import WorkflowSettingsStore, empty_settings

REQUEST = ("I want the person in <image1> to do the same dancing style and movements as the dancer in <video1>. "
           "Put the person on a rooftop at night with neon city lights behind them. I want energetic electronic music. "
           "Start with a medium full-body shot, then slowly move the camera around the dancer.")
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
               REF.replace("[Shot 1] A", "[Shot 1] At 00:00.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:16.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:05.000, A [Shot 3] At 00:04.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:05.000, A [Shot 3] At 00:05.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] A [Shot 2] At 00:15.000, A"),
               REF.replace("[Shot 1] A", "[Shot 1] <image10> A"),
               REF.replace("[reference generation]", "[editing]"), REF.replace("[Shot 1] A", "[Shot 1] <Subject 99> A")]
        for prompt in bad:
            with self.subTest(prompt=prompt[:100]), self.assertRaises(ValueError):
                validate_output(prompt, data, plan)

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
        with self.assertRaises(ValueError):
            validate_output(BASE, data, plan)

    def test_audio_only_is_a_nonblocking_warning_and_missing_audio_is_never_invented(self):
        data = validate_minimax_draft({"user_request": "Use <audio1> for music style", "references": ["audio1"]}, generation=True)
        self.assertTrue(reference_warnings(data))
        self.assertFalse(reference_warnings(dance_input()))
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
        backend = ScriptedBackend("wrong", "still wrong")
        with patch("goated_prompter.minimax.create_backend", return_value=backend), self.assertRaises(BackendGenerationError):
            MiniMaxService({"backend": "mock"}, lambda: None).run(GoatedPrompterRequest(idea="A leaf falls"), {"user_request": "A leaf falls"}, lambda _: None)
        self.assertEqual(len(backend.calls), 2)


class MiniMaxEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"GOATED_PROMPTER_USER_DIR": str(Path(self.temp) / "directors")}))
        self.backend = ScriptedBackend(DANCE_PLAN, REF)
        self.enterContext(patch("goated_prompter.minimax.create_backend", return_value=self.backend))
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
        old["explore"]["draft"]["base"] = "Keep my previous draft"
        local.atomic_json(path, old)
        response = await self.client.get("/api/workspace/settings/minimax")
        record = await response.json()
        self.assertEqual(record["draft"], default_minimax_draft())
        draft = {**dance_input(), "generated_prompt": REF}
        saved = await self.client.put("/api/workspace/settings/minimax", json={"revision": record["revision"], "draft": draft})
        self.assertEqual(saved.status, 200)
        reload = WorkflowSettingsStore(path, local.read_store, local.atomic_json)
        self.assertEqual(reload.snapshot("minimax")["draft"], draft)
        self.assertEqual(reload.snapshot("explore")["draft"]["base"], "Keep my previous draft")
        stale = await self.client.put("/api/workspace/settings/minimax", json={"revision": 0, "draft": {}})
        self.assertEqual(stale.status, 409)


if __name__ == "__main__":
    unittest.main()
