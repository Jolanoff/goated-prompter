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
from tests.support.backends import ScriptedBackend
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
        self.assertIn("never copy their wording, but keep every number they give.\n- the visual style of every image: chibi style", rule)
        self.assertNotIn("the app adds", rule)

    def test_a_meaning_note_is_rewritten_and_keeps_its_numbers(self):
        note = trigger("21 yo slim man, freckles", "character", expand="on")
        brief = brief_for("Krea 2", triggers=[note, trigger("chibi style", "style", expand="on")], cast=mara(1))
        copied, lost = (prompts.meaning_problem("Mara, 21 yo slim man, freckles, kneels.", brief),
                        prompts.meaning_problem("Mara, a slim 25-year-old man with freckles, kneels.", brief))
        self.assertIn("word for word", copied[0])
        self.assertFalse(copied[1], "Copied wording is kept after the retry.")
        self.assertIn("number 21", lost[0])
        self.assertTrue(lost[1], "A lost number is a wrong fact.")
        self.assertIsNone(prompts.meaning_problem("Mara, a slim 21-year-old man with freckles, in chibi style.", brief),
                          "Short notes may be written as they are.")

    def test_rules_say_what_exact_triggers_carry(self):
        triggers = [trigger("clo21", "character"), trigger("mystyle", "style"), trigger("dress_tok", "outfit"),
                    trigger("chibi style", "style", expand="both")]
        rule = prompts._trigger_rule(brief_for("Krea 2", triggers=triggers, cast=mara(1, 3)))
        self.assertIn('do not write them or a variant of them: "clo21"; "mystyle"; "dress_tok"; "chibi style".', rule)
        self.assertIn("Their texts already carry Mara's face, hair, eyes, skin and body; the visual style, medium and "
                      "rendering; Mara's outfit. Never describe these.", rule)
        self.assertIn("- the visual style of every image: chibi style", rule)

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
        self.assertEqual(brief["version"], 14)
        self.assertEqual(understanding.validate_brief(brief), brief)
        meaning = brief_for(triggers=[trigger("red-haired elf girl", "character", expand="on")], cast=mara(1))
        self.assertEqual([person["known"] for person in meaning["characters"]], [False])

    def test_scenes_hear_what_outfit_and_meaning_triggers_ask(self):
        brief = brief_for(triggers=[trigger("dress_tok", "outfit"), trigger("rainy city", expand="on"),
                                    trigger("mystyle", "style")], cast=mara(1))
        notes = scenes.trigger_notes(brief)
        self.assertEqual(len(notes), 1, "Outfits and style are the final prompt's concern; scenes have no clothing.")
        self.assertIn('"rainy city" applies to every image', notes[0])
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
        brief = {key: value for key, value in brief_for().items() if key != "kept"}
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
                "space": f"street {number}", "lighting": "noon", "mood": "warm", "camera": "wide shot", "extras": "stalls",
                "frame": {label: {"shows": "full body", "face": "visible"} for label in ("Naruto", "woman")}}

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
        self.assertIn("Naruto (known character): expression a grin\n", final.user_message)
        self.assertNotIn("clothing", final.user_message, "Clothing is chosen by the final prompt, not the scene.")
        self.assertNotIn("COMPILED", final.system_message, "a generated scene is never parsed as user rules")
        self.assertIn("the app adds these exact texts to the prompt itself", text)
        self.assertNotIn("VISUAL STYLE — Realistic", final.system_message, "a style trigger replaces the Style setting")
        self.assertEqual(written[0]["prompt"], f"masterpiece, safe, 1boy, 1girl, {NARUTO}, mystyle, full body, street"
                                               "\n\nNaruto talks with a woman.")
        self.assertTrue(written[0]["trigger_ok"])

    def test_exact_style_trigger_removes_prose_targets_medium_demands(self):
        for target, demands in (("Anima", ("environment and style tags",)),
                                ("Krea 2", ("State the medium in words", '"Aesthetic and style:"')),
                                ("FLUX.2 Klein", ("in the order subject, action, style, context",)),
                                ("Z-Image", ("Use one dominant style", "the style and medium")),
                                ("Qwen Image (original)", ("State the style precisely",)),
                                ("Qwen Image 2.1", ("Open by naming medium, style,",))):
            with self.subTest(target=target):
                self.calls.clear()
                self.brief["settings"]["target"] = target
                written = prompts.write_prompts({"backend": "mock"}, self.request, self.brief, [self.scene()],
                                                progress=lambda _: None)
                final = next(call for call in self.calls if call.diagnostic_stage == "final")
                adapter = final.system_message.split("TARGET MODEL ADAPTER\n", 1)[1].split("\n\nUSER SETTINGS", 1)[0]
                self.assertIn("the visual style, medium and rendering. Never describe these.", final.system_message)
                for demand in demands:
                    self.assertNotIn(demand, adapter)
                self.assertIn("mystyle", written[0]["prompt"])
                self.assertTrue(written[0]["trigger_ok"])

    def test_expanded_style_triggers_still_reach_the_final_writer(self):
        for expand in ("on", "both"):
            with self.subTest(expand=expand):
                self.calls.clear()
                self.brief["settings"]["target"] = "Krea 2"
                self.brief["input"]["triggers"][1] = trigger("chibi style", "style", expand=expand)
                prompts.write_prompts({"backend": "mock"}, self.request, self.brief, [self.scene()],
                                      progress=lambda _: None)
                final = next(call for call in self.calls if call.diagnostic_stage == "final")
                self.assertIn("- the visual style of every image: chibi style", final.system_message)
                self.assertNotIn("the visual style, medium and rendering. Never describe these.", final.system_message)
                self.assertIn("State the medium in words", final.system_message)

    def test_exact_style_trigger_ideogram_does_not_require_invented_style_fields(self):
        self.brief["settings"]["target"] = "Ideogram4"
        caption = {"high_level_description": "Naruto talks with a woman.",
                   "compositional_deconstruction": {"background": "A street in noon light.", "elements": [
                       {"type": "obj", "desc": "Naruto stands on the left, talking with the woman on the right."}]}}
        backend = ScriptedBackend([ideogram_json(caption)])
        with patch("goated_prompter.features.builder.service.create_backend", return_value=backend):
            written = prompts.write_prompts({"backend": "mock"}, self.request, self.brief, [self.scene()],
                                            progress=lambda _: None)
        system = backend.calls[0].system_message
        adapter = system.split("TARGET MODEL ADAPTER\n", 1)[1].split("\n\nUSER SETTINGS", 1)[0]
        self.assertNotIn('"style_description"', adapter)
        self.assertNotIn('"medium"', adapter)
        self.assertNotIn("style_description", system.rsplit("OUTPUT FORMAT", 1)[1])
        placed = json.loads(written[0]["prompt"])
        self.assertEqual(list(placed), ["high_level_description", "compositional_deconstruction"])
        self.assertEqual(placed["high_level_description"], "mystyle, Naruto talks with a woman.")
        self.assertEqual(written[0]["prompt"].count("mystyle"), 1)
        self.assertTrue(written[0]["trigger_ok"])
        self.assertEqual(len(backend.calls), 1)


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


