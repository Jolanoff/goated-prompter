"""Prompt extraction from image metadata uses synthetic images and graphs only."""

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from goated_prompter.features.caption.metadata import COMPUTED_PROMPT, extract_folder, extract_prompt
from tests.helpers import enter_context
from tests.support.artifacts import task_paths
from tests.support.safety import synthetic_storage

POSITIVE = "a person carrying a wooden box across a sunny courtyard"
NEGATIVE = "blurry, low quality"

API_GRAPH = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": POSITIVE, "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["4", 1]}},
    "10": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["6", 0], "negative": ["7", 0],
                                                               "strength": 1.0}},
    "3": {"class_type": "KSampler", "inputs": {"positive": ["10", 0], "negative": ["10", 1], "model": ["4", 0],
                                               "seed": 1, "sampler_name": "euler"}},
}

GUIDER_GRAPH = {
    "11": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "t5.safetensors", "type": "flux"}},
    "20": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": POSITIVE}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["20", 0], "clip": ["11", 0]}},
    "26": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
    "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
    "22": {"class_type": "BasicGuider", "inputs": {"model": ["12", 0], "conditioning": ["26", 0]}},
    "12": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux.safetensors"}},
}

# The positive text is chosen by a switch while the workflow runs: one branch is a constant prompt,
# the other a generator fed with instructions. The stored graph cannot say which text was used.
COMPUTED_GRAPH = {
    "1": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "Instructions for a text generator."}},
    "2": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": POSITIVE}},
    "3": {"class_type": "TextGenerate", "inputs": {"prompt": ["1", 0], "clip": ["9", 0]}},
    "4": {"class_type": "Switch", "inputs": {"switch": ["8", 0], "on_true": ["3", 0], "on_false": ["2", 0]}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": ["4", 0], "clip": ["9", 0]}},
    "6": {"class_type": "KSampler", "inputs": {"model": ["10", 0], "positive": ["5", 0], "negative": ["7", 0]}},
    "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
    "8": {"class_type": "BooleanToggle", "inputs": {"value": False}},
    "11": {"class_type": "ImageSaver", "inputs": {"positive": ["12", 0], "negative": ""}},
    "12": {"class_type": "JoinStrings", "inputs": {"string1": ["4", 0], "string2": "<lora:style:1>"}},
}

EDITOR_WORKFLOW = {
    "nodes": [
        {"id": 6, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "link": 1}], "widgets_values": [POSITIVE]},
        {"id": 7, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "link": 2}], "widgets_values": [NEGATIVE]},
        {"id": 4, "type": "CheckpointLoaderSimple", "inputs": [], "widgets_values": ["model.safetensors"]},
        {"id": 3, "type": "KSampler", "inputs": [{"name": "model", "link": 5}, {"name": "positive", "link": 3},
                                                 {"name": "negative", "link": 4}],
         "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1]},
    ],
    "links": [[1, 4, 1, 6, 0, "CLIP"], [2, 4, 1, 7, 0, "CLIP"], [3, 6, 0, 3, 1, "CONDITIONING"],
              [4, 7, 0, 3, 2, "CONDITIONING"], [5, 4, 0, 3, 0, "MODEL"]],
}


