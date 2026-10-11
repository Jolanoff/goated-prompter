"""Private position routing and preservation through Dataset planning and writing."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.brainstorm import sexual_positions
from goated_prompter.features.dataset.ideas import DatasetIdeasService, creative_directions, ideas_instruction
from goated_prompter.features.dataset.private_vocabulary import VOCABULARY_FILE_ENV, parse_vocabulary
from goated_prompter.features.dataset.plan import scene_plan_signature
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.service import DatasetService
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import CaptureBackend, saved_scene, valid_draft


VOCABULARY = """[solo positions]
solo seated pose
[two men positions]
male pair seated pose
[two women positions]
female pair seated pose
[man and woman positions]
mixed pair seated pose
[three positions]
trio seated pose
[group positions]
group seated pose
[anal positions]
anal supported pose alpha
anal supported pose beta
anal supported pose gamma
[vaginal positions]
vaginal supported pose
[oral positions]
oral supported pose
[feet positions]
feet supported pose
[kink positions]
kink supported pose
[solo kink positions]
solo kink supported pose
[toys]
solo toy pose
[finish positions]
finish supported pose
[setting]
synthetic room alpha
synthetic room beta
synthetic room gamma
"""


class PositionRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "vocabulary.txt"
        self.path = path
        path.write_text(VOCABULARY, encoding="utf-8")
        patcher = patch.dict("os.environ", {VOCABULARY_FILE_ENV: str(path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def draft(self, subject, *sexes, **changes):
        cast = [{"name": f"adult participant {index}", "count": 1, "sex": sex, "kind": "human",
                 "origin": "random", "series": "", "traits": ""} for index, sex in enumerate(sexes, 1)]
        brief = dataset_understanding_fixture(character_count=len(cast), characters=cast)
        return valid_draft(**{"subject": subject, "trigger": "", "amount": 3,
            "trigger_type": "Multiple characters", "_confirmed_intent": brief, **changes})

    def test_anal_section_is_parsed(self):
        sections = parse_vocabulary(VOCABULARY)
        self.assertEqual(sections.get("anal positions"),
                         ("anal supported pose alpha", "anal supported pose beta", "anal supported pose gamma"))

    def test_explicit_anal_keeps_male_positions_without_other_acts(self):
        positions = set(sexual_positions(self.draft("two adult males having anal sex", "male", "male")))
        self.assertIn("male pair seated pose", positions)
        self.assertIn("anal supported pose alpha", positions)
        self.assertFalse(positions & {"oral supported pose", "vaginal supported pose", "kink supported pose",
                                     "feet supported pose", "female pair seated pose", "mixed pair seated pose"})

    def test_generic_male_sex_can_use_all_compatible_categories(self):
        positions = set(sexual_positions(self.draft("2 males having sex", "male", "male")))
        self.assertTrue({"male pair seated pose", "anal supported pose alpha", "oral supported pose",
                         "kink supported pose", "feet supported pose"} <= positions)
        self.assertFalse(positions & {"vaginal supported pose", "female pair seated pose", "mixed pair seated pose"})

    def test_every_assignment_carries_a_position_even_with_event_seeds(self):
        data = self.draft("two adult males having anal sex", "male", "male")
        context = json.loads(ideas_instruction(data, dataset_assignments(data), direction_salt=1,
                             event_seeds={1: "A repeated generic event."}).user_message)
        directions = [row["creative_direction"] for row in context["assignments"]]
        self.assertTrue(all(direction.get("position") for direction in directions))
        self.assertEqual(len({direction["position"] for direction in directions}), 3)

    def test_model_omitting_the_assigned_position_cannot_produce_a_valid_scene(self):
        data = self.draft("two adult males having anal sex", "male", "male")
        session = Mock()
        session.generate.return_value = json.dumps([
            {"index": index, "idea": f"The two adults interact at station {index}.",
             "scene": f"The two adults sit together at station {index}."} for index in range(1, 4)])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=data,
            assignments=dataset_assignments(data), direction_salt=1, progress=lambda _: None, allow_partial=True)
        self.assertTrue(all(row.get("idea_status") == "failed" for row in rows))
        self.assertTrue(all("position" in row["failure_reason"].casefold() for row in rows))

    def test_kink_request_does_not_turn_into_oral_or_vaginal(self):
        positions = set(sexual_positions(self.draft("two adult males in bondage", "male", "male")))
        self.assertIn("kink supported pose", positions)
        self.assertIn("male pair seated pose", positions)
        self.assertFalse(positions & {"oral supported pose", "anal supported pose alpha", "vaginal supported pose"})

    def test_bound_master_wording_selects_kink_without_a_possessive_prefix(self):
        data = self.draft("master with his bound adult male partner having sex", "unspecified", "unspecified")
        self.assertIn("kink supported pose", sexual_positions(data))
        self.assertIn("male pair seated pose", sexual_positions(data))
        self.assertNotIn("female pair seated pose", sexual_positions(data))

    def test_women_and_mixed_casts_can_use_vaginal_positions(self):
        for sexes in (("female", "female"), ("male", "female")):
            with self.subTest(sexes=sexes):
                positions = set(sexual_positions(self.draft("adults having vaginal sex", *sexes)))
                self.assertIn("vaginal supported pose", positions)
                self.assertNotIn("male pair seated pose", positions)
                self.assertNotIn("oral supported pose", positions)

    def test_solo_uses_solo_and_compatible_extras_not_partner_positions(self):
        self.path.write_text(VOCABULARY + "\n[anal positions]\nanal with another partner\n", encoding="utf-8")
        positions = set(sexual_positions(self.draft("one adult male masturbating", "male")))
        self.assertTrue({"solo seated pose", "solo toy pose", "solo kink supported pose"} <= positions)
        self.assertFalse(positions & {"male pair seated pose", "mixed pair seated pose", "anal with another partner"})

    def test_two_hands_or_both_knees_do_not_turn_a_solo_pose_into_a_partner_pose(self):
        self.path.write_text("[solo positions]\nsolo pose with both knees supported\n"
                             "solo pose with two hands resting on the seat\n", encoding="utf-8")
        positions = sexual_positions(self.draft("one adult male masturbating", "male"))
        self.assertEqual(set(positions), {"solo pose with both knees supported", "solo pose with two hands resting on the seat"})

    def test_solo_cast_positions_survive_an_explicit_kink_and_feet_request(self):
        positions = sexual_positions(self.draft("one adult male masturbating in bondage with a foot fetish", "male"))
        self.assertIn("solo seated pose", positions)
        self.assertIn("solo kink supported pose", positions)
        self.assertIn("feet supported pose", positions)
        self.assertNotIn("male pair seated pose", positions)

    def test_counted_and_group_casts_keep_their_own_groups(self):
        for sexes, expected in ((("male", "male", "male"), "trio seated pose"),
                                (("female", "male", "male", "male"), "group seated pose")):
            with self.subTest(sexes=sexes):
                positions = sexual_positions(self.draft("adults having sex", *sexes))
                self.assertIn(expected, positions)

    def test_a_counted_cast_entry_routes_like_two_individual_men(self):
        data = self.draft("two adult men having anal sex", "male")
        data["_confirmed_intent"]["characters"][0]["count"] = 2
        data["_confirmed_intent"]["character_count"] = 2
        individual = self.draft("two adult men having anal sex", "male", "male")
        self.assertEqual(sexual_positions(data), sexual_positions(individual))

    def test_a_missing_cast_can_still_resolve_an_explicit_group_of_women(self):
        data = self.draft("four adult women having vaginal sex")
        data["_confirmed_intent"]["character_count"] = 4
        positions = sexual_positions(data)
        self.assertIn("vaginal supported pose", positions)
        self.assertNotIn("male pair seated pose", positions)

    def test_exclusions_do_not_leak_across_fields_or_cancel_a_different_requested_act(self):
        data = self.draft("two adult men having sex", "male", "male", constraints="No oral, no kink, but anal is welcome.")
        positions = set(sexual_positions(data))
        self.assertIn("anal supported pose alpha", positions)
        self.assertFalse(positions & {"oral supported pose", "kink supported pose"})

    def test_explicit_user_act_takes_precedence_over_director_defaults(self):
        data = self.draft("two adult men having anal sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="Use BDSM positions.")):
            positions = sexual_positions(data)
        self.assertIn("anal supported pose alpha", positions)
        self.assertNotIn("kink supported pose", positions)

    def test_generic_sex_allows_selected_kinks_despite_a_conditional_director_ban(self):
        data = self.draft("two adult men having sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="Do not invent unrequested fetish elements.")):
            self.assertIn("kink supported pose", sexual_positions(data))

    def test_incompatible_anatomy_is_removed_even_from_a_generic_section(self):
        self.path.write_text("[anal positions]\nanal with a woman\nanal supported pose\n"
                             "[oral positions]\ncunnilingus with her partner\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult men having sex", "male", "male"))
        self.assertEqual(positions, ("anal supported pose",))

    def test_a_kink_modifier_does_not_allow_a_different_requested_act(self):
        self.path.write_text("[anal positions]\nanal supported pose\n[kink positions]\n"
                             "bondage oral pose\nbondage anal pose\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult men having anal sex in bondage", "male", "male"))
        self.assertIn("anal supported pose", positions)
        self.assertIn("bondage anal pose", positions)
        self.assertNotIn("bondage oral pose", positions)

    def test_grounded_feet_in_a_pose_description_are_not_a_different_sex_act(self):
        self.path.write_text("[anal positions]\nanal pose with feet planted on the floor\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult men having anal sex", "male", "male"))
        self.assertEqual(positions, ("anal pose with feet planted on the floor",))

    def test_licking_feet_is_not_routed_to_oral_positions(self):
        data = self.draft("two adult men licking feet", "male", "male")
        positions = sexual_positions(data)
        self.assertIn("feet supported pose", positions)
        self.assertNotIn("oral supported pose", positions)

    def test_a_strap_on_does_not_make_an_extra_male_partner_compatible_with_women(self):
        self.path.write_text("[anal positions]\nanal pose with a man wearing a strap-on\n"
                             "anal pose with a strap-on\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult women having sex", "female", "female"))
        self.assertEqual(positions, ("anal pose with a strap-on",))

    def test_guided_assignments_get_positions_without_a_brainstorm(self):
        data = self.draft("two adult men having anal sex", "male", "male", source_mode="guided",
                          inputs="First compatible scene\nSecond compatible scene")
        directions = creative_directions(data, [1, 2, 3], 1)
        self.assertTrue(all(row.get("position") for row in directions.values()))

    def test_guided_acts_are_routed_per_line_not_mixed_across_the_batch(self):
        self.path.write_text("[anal positions]\nanal supported pose\n[oral positions]\noral supported pose\n", encoding="utf-8")
        data = self.draft("two adult men having sex", "male", "male", source_mode="guided",
                          inputs="anal sex\noral sex")
        directions = creative_directions(data, [1, 2, 3, 4], 1)
        self.assertEqual([directions[index]["position"] for index in range(1, 5)],
                         ["anal supported pose", "oral supported pose", "anal supported pose", "oral supported pose"])

    def test_an_explicit_vocabulary_position_is_kept_instead_of_randomized(self):
        data = self.draft("two adult men using anal supported pose beta", "male", "male")
        self.assertEqual(sexual_positions(data), ("anal supported pose beta",))

    def test_settings_are_dealt_without_repetition_until_the_pool_is_exhausted(self):
        directions = creative_directions(self.draft("two adult men having anal sex", "male", "male"), [1, 2, 3, 4], 1)
        self.assertEqual(len({directions[index]["setting"] for index in (1, 2, 3)}), 3)
        self.assertEqual(directions[1]["setting"], directions[4]["setting"])

    def test_an_empty_position_pool_does_not_invent_a_private_position(self):
        self.path.write_text("[setting]\nsynthetic room\n", encoding="utf-8")
        directions = creative_directions(self.draft("two adult men having anal sex", "male", "male"), [1], 1)
        self.assertNotIn("position", directions[1])

    def test_final_writer_is_given_the_selected_position_contract(self):
        data = self.draft("two adult men having anal sex", "male", "male")
        scene = saved_scene(scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        self.assertIn("SELECTED POSITION", instruction.system_message)
        self.assertIn("anal supported pose alpha", instruction.system_message)

    def test_final_output_that_drops_the_position_is_rejected(self):
        data = self.draft("two adult men having anal sex", "male", "male", trigger="ohwx_person")
        scene = saved_scene(scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.return_value = "Two adult men, including ohwx_person, interact in a room under warm lamplight."
        with self.assertRaisesRegex(BackendGenerationError, "position"):
            DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=0)

    def test_vocabulary_edits_invalidate_a_saved_scene_plan(self):
        data = self.draft("two adult men having anal sex", "male", "male")
        assignments = dataset_assignments(data)
        before = scene_plan_signature(data, assignments)
        self.path.write_text(VOCABULARY + "\n[anal positions]\na different anal pose\n", encoding="utf-8")
        self.assertNotEqual(before, scene_plan_signature(data, assignments))

    def test_director_act_changes_invalidate_positions_but_style_only_changes_do_not(self):
        data = self.draft("two adult men having sex", "male", "male")
        assignments = dataset_assignments(data)
        def signature(instructions):
            with patch("goated_prompter.features.dataset.quality.get_director_preset",
                       return_value=Mock(instructions=instructions)):
                return scene_plan_signature(data, assignments)
        self.assertNotEqual(signature("Use anal positions."), signature("Use oral positions."))
        self.assertEqual(signature("Use anal positions under warm light."),
                         signature("Use anal positions under cool light."))

    def test_final_preservation_accepts_capitalization_and_punctuation_changes(self):
        data = self.draft("two adult men having anal sex", "male", "male", trigger="ohwx_person")
        scene = saved_scene(scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.return_value = "Two adult men, including ohwx_person, use ANAL supported pose alpha in a room."
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=0)
        self.assertIn("ANAL supported pose alpha", output)
        session.generate.assert_called_once()

    def test_an_omitted_final_position_uses_the_existing_bounded_output_retry(self):
        data = self.draft("two adult men having anal sex", "male", "male", trigger="ohwx_person")
        scene = saved_scene(scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.side_effect = ["Two adult men, including ohwx_person, interact in a room.",
                                       "Two adult men, including ohwx_person, use anal supported pose alpha in a room."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=1)
        self.assertIn("anal supported pose alpha", output)
        self.assertEqual(session.generate.call_count, 2)
        correction = session.generate.call_args.args[0].system_message
        self.assertIn("Preserve the selected position wording", correction)

    def test_an_unusable_brainstorm_does_not_lose_positions_on_the_way_to_final_prompts(self):
        data = self.draft("2 adult males having anal sex", "male", "male", trigger="ohwx_person")

        class Backend(CaptureBackend):
            def generate(self, instruction):
                self.calls.append(instruction)
                if instruction.diagnostic_stage == "dataset:ideas:brainstorm":
                    return "not json"
                if instruction.diagnostic_stage == "dataset:ideas":
                    assignments = json.loads(instruction.user_message)["assignments"]
                    return json.dumps([{"index": row["index"], "idea": f"Two adult men interact at station {row['index']}.",
                        "scene": "Two adult men use " + row["creative_direction"]["position"] + " in "
                                 + row["creative_direction"]["setting"] + "."} for row in assignments])
                return "ohwx_person: " + instruction.user_message

        backend = Backend()
        with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
            result = DatasetService({"backend": "mock"}, lambda: None).run(
                GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data, lambda _: None, lambda _: None)
        self.assertEqual(result["completed"], 3)
        eligible = set(sexual_positions(data))
        positions = []
        for row in result["prompts"]:
            matches = [position for position in eligible if position in row["scene"]]
            self.assertEqual(len(matches), 1)
            self.assertIn(matches[0], row["prompt"])
            positions.extend(matches)
        self.assertEqual(len(set(positions)), 3)
