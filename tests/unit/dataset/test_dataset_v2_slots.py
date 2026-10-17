"""Dataset V2 slot identity: image N stays image N from its vocabulary to its final prompt. Scripted responses only."""

from collections import defaultdict
import json
import re
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset import runner
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.local_jobs import Job

PLACE = re.compile(r"location(\d+)")
from tests.support.dataset_scenes import composer_user


class SlotIdentityTests(unittest.TestCase):
    """The composer writes "location<N>" as image N's space, so every later stage can be traced to its image."""

    def setUp(self):
        self.config = {"backend": "mock"}
        self.request = GoatedPrompterRequest(idea="Adult reading", planning_mode="Direct", director_preset="general_director")
        self.failing = {"omitted": set(), "description": set()}  # omitted: the answer stops before this image
        self.calls, self.scripts = [], defaultdict(list)
        self.backend = MockBackend()
        self.enterContext(patch.object(self.backend, "generate", side_effect=self.generate))
        for module in (understanding, scenes):
            self.enterContext(patch.object(module, "create_backend", return_value=self.backend))
        self.enterContext(patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        self.make_brief(3)

    def make_brief(self, amount, guided=()):
        data = {**default_dataset_draft(), "subject": "Alex reads", "amount": amount, "seed": 73, "seed_mode": "fixed"}
        if guided:
            data.update(source_mode="guided", inputs="\n".join(guided))
        value = {"path": "character", "summary": "Alex reads", "fixed": "Alex stays the same", "randomized": "Location",
                 "must": [], "avoid": [],
                 "characters": [{"label": "Alex", "gender": "custom", "custom": "adult human reader", "pronoun": "it", "count": 1}]}
        self.brief = understanding.apply_rules(value, data)

    @staticmethod
    def image(text):
        return int(PLACE.search(json.dumps(text)).group(1))

    def generate(self, instruction):
        self.calls.append(instruction)
        stage, user = instruction.diagnostic_stage, composer_user(instruction.user_message) if instruction.diagnostic_stage == "dataset_v2:scenes" else None
        if self.scripts[stage]:
            return self.scripts[stage].pop(0)
        if stage == "dataset_v2:scenes":
            out = []
            for row in user["images"]:
                number = row["image"]
                if number in self.failing["omitted"]:
                    break
                label = "Nobody" if number in self.failing["description"] else "Alex"
                out.append({"subjects": {label: {field: f"visible {field}" for field in scenes.SUBJECT_FIELDS}},
                            "actions": "Alex reads the book", "position": {label: f"Seated at location{number}"},
                            "space": f"location{number}", "lighting": "daylight", "mood": "calm", "camera": "wide",
                            "extras": "books"})
            return json.dumps({"scenes": out})
        # Builder: echo the image the scene came from, so prompt-to-scene association is checkable.
        found = PLACE.search(instruction.user_message or "") or PLACE.search(instruction.system_message or "")
        return f"Alex reads a book at location{found.group(1)}." if found else "Alex reads a book."

    def write_scenes(self):
        return scenes.write_scenes(self.config, self.request, self.brief, progress=lambda _message: None)

    def run_job(self, scenes_only=False):
        job = Job()
        with patch.object(runner, "create_backend", return_value=self.backend):
            runner.run_dataset_v2_scenes(None, job, self.request, self.config, {"brief": self.brief, "scenes_only": scenes_only})
        return job

    def assert_slots(self, result, written, failed_stage=None):
        total = self.brief["input"]["amount"]
        self.assertEqual([row["slot"] for row in result["slots"]], list(range(1, total + 1)))
        self.assertEqual([row["slot"] for row in result["slots"] if row["status"] == "written"], written)
        self.assertEqual([scene["slot"] for scene in result["scenes"]], written)
        for scene in result["scenes"]:
            self.assertEqual(scene["space"], f"location{scene['slot']}", "a scene keeps its own image's content")
        failed = [row for row in result["slots"] if row["status"] == "failed"]
        self.assertEqual(sorted(row["slot"] for row in failed), sorted(set(range(1, total + 1)) - set(written)))
        self.assertEqual(sorted(item["slot"] for item in result["missing"]), [row["slot"] for row in failed])
        for row in failed:
            self.assertTrue(row["reasons"], row)
            if failed_stage:
                self.assertEqual(row["stage"], failed_stage)
        self.assertEqual(result["complete"], not failed)
        self.assertEqual(result["written"], len(written))
        return failed

    # -- scenes
    def test_all_scenes_succeed(self):
        result = self.write_scenes()
        self.assert_slots(result, [1, 2, 3])
        self.assertEqual([row["stage"] for row in result["slots"]], [None, None, None])
        self.assertEqual([row["concept"] for row in result["slots"]], [None] * 3)

    def test_failed_first_scene(self):
        self.failing["description"] = {1}
        self.assert_slots(self.write_scenes(), [2, 3], "scene")

    def test_failed_middle_scene(self):
        self.failing["description"] = {2}
        result = self.write_scenes()
        self.assert_slots(result, [1, 3], "scene")

    def test_failed_final_scene(self):
        self.failing["description"] = {3}
        self.assert_slots(self.write_scenes(), [1, 2], "scene")

    def test_multiple_failed_scenes_in_two_batches(self):
        self.make_brief(7)
        self.failing["description"] = {2, 6}
        result = self.write_scenes()
        self.assert_slots(result, [1, 3, 4, 5, 7], "scene")

    def test_an_answer_that_stops_early_fails_only_the_images_it_never_wrote(self):
        self.failing["omitted"] = {2}
        result = self.write_scenes()
        failed = self.assert_slots(result, [1], "scene")
        self.assertTrue(all("missing" in row["reasons"][0] for row in failed))

    # -- guided inputs
    def test_guided_inputs_stay_with_their_slots_including_failed_ones(self):
        self.make_brief(3, guided=("reading by a window", "reading on a train", "reading in a garden"))
        self.failing["description"] = {2}
        result = self.write_scenes()
        self.assert_slots(result, [1, 3], "scene")
        self.assertEqual({row["slot"]: row["input"] for row in result["slots"]},
                         {1: "reading by a window", 2: "reading on a train", 3: "reading in a garden"})
        self.assertEqual(result["missing"][0]["input"], "reading on a train")

    def test_guided_inputs_repeat_by_slot_when_fewer_than_images(self):
        self.make_brief(3, guided=("first", "second"))
        result = self.write_scenes()
        self.assertEqual([row["input"] for row in result["slots"]], ["first", "second", "first"])

    def test_guided_failure_keeps_later_inputs_unassigned_to_wrong_slots(self):
        self.make_brief(3, guided=("one", "two", "three"))
        self.failing["omitted"] = {2}
        result = self.write_scenes()
        self.assertEqual([(row["slot"], row["status"], row["input"]) for row in result["slots"]],
                         [(1, "written", "one"), (2, "failed", "two"), (3, "failed", "three")])

    def test_random_source_has_empty_inputs(self):
        self.assertEqual([row["input"] for row in self.write_scenes()["slots"]], ["", "", ""])

    # -- Builder handoff and the job result
    def test_prompts_keep_their_scene_slot_after_a_failed_middle_scene(self):
        self.failing["description"] = {2}
        job = self.run_job()
        self.assertEqual(job.status, "succeeded")
        result = job.result
        self.assertEqual([item["slot"] for item in result["prompts"]], [1, 3])
        self.assertEqual([item["index"] for item in result["prompts"]], [1, 3], "index is the slot, never a list position")
        for item in result["prompts"]:
            self.assertIn(f"location{item['slot']}", item["prompt"], "each prompt was written from its own image's scene")
        by_slot = {scene["slot"]: scene for scene in result["scenes"]}
        self.assertEqual({item["slot"] for item in result["prompts"]}, set(by_slot))
        self.assertTrue(any("image 3" in event["message"] for event in job.events))

    def test_every_slot_is_accounted_for_exactly_once(self):
        self.make_brief(4)
        self.failing["description"] = {1, 3}
        result = self.run_job().result
        written = {row["slot"] for row in result["slots"] if row["status"] == "written"}
        failed = {row["slot"] for row in result["slots"] if row["status"] == "failed"}
        self.assertEqual(written | failed, {1, 2, 3, 4})
        self.assertFalse(written & failed)
        self.assertEqual({item["slot"] for item in result["prompts"]}, written)

    def test_scenes_only_run_keeps_slots_and_writes_no_prompts(self):
        self.failing["description"] = {2}
        result = self.run_job(scenes_only=True).result
        self.assertEqual((result["stage"], result["prompts"]), ("scenes", []))
        self.assertEqual([scene["slot"] for scene in result["scenes"]], [1, 3])

    def test_builder_input_and_seed_are_unchanged_by_slot_identity(self):
        result = self.run_job().result
        builder = [call for call in self.calls if not call.diagnostic_stage.startswith("dataset_v2:")]
        self.assertTrue(builder)
        for call in builder:
            self.assertNotIn('"slot"', call.user_message or "", "the Builder idea is the scene text, not the record")
            self.assertEqual(call.seed, self.brief["input"]["seed"])
        self.assertEqual([item["slot"] for item in result["prompts"]], [1, 2, 3])

    def test_slotless_scenes_keep_their_position_as_before(self):
        written = self.write_scenes()["scenes"]
        bare = [{key: value for key, value in scene.items() if key != "slot"} for scene in written]
        result = prompts.write_prompts(self.config, self.request, self.brief, bare, progress=lambda _message: None)
        self.assertEqual([item["slot"] for item in result], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
