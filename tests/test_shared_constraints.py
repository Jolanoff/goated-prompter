import unittest

from goated_prompter.core import GoatedPrompterRequest, assemble_instruction
from goated_prompter.planning.rule_compiler import compile_rules
from goated_prompter.planning.constraints import compile_request
from goated_prompter.planning.constraint_validation import constraint_issues
from goated_prompter.planning.validation import validate_plan


class SharedConstraintTests(unittest.TestCase):
    def test_structured_facts_have_exact_provenance(self):
        compiled = compile_rules('same short black hair; no hats; no jewelry; outfit can change; sign must say "NO ENTRY"')
        self.assertEqual(compiled["forbidden"], ["hats", "jewelry"])
        self.assertEqual(compiled["variable"], ["outfit"])
        self.assertEqual(compiled["protected_literal"], ["NO ENTRY"])
        hat = next(row for row in compiled["provenance"] if row["value"] == "hats")
        self.assertEqual(hat, {"value": "hats", "kind": "forbidden", "source": "constraints", "source_text": "no hats", "confidence": "high"})
        request = compile_request('same short black hair; prefer soft light; a portrait')
        self.assertEqual(request.required, ('same short black hair',))
        self.assertEqual(request.soft_preferences, ('soft light',))

    def test_ambiguous_visual_negatives_names_and_conditionals_stay_unparsed(self):
        for text in ('no smoking sign', 'No Entry', 'no hats unless raining', 'no one is alone', 'a film titled "No Country"', 'a character named "No Hat"'):
            with self.subTest(text=text):
                self.assertFalse(compile_rules(text)["forbidden"])
                self.assertEqual(compile_request(text).positive_request, text)

    def test_protected_literal_dialogue_and_soft_preferences(self):
        compiled = compile_rules('prefer soft light; no hats; dialogue says "No hats!"')
        self.assertEqual(compiled["soft_preferences"], ["soft light"])
        self.assertEqual(compiled["protected_literal"], ["No hats!"])
        self.assertFalse(constraint_issues('A sign reads "No hats!".', compiled))
        self.assertFalse(constraint_issues('<d>[English] No hats!</d>', compiled))
        self.assertEqual(constraint_issues('A person without hats.', compiled)[0]["code"], "constraint_negative_leakage")
        self.assertEqual(constraint_issues('A person wearing hats.', compiled)[0]["code"], "forbidden_content")
        tagged = compile_rules('<d>[English] No hats!</d>; no jewelry')
        self.assertEqual(tagged["forbidden"], ["jewelry"])
        self.assertEqual(tagged["protected_literal"], ['<d>[English] No hats!</d>'])
        self.assertFalse(constraint_issues('A character named "No Hat".', compiled))
        self.assertEqual(constraint_issues('A hat-shaped cloud.', compiled)[0]["severity"], "warning")

    def test_builder_direct_compiles_exclusions_without_a_planning_call(self):
        instruction = assemble_instruction(GoatedPrompterRequest(idea='A person holds a sign reading "NO ENTRY". no hats', planning_mode="Direct"), text_only=True)
        self.assertNotIn("no hats", instruction.user_message)
        self.assertIn('"forbidden": ["hats"]', instruction.system_message)
        self.assertIn('"NO ENTRY"', instruction.user_message)
        self.assertIn("silently", instruction.system_message)

    def test_planners_reject_actual_forbidden_content_separately_from_exclusion_leakage(self):
        compiled = compile_request("A person running. no hats")
        with self.assertRaisesRegex(ValueError, "forbidden fact"):
            validate_plan('{"primary_action":"A person wearing a hat while running."}', compiled)
        with self.assertRaisesRegex(ValueError, "exclusion"):
            validate_plan('{"primary_action":"A person running without hats."}', compiled)