class MetadataCaptionTests(unittest.TestCase):
    def setUp(self):
        _, scratch = task_paths("issue-118", "unit")
        storage = enter_context(self, synthetic_storage(scratch))
        self.folder = Path(enter_context(self, tempfile.TemporaryDirectory(dir=storage)))

    def png(self, name, **fields):
        info = PngInfo()
        for key, value in fields.items():
            info.add_text(key, value if isinstance(value, str) else json.dumps(value))
        Image.new("RGB", (16, 16), "gray").save(self.folder / name, pnginfo=info)
        return self.folder / name

    def test_api_graph_returns_only_positive_prompt(self):
        path = self.png("a.png", prompt=API_GRAPH, workflow=EDITOR_WORKFLOW)
        self.assertEqual(extract_prompt(path), POSITIVE)

    def test_guider_graph_follows_linked_text(self):
        self.assertEqual(extract_prompt(self.png("a.png", prompt=GUIDER_GRAPH)), POSITIVE)

    def test_editor_workflow_when_api_graph_is_missing(self):
        self.assertEqual(extract_prompt(self.png("a.png", workflow=EDITOR_WORKFLOW)), POSITIVE)

    def test_parameters_block(self):
        parameters = f"{POSITIVE}\nNegative prompt: {NEGATIVE}\nSteps: 20, Sampler: Euler, Seed: 1"
        self.assertEqual(extract_prompt(self.png("a.png", parameters=parameters)), POSITIVE)

    def test_parameters_block_wins_over_graph_and_drops_network_tags(self):
        parameters = f"{POSITIVE} <lora:style_v2:0.8>\nNegative prompt: \nSteps: 8, Sampler: euler"
        path = self.png("a.png", parameters=parameters, prompt=COMPUTED_GRAPH)
        self.assertEqual(extract_prompt(path), POSITIVE)

    def test_prompt_built_at_run_time_fails_without_writing_a_file(self):
        self.png("a.png", prompt=COMPUTED_GRAPH)
        result = extract_folder({"folder": str(self.folder)})
        self.assertEqual(result["files"][0]["status"], "missing")
        self.assertEqual(result["files"][0]["error"], COMPUTED_PROMPT)
        self.assertFalse((self.folder / "a.txt").exists())

    def test_webp_exif_graph(self):
        path = self.folder / "a.webp"
        exif = Image.Exif()
        exif[0x0110] = "prompt:" + json.dumps(API_GRAPH)
        Image.new("RGB", (16, 16), "gray").save(path, exif=exif)
        self.assertEqual(extract_prompt(path), POSITIVE)

    def test_folder_writes_sidecars_keeps_existing_and_reports_missing(self):
        self.png("a.png", prompt=API_GRAPH)
        self.png("b.png", prompt=API_GRAPH)
        Image.new("RGB", (16, 16)).save(self.folder / "c.png")
        (self.folder / "b.txt").write_text("Manual caption", encoding="utf-8")
        result = extract_folder({"folder": str(self.folder), "trigger": "boxcarry"})
        self.assertEqual([row["status"] for row in result["files"]], ["saved", "skipped", "missing"])
        self.assertEqual((result["saved"], result["skipped"], result["missing"], result["errors"]), (1, 1, 1, 0))
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), f"boxcarry, {POSITIVE}\n")
        self.assertEqual((self.folder / "b.txt").read_text(encoding="utf-8"), "Manual caption")
        self.assertFalse((self.folder / "c.txt").exists())

    def test_single_image_replaces_existing_caption_but_failure_keeps_it(self):
        self.png("a.png", prompt=API_GRAPH)
        self.png("b.png", prompt=COMPUTED_GRAPH)
        for name in ("a", "b"):
            (self.folder / f"{name}.txt").write_text("Old caption", encoding="utf-8")
        result = extract_folder({"folder": str(self.folder), "image": "a.png"})
        self.assertEqual([(row["image"], row["status"]) for row in result["files"]], [("a.png", "saved")])
        self.assertEqual((self.folder / "a.txt").read_text(encoding="utf-8"), POSITIVE + "\n")
        result = extract_folder({"folder": str(self.folder), "image": "b.png"})
        self.assertEqual(result["files"][0]["status"], "missing")
        self.assertEqual((self.folder / "b.txt").read_text(encoding="utf-8"), "Old caption")

    def test_unreadable_image_reports_error_and_continues(self):
        (self.folder / "a.png").write_bytes(b"not an image")
        self.png("b.png", prompt=API_GRAPH)
        result = extract_folder({"folder": str(self.folder)})
        self.assertEqual([row["status"] for row in result["files"]], ["error", "saved"])

    def test_invalid_input_rejected(self):
        for value in ({"folder": str(self.folder), "description": "x"}, {"folder": "missing-folder"},
                      {"folder": str(self.folder), "trigger": "a\nb"}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                extract_folder(value)


if __name__ == "__main__":
    unittest.main()
