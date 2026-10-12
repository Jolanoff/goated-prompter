"""Private position routing and preservation through Dataset planning and writing."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.brainstorm import sexual_positions
from goated_prompter.features.dataset.ideas import DatasetIdeasService, creative_directions, ideas_instruction
from goated_prompter.features.dataset.private_vocabulary import VOCABULARY_FILE_ENV, parse_vocabulary, private_rules
from goated_prompter.features.dataset.plan import ScenePlanner, reusable_scene_plan, scene_plan_signature, validate_saved_scene_plan
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.quality import kink_request, ownership_request, pet_request, position_categories
from goated_prompter.features.dataset.service import DatasetService, saved_dataset_draft
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

    def test_conditional_director_guidance_does_not_activate_ownership_or_narrow_the_act(self):
        director = ("Prefer partial clothing, collars, cuffs or light restraints when they fit the request. "
                    "For domination or ownership requests, show control through posture, restraint and who guides whom. "
                    "For feet or other specific focuses, only emphasize them when requested. "
                    "Do not invent unrequested fetishes.")
        data = self.draft("two adult men having sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=director)):
            self.assertFalse(ownership_request(data))
            self.assertFalse(kink_request(data))
            self.assertEqual(position_categories(data), (set(), set()))

    def test_conditional_director_keeps_general_vocabulary_and_omits_ownership_rules(self):
        self.path.write_text("[rules]\nUse readable adult arrangements.\n[ownership rules]\nUse ownership dynamics.\n"
                             "[mood]\nordinary mood\n[kink mood]\nkink mood\n[interaction]\nordinary interaction\n"
                             "[kink interaction]\nkink interaction\n[setting]\nordinary room\n[kink setting]\nkink room\n"
                             "[clothing]\nordinary clothing\n[kink clothing]\nkink clothing\n[props]\nsynthetic collar\n",
                             encoding="utf-8")
        data = self.draft("two adult men having sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="For domination or ownership requests, use collars and restraint.")):
            rules = private_rules(data)
            directions = creative_directions(data, [1, 2, 3], 1)
        self.assertIn("Use readable adult arrangements.", rules)
        self.assertNotIn("Use ownership dynamics.", rules)
        for row in directions.values():
            self.assertEqual(row["mood"], "ordinary mood")
            self.assertEqual(row["interaction"], "ordinary interaction")
            self.assertEqual(row["setting"], "ordinary room")
            self.assertEqual(row["clothing"], "ordinary clothing")
            self.assertNotIn("prop", row)

    def test_director_conditions_apply_to_the_whole_sentence_including_comma_lists(self):
        data = self.draft("two adult men having sex", "male", "male")
        for instructions in ("If the user requests ownership, show collars, leashes and restraints.",
                             "When pet play is requested, use collars, a leash, and a pet setting.",
                             "Use collars, leashes and restraints only when requested.",
                             "For ownership requests, show a collar, a leash and restraint."):
            with self.subTest(instructions=instructions), patch(
                "goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=instructions)):
                self.assertFalse(ownership_request(data))
                self.assertFalse(kink_request(data))
                self.assertFalse(pet_request(data))
                self.assertEqual(position_categories(data), (set(), set()))

    def test_a_conditional_director_still_honors_explicit_user_requests(self):
        director = "For ownership or pet play requests, show collars, leashes and restraint."
        data = self.draft("an adult man with his collared adult human pet", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=director)):
            self.assertTrue(ownership_request(data))
            self.assertTrue(kink_request(data))
            self.assertTrue(pet_request(data))

    def test_an_unconditional_director_default_is_not_lost_next_to_conditional_guidance(self):
        data = self.draft("two adult men having sex", "male", "male")
        director = "Use BDSM in every scene. For ownership requests, show a collar and leash."
        with patch("goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=director)):
            self.assertTrue(kink_request(data))
            self.assertFalse(ownership_request(data))
            self.assertEqual(position_categories(data), ({"kink"}, set()))

    def test_director_guidance_for_every_request_is_an_unconditional_default(self):
        data = self.draft("two adult men having sex", "male", "male")
        for instructions in ("For every request, use BDSM.", "For each request, use BDSM."):
            with self.subTest(instructions=instructions), patch(
                "goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=instructions)):
                self.assertTrue(kink_request(data))
                self.assertEqual(position_categories(data), ({"kink"}, set()))

    def test_conditional_director_position_names_do_not_force_one_vocabulary_entry(self):
        data = self.draft("two adult men having sex", "male", "male")
        director = "For a requested anal scene, use anal supported pose beta."
        with patch("goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=director)):
            positions = sexual_positions(data)
        self.assertIn("anal supported pose alpha", positions)
        self.assertIn("anal supported pose beta", positions)
        self.assertIn("male pair seated pose", positions)

    def test_conditional_director_keywords_do_not_unlock_requested_vocabulary_extras(self):
        self.path.write_text(VOCABULARY + "\n[requested]\nleash => requested supported pose\n", encoding="utf-8")
        data = self.draft("two adult men having sex", "male", "male")
        director = "For ownership requests, show a leash."
        with patch("goated_prompter.features.dataset.quality.get_director_preset", return_value=Mock(instructions=director)):
            self.assertNotIn("requested supported pose", sexual_positions(data))

    def test_penetration_requests_with_men_do_not_use_unrelated_act_categories(self):
        for subject in ("2 males fucking", "two adult men in intercourse", "one adult man penetrates another adult man"):
            with self.subTest(subject=subject):
                positions = set(sexual_positions(self.draft(subject, "male", "male")))
                self.assertTrue({"anal supported pose alpha", "male pair seated pose"} <= positions)
                self.assertFalse(positions & {"oral supported pose", "feet supported pose", "kink supported pose",
                                             "solo toy pose", "finish supported pose", "vaginal supported pose"})

    def test_user_penetration_request_takes_precedence_over_a_kink_director(self):
        data = self.draft("two adult males fucking", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="Use BDSM positions.")):
            positions = sexual_positions(data)
        self.assertIn("anal supported pose alpha", positions)
        self.assertNotIn("kink supported pose", positions)

    def test_explicit_oral_penetration_is_not_mistaken_for_anal(self):
        positions = sexual_positions(self.draft("two adult men face-fucking", "male", "male"))
        self.assertIn("oral supported pose", positions)
        self.assertNotIn("anal supported pose alpha", positions)

    def test_mixed_cast_penetration_can_use_anal_or_vaginal_but_not_other_acts(self):
        positions = sexual_positions(self.draft("two adults having intercourse", "male", "female"))
        self.assertIn("anal supported pose alpha", positions)
        self.assertIn("vaginal supported pose", positions)
        self.assertNotIn("oral supported pose", positions)
        self.assertNotIn("kink supported pose", positions)

    def test_negated_penetration_does_not_add_it_to_an_oral_request(self):
        positions = sexual_positions(self.draft("two adult men, no fucking, only oral sex", "male", "male"))
        self.assertIn("oral supported pose", positions)
        self.assertNotIn("anal supported pose alpha", positions)

    def test_explicit_kink_can_modify_penetration_without_substituting_other_acts(self):
        self.path.write_text("[anal positions]\nanal supported pose\n[kink positions]\n"
                             "bondage anal pose\nbondage oral pose\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult men fucking in bondage", "male", "male"))
        self.assertIn("anal supported pose", positions)
        self.assertIn("bondage anal pose", positions)
        self.assertNotIn("bondage oral pose", positions)

    def test_penetrative_wording_reaches_ideas_as_compatible_assignments(self):
        for mode in ("random", "guided"):
            with self.subTest(mode=mode):
                data = self.draft("2 males fucking", "unspecified", "unspecified", source_mode=mode,
                                  inputs="Same adult cast having intercourse")
                context = json.loads(ideas_instruction(data, dataset_assignments(data), direction_salt=1,
                    event_seeds={1: "An unrelated generic scenario."}).user_message)
                allowed = {"male pair seated pose", "anal supported pose alpha",
                           "anal supported pose beta", "anal supported pose gamma"}
                positions = [row["creative_direction"]["position"] for row in context["assignments"]]
                self.assertTrue(set(positions) <= allowed)
                self.assertEqual(len(set(positions)), 3)

    def test_routing_preview_reports_resolved_cast_and_penetrative_act(self):
        from goated_prompter.features.dataset.brainstorm import dataset_routing
        route = dataset_routing(self.draft("2 males fucking", "male", "male"))[0]
        self.assertTrue(route["nsfw"])
        self.assertEqual(route["scope"], "all_outputs")
        self.assertEqual(route["cast"], {"count": 2, "male": 2, "female": 0, "unspecified": 0,
                                        "mode": "pair", "source": "approved_cast"})
        self.assertEqual(route["user_categories"], ["penetration"])
        self.assertEqual(route["effective_categories"], ["anal"])
        self.assertIn("anal", route["position_pools"])
        self.assertNotIn("group", route["position_pools"])
        self.assertEqual(route["private_position_count"], 4)

    def test_routing_preview_keeps_broad_requests_distinct_from_eligible_categories(self):
        from goated_prompter.features.dataset.brainstorm import dataset_routing
        data = self.draft("two adult men having sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="For ownership requests, use collars and restraint.")):
            route = dataset_routing(data)[0]
        self.assertEqual(route["user_categories"], [])
        self.assertEqual(route["director_categories"], [])
        self.assertEqual(route["effective_categories"], [])
        self.assertIn("oral", route["position_pools"])
        self.assertIn("kink", route["position_pools"])
        self.assertFalse(route["kink_styling"])
        self.assertFalse(route["ownership_styling"])

    def test_routing_preview_reports_solo_group_exclusions_and_director_defaults(self):
        from goated_prompter.features.dataset.brainstorm import dataset_routing
        solo = dataset_routing(self.draft("one adult male masturbating", "male"))[0]
        self.assertEqual(solo["cast"]["mode"], "solo")
        group = dataset_routing(self.draft("four adult males having sex", "male", "male", "male", "male"))[0]
        self.assertEqual(group["cast"]["mode"], "group")
        self.assertEqual(group["cast"]["male"], 4)
        self.assertIn("group", group["position_pools"])
        data = self.draft("two adult men having sex", "male", "male", constraints="No oral.")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="Use anal positions.")):
            directed = dataset_routing(data)[0]
        self.assertEqual(directed["director_categories"], ["anal"])
        self.assertIn("oral", directed["excluded_categories"])
        self.assertNotIn("oral", directed["position_pools"])

    def test_routing_preview_preserves_guided_line_scope(self):
        from goated_prompter.features.dataset.brainstorm import dataset_routing
        data = self.draft("two adult men having sex", "male", "male", source_mode="guided",
                          inputs="anal sex\noral sex\nfoot worship", amount=2)
        routes = dataset_routing(data)
        self.assertEqual([route["scope"] for route in routes], ["guided:1", "guided:2"])
        self.assertEqual([route["effective_categories"] for route in routes], [["anal"], ["oral"]])

    def test_nonsexual_routing_preview_does_not_claim_active_sexual_pools(self):
        from goated_prompter.features.dataset.brainstorm import dataset_routing
        route = dataset_routing(self.draft("two adult men reading", "male", "male"))[0]
        self.assertFalse(route["nsfw"])
        self.assertEqual(route["position_pools"], [])
        self.assertEqual(route["private_position_count"], 0)

    def test_a_generic_penetration_entry_is_compatible_with_an_explicit_act(self):
        self.path.write_text("[two men positions]\npenetration while seated\n", encoding="utf-8")
        positions = sexual_positions(self.draft("two adult men having anal sex", "male", "male"))
        self.assertEqual(positions, ("penetration while seated",))

    def test_an_explicit_user_act_overrides_a_directors_default_penetration_ban(self):
        data = self.draft("two adult men having anal sex", "male", "male")
        with patch("goated_prompter.features.dataset.quality.get_director_preset",
                   return_value=Mock(instructions="Avoid penetration.")):
            positions = sexual_positions(data)
        self.assertIn("anal supported pose alpha", positions)

    def test_every_assignment_carries_a_position_even_with_event_seeds(self):
        data = self.draft("two adult males having anal sex", "male", "male")
        context = json.loads(ideas_instruction(data, dataset_assignments(data), direction_salt=1,
                             event_seeds={1: "A repeated generic event."}).user_message)
        directions = [row["creative_direction"] for row in context["assignments"]]
        self.assertTrue(all(direction.get("position") for direction in directions))
        self.assertEqual(len({direction["position"] for direction in directions}), 3)

    def test_natural_scene_wording_retains_the_app_assigned_position_as_plan_data(self):
        data = self.draft("two adult males having anal sex", "male", "male")
        session = Mock()
        session.generate.return_value = json.dumps([
            {"index": index, "idea": f"The two adults interact at station {index}.",
             "scene": f"The two adults sit together at station {index}."} for index in range(1, 4)])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=data,
            assignments=dataset_assignments(data), direction_salt=1, progress=lambda _: None, allow_partial=True)
        self.assertTrue(all(row.get("idea_status") != "failed" for row in rows))
        self.assertEqual(len({row["selected_position"] for row in rows}), 3)
        assignments = json.loads(session.generate.call_args.args[0].user_message)["assignments"]
        self.assertEqual([row["selected_position"] for row in rows],
                         [row["creative_direction"]["position"] for row in assignments])

    def test_selected_position_survives_saved_scene_validation(self):
        scene = saved_scene(selected_position="supported seated pose", scene="Two adults sit facing away.")
        self.assertEqual(validate_saved_scene_plan([scene])[0]["selected_position"], "supported seated pose")

    def test_selected_position_survives_composition_and_serialized_draft_loading(self):
        scene = saved_scene(selected_position="supported seated pose", scene="Two adults sit facing away.")
        composed = ScenePlanner.compose([scene])
        loaded = saved_dataset_draft(json.loads(json.dumps(valid_draft(scene_plan=composed))))
        self.assertEqual(loaded["scene_plan"][0]["selected_position"], "supported seated pose")
        self.assertEqual(loaded["scene_plan"][0]["self_check"], "PASS")

    def test_old_verbatim_gate_plans_require_fresh_scenes(self):
        data = self.draft("two adult men having anal sex", "male", "male", amount=1,
                          scene_plan=[saved_scene(scene="Two adults sit together.")])
        assignments = dataset_assignments(data)
        with patch("goated_prompter.features.dataset.plan.SCENE_PLAN_VERSION", 9):
            data["scene_plan_signature"] = scene_plan_signature(data, assignments)
        self.assertIsNone(reusable_scene_plan(data, assignments))

    def test_no_usable_vocabulary_leaves_scene_position_model_generated(self):
        self.path.write_text("[setting]\nsynthetic room\n", encoding="utf-8")
        data = self.draft("two adult men having anal sex", "male", "male", amount=1)
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "idea": "Two adults interact.",
                                                    "scene": "Two adults sit facing one another."}])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None)
        self.assertNotIn("selected_position", rows[0])
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1,
                                          plan_item=saved_scene(**rows[0]))
        self.assertNotIn("SELECTED POSITION", instruction.system_message)

    def test_natural_position_wording_does_not_bypass_existing_anatomy_checks(self):
        data = self.draft("two adult men having anal sex", "male", "male", amount=1)
        session = Mock()
        session.generate.return_value = json.dumps([{"index": 1, "idea": "Two adults interact.",
            "scene": "Two adults sit together with a detached arm beside them."}])
        rows = DatasetIdeasService(lambda: None).run(session=session, data=data,
            assignments=dataset_assignments(data), progress=lambda _: None, allow_partial=True)
        self.assertEqual(rows[0]["idea_status"], "failed")
        self.assertIn("selected_position", rows[0])
        self.assertIn("attached", rows[0]["failure_reason"])

    def test_invalid_selected_position_metadata_is_rejected(self):
        for position in (None, 7, [], "", " " * 3, "x" * 10001):
            with self.subTest(position_type=type(position).__name__), self.assertRaises(ValueError):
                validate_saved_scene_plan([saved_scene(selected_position=position)])

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
        scene = saved_scene(selected_position="anal supported pose alpha",
                            scene="Two adult men sit together in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        self.assertIn("SELECTED POSITION", instruction.system_message)
        self.assertIn("anal supported pose alpha", instruction.system_message)

    def test_saved_plans_and_prompt_regeneration_pass_the_explicit_position_to_the_writer(self):
        data = self.draft("two adult men having anal sex", "male", "male", amount=1, trigger="ohwx_person",
            scene_plan=[saved_scene(selected_position="anal supported pose alpha",
                                    scene="Two adult men sit facing away in a room.")])
        data["scene_plan_signature"] = scene_plan_signature(data, dataset_assignments(data))
        for action in (None, ("regenerate_prompt", 1)):
            with self.subTest(action=action):
                backend = CaptureBackend()
                with patch("goated_prompter.features.dataset.service.create_backend", return_value=backend):
                    result = DatasetService({"backend": "mock"}, lambda: None).run(
                        GoatedPrompterRequest(idea=data["subject"], prompt_model="Custom"), data,
                        lambda _: None, lambda _: None, scene_action=action)
                self.assertEqual(result["completed"], 1)
                self.assertEqual(result["scene_plan"][0]["selected_position"], "anal supported pose alpha")
                self.assertEqual(len(backend.calls), 1)
                self.assertIn("SELECTED POSITION", backend.calls[0].system_message)
                self.assertIn("anal supported pose alpha", backend.calls[0].system_message)

    def test_final_output_can_describe_the_position_without_copying_its_label(self):
        data = self.draft("two adult men having anal sex", "male", "male", trigger="ohwx_person")
        scene = saved_scene(selected_position="anal supported pose alpha",
                            scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.return_value = "Two adult men, including ohwx_person, sit close together with their feet grounded under warm lamplight."
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=0)
        self.assertEqual(output, session.generate.return_value)
        session.generate.assert_called_once()

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
        scene = saved_scene(selected_position="anal supported pose alpha",
                            scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.return_value = "Two adult men, including ohwx_person, use ANAL supported pose alpha in a room."
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=0)
        self.assertIn("ANAL supported pose alpha", output)
        session.generate.assert_called_once()

    def test_final_writer_does_not_retry_only_because_a_position_label_is_absent(self):
        data = self.draft("two adult men having anal sex", "male", "male", trigger="ohwx_person")
        scene = saved_scene(selected_position="anal supported pose alpha",
                            scene="Two adult men use anal supported pose alpha in a room.")
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        session.generate.side_effect = ["Two adult men, including ohwx_person, interact in a room.",
                                       "Two adult men, including ohwx_person, use anal supported pose alpha in a room."]
        output = DatasetService({}, lambda: None)._generate(session, instruction, data, 1, lambda _: None, scene, retries=1)
        self.assertNotIn("anal supported pose alpha", output)
        session.generate.assert_called_once()

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
        positions = [row["selected_position"] for row in result["scene_plan"]]
        self.assertTrue(set(positions) <= eligible)
        writers = [call for call in backend.calls if call.diagnostic_stage in {"dataset:1", "dataset:2", "dataset:3"}]
        self.assertEqual(len(writers), 3)
        for position, instruction in zip(positions, writers):
            self.assertIn("SELECTED POSITION", instruction.system_message)
            self.assertIn(position, instruction.system_message)
        self.assertEqual(len(set(positions)), 3)
