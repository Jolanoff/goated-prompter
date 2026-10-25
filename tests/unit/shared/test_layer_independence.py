"""Each part of the writing instructions does its own job: the Mode the task, the target how a prompt is written,
the Style the medium and look, the Director the emphasis, Creativity how much is invented. None carries another's."""

import json
import unittest

from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.builder.service import assemble_instruction
from goated_prompter.options.targets import TARGET_MODEL_NAMES
from goated_prompter.prompting.creativity import CREATIVITY_ADAPTERS
from goated_prompter.prompting.directors import DIRECTOR_PRESETS
from goated_prompter.prompting.modes import MODE_ADAPTERS
from goated_prompter.prompting.styles import resolve_style
from goated_prompter.prompting.target_models import get_model_adapter
from goated_prompter.workflow_output import balance_brackets

# Look words that belong to the Style alone.
LOOK = ("anime", "film grain", "35mm", "golden hour", "depth of field", "bokeh", "cinematic lighting", "8k", "masterpiece")


def message(**changes):
    return assemble_instruction(GoatedPrompterRequest(**{"idea": "two friends talk on a bench", **changes})).system_message


class LayerIndependence(unittest.TestCase):
    def test_targets_directors_and_modes_leave_the_look_to_the_style(self):
        for target in TARGET_MODEL_NAMES:
            for word in LOOK:
                self.assertNotIn(word, get_model_adapter(target).casefold(), target)
        for preset in DIRECTOR_PRESETS:
            for word in LOOK:
                self.assertNotIn(word, preset.instructions.casefold(), preset.label)
        for mode, text in MODE_ADAPTERS.items():
            self.assertNotIn("photograph", text.partition(":")[2].casefold(), mode)  # past the mode's own name

    def test_the_scene_writer_leaves_the_look_to_the_style_and_dresses_each_image(self):
        from goated_prompter.features.dataset.v2.scenes import COMPOSE_SYSTEM
        from goated_prompter.features.dataset.v2.prompts import SCENE_RULES
        from goated_prompter.features.dataset.v2.scenes import SECTIONS, SUBJECT_FIELDS, retire_fields
        self.assertNotIn("lighting", SECTIONS)
        self.assertNotIn("mood", SECTIONS)
        self.assertNotIn("clothing", SUBJECT_FIELDS)
        self.assertIn("camera: what the image shows,", COMPOSE_SYSTEM)
        self.assertIn("his, her or their is always that position's own person", " ".join(COMPOSE_SYSTEM.split()))
        self.assertIn("where that person is in the frame", COMPOSE_SYSTEM)
        self.assertIn("nobody is reduced to a hand, an arm or one body part", " ".join(COMPOSE_SYSTEM.split()))
        self.assertIn("change the arrangement or the viewpoint instead of cropping a person out", " ".join(COMPOSE_SYSTEM.split()))
        # The scene decides the visible clothing and light once (in extras); the final prompt writes them as given.
        self.assertIn("The scene's extras give the clothing and the light: write them as given", " ".join(SCENE_RULES.split()))
        # A live scene dressed the people of the act in shorts and the final prompt kept them, so that garment goes;
        # live final prompts also dressed people the scene left bare.
        self.assertIn("no garment covers it even when the extras give one", " ".join(SCENE_RULES.split()))
        self.assertIn("a person they call bare stays bare with no garment added", " ".join(SCENE_RULES.split()))
        # A live final prompt gave a person an age that neither the scene nor the request gave.
        self.assertIn("Never give anyone an age the idea does not give", " ".join(SCENE_RULES.split()))
        # A live scene put the mouth of the person whose body part the act used on the other's mouth (a kiss).
        self.assertIn("a mouth touches someone only where the actions put it", " ".join(COMPOSE_SYSTEM.split()))
        self.assertEqual(retire_fields({"lighting": "x", "mood": "y", "subjects": {"a": {"clothing": "z", "hair": "h"}}}),
                         {"subjects": {"a": {"hair": "h"}}}, "A scene with retired fields still works.")

    def test_framing_is_shown_by_what_is_visible_not_by_a_shot_name(self):
        from goated_prompter.prompting.base import CORE_SYSTEM_PROMPT
        from goated_prompter.prompting.target_models import MODEL_ADAPTERS
        from goated_prompter.features.dataset.v2.prompts import SCENE_RULES
        self.assertIn("Image models frame by what the prompt says is visible, not by shot names", CORE_SYSTEM_PROMPT)
        self.assertNotIn("one shot size", MODEL_ADAPTERS["Krea 2"])
        self.assertIn("composition shown through what is visible rather than a shot size", MODEL_ADAPTERS["Krea 2"])
        self.assertIn('A shot name or a phrase such as "fully visible" never stands in for that description', " ".join(SCENE_RULES.split()))
        self.assertIn("every body part shown is joined to its owner, who is described in the frame", " ".join(SCENE_RULES.split()))

    def test_two_or_more_people_are_kept_apart_by_every_prose_target(self):
        for target in TARGET_MODEL_NAMES:
            adapter = get_model_adapter(target)
            if target in ("Anima", "MiniMax H3"):
                continue
            self.assertIn("When the image has two or more people", adapter, target)
            self.assertIn("never use the pronoun", adapter, target)
            self.assertIn("say whose it is, its state and how many there are", adapter, target)
        self.assertIn("each character its own sentence with its place in the frame", get_model_adapter("Anima"))

    def test_extra_length_goes_to_the_subjects_before_the_setting(self):
        from goated_prompter.prompting.details import MAXIMUM_DETAIL_GUIDANCE
        self.assertLess(MAXIMUM_DETAIL_GUIDANCE.index("the subjects first"), MAXIMUM_DETAIL_GUIDANCE.index("Only then add the setting"))

    def test_creativity_never_moves_people(self):
        self.assertNotIn("staging", CREATIVITY_ADAPTERS["Balanced"])

    def test_only_creativity_decides_how_much_is_invented(self):
        """Mode, target, Length, Directors, the planner and the Dataset prompt rules each keep their own job; none of
        them says how much may be invented, how long the prompt is or what look it has."""
        from goated_prompter.features.dataset.v2.prompts import SCENE_RULES
        from goated_prompter.features.dataset.v2.scenes import COMPOSE_SYSTEM
        from goated_prompter.planning.scene_planner import AUTHORITY
        from goated_prompter.prompting.base import CORE_SYSTEM_PROMPT, PRIORITY_CONTRACT, TEXT_ONLY_PRIORITY_CONTRACT
        from goated_prompter.prompting.details import LENGTH_ADAPTERS
        from goated_prompter.prompting.target_models import MODEL_ADAPTERS
        guides = {f"Director {preset.label}": preset.instructions for preset in DIRECTOR_PRESETS}
        guides.update({f"Mode {name}": text for name, text in MODE_ADAPTERS.items() if name != "Remix"})
        guides.update({f"Length {name}": text for name, text in LENGTH_ADAPTERS.items()})
        # MiniMax H3 keeps its own reference and dialogue contract (its own tab).
        guides.update({f"Target {name}": text for name, text in MODEL_ADAPTERS.items() if name != "MiniMax H3"})
        guides.update({"core": CORE_SYSTEM_PROMPT, "priority": PRIORITY_CONTRACT, "text priority": TEXT_ONLY_PRIORITY_CONTRACT,
                       "planner": AUTHORITY, "dataset prompt rules": SCENE_RULES, "scene writer": COMPOSE_SYSTEM})
        owned = ("conservativ", "embellish", "overdecorat", "brainstorm", "recast", "look default", "quality default",
                 "invent signage", "invent dialogue", "explicitness", "sanitize", "only when they support")
        for name, text in guides.items():
            for word in owned:
                self.assertNotIn(word, " ".join(text.split()).casefold(), name)
            if name.startswith("Target"):
                self.assertNotIn("exhaustive", text, f"{name}: how long the prompt is belongs to Length")
        for level in CREATIVITY_ADAPTERS.values():
            self.assertIn("Never add or replace a subject or an act", level)
        self.assertIn("Avoid the most obvious way to show it", CREATIVITY_ADAPTERS["Creative"])
        self.assertIn("decide boldly", CREATIVITY_ADAPTERS["Dice"])

    def test_abstract_words_become_signs_without_examples(self):
        from goated_prompter.features.dataset.v2.scenes import _system
        from goated_prompter.prompting.base import SHOW_DONT_TELL
        self.assertIn(SHOW_DONT_TELL, message())
        self.assertIn(SHOW_DONT_TELL, _system({"path": "sfw_character", "characters": [], "input": {},
                                               "settings": {"style": "Auto", "creativity": "Balanced"}}, []))
        for level in ("Strict", "Balanced"):
            self.assertIn("only when the request asks for them", CREATIVITY_ADAPTERS[level])
            self.assertNotIn("written on a prop", CREATIVITY_ADAPTERS[level])
        for level in ("Creative", "Dice"):
            self.assertIn("may come from the request's own words or meaning", CREATIVITY_ADAPTERS[level])
        for leak in ("e.g.", "for example", "such as", "like a "):
            self.assertNotIn(leak, SHOW_DONT_TELL.casefold())
            for level in CREATIVITY_ADAPTERS.values():
                self.assertNotIn(leak, level.casefold())

    def test_the_writing_temperature_follows_creativity(self):
        temperatures = [assemble_instruction(GoatedPrompterRequest(idea="a cat", creativity=level)).temperature
                        for level in ("Strict", "Balanced", "Creative", "Dice")]
        self.assertEqual(temperatures, sorted(temperatures))
        self.assertEqual(len(set(temperatures)), 4)

    def test_repairs_protect_facts_not_props_or_clothing(self):
        from goated_prompter.planning.semantic_validation import AUDIT_CONTRACT, repair_contract
        rule = json.loads(repair_contract({}, "", "x").split("\n", 3)[3])["repair_rule"]
        self.assertIn("Do not introduce subjects, actions or exclusions", rule)
        self.assertNotIn("props", rule + AUDIT_CONTRACT)

    def test_a_medium_mode_sets_the_style_only_when_the_style_is_auto(self):
        self.assertEqual(resolve_style("Auto", "Krea 2", "Photography"), "Realistic")
        self.assertEqual(resolve_style("Auto", "Krea 2", "Product"), "Product")
        self.assertEqual(resolve_style("Anime", "Krea 2", "Photography"), "Anime")
        self.assertEqual(resolve_style("Auto", "Anima", "Photography"), "Anime")
        self.assertIn("VISUAL STYLE — Realistic", message(mode="Photography", target_model="Krea 2"))

    def test_the_style_comes_after_the_library_templates(self):
        system = message(style="Anime", target_model="Krea 2", library_references=("A saved prompt.",))
        self.assertIn("Template 1:\nA saved prompt.", system)
        self.assertGreater(system.index("VISUAL STYLE"), system.index("TEMPLATES FROM THE USER'S PROMPT LIBRARY"))
        self.assertIn("follow Template 1", system)

    def test_unclosed_and_stray_brackets_are_removed(self):
        self.assertEqual(balance_brackets("[Subject: one.\n\n[Light: two.]"), "Subject: one.\n\n[Light: two.]")
        self.assertEqual(balance_brackets("a] b"), "a b")
        for kept in ("(tag:1.2), \\(series\\)", 'a sign reading "[OPEN" here', "plain (closed) [text]"):
            self.assertEqual(balance_brackets(kept), kept)