class RolesShownNotTold(unittest.TestCase):
    """At Creative and Dice a role label is replaced by the person's look; the scene's signs carry the role."""

    brief = {"characters": [{"label": "servant", "gender": "male", "known": False, "triggers": []},
                            {"label": "ruler", "gender": "female", "known": False, "triggers": []}]}
    scene = {"subjects": {"servant": {"skin": "pale", "hair": "short dark hair"}, "ruler": {"skin": "tan", "hair": "long red hair"}}}

    def named(self, creativity, text):
        return prompts.name_people(text, {**self.brief, "settings": {"creativity": creativity}}, self.scene)

    def test_creative_and_dice_name_people_by_look(self):
        for level in ("Creative", "Dice"):
            self.assertEqual(self.named(level, "the ruler lifts her servant's chin"),
                             "the woman with tan skin lifts the man with pale skin's chin")

    def test_strict_and_balanced_keep_the_role(self):
        for level in ("Strict", "Balanced"):
            self.assertEqual(self.named(level, "the ruler lifts her servant's chin"), "the ruler lifts her servant's chin")

    def test_words_written_on_something_stay(self):
        self.assertEqual(self.named("Creative", 'a tag reading "servant" on the servant'),
                         'a tag reading "servant" on the man with pale skin')

    def test_people_who_share_a_look_are_told_apart_without_brackets_or_commas(self):
        brief = {"characters": [{"label": "guard", "gender": "male"}, {"label": "prisoner", "gender": "male"}],
                 "settings": {"creativity": "Creative"}}
        scene = {"subjects": {"guard": {"skin": "pale, freckled", "hair": "short, dark"},
                              "prisoner": {"skin": "pale, freckled", "hair": "long blond hair"}}}
        self.assertEqual(prompts.anchors(scene, brief),
                         {"guard": "the man with pale skin and short dark hair",
                          "prisoner": "the man with pale skin and long blond hair"})

    def test_named_known_or_triggered_people_keep_their_name(self):
        brief = {"characters": [{"label": "Mara", "gender": "female"}, {"label": "guard", "gender": "male", "triggers": [1]}],
                 "settings": {"creativity": "Dice"}}
        self.assertEqual(prompts.name_people("Mara passes the guard", brief, {"subjects": {}}), "Mara passes the guard")


