"""Understanding response-format regressions without inference or private storage."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.llama_cpp_process import LlamaCppLaunchConfig
from goated_prompter.backends.local_llama_cpp import LocalLlamaCppBackend
from goated_prompter.backends.openai_compatible import OpenAICompatibleBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.ideas import ideas_instruction
from goated_prompter.features.dataset.intent import DatasetIntentTickets
from goated_prompter.features.dataset.scene import scene_instruction
from goated_prompter.features.dataset.understanding import DatasetUnderstandingService, understanding_instruction, validate_understanding
from goated_prompter.features.dataset.prompting import dataset_instruction
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import saved_scene, valid_draft


class DatasetUnderstandingTests(unittest.TestCase):
    def compact_brief(self, **changes):
        return {"requested_generation": "Two athletes practice a controlled grappling throw.",
            "character_count": 2, "identity_policy": "random_per_prompt",
            "requirements": [], "expansion_freedom": "Expand only the scoped free choices.",
            "physical_conflicts": [], "clarifications": [], **changes}

    def test_understanding_requests_minified_generation_without_shortening_facts_or_literals(self):
        trigger = 'Mira: blue hair\nHana: crystal wings'
        subject = 'Two athletes hold a sign reading "NO  ENTRY".'
        data = valid_draft(subject=subject, trigger_type="Multiple characters", trigger=trigger)
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Return ONLY one minified JSON object on a single line", rules)
        self.assertIn("No indentation or optional whitespace outside string values", rules)
        self.assertIn("Preserve whitespace and literal text inside strings", rules)
        self.assertIn("Formatting compaction must not omit facts or change qualifiers", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], subject)
        self.assertEqual(json.loads(instruction.user_message)["source"]["trigger"], trigger)
        self.assertEqual(instruction.max_tokens, 4096)
        self.assertEqual(instruction.hard_max_tokens, 4096)
        self.assertEqual(instruction.json_schema["properties"]["requirements"]["properties"]["hard"]["maxItems"], 23)
        self.assertEqual(instruction.temperature, .15)
        self.assertEqual(instruction.top_p, .85)

    def test_understanding_requests_semantic_brevity_without_smaller_fact_limits(self):
        data = valid_draft(subject="One red duck and two men travel together as best friends.",
            trigger_type="Multiple characters", trigger="duck, 2 men", source_mode="guided",
            inputs="One shared vehicle chosen once\nAt least one man is blond; show both hands")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("Do not add paraphrases or separate facts already contained in another fact", rules)
        self.assertIn('"one red duck" already specifies its color', rules)
        self.assertIn("Group ordinary unspecified freedoms into a concise category entry", rules)
        self.assertIn("Keep choose-once freedoms separate from per-image freedoms", rules)
        self.assertIn("Do not inventory every possible unspecified trait or setting", rules)
        self.assertIn("The 24-entry limit is a ceiling, not a target", rules)
        source = json.loads(instruction.user_message)
        self.assertEqual(source["source"]["subject"], data["subject"])
        self.assertEqual(source["guided_inputs"][1]["input"], "At least one man is blond; show both hands")
        buckets = instruction.json_schema["properties"]["requirements"]["properties"]
        self.assertEqual({kind: bucket["maxItems"] for kind, bucket in buckets.items()},
            {"hard": 23, "soft": 24, "free": 24, "context": 24})
        self.assertEqual((instruction.max_tokens, instruction.hard_max_tokens), (4096, 4096))

    def test_categorical_freedoms_keep_local_and_choose_once_policies_through_approval(self):
        data = valid_draft(subject="One red duck and two men travel together as best friends.",
            trigger_type="Multiple characters", trigger="duck, 2 men", source_mode="guided",
            inputs="Choose one shared vehicle once and keep it across images\nShow both men's hands; at least one is blond")
        hard = [{"scope": "all_outputs", "text": "Exactly one red duck and two male humans.", "sections": ["fixed"]},
            {"scope": "all_outputs", "text": "The duck and two men travel together as best friends.", "sections": ["interactions"]},
            {"scope": "all_outputs", "text": "Photorealistic visual style.", "sections": ["fixed"]},
            {"scope": "guided:1", "text": "Keep the chosen vehicle the same across this input's images.", "sections": ["fixed"]},
            {"scope": "guided:2", "text": "Show both men's hands; at least one man is blond, not necessarily both.",
                "sections": ["visible_evidence", "rules"]}]
        free = [{"scope": "all_outputs", "text": "Unspecified clothing, setting and composition remain open per image.",
                "sections": ["may_vary"]},
            {"scope": "guided:1", "text": "Choose the shared vehicle once, not independently per image.", "sections": ["may_vary"]},
            {"scope": "guided:2", "text": "This input's background remains open per image.", "sections": ["may_vary"]}]
        compact = self.compact_brief(character_count=3, requested_generation=data["subject"],
            requirements={"hard": hard, "soft": [], "free": free, "context": []})
        before = deepcopy(compact)
        result = self.run_response(json.dumps(compact, separators=(",", ":")), data)
        self.assertEqual(result["hard"][:-1], [{"scope": item["scope"], "text": item["text"]} for item in hard])
        self.assertEqual(result["free"], [{"scope": item["scope"], "text": item["text"]} for item in free])
        self.assertEqual(result["may_vary"], result["free"])
        self.assertTrue(result["hard"][-1]["text"].endswith(data["trigger"]))
        self.assertEqual(compact, before)
        tickets = DatasetIntentTickets()
        token = tickets.register(data, result)["confirmation_token"]
        self.assertEqual(tickets.approve(token, data), result)

    def test_minified_and_pretty_responses_preserve_identical_scoped_facts_and_string_whitespace(self):
        text = 'Show the sign reading "NO  ENTRY"; the caption has a tab\tand a line break\nthen caf\u00e9.'
        brief = self.compact_brief(requirements={"hard": [
            {"scope": "guided:1", "text": text, "sections": ["rules", "visible_evidence"]}],
            "soft": [], "free": [], "context": []})
        data = valid_draft(source_mode="guided", inputs="A sign\nTwo strangers",
            trigger_type="Multiple characters", trigger='Mira: blue hair\nHana: crystal wings')
        minified = json.dumps(brief, ensure_ascii=False, separators=(",", ":"))
        pretty = json.dumps(brief, ensure_ascii=False, indent=2)
        compact_result = self.run_response(minified, data)
        self.assertEqual(compact_result, self.run_response(pretty, data))
        self.assertEqual(compact_result["hard"][0], {"scope": "guided:1", "text": text})
        self.assertEqual(compact_result["visible_evidence"][0]["text"], text)
        self.assertEqual(compact_result["hard"][-1]["text"].split("Supplied character trigger (verbatim):\n")[1], data["trigger"])
        tickets = DatasetIntentTickets()
        token = tickets.register(data, compact_result)["confirmation_token"]
        self.assertEqual(tickets.approve(token, data), compact_result)

    def test_generation_schema_reserves_the_character_source_slot_without_limiting_other_kinds(self):
        for subject_type, trigger, hard_limit in (("Multiple characters", "athlete_1, athlete_2", 23),
                ("Multiple characters", "", 24), ("Character", "athlete_1", 24)):
            with self.subTest(subject_type=subject_type, trigger=trigger):
                schema = understanding_instruction(valid_draft(trigger_type=subject_type, trigger=trigger)).json_schema
                requirements = schema["properties"]["requirements"]
                self.assertEqual(requirements["type"], "object")
                self.assertEqual(set(requirements["required"]), {"hard", "soft", "free", "context"})
                self.assertIs(requirements["additionalProperties"], False)
                for kind in ("hard", "soft", "free", "context"):
                    bucket = requirements["properties"][kind]
                    self.assertEqual(bucket["maxItems"], hard_limit if kind == "hard" else 24)
                    self.assertEqual(bucket["items"]["required"], ["scope", "text", "sections"])

    def test_cross_authority_tags_reproduce_the_reported_error_without_retrying(self):
        data = valid_draft(subject="Three young adult men dancing together.",
            trigger_type="Multiple characters", trigger="3 male must be 20 yo")
        buckets = {"hard": [], "soft": [], "free": [], "context": []}
        cases = (("free", "fixed"), ("soft", "rules"), ("hard", "may_vary"), ("context", "interactions"))
        for kind, tag in cases:
            with self.subTest(kind=kind, tag=tag):
                brief = self.compact_brief(character_count=3, requirements={**buckets, kind: [
                    {"scope": "all_outputs", "text": "Exactly three young adult men dance together.", "sections": [tag]}]})
                with self.assertRaisesRegex(BackendGenerationError,
                        "Compact review sections must preserve their requirement authority.*No generation started"):
                    self.run_response(json.dumps(brief), data)

    def test_generation_schema_prevents_cross_authority_review_tags(self):
        instruction = understanding_instruction(valid_draft(trigger_type="Multiple characters",
            trigger="3 male must be 20 yo", source_mode="guided", inputs="Three men dance\nThree men rest"))
        buckets = instruction.json_schema["properties"]["requirements"]["properties"]
        expected_tags = {"hard": {"fixed", "must_vary", "rules", "visible_evidence", "interactions",
                "natural_occlusions", "visibility_to_preserve", "action_options"},
            "soft": set(), "free": {"may_vary"}, "context": {"natural_occlusions"}}
        for kind, tags in expected_tags.items():
            with self.subTest(kind=kind):
                sections = buckets[kind]["items"]["properties"]["sections"]
                self.assertEqual(sections["maxItems"], len(tags))
                if tags:
                    self.assertEqual(set(sections["items"]["enum"]), tags)
                self.assertEqual(sections.get("minItems", 0), 1 if kind == "context" else 0)
        self.assertEqual(buckets["hard"]["maxItems"], 23)
        self.assertEqual(buckets["free"]["items"]["properties"]["scope"]["enum"],
            ["all_outputs", "dataset", "guided:1", "guided:2"])

    def test_every_distinct_generated_tag_combination_preserves_scoped_authority(self):
        data = valid_draft(source_mode="guided", inputs="Three men dancing", trigger_type="Character", trigger="")
        buckets = understanding_instruction(data).json_schema["properties"]["requirements"]["properties"]
        entry = {"scope": "guided:1", "text": "A scoped fact with its original qualifiers."}
        for kind, bucket in buckets.items():
            schema = bucket["items"]["properties"]["sections"]
            tags = schema["items"].get("enum", []) if schema["maxItems"] else []
            for size in range(schema.get("minItems", 0), schema["maxItems"] + 1):
                for sections in combinations(tags, size):
                    with self.subTest(kind=kind, sections=sections):
                        requirements = {"hard": [], "soft": [], "free": [], "context": []}
                        requirements[kind] = [{**entry, "sections": list(sections)}]
                        result = self.run_response(json.dumps(self.compact_brief(requirements=requirements)), data)
                        for authority in ("hard", "soft", "free"):
                            self.assertEqual(result[authority], [entry] if authority == kind else [])
                        for section in ("fixed", "may_vary", "must_vary", "rules", "visible_evidence",
                                "interactions", "natural_occlusions", "visibility_to_preserve", "action_options"):
                            self.assertEqual(result[section], [entry] if section in sections else [])

    def test_dancing_brief_keeps_counts_approximate_age_and_free_choices_through_approval(self):
        data = valid_draft(subject="Three men dancing together.", trigger_type="Multiple characters",
            trigger="3 male must be 20 yo")
        hard = [{"scope": "all_outputs", "text": "Exactly three male characters, approximately 20 years old.",
                "sections": ["fixed", "rules"]},
            {"scope": "all_outputs", "text": "The three characters dance together.", "sections": ["interactions"]},
            {"scope": "all_outputs", "text": "Photorealistic visual style.", "sections": ["fixed"]}]
        free = [{"scope": "all_outputs", "text": "Unspecified dance style, setting and clothing remain open choices.",
            "sections": ["may_vary"]}]
        compact = self.compact_brief(character_count=3, requested_generation=data["subject"],
            requirements={"hard": hard, "soft": [], "free": free, "context": []})
        result = self.run_response(json.dumps(compact, separators=(",", ":")), data)
        self.assertEqual(result["character_count"], 3)
        self.assertEqual(result["hard"][:-1], [{"scope": item["scope"], "text": item["text"]} for item in hard])
        self.assertEqual(result["free"], [{"scope": free[0]["scope"], "text": free[0]["text"]}])
        self.assertEqual(result["may_vary"], result["free"])
        self.assertEqual(result["visible_evidence"], [])
        self.assertTrue(result["hard"][-1]["text"].endswith(data["trigger"]))
        tickets = DatasetIntentTickets()
        token = tickets.register(data, result)["confirmation_token"]
        self.assertEqual(tickets.approve(token, data), result)

    def test_grouped_compact_boundary_keeps_all_facts_and_the_complete_character_source(self):
        hard = [{"scope": "guided:1" if index % 2 else "all_outputs",
            "text": f"Athlete obligation {index}, including its qualifier.", "sections": []}
            for index in range(23)]
        soft = [{"scope": "all_outputs", "text": f"Preference {index}.", "sections": []}
            for index in range(24)]
        free = [{"scope": "dataset", "text": f"Choose shared detail {index} once.", "sections": ["may_vary"]}
            for index in range(24)]
        context = [{"scope": "guided:1", "text": f"Natural overlap {index}.", "sections": ["natural_occlusions"]}
            for index in range(24)]
        compact = self.compact_brief(requirements={"hard": hard, "soft": soft, "free": free, "context": context})
        before = deepcopy(compact)
        data = valid_draft(trigger_type="Multiple characters", trigger="Mira: blue hair\nHana: crystal wings",
            source_mode="guided", inputs="Two athletes grapple")
        result = self.run_response(json.dumps(compact), data)
        self.assertEqual(result["hard"][:-1], [{"scope": item["scope"], "text": item["text"]} for item in hard])
        self.assertEqual(result["soft"], [{"scope": item["scope"], "text": item["text"]} for item in soft])
        self.assertEqual(result["free"], [{"scope": item["scope"], "text": item["text"]} for item in free])
        self.assertEqual(result["natural_occlusions"], [{"scope": item["scope"], "text": item["text"]} for item in context])
        self.assertEqual(result["hard"][-1]["text"].split("Supplied character trigger (verbatim):\n")[1], data["trigger"])
        self.assertEqual(len(result["hard"]), 24)
        self.assertEqual(compact, before)
        ticket = DatasetIntentTickets()
        token = ticket.register(data, result)["confirmation_token"]
        self.assertEqual(ticket.approve(token, data), result)

    def test_grouped_compact_rejects_missing_buckets_extra_kind_fields_and_overflow_without_retries(self):
        fact = {"scope": "all_outputs", "text": "Required fact.", "sections": []}
        buckets = {"hard": [fact], "soft": [], "free": [], "context": []}
        invalid = [{**buckets, "hard": [{**fact, "kind": "free"}]},
            {**buckets, "hard": [fact] * 25}, {**buckets, "soft": [fact] * 25},
            {**buckets, "extra": []}, {**buckets, "hard": "fact"}]
        missing = dict(buckets)
        del missing["context"]
        invalid.append(missing)
        for requirements in invalid:
            with self.subTest(requirements=requirements), self.assertRaises(BackendGenerationError):
                self.run_response(json.dumps(self.compact_brief(requirements=requirements)))

    def test_compact_facts_expand_once_into_the_existing_scoped_review_and_contract(self):
        facts = [
            {"scope": "all_outputs", "text": "Both athletes wear gloves; at least one is blond.",
             "kind": "hard", "sections": ["fixed", "rules"]},
            {"scope": "guided:1", "text": "Punch or block, not both together.",
             "kind": "hard", "sections": ["action_options", "interactions"]},
            {"scope": "guided:1", "text": "Show both gloved hands despite their overlap.",
             "kind": "hard", "sections": ["visible_evidence", "visibility_to_preserve"]},
            {"scope": "all_outputs", "text": "Prefer warm lighting.", "kind": "soft", "sections": []},
            {"scope": "dataset", "text": "Choose the setup once and share it across images.",
             "kind": "free", "sections": ["may_vary"]},
            {"scope": "dataset", "text": "Vary the combat dynamic across images.",
             "kind": "hard", "sections": ["must_vary"]},
            {"scope": "guided:1", "text": "Raised gloves may obscure faces.",
             "kind": "context", "sections": ["natural_occlusions"]},
        ]
        compact = self.compact_brief(identity_policy="mixed", requirements=facts)
        before = deepcopy(compact)
        data = valid_draft(source_mode="guided", inputs="Punch or block\nTwo strangers",
            amount=10, target="Krea 2", length="Maximum Detail")
        result = self.run_response(json.dumps(compact), data)
        entries = [{"scope": fact["scope"], "text": fact["text"]} for fact in facts]
        expected = dataset_understanding_fixture(
            requested_generation=compact["requested_generation"], character_count=2, identity_policy="mixed",
            expansion_freedom=compact["expansion_freedom"],
            dataset_contents="10 image prompts; target: Krea 2; detail: Maximum Detail.",
            hard=[entries[0], entries[1], entries[2], entries[5]], soft=[entries[3]], free=[entries[4]],
            fixed=[entries[0]], rules=[entries[0]], action_options=[entries[1]], interactions=[entries[1]],
            visible_evidence=[entries[2]], visibility_to_preserve=[entries[2]], may_vary=[entries[4]],
            must_vary=[entries[5]], natural_occlusions=[entries[6]])
        self.assertEqual(result, expected)
        self.assertEqual(compact, before)
        self.assertEqual(validate_understanding(result, ("all_outputs", "dataset", "guided:1", "guided:2")), result)
        tickets = DatasetIntentTickets()
        token = tickets.register(data, result)["confirmation_token"]
        self.assertEqual(tickets.approve(token, data), result)
        approved = {**data, "_confirmed_intent": tickets.approve(token, data)}
        equivalent = {**data, "_confirmed_intent": expected}
        assignment = dataset_assignments(approved)[0]
        row = saved_scene(input=assignment["input"])
        request = GoatedPrompterRequest(idea=data["subject"])
        self.assertEqual(ideas_instruction(approved, dataset_assignments(approved)),
            ideas_instruction(equivalent, dataset_assignments(equivalent)))
        self.assertEqual(scene_instruction(approved, assignment, row), scene_instruction(equivalent, assignment, row))
        self.assertEqual(dataset_instruction(request, approved, 1, plan_item=row),
            dataset_instruction(request, equivalent, 1, plan_item=row))
        result["hard"][0]["text"] = "changed"
        self.assertNotEqual(result["fixed"][0]["text"], "changed")

    def test_compact_conflicts_keep_clarifications_and_do_not_gain_approval(self):
        conflict = {"scope": "guided:1", "conflict": "Eyes-only crop excludes shoes.",
            "compatible_resolution": None}
        compact = self.compact_brief(physical_conflicts=[conflict],
            clarifications=["Should the crop show only eyes, or also shoes?"])
        data = valid_draft(source_mode="guided", inputs="Eyes only, with shoes visible")
        result = self.run_response(json.dumps(compact), data)
        self.assertEqual(result["physical_conflicts"], [conflict])
        self.assertEqual(result["clarifications"], compact["clarifications"])
        self.assertEqual(DatasetIntentTickets().register(data, result)["confirmation_token"], "")
        compact["clarifications"] = []
        with self.assertRaisesRegex(BackendGenerationError, "require clarification"):
            self.run_response(json.dumps(compact), data)

    def test_compact_response_rejects_unknown_tags_scopes_and_demoted_obligations(self):
        fact = {"scope": "all_outputs", "text": "Two athletes.", "kind": "hard", "sections": ["fixed"]}
        invalid = [{**fact, **change} for change in (
            {"scope": "guided:99"}, {"kind": "unknown"}, {"text": ""}, {"sections": "fixed"},
            {"sections": ["unknown"]}, {"sections": ["fixed", "fixed"]}, {"extra": True},
            {"kind": "soft"}, {"kind": "context"}, {"sections": ["may_vary"]})]
        invalid.append({**fact, "kind": "context", "sections": []})
        for entry in invalid:
            with self.subTest(entry=entry), self.assertRaises(BackendGenerationError):
                self.run_response(json.dumps(self.compact_brief(requirements=[entry])))
        for changes in ({"requirements": {}}, {"extra": []}, {"dataset_contents": "invented settings"}):
            with self.subTest(changes=changes), self.assertRaises(BackendGenerationError):
                self.run_response(json.dumps(self.compact_brief(**changes)))

    def test_compact_source_slot_and_per_section_limits_remain_strict(self):
        fact = {"scope": "all_outputs", "text": "Requirement.", "kind": "hard", "sections": ["fixed"]}
        data = valid_draft(trigger_type="Multiple characters", trigger="athlete_1, athlete_2")
        result = self.run_response(json.dumps(self.compact_brief(requirements=[fact])), data)
        self.assertEqual(result["hard"][0], {"scope": fact["scope"], "text": fact["text"]})
        self.assertIn(data["trigger"], result["hard"][-1]["text"])
        facts = [{**fact, "text": f"Requirement {index}."} for index in range(24)]
        with self.assertRaisesRegex(BackendGenerationError, "leave one HARD entry"):
            self.run_response(json.dumps(self.compact_brief(requirements=facts)), data)
        with self.assertRaisesRegex(BackendGenerationError, "fixed must be an array"):
            self.run_response(json.dumps(self.compact_brief(requirements=facts + [{**fact, "text": "Extra."}])))
        with self.assertRaisesRegex(BackendGenerationError, "hard must be an array"):
            self.run_response(json.dumps(self.compact_brief(requirements=[{**item, "sections": []}
                for item in facts + [{**fact, "text": "Extra."}]])))

    def test_compact_object_zero_normalization_is_preserved(self):
        data = valid_draft(trigger_type="Object / product")
        result = self.run_response(json.dumps(self.compact_brief(character_count=0,
            identity_policy="not_applicable")), data)
        self.assertIsNone(result["character_count"])
        self.assertEqual(result["dataset_contents"], "12 image prompts; target: Generic; detail: Medium.")

    def test_multiple_character_source_survives_a_lossy_brief_before_review(self):
        trigger = "2 girls, mira, (blue hair:1.2), bat wings, bat wings, hana, blonde hair, crystal wings"
        data = valid_draft(trigger_type="Multiple characters", trigger=trigger,
            subject="Mira on the left reads with Hana on the right. Their appearance may be naturally hidden.")
        brief = dataset_understanding_fixture(character_count=2, identity_policy="fixed", hard=[
            {"scope": "all_outputs", "text": "Mira and Hana read together."}])
        before = deepcopy(brief)
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["hard"][:-1], before["hard"])
        requirement = result["hard"][-1]
        self.assertEqual(requirement["scope"], "all_outputs")
        self.assertEqual(requirement["text"].split("Supplied character trigger (verbatim):\n", 1)[1], trigger)
        self.assertIn("ownership", requirement["text"])
        self.assertIn("not a visibility requirement", requirement["text"])
        self.assertEqual(result["visible_evidence"], [])
        self.assertEqual(brief, before)
        self.assertEqual(set(result), set(brief))

    def test_source_requirement_preserves_identifier_only_mixed_and_local_identity_policies(self):
        data = valid_draft(trigger_type="Multiple characters", trigger="person_1, person_2",
            source_mode="guided", inputs="Mira with a different partner\nTwo strangers")
        brief = dataset_understanding_fixture(identity_policy="mixed", character_count=None,
            hard=[{"scope": "guided:1", "text": "Mira is fixed; her partner's identity is random."}],
            free=[{"scope": "guided:2", "text": "Random identities for both people."}])
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["identity_policy"], "mixed")
        self.assertIsNone(result["character_count"])
        self.assertEqual(result["hard"][0], brief["hard"][0])
        self.assertEqual(result["free"], brief["free"])
        self.assertEqual(result["fixed"], [])
        self.assertEqual(result["visible_evidence"], [])
        self.assertIn("identifiers alone invent neither appearance nor fixed identity", result["hard"][-1]["text"])

    def test_source_requirement_keeps_named_blocks_weights_and_the_full_trigger_boundary(self):
        trigger = "Mira: (blue hair:1.2), bat wings, bat wings\n\nHana: blonde hair, crystal wings, "
        trigger += "x" * (1000 - len(trigger))
        result = self.run_response(json.dumps(dataset_understanding_fixture()),
            valid_draft(trigger_type="Multiple characters", trigger=trigger))
        self.assertEqual(result["hard"][-1]["text"].split("Supplied character trigger (verbatim):\n", 1)[1], trigger)

    def test_source_requirement_does_not_duplicate_an_already_grounded_fresh_brief(self):
        data = valid_draft(trigger_type="Multiple characters", trigger="Mira, blue hair, Hana, blonde hair")
        grounded = self.run_response(json.dumps(dataset_understanding_fixture()), data)
        self.assertEqual(self.run_response(json.dumps(grounded), data), grounded)

    def test_source_requirement_preserves_other_types_and_never_drops_hard_entries_to_fit(self):
        brief = dataset_understanding_fixture(hard=[{"scope": "all_outputs", "text": f"Requirement {index}."}
            for index in range(24)])
        for subject_type in ("Character", "Animal", "Object / product", "Visual style", "Custom"):
            with self.subTest(subject_type=subject_type):
                self.assertEqual(self.run_response(json.dumps(brief), valid_draft(trigger_type=subject_type)), brief)
        data = valid_draft(trigger_type="Multiple characters", trigger="Mira, blue hair, Hana, blonde hair")
        with self.assertRaisesRegex(BackendGenerationError, "leave one HARD entry.*No generation started"):
            self.run_response(json.dumps(brief), data)
        brief["hard"].pop()
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result["hard"][:-1], brief["hard"])
        self.assertEqual(len(result["hard"]), 24)

    def test_hard_soft_free_contract_is_validated_without_promoting_generated_choices(self):
        brief = dataset_understanding_fixture(
            hard=[{"scope": "all_outputs", "text": "One red ceramic cup; its base touching the table is visible."}],
            soft=[{"scope": "all_outputs", "text": "Prefer a close camera and warm lighting."}],
            free=[{"scope": "all_outputs", "text": "Background and exact camera angle."}])
        self.assertEqual(validate_understanding(brief, ("all_outputs", "dataset")), brief)
        instruction = understanding_instruction(valid_draft(subject="One red cup on a table."))
        self.assertIn("hard: user requirements", instruction.system_message)
        self.assertIn("soft: preferences", instruction.system_message)
        self.assertIn("free: unspecified", instruction.system_message)

    def test_contract_categories_require_explicit_scoped_bounded_arrays(self):
        for field in ("hard", "soft", "free"):
            for invalid in (None, "cup", ["cup"], [{"scope": "guided:99", "text": "Cup"}],
                    [{"scope": "all_outputs", "text": "Cup", "approved": True}],
                    [{"scope": "all_outputs", "text": ""}],
                    [{"scope": "all_outputs", "text": "x" * 2001}],
                    [{"scope": "all_outputs", "text": "Cup"}] * 25):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    validate_understanding(dataset_understanding_fixture(**{field: invalid}), ("all_outputs", "dataset"))
            legacy = dataset_understanding_fixture()
            del legacy[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_understanding(legacy, ("all_outputs", "dataset"))

    def test_shared_unspecified_choices_are_choose_once_not_per_image_freedom(self):
        data = valid_draft(subject="A crew working on one shared stunt setup. Choose the setup freely, but keep it the same throughout the dataset.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("keep that freedom dataset-scoped", rules)
        self.assertIn("may choose it once, but must not independently choose a different value per image", rules)
        self.assertIn("dataset-scoped free/may_vary", rules)
        self.assertIn("shared-consistency obligation in hard and fixed without inventing a value", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_fixed_and_unspecified_human_identities_explicitly_require_mixed_policy(self):
        data = valid_draft(subject="Alex is the same performer in every image; the two other crew members are random people.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("If some identities are explicitly fixed while other human identities remain unspecified/random, identity_policy is mixed, not fixed", rules)
        self.assertIn("Partial identity locks do not fix every other trait", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_naturally_hidden_fixed_traits_are_not_demanded_visible_evidence(self):
        data = valid_draft(subject="The same performer has a back tattoo and a shoulder scar; neither needs to be visible.")
        instruction = understanding_instruction(data)
        rules = " ".join(instruction.system_message.split())
        self.assertIn("visible_evidence contains only features the user actually requires to be visibly demonstrated", rules)
        self.assertIn("A fixed identity trait that may naturally be hidden is not demanded visible evidence", rules)
        self.assertIn("Keep it fixed without forcing later stages to expose it", rules)
        self.assertEqual(json.loads(instruction.user_message)["source"]["subject"], data["subject"])

    def test_user_written_style_requirements_still_reach_understanding(self):
        data = valid_draft(subject="A cup in ink wash.", constraints="Keep ink wash rendering in every image.")
        instruction = understanding_instruction(data)
        source = json.loads(instruction.user_message)["source"]
        self.assertEqual(source["subject"], data["subject"])
        self.assertEqual(source["constraints"], data["constraints"])

    def test_scoped_contract_and_user_conflicts_survive_one_understanding_call(self):
        brief = dataset_understanding_fixture(
            hard=[{"scope": "guided:1", "text": "Extreme close-up of only his eyes."},
                  {"scope": "guided:1", "text": "Show his shoes clearly in the same image."}],
            soft=[{"scope": "all_outputs", "text": "Warm lighting."}],
            free=[{"scope": "guided:2", "text": "Background."}],
            physical_conflicts=[{"scope": "guided:1", "conflict": "Eyes-only crop excludes shoes.",
                                 "compatible_resolution": None}],
            clarifications=["Should the crop show only eyes, or also the shoes?"])
        data = valid_draft(source_mode="guided", inputs="Eyes only, with shoes visible\nA cup")
        self.assertEqual(self.run_response(json.dumps(brief), data), brief)

    def run_response(self, raw, data=None):
        backend, session = Mock(), Mock()
        backend.generation_session.return_value = nullcontext(session)
        session.generate.return_value = raw
        service = DatasetUnderstandingService({"backend": "mock"}, lambda: None)
        with patch("goated_prompter.features.dataset.understanding.create_backend", return_value=backend):
            try:
                return service.run(GoatedPrompterRequest(idea="A synthetic cup"),
                                   valid_draft() if data is None else data, lambda _message: None)
            finally:
                session.generate.assert_called_once()

    def test_valid_brief_accepts_one_json_fence_without_another_model_call(self):
        brief = dataset_understanding_fixture()
        raw = json.dumps(brief)
        for value in (raw, "```json\n" + raw + "\n```", "```\n" + raw + "\n```", "\ufeff" + raw):
            with self.subTest(wrapper=value[:10]):
                self.assertEqual(self.run_response(value), brief)

    def test_richer_count_identity_and_scoped_action_options_survive_validation(self):
        brief = dataset_understanding_fixture(character_count=2, identity_policy="random_per_prompt",
            fixed=[{"scope": "all_outputs", "text": "Two adults; at least one has blond hair, not necessarily both."}],
            may_vary=[{"scope": "dataset", "text": "Different people across images; preserve each identity within its image."}],
            action_options=[{"scope": "guided:2", "text": "Punch or block; alternatives, not simultaneous actions."}])
        validated = validate_understanding(brief, ("all_outputs", "dataset", "guided:1", "guided:2"))
        self.assertEqual(validated, brief)
        self.assertEqual(validate_understanding(dataset_understanding_fixture(), ("all_outputs", "dataset")),
            dataset_understanding_fixture())

    def test_object_understanding_explicitly_uses_null_not_zero_characters(self):
        instruction = understanding_instruction(valid_draft(subject="A chipped blue ceramic cup.",
            trigger_type="Object / product"))
        self.assertIn('"character_count": null, "identity_policy": "not_applicable"', instruction.system_message)
        self.assertIn("Never use 0", instruction.system_message)
        source = json.loads(instruction.user_message)["source"]
        self.assertEqual(source["trigger_type"], "Object / product")
        self.assertEqual(source["subject"], "A chipped blue ceramic cup.")

    def test_trigger_label_is_not_image_lettering_or_a_negative_start_rule(self):
        instruction = understanding_instruction(valid_draft(trigger="eval_subject", trigger_at_start=False))
        self.assertIn("not visible image lettering", instruction.system_message)
        self.assertIn("trigger_at_start=false does not forbid", instruction.system_message)
        self.assertEqual(json.loads(instruction.user_message)["source"]["trigger"], "eval_subject")

    def test_richer_identity_and_action_metadata_still_rejects_invalid_types_and_scopes(self):
        for changes in ({"character_count": True}, {"character_count": 0}, {"character_count": 101},
                        {"identity_policy": []}, {"identity_policy": "same random person"},
                        {"action_options": "punch"}, {"action_options": [{"scope": "guided:9", "text": "Punch"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_understanding(dataset_understanding_fixture(**changes), ("all_outputs", "dataset"))

    def test_empty_prose_truncated_multiple_or_invalid_briefs_never_proceed(self):
        brief = json.dumps(dataset_understanding_fixture())
        invalid = ("", "  ", None, "Here is the brief:\n" + brief,
            brief + "\nAnother object: " + brief, "```json\n" + brief,
            "<think>Analyze the request.</think>\n" + brief, "[]", "{}",
            brief.replace('"fixed": []', '"fixed": [], "fixed": []'))
        for raw in invalid:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(BackendGenerationError):
                self.run_response(raw)

    def test_empty_response_has_a_specific_error_without_a_fabricated_brief(self):
        with self.assertRaisesRegex(BackendGenerationError, "empty.*No generation started"):
            self.run_response("  ")

    def test_object_response_canonicalizes_integer_zero_without_another_model_call(self):
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable",
            requested_generation="A chipped blue ceramic cup on a wooden table.")
        data = {**valid_draft(), "subject": "A chipped blue ceramic cup on a wooden table.",
                "trigger_type": "Object / product"}
        result = self.run_response(json.dumps(brief), data)
        self.assertEqual(result, {**brief, "character_count": None})
        self.assertEqual(brief["character_count"], 0)

    def test_object_count_normalization_does_not_relax_invalid_counts_or_identity(self):
        data = {**valid_draft(), "trigger_type": "Object / product"}
        invalid = [(count, "not_applicable") for count in (False, 0.0, "0", -1, 101)]
        invalid.extend((0, policy) for policy in ("fixed", "random_per_prompt", "mixed"))
        for count, policy in invalid:
            with self.subTest(count=count, policy=policy), self.assertRaises(BackendGenerationError):
                self.run_response(json.dumps(dataset_understanding_fixture(
                    character_count=count, identity_policy=policy)), data)

    def test_non_object_response_still_rejects_zero_even_with_not_applicable_identity(self):
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable")
        with self.assertRaises(BackendGenerationError):
            self.run_response(json.dumps(brief), {**valid_draft(), "trigger_type": "Character"})

    def test_object_count_normalization_preserves_valid_counts_and_other_validation(self):
        data = {**valid_draft(), "trigger_type": "Object / product"}
        for count in (None, 1, 100):
            brief = dataset_understanding_fixture(character_count=count, identity_policy="not_applicable")
            with self.subTest(count=count):
                self.assertEqual(self.run_response(json.dumps(brief), data), brief)
        brief = dataset_understanding_fixture(character_count=0, identity_policy="not_applicable",
            fixed=[{"scope": "guided:99", "text": "A cup."}])
        with self.assertRaises(BackendGenerationError):
            self.run_response(json.dumps(brief), data)

    def test_understanding_requests_llama_json_decoding_only_for_its_model_call(self):
        instruction = understanding_instruction(valid_draft())
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(dataset_understanding_fixture())}}]}).encode()
        for owned, json_output in ((True, True), (False, True), (True, False)):
            with self.subTest(owned_llama=owned, json_output=json_output):
                backend = OpenAICompatibleBackend({"base_url": "http://127.0.0.1:8189/v1", "model": "synthetic",
                    "_is_llama_cpp": owned})
                with (patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send,
                      patch("goated_prompter.backends.openai_compatible.log_request"),
                      patch("goated_prompter.backends.openai_compatible.log_response")):
                    backend.generate(replace(instruction, json_output=json_output))
                send.assert_called_once()
                payload = json.loads(send.call_args.args[0].data)
                if owned and json_output:
                    self.assertEqual(payload.get("response_format"), {"type": "json_schema", "json_schema": {
                        "name": "response", "strict": True, "schema": instruction.json_schema}})
                else:
                    self.assertNotIn("response_format", payload)

    def test_fresh_and_reused_local_sessions_send_identical_understanding_requests(self):
        config = LlamaCppLaunchConfig(executable=Path("synthetic-llama-server"), model_path=Path("model.gguf"),
            mmproj_path=Path("mmproj.gguf"), host="127.0.0.1", port=8189, context_size=32768,
            image_min_tokens=1024, gpu_layers="auto", reasoning="off", keep_model_loaded=True,
            max_tokens=768, timeout=180, startup_timeout=180, temperature=.7,
            alias="synthetic", requested_model="Synthetic model")
        owned = SimpleNamespace(config=replace(config, port=8190), process=SimpleNamespace(pid=42))
        manager = Mock()
        manager.acquire.side_effect = [(owned, {"reused": False, "restarted": False}),
            (owned, {"reused": True, "restarted": False})]
        with patch.object(LlamaCppLaunchConfig, "from_mapping", return_value=config):
            backend = LocalLlamaCppBackend({}, process_manager=manager)
        raw = json.dumps(self.compact_brief())
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"choices": [{"finish_reason": "stop",
            "message": {"content": raw}}]}).encode()
        data = valid_draft(subject="One red duck and two men travel together as best friends.",
            trigger_type="Multiple characters", trigger="duck, 2 men")
        request = GoatedPrompterRequest(idea=data["subject"])
        service = DatasetUnderstandingService({"backend": "mock"}, lambda: None)
        with (patch("goated_prompter.features.dataset.understanding.create_backend", return_value=backend),
              patch("goated_prompter.backends.openai_compatible.urlopen", return_value=response) as send,
              patch("goated_prompter.backends.openai_compatible.log_request"),
              patch("goated_prompter.backends.openai_compatible.log_response")):
            first = service.run(request, data, lambda _message: None)
            second = service.run(request, data, lambda _message: None)
        self.assertEqual(first, second)
        self.assertEqual(send.call_count, 2)
        outgoing = [json.loads(invocation.args[0].data) for invocation in send.call_args_list]
        self.assertEqual(outgoing[0], outgoing[1])
        self.assertEqual(outgoing[0]["temperature"], .15)
        self.assertEqual(outgoing[0]["top_p"], .85)
        self.assertEqual(outgoing[0]["max_tokens"], 4096)
        self.assertEqual(outgoing[0]["response_format"]["json_schema"]["schema"], understanding_instruction(data).json_schema)
        self.assertEqual([invocation.args[0].full_url for invocation in send.call_args_list],
            ["http://127.0.0.1:8190/v1/chat/completions"] * 2)
        self.assertEqual(manager.acquire.call_args_list, [call(config, include_state=True)] * 2)
        self.assertEqual(manager.release.call_args_list, [call(owned)] * 2)

    def test_understanding_schema_generates_each_fact_once_with_scoped_section_tags(self):
        for subject_type, trigger in (("Character", "token"),
                ("Multiple characters", "Mira, blue hair, Hana, blonde hair"),
                ("Multiple characters", "")):
            with self.subTest(subject_type=subject_type, trigger=trigger):
                instruction = understanding_instruction(valid_draft(trigger_type=subject_type, trigger=trigger,
                    source_mode="guided", inputs="A handshake\n\nA portrait"))
                schema = instruction.json_schema
                self.assertIsNotNone(schema)
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                fields = set(self.compact_brief())
                self.assertEqual(set(schema["required"]), fields)
                self.assertEqual(set(schema["properties"]), fields)
                props = schema["properties"]
                self.assertEqual(props["character_count"], {"type": ["integer", "null"], "minimum": 1, "maximum": 100})
                self.assertEqual(set(props["identity_policy"]["enum"]), {"fixed", "random_per_prompt", "mixed", "not_applicable"})
                requirements = props["requirements"]
                self.assertEqual(requirements["type"], "object")
                self.assertIs(requirements["additionalProperties"], False)
                self.assertEqual(set(requirements["required"]), {"hard", "soft", "free", "context"})
                for kind in ("hard", "soft", "free", "context"):
                    array = requirements["properties"][kind]
                    self.assertEqual(array["maxItems"], 23 if kind == "hard" and subject_type == "Multiple characters" and trigger else 24)
                    item = array["items"]
                    self.assertEqual(set(item["required"]), {"scope", "text", "sections"})
                    self.assertEqual(set(item["properties"]), {"scope", "text", "sections"})
                    self.assertIs(item["additionalProperties"], False)
                    self.assertEqual(item["properties"]["scope"]["enum"], ["all_outputs", "dataset", "guided:1", "guided:2"])
                    sections = item["properties"]["sections"]
                    if kind == "soft":
                        self.assertEqual(sections["maxItems"], 0)
                    else:
                        expected_tags = {"hard": {"fixed", "must_vary", "rules", "visible_evidence", "interactions",
                                "natural_occlusions", "visibility_to_preserve", "action_options"},
                            "free": {"may_vary"}, "context": {"natural_occlusions"}}
                        self.assertEqual(set(sections["items"]["enum"]), expected_tags[kind])
                for field, value in self.compact_brief().items():
                    if isinstance(value, str) and field != "identity_policy":
                        self.assertEqual(props[field], {"type": "string", "minLength": 1, "maxLength": 2000})
                    if not isinstance(value, list) or field == "requirements":
                        continue
                    array = props[field]
                    self.assertEqual(array["type"], "array")
                    self.assertEqual(array["maxItems"], 24)
                    self.assertIsInstance(array["items"], dict)
                    item = array["items"]
                    if field == "clarifications":
                        self.assertEqual(item, {"type": "string", "minLength": 1, "maxLength": 2000})
                        continue
                    self.assertIs(item["additionalProperties"], False)
                    self.assertEqual(item["properties"]["scope"]["enum"], ["all_outputs", "dataset", "guided:1", "guided:2"])
                    expected = {"scope", "conflict", "compatible_resolution"}
                    self.assertEqual(set(item["required"]), expected)
                    self.assertEqual(set(item["properties"]), expected)
                    if field == "physical_conflicts":
                        self.assertEqual(item["properties"]["compatible_resolution"]["type"], ["string", "null"])

    def test_shape_valid_object_with_25_hard_entries_is_rejected_without_retry(self):
        brief = dataset_understanding_fixture(hard=[{"scope": "all_outputs", "text": f"Source requirement {index}."}
            for index in range(25)])
        with self.assertRaisesRegex(BackendGenerationError, "hard must be an array within the understanding limit.*No generation started"):
            self.run_response(json.dumps(brief), valid_draft(trigger_type="Multiple characters", trigger="Mira, Hana"))