class OneDecisionOneOwner(unittest.TestCase):
    """Fixes from the ownership audit: each decision is made once and carried through every step and retry."""

    def test_renamed_primary_directors_still_keep_every_attribute_on_image_1(self):
        from goated_prompter.contracts import EncodedImage
        from goated_prompter.reference_map import resolve_reference_map
        first, second = EncodedImage("b25l", "image/png", 16, 16), EncodedImage("dHdv", "image/png", 16, 16)
        request = GoatedPrompterRequest(idea="a portrait", image=first, image_2=second)
        for name in ("Recreate a Reference Image", "Edit Only the Requested Details", "reverse_engineer"):
            sources = {item.source for item in resolve_reference_map(request, name).attributes}
            self.assertNotIn("Image 2", sources, name)
        self.assertIn("Image 2", {item.source for item in resolve_reference_map(request, "General").attributes})

    def test_off_style_adds_no_style_section_even_on_anima(self):
        from goated_prompter.options.styles import OFF_STYLE
        self.assertEqual(resolve_style(OFF_STYLE, "Anima"), OFF_STYLE)
        self.assertNotIn("VISUAL STYLE", message(style=OFF_STYLE, target_model="Anima"))

    def test_directors_never_set_the_writing_form_or_length(self):
        for preset in DIRECTOR_PRESETS:
            text = preset.instructions.casefold()
            for word in ("fluent visual prose", "keyword", "concise", "compact", "one-sentence", "return only"):
                self.assertNotIn(word, text, preset.label)

    def test_precedence_is_one_rule_not_a_ranked_list(self):
        from goated_prompter.prompting.base import TEXT_ONLY_PRIORITY_CONTRACT
        self.assertIn("decide the facts", TEXT_ONLY_PRIORITY_CONTRACT)
        self.assertNotIn("1. ", TEXT_ONLY_PRIORITY_CONTRACT)

    def test_a_target_layout_is_only_a_default_and_its_word_limit_caps_the_library(self):
        plain = message(target_model="FLUX.2 Klein")
        self.assertIn("in the order subject, action, style, context", plain)
        templated = message(target_model="FLUX.2 Klein", library_references=("A saved prompt.",))
        self.assertNotIn("in the order subject, action, style, context", templated, "Template 1 decides the structure.")
        self.assertIn("lead with the main subject and action", templated, "Model knowledge stays.")

    def test_qwen_edits_only_when_the_mode_is_an_edit(self):
        from goated_prompter.contracts import EncodedImage
        image = EncodedImage("b25l", "image/png", 16, 16)
        self.assertNotIn("image-editing rewrite", message(target_model="Qwen Image 2.1", image=image, mode="Enhance"))
        self.assertIn("image-editing rewrite", message(target_model="Qwen Image 2.1", image=image, mode="Image Edit"))

    def test_style_and_capture_add_no_scene_content(self):
        from goated_prompter.prompting.styles import CAPTURE_ADAPTERS, STYLE_ADAPTERS
        self.assertNotIn("clutter", CAPTURE_ADAPTERS["Phone snapshot"])
        self.assertNotIn("studio", STYLE_ADAPTERS["Product"])

    def test_a_remix_scenario_chosen_once_is_kept(self):
        request = GoatedPrompterRequest(idea="two friends", mode="Remix", target_model="Generic")
        system = assemble_instruction(request, scenario="A saved rooftop scenario.").system_message
        self.assertIn("SCENARIO TO RECAST (from the user's prompt library)" + chr(10) + "A saved rooftop scenario.", system)

    def test_any_style_trigger_turns_the_style_off_for_every_dataset_step(self):
        from goated_prompter.features.dataset.v2.draft import default_dataset_draft
        from goated_prompter.features.dataset.v2 import understanding
        from goated_prompter.features.dataset.v2.scenes import compose_message
        from goated_prompter.features.dataset.v2.triggers import run_style
        from goated_prompter.options.styles import OFF_STYLE
        for expand in ("off", "on", "both"):
            data = {**default_dataset_draft(), "subject": "a cat naps", "amount": 1, "target": "Anima", "style": "Painting",
                    "triggers": [{"text": "softstyle", "kind": "style", "expand": expand, "start": False}]}
            brief = understanding.apply_rules({"path": "non_character", "summary": "a cat naps", "fixed": "", "randomized": "",
                                               "must": [], "avoid": [], "characters": []}, data)
            self.assertEqual(run_style(brief), (OFF_STYLE, "Auto"), expand)
            self.assertNotIn('"style"', compose_message(brief, [{"image": 1}]))


if __name__ == "__main__":
    unittest.main()