class AnimaTagLine(unittest.TestCase):
    """The Dataset knows its cast, so the count tags come from it; the tag line is written in Anima's own format."""

    cast = {"characters": [{"label": "knight", "gender": "male"}, {"label": "queen", "gender": "female"}]}

    def test_count_tags_come_from_the_cast(self):
        line = prompts.anima_tag_line("score_9, masterpiece, 2girls, 1boy, solo, 2people, knight, throne room\n\nProse.", self.cast)
        self.assertEqual(line, "score_9, masterpiece, 1boy, 1girl, knight, throne room\n\nProse.")
        self.assertEqual(prompts.count_tags([{"gender": "male"}]), ["1boy", "solo"])
        self.assertEqual(prompts.count_tags([{"gender": "male", "count": 2}, {"gender": ""}]), ["2boys", "1other"])

    def test_a_phrase_or_placeholder_among_the_tags_still_gets_the_casts_count_tags(self):
        # A live tag line with one long phrase was read as prose and kept the model's "2men, solo".
        line = prompts.anima_tag_line("masterpiece, 2boys, solo, [knight in silver armor], the knight holding the queen's hand "
                                      "in front of the old stone throne, throne room, kneeling, candles, banners, "
                                      "night\n\nProse.", self.cast)
        self.assertEqual(line, "masterpiece, 1boy, 1girl, throne room, kneeling, candles, banners, night\n\nProse.")

    def test_a_tag_beside_its_opposite_goes_with_it(self):
        # Each describes one person; a tag line cannot say whose.
        line = prompts.anima_tag_line("masterpiece, tired, kneeling, untired, armored, unarmored, throne room\n\nProse.",
                                      self.cast)
        self.assertEqual(line, "masterpiece, 1boy, 1girl, kneeling, throne room\n\nProse.")

    def test_underscores_become_spaces_except_score_tags_and_low_quality_tags_go(self):
        line = prompts.anima_tag_line("score_8_up, low_quality, worst quality, lowres, knight_is_kneeling, \\(armor\\)\n\nA_b.",
                                      self.cast)
        self.assertEqual(line, "score_8_up, 1boy, 1girl, knight is kneeling, \\(armor\\)\n\nA_b.")

    def test_quality_then_one_safety_tag_then_counts_and_no_invented_score_or_solo_tags(self):
        line = prompts.anima_tag_line("1boy, rating: explicit, score_7_sub, score_9_of_9, solo man, solo focus, safe, "
                                      "kneeling, masterpiece, score_9\n\nProse.", self.cast)
        # With two people "solo focus" goes: a model adds it and the image then drops one of them.
        self.assertEqual(line, "masterpiece, score_9, explicit, 1boy, 1girl, kneeling\n\nProse.")

    def test_the_scenes_widest_frame_is_the_one_framing_tag(self):
        scene = {"frame": {"knight": {"shows": "head to knees", "face": "visible"},
                           "lady": {"shows": "head to hips", "face": "visible"}}}
        line = prompts.anima_tag_line("masterpiece, upper body, close-up, kneeling\n\nProse.", self.cast, scene)
        self.assertEqual(line, "masterpiece, 1boy, 1girl, cowboy shot, kneeling\n\nProse.")
        self.assertEqual(prompts.anima_tag_line("masterpiece, upper body\n\nProse.", self.cast),
                         "masterpiece, 1boy, 1girl, upper body\n\nProse.", "a scene without frames keeps the model's tag")

    def test_exact_trigger_text_replaces_every_form_of_its_tags(self):
        # Live runs kept "cu chulainn", "fate" and invented "fate \(fate_series\)" and "fate \(fate \(series\)\)"
        # beside the exact trigger text.
        triggers = [{"text": "uchiha madara, naruto \\(series\\)", "kind": "character", "expand": "off", "start": False},
                    {"text": "cu chulainn \\(fate\\), fate \\(series\\)", "kind": "character", "expand": "off", "start": False}]
        prompt = ("masterpiece, 2boys, cu chulainn, fate \\(fate\\_series\\), fate \\(fate \\(series\\)\\), fate, Uchiha_Madara, naked\n\nProse.")
        line = prompts._anima_with_triggers(prompt, triggers)
        self.assertEqual(line, "masterpiece, 2boys, uchiha madara, naruto \\(series\\), cu chulainn \\(fate\\), "
                               "fate \\(series\\), naked\n\nProse.")

    def test_the_apps_own_names_for_people_are_never_tags(self):
        # Live tag lines kept "the man with pale skin" and "man with olive skin", the prompt's own names for people.
        brief = {"characters": [{"label": "man 1", "gender": "male"}, {"label": "man 2", "gender": "male"}],
                 "settings": {"creativity": "Balanced"}, "fixed": {}}
        scene = {"subjects": {"man 1": {"skin": "pale", "hair": "black"}, "man 2": {"skin": "olive", "hair": "red"}}}
        line = prompts.anima_tag_line("masterpiece, the man with pale skin, man with olive skin, 4males, kneeling"
                                      "\n\nprose.", brief, scene)
        self.assertEqual(line, "masterpiece, 2boys, kneeling\n\nProse.")
        # A live tag line led each person's tags with their name: "the man with pale skin: pale skin, ...".
        line = prompts.anima_tag_line("masterpiece, the man with pale skin: pale skin, slender, man with olive skin: "
                                      "olive skin\n\nhe kneels. she waits? yes.", brief, scene)
        self.assertEqual(line, "masterpiece, 2boys, pale skin, slender, olive skin\n\nHe kneels. She waits? Yes.")

    def test_the_nsfw_switch_off_makes_the_safety_tag_safe(self):
        # A live rainy-city couple with NSFW off was tagged "sensitive".
        brief = {**self.cast, "input": {"nsfw": False}}
        self.assertEqual(prompts.anima_tag_line("masterpiece, sensitive, walking\n\nProse.", brief),
                         "masterpiece, safe, 1boy, 1girl, walking\n\nProse.")
        self.assertEqual(prompts.anima_tag_line("masterpiece, explicit, walking\n\nProse.",
                                                {**self.cast, "input": {"nsfw": True}}),
                         "masterpiece, explicit, 1boy, 1girl, walking\n\nProse.", "with NSFW on the model's rating stays")

    def test_brackets_around_the_apps_names_and_over_several_tags_go(self):
        # A live prose wrapped every person in brackets ("[the man with tan skin] lies"), which weighs them on Anima, and
        # a tag line bracketed one person's tags as a group.
        brief = {"characters": [{"label": "man 1", "gender": "male"}, {"label": "man 2", "gender": "male"}],
                 "settings": {"creativity": "Balanced"}, "fixed": {}}
        scene = {"subjects": {"man 1": {"skin": "tan", "hair": "black"}, "man 2": {"skin": "pale", "hair": "red"}}}
        self.assertEqual(prompts.plain_names("[the man with tan skin] lies down. Then [the man with pale skin] kneels "
                                             "beside [the man with tan skin].", brief, scene),
                         "The man with tan skin lies down. Then the man with pale skin kneels beside the man with tan skin.")
        self.assertEqual(prompts.anima_tag_line("masterpiece, [pale skin, slender, walking], [tan skin, beard]\n\nProse.",
                                                self.cast),
                         "masterpiece, 1boy, 1girl, pale skin, slender, walking, tan skin, beard\n\nProse.")

    def test_a_person_of_open_gender_is_counted_as_the_scene_writes_them(self):
        # A rainy-city couple of unnamed genders was tagged "2others" while every prose wrote a woman and a man.
        couple = {"characters": [{"label": "person 1"}, {"label": "person 2"}]}
        scene = {"position": {"person 1": "left, her hand in person 2's hand", "person 2": "right, his hand in person 1's"}}
        self.assertEqual(prompts.anima_tag_line("masterpiece, 2others, walking\n\nProse.", couple, scene),
                         "masterpiece, 1boy, 1girl, walking\n\nProse.")
        self.assertEqual(prompts.anima_tag_line("masterpiece, walking\n\nProse.", couple), "masterpiece, 2others, walking"
                         "\n\nProse.", "without a scene nothing says who they are")

    def test_a_scene_that_shows_genitals_is_rated_explicit_with_nsfw_on(self):
        # Live tag lines rated sex scenes "sensitive".
        brief = {**self.cast, "input": {"nsfw": True}}
        scene = {"actions": "the knight's penis in the queen's mouth", "position": {}}
        self.assertEqual(prompts.anima_tag_line("masterpiece, sensitive, kneeling\n\nProse.", brief, scene),
                         "masterpiece, explicit, 1boy, 1girl, kneeling\n\nProse.")
        scene = {"actions": "the knight kisses the queen", "position": {}}
        self.assertEqual(prompts.anima_tag_line("masterpiece, sensitive, kneeling\n\nProse.", brief, scene),
                         "masterpiece, sensitive, 1boy, 1girl, kneeling\n\nProse.", "nothing explicit shown: it stays")

    def test_tag_blocks_split_by_blank_lines_become_one_line(self):
        line = prompts.anima_tag_line("masterpiece, 1boy\n\nkneeling, collar,\n\nA knight kneels. He waits.", self.cast)
        self.assertEqual(line, "masterpiece, 1boy, 1girl, kneeling, collar\n\nA knight kneels. He waits.")

    def test_a_prompt_without_a_tag_line_is_left_alone(self):
        self.assertEqual(prompts.anima_tag_line("A knight kneels.", self.cast), "A knight kneels.")


if __name__ == "__main__":
    unittest.main()
