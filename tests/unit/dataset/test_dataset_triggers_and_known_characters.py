"""The user's trigger list: each trigger says what it stands for and whether code places its exact text, the model
writes its meaning, or both. Code places exact texts in every target format, characters a trigger covers keep the
look it carries, and ordinary words never trip the adult-content checks. Scripted models only: this checks what is
asked and what code does with an answer, not how a live model writes."""

import json
import unittest
from unittest.mock import patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import prompts, scenes, understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft, validate_dataset_draft
from goated_prompter.features.dataset.v2.safety import adults_only_error, minor_reference
from goated_prompter.workflow_output import ideogram_json
from tests.helpers import enter_context
from tests.support.dataset_scenes import composer_user

NARUTO = "uzumaki naruto, naruto \\(series\\)"
HINATA = "hyuuga hinata, naruto \\(series\\)"
PAIR = [{"label": "Naruto", "gender": "male", "custom": "", "pronoun": "he", "count": 1, "triggers": [1]},
        {"label": "Hinata", "gender": "female", "custom": "", "pronoun": "she", "count": 1, "triggers": [2]}]


def mara(*triggers):
    return [{"label": "Mara", "gender": "female", "custom": "", "pronoun": "she", "count": 1, "triggers": list(triggers)}]


def trigger(text, kind="other", expand="off", start=False):
    return {"text": text, "kind": kind, "expand": expand, "start": start}


PAIR_TRIGGERS = [trigger(NARUTO, "character"), trigger(HINATA, "character")]


def brief_for(target="Anima", triggers=PAIR_TRIGGERS, cast=PAIR, **data):
    values = {**default_dataset_draft(), "subject": "Naruto and Hinata kiss", "amount": 1, "seed": 4,
              "seed_mode": "fixed", "triggers": triggers, "target": target, **data}
    value = {"path": "character", "summary": values["subject"], "fixed": "", "randomized": "", "must": [], "avoid": [],
             "characters": cast}
    return understanding.apply_rules(value, values)


class TriggerPlacement(unittest.TestCase):
    def test_anima_character_tags_take_the_users_exact_form_once(self):
        brief = brief_for()
        written = ("masterpiece, best quality, explicit, 1boy, 1girl, uzumaki_naruto, naruto (series), Hyuuga Hinata, "
                   "kiss, bedroom\n\nNaruto kisses Hinata by the window.")
        placed = prompts.place_triggers(written, brief)
        self.assertEqual(placed, f"masterpiece, best quality, explicit, 1boy, 1girl, {NARUTO}, {HINATA}, kiss, bedroom"
                                 "\n\nNaruto kisses Hinata by the window.")
        self.assertIsNone(prompts.trigger_problem(placed, brief))

    def test_anima_follows_its_section_order_and_pinned_triggers_lead(self):
        triggers = [trigger("sword_tok", "object"), trigger("clo21", "character"), trigger("mystyle", "style", start=True)]
        brief = brief_for(triggers=triggers, cast=mara(2))
        written = "score_9, explicit, 1girl, kneeling, bedroom\n\nMara kneels."
        self.assertEqual(prompts.place_triggers(written, brief),
                         "mystyle, score_9, explicit, 1girl, clo21, kneeling, bedroom, sword_tok\n\nMara kneels.")
        prose = "Mara kneels in a bedroom. Soft light falls on her."
        self.assertEqual(prompts.place_triggers(prose, brief), "mystyle, sword_tok, clo21\n\n" + prose)

    def test_prose_puts_a_character_trigger_at_its_first_mention(self):
        triggers = [trigger("clo21", "character"), trigger("mystyle", "style"), trigger("ohwx", start=True)]
        brief = brief_for("Krea 2", triggers=triggers, cast=mara(1))
        placed = prompts.place_triggers("A dim room. Mara kneels by the window; Mara smiles.", brief)
        self.assertEqual(placed, "ohwx, mystyle, A dim room. clo21 Mara kneels by the window; Mara smiles.")
        self.assertIsNone(prompts.trigger_problem(placed, brief))
        self.assertEqual(prompts.place_triggers("A woman kneels.", brief), "ohwx, clo21, mystyle, A woman kneels.")
        self.assertIsNotNone(prompts.trigger_problem("mystyle, ohwx, clo21 Mara kneels.", brief), "pinned goes first")

    def test_a_role_noun_or_numbered_person_gets_the_trigger_at_its_mention(self):
        woman = [{"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1, "triggers": [1]},
                 {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        brief = brief_for("Krea 2", triggers=[trigger("clo21", "character")], cast=woman)
        self.assertEqual(prompts.place_triggers("A man holds the woman close.", brief), "A man holds the clo21 woman close.")
        men = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1, "triggers": [1]},
               {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}]
        brief = brief_for("Krea 2", triggers=[trigger("clo21", "character")], cast=men)
        self.assertEqual(brief["characters"][0]["label"], "man 1")
        self.assertEqual(prompts.place_triggers("The first man kneels behind the second man.", brief),
                         "The clo21 first man kneels behind the second man.")

    def test_ideogram_puts_each_trigger_where_it_belongs(self):
        triggers = [trigger("clo21", "character"), trigger("mystyle", "style"), trigger("ohwx", start=True)]
        caption = {"high_level_description": "A woman kneels.",
                   "style_description": {"aesthetics": "Moody", "lighting": "Lamp", "photo": "35mm", "medium": "Photograph"},
                   "compositional_deconstruction": {"background": "A bedroom", "elements": [
                       {"type": "obj", "desc": "A lamp"}, {"type": "obj", "desc": "Mara kneels on the rug."}]}}
        brief = brief_for("Ideogram4", triggers=triggers, cast=mara(1))
        placed = json.loads(prompts.place_triggers(ideogram_json(caption), brief))
        self.assertEqual(placed["high_level_description"], "ohwx, A woman kneels.")
        self.assertEqual(placed["style_description"]["aesthetics"], "mystyle, Moody")
        self.assertEqual(placed["compositional_deconstruction"]["elements"][1]["desc"], "clo21, Mara kneels on the rug.")
        self.assertIsNone(prompts.trigger_problem(ideogram_json(placed), brief))

    def test_meaning_only_triggers_are_written_by_the_model_not_placed(self):
        brief = brief_for("Krea 2", triggers=[trigger("chibi style", "style", expand="on")], cast=mara())
        self.assertEqual(prompts.place_triggers("Mara kneels.", brief), "Mara kneels.")
        self.assertIsNone(prompts.trigger_problem("Mara kneels.", brief))
        rule = prompts._trigger_rule(brief)
        self.assertIn('Express in every prompt, in your own words: "chibi style" (the visual style of every image)', rule)
        self.assertNotIn("the app adds", rule)

    def test_rules_say_what_exact_triggers_carry(self):
        triggers = [trigger("clo21", "character"), trigger("mystyle", "style"), trigger("dress_tok", "outfit"),
                    trigger("chibi style", "style", expand="both")]
        rule = prompts._trigger_rule(brief_for("Krea 2", triggers=triggers, cast=mara(1, 3)))
        self.assertIn('do not write them or a variant of them: "clo21"; "mystyle"; "dress_tok"; "chibi style".', rule)
        self.assertIn("Their texts already carry Mara's face, hair, eyes, skin and body; the visual style, medium and "
                      "rendering; Mara's outfit. Never describe these.", rule)
        self.assertIn('"chibi style" (the visual style of every image)', rule)

    def test_no_trigger_changes_nothing(self):
        self.assertEqual(prompts.place_triggers("A woman reads.", brief_for("Krea 2", triggers=[], cast=mara())), "A woman reads.")


class TriggerDrafts(unittest.TestCase):
    def test_an_older_single_trigger_becomes_one_exact_trigger(self):
        draft = validate_dataset_draft({"trigger": " ohwx ", "trigger_at_start": True, "trigger_connected": False})
        self.assertEqual(draft["triggers"], [trigger("ohwx", start=True)])
        self.assertNotIn("trigger", draft)

    def test_a_saved_name_field_is_dropped(self):
        draft = validate_dataset_draft({"triggers": [{**trigger("clo21", "character"), "name": "Mara"}]})
        self.assertEqual(draft["triggers"], [trigger("clo21", "character")])

    def test_every_trigger_row_is_checked_before_a_run(self):
        base = {**default_dataset_draft(), "subject": "x"}
        self.assertEqual(validate_dataset_draft({**base, "triggers": [trigger("")]})["triggers"], [trigger("")],
                         "an empty row may be saved while editing")
        for triggers, message in (([trigger("")], "is empty"), ([trigger("a")] * 21, "at most 20"),
                                  ([trigger("a", "pose")], "unknown type"), ([{"text": "a"}], "needs exactly")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_dataset_draft({**base, "triggers": triggers}, generation=True)


class TriggerCast(unittest.TestCase):
    TRIGGERS = [trigger("clo21", "character"), trigger("dress_tok", "outfit"), trigger("chibi style", "style", expand="on")]

    def answer(self, *characters):
        return {"path": "character", "summary": "s", "fixed": "", "randomized": "", "must": [], "avoid": [],
                "characters": list(characters)}

    def test_understanding_links_every_character_and_outfit_trigger_to_one_person(self):
        data = {**default_dataset_draft(), "subject": "a woman kisses a man", "triggers": self.TRIGGERS}
        user = json.loads(understanding.instruction(data).user_message)
        self.assertEqual(user["triggers"][0], {"number": 1, "text": "clo21", "type": "character"})
        woman = {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}
        man = {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}
        errors = " ".join(understanding.model_errors(self.answer(woman, man), False, data))
        self.assertIn('Trigger 1 ("clo21", character) must belong to exactly one character', errors)
        self.assertIn('Trigger 2 ("dress_tok", outfit)', errors)
        self.assertNotIn("Trigger 3", errors, "a style trigger belongs to no one")
        self.assertEqual(understanding.model_errors(self.answer({**woman, "triggers": [1, 2]}, man), False, data), [])
        for wrong in (self.answer({**woman, "triggers": [1, 2]}, {**man, "triggers": [2]}),
                      self.answer({**woman, "triggers": [1, 3]}, man), self.answer({**woman, "count": 2, "triggers": [1, 2]})):
            with self.subTest(wrong=wrong):
                self.assertTrue(understanding.model_errors(wrong, False, data))

    def test_an_exact_character_trigger_makes_its_person_known_and_a_meaning_one_does_not(self):
        brief = brief_for()
        self.assertEqual([(person["known"], person["triggers"]) for person in brief["characters"]], [(True, [1]), (True, [2])])
        self.assertEqual(brief["version"], 13)
        self.assertEqual(understanding.validate_brief(brief), brief)
        meaning = brief_for(triggers=[trigger("red-haired elf girl", "character", expand="on")], cast=mara(1))
        self.assertEqual([person["known"] for person in meaning["characters"]], [False])

    def test_scenes_hear_what_outfit_and_meaning_triggers_ask(self):
        brief = brief_for(triggers=[trigger("dress_tok", "outfit"), trigger("rainy city", expand="on"),
                                    trigger("mystyle", "style")], cast=mara(1))
        notes = scenes.trigger_notes(brief)
        self.assertEqual(len(notes), 2)
        self.assertIn("Mara's outfit comes from a trigger", notes[0])
        self.assertIn('"rainy city" applies to every image', notes[1])
        message = scenes.compose_message({**brief, "_family": "qwen"}, [{"image": 1}])
        self.assertEqual(composer_user(message)["triggers"], notes)


class Labels(unittest.TestCase):
    def test_an_article_before_a_label_is_not_doubled(self):
        brief = {"characters": [{"label": "man 1"}, {"label": "man 2"}]}
        self.assertEqual(prompts.unlabel("The man 1 kneels behind man 2.", brief), "the first man kneels behind the second man.")

    def test_a_measurement_is_not_a_label(self):
        brief = {"characters": [{"label": "man 1"}]}
        for text in ("a man 1 meter away", "a man 1 m away"):
            self.assertIsNone(prompts.label_problem(text, brief), text)
        self.assertIsNotNone(prompts.label_problem("man 1 stands", brief))


class KnownCharacters(unittest.TestCase):
    def test_role_nouns_and_original_names_are_not_known_without_the_model_saying_so(self):
        brief = brief_for(triggers=[trigger("ohwx woman")], cast=[{"label": "woman", "gender": "female", "custom": "",
                                                                  "pronoun": "she", "count": 1}])
        self.assertEqual(brief["characters"][0]["triggers"], [])
        self.assertEqual([person["known"] for person in brief["characters"]], [False])
        named = brief_for(triggers=[], cast=[{**PAIR[0], "known": True, "triggers": []}, {**PAIR[1], "triggers": []}])
        self.assertEqual([person["known"] for person in named["characters"]], [True, False])

    def test_older_briefs_stay_valid_and_keep_their_single_trigger(self):
        brief = brief_for()
        brief["version"] = 11
        for person in brief["characters"]:
            del person["known"], person["triggers"]
        brief["input"] = {key: value for key, value in brief["input"].items() if key != "triggers"}
        brief["input"].update(trigger="ohwx", trigger_at_start=True)
        self.assertEqual(understanding.validate_brief(brief), brief)
        self.assertEqual(prompts.place_triggers("A woman reads.", {**brief, "settings": {**brief["settings"], "target": "Krea 2"}}),
                         "ohwx, A woman reads.")
        with self.assertRaises(ValueError):
            understanding.validate_brief({**brief, "version": 12})

    def test_the_model_answer_may_carry_known_and_nothing_else_new(self):
        value = {"path": "character", "summary": "s", "fixed": "", "randomized": "", "must": [], "avoid": [],
                 "characters": [{**PAIR[0], "known": True}]}
        self.assertEqual(understanding.model_errors(value, False), [])
        self.assertTrue(understanding.model_errors({**value, "characters": [{**PAIR[0], "known": "yes"}]}, False))
        self.assertTrue(understanding.model_errors({**value, "characters": [{**PAIR[0], "famous": True}]}, False))
        schema = understanding.instruction({"subject": "x"}).json_schema
        self.assertIn("known", schema["properties"]["characters"]["items"]["properties"])


class KnownCharacterScenes(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.backend = MockBackend()
        enter_context(self, patch.object(self.backend, "generate", side_effect=self.generate))
        enter_context(self, patch.object(scenes, "create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.create_backend", return_value=self.backend))
        enter_context(self, patch("goated_prompter.features.builder.service.pick_references", return_value=()))
        self.request = GoatedPrompterRequest(idea="dataset", planning_mode="Direct", director_preset="general_director")
        self.brief = brief_for(cast=[PAIR[0], {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}],
                               triggers=[trigger(NARUTO, "character"), trigger("mystyle", "style")],
                               style="Realistic")

    @staticmethod
    def scene(number=1):
        return {"subjects": {"Naruto": {"expression": "a grin", "clothing": "his orange jumpsuit"},
                             "woman": {field: f"her {field}" for field in scenes.SUBJECT_FIELDS}},
                "position": {"Naruto": "standing left", "woman": "standing right"}, "actions": "they talk",
                "space": f"street {number}", "lighting": "noon", "mood": "warm", "camera": "wide shot", "extras": "stalls"}

    def generate(self, instruction):
        self.calls.append(instruction)
        if instruction.diagnostic_stage == "dataset_v2:scenes":
            rows = composer_user(instruction.user_message)["images"]
            return json.dumps({"scenes": [self.scene(row["image"]) for row in rows]})
        return "masterpiece, safe, 1boy, 1girl, street\n\nNaruto talks with a woman."

    def test_a_known_character_gets_only_expression_and_clothing(self):
        result = scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)
        self.assertTrue(result["complete"], result["missing"])
        call = self.calls[0]
        subjects = call.json_schema["properties"]["scenes"]["items"]["properties"]["subjects"]["properties"]
        self.assertEqual(subjects["Naruto"]["required"], list(scenes.KNOWN_SUBJECT_FIELDS))
        self.assertEqual(subjects["woman"]["required"], list(scenes.SUBJECT_FIELDS))
        self.assertIn('"known": true is an established character', call.system_message)
        self.assertEqual(set(result["scenes"][0]["subjects"]["Naruto"]), set(scenes.KNOWN_SUBJECT_FIELDS))
        # A known character with invented looks is the wrong shape, as is an unknown one without them.
        bad = self.scene()
        bad["subjects"]["woman"] = {"expression": "calm", "clothing": "a coat"}
        self.assertTrue(scenes.scene_errors(bad, ["Naruto", "woman"], [], known=frozenset({"Naruto"})))
        self.assertEqual(scenes.scene_errors(self.scene(), ["Naruto", "woman"], [], known=frozenset({"Naruto"})), [])

    def test_the_builder_names_the_character_and_code_places_the_triggers(self):
        result = scenes.write_scenes({"backend": "mock"}, self.request, self.brief, progress=lambda _: None)
        written = prompts.write_prompts({"backend": "mock"}, self.request, self.brief, result["scenes"], progress=lambda _: None)
        final = [call for call in self.calls if call.diagnostic_stage == "final"][0]
        text = final.system_message + final.user_message
        self.assertIn("KNOWN CHARACTERS: Naruto is an established character the target model already knows", text)
        self.assertIn("Naruto (known character): expression a grin; clothing his orange jumpsuit", final.user_message)
        self.assertNotIn("COMPILED", final.system_message, "a generated scene is never parsed as user rules")
        self.assertIn("the app adds these exact texts to the prompt itself", text)
        self.assertNotIn("VISUAL STYLE — Realistic", final.system_message, "a style trigger replaces the Style setting")
        self.assertEqual(written[0]["prompt"], f"masterpiece, safe, 1boy, 1girl, {NARUTO}, mystyle, street"
                                               "\n\nNaruto talks with a woman.")
        self.assertTrue(written[0]["trigger_ok"])


class EverydayWords(unittest.TestCase):
    def check(self, subject, **data):
        return adults_only_error({"subject": subject, "director_preset": "general_director", **data}, include_director=False)

    def test_ordinary_requests_are_not_treated_as_adult_content(self):
        for subject in ("A kid in a collared shirt at school", "A child walking a dog on a leash",
                        "A teen with kinky hair", "A cum laude graduation, teens cheering"):
            with self.subTest(subject=subject):
                self.assertIsNone(self.check(subject))
        self.assertIsNone(self.check("A dog on a leash in the park", trigger_type="Animal"))
        self.assertIsNone(minor_reference("baby oil and kid gloves on the table"))

    def test_sexual_requests_with_a_minor_or_an_animal_are_still_refused(self):
        for subject in ("A collared submissive teen", "A teen on a leash", "Explicit sex with a schoolgirl",
                        "A 16 year old in lingerie"):
            with self.subTest(subject=subject):
                self.assertIsNotNone(self.check(subject))
        self.assertIsNotNone(self.check("A leashed woman in bdsm gear", trigger_type="Animal"))


if __name__ == "__main__":
    unittest.main()
